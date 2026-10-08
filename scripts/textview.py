#!/usr/bin/env python3
"""Wispr gyvas transkripcijų langas — „Rodyti nuskaitytą tekstą".

- Tail'ina visus recordings/*.named.txt + *.txt: nauji/papildyti tekstai įtraukiami automatiškai.
- Sesijos (failai) atskiriamos skyrikliu: // ───── TIMESTAMP · VOX/SLACK · vardas ─────
- Kalbėtojai (Tu, kolegų vardai) paryškinami skirtingom spalvom.
- Tekstą galima žymėti, kopijuoti (Ctrl+C / „Kopijuoti viską"), ieškoti.
- Sistemos python3 (gi/GTK).
"""
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

RETENTION_DAYS = 2   # laikom tik tiek paskutinių dienų (senesnį trimint iš viršaus)

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango  # noqa: E402

import os
REC = Path(os.environ.get("WISPR_REC", str(Path.home() / "wispr" / "recordings")))
LINE = re.compile(r"^\[(\d+:\d\d:\d\d)\]\s+([^:]+):\s*(.*)$")
NAME_TS = re.compile(r"(vox|slack)_(\d{8})_(\d{6})")

# Spalvos kalbėtojams (veikia light+dark); priskiriamos pagal pasirodymą
PALETTE = ["#1a73e8", "#188038", "#d93025", "#9334e6", "#e37400",
           "#00897b", "#c5221f", "#7cb342", "#6d4c41"]


class TextView(Gtk.Window):
    def __init__(self):
        super().__init__(title="Diktatūra — nuskaitytas tekstas")
        self.set_default_size(820, 640)
        self.seen = {}          # failas -> perskaityta baitų
        self.order = []         # rodomi failai eilės tvarka (sena->nauja)
        self.marks = {}         # failas -> žymeklis sesijos pradžioje (trimingui)
        self.spk_tags = {}      # vardas -> tag
        self.pi = 0             # palette indeksas
        self.autoscroll = True

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)

        # Įrankių juosta
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tb.set_margin_top(6); tb.set_margin_bottom(6)
        tb.set_margin_start(6); tb.set_margin_end(6)
        self.search = Gtk.SearchEntry(); self.search.set_placeholder_text("Ieškoti… (Ctrl+F) — nuo 3 simbolių")
        self.search.connect("search-changed", lambda w: self.highlight_all())
        self.search.connect("activate", lambda w: self.goto_match(1))
        tb.pack_start(self.search, True, True, 0)
        b_prev = Gtk.Button(label="◀"); b_prev.set_tooltip_text("Ankstesnis (Shift+Enter)")
        b_prev.connect("clicked", lambda w: self.goto_match(-1)); tb.pack_start(b_prev, False, False, 0)
        b_next = Gtk.Button(label="▶"); b_next.set_tooltip_text("Kitas (Enter)")
        b_next.connect("clicked", lambda w: self.goto_match(1)); tb.pack_start(b_next, False, False, 0)
        self.lbl_match = Gtk.Label(label=""); tb.pack_start(self.lbl_match, False, False, 6)
        btn_copy = Gtk.Button(label="Kopijuoti viską")
        btn_copy.connect("clicked", self.copy_all); tb.pack_start(btn_copy, False, False, 0)
        self.cb_auto = Gtk.CheckButton(label="Sekti naujus"); self.cb_auto.set_active(True)
        self.cb_auto.connect("toggled", lambda w: setattr(self, "autoscroll", w.get_active()))
        tb.pack_start(self.cb_auto, False, False, 0)
        box.pack_start(tb, False, False, 0)

        # Teksto rodinys
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.tv = Gtk.TextView()
        self.tv.set_wrap_mode(Gtk.WrapMode.WORD)
        self.tv.set_editable(True)       # galima valyti/redaguoti prieš kopijuojant
        self.tv.set_left_margin(10); self.tv.set_right_margin(10)
        self.tv.override_font(Pango.FontDescription("monospace 10"))
        self.buf = self.tv.get_buffer()
        self.t_sep = self.buf.create_tag("sep", foreground="#888888", weight=Pango.Weight.BOLD)
        self.t_time = self.buf.create_tag("time", foreground="#999999")
        self.t_hl = self.buf.create_tag("hl", background="#fde047", foreground="#000000")   # visi radiniai
        self.t_cur = self.buf.create_tag("cur", background="#fb923c", foreground="#000000")  # dabartinis
        self.matches = []; self.match_idx = -1
        sw.add(self.tv); box.pack_start(sw, True, True, 0)

        # Būsenos juosta
        self.status = Gtk.Label(label="Kraunu…"); self.status.set_xalign(0)
        self.status.set_margin_start(8); self.status.set_margin_bottom(4)
        box.pack_start(self.status, False, False, 0)

        self.connect("key-press-event", self.on_key)
        self.refresh()
        GLib.timeout_add_seconds(2, self.refresh)
        if os.environ.get("WISPR_SHOT"):   # paslėptas: nufotografuoti save ir išeiti
            GLib.timeout_add(1800, self._selfshot)

    def _selfshot(self):
        win = self.get_window()
        if win:
            pb = Gdk.pixbuf_get_from_window(win, 0, 0, win.get_width(), win.get_height())
            if pb:
                pb.savev(os.environ["WISPR_SHOT"], "png", [], [])
        Gtk.main_quit()
        return False

    def on_key(self, _w, ev):
        if (ev.state & Gdk.ModifierType.CONTROL_MASK) and ev.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.search.grab_focus(); self.search.select_region(0, -1); return True
        if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.search.has_focus():
            self.goto_match(-1 if ev.state & Gdk.ModifierType.SHIFT_MASK else 1); return True
        return False

    def highlight_all(self):
        q = self.search.get_text()
        s, e = self.buf.get_bounds()
        self.buf.remove_tag(self.t_hl, s, e)
        self.buf.remove_tag(self.t_cur, s, e)
        self.matches = []; self.match_idx = -1
        if len(q) < 3:
            self.lbl_match.set_text("")
            return
        it = self.buf.get_start_iter()
        while True:
            found = it.forward_search(q, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
            if not found:
                break
            ms, me = found
            self.buf.apply_tag(self.t_hl, ms, me)
            self.matches.append((ms.get_offset(), me.get_offset()))
            it = me
        self.lbl_match.set_text(f"{len(self.matches)} rasta" if self.matches else "nerasta")

    def goto_match(self, delta):
        if not self.matches:
            return
        self.match_idx = (self.match_idx + delta) % len(self.matches)
        so, eo = self.matches[self.match_idx]
        ms = self.buf.get_iter_at_offset(so); me = self.buf.get_iter_at_offset(eo)
        s, e = self.buf.get_bounds(); self.buf.remove_tag(self.t_cur, s, e)
        self.buf.apply_tag(self.t_cur, ms, me)
        self.tv.scroll_to_iter(ms, 0.2, False, 0, 0)
        self.lbl_match.set_text(f"{self.match_idx + 1}/{len(self.matches)}")

    def spk_tag(self, name):
        if name not in self.spk_tags:
            color = PALETTE[self.pi % len(PALETTE)]; self.pi += 1
            self.spk_tags[name] = self.buf.create_tag(f"spk_{name}", foreground=color,
                                                      weight=Pango.Weight.BOLD)
        return self.spk_tags[name]

    @staticmethod
    def file_dt(f):
        m = NAME_TS.search(f.name)
        if m:
            try:
                return datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S")
            except ValueError:
                pass
        return datetime.fromtimestamp(f.stat().st_mtime)

    def files(self):
        # Visi .txt, bet ne grynas .dialog.txt (paliekam .clean.dialog.txt). .named.txt + mono .txt įeina.
        # Tik paskutinių RETENTION_DAYS dienų; rikiuota pagal ĮRAŠYMO datą (sena->nauja, naujausias apačioj).
        cutoff = (datetime.now().date() - timedelta(days=RETENTION_DAYS - 1))
        fs = [f for f in REC.glob("*.txt")
              if not (f.name.endswith(".dialog.txt") and not f.name.endswith(".clean.dialog.txt"))
              and self.file_dt(f).date() >= cutoff]
        return sorted(fs, key=self.file_dt)

    def sep_for(self, f):
        m = NAME_TS.search(f.name)
        if m:
            src = m.group(1).upper()
            ts = datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
            return f"\n// ───────────────  {ts} · {src} · {f.stem}  ───────────────\n\n"
        return f"\n// ───────────────  {f.stem}  ───────────────\n\n"

    def append_line(self, raw):
        end = self.buf.get_end_iter()
        m = LINE.match(raw)
        if m:
            t, spk, txt = m.groups(); spk = spk.strip()
            self.buf.insert_with_tags(self.buf.get_end_iter(), f"[{t}] ", self.t_time)
            self.buf.insert_with_tags(self.buf.get_end_iter(), f"{spk}: ", self.spk_tag(spk))
            self.buf.insert(self.buf.get_end_iter(), txt + "\n")
        else:
            self.buf.insert(end, raw + "\n")

    def expire_oldest(self):
        f0 = self.order.pop(0)
        start = self.buf.get_iter_at_mark(self.marks[f0])
        end = (self.buf.get_iter_at_mark(self.marks[self.order[0]]) if self.order
               else self.buf.get_end_iter())
        self.buf.delete(start, end)
        self.buf.delete_mark(self.marks.pop(f0))
        self.seen.pop(f0, None)

    def refresh(self):
        # 1) Trimint senas sesijas iš VIRŠAUS (iškritusias iš RETENTION_DAYS lango)
        cutoff = datetime.now().date() - timedelta(days=RETENTION_DAYS - 1)
        while self.order and self.file_dt(self.order[0]).date() < cutoff:
            self.expire_oldest()
        # 2) Pridėti naujus / papildytus (sena->nauja, naujausias apačioj)
        added = False
        for f in self.files():
            try:
                size = f.stat().st_size
            except OSError:
                continue
            prev = self.seen.get(f)
            if prev is None:
                # nauja sesija — žymeklis (trimingui) + skyriklis + turinys
                self.marks[f] = self.buf.create_mark(None, self.buf.get_end_iter(), True)
                self.order.append(f)
                self.buf.insert_with_tags(self.buf.get_end_iter(), self.sep_for(f), self.t_sep)
                for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    self.append_line(ln)
                self.seen[f] = size; added = True
            elif size > prev:
                # failas papildytas — tik naujas gabalas
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(prev); new = fh.read()
                for ln in new.splitlines():
                    self.append_line(ln)
                self.seen[f] = size; added = True
        if added:
            if len(self.search.get_text()) >= 3:
                self.highlight_all()   # paryškinti ir naują tekstą
            if self.autoscroll:
                GLib.idle_add(self.scroll_end)
        self.status.set_text(f"Rodoma {len(self.order)} sesijų (pask. {RETENTION_DAYS} d.) · "
                             f"kalbėtojų: {len(self.spk_tags)} · "
                             f"{'seka naujus' if self.autoscroll else 'nestabdoma'}")
        return True

    def scroll_end(self):
        self.tv.scroll_to_mark(self.buf.get_insert(), 0, False, 0, 0)
        end = self.buf.get_end_iter(); self.buf.place_cursor(end)
        self.tv.scroll_to_iter(end, 0, False, 0, 0)
        return False

    def copy_all(self, _):
        s, e = self.buf.get_bounds()
        txt = self.buf.get_text(s, e, True)
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(txt, -1)
        self.status.set_text("✓ Nukopijuota viskas į iškarpinę")



if __name__ == "__main__":
    w = TextView()
    w.connect("destroy", Gtk.main_quit)
    w.show_all()
    Gtk.main()
