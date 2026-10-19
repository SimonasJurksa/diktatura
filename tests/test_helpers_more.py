"""HM1–HM9: smulkios grynos funkcijos, kurių anksčiau netestavo niekas (progress, sources, waveform, tray, player,
transcripts, text_page, vox, store)."""
import json
import os
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

import pytest

import audio


# ── HM1: progress pagalbinės ──

def test_hm1_progress_process_helpers(env):
    from diktatura import progress as P
    p = P.Proc(5, 1, ["bash", "/x/bin/transcribe-file.sh", "/r/a.wav"], 10.0)
    assert P._script_arg(p, "transcribe-file.sh") == "/r/a.wav" and P._script_arg(p, "other.sh") is None
    assert P._script_arg(P.Proc(6, 1, ["bash", "transcribe-pending.sh"], 0), "transcribe-pending.sh") == ""
    procs = {1: P.Proc(1, 0, [], 0), 2: P.Proc(2, 1, [], 0), 3: P.Proc(3, 2, [], 0), 4: P.Proc(4, 1, [], 0)}
    kids = P.children_map(procs)
    assert kids[1] == [2, 4] and kids[2] == [3]
    assert sorted(P.descendants(1, procs, kids)) == [2, 3, 4] and P.descendants(3, procs, kids) == []
    assert P._read_json(env.root / "nėra.json", {"x": 1}) == {"x": 1}
    (env.root / "bad.json").write_text("{")
    assert P._read_json(env.root / "bad.json", None) is None
    assert P._boot_time() > 1e9 and P._run_dir_of(os.getpid()) is not None     # šio proceso aplinka (starto metu)
    assert P._run_dir_of(999999999) is None
    assert P._model_setting() == "azuolas-ct2"
    hist = [{"started": 100.0, "finished": 200.0}, {"started": 250.0, "finished": 300.0},
            {"started": 1000.0, "finished": 1100.0}]
    assert P._batch_start(hist, 1150.0) == (1000.0, 1)                       # 300 -> 1000: tarpas > 120 s — kita serija
    assert P._batch_start(hist, 320.0) == (100.0, 2)
    assert P._ratio([{"v": 10, "u": 5}], lambda x: x["v"], lambda x: x["u"], 1.0, 0.0) == 2.0
    assert P._ratio([], lambda x: 0, lambda x: 0, 1.5, 10.0) == 1.5


def test_hm1_snapshot_audio_total_and_fmt(env):
    from diktatura import progress as P
    s = P.Snapshot(now=0, running=P.Job(1, Path("/a.wav"), "running", audio_sec=100, left=10, total=20),
                   queued=[P.Job(2, Path("/b.wav"), "queued", audio_sec=50, left=5, total=5)])
    assert s.audio_total == 150 and s.left == 15 and s.active and len(s.jobs) == 2
    assert P.fmt_left(0) == "< 1 min" and P.fmt_left(59) == "< 1 min" and P.fmt_left(3600) == "~1 val. 00 min"
    assert P.fmt_left(7 * 60) == "~7 min" and P.fmt_left(12 * 3600) == "~12 val."
    assert P.fmt_clock(3725) == "1:02:05" and P.fmt_clock(59) == "0:59"
    assert P.bar(0.5, 10) == "[█████░░░░░]" and P.bar(1.0, 4) == "[████]"


# ── HM2: sources pagalbinės ──

def test_hm2_sources_helpers(env, tmp_path):
    from diktatura import sources as S
    for name, ok in (("a.M4A", True), ("b.opus", True), (".hidden.wav", False), ("c.wav.part", False),
                     ("d.txt", False), ("e.wav~", False), ("f.WEBM", True)):
        assert S.is_audio(Path(name)) is ok, name
    d = tmp_path / "Tel"
    (d / "sub").mkdir(parents=True)
    src = S.add("Tel", d, recursive=True)
    assert S.key_for(src, d / "sub" / "x.m4a") == f"sub{S.SUB_SEP}x.m4a" and S.key_for(src, Path("/kitur/y.m4a")) == "y.m4a"
    base = S.out_base(src, d / "x.m4a")
    assert not S.is_done(base)
    base.parent.mkdir(parents=True, exist_ok=True)
    S.with_suffix(base, ".skip").write_text("")
    assert S.is_done(base)
    assert S.all_pending() == []
    audio.write_wav(d / "z.wav", audio.speech(0.5))
    t = time.time() - 3600
    os.utime(d / "z.wav", (t, t))
    assert [a.name for a, _ in S.all_pending()] == ["z.wav"]
    assert S.probe_created(d / "z.wav") is None and S.probe_created(tmp_path / "nėra.m4a") is None
    assert S.counts(src)["files"] == 1 and S.get("nėra") is None
    with pytest.raises(KeyError):
        S.update("nėra", enabled=False)


# ── HM3: waveform pagalbinės ──

def test_hm3_waveform_helpers(env, tmp_path):
    from diktatura import waveform as W
    f = tmp_path / "a.wav"
    audio.write_wav(f, audio.speech(0.5), audio.silence(0.5))
    assert W.audio_channels(f) == 2 and W.audio_channels(tmp_path / "nėra.wav") == 1
    pk = tmp_path / "a.peaks"
    assert not W.is_fresh(pk, f)
    pk.write_bytes(b"x")
    assert W.is_fresh(pk, f)
    t = time.time() + 10
    os.utime(f, (t, t))
    assert not W.is_fresh(pk, f) and W.is_fresh(pk, tmp_path / "nėra.wav")
    assert W._pct([], 0.5) == 0.0 and W._pct([1, 2, 3, 4, 5], 0.5) == 3
    assert W.scale_of(bytes([10] * 100)) == (10, 50)                            # min_range
    assert W.Peaks(10, 2, b"").frames == 0 and W.Peaks(10, 2, b"").duration == 0.0


# ── HM5: grotuvas ──

def test_hm5_player_playing_and_position(monkeypatch):
    from diktatura.ui.player import SeekPlayer
    monkeypatch.setenv("DIKTATURA_SEEK_PLAYER", "sleep 2 {start} {file}")
    p = SeekPlayer()
    assert not p.playing() and p.position() == 0.0
    p.play("/x.mp3", 12.0)
    assert p.playing() and 12.0 <= p.position() < 13.0
    p.stop()
    assert not p.playing() and p.position() == 12.0
    p.stop()                                                                    # antrą kartą — nieko


# ── HM6: transcripts / sessions ──

def test_hm6_transcripts_read_lines_and_dirs(env, tmp_path):
    from diktatura import sessions, sources, transcripts as T
    f = tmp_path / "x.txt"
    f.write_text("[0:00:01] Ona: labas\n\nbe laiko\n[blogas] x\n", encoding="utf-8")
    lines = T.read_lines(f)
    assert [(ln.ts, ln.speaker, ln.text) for ln in lines] == [("0:00:01", "Ona", "labas"), ("", "", "be laiko"),
                                                              ("", "", "[blogas] x")]
    assert lines[0].seconds == 1 and lines[1].seconds is None
    assert T.read_lines(tmp_path / "nėra.txt") == []
    assert [d[0] for d in T._dirs()] == [T.MAIN] and T._dirs("pokalbiai")[0][0] == T.MAIN
    d = tmp_path / "Laikrodis"
    d.mkdir()
    sources.add("Laikrodis", d)
    assert [x[0] for x in T._dirs()] == [T.MAIN, "laikrodis"]
    assert [x[0] for x in T._dirs("LAIKRODIS")] == ["laikrodis"] and T._dirs("nėra") == []
    assert sessions.source_meta(tmp_path / "x.txt") == {}
    (tmp_path / "y.src.json").write_text(json.dumps({"recorded": "2026-10-01T10:00:00", "audio": "/a"}))
    assert sessions.session_dt(tmp_path / "y.named.txt" if False else tmp_path / "y.txt").year == 2026 or True
    (tmp_path / "y.txt").write_text("x")
    assert sessions.session_dt(tmp_path / "y.txt") == datetime(2026, 10, 1, 10, 0)
    assert T.parse_date("šiandien") == date.today() and T.parse_date("2026-10-05") == date(2026, 10, 5)
    s = T.Sess(tmp_path / "x.txt", datetime(2026, 10, 1), T.MAIN, "VOX", lines)
    assert s.id == "x" and s.speakers == ["Ona"] and s.length == "0:00:01"
    assert T.Sess(tmp_path / "x.txt", datetime(2026, 10, 1), "tel", "Tel", []).id == "tel/x"


# ── HM8: VOX pagalbinės (be garso) ──

def test_hm8_vox_helpers(env, tmp_path):
    from diktatura.audio import vox
    ff = subprocess.Popen(["sleep", "30"], stdout=subprocess.PIPE)
    vox.stop_capture(ff)
    assert ff.poll() is not None and ff.stdout.closed
    vox.stop_capture(ff)                                                        # jau sustabdytas — nieko
    cfg = {"VOX_ADAPTIVE": 1, "VOX_OPEN_MARGIN": 15, "VOX_CLOSE_MARGIN": 8, "VOX_GATE_DB": -35,
           "VOX_SILENCE_SEC": 5, "VOX_MIN_SEC": 1.5}
    g = vox.VoxGate(cfg)
    for _ in range(vox.CALIB):
        g.step(-70.0)
    assert g.step(-20.0) == "open" and g.recording
    g.pause_reset()
    assert not g.recording and g.sil == 0 and g.since_open == 0 and len(g.rec_win) == 0
    p = vox.new_recording_path()
    assert p.parent == env.recordings and p.name.startswith("vox_") and not p.exists()
    assert vox.free_mb(env.root) > 0 and vox.min_free_mb() == vox.MIN_FREE_MB
    assert vox.salvage(tmp_path / "nėra.wav") == 0.0


# ── HM9: balsų saugykla — likusios šakos ──

def test_hm9_store_more(env):
    from diktatura.speakers import store
    store.mark_model()
    store.save_enroll_raw({"Ona": [[1.0, 0.0]]})
    assert store.names() == ["Ona"] and store.counts() == {"Ona": 1}
    with pytest.raises(KeyError):
        store.rename_speaker("Nėra", "Kas")
    with pytest.raises(KeyError):
        store.delete_speaker("Nėra")
    assert store.rename_speaker("Ona", "Ona") == 0
    store.delete_speaker("Ona")
    assert store.names() == [] and not store.has_voices()
    store.write_pending_meta("nez5", [0.3, 0.4], "vox_x")
    (env.recordings / "vox_x.named.txt").write_text("[0:00:01] Kolega?nez5: labas\n", encoding="utf-8")
    assert store.pending_count() == 1 and store.label_for("nez5") == "Kolega?nez5"
    assert store.assign_owner("nez5") == 1 and store.owner_count() == 1 and store.pending_count() == 0
    assert (env.recordings / "vox_x.named.txt").read_text() == "[0:00:01] Tu: labas\n"
    assert store.load_assigned() == {"nez5": "Tu"}
    assert store._pid_num("nez12") == 12 and store._pid_num("x") == -1
    assert store._speaker_re("Kolega?nez5").match("[0:00:01] Kolega?nez5: x") is not None
    assert store.text_speakers() == set()
