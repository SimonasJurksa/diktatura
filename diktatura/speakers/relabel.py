#!/usr/bin/env python3
"""Diktatūra — perskaičiuoti kolegų eilučių kalbėtojus paskutinių dienų tekstuose (.venv).

Kam: pakeitus balso modelį ar griežtumą, seni tekstai turi senus (dažnai klaidingus) vardus. Kiekvienai ne „Tu"
eilutei, kurios įrašas (wav/mp3) dar yra: dešinio kanalo atkarpa (iki kitos eilutės, ≤ 20 s) -> tik kalba (VAD) ->
tas pats griežtas sprendimas kaip transkripcijoje (speakerlib.label_segments): registruotas vardas / „Tu" /
„Kolega?" / nežinomas -> „Kolega?nezN" (naujas balsas -> Apmokymai; ten įvardijus pasitaiso ir šie tekstai).
„Tu" eilutės (tavo mikrofonas) nekeičiamos. Prieš perrašant originalai nukopijuojami į
<duomenys>/backup/relabel-<laikas>/.

    python -m diktatura.speakers.relabel [--days 2]            # ką keistų (nieko nekeičia, nežinomų nekuria)
    python -m diktatura.speakers.relabel [--days 2] --apply
"""
import argparse
import shutil
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from diktatura import config, debug, paths, sessions
from diktatura.speakers import speakerlib as sl
from diktatura.speakers import store
from diktatura.speakers import teach

SR = 16000
MIN_SPEECH_SEC = 1.0      # trumpesnei kalbai vardas nespėjamas -> „Kolega?"


class Ctx:
    """Saugykla vienam paleidimui (pending papildomas vietoje — tas pats nežinomas balsas -> tas pats nezN)."""

    def __init__(self, apply: bool, threshold=None, margin=None):
        c = config.load()
        self.threshold = float(c["SPEAKER_THRESHOLD"]) if threshold is None else threshold
        self.margin = float(c["SPEAKER_MARGIN"]) if margin is None else margin
        self.store, self.owner = sl.load_enroll(), sl.load_owner()
        self.pending, self.ignored = sl.load_pending(), sl.load_ignored()
        self.apply, self.new = apply, 0

    def add_pending(self, emb, samples, sr, src):
        self.new += 1
        if self.apply:
            return sl.add_pending(emb, samples, sr, src)
        return f"nez(naujas{self.new})"


def relabel_file(path: Path, ctx: Ctx, embed, backup: Path = None) -> list:
    """-> [(eilutės nr., senas, naujas)] — tik pasikeitusios; ctx.apply -> failas perrašomas (originalas -> backup)."""
    audio = sessions.audio_for(path)
    if audio is None or teach.n_channels(audio) < 2:
        return []
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changes = []
    for idx, raw in enumerate(lines):
        p = sessions.parse_line(raw.rstrip("\n"))
        if not p or p[1] == store.ME:
            continue
        span = store.line_span(path, idx)
        if span is None:
            continue
        x, sec = teach.speech_only(teach.decode(audio, span[0], span[1] - span[0], 1))
        who = store.UNKNOWN
        if sec >= MIN_SPEECH_SEC:
            [(_, _, who, _)], _ = sl.label_segments(
                [(0.0, sec, p[2])], x, ctx.store, ctx.pending, ctx.ignored, ctx.threshold, embed,
                ctx.add_pending, sessions.base_name(path.name), margin=ctx.margin, owner=ctx.owner)
        if who != p[1]:
            changes.append((idx, p[1], who))
            nl = "\n" if raw.endswith("\n") else ""
            lines[idx] = f"[{p[0]}] {who}: {p[2]}{nl}"
    if changes and ctx.apply:
        if backup:
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup / path.name)
        store._atomic_write(path, "".join(lines))
    return changes


def recent_files(days: int, today: date = None) -> list:
    since = (today or date.today()) - timedelta(days=max(days, 1) - 1)
    return [f for f in sessions.text_files(paths.RECORDINGS, since) if f.name.endswith(".named.txt")]


def run(days: int, apply: bool, embed=None, out=print) -> dict:
    if not store.compatible():
        raise SystemExit(f"Balsai paskaičiuoti senu modeliu ({store.model_id()}) — pirma: make speakers-migrate")
    embed = embed or sl.compute_embedding
    ctx = Ctx(apply)
    files = recent_files(days)
    backup = paths.DATA_DIR / "backup" / f"relabel-{datetime.now():%Y%m%d_%H%M%S}" if apply else None
    total, after = 0, Counter()
    for f in files:
        ch = relabel_file(f, ctx, embed, backup)
        total += len(ch)
        after.update(new for _, _, new in ch)
        if ch:
            out(f"  {f.name}: pakeista {len(ch)} eil. — " + ", ".join(
                f"{o}→{n}" for (o, n), k in Counter((o, n) for _, o, n in ch).most_common(4)))
    res = {"files": len(files), "changed": total, "labels": dict(after),
           "new_pending": ctx.new,
           "backup": str(backup) if backup and total else None}
    debug.log("speakers", f"relabel {days} d.: failų {len(files)}, pakeista {total} eil., apply={apply}")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(prog="diktatura.speakers.relabel")
    ap.add_argument("--days", type=int, default=2, help="kelių paskutinių dienų tekstus (numatytai 2)")
    ap.add_argument("--apply", action="store_true", help="perrašyti (be jo — tik parodo)")
    a = ap.parse_args()
    print(f"Kalbėtojų perskaičiavimas: paskutinės {a.days} d. ({'PERRAŠOMA' if a.apply else 'tik peržiūra'})")
    r = run(a.days, a.apply)
    print(f"Failų: {r['files']}, pakeistų eilučių: {r['changed']}; nauji kalbėtojai: "
          + (", ".join(f"{k} {v}" for k, v in sorted(r["labels"].items())) or "—"))
    if not a.apply:
        print(f"Nieko nepakeista (būtų naujų nežinomų balsų: {r['new_pending']}). "
              f"Atlikti: make speakers-relabel DAYS={a.days} APPLY=1")
    elif r["backup"]:
        print(f"✓ Originalai: {r['backup']}. Nežinomus balsus įvardink 🎓 Apmokymuose — tekstai pasitaisys patys.")


if __name__ == "__main__":
    main()
