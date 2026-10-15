"""C6–C8, B6, D3 (VOX): tikras `python -m diktatura.audio.vox` su sintetiniu capture (DIKTATURA_CAPTURE_CMD)."""
import os
import re
import signal
import subprocess
import sys
import time

import audio
from testenv import PCM_GEN
from diktatura.audio.vox import PREROLL

VOX = [sys.executable, "-m", "diktatura.audio.vox"]


def capture(*segments, speed=0, hold=False, marks=None):
    cmd = f"{sys.executable} {PCM_GEN} {' '.join(segments)} --speed {speed}"
    if hold:
        cmd += " --hold"
    if marks:
        cmd += f" --marks {marks}"
    return cmd


def run_vox(env, cap, timeout=30):
    return subprocess.run(VOX, env={**os.environ, "DIKTATURA_CAPTURE_CMD": cap},
                          capture_output=True, text=True, timeout=timeout)


def vox_files(env, ext="wav"):
    return sorted(env.recordings.glob(f"vox_*.{ext}"))


def wait_for(cond, timeout=10.0, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def test_c6_short_blip_file_deleted(env):
    env.write_conf(AUTOTRANSCRIBE=0, VOX_MIN_SEC=1.5, VOX_SILENCE_SEC=5)
    r = run_vox(env, capture("silence:-70:3", "speech:-20:0.3", "silence:-70:6"))
    assert r.returncode == 3, r.stdout + r.stderr          # capture baigėsi -> 3 (systemd perkrautų)
    assert vox_files(env) == []
    assert "per trumpas" in env.log("autorecord")


def test_c7_preroll_and_stereo_layout(env):
    env.write_conf(AUTOTRANSCRIBE=0, VOX_SILENCE_SEC=5)
    run_vox(env, capture("silence:-70:3", "speech:-20:2", "silence:-70:6"))
    [f] = vox_files(env)
    data, sr = audio.read_wav(f)
    assert sr == 16000 and data.shape[1] == 2
    chunks = len(data) // 1600
    assert chunks == PREROLL + 20 + 50                       # pre-roll + 2 s kalbos + 5 s tylos
    left = audio.chunk_levels(data[:, 0])
    assert max(left[:PREROLL]) < -60                         # pre-roll = tyla prieš kalbą
    assert min(left[PREROLL:PREROLL + 20]) > -30             # tada kalba
    assert max(audio.chunk_levels(data[:, 1])) < -60         # R (sistema) — tylus


def test_c8_state_file_and_clean_sigterm(env):
    env.write_conf(AUTOTRANSCRIBE=1, MODE="immediate")
    state = env.run / "recording"
    p = subprocess.Popen(VOX, env={**os.environ, "DIKTATURA_CAPTURE_CMD":
                                   capture("silence:-70:3", *["speech:-20:2 silence:-70:0.5"] * 13, hold=True)},
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        assert wait_for(state.exists), "būsenos failas turi atsirasti įrašant"
        kind, path = state.read_text().split(" ", 1)
        assert kind == "vox" and path.endswith(".wav")
        time.sleep(0.8)                                      # VOX suvartoja visą (greitą) kalbą, toliau laukia
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=5) == 0
    finally:
        if p.poll() is None:
            p.kill()
    assert not state.exists(), "po SIGTERM būsenos failas išvalytas"
    [f] = vox_files(env)
    data, _ = audio.read_wav(f)                              # wav antraštė teisinga (uždarytas)
    assert len(data) >= 16000 * 30
    log = env.log("autorecord")
    assert "servisas stabdomas" in log                       # transkripcija nepaleista (systemd ją nužudytų)
    assert not list(env.recordings.glob("*.txt"))


def test_b6_config_change_applies_while_running(env, tmp_path):
    env.write_conf(AUTOTRANSCRIBE=0, VOX_SILENCE_SEC=12)
    marks = tmp_path / "marks"
    p = subprocess.Popen(VOX, env={**os.environ, "DIKTATURA_CAPTURE_CMD": capture(
        "silence:-70:3", "speech:-20:2", "silence:-70:20", speed=5, marks=marks)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert wait_for(lambda: marks.exists() and len(marks.read_text().splitlines()) >= 3, 15)
        env.write_conf(AUTOTRANSCRIBE=0, VOX_SILENCE_SEC=2)   # tyla prasidėjo — pakeičiam nustatymą
        p.wait(timeout=20)
    finally:
        if p.poll() is None:
            p.kill()
    [f] = vox_files(env)
    dur = len(audio.read_wav(f)[0]) / 16000
    # be pakeitimo: 0.8 + 2 + 12 = 14.8 s; su pakeitimu: uždaro per ≤ 5 s (perskaitymas) + 2 s
    assert dur < 12, f"naujas VOX_SILENCE_SEC nepritaikytas (įrašas {dur:.1f}s)"


def test_d3_vox_immediate_transcribes_and_archives(env, fake_asr):
    env.write_conf(AUTOTRANSCRIBE=1, MODE="immediate", ARCHIVE_MP3=1)
    run_vox(env, capture("silence:-70:3", "speech:-20:2", "silence:-70:6"))
    assert wait_for(lambda: vox_files(env, "named.txt") and vox_files(env, "mp3") and not vox_files(env), 15), \
        "turi atsirasti tekstas + mp3, o wav po archyvavimo — ištrintas"


def test_d3_vox_deferred_and_disabled_do_not_transcribe(env, fake_asr):
    for conf, msg in (({"MODE": "deferred"}, "deferred"), ({"AUTOTRANSCRIBE": 0}, "išjungta")):
        for f in env.recordings.glob("*"):
            f.unlink()
        env.write_conf(**conf)
        run_vox(env, capture("silence:-70:3", "speech:-20:2", "silence:-70:6"))
        time.sleep(0.5)
        assert len(vox_files(env)) == 1 and not vox_files(env, "named.txt")
        assert msg in env.log("autorecord")


# ── C10: pasenusios triukšmo grindys tikrame daemon'e (2026-10-13 incidentas) ──

def test_c10_stale_floor_background_never_becomes_endless_recording(env):
    env.write_conf(AUTOTRANSCRIBE=0, VOX_SILENCE_SEC=5)
    # grindys išmoktos, kai mikrofonas buvo nutilęs (−92), tada 2 s kalbos ir 30 s pastovaus ventiliatoriaus (−66)
    r = run_vox(env, capture("silence:-92:3:LR", "speech:-20:2", "noise:-66:30:LR"))
    assert r.returncode == 3
    [f] = vox_files(env)
    dur = len(audio.read_wav(f)[0]) / 16000
    assert dur < 13, f"įrašas turėjo užsidaryti netrukus po kalbos, o truko {dur:.1f} s"
    log = env.log("autorecord")
    assert re.search(r"↕ fonas garsesnis nei išmoktas triukšmo lygis \(-9\d → -66 dB\)", log)   # −92 + int16 kvantavimas
    assert log.count("🔴 garsas aptiktas") == 1                  # ventiliatorius naujo įrašo nebeatidaro


def test_c10_stale_floor_background_only_file_deleted(env):
    env.write_conf(AUTOTRANSCRIBE=0)
    run_vox(env, capture("silence:-92:3:LR", "noise:-66:30:LR"))
    assert vox_files(env) == [] and "per trumpas" in env.log("autorecord")


# ── C11: garso įrenginių sekimas (2026-10-13: PulseAudio perkėlė „sistemos" srautą į mikrofoną) ──

OUTPUTS = """Source Output #300
\tDriver: protocol-native.c
\tSource: 4
\tProperties:
\t\tmedia.name = "record"
\t\tapplication.name = "diktatura-vox-mic"
\t\tapplication.process.id = "4242"
Source Output #301
\tSource: 4
\tProperties:
\t\tapplication.name = "diktatura-vox-sistema"
\t\tapplication.process.id = "4242"
Source Output #302
\tSource: 0
\tProperties:
\t\tapplication.name = "Slack"
\t\tapplication.process.id = "999"
"""
SOURCES = "0\tspk.monitor\tmodule-alsa-card.c\ts16le 2ch 48000Hz\tSUSPENDED\n4\tmic.a\tmodule-alsa-card.c\ts16le 2ch 48000Hz\tRUNNING\n"


def test_c11_parse_streams_and_mismatch():
    from diktatura.audio import vox
    streams = vox.parse_streams(OUTPUTS, SOURCES, 4242)
    assert streams == {vox.APP_MIC: "mic.a", vox.APP_SYS: "mic.a"}       # kito proceso (Slack) srautas nematomas
    devs = ("mic.a", "spk.monitor")
    assert vox.mismatch(devs, devs, streams) == \
        "PulseAudio perkėlė sistemos garso srautą į mic.a (turi būti spk.monitor)"
    assert vox.mismatch(devs, devs, {vox.APP_MIC: "mic.a", vox.APP_SYS: "spk.monitor"}) is None
    assert vox.mismatch(devs, devs, {}) is None                           # srautų dar nėra — nieko nedarom
    assert vox.mismatch(devs, ("mic.b", "spk.monitor"), {}) == "pasikeitė numatytieji mikrofonas: mic.a → mic.b"
    assert vox.mismatch(devs, ("mic.a", "usb.monitor"), {}) == \
        "pasikeitė numatytieji garsiakalbiai: spk.monitor → usb.monitor"
    assert vox.parse_streams(OUTPUTS, "", 4242) == {vox.APP_MIC: "#4", vox.APP_SYS: "#4"}


def test_c11_device_problem_ignores_pactl_failure(monkeypatch):
    from diktatura.audio import vox

    def boom(*a):
        raise OSError("pulse nepasiekiamas")
    monkeypatch.setattr(vox, "pactl", boom)
    assert vox.device_problem(1, ("mic.a", "spk.monitor")) is None


def test_c11_new_recording_path_never_overwrites(env):
    from diktatura.audio import vox
    a = vox.new_recording_path()
    a.write_bytes(b"x")
    b = vox.new_recording_path()
    assert b != a and b.name.startswith("vox_") and not b.exists()


def test_c11_device_change_closes_recording_and_restarts_capture(env, monkeypatch):
    """main() procese: ~5 s įrašo -> „pasikeitė mikrofonas" -> įrašas išsaugomas, capture paleidžiamas iš naujo,
    vėl 2 s kalibracija, antras įrašas — atskiras failas (ta pati sekundė neperrašo)."""
    from diktatura.audio import vox
    env.write_conf(AUTOTRANSCRIBE=0, VOX_SILENCE_SEC=5)
    monkeypatch.delenv("DIKTATURA_CAPTURE_CMD", raising=False)
    devs = [("mic.a", "spk.monitor"), ("mic.b", "spk.monitor")]
    cmds = [capture("silence:-70:3", "speech:-20:4", hold=True),
            capture("silence:-70:3", "speech:-20:2", "silence:-70:6")]
    checks = []

    def problem(pid, have):
        checks.append(have)
        return "pasikeitė numatytieji mikrofonas: mic.a → mic.b" if len(checks) == 5 else None
    monkeypatch.setattr(vox, "capture_devices", lambda: devs.pop(0))
    monkeypatch.setattr(vox, "capture_cmd", lambda d=None: (cmds.pop(0).split(), f"mic={d[0]}"))
    monkeypatch.setattr(vox, "device_problem", problem)
    monkeypatch.setattr(vox, "DEVICE_EVERY", 10)
    monkeypatch.setattr(vox, "SWITCH_GAP", 0)
    assert vox.main() == 3                                     # antras capture baigėsi
    assert checks[0] == ("mic.a", "spk.monitor") and checks[-1] == ("mic.b", "spk.monitor")
    first, second = vox_files(env)
    assert 2 <= len(audio.read_wav(first)[0]) / 16000 < 4     # pre-roll + ~2 s kalbos iki perjungimo
    assert len(audio.read_wav(second)[0]) / 16000 > 7
    log = env.log("autorecord")
    assert "🔀 pasikeitė numatytieji mikrofonas: mic.a → mic.b — perjungiu garso capture" in log
    assert "🎧 klausau iš naujo: mic=mic.b" in log and log.count("🔴 garsas aptiktas") == 2
    assert not (env.run / "recording").exists()
