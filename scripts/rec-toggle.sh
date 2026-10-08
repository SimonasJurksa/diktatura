#!/usr/bin/env bash
# Rankinis start/stop VIENA komanda (toggle).
#   1 kartą paleidi -> pradeda įrašymą
#   dar kartą paleidi -> sustabdo (WAV užsidaro tvarkingai)
# Patogu susieti su klaviatūros klavišu (žr. apačioje).
#   bash ~/wispr/scripts/rec-toggle.sh [vardas]
set -euo pipefail

REC_DIR="$HOME/wispr/recordings"
PIDFILE="$REC_DIR/.rec.pid"
mkdir -p "$REC_DIR"

# --- STOP ---
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  pid="$(cat "$PIDFILE")"
  kill -INT "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5; do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done
  rm -f "$PIDFILE"
  last="$(ls -t "$REC_DIR"/*.wav 2>/dev/null | head -1)"
  dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$last" 2>/dev/null || echo '?')"
  notify-send "🛑 Įrašymas sustabdytas" "$(basename "$last") (${dur%.*}s)" 2>/dev/null || true
  echo "STOP. Išsaugota: $last (${dur%.*}s)"
  exit 0
fi

# --- START ---
NAME="${1:-rec}"
OUT="$REC_DIR/${NAME}_$(date +%Y%m%d_%H%M%S).wav"
MIC="$(pactl get-default-source)"
MON="$(pactl get-default-sink).monitor"

# STEREO: kairys = mic (tu), dešinys = sistemos garsas (kolegos) — diarizacijai patogu.
ffmpeg -hide_banner -loglevel warning \
  -f pulse -i "$MIC" \
  -f pulse -i "$MON" \
  -filter_complex "[0:a]pan=mono|c0=0.5*c0+0.5*c1[l];[1:a]pan=mono|c0=0.5*c0+0.5*c1[r];[l][r]join=inputs=2:channel_layout=stereo[a]" \
  -map "[a]" -ac 2 -ar 16000 -c:a pcm_s16le "$OUT" >/dev/null 2>&1 &

echo $! > "$PIDFILE"
notify-send "🔴 Įrašymas pradėtas" "$(basename "$OUT")" 2>/dev/null || true
echo "START. Rašau į: $OUT  (PID $(cat "$PIDFILE"))"
echo "Sustabdyti: paleisk šį skriptą dar kartą."
