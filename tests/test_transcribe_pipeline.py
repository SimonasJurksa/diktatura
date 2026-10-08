"""E. Transkripcijos eilė (bin/transcribe-file.sh, bin/transcribe-pending.sh) su netikru ASR."""
import json
import os
import subprocess
import time

import audio
from testenv import REAL, REPO

TFILE = REPO / "bin" / "transcribe-file.sh"
TPENDING = REPO / "bin" / "transcribe-pending.sh"


def make_wav(env, name, stereo=True, sec=1.0, age=None):
    f = env.recordings / name
    sig = audio.speech(sec, -20)
    audio.write_wav(f, sig, audio.silence(sec) if stereo else None)
    if age:
        t = time.time() - age
        os.utime(f, (t, t))
    return f


def trace_names(trace):
    return [ln.split()[2] for ln in trace.read_text().splitlines() if ln.startswith("start")] if trace.exists() else []


def test_stereo_goes_to_named_and_mono_to_txt(env, fake_asr):
    env.write_conf(ARCHIVE_MP3=0)
    st = make_wav(env, "vox_20260101_100000.wav", stereo=True)
    mo = make_wav(env, "rec_20260101_100001.wav", stereo=False)
    for f in (st, mo):
        r = env.sh("bash", TFILE, f)
        assert r.returncode == 0, r.stdout + r.stderr
    assert (env.recordings / "vox_20260101_100000.named.txt").read_text() == "[0:00:01] Tu: labas rytas"
    assert (env.recordings / "rec_20260101_100001.txt").exists()
    assert "2ch" in env.log("transcribe") and "1ch" in env.log("transcribe")


def test_e1_two_requests_run_one_at_a_time(env, fake_asr, monkeypatch):
    env.write_conf(ARCHIVE_MP3=0)
    monkeypatch.setenv("FAKE_ASR_SLEEP", "1")
    a = make_wav(env, "vox_20260101_110000.wav")
    b = make_wav(env, "vox_20260101_110001.wav")
    procs = [subprocess.Popen(["bash", str(TFILE), str(f)], stdout=subprocess.DEVNULL) for f in (a, b)]
    assert [p.wait(timeout=20) for p in procs] == [0, 0]
    ev = [ln.split() for ln in fake_asr.read_text().splitlines()]
    assert [e[0] for e in ev] == ["start", "end", "start", "end"], f"persidengė: {ev}"
    assert "EILĖJE" in env.log("transcribe")


def test_e2_empty_text_deleted_or_kept(env, fake_asr, monkeypatch):
    monkeypatch.setenv("FAKE_ASR_TEXT", "  \n")
    env.write_conf(DELETE_EMPTY=1)
    f = make_wav(env, "vox_20260101_120000.wav")
    assert env.sh("bash", TFILE, f).returncode == 0
    assert not f.exists() and not f.with_suffix(".named.txt").exists()
    env.write_conf(DELETE_EMPTY=0)
    g = make_wav(env, "vox_20260101_120001.wav")
    assert env.sh("bash", TFILE, g).returncode == 0
    assert g.exists() and g.with_suffix(".named.txt").exists()


def test_e2_empty_mono_also_removes_srt(env, fake_asr, monkeypatch):
    monkeypatch.setenv("FAKE_ASR_TEXT", "")
    env.write_conf(DELETE_EMPTY=1)
    f = make_wav(env, "rec_20260101_120002.wav", stereo=False)
    f.with_suffix(".srt").write_text("")
    env.sh("bash", TFILE, f)
    assert not list(env.recordings.glob("rec_20260101_120002.*"))


def test_e3_archive_mp3_with_bitrate(env, fake_asr):
    env.write_conf(ARCHIVE_MP3=1, ARCHIVE_KBPS=32)
    f = make_wav(env, "vox_20260101_130000.wav", sec=3)
    assert env.sh("bash", TFILE, f).returncode == 0
    mp3 = f.with_suffix(".mp3")
    assert mp3.exists() and not f.exists()
    info = json.loads(subprocess.run([REAL["ffprobe"], "-v", "error", "-show_entries", "stream=bit_rate",
                                      "-of", "json", str(mp3)], capture_output=True, text=True).stdout)
    assert int(info["streams"][0]["bit_rate"]) == 32000
    env.write_conf(ARCHIVE_MP3=0)
    g = make_wav(env, "vox_20260101_130001.wav")
    env.sh("bash", TFILE, g)
    assert g.exists() and not g.with_suffix(".mp3").exists()


def test_e3_mp3_input_is_not_reencoded(env, fake_asr):
    env.write_conf(ARCHIVE_MP3=1)
    w = make_wav(env, "vox_20260101_130002.wav")
    mp3 = w.with_suffix(".mp3")
    subprocess.run([REAL["ffmpeg"], "-loglevel", "error", "-i", str(w), str(mp3)], check=True)
    w.unlink()
    before = mp3.stat().st_mtime_ns
    assert env.sh("bash", TFILE, mp3).returncode == 0
    assert mp3.stat().st_mtime_ns == before and mp3.with_suffix(".named.txt").exists()


def test_e4_failed_transcription_keeps_audio(env, fake_asr, monkeypatch):
    monkeypatch.setenv("FAKE_ASR_FAIL", "1")
    f = make_wav(env, "vox_20260101_140000.wav")
    r = env.sh("bash", TFILE, f)
    assert r.returncode == 1 and f.exists() and not f.with_suffix(".named.txt").exists()
    assert "garsas paliktas" in env.log("transcribe")


def test_e7_pending_skips_done_skipped_active_and_fresh(env, fake_asr):
    env.write_conf(ARCHIVE_MP3=0)
    old = 3600
    done = make_wav(env, "vox_20260101_150001.wav", age=old)
    done.with_suffix(".named.txt").write_text("[0:00:01] Tu: jau yra")
    sk = make_wav(env, "vox_20260101_150002.wav", age=old)
    sk.with_suffix(".skip").write_text("")
    make_wav(env, "vox_20260101_150003.wav", age=old)                 # -> transkribuoti
    make_wav(env, "vox_20260101_150004.wav")                          # ką tik keistas -> dar rašomas
    active = make_wav(env, "vox_20260101_150005.wav", age=old)
    (env.run / "recording").write_text(f"vox {active}")               # šiuo metu rašomas (būsenos failas)
    make_wav(env, "slack_20260101_150006.wav", age=old)               # -> transkribuoti
    r = env.sh("bash", TPENDING)
    assert r.returncode == 0, r.stderr
    assert sorted(trace_names(fake_asr)) == ["slack_20260101_150006.wav", "vox_20260101_150003.wav"]
    again = env.sh("bash", TPENDING)                                  # antras kartas — nieko naujo
    assert "nieko transkribuoti" in again.stderr or len(trace_names(fake_asr)) == 2
