#!/usr/bin/env bash
# Diktatūra — sutranskribuoja VISUS įrašus, kurie dar neturi teksto.
# Naudoja: naktinis timer (01:30) ir `make transcribe-pending`. Serializuota per transcribe-file.sh (flock).
# Praleidžia: turinčius tekstą, pažymėtus *.skip, šiuo metu rašomą failą.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
log(){ echo "$(date '+%F %T') [pending] $*" | tee -a "$LOG_TRANSCRIBE" >&2; }
load_config
DBG_TAG=pending

# Būsenos faile: "<šaltinis> <rašomo failo kelias>"
active=""; [ -f "$STATE_RECORDING" ] && active="$(cut -d' ' -f2- "$STATE_RECORDING" 2>/dev/null)"

shopt -s nullglob
pending=()
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

if [ ${#pending[@]} -eq 0 ]; then
  log "nieko transkribuoti — visi įrašai turi tekstą."
  exit 0
fi
log "rasta ${#pending[@]} įrašų be teksto. Transkribuoju (po vieną)..."
for f in "${pending[@]}"; do
  log "→ $(basename "$f")"
  bash "$REPO/bin/transcribe-file.sh" "$f"
done
log "baigta: ${#pending[@]} įrašų."
