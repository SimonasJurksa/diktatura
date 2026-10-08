"""Diktatūra — balsų saugykla (tik stdlib: naudoja ir UI per sistemos python3, ir .venv).

Failai (<duomenys>/speakers/, paths.SPEAKERS):
  enroll.json    {vardas: [embedding, ...]} — registruoti balsai (keli pavyzdžiai vienam vardui)
  pending/       nezN.wav + nezN.json {"embedding", "src", "added"} — nežinomi balsai, laukiantys vardo
  pending/.next  kitas nez numeris: id niekada nepanaudojami pakartotinai (seni tekstai nesumaišomi)
  ignored.json   [embedding, ...] — „ne žmogus / triukšmas": toks balsas į pending nebededamas
  assigned.json  {nezN: vardas | ""} — kam priskirtas buvęs nežinomas ("" = triukšmas). Transkripcija,
                 kuri vyko priskyrimo metu, pagal jį pasitaiso savo eilutes (resolve_labels).

Tekstuose nežinomas balsas žymimas „Kolega?nezN"; priskyrus vardą, visose transkripcijose
„Kolega?nezN" -> vardas (rename_in_transcripts). Embedding'ai čia — paprasti sąrašai (be numpy).
"""
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from diktatura import paths, sessions

UNKNOWN = "Kolega?"
PID = re.compile(r"^nez(\d+)$")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


# ── Registruoti balsai ──

def load_enroll_raw() -> dict:
    return _read_json(paths.ENROLL, {})


def save_enroll_raw(store: dict) -> None:
    _atomic_write(paths.ENROLL, json.dumps(store))


def names() -> list:
    return sorted(load_enroll_raw(), key=str.casefold)


def counts() -> dict:
    """{vardas: pavyzdžių skaičius}"""
    return {k: len(v) for k, v in load_enroll_raw().items()}


def add_embedding(name: str, embedding) -> int:
    name = clean_name(name)
    store = load_enroll_raw()
    store.setdefault(name, []).append([float(x) for x in embedding])
    save_enroll_raw(store)
    return len(store[name])


def clean_name(name: str) -> str:
    """Vardas tekste stovi prieš „:" — dvitaškis ir naujos eilutės neleidžiami."""
    n = " ".join(str(name).replace(":", " ").split())
    if not n:
        raise ValueError("Vardas negali būti tuščias")
    if n.startswith(UNKNOWN):
        raise ValueError(f"Vardas negali prasidėti „{UNKNOWN}“")
    return n


# ── Nežinomi balsai (pending) ──

@dataclass
class PendingVoice:
    id: str
    wav: Path
    src: str
    added: str
    embedding: list

    @property
    def label(self) -> str:
        return label_for(self.id)


def label_for(pid: str) -> str:
    return f"{UNKNOWN}{pid}"


def _pid_num(pid: str) -> int:
    m = PID.match(pid)
    return int(m.group(1)) if m else -1


def list_pending() -> list:
    out = []
    for j in paths.PENDING.glob("nez*.json"):
        d = _read_json(j, None)
        if not isinstance(d, dict) or "embedding" not in d:
            continue
        out.append(PendingVoice(j.stem, j.with_suffix(".wav"), d.get("src", ""), d.get("added", ""), d["embedding"]))
    return sorted(out, key=lambda p: _pid_num(p.id))


def pending_count() -> int:
    return sum(1 for _ in paths.PENDING.glob("nez*.json")) if paths.PENDING.exists() else 0


def next_pending_id() -> str:
    """Naujas id: didesnis už bet kurį esamą ir už visus kada nors išduotus (pending/.next)."""
    paths.PENDING.mkdir(parents=True, exist_ok=True)
    counter = paths.PENDING / ".next"
    try:
        nxt = int(counter.read_text().strip())
    except (FileNotFoundError, ValueError):
        nxt = 1
    used = [_pid_num(p.stem) for p in paths.PENDING.glob("nez*.json")]
    used += [_pid_num(k) for k in load_assigned()]
    n = max([nxt] + [u + 1 for u in used])
    counter.write_text(str(n + 1))
    return f"nez{n}"


def write_pending_meta(pid: str, embedding, src: str) -> None:
    _atomic_write(paths.PENDING / f"{pid}.json", json.dumps({
        "embedding": [float(x) for x in embedding], "src": src,
        "added": datetime.now().isoformat(timespec="seconds")}))


def get_pending(pid: str) -> PendingVoice:
    for p in list_pending():
        if p.id == pid:
            return p
    raise KeyError(f"Nėra nežinomo balso {pid}")


def _remove_pending(pid: str) -> None:
    for ext in (".wav", ".json"):
        (paths.PENDING / f"{pid}{ext}").unlink(missing_ok=True)


# ── Priskyrimai ──

def load_assigned() -> dict:
    return _read_json(paths.SPEAKERS / "assigned.json", {})


def _remember_assigned(pid: str, name: str) -> None:
    d = load_assigned()
    d[pid] = name
    _atomic_write(paths.SPEAKERS / "assigned.json", json.dumps(d, ensure_ascii=False))


def load_ignored() -> list:
    return _read_json(paths.SPEAKERS / "ignored.json", [])


def assign(pid: str, name: str) -> int:
    """Nežinomas balsas -> vardas: embedding į enroll.json, pending pašalinamas, tekstuose
    „Kolega?nezN" -> vardas. Grąžina pakeistų teksto eilučių skaičių."""
    name = clean_name(name)
    p = get_pending(pid)
    add_embedding(name, p.embedding)
    _remember_assigned(pid, name)
    _remove_pending(pid)
    return rename_in_transcripts(label_for(pid), name)


def discard(pid: str, remember: bool = True) -> int:
    """„Ne žmogus / triukšmas": pavyzdys ištrinamas, enroll nekinta; remember -> panašus garsas
    ateityje nebededamas į pending. Tekstuose „Kolega?nezN" -> „Kolega?"."""
    p = get_pending(pid)
    if remember:
        ign = load_ignored()
        ign.append([float(x) for x in p.embedding])
        _atomic_write(paths.SPEAKERS / "ignored.json", json.dumps(ign))
    _remember_assigned(pid, "")
    _remove_pending(pid)
    return rename_in_transcripts(label_for(pid), UNKNOWN)


def rename_speaker(old: str, new: str) -> int:
    """Pervadinti registruotą balsą; jei naujas vardas jau yra — sujungti (pvz. „Ruta" -> „Rūta").
    Tekstuose senas vardas pakeičiamas nauju. Grąžina pakeistų eilučių skaičių."""
    new = clean_name(new)
    store = load_enroll_raw()
    if old not in store:
        raise KeyError(f"Nėra registruoto balso „{old}“")
    if old == new:
        return 0
    store.setdefault(new, []).extend(store.pop(old))
    save_enroll_raw(store)
    return rename_in_transcripts(old, new)


def delete_speaker(name: str) -> None:
    store = load_enroll_raw()
    if store.pop(name, None) is None:
        raise KeyError(f"Nėra registruoto balso „{name}“")
    save_enroll_raw(store)


def resolve_labels(rows):
    """[(st, en, kas, tekstas)] -> tas pats, bet „Kolega?nezN", kurie jau priskirti, pakeisti vardu
    (transkripcija galėjo vykti tuo metu, kai vartotojas priskyrė vardą)."""
    assigned = load_assigned()
    out = []
    for st, en, who, tx in rows:
        if who.startswith(UNKNOWN) and who[len(UNKNOWN):] in assigned:
            who = assigned[who[len(UNKNOWN):]] or UNKNOWN
        out.append((st, en, who, tx))
    return out


# ── Transkripcijos ──

def _speaker_re(label: str):
    return re.compile(r"^(\[\d+:\d\d:\d\d\]\s+)" + re.escape(label) + r"(?=:)", re.M)


def rename_in_transcripts(old_label: str, new_label: str, rec_dir=None) -> int:
    """Visose rodomose transkripcijose kalbėtoją old_label pakeisti new_label (tik kalbėtojo vietoje,
    ne tekste). Rašoma atomiškai. Grąžina pakeistų eilučių skaičių."""
    rx = _speaker_re(old_label)
    total = 0
    for f in Path(rec_dir or paths.RECORDINGS).glob("*.txt"):
        if not sessions.is_display_text(f.name):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new, n = rx.subn(lambda m: m.group(1) + new_label, text)
        if n:
            _atomic_write(f, new)
            total += n
    return total


def occurrences(label: str, rec_dir=None) -> list:
    """Kur kalbėjo šis kalbėtojas: [(transkripcijos failas, „H:MM:SS", tekstas)], sena -> nauja."""
    return occurrences_many([label], rec_dir)[label]


def occurrences_many(labels, rec_dir=None) -> dict:
    """Kaip occurrences, bet keliems kalbėtojams vienu failų perėjimu: {label: [(failas, laikas, tekstas)]}."""
    want = set(labels)
    out = {lb: [] for lb in labels}
    for f in sessions.text_files(Path(rec_dir or paths.RECORDINGS)):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for ln in lines:
            p = sessions.parse_line(ln)
            if p and p[1] in want:
                out[p[1]].append((f, p[0], p[2]))
    return out
