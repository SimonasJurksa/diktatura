"""PE1–PE4: pilnas kelias BE tikro garso įrenginio (sintetinis capture) ir be Ąžuolo (netikras ASR):
VOX -> wav -> eilė -> tekstas + 🌊 banga + mp3 -> Teksto langas -> MCP paieška -> eksportas -> seno garso trynimas.
Tikras PulseAudio / Ąžuolas — tests/e2e ir make test-full."""
import json
import os
import subprocess
import time

import audio
from flowdemo import wait_for
from testenv import REPO


def test_pe1_vox_to_text_wave_and_archive(flow):
    from diktatura import sessions, waveform
    texts = sorted(flow.recordings.glob("vox_*.named.txt"))
    for t in texts:
        base = sessions.base_name(t.name)
        assert (flow.recordings / f"{base}.mp3").exists() and not (flow.recordings / f"{base}.wav").exists()
        pk = waveform.read(flow.recordings / f"{base}.peaks")
        assert pk is not None and pk.channels == 2 and 3 <= pk.duration <= 8
        assert sessions.audio_for(t).suffix == ".mp3"
    log = flow.log("transcribe")
    assert log.count("ANALIZĖ baigta") == 2 and log.count("wav→mp3") == 2 and "EILĖJE" in log   # antras laukė eilėje
    assert "per trumpas" in flow.log("autorecord")


def test_pe3_mcp_sees_the_same_texts(flow):
    msgs = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "search", "arguments": {"query": "migracij", "speaker": "Tu"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "speaker_stats", "arguments": {}}})]
    r = subprocess.run([str(REPO / "bin" / "mcp-server.sh")], input="\n".join(msgs) + "\n", capture_output=True,
                       text=True, timeout=30)
    out = {m["id"]: m for m in map(json.loads, r.stdout.splitlines())}
    assert out[1]["result"]["content"][0]["text"].startswith("Rasta: 2")
    assert "- Ona:" in out[2]["result"]["content"][0]["text"]


def test_pe4_cleanup_removes_audio_keeps_text_and_wave(flow, monkeypatch):
    from diktatura import cleanup
    future = time.time() + 40 * 86400                                            # „po 40 dienų" (laikas — iš vardo)
    monkeypatch.setattr(cleanup.time, "time", lambda: future)
    done = cleanup.run({"AUDIO_CLEANUP": "age", "AUDIO_KEEP_DAYS": 7, "AUDIO_MAX_GB": 5, "AUTOTRANSCRIBE": 1}, busy=set())
    assert len(done.delete) == 2
    left = sorted(p.suffix for p in flow.recordings.iterdir())
    assert left == [".peaks", ".peaks", ".txt", ".txt"]
    assert "senas garsas ištrintas" in flow.log("transcribe")


def test_pe5_queue_three_at_once_runs_sequentially(env, fake_asr, monkeypatch):
    """Trys failai vienu metu — po vieną (flock), visi gauna tekstą, ⏳ eiga juos mato."""
    from diktatura import progress
    env.write_conf(ARCHIVE_MP3=0)
    monkeypatch.setenv("FAKE_ASR_SLEEP", "1")
    files = []
    for i in range(3):
        f = env.recordings / f"vox_2026101{i}_100000.wav"
        audio.write_wav(f, audio.speech(1.0), audio.silence(1.0))
        t = time.time() - 3600
        os.utime(f, (t, t))
        files.append(f)
    procs = [subprocess.Popen(["bash", str(REPO / "bin" / "transcribe-file.sh"), str(f)], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, start_new_session=True) for f in files]
    assert wait_for(lambda: progress.snapshot().running is not None, 10)
    s = progress.snapshot()
    assert len(s.jobs) == 3 and s.left > 0
    assert [p.wait(timeout=60) for p in procs] == [0, 0, 0]
    ev = [ln.split()[0] for ln in fake_asr.read_text().splitlines()]
    assert ev == ["start", "end"] * 3                                             # niekada dviese
    assert all(f.with_suffix(".named.txt").exists() for f in files)
    assert not progress.snapshot().active
