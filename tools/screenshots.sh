#!/usr/bin/env bash
# Diktatūra — README nuotraukos (docs/img/{text,training,settings}.png) iš IŠGALVOTŲ demo duomenų.
#   bash tools/screenshots.sh
# Langas piešiamas per broadway (atmintyje) — tavo ekrane nieko neatsiranda; tikri duomenys neliečiami
# (laikinas DIKTATURA_* katalogas + tools/demo_data.py). Reikia: broadwayd (libgtk-3-bin).
set -euo pipefail
REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
T="$(mktemp -d)"
cleanup(){ [ -n "${BW:-}" ] && kill "$BW" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
export DIKTATURA_DATA="$T/data" DIKTATURA_CONFIG_DIR="$T/cfg" DIKTATURA_STATE="$T/state" DIKTATURA_RUN="$T/run"
export DIKTATURA_APP_ID="lt.diktatura.Screenshots$$" PYTHONPATH="$REPO"
# netikras systemctl: „veikia VOX" (tikri servisai neliečiami)
export DIKTATURA_SYSTEMCTL="$REPO/tests/helpers/fakebin/systemctl-fake" FAKE_SYSTEMD="$T/systemd"
mkdir -p "$FAKE_SYSTEMD" && touch "$FAKE_SYSTEMD/diktatura-vox.service.active"
python3 "$REPO/tools/demo_data.py"
for n in $(seq 50 79); do (echo > /dev/tcp/127.0.0.1/$((8080 + n))) 2>/dev/null || { D=$n; break; }; done
broadwayd ":$D" >/dev/null 2>&1 & BW=$!
sleep 0.7
for page in text training settings; do
  GDK_BACKEND=broadway BROADWAY_DISPLAY=":$D" timeout 30 python3 -m diktatura.ui.app --page "$page" \
    --shot "$REPO/docs/img/$page.png"
  echo "✓ docs/img/$page.png"
done
