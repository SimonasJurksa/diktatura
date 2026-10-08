#!/usr/bin/env python3
"""Diktatūra — pavyzdiniai (IŠGALVOTI) duomenys README nuotraukoms ir rankiniam UI bandymui.

    DIKTATURA_DATA=/tmp/demo/data DIKTATURA_CONFIG_DIR=/tmp/demo/cfg python3 tools/demo_data.py
    DIKTATURA_DATA=/tmp/demo/data DIKTATURA_CONFIG_DIR=/tmp/demo/cfg python3 -m diktatura.ui.app --page training

Sukuria transkripcijas (šiandien/vakar), du nežinomus balsus (pending: sintetinis garsas) ir registruotus vardus.
Saugiklis: atsisako rašyti, jei DIKTATURA_DATA nenurodytas (kad neužterštų tikrų duomenų).
"""
import json
import math
import os
import random
import struct
import sys
import wave
from datetime import datetime, timedelta
from pathlib import Path

if not os.environ.get("DIKTATURA_DATA"):
    sys.exit("Nurodyk DIKTATURA_DATA=<laikinas katalogas> — tikrų duomenų neliečiam.")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from diktatura import paths  # noqa: E402

TODAY = datetime.now().replace(microsecond=0)
SESSIONS = [
    ("slack", TODAY - timedelta(days=1, hours=2), [
        ("Ona", "Labas rytas, gal pradedam? Šiandien trys temos."),
        ("Tu", "Labas. Pirmiausia — naujos versijos diegimas."),
        ("Jonas", "Diegimą galim daryti ketvirtadienį po pietų, testai jau žali."),
        ("Kolega?nez1", "O kaip su duomenų bazės migracija?"),
        ("Tu", "Migraciją paleisim atskirai, pirmadienį ryte."),
        ("Ona", "Gerai, užsirašau: ketvirtadienį diegimas, pirmadienį migracija."),
    ]),
    ("vox", TODAY - timedelta(hours=3), [
        ("Tu", "Priminimas sau: paruošti ataskaitą iki penktadienio ir išsiųsti Onai."),
    ]),
    ("slack", TODAY - timedelta(hours=1), [
        ("Jonas", "Ar visi girdi? Pradedam trumpą susitikimą."),
        ("Kolega?nez2", "Girdžiu. Turiu klausimą dėl serverio apkrovos."),
        ("Tu", "Apkrovą pažiūrėsiu po pietų ir parašysiu kanale."),
        ("Kolega?nez1", "Ačiū, tada laukiam žinutės."),
        ("Jonas", "Puiku, susitikimas baigtas."),
    ]),
]


def fake_voice(path: Path, f0: float, seed: int, sec: float = 4.0):
    rnd = random.Random(seed)
    sr = 16000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        frames = bytearray()
        for i in range(int(sr * sec)):
            t = i / sr
            env = 0.5 + 0.5 * math.sin(2 * math.pi * 3 * t) ** 2
            v = sum(math.sin(2 * math.pi * f0 * k * t) / k for k in (1, 2, 3)) * env * 0.15 + rnd.gauss(0, 0.01)
            frames += struct.pack("<h", int(max(-1, min(1, v)) * 32767))
        w.writeframes(bytes(frames))


def main():
    paths.ensure_dirs()
    for src, when, rows in SESSIONS:
        base = paths.RECORDINGS / f"{src}_{when:%Y%m%d_%H%M%S}"
        t = 3
        lines = []
        for who, text in rows:
            lines.append(f"[{timedelta(seconds=t)}] {who}: {text}")
            t += 4 + len(text) // 12
        base.with_suffix(".named.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # žymės: ⭐ svarbu ir ☐ užduotis pirmoje sesijoje (rodo README nuotraukoje)
    src0, when0, rows0 = SESSIONS[0]
    name0 = f"{src0}_{when0:%Y%m%d_%H%M%S}.named.txt"
    (paths.DATA_DIR / "annotations.json").write_text(json.dumps({
        f"{name0}#2": {"tag": "task", "done": False, "text": rows0[2][1], "added": TODAY.isoformat()},
        f"{name0}#5": {"tag": "star", "done": False, "text": rows0[5][1], "added": TODAY.isoformat()},
    }, ensure_ascii=False), encoding="utf-8")
    rnd = random.Random(1)
    emb = lambda: [rnd.gauss(0, 1) for _ in range(192)]  # noqa: E731
    paths.ENROLL.write_text(json.dumps({"Ona": [emb(), emb()], "Jonas": [emb()]}), encoding="utf-8")
    first = SESSIONS[0]
    for i, (f0, src) in enumerate(((140, first), (210, SESSIONS[2])), 1):
        fake_voice(paths.PENDING / f"nez{i}.wav", f0, i)
        (paths.PENDING / f"nez{i}.json").write_text(json.dumps({
            "embedding": emb(), "src": f"{src[0]}_{src[1]:%Y%m%d_%H%M%S}",
            "added": (src[1] + timedelta(minutes=5)).isoformat()}), encoding="utf-8")
    (paths.PENDING / ".next").write_text("3")
    print(f"✓ demo duomenys: {paths.DATA_DIR}")


if __name__ == "__main__":
    main()
