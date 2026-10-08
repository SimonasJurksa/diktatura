#!/usr/bin/env python3
"""Diktatūra — faster-whisper: įprastas WhisperModel.transcribe vs BatchedInferencePipeline (CPU), TAS PATS garsas.

    .venv/bin/python tools/batched_bench.py <garsas> [--start 0] [--seconds 120] [--model azuolas-ct2]
                                            [--threads 4] [--batch 4 8] [--channel 0]

Modelis kraunamas vieną kartą; matuojama tik transkripcija. Spausdina laiką, RTF ir kiek tekstai sutampa (WER
tarp jų). Laukia TIKRO transkripcijos užrakto (du Ąžuolai vienu metu = OOM). Garsas ir tekstai niekur nesaugomi.
"""
import argparse
import fcntl
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from diktatura import paths  # noqa: E402
from diktatura.asr import models  # noqa: E402

SR = 16000


def decode(path, start, seconds, channel):
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start)] + (["-t", str(seconds)] if seconds else []) + \
          ["-i", str(path), "-af", f"pan=mono|c0=c{channel}", "-ar", str(SR), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def words(t):
    return re.findall(r"\w+", t.lower())


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
    return d[len(h)] / max(1, len(r))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--model", default="azuolas-ct2")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--batch", type=int, nargs="+", default=[4, 8])
    ap.add_argument("--channel", type=int, default=0)
    a = ap.parse_args()
    x = decode(a.audio, a.start, a.seconds, a.channel)
    dur = len(x) / SR
    paths.RUN_DIR.mkdir(parents=True, exist_ok=True)
    with open(paths.TRANSCRIBE_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        os.nice(10)
        t0 = time.time()
        model = models.load(a.model, "int8", a.threads)
        print(f"modelis {a.model} užkrautas per {time.time() - t0:.1f}s; garsas {dur:.1f}s; gijos {a.threads}")
        t0 = time.time()
        segs, _ = model.transcribe(x, language="lt", beam_size=5, vad_filter=True,
                                   vad_parameters=dict(min_silence_duration_ms=500))
        base = " ".join(s.text.strip() for s in segs)
        tb = time.time() - t0
        print(f"įprastas:      {tb:6.1f}s  RTF {tb / dur:.2f}  žodžių {len(words(base))}")
        from faster_whisper import BatchedInferencePipeline
        pipe = BatchedInferencePipeline(model=model)
        for b in a.batch:
            t0 = time.time()
            segs, _ = pipe.transcribe(x, language="lt", beam_size=5, batch_size=b)
            txt = " ".join(s.text.strip() for s in segs)
            t = time.time() - t0
            print(f"batched b={b:<3}  {t:6.1f}s  RTF {t / dur:.2f}  x{tb / t:.2f}  "
                  f"žodžių {len(words(txt))}  skirtumas nuo įprasto (WER) {wer(base, txt):.1%}")


if __name__ == "__main__":
    main()
