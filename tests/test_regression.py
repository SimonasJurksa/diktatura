"""S. Regresija — UŽRAKINTA dabartinė elgsena: jei kuris nors testas čia lūžta, vadinasi kažkas pakeitė tai, ką
savininkas mato ar naudoja (numatytuosius nustatymus, komandas, transkripcijos formatą, eilės taisykles…).
Sąmoningas pakeitimas = atnaujinti ir šį testą (taip pakeitimas tampa matomas peržiūroje), ne „pataisyti" kodą atgal.
"""
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

import audio
from testenv import REPO

# ── S1: numatytieji nustatymai, tipai, grupės ir ribos (Nustatymų lango tvarka) ──
DEFAULTS = {
    "THEME": ("light", "choice", "Išvaizda", ('light', 'dark', 'contrast', 'compact')),
    "WAVEFORM": ("1", "bool", "Išvaizda"),
    "REC_PILL": ("1", "bool", "Išvaizda"),
    "CLEAN_VIEW": ("0", "bool", "Tekstas"),
    "FILLER_WORDS": ("nu,tipo", "words", "Tekstas"),
    "VOX_SILENCE_SEC": ("5", "float", "Įrašymas", 1, 600),
    "VOX_MIN_SEC": ("1.5", "float", "Įrašymas", 0.2, 30),
    "VOX_ADAPTIVE": ("1", "bool", "Įrašymas"),
    "VOX_OPEN_MARGIN": ("15", "float", "Įrašymas", 3, 40),
    "VOX_CLOSE_MARGIN": ("8", "float", "Įrašymas", 1, 30),
    "VOX_GATE_DB": ("-35", "float", "Įrašymas", -80, -5),
    "SLACK_GRACE_SEC": ("4", "float", "Įrašymas", 1, 120),
    "MAX_REC_SEC": ("7200", "int", "Įrašymas", 60, 86400),
    "AUTOTRANSCRIBE": ("1", "bool", "Transkripcija"),
    "MODE": ("immediate", "choice", "Transkripcija", ('immediate', 'deferred')),
    "MODEL": ("azuolas-ct2", "choice", "Transkripcija", ('azuolas-ct2', 'medium')),
    "THREADS": ("6", "int", "Transkripcija", 1, 32),
    "ASR_SERVER": ("0", "bool", "Transkripcija"),
    "ASR_SERVER_IDLE_MIN": ("15", "int", "Transkripcija", 1, 480),
    "ECHO_CANCEL": ("1", "bool", "Transkripcija"),
    "VAD_FILTER": ("1", "bool", "VAD (kalbos filtras)"),
    "VAD_MIN_SPEECH_SEC": ("0.8", "float", "VAD (kalbos filtras)", 0.1, 10),
    "VAD_PAD_SEC": ("0.2", "float", "VAD (kalbos filtras)", 0, 2),
    "VAD_TRIM": ("0", "bool", "VAD (kalbos filtras)"),
    "SPEAKER_THRESHOLD": ("0.5", "float", "Kalbėtojai", 0.3, 0.95),
    "SPEAKER_MARGIN": ("0.1", "float", "Kalbėtojai", 0, 0.5),
    "SPEAKER_SUGGEST": ("0.4", "float", "Kalbėtojai", 0.2, 0.9),
    "DELETE_EMPTY": ("1", "bool", "Archyvas"),
    "ARCHIVE_MP3": ("1", "bool", "Archyvas"),
    "ARCHIVE_KBPS": ("64", "int", "Archyvas", 16, 320),
    "RETENTION_DAYS": ("2", "int", "Archyvas", 1, 365),
    "AUDIO_CLEANUP": ("off", "choice", "Archyvas", ('off', 'age', 'size')),
    "AUDIO_KEEP_DAYS": ("7", "int", "Archyvas", 1, 3650),
    "AUDIO_MAX_GB": ("5", "float", "Archyvas", 0.5, 2000),
    "DEBUG": ("0", "bool", "Debug"),
}


def test_s1_defaults_kinds_groups_ranges_locked(env):
    from diktatura import config
    d = config.defaults()
    got = {}
    for s in config.SCHEMA:
        rng = (s.lo, s.hi) if s.lo is not None else ((s.choices,) if s.choices else ())
        got[s.key] = (d[s.key], s.kind, s.group, *rng)
    assert got == DEFAULTS
    assert list(got) == list(DEFAULTS)                       # tvarka = Nustatymų lango tvarka
    for s in config.SCHEMA:                                  # kiekvienas pasirinkimas turi žmogišką pavadinimą
        assert len(s.choice_labels) == len(s.choices) and s.label and (s.help or s.kind == "bool")


# ── S2: make komandos (savininkas jas naudoja; README / CLAUDE.md jas mini) ──
MAKE_TARGETS = (
    "help doctor debug-on debug-off dlogs status recordings logs tlogs text settings training mode-vox mode-slack "
    "mode-off start off on stop restart restart-all stale rec-toggle config set config-edit config-reset auto-on auto-off "
    "immediate defer "
    "model-azuolas model-medium asr-server-on asr-server-off transcribe-pending transcribe progress cleanup mcp sources "
    "stop-transcribe nightly-on nightly-off nightly-now tray-on tray-off tray-restart speakers name-unknown assign "
    "enroll speakers-migrate speakers-relabel backup-voices restore-voices backups deps setup models model-convert "
    "desktop install-units install uninstall "
    "hooks lint test-privacy test test-full test-e2e fixtures").split()


def test_s2_make_targets_locked_and_in_help(env):
    mk = (REPO / "Makefile").read_text(encoding="utf-8")
    documented = re.findall(r"^([a-z][a-z0-9-]*):[^\n]*##", mk, re.M)
    assert documented == MAKE_TARGETS
    phony = " ".join(re.findall(r"^\.PHONY:((?:.*\\\n)*.*)", mk, re.M)[0].split()).replace("\\", "")
    missing = [t for t in MAKE_TARGETS if t not in phony.split()]
    assert missing == [], f"ne .PHONY (sutaptų su katalogu — kaip buvo `desktop`): {missing}"
    out = subprocess.run(["make", "-s", "-C", str(REPO), "help"], capture_output=True, text=True, timeout=20).stdout
    assert all(t in out for t in MAKE_TARGETS)


# ── S3: bash skriptai, systemd šablonai, modulių importas ──

def test_s3_bash_scripts_syntax(env):
    for f in sorted((REPO / "bin").glob("*.sh")) + sorted((REPO / ".githooks").glob("*")):
        if f.is_file() and f.read_text(encoding="utf-8", errors="replace").startswith("#!"):
            r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
            assert r.returncode == 0, f"{f.name}: {r.stderr}"


def test_s3_systemd_templates_render_and_point_to_repo(env):
    from diktatura import services
    for u in services.UNITS:
        txt = services.render_unit(u)
        assert "@REPO@" not in txt
        for m in re.findall(r"(?:ExecStart|ExecStartPre)=\S*?(/\S+\.(?:sh|py))", txt):
            assert Path(m).exists(), f"{u}: {m}"


def test_s3_all_non_ui_modules_import(env):
    mods = [".".join(p.relative_to(REPO).with_suffix("").parts) for p in (REPO / "diktatura").rglob("*.py")
            if "/ui/" not in str(p) and p.name != "__init__.py"]
    code = "import importlib,sys\nfor m in sys.argv[1:]: importlib.import_module(m)\nprint('ok')"
    r = subprocess.run([sys.executable, "-c", code, *mods], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


def test_s3_stdlib_only_modules_have_no_heavy_imports():
    """paths/config/sessions/… importuoja ir sistemos python3 (UI) — be numpy / faster_whisper / sherpa."""
    for name in ("paths", "config", "sessions", "services", "debug", "annotations", "reset", "cleanup", "progress",
                 "stats", "pause"):
        src = (REPO / "diktatura" / f"{name}.py").read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(numpy|faster_whisper|sherpa_onnx|sklearn)", src, re.M), name
    r = subprocess.run(["/usr/bin/python3", "-c", "import diktatura.progress, diktatura.cleanup, diktatura.reset, "
                        "diktatura.speakers.store; print('ok')"], capture_output=True, text=True, cwd=REPO,
                       env={**os.environ, "PYTHONPATH": str(REPO)}, timeout=30)
    assert r.stdout.strip() == "ok", r.stderr


# ── S4: transkripcijos formatas ir failų vardai ──

def test_s4_transcript_line_format_roundtrip():
    from diktatura import sessions
    from diktatura.asr import dialog
    rows = [(1.4, 3.0, "Tu", "labas rytas"), (65.9, 70, "Ona", "sveikas: kaip sekasi?"), (3725, 3730, "Kolega?nez3", "x")]
    text = dialog.format_rows(rows)
    assert text == "[0:00:01] Tu: labas rytas\n[0:01:05] Ona: sveikas: kaip sekasi?\n[1:02:05] Kolega?nez3: x\n"
    parsed = [sessions.parse_line(ln) for ln in text.splitlines()]
    assert parsed == [("0:00:01", "Tu", "labas rytas"), ("0:01:05", "Ona", "sveikas: kaip sekasi?"),
                      ("1:02:05", "Kolega?nez3", "x")]
    assert [sessions.ts_seconds(p[0]) for p in parsed] == [1, 65, 3725]
    assert sessions.parse_line("be laiko eilutė") is None


def test_s4_names_bases_and_display_filter(env):
    from diktatura import sessions
    assert sessions.parse_name("slack_20261012_143000.named.txt") == ("slack", datetime(2026, 10, 12, 14, 30))
    assert sessions.parse_name("vox_20261399_000000.wav") is None and sessions.parse_name("x.wav") is None
    for n, b in (("vox_a.named.txt", "vox_a"), ("vox_a.clean.dialog.txt", "vox_a"), ("vox_a.dialog.txt", "vox_a"),
                 ("vox_a.txt", "vox_a"), ("vox_a.wav", "vox_a"), ("vox_a.mp3", "vox_a"), ("vox_a.srt", "vox_a"),
                 ("vox_a.skip", "vox_a"), ("vox_a.json", "vox_a.json")):
        assert sessions.base_name(n) == b
    rec = env.recordings
    for n in ("vox_20261012_100000.named.txt", "rec_20261011_090000.txt", "vox_20261012_110000.dialog.txt",
              "slack_20261010_080000.clean.dialog.txt", "notes.md"):
        (rec / n).write_text("[0:00:01] Tu: x\n")
    assert [f.name for f in sessions.text_files(rec)] == [
        "slack_20261010_080000.clean.dialog.txt", "rec_20261011_090000.txt", "vox_20261012_100000.named.txt"]
    assert [f.name for f in sessions.text_files(rec, since=date(2026, 10, 11))] == [
        "rec_20261011_090000.txt", "vox_20261012_100000.named.txt"]
    t = rec / "vox_20261012_100000.named.txt"
    assert sessions.audio_for(t) is None
    (rec / "vox_20261012_100000.mp3").write_bytes(b"m")
    assert sessions.audio_for(t).name == "vox_20261012_100000.mp3"
    (rec / "vox_20261012_100000.wav").write_bytes(b"w")
    assert sessions.audio_for(t).name == "vox_20261012_100000.wav"                  # wav pirmenybė
    odd = rec / "pastabos.txt"
    odd.write_text("x")
    os.utime(odd, (1e9, 1e9))
    assert sessions.session_dt(odd) == datetime.fromtimestamp(1e9)                  # nestandartinis — mtime


def test_s4_dedup_rules_locked():
    from diktatura.asr import dialog
    me = [(0, 4, "labas rytas visiems kolegos"),            # kolegos frazės kopija (nutekėjimas) — išmetama
          (10, 11, "aha taip"),                             # trumpa reakcija — lieka visada
          (20, 25, "o aš manau kitaip apie šitą")]          # savas tekstas — lieka
    others = [(0.5, 4.5, "Ona", "labas rytas visiems kolegos"), (19, 26, "Jonas", "gerai")]
    rows, dropped = dialog.dedup(me, others)
    assert dropped == 1
    assert [(r[2], r[3]) for r in rows] == [("Ona", "labas rytas visiems kolegos"), ("Tu", "aha taip"),
                                            ("Jonas", "gerai"), ("Tu", "o aš manau kitaip apie šitą")]
    assert dialog.words("A ir Bė, ČIA!") == ["ir", "bė", "čia"]                       # vienraidžiai praleidžiami
    assert dialog.overlaps(0, 1, 2.9, 4) and not dialog.overlaps(0, 1, 3.1, 4)        # 2 s atsarga


def test_s4_stats_line_time_and_counts():
    from diktatura import stats
    start = datetime(2026, 10, 12, 10, 0)
    assert stats.line_time(start, 90) == datetime(2026, 10, 12, 10, 1, 30) and stats.line_time(start, None) == start
    assert stats.counts(start, 0, None) and stats.counts(start, 60, start + timedelta(seconds=60))
    assert not stats.counts(start, 59, start + timedelta(seconds=60))


def test_s4_mono_srt_timestamps():
    from diktatura.asr.transcribe import fmt_ts
    assert fmt_ts(0) == "00:00:00,000" and fmt_ts(3725.5) == "01:02:05,500" and fmt_ts(59.999) == "00:00:59,999"


# ── S5: kalbėtojų saugyklos pagalbinės funkcijos ──

def test_s5_me_labels_and_text_speakers(env):
    from diktatura.speakers import store
    assert all(store.is_me(x) for x in ("Tu", "tu", "  TU ", "Tu"))
    assert not store.is_me("Tutis") and store.label_for("nez7") == "Kolega?nez7"
    (env.recordings / "vox_20261012_100000.named.txt").write_text(
        "[0:00:01] Tu: labas\n[0:00:02] Ona: sveiki\n[0:00:03] Kolega?nez2: kas čia\n[0:00:04] Kolega?: ?\n"
        "[0:00:05] Jonas: aš\n")
    (env.recordings / "vox_20261012_110000.named.txt").write_text("[0:00:01] Ona: vėl aš\n")
    assert store.text_speakers() == {"Ona", "Jonas"}
    occ = store.occurrences_many(["Ona", "Kolega?nez2", "Rūta"])
    assert [(f.name, t, x) for f, t, x in occ["Ona"]] == [("vox_20261012_100000.named.txt", "0:00:02", "sveiki"),
                                                         ("vox_20261012_110000.named.txt", "0:00:01", "vėl aš")]
    assert len(occ["Kolega?nez2"]) == 1 and occ["Rūta"] == []


def test_s5_pending_count_get_and_assign_to_me(env):
    from diktatura.speakers import store
    assert store.pending_count() == 0 and not store.has_voices()
    store.write_pending_meta("nez1", [1.0, 0.0], "vox_20261012_100000")
    (env.pending / "nez1.wav").write_bytes(b"w")
    assert store.pending_count() == 1 and store.get_pending("nez1").src == "vox_20261012_100000"
    with pytest.raises(KeyError):
        store.get_pending("nez9")
    f = env.recordings / "vox_20261012_100000.named.txt"
    f.write_text("[0:00:01] Kolega?nez1: čia aš telefonu\n")
    assert store.assign("nez1", "tu") == 1                                           # „tu" -> tavo balsas
    assert f.read_text() == "[0:00:01] Tu: čia aš telefonu\n"
    assert store.pending_count() == 0 and store.owner_count() == 1 and store.load_assigned()["nez1"] == "Tu"


def test_s5_relabel_line_refuses_changed_line(env):
    from diktatura.speakers import store
    f = env.recordings / "vox_20261012_100000.named.txt"
    f.write_text("[0:00:01] Ona: a\n[0:00:09] Jonas: b")
    assert not store.relabel_line(f, 1, "Ona", "Rūta")                              # eilutė jau kita
    assert not store.relabel_line(f, 5, "Ona", "Rūta")
    assert store.relabel_line(f, 1, "Jonas", "Rūta") and f.read_text() == "[0:00:01] Ona: a\n[0:00:09] Rūta: b"
    assert store.line_span(f, 0) == (1.0, 9.0) and store.line_span(f, 1) == (9.0, 29.0)


def test_s5_teach_channel_choice(monkeypatch):
    from diktatura.speakers import teach
    speech = {"R": 0.0, "L": 0.0, "mono": 0.0}
    monkeypatch.setattr(teach, "speech_only", lambda x: (x, speech[x.name]))

    class Ch(np.ndarray):
        pass

    def ch(name):
        a = np.zeros(4).view(Ch)
        a.name = name
        return a
    speech.update(R=2.0, L=5.0)
    assert teach.pick([ch("L"), ch("R")])[2] == "R"                                 # R pakanka — jis (vardų kanalas)
    speech.update(R=0.5, L=5.0)
    assert teach.pick([ch("L"), ch("R")])[2] == "L"
    speech.update(R=0.7, L=0.3)
    assert teach.pick([ch("L"), ch("R")])[1:] == (0.7, "R")                          # abiejų mažai — daugiau kalbos
    speech.update(mono=3.0)
    assert teach.pick([ch("mono")])[2] == "mono"


def test_s5_teach_channel_count_real_file(env):
    from diktatura.speakers import teach
    st, mo = env.recordings / "a.wav", env.recordings / "b.wav"
    audio.write_wav(st, audio.speech(0.5), audio.silence(0.5))
    audio.write_wav(mo, audio.speech(0.5))
    assert teach.n_channels(st) == 2 and teach.n_channels(mo) == 1


# ── S6: įrašymas, serveris, grotuvas, servisai ──

def test_s6_vox_capture_command_and_helpers(env, monkeypatch):
    from diktatura.audio import vox
    monkeypatch.setenv("DIKTATURA_MIC", "mic.src")
    monkeypatch.setenv("DIKTATURA_MONITOR", "spk.monitor")
    monkeypatch.delenv("DIKTATURA_CAPTURE_CMD", raising=False)
    cmd, desc = vox.capture_cmd()
    assert desc == "mic=mic.src, sistema=spk.monitor"
    assert cmd[cmd.index("-i") + 1] == "mic.src" and "spk.monitor" in cmd and cmd.count("8192") == 2
    assert cmd[cmd.index("-i") - 1] == vox.APP_MIC and cmd[cmd.index("spk.monitor") - 2] == vox.APP_SYS
    assert vox.capture_cmd(("m2", "s2.monitor"))[1] == "mic=m2, sistema=s2.monitor"
    assert "join=inputs=2:channel_layout=stereo" in cmd[cmd.index("-filter_complex") + 1]
    assert cmd[-5:] == ["-ar", "16000", "-f", "s16le", "pipe:1"]
    monkeypatch.setenv("DIKTATURA_CAPTURE_CMD", "python3 gen.py --x 1")
    assert vox.capture_cmd() == (["python3", "gen.py", "--x", "1"], "DIKTATURA_CAPTURE_CMD")
    monkeypatch.setenv("DIKTATURA_MIN_FREE_MB", "nesąmonė")
    assert vox.min_free_mb() == vox.MIN_FREE_MB
    monkeypatch.setenv("DIKTATURA_MIN_FREE_MB", "50")
    assert vox.min_free_mb() == 50
    assert vox.free_mb("/nonexistent/x") == float("inf")
    cfg = {"VOX_ADAPTIVE": 0, "VOX_OPEN_MARGIN": 15, "VOX_CLOSE_MARGIN": 8, "VOX_GATE_DB": -35,
           "VOX_SILENCE_SEC": 5, "VOX_MIN_SEC": 1.5}
    g = vox.VoxGate(cfg)
    assert g.thresholds() == (-35, -47)
    g.update_config({**cfg, "VOX_ADAPTIVE": 1})
    assert g.thresholds() == (g.nf + 15, g.nf + 8)
    assert vox.rms_db(np.zeros(0, np.int16)) == -120.0


def test_s6_player_command_default_and_template(monkeypatch):
    from diktatura.ui import player
    monkeypatch.delenv("DIKTATURA_SEEK_PLAYER", raising=False)
    c = player.command("/x/a.mp3", 12.345)
    assert c[0] == "ffplay" and c[c.index("-ss") + 1] == "12.35" and c[-1] == "/x/a.mp3" and "-nodisp" in c
    monkeypatch.setenv("DIKTATURA_SEEK_PLAYER", "mpv --start={start} {file}")
    assert player.command("/x/a b.mp3", 3) == ["mpv", "--start=3.00", "/x/a b.mp3"]


def test_s6_units_status_missing_ok_stale(env, tmp_path, monkeypatch):
    from diktatura import services
    monkeypatch.setenv("DIKTATURA_SYSTEMD_DIR", str(tmp_path / "units"))
    assert set(services.units_status().values()) == {"missing"}
    (tmp_path / "units").mkdir()
    u0, u1 = services.UNITS[0], services.UNITS[1]
    (tmp_path / "units" / u0).write_text(services.render_unit(u0))
    (tmp_path / "units" / u1).write_text("[Unit]\nsena versija\n")
    st = services.units_status()
    assert st[u0] == "ok" and st[u1] == "stale"


def test_s6_paths_env_override_and_model_path(tmp_path):
    code = ("from diktatura import paths; print(paths.DATA_DIR, paths.RECORDINGS, paths.RUN_DIR, paths.PROGRESS_DIR, "
            "paths.TIMING, paths.model_path('azuolas-ct2'), paths.model_path('medium'))")
    e = {k: v for k, v in os.environ.items() if not k.startswith("DIKTATURA_")}
    e.update(DIKTATURA_DATA=str(tmp_path / "d"), DIKTATURA_RUN=str(tmp_path / "r"),
             DIKTATURA_STATE=str(tmp_path / "s"), PYTHONPATH=str(REPO))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=e).stdout.split()
    assert out == [str(tmp_path / "d"), str(tmp_path / "d/recordings"), str(tmp_path / "r"), str(tmp_path / "r/progress"),
                   str(tmp_path / "s/timing.json"), str(tmp_path / "d/models/azuolas-ct2"), "medium"]


def test_s6_bash_and_python_paths_agree(env):
    """bin/common.sh ir diktatura/paths.py — tos pačios šaknys (laikyti sinchronizuotus)."""
    from diktatura import paths
    out = subprocess.run(["bash", "-c", f'. {REPO}/bin/common.sh; echo "$RECORDINGS|$PENDING|$LOG_TRANSCRIBE|'
                          '$STATE_RECORDING|$TRANSCRIBE_LOCK|$CONF_FILE"'], capture_output=True, text=True).stdout.strip()
    assert out.split("|") == [str(p) for p in (paths.RECORDINGS, paths.PENDING, paths.LOG_TRANSCRIBE,
                                               paths.STATE_RECORDING, paths.TRANSCRIBE_LOCK, paths.CONF_FILE)]


# ── S7: Python ir bash eilės taisyklės sutampa; garso trynimas — tik garsas ──

def test_s7_pending_selection_same_in_python_and_bash(env, fake_asr):
    """progress.pending_files() (⏳ langelis) == ką transcribe-pending.sh tikrai transkribuoja."""
    from diktatura import progress

    def wav(n):
        f = env.recordings / n
        audio.write_wav(f, audio.speech(0.5), audio.silence(0.5))
        t = time.time() - 3600
        os.utime(f, (t, t))
        return f
    env.write_conf(ARCHIVE_MP3=0)
    for n in ("vox_20261012_100000.wav", "slack_20261012_100100.wav", "rec_20261012_100200.wav",
              "vox_20261012_100300.wav", "vox_20261012_100400.wav", "vox_20261012_100500.wav", "kitas_20261012.wav"):
        wav(n)
    (env.recordings / "vox_20261012_100300.named.txt").write_text("[0:00:01] Tu: yra")
    (env.recordings / "vox_20261012_100400.skip").write_text("")
    (env.run / "recording").write_text(f"vox {env.recordings / 'vox_20261012_100500.wav'}")
    expect = sorted(f.name for f in progress.pending_files())
    assert expect == ["rec_20261012_100200.wav", "slack_20261012_100100.wav", "vox_20261012_100000.wav"]
    assert subprocess.run(["bash", str(REPO / "bin" / "transcribe-pending.sh")], capture_output=True,
                          timeout=60).returncode == 0
    done = sorted(ln.split()[2] for ln in fake_asr.read_text().splitlines() if ln.startswith("start"))
    assert done == expect


def test_s7_cleanup_rule_texts(env):
    from diktatura import cleanup
    assert cleanup.describe_rule({"AUDIO_CLEANUP": "off"}) == "netrinama"
    assert cleanup.describe_rule({"AUDIO_CLEANUP": "age", "AUDIO_KEEP_DAYS": 7}) == "senesnis nei 7 d."
    assert cleanup.describe_rule({"AUDIO_CLEANUP": "size", "AUDIO_MAX_GB": 5.0}) == "įrašai > 5 GB"
    assert not cleanup.has_text(env.recordings, "vox_x")
    (env.recordings / "vox_x.skip").write_text("")
    assert cleanup.has_text(env.recordings, "vox_x")


def test_s7_reset_busy_includes_active_recording(env, monkeypatch):
    from diktatura import reset
    monkeypatch.setattr(reset, "running_transcriptions", lambda: [Path("/x/slack_20261012_090000.wav")])
    (env.run / "recording").write_text(f"vox {env.recordings / 'vox_20261012_100000.wav'}")
    assert reset.busy_bases() == {"vox_20261012_100000", "slack_20261012_090000"}


# ── S8: aido šalinimas — poslinkis ir nuotėkio lygis ──

def test_s8_echo_lag_and_leak_level():
    from diktatura.audio import echo
    rng = np.random.default_rng(5)
    r = (rng.normal(0, 0.1, 16000 * 20) * np.repeat(rng.random(201) > 0.4, 1600)[:16000 * 20]).astype(np.float32)
    lag = 12345
    left = (echo.shifted(r * 0.1, lag) + rng.normal(0, 0.001, r.size)).astype(np.float32)
    got, strength = echo.estimate_lag(left, r)
    assert abs(got - lag) <= 2 and strength > 0.5
    db, coh = echo.leak_db(left, echo.shifted(r, lag))
    assert -25 < db < -15 and coh > 0.9                                              # -20 dB nuotėkis, koherentiškas
