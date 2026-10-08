#!/usr/bin/env python3
"""Stereo pokalbio transkripcija su VARDAIS (galutinis Plan A+F pipeline).

L (mic) = „Tu"; R (monitor) = kolegos. Kiekvienam kolegų segmentui paskaičiuojamas
balso embedding ir priskiriamas vardas iš registro (speakers/enroll.json) pagal cosine.
Nežinomas balsas -> „Kolega?". Klasterizavimo inference metu NEREIKIA — tiesioginis
embedding ↔ registras sutapimas (over-clustering problema išnyksta).

Pipeline: loudnorm/kanalui -> Whisper -> R segmentams vardai -> de-dup (Tu vs kolegos) -> dialogas.

Naudojimas (Plan A venv):
    python transcribe_named.py <stereo.wav> [--model .../azuolas-ct2] [--threads 6] [--name-threshold 0.5]
"""
import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path.home() / "wispr" / "plans" / "F"))
import speakerlib as sl  # noqa: E402

os.environ.setdefault("HF_HOME", str(Path.home() / "wispr" / "models" / "hf"))
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"


def hhmmss(sec):
    return str(dt.timedelta(seconds=int(sec)))


def _ff(args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def extract(src, ch, dst):
    _ff(["-i", src, "-af", f"pan=mono|c0=c{ch},{LOUDNORM}", "-ar", "16000", "-ac", "1",
         "-c:a", "pcm_s16le", dst])


def load_wav(path):
    with wave.open(path) as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def wset(t):
    return {w for w in re.findall(r"\w+", t.lower()) if len(w) > 1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--model", default=str(Path.home() / "wispr" / "models" / "azuolas-ct2"))
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--lang", default="lt")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--me", default="Tu")
    ap.add_argument("--name-threshold", type=float, default=0.5)
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    audio = Path(args.audio).expanduser()
    chans = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=channels", "-of", "csv=p=0", str(audio)], text=True).strip()
    if chans != "2":
        raise SystemExit(f"Reikia STEREO (L=mic,R=monitor); yra {chans} kanalas(-ai).")

    store = sl.load_enroll()
    pending = sl.load_pending()
    print(f"Registruoti balsai: {sorted(store) or '(nėra)'}  | nežinomų laukia: {len(pending)}")
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute,
                         cpu_threads=args.threads, download_root=str(Path.home() / "wispr" / "models"))

    with tempfile.TemporaryDirectory() as td:
        me_wav = os.path.join(td, "me.wav")
        them_wav = os.path.join(td, "them.wav")
        extract(str(audio), 0, me_wav)
        extract(str(audio), 1, them_wav)

        print("Transkribuoju: Tu...")
        me_segs, _ = model.transcribe(me_wav, language=args.lang, beam_size=args.beam,
                                      vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500))
        me = [(s.start, s.end, s.text.strip()) for s in me_segs if s.text.strip()]

        print("Transkribuoju: kolegos...")
        them_segs, _ = model.transcribe(them_wav, language=args.lang, beam_size=args.beam,
                                        vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500))
        them = [(s.start, s.end, s.text.strip()) for s in them_segs if s.text.strip()]

        # Vardai kolegų segmentams per embedding
        print("Priskiriu vardus (balso atpažinimas)...")
        them_samples = load_wav(them_wav)
        named = []
        new_pending = 0
        for st, en, tx in them:
            who = "Kolega?"
            if (en - st) >= 0.8:
                seg = them_samples[int(st * 16000):int(en * 16000)]
                if len(seg) >= 16000 * 0.5:
                    emb = sl.compute_embedding(seg)
                    name, _ = sl.best_match(emb, store, args.name_threshold) if store else (None, 0)
                    if name:
                        who = name
                    else:
                        # nežinomas: ar jau matėm (pending)? jei ne — IŠSAUGOM pavyzdį vėlesniam priskyrimui
                        pid, _ = sl.best_match(emb, pending, args.name_threshold) if pending else (None, 0)
                        if not pid:
                            pid = sl.add_pending(emb, seg, 16000, audio.stem)
                            pending[pid] = [emb]
                            new_pending += 1
                        who = f"Kolega?{pid}"
            named.append((st, en, who, tx))
        if new_pending:
            print(f"🔎 Nauji nežinomi balsai: {new_pending} — pavyzdžiai speakers/pending/ (priskirk: make name-unknown)")

    # De-dup: „Tu" segmentas, kurio dauguma žodžių yra laike persidengiančiose kolegų
    # eilutėse -> nutekėjimas -> išmetam.
    def overlaps(a0, a1, b0, b1, slack=2.0):
        return (a0 - slack) < b1 and (b0 - slack) < a1

    rows = [(st, en, who, tx) for st, en, who, tx in named]
    dropped = 0
    for st, en, tx in me:
        mw = [w for w in re.findall(r"\w+", tx.lower()) if len(w) > 1]
        near = set()
        for ts, te, _, tt in named:
            if overlaps(st, en, ts, te):
                near |= wset(tt)
        frac = (sum(1 for w in mw if w in near) / len(mw)) if mw else 0.0
        if len(mw) >= 3 and frac >= 0.6:
            dropped += 1
        else:
            rows.append((st, en, args.me, tx))

    rows.sort(key=lambda r: r[0])
    out = audio.with_suffix(".named.txt")
    lines = [f"[{hhmmss(st)}] {who}: {tx}" for st, en, who, tx in rows]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if dropped:
        print(f"(de-dup: pašalinta {dropped} nutekėjimo segment(ų) iš „{args.me}“)")
    from collections import Counter
    cnt = Counter(who for _, _, who, _ in rows)
    print("Kalbėjo:", ", ".join(f"{w}×{n}" for w, n in cnt.most_common()))
    print(f"Išsaugota: {out}")


if __name__ == "__main__":
    main()
