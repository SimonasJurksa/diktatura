#!/usr/bin/env python3
"""Balso registracija: priskiria vardą balso embedding'ui.

Du būdai:
  1) Iš diarizacijos klasterio (kai jau turim clusters.json):
       python enroll.py --from-cluster <...clusters.json> --speaker 3 --name Jonas
  2) Iš atskiro švaraus garso pavyzdžio (10–20s tik to žmogaus):
       python enroll.py --wav /kelias/jonas.wav --name Jonas

Kelis kartus tą patį vardą galima registruoti (keli pavyzdžiai → tikslesnis atpažinimas).
Saugoma: ~/wispr/speakers/enroll.json
"""
import argparse
import json
import wave
from pathlib import Path

import numpy as np

import speakerlib as sl


def load_wav(path):
    with wave.open(path) as w:
        assert w.getframerate() == 16000, "reikia 16kHz mono"
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--wav")
    ap.add_argument("--from-cluster")
    ap.add_argument("--speaker", type=int)
    ap.add_argument("--from-pending", help="nežinomo balso id (pvz. nez3) iš speakers/pending/")
    args = ap.parse_args()

    if args.from_pending:
        import json
        pj = sl.PENDING / f"{args.from_pending}.json"
        if not pj.exists():
            raise SystemExit(f"Nėra pending: {args.from_pending} (yra: {[p.stem for p in sl.PENDING.glob('*.json')]})")
        emb = np.array(json.loads(pj.read_text())["embedding"], dtype=np.float32)
    elif args.from_cluster is not None:
        if args.speaker is None:
            raise SystemExit("--from-cluster reikalauja --speaker N")
        clusters = json.loads(Path(args.from_cluster).read_text())
        key = str(args.speaker)
        if key not in clusters:
            raise SystemExit(f"Nėra SPEAKER_{args.speaker} klasterių faile (yra: {sorted(clusters)})")
        emb = np.array(clusters[key], dtype=np.float32)
    elif args.wav:
        emb = sl.compute_embedding(load_wav(args.wav))
    else:
        raise SystemExit("Nurodyk --wav ARBA --from-cluster + --speaker")

    store = sl.load_enroll()
    store.setdefault(args.name, []).append(emb)
    sl.save_enroll(store)
    print(f"✓ Užregistruota: {args.name}  (viso pavyzdžių: {len(store[args.name])})")
    # Jei iš pending — pašalinam kandidatą (jau priskirtas)
    if args.from_pending:
        for ext in (".wav", ".json"):
            (sl.PENDING / f"{args.from_pending}{ext}").unlink(missing_ok=True)
        print(f"   pending {args.from_pending} pašalintas (priskirtas {args.name})")
    print(f"   Registruoti vardai: {sorted(store)}")


if __name__ == "__main__":
    main()
