"""Diktatūra — dialogo surinkimas iš stereo transkripcijos (grynos funkcijos, tik stdlib).

De-dup: ausinių mikrofonas pagauna kolegų garsą (nutekėjimas į kairį kanalą). Kadangi tavo balso
dešiniame (sistemos) kanale niekada nėra, „Tu" eilutė, kurios dauguma žodžių laike sutampa su kolegų
eilutėmis, yra nutekėjimas ir išmetama. Trumpos reakcijos (< min_words žodžių) visada paliekamos.
"""
import datetime as dt
import re

WORD = re.compile(r"\w+")


def hhmmss(sec: float) -> str:
    return str(dt.timedelta(seconds=int(sec)))


def words(text: str) -> list:
    """Žodžiai mažosiomis, be vienraidžių (jie per dažni palyginimui)."""
    return [w for w in WORD.findall(text.lower()) if len(w) > 1]


def overlaps(a0: float, a1: float, b0: float, b1: float, slack: float = 2.0) -> bool:
    return (a0 - slack) < b1 and (b0 - slack) < a1


def dedup(me, others, me_label="Tu", slack=2.0, min_words=3, min_frac=0.6):
    """me: [(start, end, tekstas)] — tavo (L) segmentai; others: [(start, end, kas, tekstas)] — kolegų (R).
    Grąžina (eilutės [(start, end, kas, tekstas)] surikiuotos pagal laiką, išmestų „Tu" segmentų skaičius)."""
    rows = list(others)
    dropped = 0
    for st, en, tx in me:
        mw = words(tx)
        near = set()
        for ts, te, _, tt in others:
            if overlaps(st, en, ts, te, slack):
                near.update(words(tt))
        frac = (sum(1 for w in mw if w in near) / len(mw)) if mw else 0.0
        if len(mw) >= min_words and frac >= min_frac:
            dropped += 1
        else:
            rows.append((st, en, me_label, tx))
    rows.sort(key=lambda r: r[0])
    return rows, dropped


def format_rows(rows) -> str:
    """[(start, end, kas, tekstas)] -> „[H:MM:SS] kas: tekstas" eilutės (failo turinys)."""
    return "".join(f"[{hhmmss(st)}] {who}: {tx}\n" for st, _en, who, tx in rows)
