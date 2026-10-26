"""QT1–QT6: ikonos „Išeiti" — Diktatūra išjungta, todėl transkripcija nevyksta nematoma.

Vykstanti sustabdoma, naujos (naktinis, sekami aplankai, po įrašo) neprasideda, kol ikona vėl nepaleista; kol atidarytas
langas (laiko užraktą) — galima. Taip pat: eiga (--sources nedaro įrašų katalogo) ir `make status` „Vyksta dabar"."""
import fcntl
import os
import subprocess
import time

import audio
from flowdemo import wait_for
from testenv import REPO

TFILE = REPO / "bin" / "transcribe-file.sh"
TPENDING = REPO / "bin" / "transcribe-pending.sh"


def make_wav(env, name, sec=1.0):
    f = env.recordings / name
    audio.write_wav(f, audio.speech(sec), audio.silence(sec))
    t = time.time() - 3600
    os.utime(f, (t, t))
    return f


def hold_lock(path):
    """Kaip atidarytas langas: laikyti užraktą (grąžina failą — uždarius užraktas dingsta)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fh


def test_qt1_quit_marker_window_lock_and_clear(env):
    from diktatura import paths, services
    assert services.quit_state() is None and not services.transcription_blocked() and not services.window_open()
    paths.QUIT_FILE.write_text('{"at": "2026-10-26T02:00:00"}')
    assert services.quit_state() == {"at": "2026-10-26T02:00:00"} and services.transcription_blocked()
    fh = services.hold_window_lock()                     # atidarytas langas — eiga matoma, galima
    try:
        assert services.window_open() and not services.transcription_blocked()
    finally:
        fh.close()
    assert not services.window_open() and services.transcription_blocked()   # langas uždarytas (ar nulūžo)
    paths.QUIT_FILE.write_text("{sugadinta")
    assert services.quit_state() == {} and services.transcription_blocked()   # sugadinta žymė — vis tiek žymė
    services.clear_quit()
    assert services.quit_state() is None and not services.transcription_blocked()
    services.clear_quit()                                # antras kartas — be klaidos


def test_qt2_quit_app_stops_transcription_and_closes_window(env, fake_systemd, fake_asr, monkeypatch):
    from diktatura import paths, progress, services
    env.write_conf(ARCHIVE_MP3=0)
    monkeypatch.setenv("FAKE_ASR_SLEEP", "30")
    f = make_wav(env, "vox_20261026_010000.wav")
    p = subprocess.Popen(["bash", str(TFILE), str(f)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    try:
        assert wait_for(lambda: fake_asr.exists() and "start" in fake_asr.read_text(), 20)
        (fake_systemd.state / "window.open").touch()
        lines = services.quit_app()
        assert lines[0] == "langas uždarytas" and lines[1].startswith("Sustabdyta: 1 f.")
        assert "org.gtk.Actions.Activate quit" in (fake_systemd.state / "gdbus").read_text()
        assert "stop diktatura-nightly.service diktatura-sources.service" in fake_systemd.calls()
        assert p.wait(timeout=20) != 0
        assert f.exists() and not f.with_suffix(".named.txt").exists()     # garsas liko — tekstą padarys vėliau
        assert not progress.snapshot().active and paths.QUIT_FILE.exists()
        assert services.quit_state()["at"].startswith(time.strftime("%Y-%m-%d"))
        assert services.recorder_mode() == "off" and "disable" not in fake_systemd.calls()   # režimas nekeistas
    finally:
        if p.poll() is None:
            p.kill()


def test_qt3_scripts_do_not_start_while_quit(env, fake_asr):
    from diktatura import paths
    env.write_conf(ARCHIVE_MP3=0)
    f = make_wav(env, "vox_20261026_020000.wav")
    paths.QUIT_FILE.write_text("{}")
    r = env.sh("bash", TFILE, f)                                       # po įrašo (iškart režimas) / eilė
    assert r.returncode == 0 and not fake_asr.exists() and not f.with_suffix(".named.txt").exists()
    assert "PRALEISTA — Diktatūra išjungta (ikonos „Išeiti“), transkribuos vėliau: vox_20261026_020000.wav" \
        in env.log("transcribe")
    r = env.sh("bash", TPENDING)                                       # naktinis — pasako, kodėl nieko nedaro
    assert r.returncode == 0 and not fake_asr.exists() and "Diktatūra išjungta" in r.stderr
    r = env.sh("bash", TPENDING, "--sources")                          # timer'is kas 2 min — tylus
    assert r.returncode == 0 and r.stderr == "" and not fake_asr.exists()
    fh = hold_lock(paths.WINDOW_LOCK)                                  # atidarytas langas — galima
    try:
        r = env.sh("bash", TFILE, f)
        assert r.returncode == 0 and f.with_suffix(".named.txt").exists() and "start" in fake_asr.read_text()
    finally:
        fh.close()


def test_qt3_make_transcribe_pending_ignores_quit(env, fake_asr):
    from diktatura import paths
    env.write_conf(ARCHIVE_MP3=0)
    f = make_wav(env, "vox_20261026_030000.wav")
    paths.QUIT_FILE.write_text("{}")
    r = subprocess.run(["make", "-s", "-C", str(REPO), "transcribe-pending"], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    assert f.with_suffix(".named.txt").exists()                        # terminale matosi — padaro


def test_qt3_bash_gate_equals_python(env):
    """bin/common.sh app_quit = services.transcription_blocked (tie patys keliai ir užraktas)."""
    from diktatura import paths, services

    def bash_blocked():
        return subprocess.run(["bash", "-c", f". '{REPO}/bin/common.sh'; app_quit"]).returncode == 0
    assert not bash_blocked() and not services.transcription_blocked()
    paths.QUIT_FILE.write_text("{}")
    assert bash_blocked() and services.transcription_blocked()
    fh = hold_lock(paths.WINDOW_LOCK)
    try:
        assert not bash_blocked() and not services.transcription_blocked()
    finally:
        fh.close()
    assert bash_blocked()
    assert subprocess.run(["bash", "-c", f". '{REPO}/bin/common.sh'; app_quit"],
                          env={**os.environ, "DIKTATURA_IGNORE_QUIT": "1"}).returncode == 1


def test_qt4_sources_run_queue_excludes_recordings(env, fake_asr, monkeypatch, tmp_path):
    """--sources (sekamų aplankų mygtukas / timer'is) daro tik aplankus: įrašų katalogo failai — ne jo eilėje
    (anksčiau eilė rodė „eilėje 234 · liko ~4 val.", nors jų niekas nedarė), o „laukia naktinio"."""
    from diktatura import progress, sources
    env.write_conf(ARCHIVE_MP3=0)
    monkeypatch.setenv("FAKE_ASR_SLEEP", "20")
    phone = tmp_path / "Telefonas"
    phone.mkdir()
    for n in ("a.wav", "b.wav"):
        audio.write_wav(phone / n, audio.speech(1.0, -20))
        t = time.time() - 3600
        os.utime(phone / n, (t, t))
    sources.add("Telefonas", phone)
    vox = make_wav(env, "vox_20261026_040000.wav")
    p = subprocess.Popen(["bash", str(TPENDING), "--sources"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    try:
        assert wait_for(lambda: progress.snapshot().running is not None, 15)
        s = progress.snapshot()
        assert s.running.name == "a.wav" and [(j.name, j.state) for j in s.queued] == [("b.wav", "pending")]
        assert s.waiting_night == [vox]
        assert progress.now_lines(s)[0].startswith("⏳ transkribuojama: a.wav — ")
        assert progress.now_lines(s)[0].endswith(" · eilėje 1")
    finally:
        os.killpg(p.pid, 9)
        p.wait()


def test_qt5_status_now_lines_and_doctor(env, fake_systemd):
    from diktatura import doctor, paths, progress
    assert progress.now_lines() == []
    r = subprocess.run(["python3", "-m", "diktatura.progress", "--now"], capture_output=True, text=True, cwd=REPO,
                       timeout=30)
    assert r.returncode == 0 and r.stdout.strip() == ""
    paths.QUIT_FILE.write_text('{"at": "2026-10-26T02:15:09"}')
    line = progress.now_lines()[0]
    assert line.startswith("⏻ Diktatūra išjungta ikonos „Išeiti“ (2026-10-26 02:15) — transkripcijos neprasideda")
    assert "make tray-on" in line and "kol atidarytas langas" not in line
    fh = hold_lock(paths.WINDOW_LOCK)
    try:
        assert "(kol atidarytas langas — prasideda)" in progress.now_lines()[0]
    finally:
        fh.close()
    res = doctor.check_services({"ASR_SERVER": False, "MODE": "deferred"})
    w = [x for x in res if "ikonos „Išeiti“" in x.title]
    assert w and w[0].status == "warn" and w[0].fix.startswith("make tray-on") and "02:15:09" in w[0].title
    mk = (REPO / "Makefile").read_text(encoding="utf-8")              # make status (tikras systemctl — netestuojam)
    assert "-m diktatura.progress --now" in mk and "DIKTATURA_IGNORE_QUIT=1 bash $(REPO)/bin/transcribe-pending.sh" in mk


def test_qt6_tray_main_clears_quit(env, monkeypatch):
    """Ikonos paleidimas (programų meniu / dokas / make tray-on) = Diktatūra vėl įjungta."""
    from diktatura import paths
    from diktatura.ui import gtk, tray
    paths.QUIT_FILE.write_text("{}")
    made = []
    monkeypatch.setattr(tray, "Tray", lambda: made.append(1))
    monkeypatch.setattr(gtk.Gtk, "main", lambda: None)
    tray.main()
    assert made == [1] and not paths.QUIT_FILE.exists()
