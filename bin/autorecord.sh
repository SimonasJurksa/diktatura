#!/usr/bin/env bash
# Diktatūra — Slack skambučių auto-įrašymo daemon.
# Aptinka Slack skambutį (PulseAudio mic srautas iš Slack/ringrtc) ir automatiškai pradeda/sustabdo
# STEREO įrašymą (L = mikrofonas, R = sistemos garsas). Pasibaigus — pagal nustatymus transkribuoja.
#   Rankiniu būdu: bash bin/autorecord.sh      Nuolat: systemd --user diktatura-autorecord.service
#
# Nustatymai (gyvai, kiekvieną ciklą): SLACK_GRACE_SEC, MAX_REC_SEC, AUTOTRANSCRIBE, MODE.
# MAX_REC_SEC — saugiklis (pvz. paliktas huddle): įrašas sustabdomas ir NAUJAS nepradedamas, kol skambučio
# srautas nedings (kitaip pakibęs srautas gamintų begalę failų).
# Env (nebūtini): DIKTATURA_MATCH (klientų regex), DIKTATURA_POLL (s), DIKTATURA_PACTL (testams — imitacija).
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"

# Slack skambučiui atidaro mic source-output "Slack" (RecordStream) ir uždaro pasibaigus; ringrtc = huddle variklis.
MATCH="${DIKTATURA_MATCH:-Slack|ringrtc|WEBRTC VoiceEngine}"
POLL="${DIKTATURA_POLL:-2}"
PACTL="${DIKTATURA_PACTL:-pactl}"

log(){ echo "$(date '+%F %T') $*" | tee -a "$LOG_AUTOREC" >&2; }

REC_PID=""
CUR_FILE=""

call_active() {
  local hits
  hits="$($PACTL list source-outputs 2>/dev/null | grep -iE "application\.(name|process\.binary) = \"($MATCH)")"
  if [ "${DEBUG:-0}" = 1 ] || [ "${DIKTATURA_DEBUG:-0}" = 1 ]; then
    [ "$hits" != "${PREV_HITS:-}" ] && dbg "Slack srautai pasikeitė: ${hits:-(nėra)}"
    PREV_HITS="$hits"
  fi
  [ -n "$hits" ]
}

start_rec() {
  CUR_FILE="$RECORDINGS/slack_$(date +%Y%m%d_%H%M%S).wav"
  local MIC MON
  MIC="$($PACTL get-default-source)"
  MON="$($PACTL get-default-sink).monitor"
  # thread_queue_size — didelis įvesties buferis: transkripcijos apkrova neturi numesti garso
  ffmpeg -hide_banner -loglevel error \
    -thread_queue_size 8192 -f pulse -i "$MIC" \
    -thread_queue_size 8192 -f pulse -i "$MON" \
    -filter_complex "[0:a]pan=mono|c0=0.5*c0+0.5*c1[l];[1:a]pan=mono|c0=0.5*c0+0.5*c1[r];[l][r]join=inputs=2:channel_layout=stereo[a]" \
    -map "[a]" -ac 2 -ar 16000 -c:a pcm_s16le "$CUR_FILE" >>"$LOG_AUTOREC" 2>&1 &
  REC_PID=$!
  REC_START=$(date +%s)
  dbg "START: mic=$MIC sistema=$MON -> $CUR_FILE (ffmpeg pid $REC_PID)"
  echo "slack $CUR_FILE" > "$STATE_RECORDING"   # "<šaltinis> <kelias>" — ikonai ir transcribe-pending
  log "🔴 START skambutis aptiktas -> $(basename "$CUR_FILE") (pid $REC_PID)"
  notify-send "🔴 Slack įrašymas pradėtas" "$(basename "$CUR_FILE")" 2>/dev/null || true
}

stop_rec() {
  [ -z "$REC_PID" ] && return
  kill -INT "$REC_PID" 2>/dev/null || true
  wait "$REC_PID" 2>/dev/null || true
  rm -f "$STATE_RECORDING"
  local dur; dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$CUR_FILE" 2>/dev/null || echo '?')"
  log "🛑 STOP -> $(basename "$CUR_FILE") (${dur%.*}s)"
  notify-send "🛑 Slack įrašymas baigtas" "$(basename "$CUR_FILE") ${dur%.*}s" 2>/dev/null || true
  load_config
  if [ "${dur%.*}" = "0" ]; then
    :  # tuščias įrašas
  elif [ "$AUTOTRANSCRIBE" != "1" ]; then
    log "⏸ auto-transkripcija IŠJUNGTA — įrašas liko be teksto: $(basename "$CUR_FILE")"
  elif [ "$MODE" = "deferred" ]; then
    log "🌙 deferred — transkripcija naktį (01:30). Įrašas eilėje: $(basename "$CUR_FILE")"
  else
    log "▶ paleidžiu auto-transkripciją: $(basename "$CUR_FILE")"
    nohup bash "$REPO/bin/transcribe-file.sh" "$CUR_FILE" >/dev/null 2>&1 &
  fi
  REC_PID=""; CUR_FILE=""
}

cleanup(){ stop_rec; log "daemon sustabdytas"; exit 0; }
trap cleanup INT TERM

load_config
DBG_TAG=slack
log "daemon startavo (match=/$MATCH/ grace=${SLACK_GRACE_SEC}s max=${MAX_REC_SEC}s poll=${POLL}s)"
idle_since=0
maxed=0   # 1 = sustabdyta dėl MAX_REC_SEC; laukiam, kol skambučio srautas dings
while true; do
  load_config   # nustatymai gyvai — keitimai veikia be restarto
  if call_active; then
    idle_since=0
    [ -z "$REC_PID" ] && [ "$maxed" = 0 ] && start_rec
    if [ -n "$REC_PID" ] && [ $(( $(date +%s) - ${REC_START:-0} )) -ge "${MAX_REC_SEC%.*}" ]; then
      log "⏱ pasiekta maksimali trukmė (${MAX_REC_SEC}s) — stabdau (galbūt paliktas huddle); naujas įrašas — tik naujam skambučiui"
      stop_rec
      maxed=1
    fi
  elif [ "$maxed" = 1 ]; then
    maxed=0; log "skambučio srautas dingo — vėl laukiu skambučių"
  elif [ -n "$REC_PID" ]; then
    now=$(date +%s)
    [ "$idle_since" -eq 0 ] && idle_since=$now
    [ $((now - idle_since)) -ge "${SLACK_GRACE_SEC%.*}" ] && stop_rec
  fi
  sleep "$POLL"
done
