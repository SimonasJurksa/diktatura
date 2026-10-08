#!/usr/bin/env bash
# Įrašo mic + sistemos garsą (monitor) į vieną 16 kHz mono WAV (Whisper formatas).
# Naudojimas:
#   bash ~/wispr/scripts/record.sh [vardas]
# Sustabdyti: Ctrl+C arba  kill <PID>  (WAV lieka tvarkingas).
set -euo pipefail

REC_DIR="$HOME/wispr/recordings"
mkdir -p "$REC_DIR"
NAME="${1:-slack}"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$REC_DIR/${NAME}_${TS}.wav"

# Auto-aptikti numatytuosius įrenginius
MIC="$(pactl get-default-source)"
SINK="$(pactl get-default-sink)"
MON="${SINK}.monitor"

echo "Mic   : $MIC"
echo "Monitor: $MON"
echo "Rašau į: $OUT"
echo "(Ctrl+C sustabdyti)"

# STEREO: kairys kanalas = mic (tu), dešinys = sistemos garsas (kolegos).
# Diarizacijai patogu (tave atskiria trivialiai); transcribe.py downmixina į mono automatiškai.
# Kiekvieną šaltinį -> mono -> join į stereo. volume=1.5 kompensuoja tylumą.
exec ffmpeg -hide_banner -loglevel warning \
  -f pulse -i "$MIC" \
  -f pulse -i "$MON" \
  -filter_complex "[0:a]pan=mono|c0=0.5*c0+0.5*c1[l];[1:a]pan=mono|c0=0.5*c0+0.5*c1[r];[l][r]join=inputs=2:channel_layout=stereo[a]" \
  -map "[a]" -ac 2 -ar 16000 -c:a pcm_s16le \
  "$OUT"
