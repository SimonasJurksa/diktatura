"""Diktatūra — sistemos savitikra:  make doctor   (python3 -m diktatura.doctor)

Kiekvienai patikrai: ✓ gerai · ⚠ įspėjimas (veikia, bet verta sutvarkyti) · ✗ klaida (kažkas neveiks) +
patarimas, ką daryti. Išėjimo kodas 1, jei yra bent viena ✗. Nieko nekeičia (tik skaito).
Tik stdlib; venv ir GTK tikrinami atskirais procesais (veikia su bet kuriuo python3).
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from diktatura import config, paths, services

OK, WARN, FAIL = "ok", "warn", "fail"
ICON = {OK: "✓", WARN: "⚠", FAIL: "✗"}
AZUOLAS_RAM_GB = 3.5


@dataclass
class R:
    status: str
    title: str
    fix: str = ""


def _run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


# ── Patikros (kiekviena grąžina R sąrašą) ──

def check_tools(which=shutil.which) -> list:
    need = [("ffmpeg", "įrašymas, mp3", "make deps"), ("ffprobe", "kanalų nustatymas", "make deps"),
            ("pactl", "garso įrenginiai, Slack aptikimas", "make deps"), ("flock", "transkripcijų eilė", "apt install util-linux"),
            ("systemctl", "servisai", "systemd")]
    nice = [("notify-send", "pranešimai", "make deps"), ("paplay", "balsų perklausa Apmokymuose", "make deps"),
            ("ffplay", "grojimas nuo eilutės teksto lange", "make deps"),
            ("ionice", "žemas transkripcijos prioritetas", "apt install util-linux"),
            ("uv", "tik make setup — .venv kūrimui", "https://docs.astral.sh/uv/"), ("curl", "modelių atsisiuntimas", "make deps")]
    out = [R(OK, f"{t} ({why})") if which(t) else R(FAIL, f"nėra {t} ({why})", fix) for t, why, fix in need]
    out += [R(OK, f"{t} ({why})") if which(t) else R(WARN, f"nėra {t} ({why})", fix) for t, why, fix in nice]
    return out


def check_audio(run=_run) -> list:
    if run(["pactl", "info"]).returncode != 0:
        return [R(FAIL, "PulseAudio/PipeWire nepasiekiamas (pactl info)", "ar prisijungęs grafinėje sesijoje? systemctl --user status pulseaudio")]
    src = run(["pactl", "get-default-source"]).stdout.strip()
    sink = run(["pactl", "get-default-sink"]).stdout.strip()
    sources = run(["pactl", "list", "sources", "short"]).stdout
    out = [R(OK, f"mikrofonas: {src}") if src else R(FAIL, "nėra numatytojo mikrofono", "Garso nustatymuose pasirink įvestį")]
    if sink and f"{sink}.monitor" in sources:
        out.append(R(OK, f"sistemos garsas: {sink}.monitor"))
    else:
        out.append(R(FAIL, f"nėra sistemos garso monitoriaus ({sink or '?'}.monitor)", "Garso nustatymuose pasirink išvestį"))
    return out


def check_python(run=_run) -> list:
    out = []
    if not paths.VENV_PY.exists():
        return [R(FAIL, f"nėra .venv ({paths.VENV_PY})", "make setup")]
    r = run([str(paths.VENV_PY), "-c", "import faster_whisper, sherpa_onnx, numpy, sklearn"], timeout=60)
    out.append(R(OK, ".venv: faster-whisper, sherpa-onnx, numpy, sklearn") if r.returncode == 0 else
               R(FAIL, ".venv paketai neįdiegti: " + (r.stderr.strip().splitlines() or ["?"])[-1], "make setup"))
    gi = ("import gi; gi.require_version('Gtk','3.0'); gi.require_version('AyatanaAppIndicator3','0.1');"
          "from gi.repository import Gtk, AyatanaAppIndicator3")
    r = run(["/usr/bin/python3", "-c", gi])
    out.append(R(OK, "sistemos python3: GTK 3 + AyatanaAppIndicator3 (ikona, langai)") if r.returncode == 0 else
               R(FAIL, "sistemos python3 neturi GTK/AppIndicator", "make deps"))
    return out


def check_desktop(run=_run, which=shutil.which) -> list:
    """GNOME rodo AppIndicator ikonas tik su plėtiniu (Ubuntu: ubuntu-appindicators)."""
    if not which("gnome-extensions"):
        return []
    enabled = run(["gnome-extensions", "list", "--enabled"]).stdout.lower()
    return [R(OK, "GNOME AppIndicator plėtinys įjungtas (ikona matoma)") if "appindicator" in enabled else
            R(WARN, "GNOME AppIndicator plėtinys neįjungtas — status bar ikona nebus matoma",
              "gnome-extensions enable ubuntu-appindicators@ubuntu.com (arba Extensions programoje)")]


def _expected_shas() -> dict:
    text = (paths.REPO / "tools" / "fetch_models.sh").read_text(encoding="utf-8")
    return {k: v for k, v in re.findall(r"^(EMB|SEG)_SHA=([0-9a-f]{64})", text, re.M)}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def check_models(cfg: dict) -> list:
    out = []
    az = paths.MODELS / "azuolas-ct2" / "model.bin"
    if az.exists():
        out.append(R(OK, f"Ąžuolas (CT2 int8): {az.parent}"))
    elif cfg["MODEL"] == "azuolas-ct2":
        out.append(R(FAIL, "nėra Ąžuolo modelio, o MODEL=azuolas-ct2", "make model-convert  (arba make model-medium)"))
    else:
        out.append(R(WARN, f"nėra Ąžuolo modelio (naudojamas {cfg['MODEL']})", "geriausiai LT kokybei: make model-convert"))
    shas = _expected_shas()
    for key, rel, what in (("EMB", "embedding_campplus_en.onnx", "balso embedding (vardai)"),
                           ("SEG", "sherpa-onnx-pyannote-segmentation-3-0/model.onnx", "segmentacija")):
        f = paths.DIARIZATION_MODELS / rel
        if not f.exists():
            out.append(R(FAIL, f"nėra kalbėtojų modelio: {what}", "make models"))
        elif shas.get(key) and _sha256(f) != shas[key]:
            out.append(R(FAIL, f"kalbėtojų modelio SHA-256 nesutampa: {f.name}", f"rm {f} && make models"))
        else:
            out.append(R(OK, f"kalbėtojų modelis: {what}"))
    return out


def check_config() -> list:
    if not paths.CONF_FILE.exists():
        return [R(WARN, f"nėra nustatymų failo — naudojami numatytieji ({paths.CONF_FILE})", "make config-reset")]
    user = config.parse(paths.CONF_FILE)
    out = []
    for k, v in user.items():
        if k not in config.BY_KEY:
            out.append(R(WARN, f"nežinomas nustatymas {k}={v} (ignoruojamas)", "make config-edit"))
            continue
        try:
            config.coerce(k, v)
        except ValueError as e:
            out.append(R(WARN, f"{e} — naudojama numatytoji", "make config-edit arba Nustatymai lange"))
    return out or [R(OK, f"nustatymai teisingi ({paths.CONF_FILE})")]


def check_services(cfg: dict) -> list:
    out = []
    st = services.units_status()
    missing = [u for u, s in st.items() if s == "missing"]
    stale = [u for u, s in st.items() if s == "stale"]
    if missing:
        out.append(R(FAIL, f"neįdiegti servisai: {', '.join(missing)}", "make install-units"))
    if stale:
        out.append(R(WARN, f"servisų failai pasenę (skiriasi nuo systemd/*.in): {', '.join(stale)}",
                     "make install-units && make restart"))
    if not missing and not stale:
        out.append(R(OK, "servisų failai įdiegti ir atnaujinti"))
    mode = services.recorder_mode()
    out.append(R(OK, f"įrašymo režimas: {services.MODE_LABELS[mode].split(' — ')[0]}") if mode != "off" else
               R(WARN, "įrašymas išjungtas (nė vienas režimas neveikia)", "make mode-vox  arba  make mode-slack"))
    out.append(R(OK, "status bar ikona veikia") if services.is_active(services.TRAY) else
               R(WARN, "status bar ikona neveikia", "make tray-on"))
    if cfg["ASR_SERVER"]:
        out.append(R(OK, "ASR serveris veikia (modelis laikomas atmintyje)") if services.is_active(services.ASR) else
                   R(WARN, "ASR_SERVER=1, bet ASR serveris neveikia — transkribuojama atskirais procesais",
                     "make asr-server-on  (arba Nustatymuose išjunk „Nuolat įkrautas modelis“)"))
    timer = services.is_enabled(services.TIMER)
    if timer:
        out.append(R(OK, "naktinė transkripcija 01:30 įjungta"))
    elif cfg["MODE"] == "deferred":
        out.append(R(FAIL, "MODE=deferred, bet naktinis timer išjungtas — įrašai liks be teksto", "make nightly-on"))
    else:
        out.append(R(WARN, "naktinis timer išjungtas (likučių nesutranskribuos)", "make nightly-on"))
    return out


def check_git(run=_run) -> list:
    if not (paths.REPO / ".git").exists():
        return []
    hp = run(["git", "-C", str(paths.REPO), "config", "core.hooksPath"]).stdout.strip()
    out = [R(OK, "privatumo sargas (git hooks) įjungtas") if hp == ".githooks" else
           R(WARN, "privatumo sargas (git hooks) neįjungtas — svarbu, jei commit'ini", "make hooks")]
    out.append(R(OK, ".private-terms yra (asmeniniai terminai sargui)") if (paths.REPO / ".private-terms").exists() else
               R(WARN, "nėra .private-terms — sargas netikrins kolegų vardų/darbovietės", "sukurk .private-terms (žr. ARCHITECTURE §6)"))
    return out


def check_resources(mem_avail_gb: float, disk_free_gb: float, model: str) -> list:
    need = AZUOLAS_RAM_GB if model == "azuolas-ct2" else 1.5
    out = []
    if mem_avail_gb >= need:
        out.append(R(OK, f"RAM laisva {mem_avail_gb:.1f} GB (transkripcijai reikia ~{need:g} GB)"))
    else:
        out.append(R(WARN, f"RAM laisva tik {mem_avail_gb:.1f} GB (transkripcijai reikia ~{need:g} GB) — gali swap'inti",
                     "uždaryk naršyklės tabus arba MODE=deferred (naktį) / make model-medium"))
    if disk_free_gb < 2:
        out.append(R(FAIL, f"diske liko tik {disk_free_gb:.1f} GB — įrašai gali nebeišsisaugoti", "atlaisvink vietos"))
    elif disk_free_gb < 8:
        out.append(R(WARN, f"diske liko {disk_free_gb:.1f} GB (modelių konversijai reikia ~8–10 GB)", "atlaisvink vietos"))
    else:
        out.append(R(OK, f"diske laisva {disk_free_gb:.0f} GB"))
    return out


def check_runtime(run=_run) -> list:
    out = []
    if paths.STATE_RECORDING.exists():
        alive = run(["pgrep", "-f", r"diktatura[.]audio[.]vox|bin/autorecord[.]sh|ffmpeg.*-f pulse"]).returncode == 0
        out.append(R(OK, "šiuo metu įrašoma") if alive else
                   R(WARN, "pakibęs būsenos failas (ikona rodo 🔴, bet niekas nerašo)", f"rm {paths.STATE_RECORDING}"))
    if config.load()["DEBUG"] or os.environ.get("DIKTATURA_DEBUG") == "1":
        size = paths.LOG_DEBUG.stat().st_size / 1e6 if paths.LOG_DEBUG.exists() else 0
        out.append(R(WARN, f"debug režimas ĮJUNGTAS ({paths.LOG_DEBUG}, {size:.1f} MB)", "išjungti: make set S=\"DEBUG=0\""))
    return out


def mem_available_gb() -> float:
    try:
        for ln in open("/proc/meminfo"):
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return 0.0


def disk_free_gb(path: Path) -> float:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free / 1e9


def run_all() -> list:
    cfg = config.load()
    return [
        ("Sistemos įrankiai", check_tools()),
        ("Garsas", check_audio()),
        ("Python aplinkos", check_python()),
        ("Darbalaukis", check_desktop()),
        ("Modeliai", check_models(cfg)),
        ("Nustatymai", check_config()),
        ("Servisai", check_services(cfg)),
        ("Privatumas (git)", check_git()),
        ("Resursai", check_resources(mem_available_gb(), disk_free_gb(paths.DATA_DIR), cfg["MODEL"])),
        ("Vyksta dabar", check_runtime()),
    ]


def main() -> int:
    groups = run_all()
    counts = {OK: 0, WARN: 0, FAIL: 0}
    print("═══ DIKTATŪRA — SAVITIKRA ═══")
    for title, results in groups:
        if not results:
            continue
        print(f"─ {title} ─")
        for r in results:
            counts[r.status] += 1
            print(f"  {ICON[r.status]} {r.title}" + (f"\n      → {r.fix}" if r.fix and r.status != OK else ""))
    print(f"\nRezultatas: {counts[OK]} ✓ · {counts[WARN]} ⚠ · {counts[FAIL]} ✗")
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
