"""Diktatūra — VAD pre-filtras: Silero VAD (faster_whisper.vad, ONNX, ~2 MB, ateina su faster-whisper).

Prieš kraunant Ąžuolą (~3 GB RAM, iki ~30 s) kiekvienam kanalui nustatomos kalbos atkarpos:
  - kalbos < VAD_MIN_SPEECH_SEC  -> kanalas praleidžiamas; jei abu (arba mono) — failas „tuščias", modelis NEkraunamas
    (VOX blyksniai, triukšmas, muzika, pypsėjimai; tuščią tekstą transcribe-file.sh tvarko pagal DELETE_EMPTY);
    tylus / be kalbos dešinys (sistemos) kanalas diktuojant — netranskribuojamas;
  - VAD_TRIM=1: garsas apkarpomas iki kalbos (+ VAD_PAD_SEC) -> trumpesnis įvestis Whisper'iui, segmentų laikai
    perskaičiuojami atgal į originalą (remap). Matuota 2026-10-08: tik 2–4 % greičiau (faster-whisper ir taip turi
    vidinį VAD), o tekstas keliais žodžiais skiriasi -> numatytai IŠJUNGTA (Whisper gauna visą kanalą).

Nustatymai: VAD_FILTER (1/0), VAD_MIN_SPEECH_SEC, VAD_PAD_SEC, VAD_TRIM.  CLI (diagnostikai):
    python -m diktatura.audio.prefilter <garsas> [--min 0.8] [--pad 0.2]
"""
import argparse
import json
from dataclasses import dataclass, field

import numpy as np

SR = 16000


def merge(spans, gap: float = 0.0) -> list:
    """Persidengiančias / besiliečiančias atkarpas [(start, end)] sujungti (rikiuotai)."""
    out = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def speech_spans(samples: np.ndarray, pad_sec: float = 0.2, threshold: float = 0.5,
                 min_silence_sec: float = 0.5, sr: int = SR) -> list:
    """Kalbos atkarpos sekundėmis [(start, end)], su paddingu (apkirpta iki įrašo ribų)."""
    if samples.size < sr // 10:
        return []
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    ts = get_speech_timestamps(samples.astype(np.float32), VadOptions(
        threshold=threshold, min_speech_duration_ms=150, min_silence_duration_ms=int(min_silence_sec * 1000),
        speech_pad_ms=0), sampling_rate=sr)
    dur = samples.size / sr
    return merge([(max(0.0, t["start"] / sr - pad_sec), min(dur, t["end"] / sr + pad_sec)) for t in ts])


def speech_seconds(spans) -> float:
    return float(sum(e - s for s, e in spans))


def trim(samples: np.ndarray, spans, sr: int = SR):
    """-> (tik kalba sujungta, mapping [(trim_start, orig_start, trukmė)] sekundėmis)."""
    parts, mapping, t = [], [], 0.0
    for s, e in spans:
        a, b = int(round(s * sr)), int(round(e * sr))
        if b <= a:
            continue
        parts.append(samples[a:b])
        mapping.append((t, a / sr, (b - a) / sr))
        t += (b - a) / sr
    return (np.concatenate(parts) if parts else samples[:0]), mapping


def remap(t: float, mapping) -> float:
    """Laikas apkarpytame garse -> laikas originale."""
    if not mapping:
        return t
    for t0, o0, d in mapping:
        if t < t0 + d:
            return o0 + max(0.0, t - t0)
    t0, o0, d = mapping[-1]
    return o0 + (t - t0)


@dataclass
class ChannelPlan:
    speech_sec: float
    skip: bool
    audio: np.ndarray
    mapping: list = field(default_factory=list)
    spans: list = field(default_factory=list)
    original_sec: float = 0.0

    def to_original(self, t: float) -> float:
        return remap(t, self.mapping)


def plan(samples: np.ndarray, min_speech_sec: float, pad_sec: float, enabled: bool = True,
         trim_audio: bool = True, sr: int = SR) -> ChannelPlan:
    """Ką daryti su kanalu: praleisti (kalbos per mažai) arba transkribuoti (apkarpytą arba visą)."""
    dur = samples.size / sr
    whole = [(0.0, 0.0, dur)]
    if not enabled:
        return ChannelPlan(dur, dur <= 0, samples, whole, [(0.0, dur)], dur)
    spans = speech_spans(samples, pad_sec, sr=sr)
    sp = speech_seconds(spans)
    if sp < min_speech_sec:
        return ChannelPlan(sp, True, samples[:0], [], spans, dur)
    if not trim_audio:
        return ChannelPlan(sp, False, samples, whole, spans, dur)
    audio, mapping = trim(samples, spans, sr)
    return ChannelPlan(sp, False, audio, mapping, spans, dur)


@dataclass
class VadSettings:
    enabled: bool
    min_speech: float
    pad: float
    trim: bool

    def plan(self, samples: np.ndarray) -> ChannelPlan:
        return plan(samples, self.min_speech, self.pad, self.enabled, self.trim)


def settings() -> VadSettings:
    """VAD nustatymai (VAD_FILTER, VAD_MIN_SPEECH_SEC, VAD_PAD_SEC, VAD_TRIM)."""
    from diktatura import config
    c = config.load()
    return VadSettings(bool(c["VAD_FILTER"]), float(c["VAD_MIN_SPEECH_SEC"]), float(c["VAD_PAD_SEC"]),
                       bool(c["VAD_TRIM"]))


def main():
    from faster_whisper.audio import decode_audio
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--min", type=float)
    ap.add_argument("--pad", type=float)
    a = ap.parse_args()
    vs = settings()
    mn = a.min if a.min is not None else vs.min_speech
    pad = a.pad if a.pad is not None else vs.pad
    chans = decode_audio(a.audio, sampling_rate=SR, split_stereo=True)
    chans = chans if isinstance(chans, tuple) else (chans,)
    out = []
    for i, ch in enumerate(chans):
        p = plan(ch, mn, pad, vs.enabled, vs.trim)
        out.append({"channel": i, "duration": round(p.original_sec, 2), "speech": round(p.speech_sec, 2),
                    "skip": p.skip, "spans": [(round(s, 2), round(e, 2)) for s, e in p.spans]})
    print(json.dumps({"min_speech_sec": mn, "pad_sec": pad, "channels": out}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
