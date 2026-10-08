"""E5–E6 [full]: tikras Ąžuolas su lietuviška kalba (Common Voice CC0 klipai, make fixtures).

Lėti (~1–2 min kiekvienas: modelio krovimas + transkripcija). Laukia tikro transkripcijos užrakto.
"""
import subprocess
import sys

import numpy as np
import pytest

import audio
import lt

pytestmark = pytest.mark.full
THREADS = "4"          # paliekam CPU ir tau


@pytest.fixture
def clips():
    c = lt.clips()
    if len(c) < 2:
        pytest.skip("nėra LT fixture'ų — make fixtures")
    return c


def joined(clips, gap=1.0):
    parts = []
    for f, _ in clips:
        parts += [lt.decode(f), np.zeros(int(16000 * gap), dtype=np.float32)]
    return np.concatenate(parts)


def test_e5_lithuanian_wer_with_azuolas(env, real_models, clips):
    wav = env.recordings / "rec_20260101_100000.wav"
    audio.write_wav(wav, joined(clips))
    r = subprocess.run([sys.executable, "-m", "diktatura.asr.transcribe", str(wav),
                        "--model", "azuolas-ct2", "--threads", THREADS], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    hyp = wav.with_suffix(".txt").read_text(encoding="utf-8")
    ref = " ".join(t for _, t in clips)
    w = lt.wer(ref, hyp)
    print(f"WER={w:.1%}\nREF: {ref}\nHYP: {hyp}")
    assert w <= 0.25


def test_e6_stereo_me_and_colleague_lines(env, real_models, clips):
    (me_f, me_t), (them_f, them_t) = clips[0], clips[2 if len(clips) > 2 else 1]
    me, them = lt.decode(me_f), lt.decode(them_f)
    n = len(me) + len(them) + 16000 * 3
    left, right = np.zeros(n, np.float32), np.zeros(n, np.float32)
    left[16000:16000 + len(me)] = me                                    # tu kalbi pirmas
    right[len(me) + 32000:len(me) + 32000 + len(them)] = them          # kolega — po to
    wav = env.recordings / "vox_20260101_100000.wav"
    audio.write_wav(wav, left, right)
    r = subprocess.run([sys.executable, "-m", "diktatura.asr.transcribe_named", str(wav),
                        "--model", "azuolas-ct2", "--threads", THREADS], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    rows = [ln.split("] ", 1)[1].split(":", 1) for ln in
            wav.with_suffix(".named.txt").read_text(encoding="utf-8").splitlines()]
    who = [w for w, _ in rows]
    assert "Tu" in who and any(w.startswith("Kolega?") for w in who), who
    me_text = " ".join(t for w, t in rows if w == "Tu")
    them_text = " ".join(t for w, t in rows if w.startswith("Kolega?"))
    assert lt.wer(me_t, me_text) <= 0.25 and lt.wer(them_t, them_text) <= 0.25
    # nežinomas kolega -> pavyzdys pending (vardui priskirti Apmokymuose)
    assert list(env.pending.glob("nez*.wav"))


def test_asr_server_keeps_model_loaded(env, real_models, clips):
    """Etapas 5: tikras serveris su Ąžuolu — antras darbas nebekrauna modelio (greičiau)."""
    import time
    from diktatura.asr import client
    wav = env.recordings / "rec_20260101_120000.wav"
    audio.write_wav(wav, lt.decode(clips[0][0]))
    p = subprocess.Popen([sys.executable, "-m", "diktatura.asr.server"], stdout=subprocess.DEVNULL)
    try:
        sock = env.run / "asr.sock"
        end = time.monotonic() + 15
        while not sock.exists() and time.monotonic() < end:
            time.sleep(0.1)
        argv = [str(wav), "--model", "azuolas-ct2", "--threads", THREADS]
        r1 = client.request("mono", argv, sock)
        r2 = client.request("mono", argv, sock)
        print(f"1-as (su krovimu): {r1['sec']} s; 2-as (modelis atmintyje): {r2['sec']} s")
        assert r1["rc"] == 0 and r1["loaded"] and r2["rc"] == 0 and not r2["loaded"]
        assert r2["sec"] < r1["sec"]
        assert lt.wer(clips[0][1], wav.with_suffix(".txt").read_text(encoding="utf-8")) <= 0.25
    finally:
        p.terminate()
        p.wait(timeout=20)
