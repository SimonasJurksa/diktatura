"""Įrašymo pauzė, kol Diktatūra pati groja garsą (diktatura.pause + VOX)."""
import json
import os
import subprocess
import sys
import time

import audio
from diktatura import pause
from testenv import PCM_GEN

VOX = [sys.executable, "-m", "diktatura.audio.vox"]


def test_hold_release_and_expiry(env):
    assert not pause.active()
    pause.hold(0.5, force=True)
    assert pause.active() and pause.info()["reason"] == "grojama perklausa"
    time.sleep(0.6)
    assert not pause.active(), "pauzė turi pasibaigti pati (jei UI nulūžtų)"
    pause.hold(30, force=True)
    pause.release(0.3)
    assert pause.active() and pause.info()["reason"] == "baigta groti"
    time.sleep(0.4)
    assert not pause.active()


def test_hold_is_throttled_but_force_writes(env):
    pause.hold(10, force=True)
    first = pause.info()["until"]
    pause.hold(100)                                   # < 1 s nuo paskutinio — nerašoma
    assert pause.info()["until"] == first
    pause.hold(100, force=True)
    assert pause.info()["until"] > first


def test_corrupt_pause_file_means_not_paused(env):
    (env.run / "pause").write_text("ne json")
    assert not pause.active()


def run_vox(env, *segments, speed=0):
    cap = f"{sys.executable} {PCM_GEN} {' '.join(segments)} --speed {speed}"
    return subprocess.run(VOX, env={**os.environ, "DIKTATURA_CAPTURE_CMD": cap}, capture_output=True, text=True,
                          timeout=60)


def test_vox_does_not_record_while_paused(env):
    env.write_conf(AUTOTRANSCRIBE=0)
    pause.hold(60, force=True)
    run_vox(env, "silence:-70:3", "speech:-20:4", "silence:-70:6")
    assert not list(env.recordings.glob("vox_*.wav")), "perklausa neturi būti įrašyta"
    assert "pristabdytas" in env.log("autorecord")


def test_vox_closes_open_recording_when_playback_starts(env, tmp_path):
    env.write_conf(AUTOTRANSCRIBE=0)
    marks = tmp_path / "marks"
    cap = f"{sys.executable} {PCM_GEN} silence:-70:3 speech:-20:12 silence:-70:3 --speed 5 --marks {marks}"
    p = subprocess.Popen(VOX, env={**os.environ, "DIKTATURA_CAPTURE_CMD": cap},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.monotonic() + 10
        while not (marks.exists() and len(marks.read_text().splitlines()) >= 2) and time.monotonic() < end:
            time.sleep(0.02)
        time.sleep(0.4)                               # ~2 s kalbos įrašyta
        pause.hold(60, force=True)                    # tada vartotojas spaudžia „▶ Groti"
        p.wait(timeout=30)
    finally:
        if p.poll() is None:
            p.kill()
    [f] = env.recordings.glob("vox_*.wav")
    dur = len(audio.read_wav(f)[0]) / 16000
    assert 1.5 < dur < 7, f"įrašas turėjo užsidaryti prasidėjus perklausai (trukmė {dur:.1f}s iš ~12.8)"
    log = env.log("autorecord")
    assert "pristabdytas" in log and "uždaryta" in log


def test_vox_records_again_after_pause_ends(env):
    env.write_conf(AUTOTRANSCRIBE=0, VOX_SILENCE_SEC=5)
    (env.run / "pause").write_text(json.dumps({"until": time.time() + 2.5, "reason": "t", "pid": 1}))
    # speed 5: 1-a kalba (audio 3–6 s ≈ 0.6–1.2 s) — pauzės metu; 2-a (audio 18 s ≈ 3.6 s) — po pauzės
    run_vox(env, "silence:-70:3", "speech:-20:3", "silence:-70:12", "speech:-20:3", "silence:-70:6", speed=5)
    files = list(env.recordings.glob("vox_*.wav"))
    assert len(files) == 1, files
    dur = len(audio.read_wav(files[0])[0]) / 16000
    assert 7 < dur < 10, f"turėjo būti tik 2-a kalba: pre-roll + 3 s + 5 s tylos (gauta {dur:.1f}s)"
    assert "vėl veikia" in env.log("autorecord")
