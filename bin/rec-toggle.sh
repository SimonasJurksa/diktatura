#!/usr/bin/env bash
# Diktatūra — rankinis įrašymas viena komanda (toggle): 1-as paleidimas pradeda, 2-as sustabdo.
# Patogu susieti su klaviatūros klavišu (GNOME: Settings → Keyboard → Custom Shortcuts):
#   bash <repo>/bin/rec-toggle.sh
# Įrašas STEREO (L = mikrofonas, R = sistemos garsas) -> recordings/rec_YYYYMMDD_HHMMSS.wav
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
PIDFILE="$RUN_DIR/rec-toggle.pid"

# --- STOP ---
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  pid="$(cat "$PIDFILE")"
  kill -INT "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done
  out="$(cut -d' ' -f2- "$STATE_RECORDING" 2>/dev/null || true)"
  rm -f "$PIDFILE" "$STATE_RECORDING"
  dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out" 2>/dev/null || echo '?')"
  notify-send "🛑 Įrašymas sustabdytas" "$(basename "$out") (${dur%.*}s)" 2>/dev/null || true
  echo "STOP. Išsaugota: $out (${dur%.*}s). Transkribuoti: make transcribe FILE=$out"
  exit 0
fi

# --- START ---
OUT="$RECORDINGS/rec_$(date +%Y%m%d_%H%M%S).wav"
MIC="$(pactl get-default-source)"
MON="$(pactl get-default-sink).monitor"
ffmpeg -hide_banner -loglevel warning \
  -thread_queue_size 8192 -f pulse -i "$MIC" \
  -thread_queue_size 8192 -f pulse -i "$MON" \
  -filter_complex "[0:a]pan=mono|c0=0.5*c0+0.5*c1[l];[1:a]pan=mono|c0=0.5*c0+0.5*c1[r];[l][r]join=inputs=2:channel_layout=stereo[a]" \
  -map "[a]" -ac 2 -ar 16000 -c:a pcm_s16le "$OUT" >/dev/null 2>&1 &
echo $! > "$PIDFILE"
echo "rec $OUT" > "$STATE_RECORDING"
notify-send "🔴 Įrašymas pradėtas" "$(basename "$OUT")" 2>/dev/null || true
echo "START. Rašau į: $OUT — sustabdyti: paleisk šį skriptą dar kartą."
