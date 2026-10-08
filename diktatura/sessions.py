"""Diktatūra — įrašų sesijos: failų vardai, datos ir transkripcijų eilutės (grynos funkcijos, tik stdlib).

Įrašo vardas: <šaltinis>_YYYYMMDD_HHMMSS.<plėtinys>, šaltinis ∈ {vox, slack, rec}.
Transkripcijos šalia garso: <bazė>.named.txt (stereo, su vardais), <bazė>.txt (mono),
<bazė>.clean.dialog.txt (senas formatas; grynas .dialog.txt nerodomas).
Transkripcijos eilutė: „[H:MM:SS] Kalbėtojas: tekstas" (laikas — nuo įrašo pradžios).

Naudoja ir UI (sistemos python3), ir .venv — todėl tik stdlib.
"""
import re
from datetime import datetime
from pathlib import Path

SOURCES = ("vox", "slack", "rec")
NAME_TS = re.compile(r"(vox|slack|rec)_(\d{8})_(\d{6})")
LINE = re.compile(r"^\[(\d+:\d\d:\d\d)\]\s+([^:]+):\s*(.*)$")
# Transkripcijų plėtiniai (ilgiausi pirmi — kad „x.named.txt" nebūtų palaikytas „x.named" + „.txt")
TEXT_SUFFIXES = (".clean.dialog.txt", ".named.txt", ".dialog.txt", ".txt")
AUDIO_SUFFIXES = (".wav", ".mp3")


def parse_name(name: str):
    """'vox_20261008_143000.named.txt' -> ('vox', datetime(2026, 10, 8, 14, 30)); netinkamas -> None."""
    m = NAME_TS.search(name)
    if not m:
        return None
    try:
        return m.group(1), datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def session_dt(path: Path) -> datetime:
    """Įrašymo laikas iš failo vardo; jei vardas nestandartinis — failo keitimo laikas."""
    p = parse_name(Path(path).name)
    if p:
        return p[1]
    return datetime.fromtimestamp(Path(path).stat().st_mtime)


def base_name(name: str) -> str:
    """'vox_x.named.txt' -> 'vox_x'; 'vox_x.wav' -> 'vox_x' (žinomi plėtiniai nuimami)."""
    for suf in TEXT_SUFFIXES + AUDIO_SUFFIXES + (".srt", ".skip"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def is_display_text(name: str) -> bool:
    """Ar transkripcija rodoma teksto lange: .named.txt, mono .txt, .clean.dialog.txt (ne grynas .dialog.txt)."""
    if not name.endswith(".txt"):
        return False
    return not (name.endswith(".dialog.txt") and not name.endswith(".clean.dialog.txt"))


def text_files(rec_dir: Path, since=None) -> list:
    """Rodomos transkripcijos kataloge, rikiuotos pagal įrašymo laiką (sena -> nauja).
    since: date — tik nuo šios dienos (imtinai)."""
    out = []
    for f in Path(rec_dir).glob("*.txt"):
        if not is_display_text(f.name):
            continue
        try:
            when = session_dt(f)
        except OSError:
            continue
        if since is None or when.date() >= since:
            out.append((when, f))
    return [f for _, f in sorted(out)]


def audio_for(text_path: Path):
    """Transkripcijos garsas (wav pirmenybė, tada mp3 archyvas) arba None."""
    text_path = Path(text_path)
    base = text_path.parent / base_name(text_path.name)
    for suf in AUDIO_SUFFIXES:
        a = base.with_name(base.name + suf)
        if a.exists():
            return a
    return None


def parse_line(raw: str):
    """'[0:01:02] Jonas: labas' -> ('0:01:02', 'Jonas', 'labas'); kita -> None."""
    m = LINE.match(raw)
    if not m:
        return None
    return m.group(1), m.group(2).strip(), m.group(3)


def ts_seconds(ts: str) -> int:
    """'1:02:03' -> 3723."""
    h, m, s = (int(x) for x in ts.split(":"))
    return h * 3600 + m * 60 + s


def speaker_stats(rows, max_turn: float = 60.0, words_per_sec: float = 2.5) -> dict:
    """Kas kiek kalbėjo. rows: [(sesijos raktas, laikas s | None, kalbėtojas, tekstas)] laiko tvarka.
    Eilutės trukmė ≈ iki kitos eilutės toje sesijoje (ne daugiau max_turn); paskutinė / be laiko — pagal žodžius.
    -> {kalbėtojas: {"lines": n, "words": n, "seconds": s}} (be kalbėtojo eilutės — „—")."""
    out = {}
    rows = list(rows)
    for i, (sess, t, spk, text) in enumerate(rows):
        words = len(text.split())
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if t is not None and nxt is not None and nxt[0] == sess and nxt[1] is not None and nxt[1] >= t:
            sec = min(nxt[1] - t, max_turn)
        else:
            sec = min(words / words_per_sec, max_turn)
        s = out.setdefault(spk or "—", {"lines": 0, "words": 0, "seconds": 0.0})
        s["lines"] += 1
        s["words"] += words
        s["seconds"] += sec
    return out
