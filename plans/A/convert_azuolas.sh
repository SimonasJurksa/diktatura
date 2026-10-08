#!/usr/bin/env bash
# Vienkartinė Ąžuolo (akisviete/azuolas-whisper-lt) konversija į CTranslate2 int8,
# kad veiktų su faster-whisper. torch/transformers reikia TIK konversijai.
#   bash ~/wispr/plans/A/convert_azuolas.sh
set -euo pipefail

VENV="$HOME/wispr/plans/A/.venv"
OUT="$HOME/wispr/models/azuolas-ct2"
SRC_ID="akisviete/azuolas-whisper-lt"
export HF_HOME="$HOME/wispr/models/hf"

echo "== Ąžuolo konversija =="
df -h / | tail -1
avail=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
[ "$avail" -lt 8 ] && { echo "STOP: <8 GB disko ($avail GB)"; exit 1; }

if [ -d "$OUT" ] && [ -f "$OUT/model.bin" ]; then
  echo "Jau sukonvertuota: $OUT"; exit 0
fi

echo "-- diegiu torch(CPU)+transformers konversijai (vienkartinis) --"
VIRTUAL_ENV="$VENV" uv pip install \
  "torch" --index-url https://download.pytorch.org/whl/cpu
VIRTUAL_ENV="$VENV" uv pip install "transformers<5" "ctranslate2>=4"

echo "-- konvertuoju -> $OUT (int8) --"
# large-v3 bazė: 128 mel filtrų; ct2 konverteris tai paima iš preprocessor_config.
"$VENV/bin/ct2-transformers-converter" \
  --model "$SRC_ID" \
  --output_dir "$OUT" \
  --quantization int8 \
  --copy_files tokenizer.json preprocessor_config.json \
  --low_cpu_mem_usage

echo "-- padaryta --"
du -sh "$OUT"
ls -la "$OUT"
