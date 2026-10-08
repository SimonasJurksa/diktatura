#!/usr/bin/env bash
# Auto-įrašymo daemon: aptinka Slack skambutį (PulseAudio mic srautas iš Slack/ringrtc)
# ir automatiškai pradeda/sustabdo stereo įrašymą.
#   Rankiniu būdu: bash ~/wispr/scripts/autorecord.sh
#   Nuolat:        systemd --user service (žr. scripts/wispr-autorecord.service)
#
# Env kintamieji (nebūtini):
#   WISPR_MATCH   - regex klientams, kurie reiškia "skambutis" (def: Slack|ringrtc|WEBRTC)
#   WISPR_GRACE   - sek., kiek laukti po srauto dingimo prieš stabdant (def: 4) — prieš flapping
#   WISPR_POLL    - apklausos intervalas sek. (def: 2)
set -uo pipefail

REC_DIR="$HOME/wispr/recordings"
mkdir -p "$REC_DIR"
# Slack skambučiui atidaro mic source-output "Slack" (RecordStream) ir uždaro jį pasibaigus.
# (ringrtc/WEBRTC paliekam dėl visa ko.) Patikrinta: realūs skambučiai aptinkami per "Slack".
MATCH="${WISPR_MATCH:-Slack|ringrtc|WEBRTC VoiceEngine}"
GRACE="${WISPR_GRACE:-4}"
POLL="${WISPR_POLL:-2}"
# Saugiklis: jei huddle paliktas atidarytas, nerašyti amžinai (def 2h).
MAX_REC="${WISPR_MAX_REC:-7200}"
LOG="$REC_DIR/autorecord.log"

log(){ echo "$(date '+%F %T') $*" | tee -a "$LOG" >&2; }

REC_PID=""
CUR_FILE=""

call_active() {
  # Ar yra mic capture srautas (source-output) iš Slack/ringrtc?
  pactl list source-outputs 2>/dev/null | grep -qiE "application\.(name|process\.binary) = \"($MATCH)"
}

start_rec() {
  CUR_FILE="$REC_DIR/slack_$(date +%Y%m%d_%H%M%S).wav"
  local MIC MON
  MIC="$(pactl get-default-source)"
  MON="$(pactl get-default-sink).monitor"
  ffmpeg -hide_banner -loglevel error \
    -thread_queue_size 8192 -f pulse -i "$MIC" \
    -thread_queue_size 8192 -f pulse -i "$MON" \
    -filter_complex "[0:a]pan=mono|c0=0.5*c0+0.5*c1[l];[1:a]pan=mono|c0=0.5*c0+0.5*c1[r];[l][r]join=inputs=2:channel_layout=stereo[a]" \
    -map "[a]" -ac 2 -ar 16000 -c:a pcm_s16le "$CUR_FILE" >>"$LOG" 2>&1 &
  REC_PID=$!
  REC_START=$(date +%s)
  echo "slack" > "$REC_DIR/.recording"   # būsenos failas ikonai
  log "🔴 START skambutis aptiktas -> $(basename "$CUR_FILE") (pid $REC_PID)"
  notify-send "🔴 Slack įrašymas pradėtas" "$(basename "$CUR_FILE")" 2>/dev/null || true
}

stop_rec() {
  [ -z "$REC_PID" ] && return
  kill -INT "$REC_PID" 2>/dev/null || true
  wait "$REC_PID" 2>/dev/null || true
  rm -f "$REC_DIR/.recording"            # būsenos failas ikonai
  local dur; dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$CUR_FILE" 2>/dev/null || echo '?')"
  log "🛑 STOP -> $(basename "$CUR_FILE") (${dur%.*}s)"
  notify-send "🛑 Slack įrašymas baigtas" "$(basename "$CUR_FILE") ${dur%.*}s" 2>/dev/null || true
  # AUTO-ANALIZATORIUS: sprendžiam pagal config (skaitom gyvai kiekvieną kartą).
  local AUTOTRANSCRIBE=1 MODE=immediate
  [ -f "$HOME/wispr/wispr.conf" ] && . "$HOME/wispr/wispr.conf"
  if [ "${dur%.*}" = "0" ]; then
    :  # tuščias įrašas — nieko
  elif [ "$AUTOTRANSCRIBE" != "1" ]; then
    log "⏸ auto-transkripcija IŠJUNGTA — įrašas liko be teksto: $(basename "$CUR_FILE")"
  elif [ "$MODE" = "deferred" ]; then
    log "🌙 deferred — transkripcija naktį (01:30). Įrašas eilėje: $(basename "$CUR_FILE")"
  else
    log "▶ paleidžiu auto-transkripciją: $(basename "$CUR_FILE")"
    nohup bash "$HOME/wispr/scripts/transcribe-file.sh" "$CUR_FILE" >/dev/null 2>&1 &
  fi
  REC_PID=""; CUR_FILE=""
}

cleanup(){ stop_rec; log "daemon sustabdytas"; exit 0; }
trap cleanup INT TERM

log "daemon startavo (match=/$MATCH/ grace=${GRACE}s poll=${POLL}s)"
idle_since=0
while true; do
  if call_active; then
    idle_since=0
    [ -z "$REC_PID" ] && start_rec
    # Saugiklis: per ilgas įrašas (paliktas huddle) -> stabdom
    if [ -n "$REC_PID" ] && [ $(( $(date +%s) - ${REC_START:-0} )) -ge "$MAX_REC" ]; then
      log "⏱ pasiektas MAX_REC (${MAX_REC}s) — stabdau (galbūt paliktas huddle)"
      stop_rec
    fi
  else
    if [ -n "$REC_PID" ]; then
      # grace periodas prieš stabdant (trumpi srauto dingimai nenutraukia)
      now=$(date +%s)
      [ "$idle_since" -eq 0 ] && idle_since=$now
      if [ $((now - idle_since)) -ge "$GRACE" ]; then stop_rec; fi
    fi
  fi
  sleep "$POLL"
done
