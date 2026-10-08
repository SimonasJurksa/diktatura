"""Diktatūra — debug žurnalas (<state>/debug.log; tik stdlib).

Įjungiama: env DIKTATURA_DEBUG=1 (vienam paleidimui) arba nustatymas DEBUG=1 (Nustatymai → Debug).
DIKTATURA_DEBUG=0 išjungia net kai nustatymas įjungtas. Nustatymas perskaitomas ne dažniau kaip kas 5 s
(VOX kviečia kas 100 ms). Žurnalas sukamas: > 5 MB -> debug.log.1 (laikomas vienas senas).

Ką rašo: garso įrenginiai, lygiai ir VOX sprendimai, Slack srautai, kiekvieno failo kelias per pipeline,
modelio krovimo trukmė, RTF, kalbėtojų atitikimai (panašumas). Bash atitikmuo — `dbg` bin/common.sh.
"""
import datetime as dt
import os
import time

from diktatura import paths

MAX_BYTES = 5 * 1024 * 1024
_cache = [-1e9, False]


def enabled() -> bool:
    env = os.environ.get("DIKTATURA_DEBUG")
    if env is not None and env != "":
        return env in ("1", "true", "taip")
    now = time.monotonic()
    if now - _cache[0] > 5:
        try:
            from diktatura import config
            _cache[1] = bool(config.load()["DEBUG"])
        except Exception:
            _cache[1] = False
        _cache[0] = now
    return _cache[1]


def log(component: str, msg: str) -> None:
    if not enabled():
        return
    f = paths.LOG_DEBUG
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists() and f.stat().st_size > MAX_BYTES:
            os.replace(f, f.with_name(f.name + ".1"))
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"{dt.datetime.now():%F %T.%f}"[:-3] + f" [{component}] {msg}\n")
    except OSError:
        pass
