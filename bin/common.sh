# Diktatūra — bendri keliai ir nustatymai bash skriptams.
# Įsikelti:  . "$(dirname "$0")/common.sh"
# LAIKYTI SINCHRONIZUOTA su diktatura/paths.py (tos pačios šaknys ir env perrašymai).

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${DIKTATURA_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/diktatura}"
DATA_DIR="${DIKTATURA_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/diktatura}"
STATE_DIR="${DIKTATURA_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/diktatura}"
if [ -n "${DIKTATURA_RUN:-}" ]; then RUN_DIR="$DIKTATURA_RUN"
elif [ -n "${XDG_RUNTIME_DIR:-}" ]; then RUN_DIR="$XDG_RUNTIME_DIR/diktatura"
else RUN_DIR="/tmp/diktatura-$(id -u)"; fi

RECORDINGS="$DATA_DIR/recordings"
SPEAKERS="$DATA_DIR/speakers"
PENDING="$SPEAKERS/pending"
MODELS="$DATA_DIR/models"
CONF_FILE="$CONFIG_DIR/diktatura.conf"
DEFAULT_CONF="$REPO/config/diktatura.conf.default"
LOG_AUTOREC="$STATE_DIR/autorecord.log"
LOG_TRANSCRIBE="$STATE_DIR/transcribe.log"
LOG_DEBUG="$STATE_DIR/debug.log"
STATE_RECORDING="$RUN_DIR/recording"
TRANSCRIBE_LOCK="$RUN_DIR/transcribe.lock"
QUIT_FILE="$STATE_DIR/quit.json"
WINDOW_LOCK="$RUN_DIR/window.lock"
PY="$REPO/.venv/bin/python"

export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"
export HF_HOME="$MODELS/hf"
mkdir -p "$CONFIG_DIR" "$RECORDINGS" "$STATE_DIR" "$RUN_DIR"

# Diktatūra išjungta ikonos „Išeiti" (yra $QUIT_FILE) ir langas neatidarytas -> transkripcija būtų nematoma, todėl
# neprasideda (diktatura.services.transcription_blocked — tas pats Python'e). Žymę nuima ikonos paleidimas.
# Kol atidarytas langas (laiko $WINDOW_LOCK) — galima. DIKTATURA_IGNORE_QUIT=1 — make transcribe-pending (terminale matosi).
app_quit() {
  [ -f "$QUIT_FILE" ] || return 1
  [ "${DIKTATURA_IGNORE_QUIT:-0}" = 1 ] && return 1
  if [ -e "$WINDOW_LOCK" ] && ! flock -n "$WINDOW_LOCK" true 2>/dev/null; then return 1; fi
  return 0
}

# Nustatymai: pirma numatytieji, tada vartotojo (perrašo). Kviesti kiekvieną kartą prieš sprendimą — gyvai.
load_config() {
  [ -f "$CONF_FILE" ] || cp "$DEFAULT_CONF" "$CONF_FILE"
  # shellcheck disable=SC1090
  . "$DEFAULT_CONF"; . "$CONF_FILE"
}

# MODEL reikšmė -> faster-whisper argumentas (sinchronizuota su paths.model_path)
model_path() {
  case "$1" in
    azuolas|azuolas-ct2) echo "$MODELS/azuolas-ct2" ;;
    *) echo "$1" ;;
  esac
}

# Debug žurnalas (sinchronizuota su diktatura/debug.py): DIKTATURA_DEBUG=1|0 arba nustatymas DEBUG=1 (po load_config).
# Žymė — DBG_TAG (pvz. "slack", "transcribe"). > 5 MB -> debug.log.1.
dbg() {
  [ "${DIKTATURA_DEBUG:-${DEBUG:-0}}" = 1 ] || return 0
  if [ -f "$LOG_DEBUG" ] && [ "$(stat -c %s "$LOG_DEBUG")" -gt 5242880 ]; then mv -f "$LOG_DEBUG" "$LOG_DEBUG.1"; fi
  echo "$(date '+%F %T.%3N') [${DBG_TAG:-sh}] $*" >> "$LOG_DEBUG"
}
