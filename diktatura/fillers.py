"""Diktatūra — užpildų valymas be LLM (✨ „Švarus" Teksto rodinys, MCP clean=true). Tik stdlib.

Taisyklės (failai NEKEIČIAMI — valomas tik rodomas tekstas):
  1. šnekos garsai — visada: e, ee, ė, eh, ehm, em, mm, mhm, hm, aaa, uh, um (ne „e." — „e. paštas" lieka);
  2. vartotojo žodžiai (FILLER_WORDS, pvz. „nu,tipo") — kaip atskiri žodžiai;
  3. pasikartojimai: „aš aš aš manau" -> „aš manau", „aš manau aš manau" -> „aš manau";
  4. tvarka: likę kableliai / tarpai sutvarkomi, sakinio pradžia — didžiąja (jei tokia buvo).
Rezultatas tuščias -> eilutė švariame rodinyje nerodoma (buvo vien „mhm").
"""
import re

HESITATION = r"(?:e+|ė+|e+h+|e+h+m+|e+m+|m{2,}|m+h+m+|h+m+|a{3,}|u+h+m*|u+m+)"
_W = r"[^\W\d_]"                                  # raidė (be skaitmenų / „_")


def _rx(words) -> re.Pattern:
    alts = [HESITATION] + [re.escape(w) for w in words if w]
    return re.compile(rf"(?<![\w.-])(?:{'|'.join(alts)})(?![\w-])(?!\.\s*{_W})[,…]*", re.IGNORECASE)


_CACHE = {}


def parse_words(spec) -> tuple:
    """„nu, tipo,žinai" -> ("nu", "tipo", "žinai")."""
    if isinstance(spec, (list, tuple)):
        return tuple(w.strip().lower() for w in spec if w.strip())
    return tuple(w.strip().lower() for w in str(spec or "").split(",") if w.strip())


def clean(text: str, words=()) -> str:
    words = parse_words(words)
    rx = _CACHE.get(words) or _CACHE.setdefault(words, _rx(words))
    t = rx.sub(" ", text)
    for _ in range(2):                                                   # „aš aš aš" -> „aš"; dvižodžiai irgi
        t = re.sub(r"(?<!\w)(\w+)(?:[\s,]+\1)+(?!\w)", r"\1", t, flags=re.IGNORECASE)
        t = re.sub(r"(?<!\w)(\w+\s+\w+)(?:[\s,]+\1)+(?!\w)", r"\1", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*,(?:\s*,)+", ",", t)                               # „aš, , manau" -> „aš, manau"
    t = re.sub(r"\s+([,.!?…;:])", r"\1", t)
    t = re.sub(r",(?=[.!?…])", "", t)
    t = re.sub(r"^[\s,.;:…-]+", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    first = re.search(_W, text)
    if t and first and first.group().isupper() and t[0].islower():
        t = t[0].upper() + t[1:]
    return t
