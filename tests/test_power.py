"""PW1–PW5: `make off` / `make on` — viską išjungti, kai trūksta resursų, ir grąžinti tai, kas buvo įjungta."""
import json
import os
import subprocess
import time

import audio
from flowdemo import wait_for
from testenv import REPO

VOX, SLACK = "diktatura-vox.service", "diktatura-autorecord.service"
TIMER, TRAY, ASR = "diktatura-nightly.timer", "diktatura-tray.service", "diktatura-asr.service"


def test_pw1_off_remembers_and_on_restores(env, fake_systemd):
    from diktatura import services
    for u in (VOX, TIMER, TRAY):
        fake_systemd.set(u, active=True, enabled=True)
    (fake_systemd.state / "window.open").touch()
    ok, msg = services.power_off()
    assert ok and "įrašymas VOX, naktinis 01:30, ikona" in msg and "langas uždarytas" in msg and "make on" in msg
    assert not any(services.is_enabled(u) or services.is_active(u) for u in services.POWER_UNITS)
    assert "stop diktatura-nightly.service diktatura-sources.service" in fake_systemd.calls()   # vykstantys darbai
    assert "org.gtk.Actions.Activate quit" in (fake_systemd.state / "gdbus").read_text()
    assert "--dest lt.diktatura.Test" in (fake_systemd.state / "gdbus").read_text()
    st = services.power_state()
    assert st["units"] == [VOX, TIMER, TRAY] and st["at"]
    ok, msg = services.power_off()                                       # antras kartas — būsena neperrašoma tuščia
    assert ok and "jau buvo išjungta" in msg and services.power_state()["units"] == [VOX, TIMER, TRAY]
    ok, msg = services.power_on()
    assert ok and msg == "⏻ Diktatūra įjungta: įrašymas VOX, naktinis 01:30, ikona"
    assert all(services.is_enabled(u) and services.is_active(u) for u in (VOX, TIMER, TRAY))
    assert not services.is_enabled(SLACK) and not services.is_enabled(ASR)
    assert services.power_state() is None and not services.power_file().exists()


def test_pw2_on_keeps_slack_mode_and_asr(env, fake_systemd):
    from diktatura import services
    for u in (SLACK, ASR):
        fake_systemd.set(u, active=True, enabled=True)
    assert services.power_off()[0] and services.recorder_mode() == "off"
    assert services.power_on()[0]
    assert services.recorder_mode() == "slack" and services.is_active(ASR) and not services.is_active(VOX)


def test_pw3_on_without_saved_state(env, fake_systemd):
    from diktatura import services
    ok, msg = services.power_on()
    assert not ok and "make mode-vox" in msg                             # nieko neįjungta ir nebuvo make off
    fake_systemd.set(VOX, enabled=True)                                  # įjungtas, bet sustabdytas (systemctl stop)
    fake_systemd.set(TRAY, enabled=True)
    ok, msg = services.power_on()
    assert ok and services.is_active(VOX) and services.is_active(TRAY) and "įrašymas VOX, ikona" in msg
    services.power_file().parent.mkdir(parents=True, exist_ok=True)
    services.power_file().write_text("{sugadinta")
    assert services.power_state() is None
    services.power_file().write_text(json.dumps({"units": ["kitas.service", TRAY]}))
    assert services.power_on()[1] == "⏻ Diktatūra įjungta: ikona"   # svetimi unit'ai ignoruojami


def test_pw4_cli_make_off_and_doctor(env, fake_systemd):
    from diktatura import doctor, services
    fake_systemd.install_units()
    fake_systemd.set(VOX, active=True, enabled=True)
    r = subprocess.run(["make", "-s", "-C", str(REPO), "off"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.startswith("⏻ Diktatūra išjungta: įrašymas VOX"), r.stderr
    assert not services.is_active(VOX)
    res = doctor.check_services({"ASR_SERVER": False, "MODE": "deferred"})
    assert any(x.status == "warn" and "make off" in x.title and x.fix == "make on" for x in res)
    r = subprocess.run(["python3", "-m", "diktatura.services", "on"], capture_output=True, text=True, cwd=REPO,
                       timeout=30)
    assert r.returncode == 0 and "įrašymas VOX" in r.stdout and services.is_active(VOX)
    assert not any("make off" in x.title for x in doctor.check_services({"ASR_SERVER": False, "MODE": "deferred"}))
    assert subprocess.run(["python3", "-m", "diktatura.services", "x"], cwd=REPO, capture_output=True).returncode == 2
    assert "on: install-units" in (REPO / "Makefile").read_text(encoding="utf-8")


def test_pw5_off_stops_running_transcription_keeps_audio(env, fake_systemd, fake_asr, monkeypatch):
    from diktatura import progress, services
    env.write_conf(ARCHIVE_MP3=0)
    monkeypatch.setenv("FAKE_ASR_SLEEP", "30")
    f = env.recordings / "vox_20261010_100000.wav"
    audio.write_wav(f, audio.speech(1.0), audio.silence(1.0))
    t = time.time() - 3600
    os.utime(f, (t, t))
    p = subprocess.Popen(["bash", str(REPO / "bin" / "transcribe-file.sh"), str(f)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        assert wait_for(lambda: fake_asr.exists() and "start" in fake_asr.read_text(), 20)   # ASR jau vyksta
        ok, msg = services.power_off()
        assert ok and "Sustabdyta: 1 f." in msg
        assert p.wait(timeout=20) != 0
        assert f.exists() and not f.with_suffix(".named.txt").exists()    # garsas liko — tekstą padarys vėliau
        assert not progress.snapshot().active
    finally:
        if p.poll() is None:
            p.kill()
