"""Pilno kelio testų bendra dalis (tests/test_pipeline_e2e.py ir tests/ui/test_pipeline_ui.py):
VOX su sintetiniu capture -> 2 įrašai su kalba -> netikras ASR -> tekstai + mp3 + bangos."""
import os
import subprocess
import sys
import time

import pytest

from testenv import PCM_GEN

VOX = [sys.executable, "-m", "diktatura.audio.vox"]


def wait_for(cond, timeout=20.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def run_vox(env, segments, timeout=40):
    cmd = f"{sys.executable} {PCM_GEN} {' '.join(segments)} --speed 0"
    return subprocess.run(VOX, env={**os.environ, "DIKTATURA_CAPTURE_CMD": cmd}, capture_output=True, text=True,
                          timeout=timeout)


@pytest.fixture
def flow(env, fake_asr, monkeypatch):
    """Trys VOX įrašai (2 su kalba, 1 be), iškart transkribuojami netikru ASR, archyvuojami į mp3."""
    env.write_conf(AUTOTRANSCRIBE=1, MODE="immediate", ARCHIVE_MP3=1, DELETE_EMPTY=1, VOX_SILENCE_SEC=2,
                   VOX_MIN_SEC=1.0, RETENTION_DAYS=30)
    monkeypatch.setenv("FAKE_ASR_TEXT", "[0:00:01] Tu: labas rytas, migracija pirmadienį\n[0:00:03] Ona: gerai\n")
    r = run_vox(env, ["silence:-70:3", "speech:-20:2", "silence:-70:3", "speech:-20:2:R", "silence:-70:3",
                      "speech:-20:0.3", "silence:-70:3"])
    assert r.returncode == 3, r.stdout + r.stderr
    wavs = sorted(env.recordings.glob("vox_*.wav"))
    assert len(wavs) == 2                                                        # 0.3 s blyksnis ištrintas
    assert wait_for(lambda: len(list(env.recordings.glob("vox_*.named.txt"))) == 2 and
                    not list(env.recordings.glob("vox_*.wav")), 60), env.log("transcribe")
    return env


