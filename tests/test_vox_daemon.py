"""C6–C8, B6, D3 (VOX): tikras `python -m diktatura.audio.vox` su sintetiniu capture (DIKTATURA_CAPTURE_CMD)."""
import os
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
                                   capture("silence:-70:3", "speech:-20:30", hold=True)},
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
