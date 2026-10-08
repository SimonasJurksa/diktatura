#!/usr/bin/env python3
"""Gyva (beveik realaus laiko) transkripcija + švaraus WAV archyvo įrašymas.

Vienas ffmpeg: mic + sistemos monitor -> (1) WAV archyvas, (2) srautas į šį skriptą.
Skriptas kaupia ~CHUNK s gabalėlius ir transkribuoja faster-whisper'iu, spausdina gyvai.

Naudojimas (per Plan A venv):
    ~/wispr/plans/A/.venv/bin/python ~/wispr/scripts/live.py \
        [--model small] [--chunk 7] [--threads 6] [--lang lt]

Stop: Ctrl+C (ffmpeg užbaigia WAV, archyvas lieka tvarkingas).
Modelis realiam laikui: small (snappy) arba medium (lėtesnis, geresnis).
large-v3 realiu laiku NESPĖS ant šios CPU — jį naudok batch'ui (transcribe.py).
"""
import argparse
import datetime as dt
import os
import signal
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("HF_HOME", str(Path.home() / "wispr" / "models" / "hf"))

SR = 16000
BYTES_PER_SEC = SR * 2  # s16le mono


def detect_devices():
    mic = subprocess.check_output(["pactl", "get-default-source"], text=True).strip()
    sink = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
    return mic, f"{sink}.monitor"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="small",
                    help="small / medium / large-v3 / lokalus CT2 kelias (large-v3 realiu laiku nespės)")
    ap.add_argument("--chunk", type=float, default=7.0, help="gabalėlio ilgis sekundėmis")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--lang", default="lt")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--name", default="live")
    args = ap.parse_args()

    import numpy as np
    from faster_whisper import WhisperModel

    rec_dir = Path.home() / "wispr" / "recordings"
    rec_dir.mkdir(parents=True, exist_ok=True)
    archive = rec_dir / f"{args.name}_{dt.datetime.now():%Y%m%d_%H%M%S}.wav"

    mic, mon = detect_devices()
    print(f"Mic     : {mic}")
    print(f"Monitor : {mon}")
    print(f"Archyvas: {archive}")
    print(f"Modelis : {args.model} (chunk {args.chunk}s, threads {args.threads}) — kraunu...")

    models_root = Path.home() / "wispr" / "models"
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute,
                         cpu_threads=args.threads, download_root=str(models_root))
    print("Modelis užkrautas. Kalbėk — tekstas pasirodys gyvai (Ctrl+C sustabdyti).\n")

    # Vienas ffmpeg: archyvas + srautas į stdout (asplit)
    filt = ("[0:a]volume=1.5[m];[1:a]volume=1.5[s];"
            "[m][s]amix=inputs=2:duration=longest,asplit=2[a1][a2]")
    ff = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "pulse", "-i", mic,
         "-f", "pulse", "-i", mon,
         "-filter_complex", filt,
         "-map", "[a1]", "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(archive),
         "-map", "[a2]", "-ar", str(SR), "-ac", "1", "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    def stop(*_):
        if ff.poll() is None:
            ff.send_signal(signal.SIGINT)
        try:
            ff.wait(timeout=5)
        except Exception:
            ff.kill()
        print(f"\n🛑 Sustabdyta. Archyvas: {archive}")
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)

    chunk_bytes = int(args.chunk * BYTES_PER_SEC)
    t_abs = 0.0
    try:
        while True:
            buf = ff.stdout.read(chunk_bytes)
            if not buf:
                break
            audio = np.frombuffer(buf, dtype=np.int16).astype("float32") / 32768.0
            segments, _ = model.transcribe(
                audio, language=args.lang, beam_size=1,
                condition_on_previous_text=False,
                vad_filter=True, vad_parameters=dict(min_silence_duration_ms=300),
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            if text:
                stamp = str(dt.timedelta(seconds=int(t_abs)))
                print(f"[{stamp}] {text}", flush=True)
            t_abs += args.chunk
    finally:
        stop()


if __name__ == "__main__":
    main()
