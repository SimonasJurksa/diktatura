"""Diktatūra — garso bangų smailės (🌊 Teksto skiltyje, ⏳ eigos langelyje).

<bazė>.peaks — mažas dvejetainis failas šalia transkripcijos: kiekvieno kanalo smailė (max |amplitudė|) kas 1/RATE s,
dBFS -> 0..255 (FLOOR_DB…0 dB). 2 val. stereo įrašas ≈ 144 KB. Skaičiuojama transkripcijos pradžioje
(bin/transcribe-file.sh) arba Teksto skilties paprašius seniems įrašams (fone). Garsą ištrynus (AUDIO_CLEANUP) smailės
lieka — banga matoma ir be garso.

Skaitymas ir piešimo pagalbinės funkcijos — tik stdlib (UI, sistemos python3); compute() — .venv (numpy + ffmpeg).
CLI (.venv):  python -m diktatura.waveform <garsas> [--out <bazė>.peaks]
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from diktatura import sessions

MAGIC = b"DKPK"
VERSION = 1
RATE = 10                    # smailių per sekundę kanalui (100 ms — kaip VOX gabalas)
FLOOR_DB = -80.0             # 0 = ≤ −80 dBFS, 255 = 0 dBFS
HEADER = struct.Struct("<4sBHBI")   # magic, versija, rate, kanalai, kadrų skaičius
SUFFIX = ".peaks"
DECODE_SR = 8000             # smailėms užtenka; ffmpeg dekoduoja greičiau


@dataclass
class Peaks:
    rate: int
    channels: int
    data: bytes                       # kadrai iš eilės: [k0, k1, k0, k1, …]

    @property
    def frames(self) -> int:
        return len(self.data) // max(1, self.channels)

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0

    def channel(self, i: int) -> bytes:
        return self.data[i::self.channels]


def encode_db(db: float) -> int:
    return max(0, min(255, int(round((max(FLOOR_DB, min(0.0, db)) - FLOOR_DB) / -FLOOR_DB * 255))))


def decode_db(v: int) -> float:
    return FLOOR_DB + v / 255 * -FLOOR_DB


def peaks_path(path) -> Path:
    """Garso ar transkripcijos failas -> <bazė>.peaks tame pačiame kataloge."""
    p = Path(path)
    return p.with_name(sessions.base_name(p.name) + SUFFIX)


def write(path, pk: Peaks) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "wb") as fh:
        fh.write(HEADER.pack(MAGIC, VERSION, pk.rate, pk.channels, pk.frames))
        fh.write(pk.data[:pk.frames * pk.channels])
    os.replace(tmp, path)


def read(path):
    """-> Peaks arba None (nėra / sugadintas)."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    if len(raw) < HEADER.size:
        return None
    magic, ver, rate, ch, frames = HEADER.unpack_from(raw)
    if magic != MAGIC or ver != VERSION or not rate or ch not in (1, 2):
        return None
    data = raw[HEADER.size:HEADER.size + frames * ch]
    return Peaks(rate, ch, data[:len(data) // ch * ch])


def is_fresh(peaks_file, audio) -> bool:
    """Ar smailės yra ir ne senesnės už garsą (garsas perrašytas -> skaičiuoti iš naujo)."""
    try:
        return Path(peaks_file).stat().st_mtime >= Path(audio).stat().st_mtime - 1
    except OSError:
        return Path(peaks_file).exists()


# ── skaičiavimas (.venv) ──

def audio_channels(audio) -> int:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
                              "-of", "csv=p=0", str(audio)], capture_output=True, text=True, timeout=30).stdout
        return 2 if out.strip() == "2" else 1
    except (OSError, subprocess.SubprocessError):
        return 1


def compute(audio, rate: int = RATE, channels: int = None) -> Peaks:
    """Garso failas (bet koks ffmpeg formatas) -> Peaks. Skaitoma dalimis (2 val. įrašas atmintyje netelpa)."""
    import numpy as np
    ch = channels or audio_channels(audio)
    step = DECODE_SR // rate                      # mėginių kanalui viename smailės kadre
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(audio), "-ac", str(ch), "-ar", str(DECODE_SR),
           "-f", "s16le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    out = bytearray()
    block = step * ch * 2 * rate * 60             # ~1 min garso
    rest = b""
    try:
        while True:
            buf = proc.stdout.read(block)
            if not buf:
                break
            buf = rest + buf
            usable = len(buf) // (step * ch * 2) * (step * ch * 2)
            rest = buf[usable:]
            if usable:
                x = np.frombuffer(buf[:usable], dtype=np.int16).reshape(-1, step, ch)
                peak = np.abs(x.astype(np.int32)).max(axis=1) / 32768.0          # (kadrai, kanalai)
                db = 20 * np.log10(np.maximum(peak, 1e-9))
                v = np.clip(np.round((np.clip(db, FLOOR_DB, 0.0) - FLOOR_DB) / -FLOOR_DB * 255), 0, 255)
                out += v.astype(np.uint8).tobytes()
        if rest:                                      # paskutinis nepilnas kadras
            x = np.frombuffer(rest[:len(rest) // (ch * 2) * ch * 2], dtype=np.int16).reshape(-1, ch)
            if len(x):
                peak = np.abs(x.astype(np.int32)).max(axis=0) / 32768.0
                out += bytes(encode_db(20 * np.log10(max(float(p), 1e-9))) for p in peak)
    finally:
        proc.stdout.close()
        proc.wait()
    if proc.returncode not in (0, None) and not out:
        raise RuntimeError(f"ffmpeg nepavyko perskaityti {audio}")
    return Peaks(rate, ch, bytes(out))


def ensure(audio, out=None) -> Path:
    """Suskaičiuoti smailes, jei jų nėra arba garsas naujesnis. -> smailių failo kelias."""
    out = Path(out) if out else peaks_path(audio)
    if not (out.exists() and is_fresh(out, audio)):
        write(out, compute(audio))
    return out


# ── piešimui (UI, gryna logika) ──

def _pct(values, q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values[::max(1, len(values) // 4000)])
    return float(s[min(len(s) - 1, int(q * (len(s) - 1)))])


def scale_of(channel: bytes, min_range: float = 40.0) -> tuple:
    """(grindys, viršus) baitų skalėje: fonas (20-tas percentilis) — nulis, garsiausia (99,5-tas) — pilnas aukštis.
    Tylus / vien triukšmo kanalas nepadidinamas (min_range ≈ 12 dB)."""
    lo, hi = _pct(channel, 0.2), _pct(channel, 0.995)
    return lo, max(hi, lo + min_range)


def columns(channel: bytes, width: int, start: int = 0, end: int = None, scale: tuple = None) -> list:
    """Kanalo smailės [start, end) kadrų -> width stulpelių aukščių 0..1 (stulpelyje — garsiausias kadras)."""
    end = len(channel) if end is None else min(end, len(channel))
    start = max(0, min(start, end))
    n = end - start
    if width <= 0 or n <= 0:
        return [0.0] * max(0, width)
    lo, hi = scale or scale_of(channel)
    rng = (hi - lo) or 1.0
    out = []
    for x in range(width):
        a = start + x * n // width
        b = max(a + 1, start + (x + 1) * n // width)
        v = max(channel[a:b])
        out.append(max(0.0, min(1.0, (v - lo) / rng)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="diktatura.waveform")
    ap.add_argument("audio")
    ap.add_argument("--out", help="numatyta: <bazė>.peaks šalia garso")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else peaks_path(a.audio)
    try:
        if a.force:
            write(out, compute(a.audio))
        else:
            ensure(a.audio, out)
    except (OSError, RuntimeError) as e:
        print(f"⚠ banga: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
