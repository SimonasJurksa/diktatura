"""Diktatūra — balsų atsarginė kopija (tik stdlib). Balsų „pirštų atspaudai" — vienintelis sunkiai atkuriamas dalykas:
įrašus galima perdaryti, o registruotus balsus reikėtų vėl mokyti iš pavyzdžių.

Kopija: <duomenys>/backups/voices-YYYYMMDD_HHMMSS.tar.gz — speakers/{enroll,owner,ignored,assigned,model}.json
ir speakers/pending/ (laukiančių vardo balsų pavyzdžiai). Daroma: `make backup-voices`, Nustatymuose
(„💾 Balsų atsarginė kopija"), ir AUTOMATIŠKAI prieš „Ištrinti įrašus ir tekstus" su varnele „Vardų atpažinimas"
(diktatura.reset). Laikoma KEEP naujausių. Atkurti: `make restore-voices [F=failas]` (prieš tai — dabartinių kopija).
CLI: python3 -m diktatura.backup create | list | restore [failas]
"""
import io
import json
import sys
import tarfile
import time
from pathlib import Path

from diktatura import paths

KEEP = 10
FILES = ("enroll.json", "owner.json", "ignored.json", "assigned.json", "model.json")


def backups_dir() -> Path:
    return paths.DATA_DIR / "backups"


def list_backups() -> list:
    d = backups_dir()
    files = list(d.glob("voices-*.tar.gz")) if d.exists() else []
    return sorted(files, key=lambda f: (f.stat().st_mtime, f.name))      # ne pagal vardą: „-2" rikiuotųsi prieš „.tar"


def create(reason: str = "") -> Path:
    """-> archyvo kelias. Tuščia saugykla (nėra balsų) irgi archyvuojama (tada žinai, kad nebuvo ko)."""
    d = backups_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out, n = d / f"voices-{stamp}.tar.gz", 2
    while out.exists():                                 # dvi kopijos tą pačią sekundę (pvz. prieš atkūrimą) — neperrašyti
        out, n = d / f"voices-{stamp}-{n}.tar.gz", n + 1
    with tarfile.open(out, "w:gz") as tar:
        for name in FILES:
            f = paths.SPEAKERS / name
            if f.exists():
                tar.add(f, arcname=f"speakers/{name}")
        if paths.PENDING.exists():
            for f in sorted(paths.PENDING.iterdir()):
                if f.is_file():
                    tar.add(f, arcname=f"speakers/pending/{f.name}")
        meta = json.dumps({"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": reason, "files": FILES},
                          ensure_ascii=False).encode("utf-8")
        ti = tarfile.TarInfo("backup.json")
        ti.size, ti.mtime = len(meta), int(time.time())
        tar.addfile(ti, io.BytesIO(meta))
    for old in list_backups()[:-KEEP]:
        old.unlink(missing_ok=True)
    return out


def describe(path) -> dict:
    """{"created", "reason", "voices", "pending"} — kas archyve (be išpakavimo)."""
    info = {"created": "", "reason": "", "voices": 0, "pending": 0}
    with tarfile.open(path, "r:gz") as tar:
        for m in tar.getmembers():
            if m.name == "backup.json":
                try:
                    info.update({k: v for k, v in json.load(tar.extractfile(m)).items() if k in ("created", "reason")})
                except ValueError:
                    pass
            elif m.name == "speakers/enroll.json":
                try:
                    info["voices"] = len(json.load(tar.extractfile(m)))
                except ValueError:
                    pass
            elif m.name.startswith("speakers/pending/") and m.name.endswith(".json"):
                info["pending"] += 1
    return info


def restore(path, keep_current: bool = True) -> dict:
    """Atkurti iš archyvo (tik speakers/ failai; kiti keliai archyve ignoruojami). keep_current — prieš tai dabartinių
    kopija. -> describe() atkurtojo."""
    path = Path(path)
    if keep_current:
        create(reason=f"prieš atkūrimą iš {path.name}")
    with tarfile.open(path, "r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile() and m.name.startswith("speakers/")
                   and ".." not in m.name.split("/")]
        if not members:
            raise ValueError(f"{path.name}: archyve nėra balsų failų")
        paths.PENDING.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            (paths.SPEAKERS / name).unlink(missing_ok=True)
        for f in paths.PENDING.glob("nez*"):
            f.unlink()
        tar.extractall(paths.DATA_DIR, members=members)
    return describe(path)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "create"
    if cmd == "create":
        out = create("make backup-voices")
        d = describe(out)
        print(f"✓ {out} — balsų: {d['voices']}, laukiančių vardo: {d['pending']}")
    elif cmd == "list":
        items = list_backups()
        if not items:
            print(f"Kopijų nėra ({backups_dir()}). Sukurti: make backup-voices")
        for p in items:
            d = describe(p)
            print(f"{p.name}  balsų {d['voices']}, laukiančių {d['pending']}  {d['reason']}")
    elif cmd == "restore":
        items = list_backups()
        target = Path(args[1]) if len(args) > 1 else (items[-1] if items else None)
        if target is None or not target.exists():
            print("Nėra ką atkurti — nurodyk failą: make restore-voices F=<kelias>", file=sys.stderr)
            return 1
        d = restore(target)
        print(f"✓ atkurta iš {target.name}: balsų {d['voices']}, laukiančių vardo {d['pending']} "
              "(dabartiniai prieš tai išsaugoti kaip atskira kopija)")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
