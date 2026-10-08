#!/usr/bin/env bash
# Diktatūra — vienkartinė Ąžuolo (akisviete/azuolas-whisper-lt) konversija į CTranslate2 int8,
# kad veiktų su faster-whisper. torch/transformers reikia TIK konversijai — jie diegiami į LAIKINĄ
# venv, kuris po konversijos ištrinamas (pagrindinis .venv lieka be torch).
#   make model-convert     (arba: bash tools/convert_azuolas.sh)
# Rezultatas: <duomenys>/models/azuolas-ct2 (~1.5 GB). Konversijos metu reikia ~8–10 GB laisvų.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../bin/common.sh"

OUT="$MODELS/azuolas-ct2"
SRC_ID="akisviete/azuolas-whisper-lt"
TMPVENV="$MODELS/.convert-venv"

echo "== Ąžuolo konversija =="
if [ -f "$OUT/model.bin" ]; then
  echo "Jau sukonvertuota: $OUT"; exit 0
fi
df -h "$MODELS" | tail -1
avail=$(df --output=avail -BG "$MODELS" | tail -1 | tr -dc '0-9')
[ "$avail" -lt 8 ] && { echo "STOP: <8 GB disko ($avail GB)"; exit 1; }

trap 'rm -rf "$TMPVENV"' EXIT
echo "-- laikinas venv: torch(CPU) + transformers (tik konversijai) --"
uv venv "$TMPVENV" --python 3.10 -q
VIRTUAL_ENV="$TMPVENV" uv pip install -q "torch" --index-url https://download.pytorch.org/whl/cpu
VIRTUAL_ENV="$TMPVENV" uv pip install -q "transformers<5" "ctranslate2>=4"

echo "-- konvertuoju -> $OUT (int8) --"
# large-v3 bazė: 128 mel filtrų; ct2 konverteris tai paima iš preprocessor_config.
"$TMPVENV/bin/ct2-transformers-converter" \
  --model "$SRC_ID" \
  --output_dir "$OUT" \
  --quantization int8 \
  --copy_files tokenizer.json preprocessor_config.json \
  --low_cpu_mem_usage

echo "-- padaryta --"
du -sh "$OUT"
