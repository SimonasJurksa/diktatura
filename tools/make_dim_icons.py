#!/usr/bin/env python3
"""Diktatūra — sugeneruoja blankias ikonų versijas pulsavimui (icons/diktatura-<būsena>-dim.png).

Pulsuojanti ikona (kai laukia nežinomų balsų „Apmokymai") kaitalioja pilną ir blankią tos pačios spalvos
ikoną — jokių naujų spalvų. Paleisti po ikonų pakeitimo:  /usr/bin/python3 tools/make_dim_icons.py
"""
from pathlib import Path

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # noqa: E402

ICONS = Path(__file__).resolve().parent.parent / "icons"
ALPHA = 0.3


def main():
    for state in ("idle", "rec", "proc"):
        pb = GdkPixbuf.Pixbuf.new_from_file(str(ICONS / f"diktatura-{state}.png")).add_alpha(False, 0, 0, 0)
        px = bytearray(pb.get_pixels())
        stride, n = pb.get_rowstride(), pb.get_n_channels()
        for y in range(pb.get_height()):
            for x in range(pb.get_width()):
                i = y * stride + x * n + 3
                px[i] = int(px[i] * ALPHA)
        dim = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(px)), GdkPixbuf.Colorspace.RGB, True, 8,
                                              pb.get_width(), pb.get_height(), stride)
        out = ICONS / f"diktatura-{state}-dim.png"
        dim.savev(str(out), "png", [], [])
        print(f"✓ {out.name}")


if __name__ == "__main__":
    main()
