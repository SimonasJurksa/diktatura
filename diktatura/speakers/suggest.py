#!/usr/bin/env python3
"""Diktatūra — laukiančių balsų pertikrinimas pagal jau išmoktus (🎓 Apmokymai „🔄 Pertikrinti"; .venv).

Kam: įvardinus dalį nežinomų balsų (pvz. ilgas susirinkimas — šimtai trumpų fragmentų), kiti fragmentai dažnai yra
tų pačių žmonių. Kiekvienas laukiantis balsas palyginamas su registruotais (ir su tavo balsu „Tu"); jei nė vienas
netinka — su „ne žmogus / triukšmas" pavyzdžiais. Rezultatas — <duomenys>/speakers/suggestions.json (formatas —
diktatura.speakers.store): Apmokymuose 💡 pasiūlymas, sąraše viršuje, vardas jau įrašytas — patvirtini Enter.
Vardai tekstuose patys NEKEIČIAMI: trumpo fragmento balsas nepatikimas (žr. matavimus žemiau).

Griežtumas (nustatymai):
  užtikrintas — kaip transkripcijoje: ≥ SPEAKER_THRESHOLD ir bent SPEAKER_MARGIN aukščiau už antrą kandidatą
                (toks balsas dabar būtų atpažintas automatiškai; Apmokymuose galima priimti visus iš karto);
  pasiūlymas  — ≥ SPEAKER_SUGGEST ir bent store.SUGGEST_MARGIN aukščiau už antrą kandidatą.
Triukšmas lyginamas tik jei joks vardas netinka — kaip ir transkripcijoje. Kartu su vardais triukšmo pavyzdžiai
(„visko po truputį") nustelbia tikrus žmones: matuota 2026-10-25, tada iš 50 įvardintų liko 2 teisingi pasiūlymai.

Balso „profilis": jei balsas tekstuose kalbėjo ≥ PROFILE_MIN_LINES kartus, lyginama ne vieno trumpo pavyzdžio
(dažnai 1–2 s), o visų jo eilučių kalbos (iki PROFILE_MAX_LINES eilučių, ≤ PROFILE_MAX_SEC s; stereo — kolegų R
kanalas) embedding'as. Matuota 2026-10-25 (susirinkimo įrašas, 45 įvardinti balsai, „palik vieną"): teisingų
pasiūlymų dalis 75 % -> 83 % (slenkstis 0.4), užtikrintų 4/6 -> 7/9 (0.5). Registruoti balsai lieka trumpi pavyzdžiai.
Profiliai kešuojami <duomenys>/speakers/profiles.json (perskaičiuojami tik pasikeitus balso eilutėms); pirmą
kartą ilgam įrašui — apie minutę (ffmpeg + VAD + balso modelis), vėliau — akimirka.

    python -m diktatura.speakers.suggest [--no-profiles]
Spausdina eigą („profiliai k/n") ir pabaigoje vieną JSON eilutę: {"ok", "pending", "suggested", "strong", "noise",
"profiles", "by_name"}. Išėjimo kodas 2 — balsai paskaičiuoti senu modeliu (make speakers-migrate).
"""
import argparse
import json
import time
from collections import Counter

import numpy as np

from diktatura import config, debug, paths, sessions
from diktatura.speakers import speakerlib as sl
from diktatura.speakers import store
from diktatura.speakers import teach

SR = 16000
PROFILE_MIN_LINES = 2
PROFILE_MAX_LINES = 8
PROFILE_MAX_SEC = 30.0
LINE_MIN_SPEECH_SEC = 0.5     # eilutė su mažiau kalbos į profilį neimama


def thresholds(cfg=None):
    c = cfg or config.load()
    return float(c["SPEAKER_THRESHOLD"]), float(c["SPEAKER_MARGIN"]), float(c["SPEAKER_SUGGEST"])


def judge(emb, cands: dict, ignored: list, threshold: float, margin: float, suggest: float):
    """Vienas laukiantis balsas -> pasiūlymas {"name" ("" = triukšmas), "sim", "alt", "alt_sim", "strong"} | None.
    cands: {vardas | „Tu": [embedding]}; ignored: [embedding] („ne žmogus")."""
    rank = sl.ranked(emb, cands)
    top = rank[0] if rank else (0.0, None)
    alt = rank[1] if len(rank) > 1 else (0.0, None)
    name, why = sl.decide(rank, threshold, margin)
    if name or (rank and top[0] >= suggest and top[0] - alt[0] >= store.SUGGEST_MARGIN):
        return {"name": top[1], "sim": round(top[0], 3), "alt": alt[1], "alt_sim": round(alt[0], 3),
                "strong": bool(name)}
    if ignored:
        ig = max(sl.cosine(emb, e) for e in ignored)
        if ig >= suggest and ig - top[0] >= store.SUGGEST_MARGIN:
            return {"name": "", "sim": round(ig, 3), "alt": top[1], "alt_sim": round(top[0], 3),
                    "strong": why == "low" and ig >= threshold}      # transkripcija tokį žymėtų „Kolega?"
    return None


def profile_key(occ) -> str:
    """Kokios eilutės sudaro profilį (pasikeitus — perskaičiuoti)."""
    return "|".join(f"{f.name}#{i}" for f, _, _, i in occ[:PROFILE_MAX_LINES])


class Channels:
    """Kurį kanalą imti: stereo — kolegų (R, 1), mono — 0. Kešas pagal garso failą."""

    def __init__(self):
        self.ch = {}

    def __call__(self, audio) -> int:
        if audio not in self.ch:
            self.ch[audio] = 1 if teach.n_channels(audio) >= 2 else 0
        return self.ch[audio]


def profile(occ, embed, channel):
    """Balso profilis iš jo eilučių [(failas, laikas, tekstas, nr.)] -> (embedding, kalbos s) | None (per mažai)."""
    parts, total = [], 0.0
    for f, _, _, idx in occ[:PROFILE_MAX_LINES]:
        audio, span = sessions.audio_for(f), store.line_span(f, idx)
        if audio is None or span is None:
            continue
        x, sec = teach.speech_only(teach.decode(audio, span[0], span[1] - span[0], channel(audio)))
        if sec < LINE_MIN_SPEECH_SEC:
            continue
        parts.append(x)
        total += sec
        if total >= PROFILE_MAX_SEC:
            break
    if len(parts) < PROFILE_MIN_LINES:
        return None
    return embed(np.concatenate(parts)[: int(PROFILE_MAX_SEC * SR)]), total


def _profiles_file():
    return paths.SPEAKERS / "profiles.json"


def update_profiles(pend, occ, embed, out=print) -> dict:
    """{nezN: {"key", "embedding" | None, "speech_sec"}} dabar laukiantiems su ≥ PROFILE_MIN_LINES eilučių."""
    cache = store._read_json(_profiles_file(), {})
    cache = cache if isinstance(cache, dict) else {}
    need = [p for p in pend if len(occ[p.label]) >= PROFILE_MIN_LINES]
    res, channel, fails = {}, Channels(), 0
    for k, p in enumerate(need, 1):
        key = profile_key(occ[p.label])
        old = cache.get(p.id)
        if isinstance(old, dict) and old.get("key") == key:
            res[p.id] = old
            continue
        r = None
        if fails < 3:                       # balso modelio / garso nėra — nebandyti šimtus kartų
            try:
                r = profile(occ[p.label], embed, channel)
                fails = 0
            except Exception as e:          # noqa: BLE001 — profilis neprivalomas: lieka trumpas pavyzdys
                fails += 1
                debug.log("speakers", f"pertikrinimas: {p.id} profilio nepavyko ({e})")
        res[p.id] = {"key": key, "embedding": np.asarray(r[0]).round(6).tolist() if r else None,
                     "speech_sec": round(r[1], 1) if r else 0.0}
        out(f"profiliai {k}/{len(need)}")
    store._atomic_write(_profiles_file(), json.dumps(res))
    return res


def run(embed=None, profiles: bool = True, out=print) -> dict:
    if not store.compatible():
        return {"ok": False, "error": f"balsai paskaičiuoti senu modeliu ({store.model_id()}) — make speakers-migrate"}
    started, voices = time.time(), store.voices_signature()    # prieš skaitant: pasikeitę vėliau — vėl pasenę
    thr, mg, sug = thresholds()
    pend = store.list_pending()
    occ = store.occurrences_many([p.label for p in pend], with_idx=True)
    prof = update_profiles(pend, occ, embed or sl.compute_embedding, out) if profiles else {}
    cands = {k: v for k, v in sl.load_enroll().items() if v}
    owner = sl.load_owner()
    if owner:
        cands[store.ME] = owner
    ignored = [np.array(e, dtype=np.float32) for e in store.load_ignored()]
    items = {}
    for p in pend:
        pe = (prof.get(p.id) or {}).get("embedding")
        s = judge(np.array(pe or p.embedding, dtype=np.float32), cands, ignored, thr, mg, sug)
        if s:
            items[p.id] = {**s, "basis": "profile" if pe else "sample", "lines": len(occ[p.label])}
    store._atomic_write(store.suggestions_file(), json.dumps({
        "started": started, "voices": voices, "threshold": thr, "margin": mg, "suggest": sug,
        "checked": [p.id for p in pend], "items": items}, ensure_ascii=False))
    res = {"ok": True, "pending": len(pend), "suggested": len(items),
           "strong": sum(1 for s in items.values() if s["strong"]),
           "noise": sum(1 for s in items.values() if s["name"] == ""),
           "profiles": sum(1 for v in prof.values() if v.get("embedding")),
           "by_name": dict(Counter(s["name"] for s in items.values() if s["name"]).most_common())}
    debug.log("speakers", f"pertikrinimas: laukia {res['pending']}, pasiūlymų {res['suggested']} "
                          f"(užtikrintų {res['strong']}, triukšmo {res['noise']}), profilių {res['profiles']}")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(prog="diktatura.speakers.suggest")
    ap.add_argument("--no-profiles", action="store_true", help="tik trumpi pavyzdžiai (be garso dekodavimo)")
    a = ap.parse_args()
    r = run(profiles=not a.no_profiles, out=lambda s: print(s, flush=True))
    print(json.dumps(r, ensure_ascii=False), flush=True)
    raise SystemExit(0 if r["ok"] else 2)


if __name__ == "__main__":
    main()
