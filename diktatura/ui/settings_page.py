"""Diktatūra — ⚙ Nustatymai (pagrindinio lango skiltis).

Laukai generuojami iš config.SCHEMA (grupės, tipai, ribos, lietuviški paaiškinimai) — naujas nustatymas schemoje
automatiškai atsiranda ir čia. Viršuje — įrašymo režimas (VOX / Slack / išjungta; systemd per diktatura.services).
„Išsaugoti": validacija (klaida rodoma prie lauko, failas nekeičiamas) -> config.save (atominis rašymas).
Daemon'ai nustatymus perskaito patys (VOX kas ~5 s, Slack kiekvieną ciklą) — restarto nereikia.
„Atkurti numatytus" -> config/diktatura.conf.default.
"""
from diktatura import config, services
from diktatura.ui.gtk import Gdk, Gtk, button, label

MODES = ("vox", "slack", "off")


class SettingsPage(Gtk.Box):
    def __init__(self, win=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.widgets = {}           # KEY -> Gtk widget
        self.errors = {}            # KEY -> klaidos Gtk.Label
        self.mode_btns = {}
        self._loading = False
        self.loaded_mode = None

        sw = self.sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for m in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{m}")(16)
        body.pack_start(label("Pakeitimai taikomi be restarto: VOX perskaito nustatymus kas ~5 s, Slack — kas ciklą, "
                              "teksto langas — iškart.", css="dk-help", wrap=True), False, False, 0)
        body.pack_start(self._mode_frame(), False, False, 0)
        groups = []
        for s in config.SCHEMA:
            if s.group not in groups:
                groups.append(s.group)
        for g in groups:
            body.pack_start(self._group_frame(g, [s for s in config.SCHEMA if s.group == g]), False, False, 0)
        sw.add(body)
        self.pack_start(sw, True, True, 0)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(bar, f"set_margin_{m}")(10)
        self.msg = label("", wrap=True)
        bar.pack_start(self.msg, True, True, 0)
        bar.pack_start(button("Atkurti numatytus", self.on_reset_clicked,
                              "Grąžinti visas reikšmes į numatytąsias (config/diktatura.conf.default)"), False, False, 0)
        self.btn_save = button("Išsaugoti", self.save, css="suggested-action")
        bar.pack_start(self.btn_save, False, False, 0)
        self.pack_start(Gtk.Separator(), False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.load()

    # ── kūrimas ──
    def _frame(self, title):
        fr = Gtk.Frame()
        fr.set_label_widget(label(title, css="dk-title"))
        grid = Gtk.Grid(column_spacing=16, row_spacing=4)
        for m in ("top", "bottom", "start", "end"):
            getattr(grid, f"set_margin_{m}")(12)
        fr.add(grid)
        return fr, grid

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
            grid.attach(label(desc, css="dk-help", wrap=True), 1, i, 1, 1)
        return fr

    def _group_frame(self, group, settings):
        fr, grid = self._frame(group)
        row = 0
        for s in settings:
            w = self._widget(s)
            self.widgets[s.key] = w
            name = label(s.label)
            name.set_tooltip_text(s.key)
            name.set_hexpand(True)
            grid.attach(name, 0, row, 1, 1)
            w.set_halign(Gtk.Align.END)
            grid.attach(w, 1, row, 1, 1)
            if s.help:
                grid.attach(label(s.help, css="dk-help", wrap=True), 0, row + 1, 2, 1)
            err = label("", css="dk-error", wrap=True)
            err.set_no_show_all(True)
            self.errors[s.key] = err
            grid.attach(err, 0, row + 2, 2, 1)
            row += 3
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

    # ── reikšmės ──
    def set_value(self, key, value) -> None:
        s, w = config.BY_KEY[key], self.widgets[key]
        if s.kind == "bool":
            w.set_active(bool(value))
        elif s.kind == "choice":
            w.set_active_id(str(value))
        else:
            w.set_value(float(value))

    def get_value(self, key) -> str:
        s, w = config.BY_KEY[key], self.widgets[key]
        if s.kind == "bool":
            return "1" if w.get_active() else "0"
        if s.kind == "choice":
            return w.get_active_id() or ""
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

    def on_shown(self) -> None:
        if not self.dirty():
            self.load()                         # galėjo pasikeisti per `make set`

    def dirty(self) -> bool:
        return self.values() != getattr(self, "saved", {}) or self.selected_mode() != self.loaded_mode

    def _changed(self) -> None:
        if not self._loading:
            self.set_msg("Yra neišsaugotų pakeitimų" if self.dirty() else "")

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
        try:
            config.save(vals)
        except (ValueError, OSError) as e:
            self.set_msg(f"✗ Neišsaugota: {e}", "dk-error")
            return False
        notes = ["✓ Išsaugota — taikoma be restarto"]
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

    def on_reset_clicked(self) -> None:
        dlg = Gtk.MessageDialog(transient_for=self.get_toplevel() if self.win else None, modal=True,
                                message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO,
                                text="Atkurti numatytus nustatymus?")
        dlg.format_secondary_text("Visos reikšmės bus grąžintos į numatytąsias. Įrašymo režimas nesikeis.")
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.YES:
            self.reset_to_defaults()

    def reset_to_defaults(self) -> None:
        config.reset()
        self.load()
        self.set_msg("✓ Atkurti numatytieji nustatymai", "dk-ok")
