"""L. Kolegų garso nuotėkio šalinimas iš mikrofono kanalo (diktatura.audio.echo) + transkripcijos L paruošimas.

Sintetiniai „balsai" — triukšmas su kalbos tipo gaubtine (skirtingos sėklos -> nekoreliuoti). Nuotėkis — kaip matuota
tikrame kompiuteryje: tiesinis, -20 dB, trumpas FIR, L atsilieka ~1 s.
"""
import subprocess
import wave

import numpy as np
import pytest

from diktatura.audio import echo

SR = 16000


def voice(sec, seed):
    rng = np.random.default_rng(seed)
    n = int(sec * SR)
    env = np.repeat(rng.random(n // 1600 + 1) > 0.45, 1600)[:n].astype(np.float32)   # 0.1 s „skiemenys"
    return (rng.normal(0, 0.1, n) * env).astype(np.float32)


def leak(r, lag, gain_db=-20.0, fir=(1.0, 0.35, -0.2)):
    x = np.convolve(r, np.array(fir, np.float32))[:len(r)] * 10 ** (gain_db / 20)
    return echo.shifted(x.astype(np.float32), lag)


def residual_db(out, user, r_leak):
    """Kiek nuotėkio liko (dB nuo pradinio nuotėkio lygio)."""
    e = out - user
    return 10 * np.log10(np.mean(e ** 2) / np.mean(r_leak ** 2))


@pytest.mark.parametrize("lag_sec", [0.98, 0.0, -0.3])
def test_l1_leak_removed_user_kept(lag_sec):
    R, user = voice(60, 1), voice(60, 2) * 0.5
    lk = leak(R, int(lag_sec * SR))
    L = user + lk
    out, info = echo.cancel(L, R)
    assert info["applied"] and abs(info["lag_ms"] - lag_sec * 1000) <= 1
    assert residual_db(out, user, lk) < -35                                     # nuotėkis nuslopintas ≥ 35 dB
    assert np.corrcoef(out, user)[0, 1] > 0.995                                # tavo balsas nesugadintas


def test_l2_no_leak_nothing_changed():
    R, user = voice(40, 3), voice(40, 4)
    out, info = echo.cancel(user, R)
    assert not info["applied"] and out is user
    out, info = echo.cancel(user, np.zeros_like(user))                         # sistemos garsas tylus
    assert not info["applied"]


def test_l3_chunked_apply_equals_whole():
    R, user = voice(20, 5), voice(20, 6)
    x = echo.shifted(R, 100)
    h, _ = echo.estimate_path(user + leak(R, 100), x)
    a = echo.apply_path(user, x, h, chunk=1 << 20)
    b = echo.apply_path(user, x, h, chunk=3001)                                # daug blokų ribų
    np.testing.assert_allclose(a, b, atol=1e-5)


def test_l4b_short_recording_still_cleaned():
    """Trumpas VOX gabalas skambučio metu (8 s): poslinkis ~1 s vis tiek randamas ir nuotėkis pašalinamas."""
    R, user = voice(8, 9), voice(8, 10) * 0.2
    lk = leak(R, int(0.98 * SR))
    out, info = echo.cancel(user + lk, R)
    assert info["applied"] and abs(info["lag_ms"] - 980) <= 1
    assert residual_db(out, user, lk) < -20
    for seed in range(5):                                                      # trumpas be nuotėkio — neliečiamas
        u = voice(8, 20 + seed)
        assert not echo.cancel(u, voice(8, 40 + seed))[1]["applied"]


def test_l4_short_or_silent_input_does_not_crash():
    for n in (0, 100, SR):
        out, info = echo.cancel(np.zeros(n, np.float32), np.zeros(n, np.float32))
        assert not info["applied"] and len(out) == n


def write_stereo(path, left, right):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(np.stack([left, right], 1), -1, 1) * 32767).astype(np.int16).tobytes())


def read_mono(path):
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def test_l5_transcription_me_channel_cleaned_before_loudnorm(tmp_path):
    """transcribe_named.extract_me: su ECHO_CANCEL L be kolegų kopijos (prieš loudnorm); be jo — kaip anksčiau."""
    from diktatura.asr.transcribe_named import extract_me
    R, user = voice(40, 7), voice(40, 8) * 0.3
    src = tmp_path / "vox_20261009_120000.wav"
    write_stereo(src, user + leak(R, int(0.98 * SR)), R)
    on, off = tmp_path / "on.wav", tmp_path / "off.wav"
    info = extract_me(str(src), str(on), str(tmp_path), enabled=True)
    assert info["applied"] and abs(info["lag_ms"] - 980) <= 1
    assert extract_me(str(src), str(off), str(tmp_path), enabled=False) is None
    a, b = read_mono(on), read_mono(off)
    lag = int(0.98 * SR)
    corr = lambda s: abs(np.corrcoef(s[lag:], R[:len(s) - lag])[0, 1])          # noqa: E731
    assert corr(b) > 0.2 and corr(a) < 0.05                                    # be valymo — R kopija yra
    assert subprocess.run(["ffprobe", "-v", "error", str(on)]).returncode == 0
