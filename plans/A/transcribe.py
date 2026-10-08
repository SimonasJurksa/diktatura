#!/usr/bin/env python3
"""Plan A — batch transkripcija per faster-whisper.

Naudojimas:
    python transcribe.py <audio.wav> [--model large-v3] [--threads 6] [--lang lt]

Modelis:
  - "large-v3"  -> standartinis Whisper large-v3 (auto-parsisiunčia CT2 formatu, be torch).
  - kelias      -> lokalus CT2 katalogas (pvz. Ąžuolas po konversijos: ~/wispr/models/azuolas-ct2).

Išvestis: šalia audio sukuria .txt ir .srt. Spausdina RTF (trukmė/garsas) ir resursus.
Modelių cache: ~/wispr/models (bendras visiems planams).
"""
import argparse
import os
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", str(Path.home() / "wispr" / "models" / "hf"))


def fmt_ts(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    ms = int((s - int(s)) * 1000)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--model", default="large-v3",
                    help="large-v3 arba lokalus CT2 katalogo kelias")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--lang", default="lt")
    ap.add_argument("--compute", default="int8", help="int8 / int8_float32 / float32")
    ap.add_argument("--beam", type=int, default=5)
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    audio = Path(args.audio).expanduser()
    if not audio.exists():
        raise SystemExit(f"Nėra failo: {audio}")

    models_root = Path.home() / "wispr" / "models"
    models_root.mkdir(parents=True, exist_ok=True)

    print(f"Modelis   : {args.model}  (compute={args.compute}, threads={args.threads})")
    print(f"Garsas    : {audio}")
    t0 = time.time()
    model = WhisperModel(
        args.model,
        device="cpu",
        compute_type=args.compute,
        cpu_threads=args.threads,
        download_root=str(models_root),
    )
    t_load = time.time() - t0
    print(f"Modelis užkrautas per {t_load:.1f}s. Transkribuoju...")

    t1 = time.time()
    segments, info = model.transcribe(
        str(audio),
        language=args.lang,
        beam_size=args.beam,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    txt_path = audio.with_suffix(".txt")
    srt_path = audio.with_suffix(".srt")
    lines, srt = [], []
    for i, seg in enumerate(segments, 1):
        text = seg.text.strip()
        lines.append(text)
        srt.append(f"{i}\n{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}\n{text}\n")
        print(f"[{seg.start:7.1f}–{seg.end:7.1f}] {text}")

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    srt_path.write_text("\n".join(srt) + "\n", encoding="utf-8")

    dur = info.duration
    proc = time.time() - t1
    rtf = proc / dur if dur else 0
    print("\n" + "=" * 60)
    print(f"Garso trukmė : {dur:.1f}s")
    print(f"Transkripcija: {proc:.1f}s  (modelio krovimas +{t_load:.1f}s)")
    print(f"RTF          : {rtf:.2f}x  ({'greičiau' if rtf < 1 else 'LĖČIAU'} nei realus laikas)")
    print(f"Išvestis     : {txt_path.name} , {srt_path.name}")


if __name__ == "__main__":
    main()
