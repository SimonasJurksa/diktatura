"""Diktatūra — žymės transkripcijų eilutėms: ⭐ svarbu, ✅ užduotis (atlikta / ne). Tik stdlib (naudoja UI).

Saugoma <duomenys>/annotations.json (privatu — teksto ištraukos; repo NIEKADA):
  {"<failo vardas>#<eilutės nr.>": {"tag": "star"|"task", "done": bool, "text": "<eilutės tekstas>", "added": ISO}}
Raktas be kalbėtojo — žymė išlieka, kai Apmokymuose „Kolega?nezN" pervadinamas vardu. Jei transkripcija
perrašyta ir eilutės tekstas nebesutampa — žymė ieškoma pagal tekstą tame pačiame faile (match).
"""
import json
import os
import tempfile
from datetime import datetime

from diktatura import paths

TAGS = {"star": "⭐", "task": "☐"}
DONE_ICON = "☑"


def _file():
    return paths.DATA_DIR / "annotations.json"


def load() -> dict:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def save(d: dict) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".annotations.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, f)


def key(file_name: str, idx: int) -> str:
    return f"{file_name}#{idx}"


def match(d: dict, file_name: str, idx: int, text: str):
    """Žymė šiai eilutei (tikrinamas tekstas; jei eilutė pasislinko — ieškoma pagal tekstą tame faile)."""
    a = d.get(key(file_name, idx))
    if a and a.get("text") == text:
        return a
    for k, v in d.items():
        if k.startswith(file_name + "#") and v.get("text") == text:
            return v
    return None


def set_tag(file_name: str, idx: int, text: str, tag) -> None:
    """tag: 'star' | 'task' | None (pašalinti)."""
    d = load()
    for k in [k for k, v in d.items() if k.startswith(file_name + "#") and v.get("text") == text]:
        del d[k]
    if tag:
        if tag not in TAGS:
            raise ValueError(f"Nežinoma žymė: {tag}")
        d[key(file_name, idx)] = {"tag": tag, "done": False, "text": text,
                                  "added": datetime.now().isoformat(timespec="seconds")}
    save(d)


def toggle_done(file_name: str, idx: int, text: str) -> bool:
    d = load()
    a = match(d, file_name, idx, text)
    if not a or a.get("tag") != "task":
        raise KeyError("Ši eilutė nepažymėta kaip užduotis")
    a["done"] = not a.get("done", False)
    save(d)
    return a["done"]


def icon(a) -> str:
    if not a:
        return ""
    if a.get("tag") == "task":
        return DONE_ICON if a.get("done") else TAGS["task"]
    return TAGS.get(a.get("tag"), "")
