#!/usr/bin/env python3
"""Diarizacija (kas kada kalba) per sherpa-onnx — BE torch.

Įveda: mono 16 kHz WAV (pvz. kolegų R kanalas).
Išveda: segmentai (start, end, speaker_id) → stdout + .rttm/.json jei nurodyta.

Naudojimas:
    python -m diktatura.speakers.diarize <mono16k.wav> [--num-speakers N] [--threshold 0.5]
--num-speakers: jei žinai kiek žmonių (pvz. 6). -1 (numatyta) = auto pagal threshold.
"""
import argparse
import json
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx

from diktatura import paths


def model_paths():
    """(segmentacijos, embedding) ONNX keliai — skaičiuojami kvietimo metu (testai perrašo DIKTATURA_DATA)."""
    d = paths.DIARIZATION_MODELS
    return d / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx", d / "embedding_campplus_en.onnx"


def load_wav(path: str):
    with wave.open(path) as w:
        assert w.getframerate() == 16000, f"reikia 16kHz, yra {w.getframerate()}"
        assert w.getnchannels() == 1, "reikia mono"
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def build(num_speakers: int, threshold: float, threads: int = 4):
    seg_model, emb_model = model_paths()
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg_model)),
            num_threads=threads,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb_model), num_threads=threads),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=num_speakers, threshold=threshold),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not cfg.validate():
        raise SystemExit("Netinkama diarizacijos konfigūracija (patikrink modelių kelius)")
    return sherpa_onnx.OfflineSpeakerDiarization(cfg)


def diarize(wav_path: str, num_speakers: int = -1, threshold: float = 0.5):
    samples = load_wav(wav_path)
    sd = build(num_speakers, threshold)
    res = sd.process(samples).sort_by_start_time()
    return [(s.start, s.end, s.speaker) for s in res]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--num-speakers", type=int, default=-1)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--json", action="store_true", help="išsaugoti .diar.json šalia audio")
    args = ap.parse_args()

    segs = diarize(args.audio, args.num_speakers, args.threshold)
    speakers = sorted({sp for _, _, sp in segs})
    print(f"Rasta kalbėtojų: {len(speakers)}  (segmentų: {len(segs)})")
    for st, en, sp in segs:
        print(f"[{st:7.2f}–{en:7.2f}] SPEAKER_{sp:02d}")
    if args.json:
        out = Path(args.audio).with_suffix(".diar.json")
        out.write_text(json.dumps([{"start": s, "end": e, "speaker": sp} for s, e, sp in segs]),
                       encoding="utf-8")
        print(f"Išsaugota: {out}")


if __name__ == "__main__":
    main()
