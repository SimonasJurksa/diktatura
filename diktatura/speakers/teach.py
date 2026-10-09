#!/usr/bin/env python3
"""Diktatūra — mokymasis iš pataisymo: „šią eilutę iš tikro sakė X" -> X balso pavyzdys (.venv).

Teksto lange pataisius kalbėtoją (pvz. „Jonas" -> „Tu", kai kalbėjai per telefoną), UI paleidžia:
    python -m diktatura.speakers.teach <transkripcija.txt> <eilutės nr.> <vardas | Tu>
Iš įrašo (wav arba mp3 archyvo) paimama tos eilutės atkarpa (iki kitos eilutės, ≤ 20 s):
  - stereo: dešinys (kolegų / sistemos) kanalas, jei jame yra kalbos, kitaip kairys (mikrofonas);
  - tik kalbos dalys (Silero VAD) -> balso embedding -> registruojamas vardui (enroll.json) arba tau (owner.json).
Išėjimo kodai: 0 — išmokta; 3 — per mažai kalbos (eilutė tik pervadinta); 2 — nėra garso / eilutės.
"""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

from diktatura import debug, sessions
from diktatura.audio import prefilter
from diktatura.speakers import speakerlib as sl
from diktatura.speakers import store

SR = 16000
MIN_SPEECH_SEC = 1.5     # trumpesnės kalbos embedding nepatikimas — geriau nemokyti


def n_channels(audio) -> int:
    return int(subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
         "-of", "csv=p=0", str(audio)], text=True).strip() or 1)


def decode(audio, start: float, dur: float, ch: int) -> np.ndarray:
    """Vieno kanalo atkarpa float32 16 kHz."""
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(audio),
         "-af", f"pan=mono|c0=c{ch}", "-ar", str(SR), "-ac", "1", "-f", "s16le", "-"])
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def channels(audio, start: float, dur: float) -> list:
    """Atkarpos kanalai [L, R] (arba [mono]) float32 16 kHz."""
    return [decode(audio, start, dur, ch) for ch in range(min(n_channels(audio), 2))]


def speech_only(x: np.ndarray):
    """-> (tik kalbos garsas, kalbos sekundės)."""
    spans = prefilter.speech_spans(x, pad_sec=0.1)
    if not spans:
        return x[:0], 0.0
    audio, _ = prefilter.trim(x, spans)
    return audio, len(audio) / SR


def pick(chans: list):
    """Kurį kanalą imti: R (kolegų kanalas, kuriame klydo vardai), jei jame pakanka kalbos; kitaip L.
    -> (kalbos garsas, kalbos sekundės, "R" | "L" | "mono")."""
    order = [(chans[1], "R"), (chans[0], "L")] if len(chans) == 2 else [(chans[0], "mono")]
    best = (order[0][0][:0], 0.0, "-")
    for x, name in order:
        a, sec = speech_only(x)
        if sec >= MIN_SPEECH_SEC:
            return a, sec, name
        if sec > best[1]:
            best = (a, sec, name)
    return best


def teach(path, idx: int, name: str, embed=None) -> dict:
    """Išmokti balsą iš transkripcijos eilutės. -> {"ok", "who", "speech_sec", "channel", "count"|"error"}."""
    span = store.line_span(path, idx)
    audio = sessions.audio_for(path)
    if span is None or audio is None:
        return {"ok": False, "error": "nėra eilutės laiko arba garso (įrašas ištrintas?)"}
    me = store.is_me(name)
    who = store.ME if me else store.clean_name(name)
    if not store.compatible():
        return {"ok": False, "error": f"balsai paskaičiuoti senu modeliu ({store.model_id()}) — make speakers-migrate"}
    x, sec, ch = pick(channels(audio, span[0], span[1] - span[0]))
    res = {"who": who, "speech_sec": round(sec, 1), "channel": ch}
    if sec < MIN_SPEECH_SEC:
        return {**res, "ok": False, "error": f"per mažai kalbos ({sec:.1f} s < {MIN_SPEECH_SEC:g} s)"}
    emb = (embed or sl.compute_embedding)(x)
    store.claim_model()
    src = f"{sessions.base_name(Path(path).name)}@{int(span[0])}"
    count = store.add_owner(emb, src) if me else store.add_embedding(who, emb)
    debug.log("speakers", f"pataisymas: {src} -> {who} ({res['channel']}, kalbos {sec:.1f}s), pavyzdžių {count}")
    return {**res, "ok": True, "count": count}


def main() -> None:
    ap = argparse.ArgumentParser(prog="diktatura.speakers.teach")
    ap.add_argument("transcript")
    ap.add_argument("idx", type=int)
    ap.add_argument("name")
    a = ap.parse_args()
    r = teach(Path(a.transcript), a.idx, a.name)
    print(json.dumps(r, ensure_ascii=False))
    raise SystemExit(0 if r["ok"] else (3 if "speech_sec" in r else 2))


if __name__ == "__main__":
    main()
