#!/usr/bin/env python3
"""Stereo įrašo transkripcija PO KANALĄ (L=Tu, R=Kolegos) → dialogas be aido.

Naujas įrašymas yra stereo: kairys = mic (tu), dešinys = sistemos garsas (kolegos).
Čia kiekvienas kanalas transkribuojamas atskirai ir sulyginamas pagal laiką →
  [HH:MM:SS] Tu: ...
  [HH:MM:SS] Kolegos: ...
Taip „Tu vs Kolegos" atskiriama be diarizacijos.
(Kuris konkretus kolega — vėliau per diarizaciją ant R kanalo, Plan F.)

Du kokybės žingsniai:
  1. loudnorm (EBU R128) kiekvienam kanalui — vienodas garsumas nepriklausomai nuo
     Slack/Ubuntu mic AGC (auto-adjust). NE dynaudnorm (tas pumpuoja tylą/triukšmą).
  2. Tekstinė DE-DUPLIKACIJA: tavo balsas niekada nėra R kanale, tad jei „Tu" (L)
     segmentas laike persidengia su „Kolegos" (R) ir tekstas panašus (>=0.55) —
     tai kolegų nutekėjimas į mic (headset bleed) -> išmetam iš „Tu". R = tiesa.
  (Ducking atmestas: loudnorm pagarsindavo nutekėjimą, o de-dup jį pašalina patikimiau.)

Naudojimas (Plan A venv):
    python transcribe_stereo.py <stereo.wav> [--model .../azuolas-ct2] [--threads 6]
"""
import argparse
import datetime as dt
import os
import re
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("HF_HOME", str(Path.home() / "wispr" / "models" / "hf"))


def hhmmss(sec: float) -> str:
    return str(dt.timedelta(seconds=int(sec)))


# Normalizacija: loudnorm (EBU R128) — vienodas garsumas nepriklausomai nuo Slack/Ubuntu
# AGC (auto-adjust) kaprizų; skirtingai nei dynaudnorm, NEpumpuoja tylos/triukšmo.
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"


def _ff(args: list) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def extract_channel(src: str, which: str, dst: str, workdir: str) -> None:
    """Išskiria ir išvalo vieną kalbėtojo kanalą į mono 16k.

    which="them": R kanalas (kolegos) — švarus → tik loudnorm.
    which="me":   L kanalas (tu) → loudnorm (tvarko kintantį/tylų mic lygį),
                  tada DUCKINAM pagal R (nutildom, kai kolegos kalba) → dingsta ausinių
                  nutekėjimas į mic. Normalizacija PRIEŠ ducking (kad ducking liktų paskutinis).
    """
    ch = "c1" if which == "them" else "c0"
    _ff(["-i", src, "-af", f"pan=mono|c0={ch},{LOUDNORM}",
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", dst])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--model", default=str(Path.home() / "wispr" / "models" / "azuolas-ct2"))
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--lang", default="lt")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--me", default="Tu")
    ap.add_argument("--them", default="Kolegos")
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    audio = Path(args.audio).expanduser()
    if not audio.exists():
        raise SystemExit(f"Nėra failo: {audio}")

    # Patikra: ar tikrai stereo
    chans = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=channels", "-of", "csv=p=0", str(audio)],
        text=True).strip()
    if chans != "2":
        raise SystemExit(f"Reikia STEREO įrašo (L=mic,R=monitor). Šis turi {chans} kanalą(-us). "
                         f"Naujus įrašus daryk per atnaujintą record.sh/autorecord.sh.")

    print(f"Modelis : {args.model} (threads={args.threads})")
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute,
                         cpu_threads=args.threads,
                         download_root=str(Path.home() / "wispr" / "models"))

    chan = {}  # which -> list[(start,end,text)]
    with tempfile.TemporaryDirectory() as td:
        for which, who in [("me", args.me), ("them", args.them)]:
            tmp = os.path.join(td, f"{which}.wav")
            extract_channel(str(audio), which, tmp, td)
            print(f"Transkribuoju kanalą: {who}...")
            segs, _ = model.transcribe(
                tmp, language=args.lang, beam_size=args.beam,
                vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500))
            chan[which] = [(s.start, s.end, s.text.strip()) for s in segs if s.text.strip()]

    # De-duplikacija: tavo balsas NIEKADA nėra R (kolegų) kanale. Todėl jei "me" (L)
    # segmentas laike persidengia su "them" (R) ir dauguma jo žodžių randasi tose
    # kolegų eilutėse -> tai kolegų nutekėjimas į mic -> išmetam iš "me". R = tiesa.
    # Žodžių persidengimas (ne SequenceMatcher) pagauna ir atvejį, kai kolegų segmentas
    # ILGESNIS nei nutekėjimo (tada pilnas panašumas būtų žemas). Trumpas <3 žodžių
    # "me" segmentas paliekamas (reakcijos „jo/okei").
    def wset(t):
        return {w for w in re.findall(r"\w+", t.lower()) if len(w) > 1}

    def overlaps(a0, a1, b0, b1, slack=2.0):
        return (a0 - slack) < b1 and (b0 - slack) < a1

    them = chan.get("them", [])
    dropped = 0
    rows = [(st, en, args.them, tx) for st, en, tx in them]
    for st, en, tx in chan.get("me", []):
        mw = [w for w in re.findall(r"\w+", tx.lower()) if len(w) > 1]
        near = set()
        for ts, te, tt in them:
            if overlaps(st, en, ts, te):
                near |= wset(tt)
        frac = (sum(1 for w in mw if w in near) / len(mw)) if mw else 0.0
        if len(mw) >= 3 and frac >= 0.6:
            dropped += 1
        else:
            rows.append((st, en, args.me, tx))

    rows.sort(key=lambda r: r[0])
    if dropped:
        print(f"(de-dup: pašalinta {dropped} kolegų nutekėjimo segment(ų) iš „{args.me}“)")
    out = audio.with_suffix(".dialog.txt")
    lines = [f"[{hhmmss(st)}] {who}: {txt}" for st, en, who, txt in rows]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "=" * 60)
    for ln in lines:
        print(ln)
    print("=" * 60)
    print(f"Išsaugota: {out}")


if __name__ == "__main__":
    main()
