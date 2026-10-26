#!/usr/bin/env python3
"""Diktatūra — pavyzdiniai (IŠGALVOTI) duomenys README nuotraukoms ir rankiniam UI bandymui.

    DIKTATURA_DATA=/tmp/demo/data DIKTATURA_CONFIG_DIR=/tmp/demo/cfg python3 tools/demo_data.py
    DIKTATURA_DATA=/tmp/demo/data DIKTATURA_CONFIG_DIR=/tmp/demo/cfg python3 -m diktatura.ui.app --page training

Sukuria transkripcijas (šiandien/vakar) su sintetinėmis bangomis (.peaks), du nežinomus balsus (pending: sintetinis
garsas), registruotus vardus ir 💡 pasiūlymą (suggestions.json — kaip po „🔄 Pertikrinti").
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
from diktatura import paths, waveform  # noqa: E402
from diktatura.speakers import store  # noqa: E402

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
        ("Tu", "Ee, nu, apkrovą pažiūrėsiu po pietų ir parašysiu kanale."),
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


def fake_peaks(path: Path, spans: list, total: float, seed: int):
    """Sintetinė stereo banga: kalbos atkarpos (s, e, kanalas) garsios su skiemenų ritmu, tarp jų — tylus fonas."""
    rnd = random.Random(seed)
    n = int(total * waveform.RATE)
    data = bytearray()
    for i in range(n):
        t = i / waveform.RATE
        for ch in (0, 1):
            on = any(s <= t < e and c == ch for s, e, c in spans)
            v = 150 + 70 * abs(math.sin(2 * math.pi * 2.2 * t + ch)) + rnd.uniform(-20, 20) if on else rnd.uniform(55, 75)
            data.append(int(max(0, min(255, v))))
    waveform.write(path, waveform.Peaks(waveform.RATE, 2, bytes(data)))


def main():
    paths.ensure_dirs()
    for k, (src, when, rows) in enumerate(SESSIONS):
        base = paths.RECORDINGS / f"{src}_{when:%Y%m%d_%H%M%S}"
        t = 3
        lines, spans = [], []
        for who, text in rows:
            lines.append(f"[{timedelta(seconds=t)}] {who}: {text}")
            dur = 4 + len(text) // 12
            spans.append((t + 0.3, t + dur - 0.6, 0 if who == "Tu" else 1))
            t += dur
        base.with_suffix(".named.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        fake_peaks(base.with_suffix(".peaks"), spans, t + 3, k)
        if k == 0:                                     # vienai sesijai — ir garsas (tyla): „▶ Groti", „🔁" aktyvūs
            with wave.open(str(base.with_suffix(".wav")), "wb") as w:
                w.setnchannels(2); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(bytes(16000 * 4 * (t + 3)))
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
    store.mark_model()
    first = SESSIONS[0]
    for i, (f0, src) in enumerate(((140, first), (210, SESSIONS[2])), 1):
        fake_voice(paths.PENDING / f"nez{i}.wav", f0, i)
        (paths.PENDING / f"nez{i}.json").write_text(json.dumps({
            "embedding": emb(), "src": f"{src[0]}_{src[1]:%Y%m%d_%H%M%S}",
            "added": (src[1] + timedelta(minutes=5)).isoformat()}), encoding="utf-8")
    (paths.PENDING / ".next").write_text("3")
    # 💡 pasiūlymas (kaip po „🔄 Pertikrinti"): nez2 panašus į Joną; dabartinis balsų parašas — neperskaičiuojamas
    store._atomic_write(store.suggestions_file(), json.dumps({
        "started": datetime.now().timestamp(), "voices": store.voices_signature(), "threshold": 0.5, "margin": 0.1,
        "suggest": 0.4,
        "checked": ["nez1", "nez2"], "items": {"nez2": {"name": "Jonas", "sim": 0.47, "alt": "Ona", "alt_sim": 0.36,
                                                         "strong": False, "basis": "sample", "lines": 1}}},
        ensure_ascii=False))
    print(f"✓ demo duomenys: {paths.DATA_DIR}")


if __name__ == "__main__":
    main()
