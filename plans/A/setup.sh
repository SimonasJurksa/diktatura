#!/usr/bin/env bash
# Plan A — Ąžuolas (large-v3) per faster-whisper, BATCH režimu.
# Izoliuotas venv. Paleisti iš bet kur: bash ~/wispr/plans/A/setup.sh
set -euo pipefail

PLAN_DIR="$HOME/wispr/plans/A"
VENV="$PLAN_DIR/.venv"

echo "== Plan A setup =="
echo "-- disko/RAM patikra --"
df -h / | tail -1
free -h | awk 'NR==1||/Mem/'

# Saugiklis: nebediegti, jei disko < 8 GB
avail=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
if [ "$avail" -lt 8 ]; then
  echo "STOP: mažiau nei 8 GB laisvo disko ($avail GB). Pirma valyk." >&2
  exit 1
fi

echo "-- kuriu venv per uv: $VENV --"
# uv nereikalauja python3-venv/ensurepip (sistemoje jo nėra).
uv venv "$VENV" --python 3.10 --clear

# Runtime: faster-whisper (CTranslate2, int8) — be torch.
VIRTUAL_ENV="$VENV" uv pip install faster-whisper

echo "-- patikra: faster-whisper importas --"
"$VENV/bin/python" -c "import faster_whisper, ctranslate2; print('faster-whisper', faster_whisper.__version__, '| ctranslate2', ctranslate2.__version__)"

echo "== Setup OK =="
