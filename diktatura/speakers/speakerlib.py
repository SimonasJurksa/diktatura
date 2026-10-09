#!/usr/bin/env python3
"""Balso embedding'ai ir vardų priskyrimas (sherpa-onnx, 3D-Speaker CAM++ zh-en „advanced", be torch).

Modelis pasirinktas 2026-10-09 matuojant savininko įrašuose (docs/ARCHITECTURE.md §3): tavo balsas vs kolegos —
EER ~0–1 % (buvęs CAM++ VoxCeleb — ~13 %), tas pats dydis ir greitis.

- compute_embedding(samples) -> np.ndarray  (balso „pirštų atspaudas")
- cosine(a, b), best_match(emb, store, threshold), ranked(emb, store), decide(rank, threshold, margin)
- label_segments(...) — kolegų segmentams vardai: registruotas -> vardas; tavo balsas -> „Tu";
  du balsai per panašūs -> „Kolega?" (griežtumas: slenkstis + skirtumas iki antro);
  nežinomas -> „Kolega?nezN" (naujas nežinomas išsaugomas į pending); „triukšmas" (ignored.json) -> „Kolega?".
- Saugykla (enroll.json, pending/, ignored.json) — diktatura.speakers.store (tik stdlib); čia — numpy vaizdas.
"""
import wave

import numpy as np

from diktatura import debug, paths
from diktatura.speakers import store as st

_extractor = None


def emb_model_path():
    return paths.EMB_MODEL_FILE


def extractor():
    global _extractor
    if _extractor is None:
        import sherpa_onnx
        _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb_model_path()), num_threads=4))
    return _extractor


def compute_embedding(samples: np.ndarray, sr: int = 16000) -> np.ndarray:
    """samples: float32 [-1,1] mono. Grąžina normalizuotą embedding vektorių."""
    ex = extractor()
    s = ex.create_stream()
    s.accept_waveform(sr, samples)
    s.input_finished()
    emb = np.array(ex.compute(s), dtype=np.float32)
    n = np.linalg.norm(emb)
    return emb / n if n > 0 else emb


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _arrays(raw: dict) -> dict:
    return {k: [np.array(e, dtype=np.float32) for e in v] for k, v in raw.items()}


def load_enroll() -> dict:
    """{vardas: [np.ndarray, ...]}"""
    return _arrays(st.load_enroll_raw())


def save_enroll(store: dict) -> None:
    st.claim_model()
    st.save_enroll_raw({k: [np.asarray(e).tolist() for e in v] for k, v in store.items()})


def load_pending() -> dict:
    """{id: [embedding]} — nežinomi balsai, laukiantys vardo."""
    return {p.id: [np.array(p.embedding, dtype=np.float32)] for p in st.list_pending()}


def load_owner() -> list:
    """Tavo balso embedding'ai [np.ndarray] (owner.json) — atpažinti tave kolegų kanale."""
    return [np.array(o["embedding"], dtype=np.float32) for o in st.load_owner_raw()]


def load_ignored() -> dict:
    """{'_ign0': [embedding], ...} — formatas kaip enroll (best_match'ui)."""
    return {f"_ign{i}": [np.array(e, dtype=np.float32)] for i, e in enumerate(st.load_ignored())}


def write_wav(path, samples: np.ndarray, sr: int = 16000) -> None:
    x = np.clip(samples, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


def add_pending(emb: np.ndarray, samples: np.ndarray, sr: int, src: str) -> str:
    """Išsaugo nežinomo balso pavyzdį (wav, iki 15 s) + embedding; grąžina id (pvz. 'nez3')."""
    st.claim_model()
    pid = st.next_pending_id()
    write_wav(paths.PENDING / f"{pid}.wav", samples[: sr * 15], sr)
    st.write_pending_meta(pid, np.asarray(emb).tolist(), src)
    return pid


def best_match(emb: np.ndarray, store: dict, threshold: float = 0.5):
    """Grąžina (vardas, panašumas) arba (None, geriausias_panašumas) jei < threshold."""
    best_name, best_sim = None, -1.0
    for name, embs in store.items():
        sim = max(cosine(emb, e) for e in embs)
        if sim > best_sim:
            best_name, best_sim = name, sim
    if best_sim >= threshold:
        return best_name, best_sim
    return None, best_sim


def ranked(emb: np.ndarray, store: dict) -> list:
    """[(panašumas, vardas)] mažėjančiai; vardo panašumas — geriausias iš jo pavyzdžių."""
    return sorted(((max(cosine(emb, e) for e in embs), name) for name, embs in store.items() if embs),
                  key=lambda x: -x[0])


def decide(rank, threshold: float, margin: float = 0.0):
    """Griežtas sprendimas -> (vardas | None, priežastis):
    "ok"    — geriausias >= slenksčio IR bent `margin` aukščiau už antrą (kitą vardą);
    "close" — virš slenksčio, bet du balsai per panašūs (geriau „Kolega?" nei klaidingas vardas);
    "low"   — niekas nesiekia slenksčio (naujas / nežinomas balsas)."""
    if not rank or rank[0][0] < threshold:
        return None, "low"
    if len(rank) > 1 and rank[0][0] - rank[1][0] < margin:
        return None, "close"
    return rank[0][1], "ok"


MIN_SEG_SEC = 0.8      # trumpesniam segmentui balso embedding nepatikimas -> „Kolega?"


def label_segments(segs, samples, store, pending, ignored, threshold, embed, add_pending_fn, src, sr=16000,
                   margin=0.0, owner=None, me_label="Tu"):
    """segs: [(start, end, tekstas)] kolegų kanale -> ([(start, end, kas, tekstas)], naujų nežinomų sk.).

    Registruotas balsas -> vardas; tavo balsas (owner, pvz. jungiesi telefonu ir kalbi per kolegų kanalą) -> me_label;
    du balsai per panašūs (decide: "close") -> „Kolega?"; atpažintas triukšmas (ignored) -> „Kolega?";
    nežinomas -> „Kolega?nezN" (tas pats nežinomas keliuose segmentuose/failuose -> tas pats nezN; naujas ->
    add_pending_fn). pending papildomas vietoje (kad tame pačiame faile antras segmentas atpažintų ką tik pridėtą)."""
    cands = dict(store)
    if owner:
        cands[me_label] = owner
    out, new = [], 0
    for s0, s1, tx in segs:
        who = st.UNKNOWN
        if (s1 - s0) >= MIN_SEG_SEC:
            seg = samples[int(s0 * sr):int(s1 * sr)]
            if len(seg) >= sr * 0.5:
                emb = embed(seg)
                rank = ranked(emb, cands)
                name, why = decide(rank, threshold, margin)
                if debug.enabled():
                    top = ", ".join(f"{n}={v:.2f}" for v, n in rank[:3]) or "-"
                    debug.log("speakers", f"[{s0:7.1f}–{s1:7.1f}] {top} -> {name or why} "
                                          f"(slenkstis {threshold}, skirtumas {margin})")
                if name:
                    who = name
                elif why == "low" and not (ignored and best_match(emb, ignored, threshold)[0]):
                    pid, _ = best_match(emb, pending, threshold) if pending else (None, 0.0)
                    if not pid:
                        pid = add_pending_fn(emb, seg, sr, src)
                        pending[pid] = [emb]
                        new += 1
                    who = st.label_for(pid)
        out.append((s0, s1, who, tx))
    return out, new
