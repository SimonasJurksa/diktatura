#!/usr/bin/env python3
"""Perklasterizuoja diarizacijos segmentus (švelniau) iš per-segmento embedding'ų.

sherpa-onnx FastClustering su mažu threshold per smarkiai suskaido. Čia:
  1) kiekvienam diarizacijos segmentui paskaičiuojam balso embedding'ą,
  2) agglomerative (cosine, average-linkage) su distance_threshold -> ~realus kalbėtojų skaičius,
  3) išsaugom perklasterizuotus segmentus (.reclust.json) + klasterių embeddingus (.clusters.json)
     + reprezentatyvius pavyzdžius speakers_samples/.

Naudojimas:
    python recluster.py <R_mono16k.wav> <diar.json> [--distance 0.5] [--min-dur 1.0]
--distance: didesnis = mažiau klasterių. Pasirink, kad gautum ~6-8 kalbėtojus.
"""
import argparse
import json
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.cluster import AgglomerativeClustering

import speakerlib as sl

SAMPLES_DIR = Path.home() / "wispr" / "speakers_samples"


def load_wav(path):
    with wave.open(path) as w:
        sr = w.getframerate(); data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0, sr


def write_wav(path, x, sr=16000):
    x = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("diar_json")
    ap.add_argument("--distance", type=float, default=0.5, help="cosine atstumo slenkstis (didesnis=mažiau klasterių)")
    ap.add_argument("--min-dur", type=float, default=1.0, help="ignoruoti trumpesnius segmentus embeddingui")
    ap.add_argument("--sweep", action="store_true", help="tik parodyti klasterių sk. keliems slenksčiams")
    args = ap.parse_args()

    samples, sr = load_wav(args.audio)
    segs = json.loads(Path(args.diar_json).read_text())

    # embedding kiekvienam (pakankamai ilgam) segmentui
    embs, idx = [], []
    for i, s in enumerate(segs):
        if s["end"] - s["start"] < args.min_dur:
            continue
        seg = samples[int(s["start"] * sr): int(s["end"] * sr)]
        if len(seg) >= sr * 0.5:
            embs.append(sl.compute_embedding(seg, sr)); idx.append(i)
    X = np.vstack(embs)
    print(f"Segmentų su embedding'ais: {len(X)} (iš {len(segs)})")

    if args.sweep:
        for d in [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            lab = AgglomerativeClustering(n_clusters=None, distance_threshold=d,
                                          metric="cosine", linkage="average").fit_predict(X)
            print(f"  distance={d:.2f} -> {len(set(lab))} klasteriai")
        return

    labels = AgglomerativeClustering(n_clusters=None, distance_threshold=args.distance,
                                     metric="cosine", linkage="average").fit_predict(X)
    # klasterio embedding = jo segmentų vidurkis; laikai
    cl_emb = {}
    cl_time = defaultdict(float)
    cl_spans = defaultdict(list)
    for j, i in enumerate(idx):
        c = int(labels[j]); segs[i]["speaker"] = c
        cl_time[c] += segs[i]["end"] - segs[i]["start"]
        cl_spans[c].append((segs[i]["start"], segs[i]["end"]))
        cl_emb.setdefault(c, []).append(embs[j])
    cl_emb = {c: (np.mean(v, 0) / (np.linalg.norm(np.mean(v, 0)) + 1e-9)) for c, v in cl_emb.items()}

    print(f"Klasterių: {len(cl_emb)}")
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    store = sl.load_enroll()
    for c in sorted(cl_time, key=lambda x: -cl_time[x]):
        spans = sorted(cl_spans[c], key=lambda x: x[1] - x[0], reverse=True)
        st, en = spans[0]; en = min(en, st + 15)
        write_wav(SAMPLES_DIR / f"SPEAKER_{c:02d}.wav", samples[int(st * sr): int(en * sr)], sr)
        name, sim = sl.best_match(cl_emb[c], store, 0.5) if store else (None, 0.0)
        tag = f" -> {name} (sim {sim:.2f})" if name else (f" (artim. {sim:.2f})" if store else "")
        print(f"  SPEAKER_{c:02d}: {cl_time[c]:6.1f}s{tag}")

    Path(args.diar_json).with_suffix(".reclust.json").write_text(
        json.dumps([{"start": s["start"], "end": s["end"], "speaker": s.get("speaker", -1)} for s in segs]),
        encoding="utf-8")
    Path(args.diar_json).with_suffix(".clusters.json").write_text(
        json.dumps({str(c): e.tolist() for c, e in cl_emb.items()}), encoding="utf-8")
    print(f"Pavyzdžiai: {SAMPLES_DIR}/  | klasteriai: *.clusters.json")


if __name__ == "__main__":
    main()
