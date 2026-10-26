"""I5 + G4/G5 per UI: Apmokymai — nežinomi balsai, kontekstas, vardo priskyrimas, „Ne žmogus", grojimas, pervadinimas;
🔄 pertikrinimas pagal išmoktus (💡 pasiūlymai, rikiavimas, užtikrintų priėmimas), vieta įraše ±N s."""
import json
import sys
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
    ctx = tp.context_text()
    assert "kada diegimas?" in ctx and "dar kartą" in ctx and "girdžiu" not in ctx   # tik šio balso eilutės
    assert "[0:00:04] kada diegimas?" in ctx and len(tp.ctx.get_children()) == 3
    assert [r[0] for r in tp.names_model] == ["Ona", "Ruta", "Rūta"]                 # autocomplete iš esamų vardų
    assert "Registruoti balsai (3)" in tp.tab_title("known") and tp.tab_title("pending") == "🔎 Laukia vardo (2)"


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
    p = tp.player
    tp.move(1, play=False)                                               # perjungus balsą — grojimas sustoja
    assert tp.player is None and p.poll() is not None
    tp.play()
    p = tp.player
    tp.move(1)                                                           # „Kitas ▶" — senas sustoja, kitas groja pats
    time.sleep(0.3)
    assert p.poll() is not None and tp.player is not p and tp.is_playing() and tp.playing == "sample"
    assert (tmp_path / "played").read_text().strip().endswith(f"{tp.cur.id}.wav")


def test_rename_merge_and_forget_known_voice(win, demo):
    from diktatura.speakers import store
    tp = win.training
    n = tp.rename("Ruta", "Rūta")
    assert n == 1 and store.counts()["Rūta"] == 2 and "Ruta" not in store.counts()
    assert "Rūta: iki" in win.text.text()
    tp.forget("Ona")
    assert "Ona" not in store.counts() and "Registruoti balsai (1)" in tp.tab_title("known")


def test_playback_pauses_recording_and_releases(win):
    from diktatura import pause
    tp = win.training
    assert not pause.active()
    tp.play()
    assert pause.active() and pause.info()["reason"] == "grojama perklausa"
    tp.stop()
    info = pause.info()
    assert info and info["reason"] == "baigta groti" and info["until"] - time.time() <= pause.TAIL_SEC + 0.1
    tp.move(1, play=False)                       # stop() be grojimo — pauzės nekeičia
    assert pause.info()["reason"] == "baigta groti"


def known_rows(tp):
    return [r.get_child().speaker for r in tp.known.get_children()]


def test_g7_its_me_button_and_typed_tu(win, demo):
    """Nežinomas balsas — tai tu (kalbėjai telefonu): „🙋 Tai aš" arba vardas „Tu" -> owner.json, tekstuose „Tu"."""
    from diktatura.speakers import store
    tp = win.training
    assert known_rows(tp)[0] == "Tu" and store.owner_count() == 0
    assert tp.its_me()
    assert store.owner_count() == 1 and store.counts() == {"Ona": 1, "Ruta": 1, "Rūta": 1}
    assert "Tu: kada diegimas?" in win.text.text() and "Kolega?nez1" not in win.text.text()
    assert tp.cur.id == "nez2" and "tavo balsas" in tp.msg.get_text()
    tp.entry.set_text(" tu ")
    assert tp.assign()
    assert store.owner_count() == 2 and not store.list_pending()
    assert "Tu: girdžiu" in win.text.text()
    tp.forget_me()
    assert store.owner_count() == 0 and known_rows(tp)[0] == "Tu"


# ── sekamų aplankų tekstai, 💡 pasiūlymai, rikiavimas, pertikrinimas, vieta įraše ──

def pump_until(cond, sec=30):
    from diktatura.ui import gtk
    end = time.monotonic() + sec
    while not cond() and time.monotonic() < end:
        gtk.pump(0.05)
    return cond()


def write_suggestions(env, items, checked=("nez1", "nez2")):
    from diktatura.speakers import store
    store._atomic_write(store.suggestions_file(), json.dumps({
        "started": time.time(), "voices": store.voices_signature(), "threshold": 0.5, "margin": 0.1, "suggest": 0.4,
        "checked": list(checked), "items": items}, ensure_ascii=False))


def row_texts(tp, i):
    return [w.get_text() for w in tp.list.get_row_at_index(i).get_child().get_children()]


def test_counts_include_followed_folder_texts(win, demo):
    """Regresija: susirinkimo (sekamo aplanko) balsams rodė „0 kart. · 0 sesij."."""
    d = demo.data / "sources" / "telefonas"
    d.mkdir(parents=True)
    (d / "Susirinkimas.wav.named.txt").write_text("[0:00:01] Kolega?nez2: pirmas\n[0:00:05] Kolega?nez2: antras\n",
                                                  encoding="utf-8")
    tp = win.training
    tp.set_sort("count")
    tp.reload()
    assert [v.id for v in tp.voices] == ["nez1", "nez2"]
    assert row_texts(tp, 1)[2] == "3 kart. · 2 sesij."                   # 1 įraše + 2 sekamo aplanko tekste
    tp.move(1)
    assert "pirmas" in tp.context_text() and "3 kart. 2 sesijose" in tp.lbl_info.get_text()
    tp.entry.set_text("Darius")
    tp.assign()
    assert (d / "Susirinkimas.wav.named.txt").read_text().count("Darius:") == 2


def test_suggestion_first_prefilled_and_enter_accepts(win, demo):
    from diktatura.speakers import store
    write_suggestions(demo, {"nez2": {"name": "Ona", "sim": 0.47, "alt": "Ruta", "alt_sim": 0.31, "strong": False,
                                      "basis": "profile", "lines": 3}})
    tp = win.training
    tp.reload()
    tp.cur = None
    tp.reload()
    assert [v.id for v in tp.voices] == ["nez2", "nez1"] and tp.cur.id == "nez2"   # 💡 viršuje
    assert row_texts(tp, 0)[-1] == "💡 Ona? · 0.47" and len(row_texts(tp, 1)) == 3
    assert tp.entry.get_text() == "Ona" and tp.lbl_hint.get_visible()
    assert "„Ona“ (panašumas 0.47; antras — „Ruta“ 0.31; pagal 3 eilučių balsą)" in tp.lbl_hint.get_text()
    assert tp.lbl_sugg.get_text() == "💡 pasiūlymų: 1 · užtikrintų: 0" and not tp.btn_accept.get_visible()
    assert any("💡 panašių laukia: 1" in w.get_text() for r in tp.known.get_children()
               for w in r.get_child().get_children() if hasattr(w, "get_text"))
    tp.entry.emit("activate")                                           # Enter
    assert store.counts()["Ona"] == 2 and [p.id for p in store.list_pending()] == ["nez1"]
    assert "Ona: girdžiu" in win.text.text()


def test_noise_suggestion_does_not_prefill(win, demo):
    write_suggestions(demo, {"nez1": {"name": "", "sim": 0.52, "alt": "Ona", "alt_sim": 0.3, "strong": True,
                                      "basis": "sample", "lines": 3}})
    tp = win.training
    tp.cur = None
    tp.reload()
    assert tp.cur.id == "nez1" and tp.entry.get_text() == ""
    assert row_texts(tp, 0)[-1] == "✔ triukšmas · 0.52" and "„🗑 Ne žmogus“" in tp.lbl_hint.get_text()


def test_sort_modes(win, demo):
    write_suggestions(demo, {"nez2": {"name": "Ona", "sim": 0.47, "strong": False}})
    tp = win.training
    tp.reload()
    assert [v.id for v in tp.voices] == ["nez2", "nez1"]
    tp.set_sort("count")
    assert [v.id for v in tp.voices] == ["nez1", "nez2"] and tp.cmb_sort.get_active_id() == "count"
    tp.set_sort("time")                                                 # pirmoji eilutė: nez1 0:00:04, nez2 0:00:09
    assert [v.id for v in tp.voices] == ["nez1", "nez2"]


def test_accept_strong_assigns_without_learning(win, demo, monkeypatch):
    from diktatura.speakers import store
    from diktatura.ui import training_page
    write_suggestions(demo, {"nez1": {"name": "Ona", "sim": 0.8, "strong": True},
                             "nez2": {"name": "", "sim": 0.6, "strong": True}})
    tp = win.training
    tp.reload()
    assert tp.btn_accept.get_visible() and tp.btn_accept.get_label() == "✔ Priimti užtikrintus (2)"
    before = (demo.speakers / "enroll.json").read_text()
    monkeypatch.setattr(training_page.TrainingPage, "_dialog", lambda self, *a, **k: FakeDialog())
    tp._confirm_accept_strong()
    assert store.list_pending() == [] and (demo.speakers / "enroll.json").read_text() == before
    assert "Ona: kada diegimas?" in win.text.text() and "Kolega?: girdžiu" in win.text.text()
    assert "Priimta užtikrintų pasiūlymų: 2 (tekstuose pakeista eilučių: 4)" in tp.msg.get_text()


class FakeDialog:
    def run(self):
        from diktatura.ui.gtk import Gtk
        return Gtk.ResponseType.OK

    def destroy(self):
        pass


def test_recheck_runs_in_background_and_repairs_old_texts(win, demo, monkeypatch):
    """🔄: anksčiau priskirtas, bet tekste likęs „Kolega?nez7" pataisomas; fone paskaičiuoti pasiūlymai — sąraše."""
    from diktatura.speakers import store
    from diktatura.ui import training_page
    store.mark_model()
    (demo.pending / "nez2.json").write_text(json.dumps({"embedding": [0.8, 0, 0.6, 0, 0, 0, 0, 0], "src": "x"}))
    (demo.speakers / "assigned.json").write_text(json.dumps({"nez7": "Matas"}))
    old = demo.recordings / "rec_20261020_100000.named.txt"
    old.write_text("[0:00:01] Kolega?nez7: senas\n", encoding="utf-8")
    monkeypatch.setattr(training_page, "suggest_cmd",
                        lambda: [sys.executable, "-m", "diktatura.speakers.suggest", "--no-profiles"])
    tp = win.training
    assert tp.recheck(user=True) and not tp.btn_recheck.get_sensitive()
    assert not tp.recheck(user=True) and tp.job_again is True           # paspausta dar kartą — po šio vėl
    assert pump_until(lambda: tp.job is None and tp.job_again is None)
    assert old.read_text() == "[0:00:01] Matas: senas\n"
    assert tp.btn_recheck.get_sensitive() and [v.id for v in tp.voices] == ["nez2", "nez1"]
    assert row_texts(tp, 0)[-1] == "✔ Ona · 0.80"
    assert "Pertikrinta laukiančių balsų: 2. 💡 Pasiūlymų: 1 (užtikrintų 1" in tp.msg.get_text()
    assert tp.lbl_sugg.get_text() == "💡 pasiūlymų: 1 · užtikrintų: 1"


def test_recheck_failure_is_reported(win, monkeypatch):
    from diktatura.ui import training_page
    monkeypatch.setattr(training_page, "suggest_cmd", lambda: ["false"])
    tp = win.training
    tp.recheck(user=True)
    assert pump_until(lambda: tp.job is None)
    assert tp.msg.get_text() == "✗ Pertikrinti nepavyko: klaida (1)" and tp.btn_recheck.get_sensitive()


def test_auto_recheck_only_when_stale(win, demo, monkeypatch):
    from diktatura.ui import training_page
    started = []
    monkeypatch.setattr(training_page.TrainingPage, "recheck", lambda self, user=False: started.append(user) or True)
    tp = win.training
    assert not tp.recheck_if_stale()                                    # testuose auto išjungta
    tp.auto = True
    assert tp.recheck_if_stale() and started == [False]                 # pasiūlymų dar nėra
    write_suggestions(demo, {})
    started.clear()
    assert not tp.recheck_if_stale() and started == []


def test_play_context_with_padding(win, demo, tmp_path, monkeypatch):
    """🔊 Įraše: eilutės vieta originaliame įraše ±N s (pavyzdys dažnai vos sekundė)."""
    import audio
    from diktatura import pause
    today = datetime.now().strftime("%Y%m%d")
    audio.write_wav(demo.recordings / f"slack_{today}_090000.wav", audio.speech(20, -20))
    log = tmp_path / "seek"
    monkeypatch.setenv("FAKE_PLAYER_LOG", str(log))
    monkeypatch.setenv("DIKTATURA_SEEK_PLAYER", f"{HELPERS / 'fakebin' / 'player-fake'} {{file}} {{start}} {{dur}}")
    tp = win.training
    assert tp.cur.id == "nez1" and tp.play_context()                    # pirmoji eilutė [0:00:04], kita [0:00:09]
    assert pump_until(lambda: log.exists())
    assert log.read_text().split()[-2:] == ["1.00", "11.00"] and pause.active()
    assert tp.msg.get_text() == f"🔊 slack_{today}_090000 · 0:00:01–0:00:12" and tp.btn_stop.get_sensitive()
    row = tp.ctx.get_row_at_index(1)                                    # [0:00:12] ačiū, kita [0:00:15]
    tp.spin_pad.set_value(0)
    tp.ctx.emit("row-activated", row)
    assert pump_until(lambda: len(log.read_text().splitlines()) == 2)
    assert log.read_text().splitlines()[-1].split()[-2:] == ["12.00", "3.00"]
    tp.stop()
    assert tp.player is None
    tp.ctx.select_row(tp.ctx.get_row_at_index(2))                       # kitos sesijos eilutė — garso nėra
    assert not tp.play_context() and "garso nebėra" in tp.msg.get_text()


def test_background_refresh_keeps_playback_and_typed_name(win, demo):
    """Fone baigęsis pertikrinimas (reload keep_current) nestabdo grojimo ir neperrašo ranka įvesto vardo."""
    tp = win.training
    tp.play()
    p = tp.player
    tp.entry.set_text("Mar")
    write_suggestions(demo, {"nez1": {"name": "Ona", "sim": 0.45, "strong": False}})
    tp.reload(keep_current=True)
    assert tp.player is p and p.poll() is None and tp.entry.get_text() == "Mar"
    assert "„Ona“" in tp.lbl_hint.get_text()
    tp.entry.set_text("")
    write_suggestions(demo, {"nez1": {"name": "Rūta", "sim": 0.46, "strong": False}})
    tp.reload(keep_current=True)
    assert tp.entry.get_text() == "Rūta"                                # tuščias laukelis — pasiūlymas įrašomas
    tp.stop()


# ── klaviatūra: Ctrl+Tarpas groja, žymeklis vardo laukelyje, Enter — įrašyti ir groti kitą ──

def key(keyval, state=0):
    from diktatura.ui.gtk import Gdk
    ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    ev.keyval, ev.state = keyval, Gdk.ModifierType(state)
    return ev


def test_ctrl_space_plays_and_puts_cursor_in_name(win, demo, tmp_path, monkeypatch):
    import audio
    from diktatura.ui.gtk import Gdk
    M = Gdk.ModifierType
    tp, played = win.training, tmp_path / "played"
    tp.entry.set_text("Jo")                                             # pradėtas vardas
    tp.btn_play.grab_focus()
    assert win._on_key(win, key(Gdk.KEY_space, M.CONTROL_MASK))
    assert pump_until(lambda: played.exists())
    assert played.read_text().strip().endswith("nez1.wav") and tp.is_playing() and tp.playing == "sample"
    assert tp.entry.is_focus() and tp.entry.get_text() == "Jo"
    assert tp.entry.get_position() == 2 and not tp.entry.get_selection_bounds()   # rašai toliau
    assert win._on_key(win, key(Gdk.KEY_space, M.CONTROL_MASK)) and not tp.is_playing()   # dar kartą — stabdo
    assert not win._on_key(win, key(Gdk.KEY_space))                          # be Ctrl — tarpas vardui
    assert not win._on_key(win, key(Gdk.KEY_space, M.CONTROL_MASK | M.MOD1_MASK))
    assert not win._on_key(win, key(Gdk.KEY_p, M.CONTROL_MASK))
    # Ctrl+Shift+Tarpas — vieta įraše; pasiūlymas laukelyje — pažymėtas (rašant pakeičiamas)
    today = datetime.now().strftime("%Y%m%d")
    audio.write_wav(demo.recordings / f"slack_{today}_090000.wav", audio.speech(20, -20))
    seek = tmp_path / "seek"
    monkeypatch.setenv("DIKTATURA_SEEK_PLAYER", f"{HELPERS / 'fakebin' / 'player-fake'} {{file}} {{start}} {{dur}}")
    monkeypatch.setenv("FAKE_PLAYER_LOG", str(seek))
    tp._prefilled = "Jonas"
    tp.entry.set_text("Jonas")
    assert win._on_key(win, key(Gdk.KEY_space, M.CONTROL_MASK | M.SHIFT_MASK))
    assert pump_until(lambda: seek.exists()) and tp.playing == "context"
    assert tp.entry.is_focus() and tp.entry.get_selection_bounds() == (0, 5)
    assert win._on_key(win, key(Gdk.KEY_space, M.CONTROL_MASK))              # groja vieta — Ctrl+Tarpas perjungia į pavyzdį
    assert tp.playing == "sample" and tp.is_playing()
    tp.tabs.set_visible_child_name("known")                             # registruotų skirtuke — neveikia
    assert not win._on_key(win, key(Gdk.KEY_space, M.CONTROL_MASK))
    win.show_page("text")
    assert not win._on_key(win, key(Gdk.KEY_space, M.CONTROL_MASK))          # kitoje skiltyje — ne Apmokymų reikalas


def test_enter_assigns_and_plays_next_empty_enter_skips(win, demo, tmp_path):
    from diktatura.speakers import store
    tp, played = win.training, tmp_path / "played"
    assert tp.cur.id == "nez1"
    tp.entry.set_text("  ")
    tp.entry.emit("activate")                                           # tuščias Enter — praleisti (nežinai, kas tai)
    assert tp.cur.id == "nez2" and len(store.list_pending()) == 2
    assert tp.msg.get_text() == "⏭ nez1 praleistas — nieko nekeista"
    assert pump_until(lambda: played.exists() and played.read_text().strip().endswith("nez2.wav"))
    tp.entry.set_text("Darius")
    tp.entry.emit("activate")                                           # Enter — įrašo ir groja kitą
    assert store.counts()["Darius"] == 1 and [p.id for p in store.list_pending()] == ["nez1"]
    assert tp.cur.id == "nez1" and tp.entry.get_text() == "" and tp.entry.is_focus()
    assert pump_until(lambda: played.read_text().strip().splitlines()[-1].endswith("nez1.wav"))
    assert tp.is_playing() and tp.playing == "sample"
    tp.entry.set_text("")
    assert not tp.assign() and "tuščias" in tp.msg.get_text()          # mygtukas su tuščiu — klaida, ne praleidimas


def test_existing_name_picked_with_enter_assigns_at_once(win, demo, monkeypatch):
    from diktatura.speakers import store
    from diktatura.ui import gtk, training_page
    tp = win.training
    assert not training_page.enter_pressed()                             # įvykio nėra — ne Enter
    comp = tp.entry.get_completion()
    model = comp.get_model()
    it = model.get_iter_first()
    assert model[it][0] == "Ona"
    before = store.counts()["Ona"]
    monkeypatch.setattr(training_page, "enter_pressed", lambda: False)  # pasirinkta pele — tik įrašo į laukelį
    comp.emit("match-selected", model, it)
    gtk.pump(0.05)
    assert tp.entry.get_text() == "Ona" and len(store.list_pending()) == 2
    monkeypatch.setattr(training_page, "enter_pressed", lambda: True)   # rodyklėmis + Enter — iškart priskiria
    comp.emit("match-selected", model, it)
    assert pump_until(lambda: len(store.list_pending()) == 1)
    assert store.counts()["Ona"] == before + 1 and tp.cur.id == "nez2"
