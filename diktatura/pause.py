"""Diktatūra — įrašymo pauzė, kol Diktatūra PATI groja garsą (tik stdlib; naudoja UI ir VOX).

Problema: Apmokymų perklausa ar „▶ Groti nuo čia" skamba per kolonėles -> patenka į sistemos garso kanalą ->
VOX ją įrašytų kaip naują pokalbį, o transkripcija tą patį balsą vėl pridėtų prie nežinomų.
Sprendimas: grojantis UI kas ~1 s atnaujina failą <runtime>/pause su galiojimo laiku („neįrašinėti iki …");
VOX jį tikrina kas 0.5 s. Galiojimas trumpas (kelios sekundės) — jei UI nulūžtų, pauzė pasibaigia pati.
Sustabdžius grojimą paliekama trumpa uodega (garso buferiai / capture vėlinimas ~1 s).
"""
import json
import os
import tempfile
import time

from diktatura import paths

HOLD_SEC = 3.0         # kiek galioja vienas atnaujinimas (UI atnaujina kas ~1 s)
TAIL_SEC = 1.5         # po sustabdymo — kol kolonėlėse ir capture buferiuose dar skamba
_last_write = [0.0]


def _file():
    return paths.RUN_DIR / "pause"


def hold(seconds: float = HOLD_SEC, reason: str = "grojama perklausa", force: bool = False) -> None:
    """Neįrašinėti dar `seconds` s (dažnus kvietimus apriboja iki ~1 rašymo per sekundę)."""
    now = time.time()
    if not force and now - _last_write[0] < 1.0:
        return
    _last_write[0] = now
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".pause.")
    with os.fdopen(fd, "w") as fh:
        json.dump({"until": now + seconds, "reason": reason, "pid": os.getpid()}, fh)
    os.replace(tmp, f)


def release(tail: float = TAIL_SEC) -> None:
    """Grojimas baigtas: pauzė pasibaigs po trumpos uodegos."""
    hold(tail, "baigta groti", force=True)


def info():
    """{"until", "reason", "pid"} jei pauzė galioja, kitaip None."""
    try:
        d = json.loads(_file().read_text())
        return d if float(d.get("until", 0)) > time.time() else None
    except (FileNotFoundError, ValueError, TypeError):
        return None


def active() -> bool:
    return info() is not None
