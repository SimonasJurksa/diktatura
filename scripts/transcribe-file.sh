#!/usr/bin/env bash
# Universalus "analizatorius": paima WAV ir transkribuoja tinkamu būdu.
#   - stereo (L=mic,R=monitor) -> transcribe_stereo.py (dialogas: Tu/Kolegos)
#   - mono                      -> transcribe.py
# Modelis: $WISPR_MODEL (def: Ąžuolas CT2). Gijos: $WISPR_THREADS (def: 6).
#   bash ~/wispr/scripts/transcribe-file.sh <failas.wav>
set -uo pipefail

WAV="${1:?reikia WAV kelio}"
[ -f "$WAV" ] || { echo "Nėra failo: $WAV" >&2; exit 1; }

PY="$HOME/wispr/plans/A/.venv/bin/python"
# Modelis/gijos: env viršesnis, kitaip iš config, kitaip numatyta.
CFG_MODEL="azuolas-ct2"; THREADS_CFG=6
[ -f "$HOME/wispr/wispr.conf" ] && { MODEL=; THREADS=; . "$HOME/wispr/wispr.conf"; CFG_MODEL="${MODEL:-azuolas-ct2}"; THREADS_CFG="${THREADS:-6}"; }
# config MODEL gali būti vardas (azuolas-ct2) arba „medium" — azuolas-ct2 verčiam į pilną kelią
case "${WISPR_MODEL:-$CFG_MODEL}" in
  azuolas-ct2|azuolas) MODEL="$HOME/wispr/models/azuolas-ct2" ;;
  *) MODEL="${WISPR_MODEL:-$CFG_MODEL}" ;;
esac
THREADS="${WISPR_THREADS:-$THREADS_CFG}"
LOG="$HOME/wispr/recordings/transcribe.log"

# EILĖ: tik VIENA transkripcija vienu metu (Ąžuolas ~3.3 GB — dvi lygiagrečiai = OOM).
# flock laukia, kol atsilaisvins, tad skambučiai po kelis queue'inasi, o ne krauna RAM.
exec 9>"$HOME/wispr/recordings/.transcribe.lock"
if ! flock -n 9; then
  echo "$(date '+%F %T') EILĖJE (laukia ankstesnės transkripcijos): $(basename "$WAV")" >>"$LOG"
  flock 9
fi

chans="$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of csv=p=0 "$WAV" 2>/dev/null)"
echo "$(date '+%F %T') ANALIZĖ pradėta: $(basename "$WAV") (${chans}ch, modelis=$(basename "$MODEL"))" | tee -a "$LOG"

# Transkripcija MAKSIMALIAI nusileidžia (nice 19 + ionice idle), kad garso capture
# (įrašymas) visada turėtų CPU/IO pirmenybę ir nenumestų buferių.
LOWPRIO="nice -n 19"
command -v ionice >/dev/null 2>&1 && LOWPRIO="ionice -c 3 nice -n 19"
if [ "$chans" = "2" ]; then
  # Stereo -> vardų pipeline (Tu + kolegos vardais per balso atpažinimą, de-dup).
  OMP_NUM_THREADS="$THREADS" $LOWPRIO "$PY" "$HOME/wispr/plans/A/transcribe_named.py" \
    "$WAV" --model "$MODEL" --threads "$THREADS" >>"$LOG" 2>&1
  OUT="${WAV%.wav}.named.txt"
else
  OMP_NUM_THREADS="$THREADS" $LOWPRIO "$PY" "$HOME/wispr/plans/A/transcribe.py" \
    "$WAV" --model "$MODEL" --threads "$THREADS" >>"$LOG" 2>&1
  OUT="${WAV%.wav}.txt"
fi

# Nustatymai valymui/archyvavimui (iš config)
DELETE_EMPTY=1; ARCHIVE_MP3=1; ARCHIVE_KBPS=64
[ -f "$HOME/wispr/wispr.conf" ] && . "$HOME/wispr/wispr.conf"

if [ ! -f "$OUT" ]; then
  # transkripcija žlugo (pvz. OOM) — teksto nėra. Paliekam wav (bus bandoma vėl).
  echo "$(date '+%F %T') ⚠ transkripcija nedavė failo (žlugo?) — wav paliktas: $(basename "$WAV")" | tee -a "$LOG"
  exit 1
fi

CONTENT="$(tr -d '[:space:]' < "$OUT" 2>/dev/null)"
if [ -z "$CONTENT" ]; then
  # Tuščias tekstas (ne kalba — triukšmas/kvėpavimas). Trinam tekstą ir wav.
  echo "$(date '+%F %T') ∅ tuščias tekstas — ištrinta $(basename "$WAV") + $(basename "$OUT")" | tee -a "$LOG"
  [ "$DELETE_EMPTY" = "1" ] && rm -f "$OUT" "$WAV"
  exit 0
fi

echo "$(date '+%F %T') ANALIZĖ baigta: $OUT" | tee -a "$LOG"
# Parodom tekstą iškart (notify-send su turiniu — kad „matytum" padiktuotą tekstą)
TXT="$(head -c 800 "$OUT" 2>/dev/null)"
notify-send -t 20000 "✅ Tekstas: $(basename "$OUT")" "$TXT" 2>/dev/null || true

# Archyvas: wav -> mažas mp3 (taupo vietą), wav trinam
if [ "$ARCHIVE_MP3" = "1" ] && [ -f "$WAV" ]; then
  MP3="${WAV%.wav}.mp3"
  if ffmpeg -hide_banner -loglevel error -y -i "$WAV" -c:a libmp3lame -b:a "${ARCHIVE_KBPS}k" "$MP3" 2>>"$LOG"; then
    rm -f "$WAV"
    echo "$(date '+%F %T') 💾 wav→mp3: $(basename "$MP3") ($(du -h "$MP3" | cut -f1))" | tee -a "$LOG"
  fi
fi
