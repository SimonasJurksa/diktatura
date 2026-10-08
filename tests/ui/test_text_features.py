"""Etapas 6: teksto funkcijos — regex paieška, filtrai (kalbėtojas, laikotarpis, žymėtos), žymės ⭐/☐/☑,
grojimas nuo eilutės su paryškinimu, statistika, eksportas, „Priskirti vardą" iš kontekstinio meniu."""
import time
from datetime import date, datetime, timedelta

import pytest

import audio
from diktatura import annotations, sessions
from testenv import HELPERS


def day(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y%m%d")


@pytest.fixture
def demo(env):
    r = env.recordings
    (r / f"slack_{day(0)}_100000.named.txt").write_text(
        "[0:00:01] Ona: rytoj diegimas į serverį\n[0:00:05] Tu: gerai, paruošiu migraciją\n"
        "[0:00:20] Kolega?nez1: o kada testai?\n[0:00:26] Ona: po diegimo\n", encoding="utf-8")
    audio.write_wav(r / f"slack_{day(0)}_100000.wav", audio.speech(30), audio.speech(30))
    (r / f"vox_{day(1)}_090000.named.txt").write_text("[0:00:02] Tu: vakarykštė pastaba\n", encoding="utf-8")
    (r / f"vox_{day(10)}_090000.named.txt").write_text("[0:00:02] Tu: senas archyvo įrašas\n", encoding="utf-8")
    import json
    env.pending.mkdir(parents=True, exist_ok=True)
    (env.pending / "nez1.json").write_text(json.dumps({"embedding": [1.0, 0.0], "src": f"slack_{day(0)}_100000"}))
    return env


@pytest.fixture
def win(demo, fake_systemd, monkeypatch, tmp_path):
    from diktatura.ui import gtk
    from diktatura.ui.app import MainWindow
    monkeypatch.setenv("DIKTATURA_SEEK_PLAYER", f"{HELPERS / 'fakebin' / 'player-fake'} {{start}} {{file}}")
    monkeypatch.setenv("FAKE_PLAYER_LOG", str(tmp_path / "played"))
    w = MainWindow(auto_refresh=False)
    w.show_all()
    gtk.pump(0.05)
    yield w
    w.text.stop_playback()
    w.destroy()
    gtk.pump(0.02)


def body(tp):
    return tp.text()


def test_period_range_pure():
    d = date(2026, 10, 8)
    from diktatura.ui.text_page import period_range
    assert period_range("today", 2, d) == (d, d)
    assert period_range("yesterday", 2, d) == (date(2026, 10, 7), date(2026, 10, 7))
    assert period_range("7", 2, d) == (date(2026, 10, 2), None)
    assert period_range("keep", 2, d) == (date(2026, 10, 7), None)
    assert period_range("all", 2, d) == (None, None)


def test_regex_search_and_invalid_pattern(win):
    tp = win.text
    tp.cb_regex.set_active(True)
    tp.search.set_text(r"diegim\w+|migracij")
    tp.highlight_all()
    assert len(tp.matches) == 3                                          # diegimas, diegimo, migraciją
    tp.search.set_text("(neuždaryta")
    tp.highlight_all()
    assert tp.matches == [] and "klaidinga regex" in tp.lbl_match.get_text()
    tp.cb_regex.set_active(False)
    tp.search.set_text("(neuždaryta")
    tp.highlight_all()
    assert tp.lbl_match.get_text() == "nerasta"                           # be regex — paprastas tekstas


def test_speaker_filter(win):
    tp = win.text
    assert "Ona" in tp.speakers() and [r[0] for r in tp.cmb_speaker.get_model()][0] == "Visi"
    tp.cmb_speaker.set_active_id("Ona")
    t = body(tp)
    assert "rytoj diegimas" in t and "po diegimo" in t and "migraciją" not in t
    assert "vakarykštė" not in t                                         # sesija be Onos — net be antraštės
    tp.cmb_speaker.set_active_id("__visi__")
    assert "migraciją" in body(tp)


def test_period_filter_loads_archive(win):
    tp = win.text
    assert "vakarykštė" in body(tp) and "senas archyvo" not in body(tp)  # numatyta: pask. 2 d.
    tp.cmb_period.set_active_id("today")
    assert "vakarykštė" not in body(tp) and "diegimas" in body(tp)
    tp.cmb_period.set_active_id("yesterday")
    assert "vakarykštė" in body(tp) and "diegimas" not in body(tp)
    tp.cmb_period.set_active_id("all")
    assert "senas archyvo" in body(tp)
    tp.cmb_period.set_active_id("keep")
    assert "senas archyvo" not in body(tp)


def test_tags_star_task_done_and_tagged_filter(win, demo):
    tp = win.text
    lines = {ln.text: ln for ln in tp.visible_lines()}
    tp.tag_line(lines["rytoj diegimas į serverį"], "star")
    tp.tag_line(lines["gerai, paruošiu migraciją"], "task")
    t = body(tp)
    assert "⭐ [0:00:01] Ona: rytoj" in t and "☐ [0:00:05] Tu: gerai" in t
    tp.toggle_task(lines["gerai, paruošiu migraciją"])
    assert "☑ [0:00:05] Tu: gerai" in body(tp)
    tp.cb_tagged.set_active(True)
    t = body(tp)
    assert "rytoj diegimas" in t and "migraciją" in t and "o kada testai" not in t
    tp.cb_tagged.set_active(False)
    tp.tag_line(lines["rytoj diegimas į serverį"], None)
    assert "⭐" not in body(tp)
    # žymė išlieka, kai kalbėtojas pervadinamas (raktas — failas + eilutė + tekstas, be kalbėtojo)
    from diktatura.speakers import store
    store.rename_in_transcripts("Tu", "Aš")
    tp.refresh()
    assert "☑ [0:00:05] Aš: gerai" in body(tp)
    assert (demo.data / "annotations.json").exists()


def test_context_menu_items(win, demo):
    tp = win.text
    by = {ln.text: ln for ln in tp.visible_lines()}
    labels = lambda ln: [m.get_label() for m in tp.menu_items(ln) if hasattr(m, "get_label") and m.get_label()]  # noqa
    unknown = labels(by["o kada testai?"])
    assert any(lb.startswith("▶ Groti nuo čia (0:00:20)") for lb in unknown)
    assert "🎓 Priskirti vardą balsui nez1…" in unknown
    assert not any("Priskirti" in lb for lb in labels(by["po diegimo"]))
    play = [m for m in tp.menu_items(by["vakarykštė pastaba"]) if getattr(m, "get_label", lambda: "")().startswith("▶")]
    assert play and not play[0].get_sensitive()                          # garso nėra -> negalima groti


def test_assign_from_text_opens_training_on_that_voice(win):
    tp = win.text
    ln = next(ln for ln in tp.visible_lines() if ln.speaker == "Kolega?nez1")
    tp.goto_training("nez1")
    assert win.current == "training" and win.training.cur.id == "nez1"
    assert ln.speaker == "Kolega?nez1"


def test_play_from_line_highlights_current(win, tmp_path, monkeypatch):
    tp = win.text
    ln = next(ln for ln in tp.visible_lines() if ln.ts == "0:00:05")
    assert tp.play_line(ln)
    time.sleep(0.3)
    start, f = (tmp_path / "played").read_text().split()
    assert float(start) == pytest.approx(4.5) and f.endswith(".wav")      # pusė sekundės prieš eilutę
    assert tp.btn_stop.get_visible()
    monkeypatch.setattr(tp.player, "position", lambda: 21.0)
    tp._highlight_playing()
    s, e = tp.line_range(tp.playing_line())
    assert tp.playing_line().text == "o kada testai?" and s.has_tag(tp.t_play)
    tp.stop_playback()
    assert not tp.btn_stop.get_visible() and tp.play_session is None
    assert not s.has_tag(tp.t_play)


def test_stats_per_speaker(win):
    st = win.text.stats()
    assert st["Ona"]["lines"] == 2 and st["Tu"]["lines"] == 2 and st["Kolega?nez1"]["lines"] == 1
    assert st["Tu"]["seconds"] == pytest.approx(15 + 2 / 2.5)             # 0:05→0:20 + vakar 2 žodž.
    win.text.cmb_speaker.set_active_id("Ona")
    assert set(win.text.stats()) == {"Ona"}


def test_speaker_stats_pure():
    rows = [("a", 0, "Ona", "vienas du trys"), ("a", 10, "Tu", "x"), ("a", 200, "Ona", "keturi penki"), ("b", None, "", "be")]
    st = sessions.speaker_stats(rows)
    assert st["Ona"]["seconds"] == pytest.approx(10 + 2 / 2.5) and st["Tu"]["seconds"] == 60   # ilga pauzė -> max 60
    assert st["—"]["lines"] == 1


def test_export_txt_and_md(win, tmp_path):
    tp = win.text
    ln = next(ln for ln in tp.visible_lines() if ln.ts == "0:00:01")
    tp.tag_line(ln, "star")
    txt = tp.export_to(tmp_path / "a.txt").read_text(encoding="utf-8")
    assert "⭐ [0:00:01] Ona: rytoj diegimas į serverį" in txt and "// " in txt
    md = tp.export_to(tmp_path / "a.md").read_text(encoding="utf-8")
    assert "## " in md and "- ⭐ **Ona** `0:00:01` rytoj diegimas" in md
    tp.cmb_speaker.set_active_id("Tu")
    assert "Ona" not in tp.export_text()


def test_annotations_store_pure(env):
    annotations.set_tag("f.named.txt", 3, "tekstas", "task")
    d = annotations.load()
    assert annotations.icon(annotations.match(d, "f.named.txt", 3, "tekstas")) == "☐"
    assert annotations.match(d, "f.named.txt", 7, "tekstas")              # eilutė pasislinko — rasta pagal tekstą
    assert annotations.match(d, "f.named.txt", 3, "kitas") is None
    assert annotations.toggle_done("f.named.txt", 3, "tekstas") is True
    with pytest.raises(ValueError):
        annotations.set_tag("f.named.txt", 1, "x", "kita")
