"""Diktatūra — balsų saugykla (tik stdlib: naudoja ir UI per sistemos python3, ir .venv).

Failai (<duomenys>/speakers/, paths.SPEAKERS):
  enroll.json    {vardas: [embedding, ...]} — registruoti balsai (keli pavyzdžiai vienam vardui)
  pending/       nezN.wav + nezN.json {"embedding", "src", "added"} — nežinomi balsai, laukiantys vardo
  pending/.next  kitas nez numeris: id niekada nepanaudojami pakartotinai (seni tekstai nesumaišomi)
  ignored.json   [embedding, ...] — „ne žmogus / triukšmas": toks balsas į pending nebededamas
  assigned.json  {nezN: vardas | ""} — kam priskirtas buvęs nežinomas ("" = triukšmas). Transkripcija,
                 kuri vyko priskyrimo metu, pagal jį pasitaiso savo eilutes (resolve_labels).
  model.json     {"embedding_model", "since"} — KOKIU modeliu paskaičiuoti embedding'ai (skirtingų modelių vektoriai
                 nesulyginami; be žymės, bet su balsais = LEGACY_MODEL -> make speakers-migrate)
  owner.json     [{"embedding", "src", "added"}, ...] — TAVO balsas (paskutiniai OWNER_MAX pavyzdžių): jei kalbi
                 per kolegų kanalą (pvz. prisijungęs telefonu), tokios eilutės žymimos „Tu", o ne kolegos vardu.
  suggestions.json  laukiančių balsų pasiūlymai (💡 Apmokymuose) — rašo diktatura.speakers.suggest:
                 {"started", "voices" (voices_signature), "threshold", "margin", "suggest", "checked": [nezN],
                 "items": {nezN: {"name" ("" = triukšmas), "sim", "alt", "alt_sim", "strong", "basis", "lines"}}}
  profiles.json  {nezN: {"key", "embedding", "speech_sec"}} — balso „profilis" iš visų jo eilučių (suggest kešas)

Tekstuose nežinomas balsas žymimas „Kolega?nezN"; priskyrus vardą, VISOSE transkripcijose (įrašų kataloge IR
sekamų aplankų tekstuose <duomenys>/sources/<id>/ — transcript_files) „Kolega?nezN" -> vardas (rename_in_transcripts).
apply_assigned — tą patį padaro pagal assigned.json visiems tekstams (pataiso, ko priskyrimas nepasiekė: iki
2026-10-25 sekamų aplankų tekstai buvo praleidžiami). Embedding'ai čia — paprasti sąrašai (be numpy).
"""
import fcntl
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from diktatura import paths, sessions

UNKNOWN = "Kolega?"
SUGGEST_MARGIN = 0.05   # pasiūlymui: bent tiek panašesnis į siūlomą nei į antrą kandidatą (diktatura.speakers.suggest)
EMB_MODEL = "3dspeaker_campplus_zh_en_advanced"      # dabartinis balso modelis (failas — paths.EMB_MODEL_FILE)
LEGACY_MODEL = "3dspeaker_campplus_en_voxceleb"      # iki 2026-10-09 (tada žymės failo nebuvo)
ME = "Tu"               # tavo eilutės (L kanalas; R kanale — kai atpažintas tavo balsas)
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


# ── Balso modelis ──

def _model_file() -> Path:
    return paths.SPEAKERS / "model.json"


def has_voices() -> bool:
    return bool(load_enroll_raw() or load_ignored() or load_owner_raw() or list_pending())


def model_id():
    """Kokiu modeliu paskaičiuoti saugomi balsai: žymė; be žymės — LEGACY_MODEL, jei balsų yra; None — saugykla tuščia."""
    d = _read_json(_model_file(), {})
    if isinstance(d, dict) and d.get("embedding_model"):
        return d["embedding_model"]
    return LEGACY_MODEL if has_voices() else None


def compatible() -> bool:
    """Ar saugomi balsai sulyginami su dabartiniu modeliu (tuščia saugykla — taip)."""
    return model_id() in (None, EMB_MODEL)


def mark_model(model: str = EMB_MODEL) -> None:
    _atomic_write(_model_file(), json.dumps({"embedding_model": model,
                                             "since": datetime.now().isoformat(timespec="seconds")}))


def claim_model() -> None:
    """Prieš rašant NAUJO modelio embedding'ą: tuščiai saugyklai uždėti žymę; senam modeliui — klaida."""
    mid = model_id()
    if mid is None:
        mark_model()
    elif mid != EMB_MODEL:
        raise RuntimeError(f"balsai paskaičiuoti kitu modeliu ({mid}) — paleisk: make speakers-migrate")


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


# ── Tavo balsas ──

OWNER_MAX = 40          # seniausi pavyzdžiai išmetami (balsas / mikrofonas / telefonas keičiasi)


def load_owner_raw() -> list:
    d = _read_json(paths.SPEAKERS / "owner.json", [])
    return [o for o in d if isinstance(o, dict) and o.get("embedding")] if isinstance(d, list) else []


def owner_count() -> int:
    return len(load_owner_raw())


def add_owner(embedding, src: str = "") -> int:
    """Pridėti tavo balso pavyzdį; grąžina pavyzdžių skaičių."""
    d = load_owner_raw()
    d.append({"embedding": [float(x) for x in embedding], "src": src,
              "added": datetime.now().isoformat(timespec="seconds")})
    d = d[-OWNER_MAX:]
    _atomic_write(paths.SPEAKERS / "owner.json", json.dumps(d))
    return len(d)


def clear_owner() -> None:
    (paths.SPEAKERS / "owner.json").unlink(missing_ok=True)


def clean_name(name: str) -> str:
    """Vardas tekste stovi prieš „:" — dvitaškis ir naujos eilutės neleidžiami."""
    n = " ".join(str(name).replace(":", " ").split())
    if not n:
        raise ValueError("Vardas negali būti tuščias")
    if n.startswith(UNKNOWN):
        raise ValueError(f"Vardas negali prasidėti „{UNKNOWN}“")
    if n.casefold() == ME.casefold():
        raise ValueError(f"„{ME}“ — tavo balsas, ne kolegos vardas")
    return n


def is_me(name: str) -> bool:
    return " ".join(str(name).split()).casefold() == ME.casefold()


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
    """Naujas id: didesnis už bet kurį esamą ir už visus kada nors išduotus (pending/.next).
    Po flock: transkripcija ir `make speakers-relabel` gali kurti nežinomus balsus vienu metu."""
    paths.PENDING.mkdir(parents=True, exist_ok=True)
    with open(paths.PENDING / ".next", "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        try:
            nxt = int(fh.read().strip())
        except ValueError:
            nxt = 1
        used = [_pid_num(p.stem) for p in paths.PENDING.glob("nez*.json")]
        used += [_pid_num(k) for k in load_assigned()]
        n = max([nxt] + [u + 1 for u in used])
        fh.seek(0)
        fh.truncate()
        fh.write(str(n + 1))
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


def assign(pid: str, name: str, learn: bool = True) -> int:
    """Nežinomas balsas -> vardas: embedding į enroll.json, pending pašalinamas, tekstuose
    „Kolega?nezN" -> vardas. Vardas „Tu" -> tai tavo balsas (assign_owner). learn=False — balsas neišmokstamas
    (tik vardas tekstuose; pvz. priimant užtikrintus pasiūlymus). Grąžina pakeistų teksto eilučių skaičių."""
    if is_me(name):
        return assign_owner(pid, learn)
    name = clean_name(name)
    p = get_pending(pid)
    if learn:
        add_embedding(name, p.embedding)
    _remember_assigned(pid, name)
    _remove_pending(pid)
    return rename_in_transcripts(label_for(pid), name)


def assign_owner(pid: str, learn: bool = True) -> int:
    """Nežinomas balsas — tai TU (pvz. prisijungęs telefonu): embedding -> owner.json, tekstuose -> „Tu"."""
    p = get_pending(pid)
    if learn:
        add_owner(p.embedding, p.src)
    _remember_assigned(pid, ME)
    _remove_pending(pid)
    return rename_in_transcripts(label_for(pid), ME)


def assign_many(pairs) -> int:
    """Daug nežinomų iš karto [(nezN, vardas | "Tu" | "" = triukšmas)] — balsai NEišmokstami (užtikrinti pasiūlymai:
    tokius transkripcija ir pati atpažintų), tekstai perrašomi vienu perėjimu (apply_assigned).
    -> pakeistų teksto eilučių skaičius. Nebelaukiantys (jau priskirti) praleidžiami."""
    pend = {p.id for p in list_pending()}
    d = load_assigned()
    done = []
    for pid, name in pairs:
        if pid not in pend:
            continue
        d[pid] = ME if is_me(name) else (clean_name(name) if name else "")
        done.append(pid)
    if not done:
        return 0
    _atomic_write(paths.SPEAKERS / "assigned.json", json.dumps(d, ensure_ascii=False))
    for pid in done:
        _remove_pending(pid)
    return apply_assigned()


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


# ── Pasiūlymai (💡 Apmokymuose; skaičiuoja diktatura.speakers.suggest) ──

def suggestions_file() -> Path:
    return paths.SPEAKERS / "suggestions.json"


def load_suggestions(pending_ids=None) -> dict:
    """{nezN: {"name" ("" = triukšmas, „Tu" = tavo balsas), "sim", "alt", "alt_sim", "strong", "basis", "lines"}}
    — tik dar laukiantiems (pending_ids; None — visi faile)."""
    d = _read_json(suggestions_file(), {})
    items = d.get("items") if isinstance(d, dict) else None
    if not isinstance(items, dict):
        return {}
    return {k: v for k, v in items.items()
            if isinstance(v, dict) and "name" in v and (pending_ids is None or k in pending_ids)}


def voices_signature() -> dict:
    """Su kuo lyginama: registruoti balsai, tavo balsas, triukšmo pavyzdžiai — {failas: keitimo laikas ns | None}.
    Pasikeitus (ir ištrynus, pvz. „Ištrinti balsus") — pasiūlymai pasenę."""
    out = {}
    for name in ("enroll.json", "owner.json", "ignored.json"):
        try:
            out[name] = (paths.SPEAKERS / name).stat().st_mtime_ns
        except OSError:
            out[name] = None
    return out


def suggestions_stale(threshold: float, margin: float, suggest: float, pending_ids=None) -> bool:
    """Ar pasiūlymus reikia perskaičiuoti: nėra; kiti slenksčiai; nuo skaičiavimo pradžios pasikeitė (ar ištrinti)
    registruoti balsai / tavo balsas / triukšmo pavyzdžiai; atsirado dar netikrintų laukiančių."""
    d = _read_json(suggestions_file(), None)
    if not isinstance(d, dict):
        return True
    if [d.get("threshold"), d.get("margin"), d.get("suggest")] != [threshold, margin, suggest]:
        return True
    if d.get("voices") != voices_signature():
        return True
    ids = {p.id for p in list_pending()} if pending_ids is None else set(pending_ids)
    return bool(ids - set(d.get("checked") or ()))


# ── Transkripcijos ──

def transcript_files(rec_dir=None) -> list:
    """Visos rodomos transkripcijos: įrašų katalogas + sekamų aplankų tekstai (<duomenys>/sources/<id>/), sena -> nauja
    kiekviename kataloge. rec_dir — tik tas katalogas."""
    if rec_dir is not None:
        return sessions.text_files(Path(rec_dir))
    out = sessions.text_files(paths.RECORDINGS)
    if paths.SOURCES_DATA.is_dir():
        for d in sorted(paths.SOURCES_DATA.iterdir()):
            if d.is_dir():
                out += sessions.text_files(d)
    return out


def _speaker_re(label: str):
    return re.compile(r"^(\[\d+:\d\d:\d\d\]\s+)" + re.escape(label) + r"(?=:)", re.M)


def _rewrite_speakers(rx, repl, rec_dir=None) -> int:
    """Visose transkripcijose kalbėtojo vietą (rx: grupė 1 — „[laikas] ") perrašyti repl(m) -> naujas žymuo | None
    (None — nekeisti). Rašoma atomiškai, tik pasikeitę failai. -> pakeistų eilučių skaičius."""
    total = 0
    for f in transcript_files(rec_dir):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        n = 0

        def sub(m):
            nonlocal n
            new = repl(m)
            if new is None:
                return m.group(0)
            n += 1
            return m.group(1) + new
        new_text = rx.sub(sub, text)
        if n:
            _atomic_write(f, new_text)
            total += n
    return total


def rename_in_transcripts(old_label: str, new_label: str, rec_dir=None) -> int:
    """Visose rodomose transkripcijose (įrašų + sekamų aplankų) kalbėtoją old_label pakeisti new_label (tik kalbėtojo
    vietoje, ne tekste). Rašoma atomiškai. Grąžina pakeistų eilučių skaičių."""
    return _rewrite_speakers(_speaker_re(old_label), lambda m: new_label, rec_dir)


_PENDING_LABEL = re.compile(r"^(\[\d+:\d\d:\d\d\]\s+)" + re.escape(UNKNOWN) + r"(nez\d+)(?=:)", re.M)


def apply_assigned(rec_dir=None) -> int:
    """Jau priskirtus nežinomus (assigned.json) pritaikyti visiems tekstams: „Kolega?nezN" -> vardas / „Tu" /
    „Kolega?" (triukšmas). Pataiso tekstus, kurių priskyrimas nepasiekė (sekamų aplankų tekstai iki 2026-10-25;
    tekstas, kuris tuo metu buvo perrašomas). Dar laukiantys nekeičiami. -> pakeistų eilučių skaičius."""
    assigned = load_assigned()
    if not assigned:
        return 0
    waiting = {p.id for p in list_pending()}

    def repl(m):
        pid = m.group(2)
        if pid in waiting or pid not in assigned:
            return None
        return assigned[pid] or UNKNOWN
    return _rewrite_speakers(_PENDING_LABEL, repl, rec_dir)


def line_span(path, idx: int, max_sec: float = 20.0):
    """Eilutės laikas sekundėmis (pradžia, pabaiga): iki kitos eilutės su laiku (ne ilgiau max_sec). None — be laiko."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    p = sessions.parse_line(lines[idx]) if 0 <= idx < len(lines) else None
    if not p:
        return None
    t0 = sessions.ts_seconds(p[0])
    t1 = t0 + max_sec
    for ln in lines[idx + 1:]:
        q = sessions.parse_line(ln)
        if q and sessions.ts_seconds(q[0]) > t0:
            t1 = min(t1, sessions.ts_seconds(q[0]))
            break
    return float(t0), float(t1)


def relabel_line(path, idx: int, old: str, new: str) -> bool:
    """Vienos eilutės kalbėtojas old -> new (pataisymas tekste). False — eilutė jau kita (pasikeitė failas)."""
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        return False
    p = sessions.parse_line(lines[idx].rstrip("\n")) if 0 <= idx < len(lines) else None
    if not p or p[1] != old:
        return False
    nl = "\n" if lines[idx].endswith("\n") else ""
    lines[idx] = f"[{p[0]}] {new}: {p[2]}{nl}"
    _atomic_write(path, "".join(lines))
    return True


def text_speakers(rec_dir=None) -> set:
    """Vardai, kurie yra tekstuose (be „Tu" ir „Kolega?…") — vardų užbaigimui Apmokymuose."""
    out = set()
    for f in transcript_files(rec_dir):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ln in text.splitlines():
            p = sessions.parse_line(ln)
            if p and p[1] != ME and not p[1].startswith(UNKNOWN):
                out.add(p[1])
    return out


def occurrences(label: str, rec_dir=None, with_idx: bool = False) -> list:
    """Kur kalbėjo šis kalbėtojas (įrašų ir sekamų aplankų tekstuose): [(transkripcijos failas, „H:MM:SS", tekstas)],
    sena -> nauja; with_idx — dar ir eilutės nr. faile (4-as elementas: grojimui su kontekstu, line_span)."""
    return occurrences_many([label], rec_dir, with_idx)[label]


def occurrences_many(labels, rec_dir=None, with_idx: bool = False) -> dict:
    """Kaip occurrences, bet keliems kalbėtojams vienu failų perėjimu: {label: [(failas, laikas, tekstas[, nr.])]}."""
    want = set(labels)
    out = {lb: [] for lb in labels}
    for f in transcript_files(rec_dir):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines):
            p = sessions.parse_line(ln)
            if p and p[1] in want:
                out[p[1]].append((f, p[0], p[2], i) if with_idx else (f, p[0], p[2]))
    return out
