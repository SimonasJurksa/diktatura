"""Diktatūra — nustatymai.

Numatytųjų REIKŠMIŲ šaltinis — config/diktatura.conf.default (versijuojama).
Vartotojo nustatymai — ~/.config/diktatura/diktatura.conf (perrašo numatytuosius).
SCHEMA aprašo tipą, ribas, grupę ir lietuvišką paaiškinimą (naudoja Nustatymų langas ir validacija).
Testas užtikrina, kad SCHEMA raktai == numatytųjų failo raktai.

Tik stdlib (importuoja ir sistemos python3 UI). Bash įsikelia tą patį failą per `.` (bin/common.sh).
"""
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from typing import Optional

from . import paths

LINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*([^#\s]*)")


@dataclass(frozen=True)
class Setting:
    key: str
    kind: str                       # int | float | bool | choice
    group: str
    label: str
    help: str = ""
    lo: Optional[float] = None
    hi: Optional[float] = None
    choices: tuple = ()
    choice_labels: tuple = ()       # žmogui (Nustatymų langui), ta pačia tvarka kaip choices
    step: Optional[float] = None    # Nustatymų lango žingsnis (+/-)

    def choice_label(self, value: str) -> str:
        return dict(zip(self.choices, self.choice_labels)).get(value, value)


SCHEMA = (
    # ── Įrašymas ──
    Setting("VOX_SILENCE_SEC", "float", "Įrašymas", "Tylos sekundės iki failo uždarymo",
            "Kiek sekundžių tylos reikia, kad VOX užbaigtų įrašą. Diktavimui ~5, pokalbiams 30–60.", 1, 600),
    Setting("VOX_MIN_SEC", "float", "Įrašymas", "Mažiausia įrašo trukmė",
            "Trumpesni įrašai (kosulys, spragtelėjimas) ištrinami.", 0.2, 30),
    Setting("VOX_ADAPTIVE", "bool", "Įrašymas", "Adaptyvus jautrumas",
            "Slenkstis = kambario triukšmas + atsarga (prisitaiko prie mikrofono lygio)."),
    Setting("VOX_OPEN_MARGIN", "float", "Įrašymas", "Pradžios atsarga (dB virš triukšmo)",
            "Didesnė reikšmė = reikia garsiau kalbėti, kad įrašas prasidėtų.", 3, 40),
    Setting("VOX_CLOSE_MARGIN", "float", "Įrašymas", "Išlaikymo atsarga (dB virš triukšmo)",
            "Mažesnė reikšmė = tyli kalba nenutraukia įrašo. Turi būti mažesnė už pradžios atsargą.", 1, 30),
    Setting("VOX_GATE_DB", "float", "Įrašymas", "Fiksuotas slenkstis (dBFS)",
            "Naudojamas tik kai adaptyvus jautrumas išjungtas.", -80, -5),
    Setting("SLACK_GRACE_SEC", "float", "Įrašymas", "Slack: laukimas po skambučio (s)",
            "Kiek sekundžių be Slack garso srauto, kol įrašas sustabdomas.", 1, 120),
    Setting("MAX_REC_SEC", "int", "Įrašymas", "Didžiausia įrašo trukmė (s)",
            "Saugiklis, jei skambutis paliktas atidarytas.", 60, 86400, step=60),
    # ── Transkripcija ──
    Setting("AUTOTRANSCRIBE", "bool", "Transkripcija", "Transkribuoti automatiškai",
            "Išjungus — tik įrašoma, tekstas negaminamas."),
    Setting("MODE", "choice", "Transkripcija", "Kada transkribuoti",
            "immediate — iškart po įrašo; deferred — naktį 01:30 (mažiau trukdo darbui).",
            choices=("immediate", "deferred"), choice_labels=("Iškart po įrašo", "Naktį 01:30")),
    Setting("MODEL", "choice", "Transkripcija", "Modelis",
            "azuolas-ct2 — geriausia lietuvių kalbos kokybė; medium — greičiau ir mažiau RAM.",
            choices=("azuolas-ct2", "medium"),
            choice_labels=("Ąžuolas — geriausia LT kokybė", "Whisper medium — greičiau, mažiau RAM")),
    Setting("THREADS", "int", "Transkripcija", "CPU gijos", "Daugiau = greičiau, bet labiau apkrauna kompiuterį.", 1, 32),
    Setting("ASR_SERVER", "bool", "Transkripcija", "Nuolat įkrautas modelis (ASR serveris)",
            "Modelis laikomas atmintyje — tekstas po trumpo diktavimo atsiranda greičiau (nereikia kas kartą krauti). "
            "Kaina: ~3 GB RAM, kol yra darbo; po žemiau nurodyto laiko be darbo modelis iškraunamas."),
    Setting("ASR_SERVER_IDLE_MIN", "int", "Transkripcija", "Iškrauti modelį po (min be darbo)",
            "Kiek minučių be transkripcijų laikyti modelį atmintyje.", 1, 480),
    # ── VAD ──
    Setting("VAD_FILTER", "bool", "VAD (kalbos filtras)", "Kalbos filtras prieš transkripciją",
            "Prieš kraunant modelį randama kalba (Silero VAD): įrašai be kalbos praleidžiami (modelis nekraunamas), "
            "tylus / be kalbos sistemos kanalas netranskribuojamas."),
    Setting("VAD_MIN_SPEECH_SEC", "float", "VAD (kalbos filtras)", "Mažiausiai kalbos (s)",
            "Jei kanale kalbos mažiau — jis praleidžiamas; jei visame įraše — įrašas laikomas tuščiu.", 0.1, 10, step=0.1),
    Setting("VAD_PAD_SEC", "float", "VAD (kalbos filtras)", "Paraštė aplink kalbą (s)",
            "Kiek palikti prieš ir po kiekvienos kalbos atkarpos, kad nenukirstų žodžių pradžių ir galų.", 0, 2, step=0.1),
    Setting("VAD_TRIM", "bool", "VAD (kalbos filtras)", "Apkarpyti iki kalbos",
            "Whisper'iui duoti tik kalbos atkarpas. Matuota: greičio nauda maža (2–4 %, Whisper turi savo VAD), o "
            "tekstas šiek tiek skiriasi — todėl numatytai išjungta. Kalbos neturintys įrašai/kanalai praleidžiami bet kuriuo atveju."),
    # ── Archyvas ──
    Setting("DELETE_EMPTY", "bool", "Archyvas", "Trinti tuščius įrašus",
            "Jei transkripcijoje nėra teksto (triukšmas) — ištrinti ir garsą, ir tekstą."),
    Setting("ARCHIVE_MP3", "bool", "Archyvas", "Archyvuoti į mp3", "Po transkripcijos wav keičiamas mažu mp3 (taupo vietą)."),
    Setting("ARCHIVE_KBPS", "int", "Archyvas", "mp3 kokybė (kbps)", "Kalbai pakanka 48–64.", 16, 320),
    Setting("RETENTION_DAYS", "int", "Archyvas", "Teksto lange rodomos dienos",
            "Senesni tekstai iš lango nutrinami (failai lieka).", 1, 365),
    # ── Debug ──
    Setting("DEBUG", "bool", "Debug", "Debug režimas",
            "Detalus žurnalas ~/.local/state/diktatura/debug.log: įrenginiai, garso lygiai, sprendimai, "
            "modelio krovimas, RTF. Įprastai išjungta (žurnalas greitai auga)."),
)
BY_KEY = {s.key: s for s in SCHEMA}


def parse(path) -> dict:
    """KEY=VALUE failas -> {KEY: 'value'} (komentarai ir tuščios eilutės praleidžiamos)."""
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                if ln.lstrip().startswith("#"):
                    continue
                m = LINE.match(ln)
                if m:
                    out[m.group(1)] = m.group(2)
    except FileNotFoundError:
        pass
    return out


def defaults() -> dict:
    return parse(paths.DEFAULT_CONF)


def ensure() -> None:
    """Jei vartotojo config nėra — sukurti iš numatytųjų."""
    if not paths.CONF_FILE.exists():
        paths.CONF_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(paths.DEFAULT_CONF, paths.CONF_FILE)


def coerce(key: str, value: str):
    """Tekstas -> tipizuota reikšmė; ValueError su lietuvišku paaiškinimu, jei netinka."""
    s = BY_KEY.get(key)
    if s is None:
        raise ValueError(f"Nežinomas nustatymas: {key}")
    v = str(value).strip()
    if s.kind == "bool":
        if v in ("1", "true", "True", "taip"):
            return True
        if v in ("0", "false", "False", "ne"):
            return False
        raise ValueError(f"{s.label}: turi būti 1 (taip) arba 0 (ne), gauta „{v}“")
    if s.kind == "choice":
        if v not in s.choices:
            raise ValueError(f"{s.label}: galimos reikšmės {', '.join(s.choices)}, gauta „{v}“")
        return v
    try:
        num = int(v) if s.kind == "int" else float(v)
    except ValueError:
        raise ValueError(f"{s.label}: turi būti {'sveikasis ' if s.kind == 'int' else ''}skaičius, gauta „{v}“") from None
    if s.lo is not None and num < s.lo or s.hi is not None and num > s.hi:
        raise ValueError(f"{s.label}: leistina {s.lo:g}–{s.hi:g}, gauta {num:g}")
    return num


def to_text(key: str, value) -> str:
    if BY_KEY[key].kind == "bool":
        return "1" if value in (True, 1, "1") else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def load_raw() -> dict:
    """Numatytieji + vartotojo (tekstiniai)."""
    raw = defaults()
    raw.update(parse(paths.CONF_FILE))
    return raw


def load() -> dict:
    """Tipizuoti nustatymai. Neteisinga vartotojo reikšmė -> numatytoji (sistema neturi lūžti)."""
    raw, d = load_raw(), defaults()
    out = {}
    for s in SCHEMA:
        try:
            out[s.key] = coerce(s.key, raw.get(s.key, d.get(s.key, "")))
        except ValueError:
            out[s.key] = coerce(s.key, d[s.key])
    return out


def validate(values: dict) -> dict:
    """{KEY: 'tekstas'} -> {KEY: klaidos tekstas} (tuščias = viskas gerai). Tikrina ir tarpusavio ryšius."""
    errors = {}
    typed = {}
    for k, v in values.items():
        try:
            typed[k] = coerce(k, v)
        except ValueError as e:
            errors[k] = str(e)
    o, c = typed.get("VOX_OPEN_MARGIN"), typed.get("VOX_CLOSE_MARGIN")
    if o is not None and c is not None and c >= o:
        errors["VOX_CLOSE_MARGIN"] = "Išlaikymo atsarga turi būti mažesnė už pradžios atsargą."
    return errors


def save(values: dict) -> None:
    """Išsaugoti vartotojo nustatymus. Šablonas = numatytųjų failas (komentarai ir tvarka išlieka).
    Rašoma atomiškai (tmp + rename), kad daemon'as niekada neperskaitytų pusinio failo."""
    current = load_raw()
    # tarpusavio taisyklės tikrinamos su esamomis reikšmėmis (pvz. keičiama tik VOX_CLOSE_MARGIN)
    related = {k: current[k] for k in ("VOX_OPEN_MARGIN", "VOX_CLOSE_MARGIN") if k in current}
    errors = validate({**related, **values})
    if errors:
        raise ValueError("; ".join(errors.values()))
    current.update({k: to_text(k, coerce(k, v)) for k, v in values.items()})
    lines = []
    with open(paths.DEFAULT_CONF, encoding="utf-8") as fh:
        for ln in fh:
            m = None if ln.lstrip().startswith("#") else LINE.match(ln)
            lines.append(f"{m.group(1)}={current[m.group(1)]}\n" if m and m.group(1) in current else ln)
    paths.CONF_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=paths.CONF_FILE.parent, prefix=".diktatura.conf.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    os.replace(tmp, paths.CONF_FILE)


def reset() -> None:
    """„Atkurti numatytus"."""
    paths.CONF_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paths.DEFAULT_CONF, paths.CONF_FILE)


def main(argv=None) -> int:
    """CLI (naudoja Makefile; tik stdlib — veikia ir su sistemos python3):
        python3 -m diktatura.config show            visi nustatymai (* = pakeista nuo numatytos)
        python3 -m diktatura.config get KEY
        python3 -m diktatura.config set KEY=VALUE [KEY=VALUE ...]
        python3 -m diktatura.config reset           atkurti numatytus
        python3 -m diktatura.config path            vartotojo config failo kelias
    """
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args.pop(0) if args else "show"
    if cmd == "show":
        cur, d = load(), defaults()
        for st in SCHEMA:
            val = to_text(st.key, cur[st.key])
            mark = "*" if val != d.get(st.key) else " "
            print(f" {mark} {st.key:<18} = {val:<14} {st.label}")
        print(f"   ({paths.CONF_FILE}; * = pakeista)")
    elif cmd == "get" and len(args) == 1:
        if args[0] not in BY_KEY:
            print(f"Nežinomas nustatymas: {args[0]}", file=sys.stderr)
            return 2
        print(to_text(args[0], load()[args[0]]))
    elif cmd == "set" and args:
        values = {}
        for a in args:
            k, sep, v = a.partition("=")
            if not sep:
                print(f"Formatas: KEY=VALUE (gauta „{a}“)", file=sys.stderr)
                return 2
            values[k.strip()] = v.strip()
        try:
            save(values)
        except ValueError as e:
            print(f"✗ {e}", file=sys.stderr)
            return 1
        for k in values:
            print(f"✓ {k}={to_text(k, load()[k])}")
    elif cmd == "reset":
        reset()
        print(f"✓ atkurti numatytieji nustatymai ({paths.CONF_FILE})")
    elif cmd == "path":
        print(paths.CONF_FILE)
    else:
        print(main.__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
