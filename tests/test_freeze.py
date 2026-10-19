"""FZ1–FZ9: aplinkos ir sąsajų UŽŠALDYMAS — kad atnaujinus paketus, systemd šablonus ar CLI kas nors nepasikeistų
nepastebėtai. Lūžo = pasikeitė kažkas, nuo ko priklauso veikiantis diegimas; sąmoningai keičiant — atnaujinti testą."""
import json
import re
import subprocess
import sys

import pytest

from testenv import REPO

PY3 = "/usr/bin/python3"


# ── FZ1: .venv paketų versijos = requirements.txt (atnaujinus paketą testas primins patikrinti viską) ──

def test_fz1_venv_versions_match_requirements():
    req = {}
    for ln in (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([a-zA-Z0-9_-]+)==([\w.]+)", ln.strip())
        if m:
            req[m.group(1).lower().replace("-", "_")] = m.group(2)
    assert set(req) == {"faster_whisper", "ctranslate2", "sherpa_onnx", "numpy", "scikit_learn"}
    code = ("import faster_whisper, ctranslate2, sherpa_onnx, numpy, sklearn, json; print(json.dumps({"
            "'faster_whisper': faster_whisper.__version__, 'ctranslate2': ctranslate2.__version__, "
            "'sherpa_onnx': sherpa_onnx.__version__, 'numpy': numpy.__version__, 'scikit_learn': sklearn.__version__}))")
    got = json.loads(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120).stdout)
    assert got == req, f"įdiegtos versijos skiriasi nuo requirements.txt: {got} != {req} (make setup)"
    assert sys.version_info[:2] == (3, 10)                                       # .venv — Python 3.10


# ── FZ2: systemd šablonai — esminės eilutės ──

UNIT_KEYS = {
    "diktatura-vox.service": ["ExecStart=@REPO@/.venv/bin/python -m diktatura.audio.vox",
                              "Conflicts=diktatura-autorecord.service", "Restart=on-failure", "WantedBy=default.target"],
    "diktatura-autorecord.service": ["bin/autorecord.sh", "Conflicts=diktatura-vox.service"],
    "diktatura-tray.service": ["python3 -m diktatura.ui.tray", "Restart="],
    "diktatura-nightly.service": ["bin/transcribe-pending.sh", "Type=oneshot", "Nice=10"],
    "diktatura-nightly.timer": ["OnCalendar=*-*-* 01:30:00", "Persistent=true"],
    "diktatura-asr.service": ["diktatura.asr.server"],
    "diktatura-sources.service": ["transcribe-pending.sh --sources --if-immediate", "Type=oneshot"],
    "diktatura-sources.timer": ["OnUnitActiveSec=2min", "OnBootSec=3min"],
}


def test_fz2_systemd_templates_locked():
    from diktatura import services
    assert sorted(services.UNITS) == sorted(UNIT_KEYS)
    for unit, keys in UNIT_KEYS.items():
        text = (REPO / "systemd" / f"{unit}.in").read_text(encoding="utf-8")
        for k in keys:
            assert k in text, f"{unit}: trūksta „{k}“"
        assert "@REPO@" in text or unit.endswith(".timer")
    desk = (REPO / "desktop" / "diktatura.desktop.in").read_text(encoding="utf-8")
    for k in ("Exec=@REPO@/bin/diktatura-open.sh", "StartupWMClass=diktatura", "Name=Diktatūra"):
        assert k in desk


def test_fz2_icons_present():
    for state in ("idle", "rec", "proc"):
        for suffix in ("", "-dim"):
            assert (REPO / "icons" / f"diktatura-{state}{suffix}.png").stat().st_size > 100


# ── FZ3: bin/common.sh keliai = diktatura/paths.py (laikyti sinchronizuotus) ──

def test_fz3_bash_paths_equal_python_paths(env):
    from diktatura import paths
    sh = subprocess.run(["bash", "-c", f". '{REPO}/bin/common.sh'; echo \"$RECORDINGS|$SPEAKERS|$PENDING|$MODELS|"
                         f"$CONF_FILE|$LOG_TRANSCRIBE|$STATE_RECORDING|$TRANSCRIBE_LOCK|$PY\""],
                        capture_output=True, text=True, timeout=10).stdout.strip().split("|")
    assert sh == [str(p) for p in (paths.RECORDINGS, paths.SPEAKERS, paths.PENDING, paths.MODELS, paths.CONF_FILE,
                                   paths.LOG_TRANSCRIBE, paths.STATE_RECORDING, paths.TRANSCRIBE_LOCK, paths.VENV_PY)]


# ── FZ4: stdlib moduliai veikia su SISTEMOS python3 (ikona, langas, make komandos) ──

@pytest.mark.parametrize("argv, expect", [
    (["-m", "diktatura.config", "path"], "diktatura.conf"),
    (["-m", "diktatura.config", "get", "VOX_SILENCE_SEC"], "5"),
    (["-m", "diktatura.sources", "list"], "Sekamų aplankų nėra"),
    (["-m", "diktatura.backup", "list"], "Kopijų nėra"),
    (["-m", "diktatura.progress"], "niekas netranskribuojama"),
    (["-m", "diktatura.cleanup", "--dry-run"], ""),
    (["-c", "import diktatura.doctor, diktatura.reset, diktatura.waveform, diktatura.fillers, diktatura.transcripts, "
            "diktatura.mcp_server, diktatura.services, diktatura.sessions, diktatura.annotations, diktatura.stats, "
            "diktatura.pause, diktatura.debug; print('ok')"], "ok"),
])
def test_fz4_system_python_cli(env, argv, expect):
    r = subprocess.run([PY3, *argv], capture_output=True, text=True, timeout=60, cwd=str(REPO))
    assert r.returncode == 0, r.stderr
    assert expect in r.stdout


def test_fz4_ui_modules_import_with_system_python(env):
    code = ("import os; os.environ['GDK_BACKEND']='broadway'; import diktatura.ui.gtk, diktatura.ui.themes, "
            "diktatura.ui.waveform_view, diktatura.ui.pill, diktatura.ui.progress_dialog; print('ok')")
    r = subprocess.run([PY3, "-c", code], capture_output=True, text=True, timeout=60, cwd=str(REPO))
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr


# ── FZ5: MCP įrankių sąsaja (AI klientai nuo jos priklauso) ──

def test_fz5_mcp_tool_schemas_locked():
    from diktatura import mcp_server as M
    tools = {t["name"]: sorted(t["inputSchema"].get("properties", {})) for t in M.TOOLS}
    assert tools == {
        "list_sessions": ["limit", "since", "source", "until"],
        "search": ["clean", "limit", "query", "regex", "since", "source", "speaker", "until"],
        "get_transcript": ["clean", "end", "session", "start"],
        "speaker_stats": ["since", "source", "until"],
        "list_sources": [],
    }
    assert {t["name"]: t["inputSchema"].get("required", []) for t in M.TOOLS}["search"] == ["query"]
    assert M.PROTOCOLS[0] == "2025-06-18" and set(M.HANDLERS) == set(tools)


# ── FZ6: nustatymų failo ir SCHEMA tvarka, komentarai, grupės ──

def test_fz6_default_conf_keys_order_equals_schema():
    from diktatura import config
    keys = [m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", (REPO / "config" / "diktatura.conf.default")
                                            .read_text(encoding="utf-8"), re.M)]
    assert keys == [s.key for s in config.SCHEMA]
    groups = []
    for s in config.SCHEMA:
        if s.group not in groups:
            groups.append(s.group)
    assert groups == ["Išvaizda", "Tekstas", "Įrašymas", "Transkripcija", "VAD (kalbos filtras)", "Kalbėtojai",
                      "Archyvas", "Debug"]


# ── FZ7: žurnalų eilutės, kurias skaito kiti įrankiai (progress, pill, doctor) ──

def test_fz7_log_markers_used_across_modules():
    tf = (REPO / "bin" / "transcribe-file.sh").read_text(encoding="utf-8")
    for marker in ("EILĖJE", "ANALIZĖ pradėta", "ANALIZĖ baigta", "garsas paliktas", "∅ tuščias tekstas",
                   "💾 wav→mp3", "PRALEISTA", "transkribuota iš naujo", "DIKTATURA_PEAKS", "DIKTATURA_RETRANSCRIBE"):
        assert marker in tf, marker
    vox = (REPO / "diktatura" / "audio" / "vox.py").read_text(encoding="utf-8")
    for marker in ("🔴 garsas aptiktas", "🛑", "per trumpas", "↕ fonas garsesnis", "🔀", "diske liko tik"):
        assert marker in vox, marker


# ── FZ8: CSS klasės, kuriomis remiasi skiltys ──

def test_fz8_css_classes_locked():
    from diktatura.ui import gtk
    for cls in ("dk-help", "dk-error", "dk-ok", "dk-intro", "dk-title", "dk-mono", "dk-pill", "dk-bar", "dk-pillwin"):
        assert f".{cls}" in gtk.CSS.decode(), cls


# ── FZ9: Makefile kintamieji ir failų struktūra ──

def test_fz9_repo_layout():
    for p in ("bin/transcribe-file.sh", "bin/transcribe-pending.sh", "bin/autorecord.sh", "bin/common.sh",
              "bin/mcp-server.sh", "bin/diktatura-open.sh", "bin/rec-toggle.sh", "tools/screenshots.sh",
              "tools/gallery.py", "tools/demo_data.py", "tools/fetch_models.sh", "tools/convert_azuolas.sh",
              ".githooks/pre-commit", ".githooks/pre-push", ".githooks/privacy-scan.sh", ".github/workflows/test.yml",
              "docs/ARCHITECTURE.md", "docs/PLAN.md", "docs/GALLERY.md", "CONTRIBUTING.md", "README.md"):
        assert (REPO / p).exists(), p
    for sh in REPO.glob("bin/*.sh"):
        assert sh.stat().st_mode & 0o111, f"{sh.name} nevykdomas"
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8")
    for p in ("STATUS.md", "CLAUDE.md", ".private-terms", ".venv"):
        assert p in ignored, p
