#!/usr/bin/env bash
# Diktatūra — paleidimas iš programų meniu / doko (desktop/diktatura.desktop.in):
# grąžina status bar ikoną (jei buvo uždaryta „Išeiti") ir atidaro langą (jau atidarytą — tik iškelia).
#   bin/diktatura-open.sh [text|training|settings]
# Įrašymo režimo nekeičia (jis — Nustatymuose). Testams: DIKTATURA_SYSTEMCTL, DIKTATURA_UI_PYTHON.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
${DIKTATURA_SYSTEMCTL:-systemctl} --user start diktatura-tray >/dev/null 2>&1 || true
cd "$REPO" && PYTHONPATH="$REPO" exec ${DIKTATURA_UI_PYTHON:-/usr/bin/python3} -m diktatura.ui.app --page "${1:-text}"
