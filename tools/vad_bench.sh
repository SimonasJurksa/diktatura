#!/usr/bin/env bash
# Diktatūra — VAD naudos matavimas: TAS PATS įrašas su --vad off ir --vad trim (laikas, RTF, ar tekstas nesiskiria).
# BENCH_MODES — kurie režimai (numatyta "off trim"; galimi off / on / trim).
#   bash tools/vad_bench.sh <stereo.wav|mp3> [pradžia_s] [trukmė_s]
# Izoliuota: laikinas DIKTATURA_DATA (modeliai — symlink; tikri balsai / pending / tekstai neliečiami), rezultatai
# ištrinami (BENCH_KEEP=<katalogas> — abu tekstai nukopijuojami ten palyginimui). Laukia TIKRO transkripcijos
# užrakto (du Ąžuolai vienu metu = OOM). Gijos: BENCH_THREADS (numatyta 4).
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../bin/common.sh"
IN="${1:?reikia stereo įrašo}"; SS="${2:-0}"; DUR="${3:-}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/data/recordings" "$TMP/cfg" "$TMP/state" "$TMP/run"
ln -s "$MODELS" "$TMP/data/models"
ffmpeg -hide_banner -loglevel error -ss "$SS" ${DUR:+-t "$DUR"} -i "$IN" -ac 2 -ar 16000 "$TMP/bench.wav"
exec 9>"$TRANSCRIBE_LOCK"
flock 9                                   # palaukti, kol baigsis tikra transkripcija
MODES=(${BENCH_MODES:-off trim})
for v in "${MODES[@]}"; do
  cp "$TMP/bench.wav" "$TMP/data/recordings/bench_$v.wav"
  start=$(date +%s.%N)
  DIKTATURA_DATA="$TMP/data" DIKTATURA_CONFIG_DIR="$TMP/cfg" DIKTATURA_STATE="$TMP/state" DIKTATURA_RUN="$TMP/run" \
    OMP_NUM_THREADS="${BENCH_THREADS:-4}" nice -n 10 "$PY" -m diktatura.asr.transcribe_named \
    "$TMP/data/recordings/bench_$v.wav" --vad "$v" --threads "${BENCH_THREADS:-4}" > "$TMP/$v.log" 2>&1
  wall=$(echo "$(date +%s.%N) - $start" | bc)
  words=$(wc -w < "$TMP/data/recordings/bench_$v.named.txt")
  echo "── VAD $v: viso ${wall%.*} s, žodžių $words"
  [ -n "${BENCH_KEEP:-}" ] && mkdir -p "$BENCH_KEEP" && cp "$TMP/data/recordings/bench_$v.named.txt" "$BENCH_KEEP/"
  grep -E "^VAD|RTF" "$TMP/$v.log" | sed 's/^/   /'
done
a="$TMP/data/recordings/bench_${MODES[0]}.named.txt"; b="$TMP/data/recordings/bench_${MODES[-1]}.named.txt"
echo "── teksto skirtumas ${MODES[0]} vs ${MODES[-1]} (žodžiai): $(diff <(tr -s ' \n' '\n' < "$a" | grep -v '^\[') \
  <(tr -s ' \n' '\n' < "$b" | grep -v '^\[') | grep -c '^[<>]' || true) eil."
