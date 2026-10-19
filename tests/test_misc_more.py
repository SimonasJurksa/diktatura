"""MS1–MS6: žymės (annotations), statistikos nunulinimas (stats), pauzė, rankinis įrašymas (bin/rec-toggle.sh),
VOX vartų pakraščiai, config CLI klaidos — smulkūs, bet nuo jų priklauso matoma elgsena."""
import os
import subprocess
import time
from datetime import datetime

import pytest

from testenv import REPO


# ── MS1: žymės ──

def test_ms1_annotations_shift_tolerant_and_icons(env):
    from diktatura import annotations as A
    A.set_tag("a.named.txt", 3, "labas", "star")
    d = A.load()
    assert A.match(d, "a.named.txt", 3, "labas")["tag"] == "star"
    assert A.match(d, "a.named.txt", 7, "labas")["tag"] == "star"              # eilutė pasislinko — pagal tekstą
    assert A.match(d, "a.named.txt", 3, "kitas") is None and A.match(d, "b.named.txt", 3, "labas") is None
    A.set_tag("a.named.txt", 3, "labas", "task")                              # pakeičia (ne dubliuoja)
    d = A.load()
    assert len(d) == 1 and A.icon(A.match(d, "a.named.txt", 3, "labas")) == A.TAGS["task"]
    assert A.toggle_done("a.named.txt", 3, "labas") is True
    assert A.icon(A.match(A.load(), "a.named.txt", 3, "labas")) == A.DONE_ICON
    assert A.toggle_done("a.named.txt", 3, "labas") is False
    with pytest.raises(KeyError):
        A.toggle_done("a.named.txt", 3, "nėra")
    with pytest.raises(ValueError):
        A.set_tag("a.named.txt", 1, "x", "nežinoma")
    A.set_tag("a.named.txt", 3, "labas", None)
    assert A.load() == {} and A.icon(None) == "" and A.icon({"tag": "star"}) == A.TAGS["star"]
    (env.data / "annotations.json").write_text("{sugadinta")
    assert A.load() == {}                                                      # sugadintas failas — tuščios žymės


# ── MS2: statistikos nunulinimas ──

def test_ms2_stats_reset_clear_counts(env):
    from diktatura import stats
    assert stats.reset_time() is None
    t0 = datetime(2026, 10, 10, 12, 0, 0)
    assert stats.reset(t0) == t0 and stats.reset_time() == t0
    start = datetime(2026, 10, 10, 11, 59, 0)
    assert not stats.counts(start, 30, t0) and stats.counts(start, 60, t0) and stats.counts(start, None, None)
    assert stats.line_time(start, None) == start
    stats.clear()
    assert stats.reset_time() is None
    (env.data / "stats_reset.json").write_text("{}")
    assert stats.reset_time() is None


# ── MS3: pauzė ──

def test_ms3_pause_info_reason_pid_and_expiry(env):
    from diktatura import pause
    pause.hold(2.0, "testas", force=True)
    i = pause.info()
    assert i["reason"] == "testas" and i["pid"] == os.getpid() and i["until"] > time.time()
    pause.release(tail=0.3)
    assert pause.active()
    time.sleep(0.5)
    assert not pause.active() and pause.info() is None


# ── MS4: rankinis įrašymas (rec-toggle) — netikras pactl / ffmpeg (sinusas) ──

def test_ms4_rec_toggle_start_stop(env, fake_audio):
    sh = REPO / "bin" / "rec-toggle.sh"
    r = subprocess.run(["bash", str(sh)], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and r.stdout.startswith("START") and "rec_" in r.stdout
    state = (env.run / "recording").read_text().split()
    assert state[0] == "rec" and (env.run / "rec-toggle.pid").exists()
    time.sleep(1.2)
    r = subprocess.run(["bash", str(sh)], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and r.stdout.startswith("STOP") and "make transcribe FILE=" in r.stdout
    assert not (env.run / "recording").exists() and not (env.run / "rec-toggle.pid").exists()
    [wav] = env.recordings.glob("rec_*.wav")
    import audio
    data, sr = audio.read_wav(wav)
    assert sr == 16000 and data.shape[1] == 2 and len(data) > 1000                        # stereo, antraštė uždaryta


# ── MS5: VOX vartų pakraščiai ──

def test_ms5_vox_gate_edges(env):
    from diktatura.audio.vox import CALIB, PREROLL, VoxGate
    cfg = {"VOX_ADAPTIVE": 1, "VOX_OPEN_MARGIN": 15, "VOX_CLOSE_MARGIN": 8, "VOX_GATE_DB": -35,
           "VOX_SILENCE_SEC": 0.05, "VOX_MIN_SEC": 0.05}
    g = VoxGate(cfg)
    assert g.sil_limit == 1 and g.min_chunks == 0 or g.min_chunks == 1          # ribos: bent 1 gabalas tylos
    for _ in range(CALIB):
        g.step(-70.0)
    assert g.step(-20.0) == "open" and g.rec_chunks == PREROLL + 1               # pre-roll pilnas (buvo ≥ 8 idle)
    assert g.step(-70.0) == "close"                                              # tylos riba 1 gabalas
    g2 = VoxGate(cfg, preroll_chunks=3)
    for _ in range(CALIB):
        g2.step(-70.0)
    g2.step(-20.0)
    assert g2.rec_chunks == 4 and g2.duration == 0.4
    g3 = VoxGate({**cfg, "VOX_ADAPTIVE": 0, "VOX_GATE_DB": -40.0})
    assert g3.thresholds() == (-40.0, -52.0) and g3.step(-45.0) == "idle" and g3.step(-39.0) == "open"
    assert g3.voiced_duration == 0.1


# ── MS6: config CLI klaidos ir pakraščiai ──

def test_ms6_config_cli_errors(env, capsys):
    from diktatura import config
    assert config.main(["get", "NĖRA"]) == 2 and "Nežinomas" in capsys.readouterr().err
    assert config.main(["set", "be_lygybės"]) == 2
    assert config.main(["set", "VOX_SILENCE_SEC=abc"]) == 1 and "✗" in capsys.readouterr().err
    assert config.main(["kažkas"]) == 2
    assert config.main(["path"]) == 0 and str(env.conf_file) in capsys.readouterr().out
    assert config.main(["set", "VOX_SILENCE_SEC=7", "DEBUG=1"]) == 0
    assert config.load()["VOX_SILENCE_SEC"] == 7 and config.load()["DEBUG"] is True
    assert config.main(["show"]) == 0 and "* VOX_SILENCE_SEC" in capsys.readouterr().out   # * = pakeista
    assert config.to_text("AUDIO_MAX_GB", 5.0) == "5" and config.to_text("AUDIO_MAX_GB", 2.5) == "2.5"
    with pytest.raises(ValueError, match="Nežinomas"):
        config.coerce("NĖRA", "1")
    for v, want in (("taip", True), ("ne", False), ("true", True)):
        assert config.coerce("DEBUG", v) is want
    assert config.BY_KEY["MODE"].choice_label("deferred") == "Naktį 01:30"
    assert config.BY_KEY["MODE"].choice_label("x") == "x"
    saved = env.conf_file.read_text(encoding="utf-8")
    assert saved.count("VOX_SILENCE_SEC=7") == 1 and saved.startswith("# Diktatūra")   # komentarai lieka
