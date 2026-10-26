"""QT7–QT9 per UI: ikonos „Išeiti" (vyksta transkripcija — paklausti, tada Diktatūra išjungiama), lango uždarymas, kai
Diktatūra išjungta, ir lango užraktas (kol langas atidarytas — transkripcija matoma, todėl leidžiama)."""
import os
import subprocess
import time
from pathlib import Path

import pytest

from testenv import REPO


@pytest.fixture
def gtk():
    from diktatura.ui import gtk as g
    return g


def active_snap():
    from diktatura import progress
    return progress.Snapshot(now=time.time(), running=progress.Job(
        pid=1, file=Path("/x/Susirinkimas.wav"), state="running", left=1800.0, total=3600.0))


def make_tray(snap, **kw):
    from diktatura.ui import tray
    from test_main_window import FakeIndicator
    ind = FakeIndicator()
    t = tray.Tray(indicator=ind, opener=lambda p: None, state_fn=lambda: "proc", mode_fn=lambda: "vox",
                  pending_fn=lambda: 0, timers=False, progress_fn=lambda: snap, **kw)
    return t, ind


def test_qt7_tray_quit_asks_when_transcribing_then_quits_app(env, gtk):
    from diktatura import progress
    calls, asked = [], []
    snap = active_snap()
    t, ind = make_tray(snap, confirm_fn=lambda text: asked.append(text) or False,
                       quit_fn=lambda: calls.append("quit_app"), main_quit=lambda: calls.append("main_quit"))
    labels = [it.get_label() for it in ind.menu.get_children() if it.get_label()]
    assert labels[-1] == "Išeiti (sustabdys transkripciją)"            # iš anksto matosi, kas bus
    assert not t.quit() and calls == []                                 # „Atšaukti" — viskas lieka
    assert "„Susirinkimas.wav“ — 50 % · liko ~30 min" in asked[0] and "sustabdyta (garsas lieka)" in asked[0]
    t.confirm_fn = lambda text: True
    assert t.quit() and calls == ["quit_app", "main_quit"]
    calls.clear()
    asked.clear()
    t, _ = make_tray(progress.Snapshot(now=0), confirm_fn=lambda text: asked.append(text) or False,
                     quit_fn=lambda: calls.append("quit_app"), main_quit=lambda: calls.append("main_quit"))
    assert t.it_quit.get_label() == "Išeiti"
    assert t.quit() and asked == [] and calls == ["quit_app", "main_quit"]   # nieko nevyksta — be klausimo


def test_qt7_tray_quit_without_progress_info_still_quits(env, gtk):
    calls = []

    def broken():
        raise OSError("nėra /proc")
    from diktatura.ui import tray
    from test_main_window import FakeIndicator
    t = tray.Tray(indicator=FakeIndicator(), opener=lambda p: None, state_fn=lambda: "idle", mode_fn=lambda: "vox",
                  pending_fn=lambda: 0, timers=False, progress_fn=broken, confirm_fn=lambda text: False,
                  quit_fn=lambda: calls.append("q"), main_quit=lambda: calls.append("m"))
    assert t.quit() and calls == ["q", "m"]


def test_qt8_window_close_when_quit_asks_and_stops(env, gtk, fake_systemd, monkeypatch):
    from diktatura import paths, progress
    from diktatura.ui.app import MainWindow
    stopped, asked = [], []
    monkeypatch.setattr(progress, "snapshot", active_snap)
    monkeypatch.setattr(progress, "stop_all", lambda snap=None: stopped.append(snap) or "Sustabdyta: 1 f.")
    w = MainWindow(auto_refresh=False)
    try:
        assert w.confirm_close(ask=lambda text: asked.append(text) or False)   # Diktatūra įjungta — be klausimo
        assert asked == [] and stopped == []
        paths.QUIT_FILE.write_text("{}")
        assert not w.confirm_close(ask=lambda text: asked.append(text) or False)   # „Palikti langą"
        assert "Diktatūra išjungta (ikonos „Išeiti“)" in asked[0] and stopped == []
        assert w.confirm_close(ask=lambda text: True) and len(stopped) == 1
        monkeypatch.setattr(progress, "snapshot", lambda: progress.Snapshot(now=0))
        asked.clear()
        assert w.confirm_close(ask=lambda text: asked.append(text) or False) and asked == []   # nieko nevyksta
    finally:
        w.destroy()


def test_qt9_open_window_holds_lock(env, fake_systemd, monkeypatch):
    """Tikras langas (atskiras procesas): kol atidarytas — services.window_open(); uždarytas — užraktas dingsta."""
    from diktatura import paths, services
    app_id = f"lt.diktatura.Lock{os.getpid()}"
    monkeypatch.delenv("DIKTATURA_GDBUS")
    monkeypatch.setenv("DIKTATURA_APP_ID", app_id)
    paths.QUIT_FILE.write_text("{}")
    p = subprocess.Popen(["/usr/bin/python3", "-m", "diktatura.ui.app"], cwd=REPO, env=dict(os.environ),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 15
        while time.time() < deadline and not services.window_open():
            time.sleep(0.2)
        assert services.window_open() and not services.transcription_blocked(), p.stdout.read() if p.poll() else ""
        assert services.close_window() and p.wait(timeout=15) == 0
        assert not services.window_open() and services.transcription_blocked()
    finally:
        if p.poll() is None:
            p.kill()
