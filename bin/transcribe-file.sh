#!/usr/bin/env bash
# Diktatūra — centrinis „analizatorius": paima įrašą ir transkribuoja tinkamu būdu.
#   stereo (L=mic, R=monitor) -> diktatura.asr.transcribe_named (Tu / kolegos vardais, de-dup) -> *.named.txt
#   mono                      -> diktatura.asr.transcribe                                    -> *.txt
# Po to: tuščias tekstas -> (DELETE_EMPTY) trinami ir tekstas, ir garsas; yra tekstas -> (ARCHIVE_MP3) wav -> mp3.
#   bash bin/transcribe-file.sh <failas.wav|failas.mp3>
# ASR_SERVER=1 + veikiantis diktatura-asr.service -> transkribuoja nuolat įkrautas modelis (be krovimo laiko).
# Env (nebūtini): DIKTATURA_MODEL / DIKTATURA_THREADS (perrašo config),
#                 DIKTATURA_ASR_CMD — testams: komanda "<cmd> <garsas> <išvesties .txt>" vietoj tikro ASR.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"

IN="${1:?reikia garso failo kelio}"
[ -f "$IN" ] || { echo "Nėra failo: $IN" >&2; exit 1; }
load_config
DBG_TAG=transcribe
T_START=$(date +%s)
MODEL_ARG="$(model_path "${DIKTATURA_MODEL:-$MODEL}")"
THREADS="${DIKTATURA_THREADS:-$THREADS}"
BASE="${IN%.*}"
log(){ echo "$(date '+%F %T') $*" | tee -a "$LOG_TRANSCRIBE"; }

# EILĖ: tik VIENA transkripcija vienu metu (Ąžuolas ~3.3 GB — dvi lygiagrečiai = OOM / capture badavimas).
exec 9>"$TRANSCRIBE_LOCK"
if ! flock -n 9; then
  log "EILĖJE (laukia ankstesnės transkripcijos): $(basename "$IN")"
  flock 9
fi

chans="$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of csv=p=0 "$IN" 2>/dev/null)"
if [ "$chans" = "2" ]; then OUT="$BASE.named.txt"; MOD="diktatura.asr.transcribe_named"
else OUT="$BASE.txt"; MOD="diktatura.asr.transcribe"; fi
log "ANALIZĖ pradėta: $(basename "$IN") (${chans}ch, modelis=$(basename "$MODEL_ARG"))"
dbg "įvestis=$IN kanalai=$chans modulis=$MOD išvestis=$OUT modelis=$MODEL_ARG gijos=$THREADS laukta eilėje=$(( $(date +%s) - T_START ))s"
T_ASR=$(date +%s)

# Transkripcija MAKSIMALIAI nusileidžia (nice 19 + ionice idle) — įrašymo capture turi pirmenybę.
LOWPRIO="nice -n 19"
command -v ionice >/dev/null 2>&1 && LOWPRIO="ionice -c 3 nice -n 19"
if [ -n "${DIKTATURA_ASR_CMD:-}" ]; then
  $DIKTATURA_ASR_CMD "$IN" "$OUT" >>"$LOG_TRANSCRIBE" 2>&1
else
  # ASR_SERVER=1 ir serveris veikia -> modelis jau atmintyje (diktatura.asr.client); kitaip — atskiras procesas
  rc=75
  if [ "${ASR_SERVER:-0}" = 1 ] && [ -S "$RUN_DIR/asr.sock" ]; then
    KIND=mono; [ "$MOD" = diktatura.asr.transcribe_named ] && KIND=named
    "$PY" -m diktatura.asr.client "$KIND" "$IN" --model "$MODEL_ARG" --threads "$THREADS" >>"$LOG_TRANSCRIBE" 2>&1
    rc=$?
    dbg "ASR serveris: rc=$rc"
  fi
  if [ "$rc" = 75 ]; then
    OMP_NUM_THREADS="$THREADS" $LOWPRIO "$PY" -m "$MOD" "$IN" --model "$MODEL_ARG" --threads "$THREADS" \
      >>"$LOG_TRANSCRIBE" 2>&1
  fi
fi

dbg "ASR baigtas per $(( $(date +%s) - T_ASR ))s; išvestis $( [ -f "$OUT" ] && echo "$(wc -c < "$OUT") B" || echo NĖRA)"
if [ ! -f "$OUT" ]; then
  log "⚠ transkripcija nedavė failo (žlugo?) — garsas paliktas: $(basename "$IN")"
  exit 1
fi

if [ -z "$(tr -d '[:space:]' < "$OUT" 2>/dev/null)" ]; then
  if [ "$DELETE_EMPTY" = "1" ]; then
    rm -f "$OUT" "$IN" "$BASE.srt"
    log "∅ tuščias tekstas (ne kalba) — ištrinta $(basename "$IN") + $(basename "$OUT")"
  else
    log "∅ tuščias tekstas — palikta (DELETE_EMPTY=0): $(basename "$OUT")"
  fi
  exit 0
fi

log "ANALIZĖ baigta: $OUT"
notify-send -t 20000 "✅ Tekstas: $(basename "$OUT")" "$(head -c 800 "$OUT" 2>/dev/null)" 2>/dev/null || true

# Archyvas: wav -> mažas mp3 (taupo vietą), wav trinamas. mp3 įvestis paliekama kaip yra.
if [ "$ARCHIVE_MP3" = "1" ] && [ "${IN##*.}" = "wav" ]; then
  MP3="$BASE.mp3"
  if ffmpeg -hide_banner -loglevel error -y -i "$IN" -c:a libmp3lame -b:a "${ARCHIVE_KBPS}k" "$MP3" 2>>"$LOG_TRANSCRIBE"; then
    rm -f "$IN"
    log "💾 wav→mp3: $(basename "$MP3") ($(du -h "$MP3" | cut -f1))"
    dbg "archyvas: $MP3 (${ARCHIVE_KBPS} kbps)"
  fi
fi
exit 0
