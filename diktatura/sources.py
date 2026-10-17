"""Diktatūra — sekami aplankai: telefono, laikrodžio, studijos mikrofono ir pan. įrašai (tik stdlib).

Vartotojas Nustatymuose nurodo aplankus, kuriuose kaupiasi garso failai (pvz. sinchronizuojami iš telefono). Nauji
failai transkribuojami pagal MODE (iškart — diktatura-sources.timer kas ~2 min; naktį — naktinis 01:30), o tekstai
laikomi ATSKIRAI — ne bendrame įrašų kataloge: <duomenys>/sources/<id>/. Teksto skiltyje kiekvienas aplankas — atskiras
skirtukas (savo tekstai, paieška, statistika, eksportas).

Tavo garso failai NIEKADA nekeičiami, netrinami ir nekopijuojami (bin/transcribe-file.sh <garsas> <išvesties bazė>).
Išvesties bazė = <duomenys>/sources/<id>/<failo vardas> (su poaplankiais — „poaplankis ⁄ failas"); šalia:
  <bazė>.named.txt   tekstas („[H:MM:SS] Kalbėtojas: tekstas" — kalbėtojai pagal balsus, tavo balsas — „Tu")
  <bazė>.peaks       🌊 banga;  <bazė>.skip — tuščias / be kalbos (nebetranskribuojama)
  <bazė>.src.json    {"audio": kelias, "recorded": ISO laikas, "source": id} — iš kur ir kada įrašyta
Įrašymo laikas: iš failo vardo (20261014_101500, 2026-10-14 10.15.00…), tada iš metaduomenų (ffprobe creation_time),
tada failo keitimo laikas.
Nustatymai: <config>/sources.json — [{"id", "name", "path", "enabled", "recursive", "since"}]; since — senesni failai
(buvę aplanke jį pridedant) ignoruojami, jei taip pasirinkta.
CLI:  python3 -m diktatura.sources list | pending | scan
  pending — „<garsas>\\t<išvesties bazė>" eilutės (naudoja bin/transcribe-pending.sh), prieš tai įrašo .src.json.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from diktatura import paths, sessions

AUDIO_EXT = {".m4a", ".mp3", ".wav", ".ogg", ".oga", ".opus", ".flac", ".aac", ".amr", ".3gp", ".wma", ".webm"}
PARTIAL = (".part", ".tmp", ".crdownload", ".partial", "~")
STABLE_SEC = 60.0            # failas dar sinchronizuojamas / rašomas, jei keistas vėliau
SUB_SEP = " ⁄ "              # poaplankio skyriklis išvesties varde (U+2044 — failo varde leidžiamas)
TEXT_SUFFIX = ".named.txt"
META_SUFFIX = ".src.json"
DONE_SUFFIXES = (TEXT_SUFFIX, ".skip")
NAME_TIME = re.compile(r"(?<!\d)(20\d\d)[-_.]?([01]\d)[-_.]?([0-3]\d)[ T_.-]?([0-2]\d)[-_.:hH]?([0-5]\d)[-_.:mM]?([0-5]\d)(?!\d)")


@dataclass
class Source:
    id: str
    name: str
    path: str
    enabled: bool = True
    recursive: bool = False
    since: float = 0.0               # > 0 — senesni failai ignoruojami

    @property
    def dir(self) -> Path:
        return Path(self.path).expanduser()

    @property
    def out_dir(self) -> Path:
        return paths.SOURCES_DATA / self.id


def conf_file() -> Path:
    return paths.SOURCES_CONF


def load() -> list:
    try:
        raw = json.loads(conf_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for d in raw if isinstance(raw, list) else []:
        try:
            out.append(Source(**{k: d[k] for k in Source.__dataclass_fields__ if k in d}))
        except TypeError:
            continue
    return out


def save(items: list) -> None:
    f = conf_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".sources.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump([asdict(s) for s in items], fh, ensure_ascii=False, indent=1)
    os.replace(tmp, f)


def short_path(path) -> str:
    """Rodymui: namų katalogas -> „~"."""
    p, home = str(path), str(Path.home())
    return "~" + p[len(home):] if p == home or p.startswith(home + "/") else p


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "aplankas"


def get(sid: str):
    return next((s for s in load() if s.id == sid), None)


def add(name: str, path, recursive: bool = False, include_existing: bool = True) -> Source:
    """Naujas sekamas aplankas. include_existing=False — jau esantys failai netranskribuojami (tik nauji)."""
    name = name.strip()
    p = Path(path).expanduser().resolve()
    if not name:
        raise ValueError("Nurodyk pavadinimą (pvz. Telefonas)")
    if not p.is_dir():
        raise ValueError(f"Nėra tokio aplanko: {p}")
    items = load()
    if any(Path(s.path).expanduser().resolve() == p for s in items):
        raise ValueError(f"Šis aplankas jau sekamas: {p}")
    if p == paths.RECORDINGS.resolve() or paths.DATA_DIR.resolve() in (p, *p.parents):
        raise ValueError("Diktatūros duomenų aplanko sekti negalima")
    base, sid, n = slug(name), slug(name), 2
    while any(s.id == sid for s in items):
        sid, n = f"{base}-{n}", n + 1
    src = Source(sid, name, str(p), True, bool(recursive), 0.0 if include_existing else time.time())
    save(items + [src])
    return src


def update(sid: str, **kw) -> Source:
    items = load()
    for s in items:
        if s.id == sid:
            for k, v in kw.items():
                if k in ("name", "enabled", "recursive"):
                    setattr(s, k, v)
            save(items)
            return s
    raise KeyError(sid)


def remove(sid: str) -> None:
    """Nebesekti (tekstai <duomenys>/sources/<id>/ lieka; tavo aplankas nepaliečiamas)."""
    save([s for s in load() if s.id != sid])


# ── failai ──

def is_audio(p: Path) -> bool:
    n = p.name
    return (p.suffix.lower() in AUDIO_EXT and not n.startswith(".") and not n.endswith(PARTIAL))


def scan(src: Source) -> list:
    """Garso failai aplanke (rikiuoti pagal keitimo laiką). Nepasiekiamas aplankas — tuščias sąrašas."""
    try:
        it = src.dir.rglob("*") if src.recursive else src.dir.iterdir()
        files = [p for p in it if is_audio(p) and p.is_file()]
    except OSError:
        return []
    out = []
    for p in files:
        try:
            out.append((p.stat().st_mtime, p))
        except OSError:
            continue
    return [p for _, p in sorted(out)]


def key_for(src: Source, audio: Path) -> str:
    try:
        rel = Path(audio).relative_to(src.dir)
    except ValueError:
        rel = Path(Path(audio).name)
    return SUB_SEP.join(rel.parts)


def out_base(src: Source, audio: Path) -> Path:
    """Išvesties bazė (be plėtinio): tekstas <bazė>.named.txt, banga <bazė>.peaks …"""
    return src.out_dir / key_for(src, audio)


def with_suffix(base: Path, suffix: str) -> Path:
    return base.with_name(base.name + suffix)


def is_done(base: Path) -> bool:
    return any(with_suffix(base, s).exists() for s in DONE_SUFFIXES)


def pending(src: Source, now: float = None) -> list:
    """[(garsas, išvesties bazė)] — be teksto ir be .skip, ne senesni už since, jau nebesikeičiantys."""
    now = time.time() if now is None else now
    if not src.enabled:
        return []
    out = []
    for a in scan(src):
        try:
            st = a.stat()
        except OSError:
            continue
        if src.since and st.st_mtime < src.since:
            continue
        if now - st.st_mtime < STABLE_SEC:
            continue                                   # dar sinchronizuojamas
        base = out_base(src, a)
        if not is_done(base):
            out.append((a, base))
    return out


def all_pending(now: float = None) -> list:
    return [pair for s in load() for pair in pending(s, now)]


def counts(src: Source) -> dict:
    """{"files", "texts", "pending"} — Nustatymų ir skirtuko suvestinei."""
    files = scan(src)
    texts = sum(1 for a in files if with_suffix(out_base(src, a), TEXT_SUFFIX).exists())
    return {"files": len(files), "texts": texts, "pending": len(pending(src))}


# ── laikas ir metaduomenys ──

def time_from_name(name: str):
    m = NAME_TIME.search(name)
    if not m:
        return None
    try:
        return datetime(*(int(x) for x in m.groups()))
    except ValueError:
        return None


def probe_created(audio: Path):
    """Įrašymo laikas iš garso metaduomenų (pvz. iPhone m4a creation_time) arba None."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time,date",
                              "-of", "default=nw=1:nk=1", str(audio)], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for ln in out.splitlines():
        ln = ln.strip()
        try:
            t = datetime.fromisoformat(ln.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is not None:
            t = t.astimezone().replace(tzinfo=None)      # vietinis laikas, kaip ir kitur
        if t.year >= 2000:
            return t
    return None


def recorded_time(audio: Path) -> datetime:
    return (time_from_name(Path(audio).name) or probe_created(audio)
            or datetime.fromtimestamp(Path(audio).stat().st_mtime))


def write_meta(src: Source, audio: Path, base: Path = None) -> Path:
    base = base or out_base(src, audio)
    f = with_suffix(base, META_SUFFIX)
    if f.exists():
        return f
    f.parent.mkdir(parents=True, exist_ok=True)
    data = {"audio": str(Path(audio).resolve()), "recorded": recorded_time(audio).isoformat(timespec="seconds"),
            "source": src.id}
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return f


def meta_for(text_or_base) -> dict:
    """Transkripcijos (ar bazės) .src.json arba {}."""
    p = Path(text_or_base)
    f = p.with_name(sessions.base_name(p.name) + META_SUFFIX)
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def source_of_audio(audio: Path):
    """(šaltinis, išvesties bazė), jei garsas — kurio nors sekamo aplanko; kitaip None."""
    a = Path(audio).resolve()
    for s in load():
        try:
            a.relative_to(s.dir.resolve())
        except ValueError:
            continue
        return s, out_base(s, a)
    return None


# ── CLI ──

def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "list"
    if cmd == "pending":
        for s in load():
            for a, base in pending(s):
                try:
                    write_meta(s, a, base)
                except OSError as e:
                    print(f"⚠ {a}: {e}", file=sys.stderr)
                    continue
                print(f"{a}\t{base}")
    elif cmd in ("list", "scan"):
        items = load()
        if not items:
            print("Sekamų aplankų nėra (Nustatymai → „Sekami aplankai\").")
        for s in items:
            c = counts(s)
            print(f"{'✓' if s.enabled else '·'} {s.name:<14} {s.path}  — failų {c['files']}, tekstų {c['texts']}, "
                  f"laukia {c['pending']}{'' if s.dir.is_dir() else '  ⚠ aplanko nėra'}")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
