#!/usr/bin/env bash
# Diktatūra — atsisiunčia kalbėtojų atpažinimo modelius (sherpa-onnx, ~35 MB) į <duomenys>/models/diarization.
#   make models
# Ąžuolo ASR modelis — atskirai: make model-convert (tools/convert_azuolas.sh).
# Failai tikrinami pagal SHA-256 (tiekimo grandinės apsauga): pasikeitus — sustoja.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../bin/common.sh"

DIAR="$MODELS/diarization"
BASE="https://github.com/k2-fsa/sherpa-onnx/releases/download"
# Balso embedding: 3D-Speaker CAM++ zh-en „advanced" (2026-10-09; tavo balsas vs kolegos EER ~0–1 %, buvęs
# CAM++ VoxCeleb — ~13 %, matuota savininko įrašuose — docs/ARCHITECTURE.md §3). Keičiant modelį: store.EMB_MODEL.
EMB="$DIAR/embedding_campplus_zh_en.onnx"
EMB_SHA=aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2
SEG="$DIAR/sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
SEG_SHA=220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079
mkdir -p "$DIAR"

check() {  # check <failas> <sha256>
  echo "$2  $1" | sha256sum -c --quiet - || { echo "✗ SHA-256 nesutampa: $1 — trinu"; rm -f "$1"; exit 1; }
}

if [ ! -f "$EMB" ]; then
  echo "-- balso embedding modelis (3D-Speaker CAM++ zh-en advanced, 28 MB) --"
  # „recongition" — taip (su klaida) vadinasi sherpa-onnx release tag'as
  curl -fL --progress-bar -o "$EMB" \
    "$BASE/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
fi
check "$EMB" "$EMB_SHA"

if [ ! -f "$SEG" ]; then
  echo "-- segmentacijos modelis (pyannote 3.0, 6 MB) --"
  curl -fL --progress-bar "$BASE/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2" \
    | tar -xj -C "$DIAR"
fi
check "$SEG" "$SEG_SHA"
echo "✓ kalbėtojų modeliai: $DIAR"
