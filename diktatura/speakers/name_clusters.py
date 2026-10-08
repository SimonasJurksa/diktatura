#!/usr/bin/env python3
"""Iš diarizacijos klasterių paruošia vardinimą.

Kiekvienam SPEAKER_XX:
  - paskaičiuoja klasterio balso embedding'ą (iš ilgiausių segmentų vidurkio),
  - ištraukia reprezentatyvų garso pavyzdį -> <duomenys>/speakers_samples/SPEAKER_XX.wav (paklausyti),
  - jei jau yra registruotų balsų (enroll.json) — pasiūlo vardą (cosine).

Naudojimas:
    python -m diktatura.speakers.name_clusters <R_mono16k.wav> <R_mono16k.diar.json> [--topk 5]

Po to paklausai speakers_samples/*.wav ir įvardini:
    python -m diktatura.speakers.enroll --wav <SPEAKER_00.wav> --name Vardas
"""
import argparse
import json
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np

from diktatura import paths
from diktatura.speakers import speakerlib as sl

def load_wav(path):
    with wave.open(path) as w:
        sr = w.getframerate()
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0, sr


def write_wav(path, samples, sr=16000):
    x = np.clip(samples, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("diar_json")
    ap.add_argument("--topk", type=int, default=5, help="kiek ilgiausių segmentų embeddingo vidurkiui")
    ap.add_argument("--match-threshold", type=float, default=0.5)
    args = ap.parse_args()

    samples, sr = load_wav(args.audio)
    segs = json.loads(Path(args.diar_json).read_text())
    by_spk = defaultdict(list)
    for s in segs:
        by_spk[s["speaker"]].append((s["start"], s["end"]))

    paths.SPEAKER_SAMPLES.mkdir(parents=True, exist_ok=True)
    store = sl.load_enroll()
    cluster_emb = {}

    print(f"Klasterių: {len(by_spk)}\n")
    rows = []
    for spk in sorted(by_spk):
        spans = sorted(by_spk[spk], key=lambda x: (x[1] - x[0]), reverse=True)
        total = sum(e - s for s, e in spans)
        # embedding: top-k ilgiausių segmentų vidurkis
        embs = []
        for st, en in spans[: args.topk]:
            seg = samples[int(st * sr): int(en * sr)]
            if len(seg) >= sr * 0.5:
                embs.append(sl.compute_embedding(seg, sr))
        if not embs:
            continue
        emb = np.mean(embs, axis=0)
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        cluster_emb[spk] = emb
        # reprezentatyvus pavyzdys: ilgiausias segmentas (iki 15s)
        st, en = spans[0]
        en = min(en, st + 15)
        sample_path = paths.SPEAKER_SAMPLES / f"SPEAKER_{spk:02d}.wav"
        write_wav(sample_path, samples[int(st * sr): int(en * sr)], sr)
        name, sim = sl.best_match(emb, store, args.match_threshold) if store else (None, 0.0)
        tag = f"-> {name} (sim {sim:.2f})" if name else (f"(artimiausias sim {sim:.2f})" if store else "")
        rows.append((spk, total, sample_path, name, sim))
        print(f"SPEAKER_{spk:02d}  kalbėjo {total:6.1f}s  pavyzdys: {sample_path.name}  {tag}")

    # išsaugom klasterių embeddingus (vardinimui vėliau)
    out = Path(args.diar_json).with_suffix(".clusters.json")
    out.write_text(json.dumps({str(spk): emb.tolist() for spk, emb in cluster_emb.items()}), encoding="utf-8")
    print(f"\nKlasterių embeddingai: {out}")
    print(f"Pavyzdžiai klausymui: {paths.SPEAKER_SAMPLES}/")


if __name__ == "__main__":
    main()
