"""Q13–Q18: ⏳ eigos langelis (ui.progress_dialog), Teksto mygtukas, ikonos meniu punktas, `app --progress`."""
import time
from pathlib import Path

import pytest


@pytest.fixture
def P(env):
    from diktatura import progress
    return progress


@pytest.fixture
def gtk():
    from diktatura.ui import gtk as g
    return g


def busy(P, server=False, now=None):
    now = now or time.time()
    run = P.Job(pid=11, file=Path("/x/vox_20261012_101456.wav"), state="running", start=now - 3725, phase="asr_them",
                audio_sec=6750, info={"phases": list(P.NAMED_PHASES), "phase": "asr_them", "done": 1830,
                                      "total": 6750, "kind": "named"}, left=4875, total=8600, server=server)
    q = [P.Job(pid=12, file=Path("/x/vox_20261012_121811.wav"), state="queued", audio_sec=9, left=30, total=30),
         P.Job(pid=0, file=Path("/x/slack_20261012_140000.wav"), state="pending", audio_sec=1820, left=3100,
               total=3100)]
    return P.Snapshot(now=now, running=run, queued=q, slow=1.8, rates=dict(P.DEFAULTS, n=7), batch_start=now - 4000,
                      batch_done=2)


def dialog(P, snap, **kw):
    from diktatura.ui.progress_dialog import ProgressDialog
    d = ProgressDialog(None, snapshot_fn=lambda: snap, **kw)
    d.refresh()
    d.dlg.show_all()
    d.fill(snap)
    return d


def test_q13_dialog_two_bars_queue_and_buttons(env, P, gtk):
    snap = busy(P)
    d = dialog(P, snap)
    try:
        assert d.lbl_file.get_text() == "vox_20261012_101456.wav · 1:52:30 garso"
        assert d.lbl_phase.get_text().startswith("Etapas 5/6: Transkribuojama: kolegos — 30:30 / 1:52:30")
        assert d.bar_file.get_fraction() == pytest.approx(1 - 4875 / 8600) and d.bar_file.get_text() == "43 %"
        assert "Praėjo 1:02:05 · liko ~1 val. 21 min (≈ " in d.lbl_file_eta.get_text()
        assert d.lbl_total.get_text() == "Visa eilė: 3 f. · 2:22:59 garso · jau baigta 2"
        assert d.bar_total.get_fraction() == pytest.approx(4000 / (4000 + 4875 + 30 + 3100))
        assert d.lbl_total_eta.get_text().startswith("Liko viskam ~2 val. 13 min")
        assert "1.8× lėčiau" in d.lbl_slow.get_text() and d.lbl_slow.get_visible()
        rows = [tuple(r) for r in d.model]
        assert rows == [("vox_20261012_121811.wav", "0:09", "< 1 min", ""),
                        ("slack_20261012_140000.wav", "30:20", "~52 min", "naktinis")]
        assert d.exp_queue.get_label() == "Eilėje (2)" and d.exp_queue.get_visible()
        assert d.b_skip.get_sensitive() and d.b_stop.get_sensitive() and not d.lbl_idle.get_visible()
        assert "7 transkripc." in d.note.get_text()
    finally:
        d.dlg.destroy()


def test_q13_dialog_idle_and_server_modes(env, P, gtk, monkeypatch):
    monkeypatch.setattr(P, "audio_info", lambda f: (65.0, 2))
    idle = P.Snapshot(now=time.time(), rates={"n": 0}, waiting_night=[Path("/x/vox_20261012_070000.wav")])
    d = dialog(P, idle)
    try:
        assert d.lbl_idle.get_visible() and "niekas netranskribuojama" in d.lbl_idle.get_text()
        assert "Be teksto: 1 įr. (1:05 garso) — transkribuos naktinis" in d.lbl_idle.get_text()
        assert not d.cur_box.get_visible() and not d.tot_box.get_visible() and not d.exp_queue.get_visible()
        assert not d.b_skip.get_sensitive() and not d.b_stop.get_sensitive()
        assert "istorijos dar nėra" in d.note.get_text()
        d.fill(busy(P, server=True))
        assert not d.b_skip.get_sensitive() and d.b_stop.get_sensitive()           # ASR serverio darbo nenutrauksi
        assert "ASR serverio" in d.b_skip.get_tooltip_text()
    finally:
        d.dlg.destroy()


def test_q14_skip_and_stop_need_confirmation(env, P, gtk):
    from diktatura.ui import progress_dialog as pd
    from diktatura.ui.gtk import Gtk
    calls = []
    snap = busy(P)
    d = dialog(P, snap, skip_fn=lambda s: calls.append("skip") or "Praleista: x",
               stop_fn=lambda s: calls.append("stop") or "Sustabdyta: 3 f.")
    answers, texts = [Gtk.ResponseType.CANCEL], []

    def run(dlg):
        texts.append(dlg.get_property("text") if isinstance(dlg, Gtk.MessageDialog) else "")
        return answers.pop(0)
    d.run_dialog = run
    try:
        assert d.on_response(pd.SKIP) and calls == []                                  # atšaukta
        assert texts[-1] == "Praleisti šį failą?"
        answers.append(Gtk.ResponseType.OK)
        assert d.on_response(pd.SKIP) and calls == ["skip"]
        assert d.lbl_msg.get_text() == "Praleista: x" and d.lbl_msg.get_visible()
        answers.append(Gtk.ResponseType.DELETE_EVENT)                                  # uždarytas langelis = atšaukta
        assert d.on_response(pd.STOP) and calls == ["skip"]
        answers.append(Gtk.ResponseType.OK)
        assert d.on_response(pd.STOP) and calls == ["skip", "stop"] and texts[-1] == "Sustabdyti visas transkripcijas?"
        assert not d.on_response(Gtk.ResponseType.CLOSE)                                # Uždaryti — langas užsidaro
    finally:
        d.dlg.destroy()


def test_q15_run_loop_closes_and_stops_timer(env, P, gtk):
    from diktatura.ui.progress_dialog import ProgressDialog
    from diktatura.ui.gtk import GLib, Gtk
    n = {"snap": 0}

    def snap_fn():
        n["snap"] += 1
        return busy(P)
    d = ProgressDialog(None, snapshot_fn=snap_fn, interval_ms=50)

    def run(dlg):
        gtk.pump(0.3)                                                                   # laikmatis atnaujina
        return Gtk.ResponseType.CLOSE
    d.run_dialog = run
    d.run()
    assert n["snap"] >= 3 and d._timer is None
    before = n["snap"]
    gtk.pump(0.2)
    assert n["snap"] == before                                                         # uždarius — nebeatnaujina


def test_q16_text_page_button_and_window_open(env, P, gtk, fake_systemd):
    from diktatura.ui.app import MainWindow
    w = MainWindow(auto_refresh=False)
    try:
        assert w.text.btn_progress.get_label() == "⏳ Transkripcija"                   # niekas nevyksta
        w.text.update_progress_button(busy(P))
        assert w.text.btn_progress.get_label() == "⏳ 43 % · liko ~2 val. 13 min · eilėje 2"
        opened = []
        w.open_progress = lambda: opened.append(1)
        w.text.on_progress()
        assert opened == [1]
    finally:
        w.destroy()
        gtk.pump(0.02)


def test_q16_window_open_progress_single_instance(env, P, gtk, fake_systemd, monkeypatch):
    from diktatura.ui import progress_dialog as pd
    from diktatura.ui.app import MainWindow
    runs = []

    class Fake:
        def __init__(self, parent):
            self.dlg = type("D", (), {"present": lambda s: runs.append("present")})()

        def run(self):
            runs.append("run")
            assert w.open_progress() is False                                         # antras kartas — tik iškelia
    monkeypatch.setattr(pd, "ProgressDialog", Fake)
    w = MainWindow(auto_refresh=False)
    try:
        assert w.open_progress() is False
        assert runs == ["run", "present"] and w._progress is None
    finally:
        w.destroy()
        gtk.pump(0.02)


def test_q17_tray_progress_item_and_opener(env, P, gtk, monkeypatch):
    from diktatura.ui import tray
    from test_main_window import FakeIndicator
    snaps = {"s": P.Snapshot(now=time.time())}
    opened = []
    t = tray.Tray(indicator=FakeIndicator(), opener=opened.append, state_fn=lambda: "proc", mode_fn=lambda: "vox",
                  pending_fn=lambda: 0, timers=False, progress_fn=lambda: snaps["s"])
    assert not t.it_progress.get_visible()
    snaps["s"] = busy(P)
    t.update()
    assert t.it_progress.get_visible() and t.it_progress.get_label() == "⏳ 43 % · liko ~2 val. 13 min · eilėje 2"
    t.it_progress.activate()
    assert opened == ["progress"]
    t.progress_fn = lambda: 1 / 0                                                      # eigos klaida — ikona nelūžta
    assert t.update() and not t.it_progress.get_visible()
    popen = []
    monkeypatch.setattr(tray.subprocess, "Popen", lambda args, **kw: popen.append(args))
    tray.open_app("progress")
    tray.open_app("settings")
    assert popen[0][-3:] == ["--page", "text", "--progress"] and popen[1][-2:] == ["--page", "settings"]


def test_q18_app_progress_flag(env):
    from diktatura.ui.app import parse_args
    assert parse_args(["--progress"]).progress and not parse_args(["--page", "text"]).progress


def test_q19_dialog_wave_shows_processed_part(env, P, gtk):
    from diktatura import waveform
    pf = env.recordings / "vox_20261012_101456.peaks"
    waveform.write(pf, waveform.Peaks(10, 2, bytes([200, 200] * 67500)))     # 1:52:30
    snap = busy(P)
    snap.running.file = env.recordings / "vox_20261012_101456.wav"
    snap.running.info.update(pos=1830.0, skip=[False, False])
    d = dialog(P, snap)
    try:
        assert d.wave.get_visible() and d.wave.peaks.frames == 67500
        assert d.wave.processed == [6750.0, 1830.0]                            # Tu — visas, kolegos — iki 30:30
        snap.running.info["peaks"] = str(env.recordings / "nėra.peaks")       # smailių nėra (sena versija)
        d.fill(snap)
        assert not d.wave.get_visible()
        d.fill(P.Snapshot(now=time.time(), rates={"n": 0}))                   # niekas nevyksta
        assert not d.wave.get_visible()
    finally:
        d.dlg.destroy()
