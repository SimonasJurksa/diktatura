"""Diktatūra — duomenų išvalymas „pradėti kaupti iš naujo" (tik stdlib; naudoja Nustatymų langas).

Kategorijos (renkasi vartotojas):
  RECORDINGS — įrašai ir tekstai: viskas <duomenys>/recordings/ (garsas, transkripcijos, .srt, .skip, bench/…),
               žymės ⭐/☐ (annotations.json), statistikos nunulinimas (stats_reset.json), backup/ (tekstų kopijos).
  PENDING    — nežinomi balsai, laukiantys vardo (speakers/pending/nez*.wav|json). pending/.next lieka — nezN numeriai
               nekartojami.
  VOICES     — vardų atpažinimas: registruoti balsai (enroll.json), tavo balsas (owner.json), „ne žmogus" (ignored.json),
               seni balsų archyvai (speakers/legacy-*).
Niekada netrinama: nustatymai, modeliai, logai, speakers/model.json ir assigned.json, DABAR rašomas įrašas ir DABAR
transkribuojamas failas (su jų tekstais) — kitaip transkripcija po valymo „atgaivintų" seną tekstą.
"""
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from diktatura import paths, sessions

RECORDINGS, PENDING, VOICES = "recordings", "pending", "voices"
CATEGORIES = (RECORDINGS, PENDING, VOICES)


@dataclass
class Item:
    count: int = 0
    size: int = 0
    targets: list = field(default_factory=list)


def _size(p: Path) -> int:
    try:
        if p.is_dir():
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        return p.stat().st_size
    except OSError:
        return 0


def running_transcriptions() -> list:
    """Dabar transkribuojami / archyvuojami failai (diktatura.asr.* ir wav->mp3 ffmpeg procesų argumentai)."""
    try:
        out = subprocess.run(["pgrep", "-af", r"diktatura\.asr\.transcribe|libmp3lame"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for ln in out.splitlines():
        for arg in ln.split()[1:]:
            if re.search(r"\.(wav|mp3)$", arg):
                found.append(Path(arg))
    return found


def busy_bases() -> set:
    """Įrašų „bazės" (vox_YYYYMMDD_HHMMSS), kurių liesti negalima: rašomas ir transkribuojamas."""
    out = set()
    try:
        parts = paths.STATE_RECORDING.read_text().split(maxsplit=1)
        if len(parts) == 2:
            out.add(sessions.base_name(Path(parts[1].strip()).name))
    except OSError:
        pass
    out.update(sessions.base_name(p.name) for p in running_transcriptions())
    return out


def plan(busy=None) -> dict:
    """{kategorija: Item(kiek, baitų, ką trinti)} + "kept": [palikti failai]."""
    busy = busy_bases() if busy is None else busy
    res = {c: Item() for c in CATEGORIES}
    kept = []
    rec = res[RECORDINGS]
    if paths.RECORDINGS.exists():
        for p in sorted(paths.RECORDINGS.iterdir()):
            if p.is_file() and sessions.base_name(p.name) in busy:
                kept.append(p)
                continue
            rec.targets.append(p)
    for p in (paths.DATA_DIR / "annotations.json", paths.DATA_DIR / "stats_reset.json", paths.DATA_DIR / "backup"):
        if p.exists():
            rec.targets.append(p)
    rec.count = sum(1 for p in rec.targets if p.parent == paths.RECORDINGS and p.is_file())
    if paths.PENDING.exists():
        pend = res[PENDING]
        pend.targets = sorted(p for p in paths.PENDING.glob("nez*") if p.suffix in (".wav", ".json"))
        pend.count = len({p.stem for p in pend.targets})
    voices = res[VOICES]
    for name in ("enroll.json", "owner.json", "ignored.json"):
        if (paths.SPEAKERS / name).exists():
            voices.targets.append(paths.SPEAKERS / name)
    voices.targets += sorted(paths.SPEAKERS.glob("legacy-*")) if paths.SPEAKERS.exists() else []
    from diktatura.speakers import store
    voices.count = len(store.counts()) + (1 if store.owner_count() else 0)
    for item in res.values():
        item.size = sum(_size(p) for p in item.targets)
    res["kept"] = kept
    return res


def run(categories, busy=None) -> dict:
    """Ištrinti pasirinktas kategorijas. -> {"deleted": {kategorija: kiek}, "kept": [failai], "errors": [...]}."""
    unknown = set(categories) - set(CATEGORIES)
    if unknown:
        raise ValueError(f"nežinomos kategorijos: {sorted(unknown)}")
    p = plan(busy)
    deleted, errors = {}, []
    for cat in categories:
        for t in p[cat].targets:
            try:
                if t.is_dir():
                    shutil.rmtree(t)
                else:
                    t.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                errors.append(f"{t.name}: {e}")
        deleted[cat] = p[cat].count
    return {"deleted": deleted, "kept": p["kept"], "errors": errors}


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
