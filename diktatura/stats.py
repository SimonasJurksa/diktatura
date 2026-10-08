"""Diktatūra — statistikos nunulinimas (tik stdlib; naudoja Teksto skiltis).

„↺ Nunulinti" NIEKO netrina: įsimenamas laikas (<duomenys>/stats_reset.json), ir statistika (kas kiek kalbėjo)
skaičiuoja tik eilutes, pasakytas po jo. „Skaičiuoti viską" — laikas pamirštamas.
Eilutės laikas = sesijos (įrašo) pradžia + eilutės laikas nuo įrašo pradžios.
"""
import json
from datetime import datetime, timedelta

from diktatura import paths


def _file():
    return paths.DATA_DIR / "stats_reset.json"


def reset_time():
    """Nuo kada skaičiuojama statistika (datetime) arba None — nuo pradžių."""
    try:
        return datetime.fromisoformat(json.loads(_file().read_text(encoding="utf-8"))["since"])
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return None


def reset(now: datetime = None) -> datetime:
    """Nunulinti: skaičiuoti tik nuo dabar (tekstai lieka)."""
    when = (now or datetime.now()).replace(microsecond=0)
    _file().parent.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps({"since": when.isoformat()}), encoding="utf-8")
    return when


def clear() -> None:
    """Vėl skaičiuoti viską."""
    _file().unlink(missing_ok=True)


def line_time(session_start: datetime, offset_sec) -> datetime:
    return session_start + timedelta(seconds=offset_sec or 0)


def counts(start: datetime, offset_sec, since) -> bool:
    """Ar eilutė įeina į statistiką (pasakyta ne anksčiau nei nunulinta)."""
    return since is None or line_time(start, offset_sec) >= since
