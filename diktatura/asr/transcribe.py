#!/usr/bin/env python3
"""Diktatūra — MONO įrašo transkripcija per faster-whisper (be kalbėtojų).

Naudojimas:
    python -m diktatura.asr.transcribe <audio.wav> [--model azuolas-ct2] [--threads 6] [--lang lt]

Modelis (žr. paths.model_path):
  - "azuolas-ct2" -> lokalus Ąžuolo CT2 katalogas (<duomenys>/models/azuolas-ct2, tools/convert_azuolas.sh).
  - "medium" / "large-v3" -> standartinis Whisper (auto-parsisiunčia CT2 formatu, be torch).
  - absoliutus kelias -> lokalus CT2 katalogas.

Prieš modelį — VAD (diktatura.audio.prefilter): be kalbos -> tuščias .txt, modelis nekraunamas; kitaip garsas
apkarpomas iki kalbos, o .srt laikai perskaičiuojami į originalą.
Išvestis: šalia audio sukuria .txt ir .srt. Spausdina RTF (trukmė/garsas).
Modelių cache: <duomenys>/models (paths.MODELS).
"""
import argparse
import os
import time
from pathlib import Path

from diktatura import debug, paths
from diktatura.asr import models
from diktatura.audio import prefilter

os.environ.setdefault("HF_HOME", str(paths.HF_HOME))


def fmt_ts(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    ms = int((s - int(s)) * 1000)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"


def run(argv=None, get_model=models.load) -> int:
    """Transkribuoti vieną failą. get_model(vardas, compute, gijos) — modelio šaltinis (serveris paduoda įkrautą)."""
    ap = argparse.ArgumentParser(prog="diktatura.asr.transcribe")
    ap.add_argument("audio")
    ap.add_argument("--model", default="azuolas-ct2",
                    help="azuolas-ct2 / medium / large-v3 arba lokalus CT2 katalogo kelias")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--lang", default="lt")
    ap.add_argument("--compute", default="int8", help="int8 / int8_float32 / float32")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--vad", choices=("on", "off", "trim"),
                    help="perrašo VAD nustatymus palyginimams: off — be VAD; on — vartai; trim — vartai + apkarpymas")
    args = ap.parse_args(argv)

    from faster_whisper.audio import decode_audio

    audio = Path(args.audio).expanduser()
    if not audio.exists():
        raise SystemExit(f"Nėra failo: {audio}")
    txt_path = audio.with_suffix(".txt")
    srt_path = audio.with_suffix(".srt")

    # VAD: kur kalba? (prieš kraunant modelį; be kalbos — modelis nekraunamas)
    vad = prefilter.settings()
    if args.vad:
        vad.enabled, vad.trim = args.vad != "off", args.vad == "trim" or (args.vad == "on" and vad.trim)
    tv = time.time()
    samples = decode_audio(str(audio), sampling_rate=16000)
    plan = vad.plan(samples)
    dur = len(samples) / 16000
    del samples
    t_vad = time.time() - tv
    print(f"VAD: kalbos {plan.speech_sec:.1f}s iš {dur:.1f}s" + (" — praleidžiama" if plan.skip else ""))
    debug.log("asr", f"{audio.name}: VAD kalbos {plan.speech_sec:.1f}/{dur:.1f}s, atkarpų {len(plan.spans)}")
    if plan.skip:
        print(f"∅ VAD: kalbos nerasta (< {vad.min_speech:g} s) — modelis nekraunamas, tekstas tuščias")
        debug.log("asr", f"{audio.name}: VAD — kalbos nėra, modelis NEkrautas")
        txt_path.write_text("", encoding="utf-8")
        srt_path.write_text("", encoding="utf-8")
        return 0

    print(f"Modelis   : {args.model}  (compute={args.compute}, threads={args.threads})")
    print(f"Garsas    : {audio}")
    t0 = time.time()
    model = get_model(args.model, args.compute, args.threads)
    t_load = time.time() - t0
    print(f"Modelis užkrautas per {t_load:.1f}s. Transkribuoju...")
    debug.log("asr", f"{audio.name}: modelis {args.model} užkrautas per {t_load:.1f}s (threads={args.threads})")
    t1 = time.time()

    segments, info = model.transcribe(
        plan.audio,
        language=args.lang,
        beam_size=args.beam,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    lines, srt = [], []
    for i, seg in enumerate(segments, 1):
        text = seg.text.strip()
        start, end = plan.to_original(seg.start), plan.to_original(seg.end)
        lines.append(text)
        srt.append(f"{i}\n{fmt_ts(start)} --> {fmt_ts(end)}\n{text}\n")
        print(f"[{start:7.1f}–{end:7.1f}] {text}")

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    srt_path.write_text("\n".join(srt) + "\n", encoding="utf-8")

    proc = time.time() - t1 + t_vad          # RTF: VAD + transkripcija (be modelio krovimo, kaip anksčiau)
    rtf = proc / dur if dur else 0
    print("\n" + "=" * 60)
    print(f"Garso trukmė : {dur:.1f}s")
    print(f"Transkripcija: {proc:.1f}s  (VAD {t_vad:.1f}s; Whisper gavo {info.duration:.1f}s; modelio krovimas +{t_load:.1f}s)")
    print(f"RTF          : {rtf:.2f}x  ({'greičiau' if rtf < 1 else 'LĖČIAU'} nei realus laikas)")
    debug.log("asr", f"{audio.name}: garsas {dur:.1f}s, transkripcija {proc:.1f}s, RTF {rtf:.2f}, segmentų {len(lines)}")
    print(f"Išvestis     : {txt_path.name} , {srt_path.name}")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
