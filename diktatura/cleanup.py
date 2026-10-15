"""Diktatūra — senų įrašų GARSO trynimas (Nustatymai → Archyvas → AUDIO_CLEANUP). Tik stdlib (naudoja ir UI).

Trinamas tik garsas: recordings/{vox,slack,rec}_*.wav|.mp3 (wav ir mp3 su ta pačia baze — vienas įrašas). Tekstai lieka
(Teksto langas, paieška, statistika, žymės); be garso neveikia tik „▶ Groti nuo čia" ir kalbėtojo taisymas su mokymu.
  off  — netrinama;
  age  — įrašai, senesni nei AUDIO_KEEP_DAYS dienų (įrašymo laikas iš failo vardo);
  size — kol recordings/ failai (garsas + tekstai, be pakatalogių) užima daugiau nei AUDIO_MAX_GB, trinami seniausi.
         Naujausias įrašas netrinamas niekada — net jei jis vienas didesnis už ribą.
Niekada netrinama: dabar rašomas ir dabar transkribuojamas (reset.busy_bases), ką tik keistas (< FRESH_SEC), dar be teksto
ir be .skip, kol AUTOTRANSCRIBE=1 (laukia eilės ar nakties — kitaip dingtų dar nesutranskribuotas pokalbis).
Tušti failai (≤ EMPTY_MAX B — 0 B arba tik wav antraštė: įrašymas nutrūko, pvz. pilnas diskas) trinami visada, net su off:
garso juose nėra, o naktinis juos bandytų transkribuoti kas naktį.
Paleidžiama: bin/transcribe-file.sh pabaigoje (po kiekvienos transkripcijos), bin/transcribe-pending.sh pabaigoje (naktinis),
`make cleanup [DRY=1]`, Nustatymų „Išsaugoti" (su patvirtinimu, jei nauji nustatymai ką nors ištrintų).
"""
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from diktatura import config, paths, sessions

OFF, AGE, SIZE = "off", "age", "size"
EMPTY_MAX = 44              # wav antraštė be duomenų
FRESH_SEC = 60
GB = 1024 ** 3


@dataclass
class Rec:
    base: str
    when: datetime
    audio: list                 # [Path] — wav ir (ar) mp3
    size: int = 0


@dataclass
class Plan:
    mode: str = OFF
    delete: list = field(default_factory=list)      # [Rec], seniausi pirmi
    empty: list = field(default_factory=list)       # [Path] — tušti garso failai
    total: int = 0                                  # recordings/ failai dabar, baitai
    audio_total: int = 0                            # iš jų garsas
    n_audio: int = 0                                # įrašų su garsu
    protected: int = 0                              # atitiktų taisyklę, bet saugomi (rašomas / be teksto / naujas)
    limit: float = 0                                # size: riba baitais

    @property
    def freed(self) -> int:
        return sum(r.size for r in self.delete) + sum(_size(p) for p in self.empty)

    @property
    def after(self) -> int:
        return self.total - self.freed


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def has_text(rec_dir: Path, base: str) -> bool:
    return any((rec_dir / (base + suf)).exists() for suf in sessions.TEXT_SUFFIXES + (".skip",))


def scan(rec_dir: Path = None):
    """-> ({bazė: Rec}, [tušti failai], visų recordings/ failų baitai)."""
    rec_dir = rec_dir or paths.RECORDINGS
    recs, empty, total = {}, [], 0
    try:
        files = [p for p in rec_dir.iterdir() if p.is_file()]
    except OSError:
        return recs, empty, total
    for p in files:
        size = _size(p)
        total += size
        if p.suffix not in sessions.AUDIO_SUFFIXES or not sessions.parse_name(p.name):
            continue
        if size <= EMPTY_MAX:
            empty.append(p)
            continue
        base = sessions.base_name(p.name)
        r = recs.setdefault(base, Rec(base, sessions.parse_name(p.name)[1], []))
        r.audio.append(p)
        r.size += size
    return recs, sorted(empty), total


def plan(cfg: dict = None, busy: set = None, now: float = None) -> Plan:
    """Ką ištrintų nustatymai cfg (numatyta — dabartiniai). busy — bazės, kurių liesti negalima (numatyta — rašomas
    ir transkribuojami, žr. reset.busy_bases)."""
    cfg = cfg or config.load()
    if busy is None:
        from diktatura import reset
        busy = reset.busy_bases()
    now = time.time() if now is None else now
    rec_dir = paths.RECORDINGS
    recs, empty, total = scan(rec_dir)

    def fresh(p: Path) -> bool:
        try:
            return now - p.stat().st_mtime < FRESH_SEC
        except OSError:
            return True

    out = Plan(mode=cfg.get("AUDIO_CLEANUP", OFF), total=total, n_audio=len(recs),
               audio_total=sum(r.size for r in recs.values()))
    out.empty = [p for p in empty if sessions.base_name(p.name) not in busy and not fresh(p)]
    ordered = sorted(recs.values(), key=lambda r: (r.when, r.base))

    def protected(r: Rec) -> bool:
        return (r.base in busy or any(fresh(p) for p in r.audio)
                or (cfg.get("AUTOTRANSCRIBE", True) and not has_text(rec_dir, r.base)))

    if out.mode == AGE:
        cutoff = datetime.fromtimestamp(now) - timedelta(days=float(cfg["AUDIO_KEEP_DAYS"]))
        for r in ordered:
            if r.when < cutoff:
                if protected(r):
                    out.protected += 1
                else:
                    out.delete.append(r)
    elif out.mode == SIZE:
        out.limit = float(cfg["AUDIO_MAX_GB"]) * GB
        left = total - sum(_size(p) for p in out.empty)
        for r in ordered[:-1]:                       # naujausias — niekada
            if left <= out.limit:
                break
            if protected(r):
                out.protected += 1
                continue
            out.delete.append(r)
            left -= r.size
    return out


def run(cfg: dict = None, busy: set = None, dry: bool = False) -> Plan:
    """Ištrinti pagal plan(); -> tas planas (kas ištrinta)."""
    p = plan(cfg, busy)
    if dry:
        return p
    for f in p.empty + [a for r in p.delete for a in r.audio]:
        try:
            f.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log(f"⚠ nepavyko ištrinti {f.name}: {e}")
    if p.empty:
        log(f"∅ tušti garso failai (įrašymas nutrūko, pvz. pilnas diskas) ištrinti: {len(p.empty)} — "
            + ", ".join(f.name for f in p.empty[:5]) + (" …" if len(p.empty) > 5 else ""))
    if p.delete:
        log(f"🧹 senas garsas ištrintas ({describe_rule(cfg or config.load())}): {len(p.delete)} įr., "
            f"{human_size(sum(r.size for r in p.delete))} — {p.delete[0].base} … {p.delete[-1].base}; tekstai palikti")
    return p


def describe_rule(cfg: dict) -> str:
    mode = cfg.get("AUDIO_CLEANUP", OFF)
    if mode == AGE:
        return f"senesnis nei {int(cfg['AUDIO_KEEP_DAYS'])} d."
    if mode == SIZE:
        return f"įrašai > {float(cfg['AUDIO_MAX_GB']):g} GB"
    return "netrinama"


def summary(p: Plan) -> str:
    """Žmogui: kiek užima dabar ir ką ištrintų (Nustatymų langas, `make cleanup`)."""
    s = f"Įrašų katalogas dabar užima {human_size(p.total)} (garsas — {p.n_audio} įr., {human_size(p.audio_total)})."
    if p.delete:
        s += (f" Su šiais nustatymais būtų ištrintas {len(p.delete)} įr. garsas ({human_size(sum(r.size for r in p.delete))},"
              f" {p.delete[0].when:%Y-%m-%d} – {p.delete[-1].when:%Y-%m-%d}); tekstai liktų.")
    elif p.mode != OFF:
        s += " Su šiais nustatymais dabar nieko trinti nereikia."
    if p.protected:
        s += f" Saugoma: {p.protected} įr. (dar be teksto arba rašomas)."
    if p.mode == SIZE and p.after > p.limit:
        s += f" Riba ({human_size(p.limit)}) vis tiek viršyta — naujausias įrašas ir saugomi netrinami."
    if p.empty:
        s += f" Tuščių failų (nutrūkęs įrašymas): {len(p.empty)} — bus ištrinti."
    return s


def log(msg: str) -> None:
    line = f"{datetime.now():%F %T} {msg}"
    print(line, flush=True)
    try:
        paths.LOG_TRANSCRIBE.parent.mkdir(parents=True, exist_ok=True)
        with open(paths.LOG_TRANSCRIBE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def main(argv=None) -> int:
    """python -m diktatura.cleanup [--dry-run]  — ištrinti pagal nustatymus (--dry-run: tik parodyti)."""
    args = sys.argv[1:] if argv is None else argv
    if set(args) - {"--dry-run"}:
        print(main.__doc__, file=sys.stderr)
        return 2
    dry = "--dry-run" in args
    cfg = config.load()
    p = run(cfg, dry=dry)
    if dry or os.isatty(1):
        print(f"Taisyklė: {describe_rule(cfg)}. " + summary(p))
        for r in p.delete if dry else []:
            print(f"  🗑 {r.base}  {r.when:%Y-%m-%d %H:%M}  {human_size(r.size)}  ({', '.join(a.suffix for a in r.audio)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
