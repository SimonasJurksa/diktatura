#!/usr/bin/env python3
"""Bendra balso embedding'ų biblioteka (sherpa-onnx CAM++, be torch).

- compute_embedding(samples) -> np.ndarray  (balso „pirštų atspaudas")
- cosine(a, b)
- Enroll store: ~/wispr/speakers/enroll.json  {name: [embedding...]}
  (gali būti keli embeddingai vienam vardui — tada lyginam su geriausiu).
"""
import json
from pathlib import Path

import numpy as np
import sherpa_onnx

DIAR = Path.home() / "wispr" / "models" / "diarization"
EMB_MODEL = DIAR / "embedding_campplus_en.onnx"
SPEAKERS = Path.home() / "wispr" / "speakers"
ENROLL = SPEAKERS / "enroll.json"
PENDING = SPEAKERS / "pending"   # nežinomi balsai, laukiantys vardo (sample + embedding)

_extractor = None


def extractor():
    global _extractor
    if _extractor is None:
        _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(EMB_MODEL), num_threads=4))
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


def load_enroll() -> dict:
    if ENROLL.exists():
        raw = json.loads(ENROLL.read_text(encoding="utf-8"))
        return {name: [np.array(e, dtype=np.float32) for e in embs] for name, embs in raw.items()}
    return {}


def save_enroll(store: dict) -> None:
    SPEAKERS.mkdir(parents=True, exist_ok=True)
    raw = {name: [e.tolist() for e in embs] for name, embs in store.items()}
    ENROLL.write_text(json.dumps(raw), encoding="utf-8")


def load_pending() -> dict:
    """Grąžina {id: [embedding]} — nežinomi balsai, laukiantys vardo."""
    out = {}
    if PENDING.exists():
        for j in PENDING.glob("*.json"):
            try:
                d = json.loads(j.read_text(encoding="utf-8"))
                out[j.stem] = [np.array(d["embedding"], dtype=np.float32)]
            except Exception:
                pass
    return out


def add_pending(emb: np.ndarray, samples: np.ndarray, sr: int, src: str) -> str:
    """Išsaugo nežinomo balso pavyzdį (wav) + embedding; grąžina id (pvz. 'nez3')."""
    import wave as _wave
    PENDING.mkdir(parents=True, exist_ok=True)
    nums = [int(p.stem[3:]) for p in PENDING.glob("nez*.json") if p.stem[3:].isdigit()]
    nid = f"nez{(max(nums) + 1) if nums else 1}"
    # wav pavyzdys (iki 15s)
    x = np.clip(samples[: sr * 15], -1, 1)
    with _wave.open(str(PENDING / f"{nid}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    (PENDING / f"{nid}.json").write_text(
        json.dumps({"embedding": emb.tolist(), "src": src,
                    "added": __import__("datetime").datetime.now().isoformat(timespec="seconds")}),
        encoding="utf-8")
    return nid


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
