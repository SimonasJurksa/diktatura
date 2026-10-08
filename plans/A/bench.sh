#!/usr/bin/env bash
# Palygina modelius ant TO PATIES garso klipo (kokybė + RTF + resursai).
# Naudojimas: bash bench.sh <audio.wav> "small medium large-v3"
set -euo pipefail
CLIP="${1:?reikia audio kelio}"
MODELS="${2:-small medium large-v3}"
PY="$HOME/wispr/plans/A/.venv/bin/python"
OUTDIR="${BENCH_OUT:-$HOME/wispr/recordings/bench}"
mkdir -p "$OUTDIR"

for m in $MODELS; do
  safe="${m//\//_}"
  echo "######## MODELIS: $m ########"
  OMP_NUM_THREADS=6 nice -n 10 "$PY" "$HOME/wispr/plans/A/transcribe.py" \
    "$CLIP" --model "$m" --threads 6 --lang lt 2>&1 | tee "$OUTDIR/bench_${safe}.log"
  echo
done
echo "Logai: $OUTDIR/"
