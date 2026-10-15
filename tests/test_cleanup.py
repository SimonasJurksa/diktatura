"""P. Seno garso trynimas (diktatura.cleanup, AUDIO_CLEANUP) ir pilnas diskas (VOX / Slack nebelūžta, 0 B failai)."""
import errno
import os
import signal
import subprocess
import sys
import time
import wave
from datetime import datetime, timedelta

import pytest

import audio
from testenv import PCM_GEN, REPO

TFILE = REPO / "bin" / "transcribe-file.sh"
TPENDING = REPO / "bin" / "transcribe-pending.sh"
OLD = 3600                                       # mtime prieš valandą — ne „ką tik keistas"


def name(days_ago, hhmmss="120000", src="vox"):
    return f"{src}_{(datetime.now() - timedelta(days=days_ago)):%Y%m%d}_{hhmmss}"


def put(env, fname, size=1000, age=OLD):
    f = env.recordings / fname
    f.write_bytes(b"\0" * size)
    t = time.time() - age
    os.utime(f, (t, t))
    return f


def session(env, days_ago, hhmmss="120000", exts=(".mp3",), size=1000, text=True):
    base = name(days_ago, hhmmss)
    files = [put(env, base + e, size) for e in exts]
    if text:
        put(env, base + ".named.txt", 10)
    return base, files


@pytest.fixture
def cl(env):
    from diktatura import cleanup, config
    return cleanup, config


def cfg(config, **kv):
    return {**config.load(), **kv}


# ── P1–P3: taisyklės ──

def test_p1_off_deletes_only_empty_files(env, cl):
    cleanup, config = cl
    base, [mp3] = session(env, 30)
    empty = put(env, name(2, "182224") + ".wav", 0)
    header = put(env, name(2, "182255") + ".wav", 44)
    fresh = put(env, name(0, "235959") + ".wav", 0, age=0)                 # ką tik atidarytas — dar rašomas
    busy = put(env, name(0, "235958") + ".wav", 0)
    p = cleanup.run(cfg(config, AUDIO_CLEANUP="off"), busy={busy.stem})
    assert sorted(p.empty) == sorted([empty, header]) and p.delete == []
    assert not empty.exists() and not header.exists() and fresh.exists() and busy.exists() and mp3.exists()
    assert "tušti garso failai" in env.log("transcribe")


def test_p2_age_deletes_old_audio_keeps_texts_and_protected(env, cl):
    cleanup, config = cl
    old, old_files = session(env, 10, exts=(".wav", ".mp3"))               # wav + mp3 — vienas įrašas
    recent, [recent_mp3] = session(env, 3)
    untr, [untr_wav] = session(env, 20, "130000", exts=(".wav",), text=False)   # dar be teksto
    skipped, [skip_wav] = session(env, 20, "140000", exts=(".wav",), text=False)
    put(env, skipped + ".skip", 0)
    busy, [busy_mp3] = session(env, 20, "150000")
    other = put(env, "notes_20200101.mp3", 1000)                           # ne Diktatūros įrašas
    c = cfg(config, AUDIO_CLEANUP="age", AUDIO_KEEP_DAYS=7, AUTOTRANSCRIBE=True)
    p = cleanup.run(c, busy={busy})
    assert [r.base for r in p.delete] == [skipped, old] and p.protected == 2
    assert not any(f.exists() for f in old_files) and not skip_wav.exists()
    assert (env.recordings / (old + ".named.txt")).exists()                # tekstas lieka
    assert recent_mp3.exists() and untr_wav.exists() and busy_mp3.exists() and other.exists()
    assert "senas garsas ištrintas" in env.log("transcribe") and "tekstai palikti" in env.log("transcribe")
    p = cleanup.run({**c, "AUTOTRANSCRIBE": False}, busy=set())            # transkripcija išjungta — niekas nelaukia
    assert [r.base for r in p.delete] == [untr, busy] and not untr_wav.exists()


def test_p3_size_deletes_oldest_until_under_limit_keeps_newest(env, cl, monkeypatch):
    cleanup, config = cl
    monkeypatch.setattr(cleanup, "GB", 1000)                               # 1 „GB" = 1000 B
    a, _ = session(env, 9, size=1000)
    b, _ = session(env, 8, size=1000)
    c_, _ = session(env, 7, size=1000)
    (env.recordings / "bench").mkdir()
    put(env, "bench/huge.wav", 50_000)                                     # pakatalogiai neskaičiuojami
    c = cfg(config, AUDIO_CLEANUP="size", AUDIO_MAX_GB=2.1)                # 3×1000 + 3×10 B tekstų > 2100
    p = cleanup.plan(c, busy=set())
    assert p.total == 3030 and [r.base for r in p.delete] == [a] and p.after <= 2100
    p = cleanup.run({**c, "AUDIO_MAX_GB": 0.5}, busy=set())                # riba mažesnė už vieną įrašą
    assert [r.base for r in p.delete] == [a, b]                            # naujausias lieka, net vienas > ribą
    assert [f.name for f in env.recordings.glob("*.mp3")] == [c_ + ".mp3"]
    assert "vis tiek viršyta" in cleanup.summary(cleanup.plan({**c, "AUDIO_MAX_GB": 0.5}, busy=set()))


# ── P4–P5: transkripcijos eilė ──

def test_p4_empty_wav_deleted_not_transcribed_and_cleanup_after_each(env, fake_asr):
    env.write_conf(ARCHIVE_MP3=0, AUDIO_CLEANUP="age", AUDIO_KEEP_DAYS=7)
    empty = put(env, "vox_20261010_182224.wav", 0)
    r = env.sh("bash", TFILE, empty)
    assert r.returncode == 0 and not empty.exists() and not fake_asr.exists()
    assert "tuščias failas" in env.log("transcribe")
    old, [old_mp3] = session(env, 30)
    f = env.recordings / (name(0, "100000") + ".wav")
    audio.write_wav(f, audio.speech(1.0, -20), audio.silence(1.0))
    assert env.sh("bash", TFILE, f).returncode == 0
    assert not old_mp3.exists() and (env.recordings / (old + ".named.txt")).exists()   # valymas po transkripcijos
    assert f.exists()                                                      # ką tik sutranskribuotas — naujas


def test_p5_nightly_cleans_even_with_nothing_to_transcribe(env, fake_asr):
    env.write_conf(AUDIO_CLEANUP="age", AUDIO_KEEP_DAYS=7)
    _, [old_mp3] = session(env, 30)
    r = env.sh("bash", TPENDING)
    assert r.returncode == 0 and "nieko transkribuoti" in r.stderr and not old_mp3.exists()


# ── P6–P8: VOX ir pilnas diskas ──

def capture(*segments):
    return f"{sys.executable} {PCM_GEN} {' '.join(segments)} --speed 0"


def test_p6_vox_low_disk_does_not_start_or_crash(env):
    env.write_conf(AUTOTRANSCRIBE=0)
    r = subprocess.run([sys.executable, "-m", "diktatura.audio.vox"], capture_output=True, text=True, timeout=30,
                       env={**os.environ, "DIKTATURA_MIN_FREE_MB": str(10 ** 12),
                            "DIKTATURA_CAPTURE_CMD": capture("silence:-70:3", "speech:-20:2", "silence:-70:2",
                                                             "speech:-20:2", "silence:-70:2")})
    assert r.returncode == 3, r.stderr                                     # capture baigėsi — ne traceback
    assert "Traceback" not in r.stderr and list(env.recordings.glob("vox_*")) == []
    assert env.log("autorecord").count("diske liko tik") == 1              # pranešama vieną kartą


def test_p7_vox_disk_full_mid_recording_salvages_and_keeps_running(env, monkeypatch):
    from diktatura.audio import vox
    env.write_conf(AUTOTRANSCRIBE=0, VOX_SILENCE_SEC=5)
    monkeypatch.setenv("DIKTATURA_CAPTURE_CMD", capture("silence:-70:3", "speech:-20:6", "silence:-70:6"))
    real_write, calls, full = wave.Wave_write.writeframes, [0], [False]

    def write(self, data):
        calls[0] += 1
        if calls[0] == 40:                                                 # ~3 s įrašyta — diskas pilnas
            full[0] = True
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(self, data)
    monkeypatch.setattr(wave.Wave_write, "writeframes", write)
    monkeypatch.setattr(vox, "free_mb", lambda _p: 0.0 if full[0] else 1e9)
    old = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    try:
        assert vox.main() == 3                                             # dirbo iki capture pabaigos
    finally:
        signal.signal(signal.SIGTERM, old[0])
        signal.signal(signal.SIGINT, old[1])
    [f] = env.recordings.glob("vox_*.wav")                                 # kalba tęsėsi, bet naujas neatidarytas
    with wave.open(str(f)) as w:
        assert w.getnchannels() == 2 and abs(w.getnframes() / 16000 - 3.9) < 0.15   # 39 gabalai × 0.1 s
    log = env.log("autorecord")
    assert log.count("diskas pilnas") == 1 and "išsaugota 4 s" in log and "diske liko tik" not in log   # 1 pranešimas
    assert not (env.run / "recording").exists()


def test_p8_salvage_fixes_header_or_deletes_tiny(tmp_path):
    from diktatura.audio import vox
    f = tmp_path / "vox_20261010_182224.wav"
    with wave.open(str(f), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\1\0" * 2 * 1600)                                  # antraštėje — 0.1 s
    with open(f, "ab") as fh:
        fh.write(b"\1\0" * 2 * 16000 * 2 + b"\0\0")                        # dar 2 s + pusinis kadras
    assert vox.salvage(f) == pytest.approx(2.1)
    with wave.open(str(f)) as w:
        assert w.getnframes() == 33600
    tiny = tmp_path / "vox_20261010_182255.wav"
    tiny.write_bytes(b"RIFF" + b"\0" * 100)
    assert vox.salvage(tiny) == 0 and not tiny.exists()


def test_p9_slack_low_disk_does_not_record(env, fake_audio, monkeypatch):
    monkeypatch.setenv("DIKTATURA_MIN_FREE_MB", str(10 ** 12))
    env.write_conf(AUTOTRANSCRIBE=0, SLACK_GRACE_SEC=1)
    p = subprocess.Popen(["bash", str(REPO / "bin" / "autorecord.sh")], env={**os.environ, "DIKTATURA_POLL": "0.2"},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        fake_audio.call("ringrtc")
        end = time.monotonic() + 5
        while "diske liko tik" not in env.log("autorecord") and time.monotonic() < end:
            time.sleep(0.1)
        time.sleep(0.6)                                                    # dar keli ciklai
    finally:
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=5)
    assert env.log("autorecord").count("diske liko tik") == 1
    assert list(env.recordings.glob("slack_*")) == [] and not (env.run / "recording").exists()
