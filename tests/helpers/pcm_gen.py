#!/usr/bin/env python3
"""Sintetinio garso šaltinis VOX testams (DIKTATURA_CAPTURE_CMD): rašo s16le stereo 16 kHz PCM į stdout.

    pcm_gen.py SEGMENTAS... [--speed N] [--marks FAILAS] [--hold]

SEGMENTAS = rūšis:dBFS:sekundės[:kanalai]   rūšis ∈ silence|noise|speech|tone; kanalai ∈ L|R|LR (numatyta L)
  Kitas kanalas gauna tylą (−70 dB). Pvz.: silence:-70:3 speech:-20:2 silence:-70:6
--speed N   N kartų greičiau nei realus laikas (0 = kiek tik spėja skaityti; numatyta 0)
--marks F   kiekvieno segmento pradžioje į F prirašo „<segmento nr> <100 ms gabalo nr>"
--hold      pabaigus — nebeišeiti (imituoja gyvą capture, kol bus nužudytas)
"""
import argparse
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio  # noqa: E402

KINDS = {"silence": audio.silence, "noise": audio.noise, "speech": audio.speech, "tone": audio.tone}
CHUNK = audio.SR // 10


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("segments", nargs="+")
    ap.add_argument("--speed", type=float, default=0)
    ap.add_argument("--marks")
    ap.add_argument("--hold", action="store_true")
    a = ap.parse_args()
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    out = sys.stdout.buffer
    chunk_no = 0
    t0 = time.monotonic()
    for i, spec in enumerate(a.segments):
        parts = spec.split(":")
        kind, level, sec = parts[0], float(parts[1]), float(parts[2])
        chans = parts[3] if len(parts) > 3 else "L"
        sig = KINDS[kind](sec, level) if kind != "tone" else audio.tone(sec, 1000, level)
        quiet = audio.silence(sec, -70, seed=7 + i)
        left = sig if "L" in chans else quiet
        right = sig if "R" in chans else quiet
        if a.marks:
            with open(a.marks, "a") as fh:
                fh.write(f"{i} {chunk_no}\n")
        pcm = audio.stereo_pcm(left, right)
        step = CHUNK * 4
        for off in range(0, len(pcm), step):
            out.write(pcm[off:off + step])
            chunk_no += 1
            if a.speed:
                out.flush()
                lag = t0 + chunk_no * 0.1 / a.speed - time.monotonic()
                if lag > 0:
                    time.sleep(lag)
    out.flush()
    if a.hold:
        while True:
            time.sleep(3600)
    os.close(1)


if __name__ == "__main__":
    main()
