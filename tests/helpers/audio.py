"""Sintetinis garsas testams (be mikrofono, be privačių įrašų).

Lygiai — dBFS (RMS). „speech" — kalbos imitacija: triukšmas su ~4 Hz skiemenų gaubtine
(VOX vartams svarbus tik garsumas; tikrai kalbai (VAD/ASR) naudojami LT fixture'ai — make fixtures).
"""
import wave

import numpy as np

SR = 16000


def _rng(seed):
    return np.random.default_rng(seed)


def _scale(x: np.ndarray, level_db: float) -> np.ndarray:
    rms = np.sqrt(np.mean(x.astype(np.float64) ** 2)) or 1.0
    return (x / rms * 10 ** (level_db / 20)).astype(np.float32)


def noise(sec: float, level_db: float = -60, seed: int = 1) -> np.ndarray:
    return _scale(_rng(seed).standard_normal(int(sec * SR)), level_db)


def silence(sec: float, level_db: float = -70, seed: int = 2) -> np.ndarray:
    """„Tyla" = labai tylus triukšmas (tikras mikrofonas niekada neduoda nulių)."""
    return noise(sec, level_db, seed)


def tone(sec: float, freq: float = 1000, level_db: float = -20) -> np.ndarray:
    t = np.arange(int(sec * SR)) / SR
    return _scale(np.sin(2 * np.pi * freq * t), level_db)


def speech(sec: float, level_db: float = -20, seed: int = 3) -> np.ndarray:
    """Kalbos imitacija: triukšmas × skiemenų gaubtinė; kiekvieno 100 ms gabalo RMS ~ level_db ± kelis dB."""
    n = int(sec * SR)
    t = np.arange(n) / SR
    env = 0.6 + 0.4 * np.abs(np.sin(2 * np.pi * 2.0 * t))
    return _scale(_rng(seed).standard_normal(n) * env, level_db)


def chunk_levels(x: np.ndarray, chunk: int = SR // 10) -> list:
    """100 ms gabalų RMS dBFS (kaip VOX: int16 skalė)."""
    out = []
    for i in range(0, len(x) - chunk + 1, chunk):
        c = np.clip(x[i:i + chunk], -1, 1) * 32767
        r = np.sqrt(np.mean((c / 32768.0) ** 2))
        out.append(float(20 * np.log10(r + 1e-9)))
    return out


def to_int16(x: np.ndarray) -> np.ndarray:
    return (np.clip(x, -1, 1) * 32767).astype(np.int16)


def stereo_pcm(left: np.ndarray, right: np.ndarray) -> bytes:
    n = min(len(left), len(right))
    return np.stack([to_int16(left[:n]), to_int16(right[:n])], axis=1).tobytes()


def write_wav(path, left: np.ndarray, right: np.ndarray = None, sr: int = SR) -> None:
    """Mono (be right) arba stereo 16-bit WAV."""
    with wave.open(str(path), "wb") as w:
        w.setsampwidth(2)
        w.setframerate(sr)
        if right is None:
            w.setnchannels(1)
            w.writeframes(to_int16(left).tobytes())
        else:
            w.setnchannels(2)
            w.writeframes(stereo_pcm(left, right))


def read_wav(path):
    """-> (kanalų masyvas [n, ch] float32, sr)"""
    with wave.open(str(path)) as w:
        ch, sr = w.getnchannels(), w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.reshape(-1, ch).astype(np.float32) / 32768.0, sr
