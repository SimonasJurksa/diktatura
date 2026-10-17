"""Diktatūra — ⚙ Nustatymai (pagrindinio lango skiltis).

Laukai generuojami iš config.SCHEMA (grupės, tipai, ribos, lietuviški paaiškinimai) — naujas nustatymas schemoje
automatiškai atsiranda ir čia. Viršuje — įrašymo režimas (VOX / Slack / išjungta; systemd per diktatura.services).
„Išsaugoti": validacija (klaida rodoma prie lauko, failas nekeičiamas) -> config.save (atominis rašymas).
Daemon'ai nustatymus perskaito patys (VOX kas ~5 s, Slack kiekvieną ciklą) — restarto nereikia. Pakeista tema
(THEME, grupė „Išvaizda") pritaikoma visam langui iškart išsaugojus (MainWindow.apply_theme, diktatura.ui.themes).
Grupėje „Archyvas" — seno garso trynimas (AUDIO_CLEANUP, diktatura.cleanup): po laukais gyva suvestinė (kiek užima
įrašai ir ką ištrintų lange pasirinkti, dar neišsaugoti nustatymai), nereikalingas laukas (dienos / GB) pilkas.
Pakeitus trynimo nustatymus, „Išsaugoti" prieš trinant paklausia (sąrašas, kiek ir kokio laikotarpio) ir trina iškart.
„Sekami aplankai" (po „Transkripcija"; diktatura.sources) — aplankai su telefono / laikrodžio / studijos įrašais:
➕ pridėti (pavadinimas, su poaplankiais, ar transkribuoti jau esančius), įjungti / išjungti, ✕ nebesekti. Taikoma
iškart (ne per „Išsaugoti"); pirmas aplankas įjungia diktatura-sources.timer, Teksto skiltis gauna skirtuką.
🔍 Paieška viršuje (Ctrl+F): pagal nustatymo pavadinimą, paaiškinimą ar raktą (be didžiųjų raidžių ir be
lietuviškų raidžių skirtumo — „zodziai" randa „žodžiai"); lieka tik grupės ir nustatymai su atitikmenimis, rastas
tekstas paryškinamas; grupės pavadinimo atitikmuo rodo visą grupę. Esc — išvalyti.
Apačioje, toli nuo „Išsaugoti" — „Atstatymas ir duomenys": „Atkurti numatytus nustatymus…" (patvirtinimas su
pasikeisiančių nustatymų sąrašu -> config/diktatura.conf.default) ir „Ištrinti įrašus ir tekstus…" (patvirtinimas su
pasirinkimais: įrašai ir tekstai / laukiantys vardo balsai / vardų atpažinimas — diktatura.reset). Abiejuose
dialoguose numatytasis mygtukas — „Atšaukti".
"""
import subprocess
import unicodedata
from html import escape
from pathlib import Path

from diktatura import cleanup, config, reset, services, sources
from diktatura.ui.gtk import Gdk, Gtk, Pango, button, label

MODES = ("vox", "slack", "off")
CLEANUP_KEYS = ("AUDIO_CLEANUP", "AUDIO_KEEP_DAYS", "AUDIO_MAX_GB", "AUTOTRANSCRIBE")


class SettingsPage(Gtk.Box):
    def __init__(self, win=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.widgets = {}           # KEY -> Gtk widget
        self.errors = {}            # KEY -> klaidos Gtk.Label
        self.mode_btns = {}
        self._loading = False
        self.loaded_mode = None
        self._cleanup_shown = None
        self.cleanup_info = None
        self.frames = []            # [(Gtk.Frame, pavadinimo Gtk.Label, [elementai])] — paieškai
        self._items = None          # dabar kuriamos grupės elementai (žr. _item)

        top = Gtk.Box(spacing=8)
        for m in ("top", "start", "end"):
            getattr(top, f"set_margin_{m}")(10)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Ieškoti nustatymų… (pavadinimas ar paaiškinimas, Ctrl+F)")
        self.search.connect("search-changed", lambda _w: self.apply_search())
        self.search.connect("stop-search", lambda _w: self.search.set_text(""))
        top.pack_start(self.search, True, True, 0)
        self.lbl_found = label("", css="dk-help")
        top.pack_start(self.lbl_found, False, False, 0)
        self.pack_start(top, False, False, 0)

        sw = self.sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for m in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{m}")(16)
        self.intro = label("Pakeitimai taikomi be restarto: VOX perskaito nustatymus kas ~5 s, Slack — kas ciklą, "
                           "teksto langas — iškart.", css="dk-help", wrap=True)
        body.pack_start(self.intro, False, False, 0)
        body.pack_start(self._mode_frame(), False, False, 0)
        groups = []
        for s in config.SCHEMA:
            if s.group not in groups:
                groups.append(s.group)
        for g in groups:
            body.pack_start(self._group_frame(g, [s for s in config.SCHEMA if s.group == g]), False, False, 0)
            if g == "Transkripcija":
                body.pack_start(self._sources_frame(), False, False, 0)
        body.pack_start(self._reset_frame(), False, False, 0)
        sw.add(body)
        self.pack_start(sw, True, True, 0)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(bar, f"set_margin_{m}")(10)
        self.msg = label("", wrap=True)
        bar.pack_start(self.msg, True, True, 0)
        self.btn_save = button("Išsaugoti", self.save, css="suggested-action")
        bar.pack_start(self.btn_save, False, False, 0)
        self.pack_start(Gtk.Separator(), False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.load()

    # ── kūrimas ──
    def _frame(self, title):
        fr = Gtk.Frame()
        title_lbl = label(title, css="dk-title")
        fr.set_label_widget(title_lbl)
        grid = Gtk.Grid(column_spacing=16, row_spacing=4)
        for m in ("top", "bottom", "start", "end"):
            getattr(grid, f"set_margin_{m}")(12)
        fr.add(grid)
        self._items = []
        self.frames.append((fr, title_lbl, self._items))
        return fr, grid

    def _item(self, widgets, key="") -> None:
        """Paieškos elementas: kartu rodomi / slepiami valdikliai (pavadinimas, laukas, paaiškinimas…); key — raktas."""
        self._items.append({"widgets": list(widgets), "key": key})

    def _mode_frame(self):
        fr, grid = self._frame("Įrašymo režimas")
        first = None
        for i, mode in enumerate(MODES):
            title, _, desc = services.MODE_LABELS[mode].partition(" — ")
            rb = Gtk.RadioButton.new_with_label_from_widget(first, title)
            first = first or rb
            rb.connect("toggled", lambda *_: self._changed())
            self.mode_btns[mode] = rb
            grid.attach(rb, 0, i, 1, 1)
            d = label(desc, css="dk-help", wrap=True)
            grid.attach(d, 1, i, 1, 1)
            self._item([rb, d], mode)
        return fr

    # ── sekami aplankai ──
    def _sources_frame(self):
        fr, grid = self._frame("Sekami aplankai")
        grid.attach(label("Aplankai, kuriuose kaupiasi garso įrašai — pvz. sinchronizuojami iš telefono, laikrodžio, "
                          "diktofono ar studijos mikrofono. Nauji failai transkribuojami pagal „Kada transkribuoti\" "
                          "(iškart — per ~2 min, arba naktį), kalbėtojai atpažįstami pagal balsus. Tekstai laikomi "
                          "atskirai — kiekvienam aplankui savas skirtukas Tekste. Tavo failai nekeičiami ir netrinami.",
                          css="dk-help", wrap=True), 0, 0, 1, 1)
        self.src_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        grid.attach(self.src_list, 0, 1, 1, 1)
        self.btn_add_src = button("➕ Pridėti aplanką…", self.on_add_source,
                                  "Pasirinkti aplanką su garso failais (m4a, mp3, wav, ogg, opus, flac…)")
        self.btn_add_src.set_halign(Gtk.Align.START)
        grid.attach(self.btn_add_src, 0, 2, 1, 1)
        self._item([grid])                          # eilutės kuriamos iš naujo — ieškoma visuose jų užrašuose
        self.fill_sources()
        return fr

    def fill_sources(self) -> None:
        for ch in self.src_list.get_children():
            ch.destroy()
        items = sources.load()
        if not items:
            self.src_list.pack_start(label("Kol kas nesekama jokių aplankų.", css="dk-help"), False, False, 0)
        for s in items:
            c = sources.counts(s)
            row = Gtk.Box(spacing=8)
            sw = Gtk.Switch()
            sw.set_active(s.enabled)
            sw.set_valign(Gtk.Align.CENTER)
            sw.set_tooltip_text("Sekti (išjungus — nauji failai netranskribuojami, tekstai lieka)")
            sw.connect("notify::active", lambda w, _p, sid=s.id: self.set_source_enabled(sid, w.get_active()))
            row.pack_start(sw, False, False, 0)
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            info.pack_start(label(s.name, css="dk-title"), False, False, 0)
            missing = "" if s.dir.is_dir() else " · ⚠ aplanko nėra"
            path = label(f"{sources.short_path(s.path)}{' (su poaplankiais)' if s.recursive else ''} · failų {c['files']}, tekstų "
                         f"{c['texts']}, laukia {c['pending']}{missing}", css="dk-help")
            path.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            info.pack_start(path, False, False, 0)
            row.pack_start(info, True, True, 0)
            row.pack_start(button("📂", lambda p=s.path: self.open_folder(p), "Atidaryti aplanką"), False, False, 0)
            row.pack_start(button("✕", lambda sid=s.id: self.on_remove_source(sid), "Nebesekti (tekstai lieka)"),
                           False, False, 0)
            self.src_list.pack_start(row, False, False, 0)
        self.src_list.show_all()

    def open_folder(self, path) -> None:
        try:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def choose_folder(self):
        """Aplanko pasirinkimas (atskirai — testai jį pakeičia). -> kelias | None."""
        dlg = Gtk.FileChooserNative.new("Pasirink aplanką su garso įrašais", self.get_toplevel() if self.win else None,
                                        Gtk.FileChooserAction.SELECT_FOLDER, "Pasirinkti", "Atšaukti")
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.ACCEPT else None
        dlg.destroy()
        return path

    def source_dialog(self, path):
        """-> (dialogas, pavadinimo laukas, „su poaplankiais", „ir jau esančius")."""
        p = Path(path)
        tmp = sources.Source("tmp", p.name, str(p), True, False)
        n = len(sources.scan(tmp))
        dlg = Gtk.Dialog(title="Sekti aplanką", transient_for=self.get_toplevel() if self.win else None, modal=True)
        dlg.add_button("Atšaukti", Gtk.ResponseType.CANCEL)
        dlg.add_button("Sekti", Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        dlg.set_default_response(Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_spacing(8)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(12)
        box.pack_start(label(str(p), css="dk-help", wrap=True), False, False, 0)
        name = Gtk.Entry()
        name.set_text(p.name[:1].upper() + p.name[1:])
        name.set_activates_default(True)
        name.set_placeholder_text("Pavadinimas (pvz. Telefonas)")
        box.pack_start(label("Pavadinimas (skirtuko Tekste):"), False, False, 0)
        box.pack_start(name, False, False, 0)
        rec = Gtk.CheckButton(label="Ir poaplankiuose")
        box.pack_start(rec, False, False, 0)
        old = Gtk.CheckButton(label=f"Transkribuoti ir jau esančius failus ({n})" if n else
                              "Transkribuoti ir jau esančius failus (dabar jų nėra)")
        old.set_active(0 < n <= 20)
        old.set_tooltip_text("Išjungus — transkribuojami tik nuo dabar atsirasiantys failai "
                             "(daug senų įrašų gali užimti CPU valandoms)")
        box.pack_start(old, False, False, 0)
        box.show_all()
        return dlg, name, rec, old

    def on_add_source(self) -> bool:
        path = self.choose_folder()
        if not path:
            return False
        dlg, name, rec, old = self.source_dialog(path)
        resp = self.run_dialog(dlg)
        vals = (name.get_text(), rec.get_active(), old.get_active())
        dlg.destroy()
        if resp != Gtk.ResponseType.OK:
            self.set_msg("Atšaukta — aplankas nepridėtas")
            return False
        return self.add_source(path, *vals)

    def add_source(self, path, name, recursive=False, include_existing=True) -> bool:
        try:
            src = sources.add(name, path, recursive, include_existing)
        except ValueError as e:
            self.set_msg(f"✗ {e}", "dk-error")
            return False
        notes = [f"✓ Sekamas aplankas „{src.name}\""]
        if not services.is_enabled(services.SOURCES_TIMER):
            ok, m = services.set_sources_timer(True)
            notes.append(m if ok else f"⚠ {m}")
        if config.load()["MODE"] == "deferred":
            notes.append("transkribuos naktį (Kada transkribuoti: naktį)")
        self.after_sources_change(" · ".join(notes))
        return True

    def set_source_enabled(self, sid, on: bool) -> None:
        if self._loading:
            return
        try:
            src = sources.update(sid, enabled=on)
        except KeyError:
            return
        if not any(s.enabled for s in sources.load()):
            services.set_sources_timer(False)
        elif on and not services.is_enabled(services.SOURCES_TIMER):
            services.set_sources_timer(True)
        self.after_sources_change(f"✓ „{src.name}\" {'sekamas' if on else 'nebesekamas (tekstai lieka)'}")

    def on_remove_source(self, sid) -> bool:
        src = sources.get(sid)
        if src is None:
            return False
        dlg = self._confirm(f"Nebesekti „{src.name}\"?",
                            f"{src.path}\nNauji failai nebebus transkribuojami, skirtukas Tekste dings. Jau gauti "
                            "tekstai lieka Diktatūros duomenyse, o tavo garso failai — nepaliesti.", "Nebesekti")
        resp = self.run_dialog(dlg)
        dlg.destroy()
        if resp != Gtk.ResponseType.OK:
            return False
        sources.remove(sid)
        if not any(s.enabled for s in sources.load()):
            services.set_sources_timer(False)
        self.after_sources_change(f"✓ „{src.name}\" nebesekamas (tekstai lieka)")
        return True

    def after_sources_change(self, msg) -> None:
        self.fill_sources()
        self.set_msg(msg, "dk-ok")
        if self.win is not None and hasattr(self.win, "reload_sources"):
            self.win.reload_sources()

    def _reset_frame(self):
        fr, grid = self._frame("Atstatymas ir duomenys")
        self.btn_defaults = button("↺ Atkurti numatytus nustatymus…", self.on_reset_clicked,
                                   "Grąžinti visas reikšmes į numatytąsias (prieš tai paklausiama)")
        self.btn_wipe = button("🗑 Ištrinti įrašus ir tekstus…", self.on_wipe_clicked,
                               "Pradėti kaupti iš naujo (prieš tai paklausiama, ką trinti)", css="destructive-action")
        rows = ((self.btn_defaults, "Visi aukščiau esantys nustatymai grįžta į numatytuosius. Įrašymo režimas nesikeičia."),
                (self.btn_wipe, "Ištrinami įrašai (garsas) ir tekstai — kaupimas prasideda iš naujo. Vardų atpažinimas "
                                "(registruoti balsai) lieka, nebent pažymėsi ir jį."))
        for i, (b, help_) in enumerate(rows):
            b.set_halign(Gtk.Align.START)
            grid.attach(b, 0, 2 * i, 1, 1)
            h = label(help_, css="dk-help", wrap=True)
            grid.attach(h, 0, 2 * i + 1, 1, 1)
            self._item([b, h])
        return fr

    def _group_frame(self, group, settings):
        fr, grid = self._frame(group)
        row = 0
        for s in settings:
            w = self._widget(s)
            self.widgets[s.key] = w
            name = label(s.label, wrap=True)        # siaurame lange (mažas ekranas, didelis šriftas) — per kelias eilutes
            name.set_tooltip_text(s.key)
            name.set_hexpand(True)
            grid.attach(name, 0, row, 1, 1)
            w.set_halign(Gtk.Align.END)
            grid.attach(w, 1, row, 1, 1)
            parts = [name, w]
            if s.help:
                h = label(s.help, css="dk-help", wrap=True)
                grid.attach(h, 0, row + 1, 2, 1)
                parts.append(h)
            err = label("", css="dk-error", wrap=True)
            err.set_no_show_all(True)
            self.errors[s.key] = err
            grid.attach(err, 0, row + 2, 2, 1)
            if s.key == "AUDIO_CLEANUP":            # suvestinė „kiek užima / ką ištrintų" — kartu su šiuo nustatymu
                self.cleanup_info = label("", wrap=True)
                parts.append(self.cleanup_info)
            self._item(parts, s.key)
            row += 3
        if self.cleanup_info is not None and self.cleanup_info.get_parent() is None:
            grid.attach(self.cleanup_info, 0, row, 2, 1)
        return fr

    def _widget(self, s):
        if s.kind == "bool":
            w = Gtk.Switch()
            w.connect("notify::active", lambda *_: self._changed())
        elif s.kind == "choice":
            w = Gtk.ComboBoxText()
            for c in s.choices:
                w.append(c, s.choice_label(c))
            w.connect("changed", lambda *_: self._changed())
        elif s.kind == "words":
            w = Gtk.Entry()
            w.set_width_chars(22)
            w.set_placeholder_text("nu,tipo")
            w.connect("changed", lambda *_: self._changed())
        else:
            step = s.step or (1 if s.kind == "int" else 0.5)
            w = Gtk.SpinButton.new_with_range(s.lo, s.hi, step)
            w.set_digits(0 if s.kind == "int" else 1)
            w.set_width_chars(7)
            w.connect("value-changed", lambda *_: self._changed())
        if s.kind != "bool":
            w.connect("scroll-event", self._scroll_page)
        return w

    def _scroll_page(self, w, ev) -> bool:
        """Pelės ratukas virš lauko slenka PUSLAPĮ (ne reikšmę), nebent laukas pažymėtas (fokusas)."""
        if w.has_focus():
            return False
        adj = self.sw.get_vadjustment()
        ok, dx, dy = ev.get_scroll_deltas()
        if not ok:
            dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(ev.direction, 0)
        adj.set_value(adj.get_value() + dy * adj.get_step_increment() * 3)
        return True

    # ── 🔍 paieška ──
    def on_key(self, ev) -> bool:
        if (ev.state & Gdk.ModifierType.CONTROL_MASK) and ev.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.search.grab_focus()
            self.search.select_region(0, -1)
            return True
        return False

    @staticmethod
    def fold(text: str) -> tuple:
        """Tekstas be didžiųjų ir lietuviškų raidžių skirtumo + kiekvieno simbolio vieta originale."""
        out, where = [], []
        for i, ch in enumerate(text):
            for c in unicodedata.normalize("NFKD", ch.casefold()):
                if not unicodedata.combining(c):
                    out.append(c)
                    where.append(i)
        return "".join(out), where

    def _labels(self, widget) -> list:
        """Visi Gtk.Label valdiklyje (mygtukų užrašai irgi)."""
        if isinstance(widget, Gtk.Label):
            return [widget]
        out = []
        if isinstance(widget, Gtk.Container):
            for c in widget.get_children():
                out += self._labels(c)
        return out

    def _mark(self, lbl, q: str) -> bool:
        """Paryškinti q (sulankstytą) žymoje; -> ar rasta. Be q — grąžina paprastą tekstą."""
        text = lbl.get_text()
        if not q:
            lbl.set_text(text)
            return False
        folded, where = self.fold(text)
        spans, pos = [], folded.find(q)
        while pos >= 0:
            spans.append((where[pos], where[pos + len(q) - 1] + 1))
            pos = folded.find(q, pos + len(q))
        if not spans:
            lbl.set_text(text)
            return False
        out, last = [], 0
        for a, b in spans:
            out.append(escape(text[last:a]))
            out.append(f'<span background="#fde047" foreground="#000000">{escape(text[a:b])}</span>')
            last = b
        out.append(escape(text[last:]))
        lbl.set_markup("".join(out))
        return True

    def apply_search(self) -> tuple:
        """Filtruoti pagal paieškos lauką. -> (rasta elementų, grupių)."""
        q = self.fold(self.search.get_text().strip())[0]
        n_items = n_frames = 0
        for fr, title, items in self.frames:
            title_hit = self._mark(title, q)
            frame_hit = False
            for it in items:
                hit = False
                for w in it["widgets"]:
                    for lbl in self._labels(w):
                        hit = self._mark(lbl, q) or hit
                hit = hit or bool(q and q in self.fold(it["key"])[0])
                show = not q or hit or title_hit
                for w in it["widgets"]:
                    w.set_visible(show)
                if q and hit:
                    n_items += 1
                frame_hit = frame_hit or show
            fr.set_visible(frame_hit)
            n_frames += bool(q and frame_hit)
        self.intro.set_visible(not q)
        self.lbl_found.set_text("" if not q else f"rasta: {n_items} · grupių: {n_frames}" if n_frames
                                else "nieko nerasta — pabandyk kitą žodį")
        return n_items, n_frames

    # ── reikšmės ──
    def set_value(self, key, value) -> None:
        s, w = config.BY_KEY[key], self.widgets[key]
        if s.kind == "bool":
            w.set_active(bool(value))
        elif s.kind == "choice":
            w.set_active_id(str(value))
        elif s.kind == "words":
            w.set_text(str(value))
        else:
            w.set_value(float(value))

    def get_value(self, key) -> str:
        s, w = config.BY_KEY[key], self.widgets[key]
        if s.kind == "bool":
            return "1" if w.get_active() else "0"
        if s.kind == "choice":
            return w.get_active_id() or ""
        if s.kind == "words":
            return w.get_text().strip()
        if s.kind == "int":
            return str(int(round(w.get_value())))
        return config.to_text(key, round(w.get_value(), 2))

    def values(self) -> dict:
        return {k: self.get_value(k) for k in self.widgets}

    def selected_mode(self) -> str:
        return next((m for m, b in self.mode_btns.items() if b.get_active()), "off")

    def load(self) -> None:
        self._loading = True
        try:
            cur = config.load()
            for k in self.widgets:
                self.set_value(k, cur[k])
            self.loaded_mode = services.recorder_mode()
            self.mode_btns[self.loaded_mode].set_active(True)
            self._clear_errors()
        finally:
            self._loading = False
        self.saved = self.values()
        self._cleanup_shown = None
        self.update_cleanup()

    def on_shown(self) -> None:
        if not self.dirty():
            self.load()                         # galėjo pasikeisti per `make set`

    def dirty(self) -> bool:
        return self.values() != getattr(self, "saved", {}) or self.selected_mode() != self.loaded_mode

    def _changed(self) -> None:
        if not self._loading:
            self.set_msg("Yra neišsaugotų pakeitimų" if self.dirty() else "")
            self.update_cleanup()

    # ── seno garso trynimas ──
    def cleanup_cfg(self, vals=None) -> dict:
        vals = vals or self.values()
        return {k: config.coerce(k, vals[k]) for k in CLEANUP_KEYS}

    def update_cleanup(self) -> None:
        """Pilki nereikalingi laukai + suvestinė „kiek užima / ką ištrintų" (perskaičiuojama tik pasikeitus)."""
        if self.cleanup_info is None or not set(CLEANUP_KEYS) <= set(self.widgets):
            return                              # dar kuriamas langas
        try:
            cfg = self.cleanup_cfg()
        except ValueError:
            return
        self.widgets["AUDIO_KEEP_DAYS"].set_sensitive(cfg["AUDIO_CLEANUP"] == cleanup.AGE)
        self.widgets["AUDIO_MAX_GB"].set_sensitive(cfg["AUDIO_CLEANUP"] == cleanup.SIZE)
        if cfg == self._cleanup_shown:
            return
        self._cleanup_shown = cfg
        self.cleanup_info.set_text(cleanup.summary(cleanup.plan(cfg)))

    def confirm_cleanup(self, p) -> bool:
        dlg = self._confirm("Ištrinti seną garsą?",
                            f"Su naujais nustatymais dabar bus ištrintas {len(p.delete)} įrašų garsas "
                            f"({cleanup.human_size(sum(r.size for r in p.delete))}, "
                            f"{p.delete[0].when:%Y-%m-%d} – {p.delete[-1].when:%Y-%m-%d}). Tekstai lieka. "
                            "Atkurti nebus galima.", "Išsaugoti ir ištrinti")
        resp = self.run_dialog(dlg)
        dlg.destroy()
        return resp == Gtk.ResponseType.OK

    def _clear_errors(self) -> None:
        for e in self.errors.values():
            e.set_text("")
            e.hide()

    def set_msg(self, text, css=None) -> None:
        ctx = self.msg.get_style_context()
        for c in ("dk-error", "dk-ok"):
            ctx.remove_class(c)
        if css:
            ctx.add_class(css)
        self.msg.set_text(text)

    # ── veiksmai ──
    def save(self) -> bool:
        vals = self.values()
        self._clear_errors()
        errs = config.validate(vals)
        if errs:
            for k, e in errs.items():
                if k in self.errors:
                    self.errors[k].set_text(e)
                    self.errors[k].show()
            self.set_msg("✗ Neišsaugota — pataisyk raudonai pažymėtus laukus", "dk-error")
            return False
        old = getattr(self, "saved", {})
        clean = None
        if any(vals.get(k) != old.get(k) for k in CLEANUP_KEYS):
            clean = self.cleanup_cfg(vals)
            p = cleanup.plan(clean)
            if p.delete and not self.confirm_cleanup(p):
                self.set_msg("Atšaukta — nustatymai neišsaugoti, nieko neištrinta")
                return False
        try:
            config.save(vals)
        except (ValueError, OSError) as e:
            self.set_msg(f"✗ Neišsaugota: {e}", "dk-error")
            return False
        notes = ["✓ Išsaugota — taikoma be restarto"]
        if clean is not None:
            done = cleanup.run(clean)
            if done.delete:
                notes.append(f"🧹 ištrinta seno garso: {len(done.delete)} įr. "
                             f"({cleanup.human_size(sum(r.size for r in done.delete))})")
            self._cleanup_shown = None
            self.update_cleanup()
        if vals.get("THEME") != getattr(self, "saved", {}).get("THEME") and self.win is not None:
            self.win.apply_theme(vals.get("THEME"))
            notes.append(f"tema: {config.BY_KEY['THEME'].choice_label(vals.get('THEME'))}")
        if vals.get("ASR_SERVER") != getattr(self, "saved", {}).get("ASR_SERVER"):
            ok, m = services.set_asr_server(vals.get("ASR_SERVER") == "1")
            notes.append(m if ok else f"⚠ {m}")
        if vals.get("MODE") == "deferred" and not services.is_enabled(services.TIMER):
            ok, m = services.set_timer(True)
            notes.append(m if ok else f"⚠ naktinio timer'io įjungti nepavyko: {m}")
        mode = self.selected_mode()
        if mode != self.loaded_mode:
            ok, m = services.set_recorder_mode(mode)
            if not ok:
                self.set_msg(f"✓ Nustatymai išsaugoti, bet ✗ {m}", "dk-error")
                self.loaded_mode = services.recorder_mode()
                self.saved = vals
                return False
            self.loaded_mode = mode
            notes.append(m)
        self.saved = vals
        self.set_msg(" · ".join(notes), "dk-ok")
        return True

    # ── atstatymas ──
    def run_dialog(self, dlg) -> int:
        """Atskirai — testai jį pakeičia (dialogo nerodo)."""
        return dlg.run()

    def _confirm(self, title, text, ok_label):
        dlg = Gtk.MessageDialog(transient_for=self.get_toplevel() if self.win else None, modal=True,
                                message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE, text=title)
        dlg.format_secondary_text(text)
        dlg.add_button("Atšaukti", Gtk.ResponseType.CANCEL)
        ok = dlg.add_button(ok_label, Gtk.ResponseType.OK)
        ok.get_style_context().add_class("destructive-action")
        dlg.set_default_response(Gtk.ResponseType.CANCEL)             # Enter — atšaukia
        return dlg

    def default_changes(self) -> list:
        """Kurie nustatymai pasikeistų (lyginama su tuo, kas dabar lange, įskaitant neišsaugotus)."""
        dflt, cur = config.defaults(), self.values()
        return [k for k in self.widgets if config.coerce(k, cur[k]) != config.coerce(k, dflt.get(k, ""))]

    def on_reset_clicked(self) -> bool:
        changes = self.default_changes()
        if not changes:
            self.set_msg("Visi nustatymai jau numatytieji — keisti nėra ką", "dk-ok")
            return False
        names = [config.BY_KEY[k].label for k in changes]
        shown = ", ".join(names[:6]) + (f" ir dar {len(names) - 6}" if len(names) > 6 else "")
        dlg = self._confirm("Atkurti numatytus nustatymus?",
                            f"Pasikeis {len(changes)} nustatym.: {shown}.\nĮrašymo režimas nesikeis.", "Atkurti")
        resp = self.run_dialog(dlg)
        dlg.destroy()
        if resp != Gtk.ResponseType.OK:
            self.set_msg("Atšaukta — nustatymai nepakeisti")
            return False
        self.reset_to_defaults()
        return True

    def reset_to_defaults(self) -> None:
        config.reset()
        self.load()
        if self.win is not None:
            self.win.apply_theme()
        self.set_msg("✓ Atkurti numatytieji nustatymai", "dk-ok")

    def wipe_dialog(self):
        """-> (dialogas, {kategorija: Gtk.CheckButton}). Numatytai pažymėta tik „įrašai ir tekstai"."""
        p = reset.plan()
        rec, pend, voices = p[reset.RECORDINGS], p[reset.PENDING], p[reset.VOICES]
        dlg = self._confirm("Ištrinti įrašus ir tekstus?",
                            "Pasirink, ką ištrinti. Atkurti nebus galima. Nustatymai ir modeliai lieka.", "Ištrinti")
        area = dlg.get_message_area()
        checks = {}
        for cat, text, on in (
                (reset.RECORDINGS, f"Įrašai ir tekstai — {rec.count} failų ({reset.human_size(rec.size)}), "
                                   "žymės ir statistika", True),
                (reset.PENDING, f"Nežinomi balsai, laukiantys vardo — {pend.count}", False),
                (reset.VOICES, f"Vardų atpažinimas — registruoti balsai ir tavo balsas ({voices.count}); "
                               "tada žmones reikės įvardinti iš naujo", False)):
            cb = Gtk.CheckButton(label=text)
            cb.set_active(on)
            cb.connect("toggled", lambda *_: dlg.set_response_sensitive(
                Gtk.ResponseType.OK, any(c.get_active() for c in checks.values())))
            checks[cat] = cb
            area.pack_start(cb, False, False, 0)
        if p["kept"]:
            area.pack_start(label(f"Dabar rašomas ar transkribuojamas įrašas ({len(p['kept'])} f.) bus paliktas.",
                                  css="dk-help", wrap=True), False, False, 0)
        area.show_all()
        return dlg, checks

    def on_wipe_clicked(self) -> bool:
        dlg, checks = self.wipe_dialog()
        resp = self.run_dialog(dlg)
        chosen = [c for c, cb in checks.items() if cb.get_active()]
        dlg.destroy()
        if resp != Gtk.ResponseType.OK or not chosen:
            self.set_msg("Atšaukta — nieko neištrinta")
            return False
        return self.wipe(chosen)

    def wipe(self, categories) -> bool:
        res = reset.run(categories)
        what = {reset.RECORDINGS: "įrašų ir tekstų failų", reset.PENDING: "laukiančių balsų",
                reset.VOICES: "registruotų balsų"}
        parts = [f"{what[c]}: {n}" for c, n in res["deleted"].items()]
        msg = "✓ Ištrinta — " + ", ".join(parts)
        if res["kept"]:
            msg += f" · palikta (vyksta): {len(res['kept'])} f."
        if res["errors"]:
            msg += f" · ⚠ nepavyko: {len(res['errors'])}"
        self.set_msg(msg, "dk-error" if res["errors"] else "dk-ok")
        if self.win is not None:
            self.win.text.refresh()
            self.win.training.reload()
        return not res["errors"]
