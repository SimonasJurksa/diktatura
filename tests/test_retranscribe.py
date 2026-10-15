"""X1–X4: 🔁 „Transkribuoti iš naujo" — bin/transcribe-file.sh su DIKTATURA_RETRANSCRIBE=1 (netikras ASR)."""
import subprocess

import audio
from testenv import REPO

TFILE = REPO / "bin" / "transcribe-file.sh"
OLD = "[0:00:01] Kolega?nez3: senas tekstas\n"


def run(env, *args, **extra):
    return subprocess.run(["bash", str(TFILE), *map(str, args)], capture_output=True, text=True, timeout=60,
                          env={**__import__("os").environ, "DIKTATURA_RETRANSCRIBE": "1", **extra})


def mp3_session(env, name="vox_20261014_090000"):
    wav = env.recordings / f"{name}.wav"
    audio.write_wav(wav, audio.speech(1.0), audio.silence(1.0))
    mp3 = wav.with_suffix(".mp3")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-b:a", "48k", str(mp3)], check=True)
    wav.unlink()
    (env.recordings / f"{name}.named.txt").write_text(OLD, encoding="utf-8")
    return mp3


def test_x1_new_text_replaces_old_and_keeps_prev(env, fake_asr, monkeypatch):
    env.write_conf(ARCHIVE_MP3=1)
    mp3 = mp3_session(env)
    monkeypatch.setenv("FAKE_ASR_TEXT", "[0:00:01] Ona: naujas tekstas")
    r = run(env, mp3)
    assert r.returncode == 0, r.stdout + r.stderr
    txt = env.recordings / "vox_20261014_090000.named.txt"
    assert txt.read_text() == "[0:00:01] Ona: naujas tekstas"
    assert txt.with_name(txt.name + ".prev").read_text() == OLD and mp3.exists()
    assert not list(env.recordings.glob("*.retx")) and "transkribuota iš naujo" in env.log("transcribe")


def test_x2_empty_or_failed_keeps_old_text(env, fake_asr, monkeypatch):
    env.write_conf(DELETE_EMPTY=1)
    mp3 = mp3_session(env)
    txt = env.recordings / "vox_20261014_090000.named.txt"
    monkeypatch.setenv("FAKE_ASR_TEXT", "  ")
    assert run(env, mp3).returncode == 0
    assert txt.read_text() == OLD and mp3.exists() and not list(env.recordings.glob("*.retx"))
    assert "paliktas senasis" in env.log("transcribe")
    monkeypatch.setenv("FAKE_ASR_FAIL", "1")
    assert run(env, mp3).returncode == 1
    assert txt.read_text() == OLD and mp3.exists()


def test_x3_mono_session_text_and_srt(env, fake_asr, monkeypatch):
    wav = env.recordings / "rec_20261014_091000.wav"
    audio.write_wav(wav, audio.speech(1.0))
    (env.recordings / "rec_20261014_091000.txt").write_text("senas\n")
    monkeypatch.setenv("FAKE_ASR_TEXT", "naujas mono")
    assert run(env, wav).returncode == 0
    assert (env.recordings / "rec_20261014_091000.txt").read_text() == "naujas mono"
    assert (env.recordings / "rec_20261014_091000.txt.prev").read_text() == "senas\n"


def test_x4_source_session_with_out_base(env, fake_asr, monkeypatch, tmp_path):
    from diktatura import sources
    d = tmp_path / "Telefonas"
    d.mkdir()
    a = d / "Įrašas.wav"
    audio.write_wav(a, audio.speech(1.0))
    src = sources.add("Telefonas", d)
    base = sources.out_base(src, a)
    base.parent.mkdir(parents=True)
    sources.with_suffix(base, ".named.txt").write_text(OLD)
    monkeypatch.setenv("FAKE_ASR_TEXT", "[0:00:01] Tu: iš naujo")
    assert run(env, a, base).returncode == 0
    assert sources.with_suffix(base, ".named.txt").read_text() == "[0:00:01] Tu: iš naujo"
    assert sources.with_suffix(base, ".named.txt.prev").read_text() == OLD and a.exists()
