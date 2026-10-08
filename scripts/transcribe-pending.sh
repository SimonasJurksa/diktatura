#!/usr/bin/env bash
# Sutranskribuoja VISUS įrašus, kurie dar neturi teksto (*.named.txt).
# Praleidžia tą, kuris šiuo metu įrašomas. Serializuota per transcribe-file.sh flock.
# Naudoja: naktinis timer (01:30) ir `make transcribe-pending`.
set -uo pipefail

REC="$HOME/wispr/recordings"
LOG="$REC/transcribe.log"
log(){ echo "$(date '+%F %T') [pending] $*" | tee -a "$LOG" >&2; }

shopt -s nullglob
pending=()
for wav in "$REC"/slack_*.wav "$REC"/vox_*.wav; do
  base="${wav%.wav}"
  # praleidžiam jei JAU yra bet koks tekstas
  [ -f "${base}.named.txt" ] && continue
  [ -f "${base}.clean.dialog.txt" ] && continue
  [ -f "${base}.dialog.txt" ] && continue
  [ -f "${base}.txt" ] && continue
  [ -f "${base}.skip" ] && continue               # rankinis „nepaisyti" žymeklis
  if pgrep -af "ffmpeg" 2>/dev/null | grep -qF "$wav"; then
    log "praleidžiu (dar įrašomas): $(basename "$wav")"; continue
  fi
  pending+=("$wav")
done

if [ ${#pending[@]} -eq 0 ]; then
  log "nieko transkribuoti — visi įrašai turi tekstą."
  exit 0
fi

log "rasta ${#pending[@]} įrašų be teksto. Transkribuoju (po vieną)..."
for wav in "${pending[@]}"; do
  log "→ $(basename "$wav")"
  bash "$HOME/wispr/scripts/transcribe-file.sh" "$wav"   # flock = po vieną
done
log "baigta: ${#pending[@]} įrašų."
