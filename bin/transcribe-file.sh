#!/usr/bin/env bash
# Diktatūra — centrinis „analizatorius": paima įrašą ir transkribuoja tinkamu būdu.
#   stereo (L=mic, R=monitor) -> diktatura.asr.transcribe_named (Tu / kolegos vardais, de-dup) -> *.named.txt
#   mono                      -> diktatura.asr.transcribe                                    -> *.txt
# Pirmiausia — garso bangos smailės <bazė>.peaks (🌊 Tekste ir ⏳ langelyje; diktatura.waveform).
# Po to: tuščias tekstas -> (DELETE_EMPTY) trinami ir tekstas, ir garsas; yra tekstas -> (ARCHIVE_MP3) wav -> mp3.
# Tuščias failas (≤ 44 B — įrašymas nutrūko, pvz. pilnas diskas) netranskribuojamas, o ištrinamas.
# Pabaigoje (bet kokiu atveju) — seno garso valymas pagal nustatymus (diktatura.cleanup, AUDIO_CLEANUP).
#   bash bin/transcribe-file.sh <garsas> [<išvesties bazė>]
# Išvesties bazė — sekamų aplankų failams (diktatura.sources: telefonas, laikrodis, studija): tekstas, banga ir .skip
#   rašomi ten (<bazė>.named.txt …), o garsas — TAVO failas — niekada netrinamas, nekeičiamas ir neperkoduojamas.
#   Visas garsas transkribuojamas kaip vienas kanalas, kalbėtojai — pagal balsus (tavo balsas — „Tu").
# DIKTATURA_RETRANSCRIBE=1 — „🔁 Transkribuoti iš naujo": naujas tekstas rašomas į laikiną failą ir senąjį pakeičia tik
#   pavykus (senasis išsaugomas kaip <tekstas>.prev); tuščias rezultatas ar klaida nieko netrina.
# ASR_SERVER=1 + veikiantis diktatura-asr.service -> transkribuoja nuolat įkrautas modelis (be krovimo laiko).
# Env (nebūtini): DIKTATURA_MODEL / DIKTATURA_THREADS (perrašo config),
#                 DIKTATURA_ASR_CMD — testams: komanda "<cmd> <garsas> <išvesties .txt>" vietoj tikro ASR.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"

IN="${1:?reikia garso failo kelio}"
OUTBASE="${2:-}"
[ -f "$IN" ] || { echo "Nėra failo: $IN" >&2; exit 1; }
load_config
DBG_TAG=transcribe
T_START=$(date +%s)
MODEL_ARG="$(model_path "${DIKTATURA_MODEL:-$MODEL}")"
THREADS="${DIKTATURA_THREADS:-$THREADS}"
BASE="${IN%.*}"
SOURCE=0
if [ -n "$OUTBASE" ]; then SOURCE=1; BASE="$OUTBASE"; mkdir -p "$(dirname "$BASE")"; fi
RETX="${DIKTATURA_RETRANSCRIBE:-0}"
export DIKTATURA_PEAKS="$BASE.peaks"          # ASR modulio eigos failui: kur 🌊 banga (⏳ langelis)
log(){ echo "$(date '+%F %T') $*" | tee -a "$LOG_TRANSCRIBE"; }
# Transkripcija MAKSIMALIAI nusileidžia (nice 19 + ionice idle) — įrašymo capture turi pirmenybę.
LOWPRIO="nice -n 19"
command -v ionice >/dev/null 2>&1 && LOWPRIO="ionice -c 3 nice -n 19"

# Diktatūra išjungta ikonos „Išeiti" (ir langas neatidarytas) — transkripcija būtų nematoma: nepradedam (failas lieka
# be teksto — padarys, kai vėl įjungsi). Tikrinama ir po laukimo eilėje: „Išeiti" galėjo būti paspaustas tuo metu.
quit_skip(){ app_quit || return 1; log "PRALEISTA — Diktatūra išjungta (ikonos „Išeiti“), transkribuos vėliau: $(basename "$IN")"; }
quit_skip && exit 0
# EILĖ: tik VIENA transkripcija vienu metu (Ąžuolas ~3.3 GB — dvi lygiagrečiai = OOM / capture badavimas).
exec 9>"$TRANSCRIBE_LOCK"
if ! flock -n 9; then
  log "EILĖJE (laukia ankstesnės transkripcijos): $(basename "$IN")"
  flock 9
  quit_skip && exit 0
fi
# seno garso valymas — po kiekvienos transkripcijos, dar laikant eilės užraktą (dvi valymo kopijos nesusidurs)
# ⏭ „Praleisti" (diktatura.progress.skip_current) palieka žymę <runtime>/skip/<šio bash pid> ir nužudo vaikus;
# žymė tikrinama prieš kiekvieną sunkų žingsnį — kitaip paspaudus TARP žingsnių (nėra ką žudyti) darbas eitų toliau.
SKIP_MARK="$RUN_DIR/skip/$$"
skipped(){
  [ -f "$SKIP_MARK" ] || return 1
  log "⏭ nutraukta ($1) — garsas paliktas: $(basename "$IN")"
  return 0
}
trap 'rm -f "$SKIP_MARK"; "$PY" -m diktatura.cleanup >/dev/null 2>>"$LOG_TRANSCRIBE" || true' EXIT
# kol laukė eilėje, failas galėjo būti ištrintas (Nustatymai -> „Ištrinti įrašus ir tekstus")
[ -f "$IN" ] || { log "PRALEISTA (failas ištrintas, kol laukė eilėje): $(basename "$IN")"; exit 0; }
# 0 B / tik antraštė: garso nėra (VOX nulūžo pilname diske) — kitaip naktinis jį bandytų kas naktį
if [ "$(stat -c %s "$IN")" -le 44 ]; then
  if [ "$SOURCE" = 1 ]; then
    : > "$BASE.skip"
    log "∅ tuščias failas — praleista (sekamas aplankas; failas nepaliestas): $IN"
  else
    rm -f "$IN"
    log "∅ tuščias failas (įrašymas nutrūko, pvz. pilnas diskas) — ištrinta $(basename "$IN")"
  fi
  exit 0
fi

# 🌊 bangos smailės — prieš transkripciją, kad ⏳ langelis jau rodytų bangą (2 val. įrašui ~10–30 s).
# Nepavyko — ne bėda (transkribuojam toliau); nužudytas signalu (⏳ „Praleisti" / „Sustabdyti") — darbas baigtas.
$LOWPRIO "$PY" -m diktatura.waveform "$IN" --out "$BASE.peaks" >/dev/null 2>>"$LOG_TRANSCRIBE"
rc=$?
if [ "$rc" -ge 128 ] || [ -f "$SKIP_MARK" ]; then
  log "⏭ nutraukta (bangos skaičiavimo metu) — garsas paliktas: $(basename "$IN")"
  exit 1
fi
[ "$rc" = 0 ] || dbg "bangos smailių nepavyko suskaičiuoti: $IN"

chans="$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of csv=p=0 "$IN" 2>/dev/null)"
EXTRA=()
if [ "$SOURCE" = 1 ]; then OUT="$BASE.named.txt"; MOD="diktatura.asr.transcribe_named"; EXTRA=(--source)
elif [ "$chans" = "2" ]; then OUT="$BASE.named.txt"; MOD="diktatura.asr.transcribe_named"
else OUT="$BASE.txt"; MOD="diktatura.asr.transcribe"; fi
FINAL="$OUT"
SRT="$BASE.srt"
if [ "$RETX" = 1 ]; then          # laikini vardai be .txt galo — Teksto langas jų nerodo kaip atskiros sesijos
  OUT="$FINAL.retx"; SRT="$BASE.srt.retx"
fi
[ "$MOD" = diktatura.asr.transcribe ] && EXTRA=(--srt "$SRT")
log "ANALIZĖ pradėta: $(basename "$IN") (${chans}ch, modelis=$(basename "$MODEL_ARG"))$( [ "$SOURCE" = 1 ] && echo " → $(dirname "$BASE")")$( [ "$RETX" = 1 ] && echo " — iš naujo")"
dbg "įvestis=$IN kanalai=$chans modulis=$MOD išvestis=$OUT modelis=$MODEL_ARG gijos=$THREADS laukta eilėje=$(( $(date +%s) - T_START ))s"
T_ASR=$(date +%s)

skipped "prieš transkripciją" && exit 1
if [ -n "${DIKTATURA_ASR_CMD:-}" ]; then
  $DIKTATURA_ASR_CMD "$IN" "$OUT" >>"$LOG_TRANSCRIBE" 2>&1
else
  # ASR_SERVER=1 ir serveris veikia -> modelis jau atmintyje (diktatura.asr.client); kitaip — atskiras procesas
  rc=75
  if [ "${ASR_SERVER:-0}" = 1 ] && [ -S "$RUN_DIR/asr.sock" ]; then
    KIND=mono; [ "$MOD" = diktatura.asr.transcribe_named ] && KIND=named
    "$PY" -m diktatura.asr.client "$KIND" "$IN" --model "$MODEL_ARG" --threads "$THREADS" --out "$OUT" \
      "${EXTRA[@]}" >>"$LOG_TRANSCRIBE" 2>&1
    rc=$?
    dbg "ASR serveris: rc=$rc"
  fi
  if [ "$rc" = 75 ]; then
    OMP_NUM_THREADS="$THREADS" $LOWPRIO "$PY" -m "$MOD" "$IN" --model "$MODEL_ARG" --threads "$THREADS" \
      --out "$OUT" "${EXTRA[@]}" >>"$LOG_TRANSCRIBE" 2>&1
  fi
fi

if skipped "transkripcijos metu"; then
  rm -f "$OUT" "$SRT"
  exit 1
fi
dbg "ASR baigtas per $(( $(date +%s) - T_ASR ))s; išvestis $( [ -f "$OUT" ] && echo "$(wc -c < "$OUT") B" || echo NĖRA)"
if [ ! -f "$OUT" ]; then
  log "⚠ transkripcija nedavė failo (žlugo?) — garsas paliktas: $(basename "$IN")"
  exit 1
fi

if [ -z "$(tr -d '[:space:]' < "$OUT" 2>/dev/null)" ]; then
  if [ "$RETX" = 1 ]; then
    rm -f "$OUT" "$SRT"
    log "🔁 iš naujo: naujas tekstas tuščias — paliktas senasis $(basename "$FINAL")"
  elif [ "$SOURCE" = 1 ]; then
    rm -f "$OUT" "$SRT"
    : > "$BASE.skip"
    log "∅ tuščias tekstas (ne kalba) — praleista, failas nepaliestas: $IN"
  elif [ "$DELETE_EMPTY" = "1" ]; then
    rm -f "$OUT" "$IN" "$BASE.srt" "$BASE.peaks"
    log "∅ tuščias tekstas (ne kalba) — ištrinta $(basename "$IN") + $(basename "$OUT")"
  else
    log "∅ tuščias tekstas — palikta (DELETE_EMPTY=0): $(basename "$OUT")"
  fi
  exit 0
fi

if [ "$RETX" = 1 ]; then
  [ -f "$FINAL" ] && cp -p "$FINAL" "$FINAL.prev"
  mv -f "$OUT" "$FINAL"
  [ -f "$SRT" ] && mv -f "$SRT" "$BASE.srt"
  OUT="$FINAL"
  log "🔁 transkribuota iš naujo: $(basename "$FINAL") (ankstesnis tekstas — $(basename "$FINAL").prev)"
fi
log "ANALIZĖ baigta: $OUT"
notify-send -t 20000 "✅ Tekstas: $(basename "$OUT")" "$(head -c 800 "$OUT" 2>/dev/null)" 2>/dev/null || true

# Archyvas: wav -> mažas mp3 (taupo vietą), wav trinamas. mp3 įvestis ir sekamų aplankų failai — nekeičiami.
if [ "$SOURCE" = 0 ] && [ "$ARCHIVE_MP3" = "1" ] && [ "${IN##*.}" = "wav" ]; then
  MP3="$BASE.mp3"
  if ffmpeg -hide_banner -loglevel error -y -i "$IN" -c:a libmp3lame -b:a "${ARCHIVE_KBPS}k" "$MP3" 2>>"$LOG_TRANSCRIBE"; then
    rm -f "$IN"
    log "💾 wav→mp3: $(basename "$MP3") ($(du -h "$MP3" | cut -f1))"
    dbg "archyvas: $MP3 (${ARCHIVE_KBPS} kbps)"
  fi
fi
exit 0
