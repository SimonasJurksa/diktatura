#!/usr/bin/env bash
# Testų ASR (DIKTATURA_ASR_CMD): „<garsas> <išvesties .txt>" -> įrašo $FAKE_ASR_TEXT į išvestį.
#   FAKE_ASR_SLEEP — kiek sekundžių „dirbti"; FAKE_ASR_FAIL=1 — nesukurti išvesties (žlugimas);
#   FAKE_ASR_TRACE — failas, kuriame žymimas pradžios/pabaigos laikas (lygiagretumo testui).
in="$1"; out="$2"
[ -n "${FAKE_ASR_TRACE:-}" ] && echo "start $(date +%s.%N) $(basename "$in")" >> "$FAKE_ASR_TRACE"
sleep "${FAKE_ASR_SLEEP:-0}"
[ -n "${FAKE_ASR_TRACE:-}" ] && echo "end $(date +%s.%N) $(basename "$in")" >> "$FAKE_ASR_TRACE"
[ "${FAKE_ASR_FAIL:-0}" = 1 ] && exit 1
printf '%s' "${FAKE_ASR_TEXT-[0:00:01] Tu: labas rytas}" > "$out"
