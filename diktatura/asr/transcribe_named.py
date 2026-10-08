#!/usr/bin/env python3
"""Diktatūra — STEREO pokalbio transkripcija su VARDAIS (pagrindinis pipeline).

L (mic) = „Tu"; R (monitor) = kolegos. Kiekvienam kolegų segmentui paskaičiuojamas
balso embedding ir priskiriamas vardas iš registro (<duomenys>/speakers/enroll.json) pagal cosine.
Nežinomas balsas -> „Kolega?nezN" (pavyzdys išsaugomas į pending; vardą priskiria Apmokymai).
Klasterizavimo inference metu NEREIKIA — tiesioginis embedding ↔ registras sutapimas.

Pipeline: loudnorm/kanalui -> VAD (be kalbos -> modelis nekraunamas; apkarpymas) -> Whisper -> laikai atgal į
originalą -> R segmentams vardai -> de-dup (Tu vs kolegos) -> dialogas.

Naudojimas:
    python -m diktatura.asr.transcribe_named <stereo.wav> [--model azuolas-ct2] [--threads 6] [--name-threshold 0.5]
"""
import argparse
import os
import subprocess
import tempfile
import time
import wave
from collections import Counter
from pathlib import Path

import numpy as np

from diktatura import debug, paths
from diktatura.asr import dialog, models
from diktatura.audio import prefilter
from diktatura.speakers import speakerlib as sl
from diktatura.speakers import store

os.environ.setdefault("HF_HOME", str(paths.HF_HOME))
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"


def _ff(args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def extract(src, ch, dst):
    _ff(["-i", src, "-af", f"pan=mono|c0=c{ch},{LOUDNORM}", "-ar", "16000", "-ac", "1",
         "-c:a", "pcm_s16le", dst])


def load_wav(path):
    with wave.open(path) as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe_plan(model, plan, args):
    """Whisper apkarpytam kanalui (VAD) -> [(start, end, tekstas)] ORIGINALAUS įrašo laiku."""
    if plan.skip:
        return []
    segs, _ = model.transcribe(plan.audio, language=args.lang, beam_size=args.beam,
                               vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500))
    out = [(plan.to_original(s.start), plan.to_original(s.end), s.text.strip()) for s in segs if s.text.strip()]
    plan.audio = None                       # atlaisvinti RAM prieš kitą kanalą
    return out


def run(argv=None, get_model=models.load) -> int:
    """Transkribuoti stereo pokalbį. get_model(vardas, compute, gijos) — modelio šaltinis (serveris paduoda įkrautą)."""
    ap = argparse.ArgumentParser(prog="diktatura.asr.transcribe_named")
    ap.add_argument("audio")
    ap.add_argument("--model", default="azuolas-ct2", help="azuolas-ct2 / medium / CT2 katalogo kelias")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--lang", default="lt")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--me", default="Tu")
    ap.add_argument("--name-threshold", type=float, default=0.5)
    ap.add_argument("--vad", choices=("on", "off", "trim"),
                    help="perrašo VAD nustatymus palyginimams: off — be VAD; on — vartai; trim — vartai + apkarpymas")
    args = ap.parse_args(argv)

    audio = Path(args.audio).expanduser()
    out = audio.with_suffix(".named.txt")
    chans = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=channels", "-of", "csv=p=0", str(audio)], text=True).strip()
    if chans != "2":
        raise SystemExit(f"Reikia STEREO (L=mic,R=monitor); yra {chans} kanalas(-ai).")
    vad = prefilter.settings()
    if args.vad:
        vad.enabled, vad.trim = args.vad != "off", args.vad == "trim" or (args.vad == "on" and vad.trim)
    t1 = time.time()

    with tempfile.TemporaryDirectory() as td:
        me_wav = os.path.join(td, "me.wav")
        them_wav = os.path.join(td, "them.wav")
        extract(str(audio), 0, me_wav)
        extract(str(audio), 1, them_wav)
        me_audio, them_audio = load_wav(me_wav), load_wav(them_wav)
    dur = len(me_audio) / 16000

    # VAD: kur kalba? (prieš kraunant ~3 GB modelį)
    me_plan = vad.plan(me_audio)
    del me_audio                            # RAM: ilgas skambutis = šimtai MB; L originalo nebereikia
    them_plan = vad.plan(them_audio)   # R originalas lieka — balso embedding'ams
    for nm, pl in (("L (Tu)", me_plan), ("R (kolegos)", them_plan)):
        print(f"VAD {nm}: kalbos {pl.speech_sec:.1f}s iš {pl.original_sec:.1f}s"
              + (" — praleidžiama" if pl.skip else f" → transkribuojama {len(pl.audio) / 16000:.1f}s"))
        debug.log("asr", f"{audio.name}: VAD {nm} kalbos {pl.speech_sec:.1f}/{pl.original_sec:.1f}s, "
                         f"atkarpų {len(pl.spans)}, {'PRALEISTA' if pl.skip else 'transkribuojama'}")
    if me_plan.skip and them_plan.skip:
        print(f"∅ VAD: kalbos nerasta (< {vad.min_speech:g} s) — modelis nekraunamas, tekstas tuščias")
        debug.log("asr", f"{audio.name}: VAD — kalbos nėra, modelis NEkrautas")
        out.write_text("", encoding="utf-8")
        return 0

    pending = sl.load_pending()
    print(f"Registruoti balsai: {store.names() or '(nėra)'}  | nežinomų laukia: {len(pending)}")
    t0 = time.time()
    model = get_model(args.model, args.compute, args.threads)
    t_load = time.time() - t0
    debug.log("asr", f"{audio.name}: modelis {args.model} užkrautas per {t_load:.1f}s (threads={args.threads})")

    print("Transkribuoju: Tu...")
    me = transcribe_plan(model, me_plan, args)
    debug.log("asr", f"{audio.name}: L (Tu) {len(me)} segm.")
    print("Transkribuoju: kolegos...")
    them = transcribe_plan(model, them_plan, args)
    debug.log("asr", f"{audio.name}: R (kolegos) {len(them)} segm.")

    # Vardai kolegų segmentams per balso embedding (registruoti -> vardas, nauji nežinomi -> pending)
    print("Priskiriu vardus (balso atpažinimas)...")
    named, new_pending = sl.label_segments(
        them, them_audio, store=sl.load_enroll(), pending=pending, ignored=sl.load_ignored(),
        threshold=args.name_threshold, embed=sl.compute_embedding, add_pending_fn=sl.add_pending,
        src=audio.stem)
    if new_pending:
        print(f"🔎 Nauji nežinomi balsai: {new_pending} — pavyzdžiai {paths.PENDING} (vardai: Apmokymai)")

    proc = time.time() - t1 - t_load        # RTF: be modelio krovimo (kaip transcribe.py)
    rtf = proc / dur if dur else 0
    print(f"Garsas {dur:.1f}s, apdorota {proc:.1f}s — RTF {rtf:.2f} (+ modelio krovimas {t_load:.1f}s)")
    debug.log("asr", f"{audio.name}: garsas {dur:.1f}s, apdorota {proc:.1f}s, RTF {rtf:.2f}, krovimas {t_load:.1f}s")
    rows, dropped = dialog.dedup(me, named, me_label=args.me)
    rows = store.resolve_labels(rows)   # jei transkripcijos metu nežinomam jau priskirtas vardas
    out.write_text(dialog.format_rows(rows), encoding="utf-8")
    if dropped:
        print(f"(de-dup: pašalinta {dropped} nutekėjimo segment(ų) iš „{args.me}“)")
    cnt = Counter(who for _, _, who, _ in rows)
    print("Kalbėjo:", ", ".join(f"{w}×{n}" for w, n in cnt.most_common()))
    print(f"Išsaugota: {out}")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
