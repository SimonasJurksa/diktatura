"""Diktatūra — visi keliai vienoje vietoje.

Kodas gyvena repo; DUOMENYS — už repo ribų (Linux XDG), kad privatūs įrašai fiziškai negalėtų
patekti į git:
  nustatymai   ~/.config/diktatura/diktatura.conf
  duomenys     ~/.local/share/diktatura/{recordings,speakers,models}
  logai        ~/.local/state/diktatura/*.log
  runtime      $XDG_RUNTIME_DIR/diktatura/{recording,transcribe.lock}   (tmpfs, išvaloma perkrovus)

Kiekvieną šaknį galima perrašyti env: DIKTATURA_CONFIG_DIR, DIKTATURA_DATA, DIKTATURA_STATE,
DIKTATURA_RUN (testai rašo į laikinus katalogus). Tik stdlib — importuoja ir sistemos python3 (tray/UI).
Bash atitikmuo: bin/common.sh (laikyti sinchronizuotą).
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _root(env_override: str, xdg_env: str, xdg_default: str) -> Path:
    if os.environ.get(env_override):
        return Path(os.environ[env_override]).expanduser()
    return Path(os.environ.get(xdg_env) or xdg_default).expanduser() / "diktatura"


CONFIG_DIR = _root("DIKTATURA_CONFIG_DIR", "XDG_CONFIG_HOME", "~/.config")
DATA_DIR = _root("DIKTATURA_DATA", "XDG_DATA_HOME", "~/.local/share")
STATE_DIR = _root("DIKTATURA_STATE", "XDG_STATE_HOME", "~/.local/state")
if os.environ.get("DIKTATURA_RUN"):
    RUN_DIR = Path(os.environ["DIKTATURA_RUN"]).expanduser()
elif os.environ.get("XDG_RUNTIME_DIR"):
    RUN_DIR = Path(os.environ["XDG_RUNTIME_DIR"]) / "diktatura"
else:
    RUN_DIR = Path(f"/tmp/diktatura-{os.getuid()}")

# Duomenys
RECORDINGS = DATA_DIR / "recordings"
SPEAKERS = DATA_DIR / "speakers"
ENROLL = SPEAKERS / "enroll.json"
PENDING = SPEAKERS / "pending"
SPEAKER_SAMPLES = DATA_DIR / "speakers_samples"
MODELS = DATA_DIR / "models"
DIARIZATION_MODELS = MODELS / "diarization"
EMB_MODEL_FILE = DIARIZATION_MODELS / "embedding_campplus_zh_en.onnx"   # balso embedding (vardai), žr. store.EMB_MODEL
HF_HOME = MODELS / "hf"

# Nustatymai
CONF_FILE = CONFIG_DIR / "diktatura.conf"
DEFAULT_CONF = REPO / "config" / "diktatura.conf.default"

# Logai / runtime
LOG_AUTOREC = STATE_DIR / "autorecord.log"
LOG_TRANSCRIBE = STATE_DIR / "transcribe.log"
LOG_DEBUG = STATE_DIR / "debug.log"
STATE_RECORDING = RUN_DIR / "recording"        # yra = šiuo metu rašoma (ikonai)
TRANSCRIBE_LOCK = RUN_DIR / "transcribe.lock"

# Kodas
ICONS = REPO / "icons"
BIN = REPO / "bin"
VENV_PY = REPO / ".venv" / "bin" / "python"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, RECORDINGS, SPEAKERS, PENDING, MODELS, STATE_DIR, RUN_DIR):
        d.mkdir(parents=True, exist_ok=True)


def model_path(name: str) -> str:
    """Config MODEL reikšmė -> faster-whisper argumentas.
    'azuolas'/'azuolas-ct2' -> lokalus CT2 katalogas; absoliutus kelias -> kaip yra; kita (medium...) -> vardas."""
    if name in ("azuolas", "azuolas-ct2"):
        return str(MODELS / "azuolas-ct2")
    p = Path(name).expanduser()
    return str(p) if p.is_absolute() else name
