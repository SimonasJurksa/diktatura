"""Diktatūra — visų transkripcijų skaitymas be GTK (MCP serveriui ir CLI). Tik stdlib.

Šaltiniai: „pokalbiai" — <duomenys>/recordings (VOX / Slack / rankiniai įrašai) ir sekami aplankai
(<duomenys>/sources/<id>/, diktatura.sources). Sesija = vienas tekstas; eilutė — (laikas s | None, kalbėtojas, tekstas).
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from diktatura import fillers, paths, sessions

MAIN = "pokalbiai"


@dataclass
class Line:
    ts: str
    speaker: str
    text: str

    @property
    def seconds(self):
        return sessions.ts_seconds(self.ts) if self.ts else None


@dataclass
class Sess:
    path: Path
    when: datetime
    source: str                     # „pokalbiai" arba sekamo aplanko id
    kind: str                       # VOX / SLACK / REC / aplanko pavadinimas
    lines: list = field(default_factory=list)

    @property
    def id(self) -> str:
        b = sessions.base_name(self.path.name)
        return b if self.source == MAIN else f"{self.source}/{b}"

    @property
    def speakers(self) -> list:
        seen = []
        for ln in self.lines:
            if ln.speaker and ln.speaker not in seen:
                seen.append(ln.speaker)
        return seen

    @property
    def length(self) -> str:
        secs = [ln.seconds for ln in self.lines if ln.seconds is not None]
        if not secs:
            return ""
        m, s = divmod(max(secs), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"


def read_lines(path: Path) -> list:
    out = []
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for r in raw.splitlines():
        if not r.strip():
            continue
        p = sessions.parse_line(r)
        out.append(Line(*p) if p else Line("", "", r.strip()))
    return out


def _dirs(source: str = None) -> list:
    """[(šaltinio id, katalogas, pavadinimas)] pagal filtrą: None / „all" — visi; „pokalbiai"; aplanko id ar vardas."""
    from diktatura import sources
    out = [(MAIN, paths.RECORDINGS, "")]
    for s in sources.load():
        out.append((s.id, s.out_dir, s.name))
    if source in (None, "", "all", "visi"):
        return out
    want = source.casefold()
    return [d for d in out if d[0].casefold() == want or d[2].casefold() == want
            or (d[0] == MAIN and want in ("pokalbiai", "įrašai", "irasai", "recordings"))]


def load_sessions(since: date = None, until: date = None, source: str = None) -> list:
    """Sesijos (sena -> nauja) su eilutėmis; since / until — datos imtinai."""
    out = []
    for sid, d, name in _dirs(source):
        if not d.exists():
            continue
        for f in sessions.text_files(d, since):
            when = sessions.session_dt(f)
            if until is not None and when.date() > until:
                continue
            parsed = sessions.parse_name(f.name)
            kind = parsed[0].upper() if parsed and sid == MAIN else (name or "")
            out.append(Sess(f, when, sid, kind, read_lines(f)))
    return sorted(out, key=lambda s: (s.when, s.path.name))


def find_session(sid: str):
    """„vox_20261014_101500" (pokalbiai; jei nėra — bet kuris šaltinis) arba „telefonas/Įrašas 7.m4a" -> Sess | None."""
    src, _, base = sid.strip().rpartition("/")
    cands = [s for s in load_sessions(source=src or MAIN) if sessions.base_name(s.path.name) == base]
    if not cands and not src:
        cands = [s for s in load_sessions() if sessions.base_name(s.path.name) == base]
    return cands[0] if cands else None


def search(query: str, regex: bool = False, since=None, until=None, speaker: str = None, source: str = None,
           limit: int = 50, clean: bool = False):
    """-> ([(sesija, eilutė)], viso rasta). Be didžiųjų / mažųjų raidžių skirtumo."""
    rx = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    hits, total = [], 0
    for s in load_sessions(since, until, source):
        for ln in s.lines:
            if speaker and ln.speaker.casefold() != speaker.casefold():
                continue
            text = fillers.clean(ln.text) if clean else ln.text
            if rx.search(text) or rx.search(ln.speaker or ""):
                total += 1
                if len(hits) < limit:
                    hits.append((s, Line(ln.ts, ln.speaker, text)))
    return hits, total


def format_line(ln: Line, clean: bool = False, words=()) -> str:
    text = fillers.clean(ln.text, words) if clean else ln.text
    return (f"[{ln.ts}] " if ln.ts else "") + (f"{ln.speaker}: " if ln.speaker else "") + text


def stats(sess: list) -> dict:
    rows = [(id(s), ln.seconds, ln.speaker, ln.text) for s in sess for ln in s.lines]
    return sessions.speaker_stats(rows)


def parse_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    v = str(v).strip().lower()
    today = date.today()
    if v in ("šiandien", "today"):
        return today
    if v in ("vakar", "yesterday"):
        return date.fromordinal(today.toordinal() - 1)
    return date.fromisoformat(v)
