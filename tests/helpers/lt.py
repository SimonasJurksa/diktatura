"""LT kalbos fixture'ai (make fixtures) ir WER (žodžių klaidų dažnis) testams."""
import re
import subprocess
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
CV_DIR = REPO / "tests" / "fixtures" / "cv"
MANIFEST = REPO / "tests" / "fixtures" / "cv_lt.tsv"


def clips() -> list:
    """[(mp3 kelias, tekstas)] — tik atsisiųsti."""
    out = []
    for ln in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        cid, _rng, _sha, text = ln.split("\t")
        f = CV_DIR / f"{cid}.mp3"
        if f.exists():
            out.append((f, text))
    return out


def decode(path, sr: int = 16000) -> np.ndarray:
    """Bet koks garsas -> float32 mono sr (per ffmpeg)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def norm_words(text: str) -> list:
    return re.findall(r"\w+", text.lower())


def wer(ref: str, hyp: str) -> float:
    r, h = norm_words(ref), norm_words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))
