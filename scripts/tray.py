#!/usr/bin/env python3
"""Wispr status bar ikona (GNOME/Ubuntu, AyatanaAppIndicator3).

Spalvos:
  ⚪ pilka   — nerašo (budi)
  🔴 raudona — RECORDING (vyksta įrašymas)
  🟡 geltona — posprocessingas (transkripcija / mp3 / kiti darbai)

Naudoja SISTEMOS python3 (turi gi). Paleidimas: systemd --user wispr-tray.service.
"""
import os
import subprocess
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as AppIndicator  # noqa: E402

ICONS = str(Path.home() / "wispr" / "icons")
REC = str(Path.home() / "wispr" / "recordings")
STATE = Path.home() / "wispr" / "recordings" / ".recording"


def running(pattern):
    return subprocess.run(["pgrep", "-f", pattern],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def state():
    # Įrašymą rodo būsenos failas (daemon jį sukuria/ištrina) — patikima ir VOX, ir Slack.
    if STATE.exists():
        return "rec", "🔴 Įrašoma"
    if running(r"transcribe_named|transcribe_stereo|transcribe\.py") or running(r"ffmpeg.*libmp3lame"):
        return "proc", "🟡 Apdorojama (transkripcija)"
    return "idle", "⚪ Budi (nerašo)"


def active_mode():
    for svc, name in [("wispr-vox", "VOX diktavimas"), ("wispr-autorecord", "Slack skambučiai")]:
        r = subprocess.run(["systemctl", "--user", "is-active", svc],
                           stdout=subprocess.PIPE, text=True).stdout.strip()
        if r == "active":
            return name
    return "išjungta"


class Tray:
    def __init__(self):
        self.ind = AppIndicator.Indicator.new_with_path(
            "wispr", "wispr-idle", AppIndicator.IndicatorCategory.APPLICATION_STATUS, ICONS)
        self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.menu = Gtk.Menu()
        self.item_status = Gtk.MenuItem(label="Diktatūra")
        self.item_status.set_sensitive(False)
        self.item_mode = Gtk.MenuItem(label="Režimas: …")
        self.item_mode.set_sensitive(False)
        self.menu.append(self.item_status)
        self.menu.append(self.item_mode)
        self.menu.append(Gtk.SeparatorMenuItem())
        it_text = Gtk.MenuItem(label="📄 Rodyti nuskaitytą tekstą")
        it_text.connect("activate", self.open_textview)
        self.menu.append(it_text)
        it_open = Gtk.MenuItem(label="Atidaryti įrašų aplanką")
        it_open.connect("activate", lambda _: subprocess.Popen(["xdg-open", REC]))
        self.menu.append(it_open)
        it_quit = Gtk.MenuItem(label="Išeiti iš ikonos")
        it_quit.connect("activate", lambda _: Gtk.main_quit())
        self.menu.append(it_quit)
        self.menu.show_all()
        self.ind.set_menu(self.menu)
        self.cur = None
        self.update()
        GLib.timeout_add_seconds(2, self.update)

    def open_textview(self, _):
        # Vienas langas — jei jau atidarytas, nekuriam naujo
        if running(r"textview\.py"):
            return
        subprocess.Popen(["/usr/bin/python3", str(Path.home() / "wispr/scripts/textview.py")])

    def update(self):
        st, label = state()
        if st != self.cur:
            self.ind.set_icon_full(f"wispr-{st}", label)
            self.cur = st
        self.ind.set_title(f"Diktatūra — {label}")
        self.item_status.set_label(f"Diktatūra — {label}")
        self.item_mode.set_label(f"Režimas: {active_mode()}")
        return True


if __name__ == "__main__":
    Tray()
    Gtk.main()
