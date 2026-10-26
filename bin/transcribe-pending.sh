#!/usr/bin/env bash
# Diktatūra — sutranskribuoja VISUS įrašus, kurie dar neturi teksto: įrašų katalogą ir sekamus aplankus.
# Naudoja: naktinis timer (01:30) ir `make transcribe-pending`. Serializuota per transcribe-file.sh (flock).
# Praleidžia: turinčius tekstą, pažymėtus *.skip, šiuo metu rašomą failą.
# Sekami aplankai (diktatura.sources: telefonas, laikrodis…): tekstai rašomi į <duomenys>/sources/<id>/, tavo garso
# failai nekeičiami (bin/transcribe-file.sh <garsas> <išvesties bazė>).
#   --sources       tik sekami aplankai (diktatura-sources.timer kas ~2 min; be įrašų katalogo)
#   --if-immediate  nieko nedaryti, jei MODE ne „immediate" arba AUTOTRANSCRIBE=0 (timer'is — tik „iškart" režimui)
# Diktatūra išjungta ikonos „Išeiti" (ir langas neatidarytas) — nieko nedaro (common.sh app_quit): transkripcija būtų
# nematoma. make transcribe-pending (DIKTATURA_IGNORE_QUIT=1) — vis tiek transkribuoja (eiga matosi terminale).
# Pabaigoje — seno garso valymas pagal nustatymus (diktatura.cleanup; kas naktį, net jei transkribuoti nebuvo ką).
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
log(){ echo "$(date '+%F %T') [pending] $*" | tee -a "$LOG_TRANSCRIBE" >&2; }
load_config
DBG_TAG=pending
SOURCES_ONLY=0; IF_IMMEDIATE=0
for a in "$@"; do
  case "$a" in
    --sources) SOURCES_ONLY=1 ;;
    --if-immediate) IF_IMMEDIATE=1 ;;
  esac
done
if [ "$IF_IMMEDIATE" = 1 ] && { [ "${AUTOTRANSCRIBE:-1}" != 1 ] || [ "${MODE:-immediate}" != immediate ]; }; then
  exit 0
fi
if app_quit; then
  [ "$SOURCES_ONLY" = 1 ] || log "Diktatūra išjungta (ikonos „Išeiti“) — transkripcija neprasideda, kol vėl neįjungsi (programų meniu / make tray-on)."
  exit 0                                    # sekami aplankai (kas 2 min) — tyliai
fi

# Būsenos faile: "<šaltinis> <rašomo failo kelias>"
active=""; [ -f "$STATE_RECORDING" ] && active="$(cut -d' ' -f2- "$STATE_RECORDING" 2>/dev/null)"

shopt -s nullglob
pending=()
if [ "$SOURCES_ONLY" = 0 ]; then
  for f in "$RECORDINGS"/{slack,vox,rec}_*.wav; do
    base="${f%.wav}"
    for ext in named.txt clean.dialog.txt dialog.txt txt skip; do
      [ -f "$base.$ext" ] && { dbg "praleidžiu $(basename "$f"): yra .$ext"; continue 2; }
    done
    # rašomas dabar (būsenos failas) arba ką tik keistas (saugiklis) — praleidžiam
    if [ "$f" = "$active" ] || [ $(( $(date +%s) - $(stat -c %Y "$f") )) -lt 15 ]; then
      log "praleidžiu (dar įrašomas): $(basename "$f")"; continue
    fi
    pending+=("$f")
  done
fi
# sekami aplankai: „<garsas>\t<išvesties bazė>" (diktatura.sources įrašo ir .src.json — iš kur ir kada įrašyta)
src_audio=(); src_base=()
while IFS=$'\t' read -r a b; do
  [ -n "$a" ] && [ -n "$b" ] && { src_audio+=("$a"); src_base+=("$b"); }
done < <("$PY" -m diktatura.sources pending 2>>"$LOG_TRANSCRIBE")

total=$(( ${#pending[@]} + ${#src_audio[@]} ))
if [ "$total" -eq 0 ]; then
  if [ "$SOURCES_ONLY" = 0 ]; then
    "$PY" -m diktatura.cleanup >/dev/null 2>>"$LOG_TRANSCRIBE" || true
    log "nieko transkribuoti — visi įrašai turi tekstą."
  fi
  exit 0                                    # timer'is kas 2 min — tylus, kai nėra ką daryti
fi
trap '"$PY" -m diktatura.cleanup >/dev/null 2>>"$LOG_TRANSCRIBE" || true' EXIT
log "rasta $total be teksto (įrašų ${#pending[@]}, sekamuose aplankuose ${#src_audio[@]}). Transkribuoju (po vieną)..."
for f in "${pending[@]}"; do
  log "→ $(basename "$f")"
  bash "$REPO/bin/transcribe-file.sh" "$f"
done
for i in "${!src_audio[@]}"; do
  log "→ $(basename "$(dirname "${src_base[$i]}")")/$(basename "${src_audio[$i]}")"
  bash "$REPO/bin/transcribe-file.sh" "${src_audio[$i]}" "${src_base[$i]}"
done
log "baigta: $total."
