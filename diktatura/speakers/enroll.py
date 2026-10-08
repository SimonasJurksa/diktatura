#!/usr/bin/env python3
"""Balso registracija: priskiria vardą balso embedding'ui.

Du būdai:
  1) Iš diarizacijos klasterio (kai jau turim clusters.json):
       python -m diktatura.speakers.enroll --from-cluster <...clusters.json> --speaker 3 --name Jonas
  2) Iš atskiro švaraus garso pavyzdžio (10–20s tik to žmogaus):
       python -m diktatura.speakers.enroll --wav /kelias/jonas.wav --name Jonas

Kelis kartus tą patį vardą galima registruoti (keli pavyzdžiai → tikslesnis atpažinimas).
Saugoma: <duomenys>/speakers/enroll.json (paths.ENROLL).
Įprastas kelias: Apmokymai lange arba `make name-unknown` + `make assign` (nežinomi balsai iš pending/).
"""
import argparse
import json
import wave
from pathlib import Path

import numpy as np

from diktatura.speakers import speakerlib as sl
from diktatura.speakers import store


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
        # nežinomas balsas -> vardas (+ tekstuose „Kolega?nezN" -> vardas)
        try:
            n = store.assign(args.from_pending, args.name)
        except KeyError:
            raise SystemExit(f"Nėra pending: {args.from_pending} (yra: {[p.id for p in store.list_pending()]})")
        except ValueError as e:
            raise SystemExit(str(e))
        print(f"✓ Užregistruota: {args.name}  (viso pavyzdžių: {store.counts()[store.clean_name(args.name)]})")
        print(f"   pending {args.from_pending} pašalintas; tekstuose pakeista eilučių: {n}")
        print(f"   Registruoti vardai: {store.names()}")
        return
    if args.from_cluster is not None:
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
        raise SystemExit("Nurodyk --wav, --from-pending ARBA --from-cluster + --speaker")

    n = store.add_embedding(args.name, emb.tolist())
    print(f"✓ Užregistruota: {store.clean_name(args.name)}  (viso pavyzdžių: {n})")
    print(f"   Registruoti vardai: {store.names()}")


if __name__ == "__main__":
    main()
