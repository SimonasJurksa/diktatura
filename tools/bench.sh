#!/usr/bin/env bash
# Diktatūra — palygina modelius ant TO PATIES garso klipo (kokybė + RTF).
# Naudojimas: bash tools/bench.sh <audio.wav> "medium azuolas-ct2"
# Rezultatai: <duomenys>/recordings/bench/bench_<modelis>.{log,txt}   (BENCH_OUT perrašo katalogą)
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../bin/common.sh"
CLIP="${1:?reikia audio kelio}"
MODEL_LIST="${2:-medium azuolas-ct2}"
OUTDIR="${BENCH_OUT:-$RECORDINGS/bench}"
mkdir -p "$OUTDIR"

for m in $MODEL_LIST; do
  safe="${m//\//_}"
  tmp="$OUTDIR/bench_${safe}.wav"
  cp "$CLIP" "$tmp"      # transcribe.py rašo .txt šalia garso — kiekvienam modeliui atskira kopija
  echo "######## MODELIS: $m ########"
  OMP_NUM_THREADS=6 nice -n 10 "$PY" -m diktatura.asr.transcribe \
    "$tmp" --model "$m" --threads 6 --lang lt 2>&1 | tee "$OUTDIR/bench_${safe}.log"
  rm -f "$tmp"
  echo
done
echo "Logai ir tekstai: $OUTDIR/"
