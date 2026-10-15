"""S (UI). Regresija — UŽRAKINTA tai, ką savininkas mato lange: teksto vaizdas, eksportas, mygtukai, Nustatymų grupės,
ikonos meniu, paieška ir filtrai. Lūžo = kažkas pakeitė matomą elgseną; sąmoningai keičiant — atnaujinti testą.
"""
from datetime import date, timedelta

import pytest

from testenv import REPO  # noqa: F401


@pytest.fixture
def gtk():
    from diktatura.ui import gtk as g
    return g


def D(days):
    return date.today() - timedelta(days=days)


@pytest.fixture
def demo(env):
    """Išgalvoti tekstai: vakar VOX, šiandien SLACK (su ⭐) ir mono REC."""
    from diktatura import annotations
    d0, d1 = D(0).strftime("%Y%m%d"), D(1).strftime("%Y%m%d")
    (env.recordings / f"vox_{d1}_090000.named.txt").write_text(
        "[0:00:01] Tu: labas rytas\n[0:00:04] Ona: sveikas, Jonai\n", encoding="utf-8")
    (env.recordings / f"slack_{d0}_100000.named.txt").write_text(
        "[0:00:02] Jonas: pradedam susitikimą\n[0:01:10] Kolega?nez2: aš čia\n", encoding="utf-8")
    (env.recordings / f"rec_{d0}_110000.txt").write_text("mono eilutė be laiko\n", encoding="utf-8")
    annotations.set_tag(f"slack_{d0}_100000.named.txt", 0, "pradedam susitikimą", "star")
    return d0, d1


@pytest.fixture
def win(env, fake_systemd, gtk, demo):
    from diktatura.ui.app import MainWindow
    w = MainWindow(auto_refresh=False)
    w.show_all()
    gtk.pump(0.05)
    yield w
    w.destroy()
    gtk.pump(0.02)


def hdr(day, hhmm, src, base):
    return f"// ───────────────  {day:%Y-%m-%d} {hhmm}:00 · {src} · {base}  ───────────────"


def test_su1_text_view_golden(win, demo):
    d0, d1 = demo
    expect = "\n".join([
        hdr(D(1), "09:00", "VOX", f"vox_{d1}_090000"), "",
        "[0:00:01] Tu: labas rytas", "[0:00:04] Ona: sveikas, Jonai", "",
        hdr(D(0), "10:00", "SLACK", f"slack_{d0}_100000"), "",
        "⭐ [0:00:02] Jonas: pradedam susitikimą", "[0:01:10] Kolega?nez2: aš čia", "",
        hdr(D(0), "11:00", "REC", f"rec_{d0}_110000"), "",
        "mono eilutė be laiko"])
    assert win.text.text().strip() == expect
    assert win.text.status.get_text() == f"Rodoma 3 sesijų (nuo {D(1):%Y-%m-%d}) · kalbėtojų: 4 · seka naujus"


def test_su2_export_txt_and_md_golden(win, demo):
    d0, d1 = demo
    assert win.text.export_text("txt") == "\n".join([
        f"// {D(1):%Y-%m-%d} 09:00 · VOX · vox_{d1}_090000", "",
        "[0:00:01] Tu: labas rytas", "[0:00:04] Ona: sveikas, Jonai", "",
        f"// {D(0):%Y-%m-%d} 10:00 · SLACK · slack_{d0}_100000", "",
        "⭐ [0:00:02] Jonas: pradedam susitikimą", "[0:01:10] Kolega?nez2: aš čia", "",
        f"// {D(0):%Y-%m-%d} 11:00 · REC · rec_{d0}_110000", "",
        "mono eilutė be laiko", ""])
    assert win.text.export_text("md") == "\n".join([
        f"## {D(1):%Y-%m-%d} 09:00 · VOX · vox_{d1}_090000", "",
        "- **Tu** `0:00:01` labas rytas", "- **Ona** `0:00:04` sveikas, Jonai", "",
        f"## {D(0):%Y-%m-%d} 10:00 · SLACK · slack_{d0}_100000", "",
        "- ⭐ **Jonas** `0:00:02` pradedam susitikimą", "- **Kolega?nez2** `0:01:10` aš čia", "",
        f"## {D(0):%Y-%m-%d} 11:00 · REC · rec_{d0}_110000", "",
        "- mono eilutė be laiko", ""])


def _buttons(x, out=None):
    from diktatura.ui.gtk import Gtk
    out = [] if out is None else out
    if isinstance(x, Gtk.Button) and x.get_label():
        out.append(x.get_label())
    elif isinstance(x, Gtk.Container):
        for c in x.get_children():
            _buttons(c, out)
    return out


def _frames(x, out=None):
    from diktatura.ui.gtk import Gtk
    out = [] if out is None else out
    if isinstance(x, Gtk.Frame):
        out.append(x.get_label_widget().get_text())
    if isinstance(x, Gtk.Container):
        for c in x.get_children():
            _frames(c, out)
    return out


def test_su3_layout_buttons_and_groups_locked(win):
    from diktatura.ui.app import PAGES
    assert PAGES == (("text", "📄 Tekstas"), ("training", "🎓 Apmokymai"), ("settings", "⚙ Nustatymai"))
    assert _buttons(win.text) == ["Regex", "◀", "▶", "Tik žymėtos ⭐☐", "⏹ Stabdyti grojimą", "🌊 Banga",
                                  "✨ Švarus", "📊 Statistika", "⏳ Transkripcija", "💾 Eksportuoti…", "Kopijuoti viską",
                                  "Sekti naujus", "⤓ Naujausia"]
    assert _buttons(win.training) == ["▶ Groti pavyzdį", "⏹ Stabdyti", "✔ Įrašyti", "◀ Ankstesnis", "Kitas ▶",
                                      "⏭ Praleisti", "🙋 Tai aš", "🗑 Ne žmogus / triukšmas", "📄 Grįžti į tekstą"]
    assert _frames(win.settings) == ["Įrašymo režimas", "Išvaizda", "Tekstas", "Įrašymas", "Transkripcija",
                                     "Sekami aplankai",
                                     "VAD (kalbos filtras)", "Kalbėtojai", "Archyvas", "Debug",
                                     "Atstatymas ir duomenys"]


def test_su4_tray_menu_order_locked(env, gtk):
    from diktatura import progress
    from diktatura.ui import tray
    from test_main_window import FakeIndicator
    ind = FakeIndicator()
    tray.Tray(indicator=ind, opener=lambda p: None, state_fn=lambda: "idle", mode_fn=lambda: "vox",
              pending_fn=lambda: 0, timers=False, progress_fn=lambda: progress.Snapshot(now=0))
    items = [(it.get_label(), it.get_visible()) for it in ind.menu.get_children() if it.get_label()]
    assert items == [("⚙ Nustatymai", True), ("🎓 Apmokymai paruošti (0)", False),
                     ("📄 Rodyti nuskaitytą tekstą", True), ("⏳", False), ("Diktatūra — ⚪ Budi (nerašo)", True),
                     ("Režimas: VOX", True), ("Atidaryti įrašų aplanką", True), ("Išeiti", True)]


def test_su5_search_plain_regex_and_ctrl_f(win, gtk):
    from diktatura.ui.gtk import Gdk
    t = win.text
    assert len(t.find_ranges("LABAS")) == 1                                    # be didžiųjų/mažųjų skirtumo
    assert len(t.find_ranges("aš")) == 1
    t.cb_regex.set_active(True)
    assert len(t.find_ranges(r"pra\w+|sveik\w+")) == 2
    t.cb_regex.set_active(False)
    ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    ev.keyval, ev.state = Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK
    assert t.on_key(ev) and t.search.is_focus()                                 # fokusas paieškoje


def test_su6_filters_period_speaker_tagged(win, demo):
    t = win.text
    t.set_period("today")
    assert "labas rytas" not in t.text() and "pradedam" in t.text()
    t.set_period("yesterday")
    assert "labas rytas" in t.text() and "pradedam" not in t.text()
    t.set_period("all")
    t.set_speaker_filter("Ona")
    assert [ln.text for ln in t.visible_lines()] == ["sveikas, Jonai"]
    t.set_speaker_filter(None)
    t.set_tagged_only(True)
    assert [ln.text for ln in t.visible_lines()] == ["pradedam susitikimą"]
    t.set_tagged_only(False)
    assert len(t.visible_lines()) == 5


def test_su7_pure_helpers(env):
    from diktatura.ui import text_page as tp
    from diktatura.ui import training_page as trp
    today = date(2026, 10, 12)
    assert tp.period_range("today", 2, today) == (today, today)
    assert tp.period_range("yesterday", 2, today) == (date(2026, 10, 11),) * 2
    assert tp.period_range("7", 2, today) == (date(2026, 10, 6), None)
    assert tp.period_range("all", 2, today) == (None, None)
    assert tp.period_range("keep", 2, today) == (date(2026, 10, 11), None)
    assert tp.fmt_dur(59) == "0:59" and tp.fmt_dur(3725) == "1:02:05"
    assert trp.fmt_when("slack_20261012_143000") == "2026-10-12 14:30 · SLACK"
    assert trp.fmt_when("2026-10-12T14:30:05") == "2026-10-12 14:30" and trp.fmt_when("") == "?"
    assert tp.teach_cmd("/x/a.named.txt", 3, "Ona")[-4:] == ["diktatura.speakers.teach", "/x/a.named.txt", "3", "Ona"]


def test_su7_player_cmd_env(env, monkeypatch):
    from diktatura.ui import training_page as trp
    monkeypatch.delenv("DIKTATURA_PLAYER", raising=False)
    assert trp.player_cmd() == ["paplay"]
    monkeypatch.setenv("DIKTATURA_PLAYER", "aplay -q")
    assert trp.player_cmd() == ["aplay", "-q"]
