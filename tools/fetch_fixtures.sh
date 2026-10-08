#!/usr/bin/env bash
# Diktatūra — atsisiunčia lietuviškos kalbos testų klipus (Mozilla Common Voice 22.0 lt, CC0) į tests/fixtures/cv/.
#   make fixtures
# Klipai ir tekstai — tests/fixtures/cv_lt.tsv. Kiekvienas klipas yra ištisinis baitų intervalas nesuspaustame
# tar archyve, todėl siunčiama tik ~220 KB (curl -r), ne visas 180 MB archyvas. SHA-256 tikrinamas.
# Garsas į repo NEpatenka (.gitignore + privatumo sargas).
set -euo pipefail
REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
OUT="$REPO/tests/fixtures/cv"
MANIFEST="$REPO/tests/fixtures/cv_lt.tsv"
# Nekeičiama revizija; atsarginis veidrodis su tais pačiais baitais — common_voice_17_0@8262c16b…
URLS=(
  "https://huggingface.co/datasets/fsicoli/common_voice_22_0/resolve/ae911de250fe9375d08e2daa2105b671d659d446/audio/lt/test/lt_test_0.tar"
  "https://huggingface.co/datasets/fsicoli/common_voice_17_0/resolve/8262c16bf297c87a9cd88c51997c4758ed7a8ba2/audio/lt/test/lt_test_0.tar"
)
mkdir -p "$OUT"
n=0
while IFS=$'\t' read -r id range sha _text; do
  case "$id" in ''|\#*) continue ;; esac
  f="$OUT/$id.mp3"
  if [ -f "$f" ] && echo "$sha  $f" | sha256sum -c --quiet - 2>/dev/null; then n=$((n + 1)); continue; fi
  ok=0
  for url in "${URLS[@]}"; do
    if curl -fsSL --max-filesize 1000000 -r "$range" -o "$f.part" "$url" \
       && echo "$sha  $f.part" | sha256sum -c --quiet - 2>/dev/null; then
      mv "$f.part" "$f"; ok=1; break
    fi
    rm -f "$f.part"
  done
  [ "$ok" = 1 ] || { echo "✗ nepavyko atsisiųsti (arba SHA-256 nesutampa): $id" >&2; exit 1; }
  n=$((n + 1))
done < "$MANIFEST"
echo "✓ LT testų klipai: $n ($OUT) — Mozilla Common Voice 22.0, CC0"
