#!/usr/bin/env python3
"""Papildoma „Tu" nutekėjimo valymas jau gatavame *.dialog.txt (be re-transkripcijos).

Geresnis kriterijus nei SequenceMatcher: ŽODŽIŲ PERSIDENGIMAS kolegų atžvilgiu.
Jei „Tu" eilutės žodžių dauguma (>=THRESH) randasi laike persidengiančiose „Kolegos"
eilutėse — tai kolegų nutekėjimas į mic → išmetam. Trumpas (<3 žodžių) „Tu" repliką
paliekam (reakcijos „jo/okei/mhm"), kad neprarastume tikros kalbos.

Naudojimas: python dedup_dialog.py <file.dialog.txt> [--thresh 0.6] [--win 8]
Rezultatas: <file>.clean.dialog.txt
"""
import argparse
import re
from pathlib import Path

LINE = re.compile(r"\[(\d+):(\d\d):(\d\d)\]\s+([^:]+):\s+(.*)")


def secs(h, m, s):
    return int(h) * 3600 + int(m) * 60 + int(s)


def words(t):
    return [w for w in re.findall(r"\w+", t.lower()) if len(w) > 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--thresh", type=float, default=0.6)
    ap.add_argument("--win", type=float, default=8.0, help="laiko langas (s) persidengimui")
    ap.add_argument("--me", default="Tu")
    ap.add_argument("--them", default="Kolegos")
    ap.add_argument("--minwords", type=int, default=3)
    args = ap.parse_args()

    rows = []
    for ln in Path(args.file).read_text(encoding="utf-8").splitlines():
        m = LINE.match(ln)
        if m:
            h, mn, s, who, txt = m.groups()
            rows.append([secs(h, mn, s), who.strip(), txt.strip()])

    them = [(t, set(words(tx))) for t, who, tx in rows if who == args.them]
    kept, dropped = [], 0
    for t, who, txt in rows:
        if who != args.me:
            kept.append((t, who, txt)); continue
        w = words(txt)
        if len(w) < args.minwords:
            kept.append((t, who, txt)); continue
        # surenkam visus kolegų žodžius laiko lange aplink šią repliką
        near = set()
        for tt, ws in them:
            if abs(tt - t) <= args.win:
                near |= ws
        overlap = sum(1 for x in w if x in near) / len(w)
        if overlap >= args.thresh:
            dropped += 1
        else:
            kept.append((t, who, txt))

    kept.sort(key=lambda r: r[0])
    out = Path(args.file).with_suffix("").with_suffix(".clean.dialog.txt")
    def hhmmss(x): return f"{x//3600}:{(x%3600)//60:02d}:{x%60:02d}"
    out.write_text("\n".join(f"[{hhmmss(t)}] {who}: {txt}" for t, who, txt in kept) + "\n", encoding="utf-8")
    print(f"Įeita: {len(rows)} eil. | papildomai pašalinta nutekėjimo: {dropped} | liko: {len(kept)}")
    print(f"Išsaugota: {out}")


if __name__ == "__main__":
    main()
