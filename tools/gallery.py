#!/usr/bin/env python3
"""Diktatūra — pilna nuotraukų galerija (docs/img/*.png) iš IŠGALVOTŲ demo duomenų. Paleidžia tools/screenshots.sh
(broadway — tavo ekrane nieko neatsiranda; DIKTATURA_* nukreipti į laikiną katalogą).

Nuotraukos: text, text-clean, text-search, text-menu, text-source, training, settings, settings-search, settings-sources,
progress, pill-rec, pill-after, theme-dark, theme-contrast, theme-compact. Visi vardai ir tekstai — išgalvoti.
"""
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

if not os.environ.get("DIKTATURA_DATA"):
    sys.exit("Nurodyk DIKTATURA_DATA=<laikinas katalogas> — tikrų duomenų neliečiam.")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from diktatura import config, paths, progress, sources, waveform  # noqa: E402
from diktatura.ui import gtk  # noqa: E402
from diktatura.ui.app import MainWindow  # noqa: E402
from diktatura.ui.gtk import Gdk, Gtk  # noqa: E402

OUT = REPO / "docs" / "img"
WIN = (920, 700)


def shot(widget_win, name, overlay=None, at=(0, 0)):
    """Nuotrauka; overlay — iššokęs meniu (atskiras langas) uždedamas ant pagrindinio ties at (lango koordinatės)."""
    gtk.pump(0.4)
    w = widget_win.get_window()
    pb = Gdk.pixbuf_get_from_window(w, 0, 0, w.get_width(), w.get_height())
    if overlay is not None:
        ow = overlay.get_window()
        opb = Gdk.pixbuf_get_from_window(ow, 0, 0, ow.get_width(), ow.get_height())
        dx, dy = max(0, at[0]), max(0, at[1])
        cw, ch = min(opb.get_width(), pb.get_width() - dx), min(opb.get_height(), pb.get_height() - dy)
        if cw > 0 and ch > 0:
            opb.copy_area(0, 0, cw, ch, pb, dx, dy)
    pb.savev(str(OUT / f"{name}.png"), "png", [], [])
    print(f"✓ docs/img/{name}.png")


def new_window(theme="light"):
    config.save({"THEME": theme})
    w = MainWindow(auto_refresh=False)
    w.set_default_size(*WIN)
    w.show_all()
    gtk.pump(0.3)
    return w


def demo_source():
    """Sekamas aplankas „Telefonas" su dviem tekstais (garsas — išgalvoti tušti failai)."""
    d = Path.home() / "Telefonas"                 # screenshots.sh HOME nukreipia į laikiną katalogą
    d.mkdir(exist_ok=True)
    src = sources.add("Telefonas", d)
    now = datetime.now()
    rows = [("Voice 2026-10-14 08.12.30.m4a", now - timedelta(days=1, hours=5), [
        ("Tu", "Pastaba sau: paskambinti Rūtai dėl sutarties ir paprašyti naujo pasiūlymo."),
        ("Tu", "Dar — nupirkti kavos."),
    ]), ("Voice 2026-10-15 17.40.02.m4a", now - timedelta(hours=2), [
        ("Rūta", "Labas, skambinu dėl sutarties — pasiūlymą atsiųsiu rytoj."),
        ("Tu", "Puiku, tada peržiūrėsiu ir parašysiu."),
        ("Darius", "Aš irgi klausau — reikės ir mano parašo."),
    ])]
    for name, when, lines in rows:
        audio = d / name
        audio.write_bytes(b"\0" * 100)
        base = sources.out_base(src, audio)
        base.parent.mkdir(parents=True, exist_ok=True)
        t, out, spans = 2, [], []
        for who, text in lines:
            out.append(f"[{timedelta(seconds=t)}] {who}: {text}")
            dur = 4 + len(text) // 12
            spans.append((t + 0.3, t + dur - 0.5, 0 if who == "Tu" else 1))
            t += dur
        sources.with_suffix(base, ".named.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
        sources.with_suffix(base, ".src.json").write_text(
            '{"audio": "%s", "recorded": "%s", "source": "telefonas"}' % (audio, when.isoformat(timespec="seconds")),
            encoding="utf-8")
        from demo_data import fake_peaks
        fake_peaks(sources.with_suffix(base, ".peaks"), spans, t + 3, 7)
    (d / "Voice 2026-10-16 09.01.11.m4a").write_bytes(b"\0" * 100)      # laukia transkripcijos
    t0 = time.time() - 3600
    os.utime(d / "Voice 2026-10-16 09.01.11.m4a", (t0, t0))


def fake_snapshot():
    """⏳ eiga: 1:52:30 įrašas 43 %, eilėje dar du."""
    rnd = random.Random(3)
    data = bytearray()
    for i in range(6750 * 10):
        t = i / 10
        for ch in (0, 1):
            on = (int(t / 40) + ch) % 3 == 0
            data.append(int(150 + 60 * abs(math.sin(t * 2.3 + ch)) + rnd.uniform(-25, 25)) if on
                        else int(rnd.uniform(50, 70)))
    pf = paths.RECORDINGS / "slack_20261016_101456.peaks"
    waveform.write(pf, waveform.Peaks(10, 2, bytes(data)))
    now = time.time()
    run = progress.Job(pid=11, file=paths.RECORDINGS / "slack_20261016_101456.wav", state="running", start=now - 3725,
                       phase="asr_them", audio_sec=6750, left=4875, total=8600,
                       info={"phases": list(progress.NAMED_PHASES), "phase": "asr_them", "done": 1830, "total": 6750,
                             "kind": "named", "pos": 2900.0, "skip": [False, False]})
    q = [progress.Job(pid=12, file=Path("/x/vox_20261016_121811.wav"), state="queued", audio_sec=95, left=190, total=190),
         progress.Job(pid=0, file=Path("/x/Voice 2026-10-16 09.01.11.m4a"), state="pending", audio_sec=1820, left=3100,
                      total=3100)]
    return progress.Snapshot(now=now, running=run, queued=q, slow=1.3, rates=dict(progress.DEFAULTS, n=38),
                             batch_start=now - 4000, batch_done=2)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO / "tools"))
    demo_source()

    # ── Tekstas ──
    w = new_window()
    t = w.text
    t.cmb_period.set_active_id("7")
    shot(w, "text")
    t.btn_clean.set_active(True)
    shot(w, "text-clean")
    t.btn_clean.set_active(False)
    t.search.set_text("migracij")
    t.highlight_all()
    t.goto_match(1)
    shot(w, "text-search")
    t.search.set_text("")
    t.highlight_all()
    # kontekstinis meniu: tikras Gtk.Menu — atskiras langas (nuotraukoje nesimato), todėl jo punktai — Popover'yje
    ln = next(x for x in t.visible_lines() if x.speaker == "Kolega?nez1")
    r = t.line_range(ln)
    t.tv.scroll_to_iter(r[0], 0.3, False, 0, 0)
    gtk.pump(0.2)
    rect = t.tv.get_iter_location(r[0])
    x, y = t.tv.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, rect.x, rect.y)
    pop = Gtk.Popover.new(t.tv)
    pop.set_position(Gtk.PositionType.BOTTOM)
    anchor = Gdk.Rectangle()
    anchor.x, anchor.y, anchor.width, anchor.height = x + 260, y, 1, rect.height
    pop.set_pointing_to(anchor)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    for it in t.menu_items(ln):
        if isinstance(it, Gtk.SeparatorMenuItem):
            box.pack_start(Gtk.Separator(), False, False, 2)
            continue
        mb = Gtk.ModelButton(text=it.get_label())
        mb.set_sensitive(it.get_sensitive())
        box.pack_start(mb, False, False, 0)
    box.set_margin_top(6)
    box.set_margin_bottom(6)
    pop.add(box)
    pop.show_all()
    shot(w, "text-menu")
    pop.popdown()
    pop.destroy()
    w.text_tabs.show_source("telefonas")
    shot(w, "text-source")

    # ── Apmokymai, Nustatymai ──
    w.show_page("training")
    shot(w, "training")
    w.show_page("settings")
    shot(w, "settings")
    w.settings.search.set_text("tyl")
    w.settings.apply_search()
    shot(w, "settings-search")
    w.settings.search.set_text("")
    w.settings.apply_search()
    sw = w.settings.sw.get_vadjustment()
    fr = next(fr for fr, tl, _ in w.settings.frames if tl.get_text() == "Sekami aplankai")
    gtk.pump(0.1)
    sw.set_value(fr.get_allocation().y - 20)
    shot(w, "settings-sources")

    # ── ⏳ eiga ──
    from diktatura.ui.progress_dialog import ProgressDialog
    snap = fake_snapshot()
    d = ProgressDialog(w, snapshot_fn=lambda: snap)
    d.refresh()
    d.dlg.show_all()
    d.fill(snap)
    shot(d.dlg, "progress")
    d.dlg.destroy()
    w.destroy()
    gtk.pump(0.1)

    # ── 💊 indikatorius ──
    from diktatura.ui import pill
    v = pill.PillView()
    rnd = random.Random(2)
    lv = [(-25 + 10 * math.sin(i / 3) + rnd.uniform(-5, 5) if (i // 15) % 2 == 0 else -65,
           -65 if (i // 15) % 2 == 0 else -22 + rnd.uniform(-6, 6)) for i in range(80)]
    v.show_rec("vox", 42.0, lv)
    shot(v.win, "pill-rec")
    v.show_after("⏳ Transkribuojama 43 % · liko ~2 min", 0.43)
    shot(v.win, "pill-after")
    v.win.destroy()

    # ── temos ──
    for theme, page in (("dark", "text"), ("contrast", "training"), ("compact", "text")):
        w = new_window(theme)
        w.text.cmb_period.set_active_id("7")
        if theme == "compact":
            w.resize(680, 420)
        w.show_page(page)
        shot(w, f"theme-{theme}")
        w.destroy()
        gtk.pump(0.1)
    config.save({"THEME": "light"})


if __name__ == "__main__":
    main()
