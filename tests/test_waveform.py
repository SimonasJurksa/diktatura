"""W1–W5: 🌊 garso bangos smailės (diktatura.waveform) ir jų vieta transkripcijos eilėje."""
import os
import time

import numpy as np
import pytest

import audio
from testenv import REPO

TFILE = REPO / "bin" / "transcribe-file.sh"


@pytest.fixture
def W(env):
    from diktatura import waveform
    return waveform


def stereo(path, left_sec=1.0, right_sec=1.0):
    """L: kalba pirmą sekundę, tada tyla; R: tyla, tada kalba."""
    left = np.concatenate([audio.speech(left_sec, -12), audio.silence(right_sec, -70)])
    right = np.concatenate([audio.silence(left_sec, -70), audio.speech(right_sec, -12)])
    audio.write_wav(path, left, right)
    return path


# ── W1: skaičiavimas ir formatas ──

def test_w1_compute_stereo_channels_and_roundtrip(env, W):
    f = stereo(env.recordings / "vox_20261014_100000.wav")
    pk = W.compute(f)
    assert pk.rate == W.RATE and pk.channels == 2 and pk.frames == 20 and pk.duration == pytest.approx(2.0)
    L, R = pk.channel(0), pk.channel(1)
    assert min(L[:10]) > max(L[11:]) + 50 and min(R[11:]) > max(R[:9]) + 50    # kas kada kalba — matosi
    out = env.recordings / "vox_20261014_100000.peaks"
    W.write(out, pk)
    assert W.read(out) == pk and out.stat().st_size == W.HEADER.size + 40
    assert W.peaks_path(f) == out and W.peaks_path(f.with_suffix(".named.txt")) == out


def test_w1_mono_mp3_and_odd_lengths(env, W):
    f = env.recordings / "rec_20261014_100100.wav"
    audio.write_wav(f, audio.speech(1.25, -20))
    mp3 = f.with_suffix(".mp3")
    assert os.system(f"ffmpeg -loglevel error -y -i '{f}' -b:a 48k '{mp3}'") == 0
    pk = W.compute(mp3)
    assert pk.channels == 1 and 12 <= pk.frames <= 14                       # paskutinis nepilnas kadras irgi
    assert W.compute(f).frames == 13


def test_w1_corrupt_or_missing_file_is_none(env, W, tmp_path):
    assert W.read(tmp_path / "nėra.peaks") is None
    (tmp_path / "a.peaks").write_bytes(b"DKPK")
    (tmp_path / "b.peaks").write_bytes(b"XXXX" + bytes(20))
    assert W.read(tmp_path / "a.peaks") is None and W.read(tmp_path / "b.peaks") is None


def test_w1_db_scale(W):
    assert W.encode_db(0) == 255 and W.encode_db(-80) == 0 and W.encode_db(-200) == 0 and W.encode_db(5) == 255
    assert W.decode_db(W.encode_db(-40)) == pytest.approx(-40, abs=0.2)


# ── W2: CLI / ensure ──

def test_w2_cli_ensure_skips_fresh_and_redoes_stale(env, W):
    f = stereo(env.recordings / "vox_20261014_100200.wav")
    out = W.peaks_path(f)
    assert W.main([str(f)]) == 0 and out.exists()
    W.write(out, W.Peaks(10, 2, bytes(4)))                                  # „senas" turinys, bet naujesnis už garsą
    assert W.main([str(f)]) == 0 and W.read(out).frames == 2                # šviežias — neperskaičiuojama
    t = time.time() + 5
    os.utime(f, (t, t))                                                     # garsas pakeistas vėliau
    assert W.main([str(f)]) == 0 and W.read(out).frames == 20
    W.write(out, W.Peaks(10, 2, bytes(4)))
    assert W.main([str(f), "--force"]) == 0 and W.read(out).frames == 20
    assert W.main([str(env.recordings / "nėra.wav")]) == 1


# ── W3: piešimo stulpeliai ──

def test_w3_columns_take_loudest_and_normalize(W):
    ch = bytes([10] * 50 + [200] * 10 + [10] * 40)
    lo, hi = W.scale_of(ch)
    assert lo == 10 and hi == 200
    cols = W.columns(ch, 10, scale=(lo, hi))
    assert cols[5] == 1.0 and cols[0] == 0.0 and len(cols) == 10
    assert W.columns(ch, 4, start=50, end=60, scale=(lo, hi)) == [1.0] * 4  # priartinta dalis
    assert W.columns(b"", 5) == [0.0] * 5 and W.columns(ch, 0) == []
    quiet = bytes([60, 62, 61, 63] * 30)                                    # vien triukšmas — neišpučiamas
    assert max(W.columns(quiet, 20)) < 0.1


def test_w3_more_pixels_than_frames(W):
    cols = W.columns(bytes([0, 255]), 6, scale=(0, 255))
    assert cols == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]


# ── W4: transkripcijos eilė ──

def test_w4_transcribe_file_writes_peaks_first(env, fake_asr):
    env.write_conf(ARCHIVE_MP3=1)
    f = stereo(env.recordings / "vox_20261014_100300.wav")
    r = env.sh("bash", TFILE, f)
    assert r.returncode == 0, r.stdout + r.stderr
    from diktatura import waveform
    pk = waveform.read(env.recordings / "vox_20261014_100300.peaks")
    assert pk is not None and pk.frames == 20
    assert (env.recordings / "vox_20261014_100300.mp3").exists()           # wav -> mp3, banga lieka


def test_w4_empty_text_deletes_peaks_too(env, fake_asr, monkeypatch):
    monkeypatch.setenv("FAKE_ASR_TEXT", "")
    env.write_conf(DELETE_EMPTY=1)
    f = stereo(env.recordings / "vox_20261014_100400.wav")
    assert env.sh("bash", TFILE, f).returncode == 0
    assert list(env.recordings.iterdir()) == []


def test_w4_cleanup_keeps_peaks_with_texts(env, W):
    """Seno garso trynimas trina tik garsą — banga lieka (matoma ir be garso)."""
    from diktatura import cleanup
    base = env.recordings / "vox_20200101_100000"
    for suf in (".mp3", ".named.txt", ".peaks"):
        base.with_name(base.name + suf).write_bytes(b"x" * 100)
    old = time.time() - 400 * 86400
    for p in env.recordings.iterdir():
        os.utime(p, (old, old))
    cleanup.run({"AUDIO_CLEANUP": "age", "AUDIO_KEEP_DAYS": 7, "AUDIO_MAX_GB": 5, "AUTOTRANSCRIBE": 1}, busy=set())
    assert sorted(p.name for p in env.recordings.iterdir()) == ["vox_20200101_100000.named.txt",
                                                                "vox_20200101_100000.peaks"]
