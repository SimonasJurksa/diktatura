"""I5 + G4/G5 per UI: Apmokymai — nežinomi balsai, kontekstas, vardo priskyrimas, „Ne žmogus", grojimas, pervadinimas."""
import json
import time
from datetime import datetime

import numpy as np
import pytest

from testenv import HELPERS


def emb(i, dim=8):
    v = np.zeros(dim)
    v[i] = 1.0
    return v.tolist()


@pytest.fixture
def demo(env):
    """2 nežinomi balsai (+ garsas), 1 registruotas, transkripcijos su jų eilutėmis."""
    import audio
    env.pending.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    for i, src in ((1, f"slack_{today}_090000"), (2, f"vox_{today}_100000")):
        audio.write_wav(env.pending / f"nez{i}.wav", audio.speech(2, -20))
        (env.pending / f"nez{i}.json").write_text(json.dumps({"embedding": emb(i), "src": src,
                                                              "added": f"{datetime.now():%Y-%m-%dT%H:%M:%S}"}))
    (env.speakers / "enroll.json").write_text(json.dumps({"Ona": [emb(0)], "Ruta": [emb(5)], "Rūta": [emb(6)]}))
    (env.recordings / f"slack_{today}_090000.named.txt").write_text(
        "[0:00:01] Ona: labas\n[0:00:04] Kolega?nez1: kada diegimas?\n[0:00:09] Kolega?nez2: girdžiu\n"
        "[0:00:12] Kolega?nez1: ačiū\n[0:00:15] Ruta: iki\n", encoding="utf-8")
    (env.recordings / f"vox_{today}_100000.named.txt").write_text("[0:00:02] Kolega?nez1: dar kartą\n", encoding="utf-8")
    return env


@pytest.fixture
def win(demo, fake_systemd, monkeypatch, tmp_path):
    from diktatura.ui import gtk
    from diktatura.ui.app import MainWindow
    monkeypatch.setenv("DIKTATURA_PLAYER", str(HELPERS / "fakebin" / "player-fake"))
    monkeypatch.setenv("FAKE_PLAYER_LOG", str(tmp_path / "played"))
    w = MainWindow(auto_refresh=False)
    w.show_all()
    w.show_page("training")
    gtk.pump(0.05)
    yield w
    w.training.stop()
    w.destroy()
    gtk.pump(0.02)


def test_i5_list_context_and_completion(win):
    tp = win.training
    assert [v.id for v in tp.voices] == ["nez1", "nez2"] and tp.cur.id == "nez1"
    assert tp.lbl_count.get_text() == "Laukia vardo: 2"
    assert "(1 / 2)" in tp.lbl_title.get_text()
    assert "3 kart. 2 sesijose" in tp.lbl_info.get_text()
    buf = tp.ctx.get_buffer()
    ctx = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
    assert "kada diegimas?" in ctx and "dar kartą" in ctx and "girdžiu" not in ctx   # tik šio balso eilutės
    assert [r[0] for r in tp.names_model] == ["Ona", "Ruta", "Rūta"]                 # autocomplete iš esamų vardų
    assert "Registruoti balsai (3)" in tp.exp.get_label()


def test_i5_navigation_and_skip(win):
    tp = win.training
    tp.move(1)
    assert tp.cur.id == "nez2"
    tp.move(1)
    assert tp.cur.id == "nez1"                                           # ciklas
    tp.skip()
    assert tp.cur.id == "nez2" and (win.training.voices and len(tp.voices) == 2)


def test_g4_assign_via_ui_renames_everywhere_and_moves_next(win, demo):
    from diktatura.speakers import store
    win.text.refresh()
    assert "Kolega?nez1:" in win.text.text()
    tp = win.training
    tp.entry.set_text("Darius")
    assert tp.assign()
    assert store.counts()["Darius"] == 1 and [p.id for p in store.list_pending()] == ["nez2"]
    t = (demo.recordings / [f.name for f in demo.recordings.glob("slack_*.named.txt")][0]).read_text()
    assert "Darius: kada diegimas?" in t and "Darius: ačiū" in t and "Kolega?nez2: girdžiu" in t
    assert tp.cur.id == "nez2"                                           # automatiškai kitas
    assert "Darius: dar kartą" in win.text.text() and "nez1" not in win.text.text()   # teksto skiltis atsinaujino
    assert "pakeista eilučių: 3" in tp.msg.get_text()


def test_assign_rejects_empty_name(win):
    from diktatura.speakers import store
    win.training.entry.set_text("   ")
    assert not win.training.assign()
    assert "tuščias" in win.training.msg.get_text() and len(store.list_pending()) == 2


def test_g5_not_human_via_ui(win, demo):
    from diktatura.speakers import store
    before = (demo.speakers / "enroll.json").read_text()
    win.training.move(1)                                                 # nez2
    assert win.training.not_human()
    assert [p.id for p in store.list_pending()] == ["nez1"]
    assert (demo.speakers / "enroll.json").read_text() == before
    assert len(store.load_ignored()) == 1
    assert "Kolega?: girdžiu" in win.text.text()


def test_last_voice_assigned_shows_placeholder(win):
    tp = win.training
    tp.entry.set_text("Darius")
    tp.assign()
    tp.entry.set_text("Matas")
    tp.assign()
    assert tp.voices == [] and tp.cur is None and not tp.detail.get_sensitive()
    assert tp.lbl_count.get_text() == "Laukia vardo: 0"


def test_play_and_stop_sample(win, tmp_path):
    tp = win.training
    tp.play()
    time.sleep(0.3)
    assert (tmp_path / "played").read_text().strip().endswith("nez1.wav")
    assert tp.player.poll() is None and tp.btn_stop.get_sensitive() and not tp.btn_play.get_sensitive()
    p = tp.player
    tp.stop()
    assert p.poll() is not None and tp.btn_play.get_sensitive()
    tp.play()
    tp.move(1)                                                           # perjungus balsą — grojimas sustoja
    assert tp.player is None


def test_rename_merge_and_forget_known_voice(win, demo):
    from diktatura.speakers import store
    tp = win.training
    n = tp.rename("Ruta", "Rūta")
    assert n == 1 and store.counts()["Rūta"] == 2 and "Ruta" not in store.counts()
    assert "Rūta: iki" in win.text.text()
    tp.forget("Ona")
    assert "Ona" not in store.counts() and "Registruoti balsai (1)" in tp.exp.get_label()


def test_playback_pauses_recording_and_releases(win):
    from diktatura import pause
    tp = win.training
    assert not pause.active()
    tp.play()
    assert pause.active() and pause.info()["reason"] == "grojama perklausa"
    tp.stop()
    info = pause.info()
    assert info and info["reason"] == "baigta groti" and info["until"] - time.time() <= pause.TAIL_SEC + 0.1
    tp.move(1)                                   # stop() be grojimo — pauzės nekeičia
    assert pause.info()["reason"] == "baigta groti"
