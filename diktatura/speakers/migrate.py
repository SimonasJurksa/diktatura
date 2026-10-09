#!/usr/bin/env python3
"""Diktatūra — balsų saugyklos perėjimas prie naujo balso modelio (.venv).

Skirtingų modelių embedding'ai nesulyginami, o seni balsų pavyzdžiai (garsas) nesaugomi — todėl:
  - enroll.json, ignored.json, owner.json -> archyvas <duomenys>/speakers/legacy-<modelis>-<laikas>/ (niekas netrinama);
  - laukiantys vardo balsai (pending/nezN.wav yra) — perskaičiuojami nauju modeliu, be garso — į archyvą;
  - assigned.json lieka (nezN -> vardas istorija); transkripcijos nekeičiamos;
  - uždedama žymė model.json. Vardai išmokstami iš naujo: Apmokymai / „✎ Kas kalbėjo?";
    paskutinių dienų tekstus galima perskaičiuoti: make speakers-relabel.
Kodėl ne „perkelti" senus vardus: matuota 2026-10-09 — seno modelio vardai tekstuose beveik atsitiktiniai
(tos pačios žymės eilutės tarpusavyje ne panašesnės nei skirtingų), tad iš jų išmoktas balsas būtų klaidingas.

    python -m diktatura.speakers.migrate            # ką darytų (nieko nekeičia)
    python -m diktatura.speakers.migrate --apply    # atlikti
"""
import argparse
import shutil
import wave
from datetime import datetime

import numpy as np

from diktatura import debug, paths
from diktatura.speakers import store

ARCHIVED = ("enroll.json", "ignored.json", "owner.json", "model.json")


def plan() -> dict:
    pend = store.list_pending()
    return {"from": store.model_id(), "to": store.EMB_MODEL, "needed": not store.compatible(),
            "enroll": store.counts(), "ignored": len(store.load_ignored()), "owner": store.owner_count(),
            "pending_reembed": [p.id for p in pend if p.wav.exists()],
            "pending_drop": [p.id for p in pend if not p.wav.exists()]}


def read_wav(path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def apply(embed=None, now: datetime = None):
    """Atlikti perėjimą. -> archyvo katalogas (arba None, jei perėjimo nereikia)."""
    p = plan()
    if not p["needed"]:
        return None
    if embed is None:
        from diktatura.speakers import speakerlib
        embed = speakerlib.compute_embedding
    sp = paths.SPEAKERS
    dst = sp / f"legacy-{p['from']}-{(now or datetime.now()):%Y%m%d_%H%M%S}"
    (dst / "pending").mkdir(parents=True)
    for name in ARCHIVED:
        if (sp / name).exists():
            shutil.move(str(sp / name), str(dst / name))
    for pv in store.list_pending():
        shutil.copy2(paths.PENDING / f"{pv.id}.json", dst / "pending" / f"{pv.id}.json")
        if pv.wav.exists():
            store.write_pending_meta(pv.id, embed(read_wav(pv.wav)), pv.src)
        else:
            (paths.PENDING / f"{pv.id}.json").unlink()
    store.mark_model()
    debug.log("speakers", f"migracija {p['from']} -> {store.EMB_MODEL}: archyvas {dst}")
    return dst


def main() -> None:
    ap = argparse.ArgumentParser(prog="diktatura.speakers.migrate")
    ap.add_argument("--apply", action="store_true", help="atlikti (be jo — tik parodo, ką darytų)")
    a = ap.parse_args()
    p = plan()
    if not p["needed"]:
        print(f"✓ Balsų saugykla jau dabartinio modelio ({store.EMB_MODEL}) — nieko daryti nereikia.")
        return
    print(f"Balso modelis: {p['from']} -> {p['to']}")
    print(f"  į archyvą: registruoti balsai {sum(p['enroll'].values())} pavyzd. "
          f"({', '.join(f'{k} {v}' for k, v in sorted(p['enroll'].items())) or '—'}), "
          f"„ne žmogus“ {p['ignored']}, tavo balso {p['owner']}")
    print(f"  laukiantys vardo: perskaičiuoti {len(p['pending_reembed'])}, be garso (į archyvą) {len(p['pending_drop'])}")
    if not a.apply:
        print("Nieko nepakeista. Atlikti: make speakers-migrate APPLY=1")
        return
    dst = apply()
    print(f"✓ Atlikta. Seni balsai: {dst}\n  Vardus išmok iš naujo: 🎓 Apmokymai, 📄 Tekstas → „✎ Kas kalbėjo?“; "
          "paskutinių dienų tekstus perskaičiuoti: make speakers-relabel")


if __name__ == "__main__":
    main()
