"""Diktatūra — ⏳ Transkripcijos eiga: modalinis langelis (kaip 📊 Statistika). Atidaromas iš Teksto skilties
(„⏳ Transkripcija"), ikonos meniu ir `python3 -m diktatura.ui.app --progress`.

Kaip Midnight Commander kopijuojant katalogą: dvi juostos — DABARTINIS failas ir VISA EILĖ; prie kiekvienos praėjęs
ir likęs laikas bei numatoma pabaiga (laikrodžiu). Žemiau — eilėje laukiantys su savo prognozėmis. Kas sekundę
perskaičiuojama (diktatura.progress.snapshot) — kai CPU apkrautas, prognozė ilgėja pati.
„⏭ Praleisti šį" / „⏹ Sustabdyti viską" — su patvirtinimu (numatytasis — „Atšaukti"); sustabdyti failai lieka be
teksto — juos paims naktinis (01:30) arba `make transcribe-pending`.
🌊 Dabartinio failo banga (smailės skaičiuojamos transkripcijos pradžioje): jau apdorota dalis — ryški, likusi — išblukusi
(stereo: pirma „Tu", tada kolegos).
"""
from diktatura import progress, waveform
from diktatura.ui.gtk import GLib, Gtk, Pango, label
from diktatura.ui.themes import LIGHT_PALETTE
from diktatura.ui.waveform_view import WaveformView

SKIP, STOP = 1, 2


class ProgressDialog:
    def __init__(self, parent=None, snapshot_fn=None, skip_fn=None, stop_fn=None, interval_ms=1000):
        self.snapshot_fn = snapshot_fn or progress.snapshot
        self.skip_fn = skip_fn or progress.skip_current
        self.stop_fn = stop_fn or progress.stop_all
        self.interval_ms = interval_ms
        self.snap = None
        self.message = ""
        self._timer = None
        dlg = self.dlg = Gtk.Dialog(title="⏳ Transkripcija", transient_for=parent, modal=True)
        dlg.set_default_size(600, -1)
        self.b_skip = dlg.add_button("⏭ Praleisti šį", SKIP)
        self.b_skip.set_tooltip_text("Nutraukti dabartinį failą — eilė tęsiasi; failas liks be teksto (naktinis 01:30)")
        self.b_stop = dlg.add_button("⏹ Sustabdyti viską", STOP)
        self.b_stop.set_tooltip_text("Nutraukti dabartinį ir visus laukiančius — liks be teksto (naktinis 01:30)")
        self.b_stop.get_style_context().add_class("destructive-action")
        dlg.add_button("Uždaryti", Gtk.ResponseType.CLOSE)
        dlg.set_default_response(Gtk.ResponseType.CLOSE)

        box = dlg.get_content_area()
        box.set_spacing(6)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(14)
        self.lbl_idle = label("", wrap=True)
        self.lbl_file = label("", css="dk-title")
        self.lbl_file.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.lbl_phase = label("", wrap=True)
        self.bar_file = Gtk.ProgressBar(show_text=True)
        self.bar_file.get_style_context().add_class("dk-bar")
        self.lbl_file_eta = label("", wrap=True)
        self.wave = WaveformView(height=84)
        self.wave.set_no_show_all(True)
        pal = getattr(getattr(parent, "theme", None), "palette", LIGHT_PALETTE)
        self.wave.set_colors(pal[0], pal[1])
        self._wave_key = None
        self.lbl_total = label("", css="dk-title")
        self.bar_total = Gtk.ProgressBar(show_text=True)
        self.bar_total.get_style_context().add_class("dk-bar")
        self.lbl_total_eta = label("", wrap=True)
        self.lbl_slow = label("", wrap=True)
        self.lbl_msg = label("", css="dk-ok", wrap=True)
        self.model = Gtk.ListStore(str, str, str, str)
        tv = Gtk.TreeView(model=self.model)
        for i, title in enumerate(("Failas", "Garsas", "≈ Truks", "")):
            cell = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(title, cell, text=i)
            if i == 0:
                cell.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
                col.set_expand(True)
            tv.append_column(col)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(140)
        sw.add(tv)
        self.exp_queue = Gtk.Expander(label="Eilėje")
        self.exp_queue.add(sw)
        self.exp_queue.set_expanded(True)
        self.note = label("", css="dk-help", wrap=True)
        self.cur_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for w in (self.lbl_file, self.lbl_phase, self.wave, self.bar_file, self.lbl_file_eta):
            self.cur_box.pack_start(w, False, False, 0)
        self.tot_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for w in (Gtk.Separator(), self.lbl_total, self.bar_total, self.lbl_total_eta, self.lbl_slow):
            self.tot_box.pack_start(w, False, False, 0)
        for w in (self.lbl_idle, self.cur_box, self.tot_box, self.exp_queue, self.lbl_msg, self.note):
            box.pack_start(w, w is self.exp_queue, w is self.exp_queue, 0)

    # ── vaizdas ──
    def fill(self, snap) -> None:
        self.snap = snap
        now = snap.now
        j = snap.running
        self.lbl_idle.set_visible(not snap.active)
        if not snap.active:
            idle = "Šiuo metu niekas netranskribuojama."
            if snap.waiting_night:
                secs = sum(progress.audio_info(f)[0] for f in snap.waiting_night)
                idle += (f"\nBe teksto: {len(snap.waiting_night)} įr. ({progress.fmt_clock(secs)} garso) — "
                         "transkribuos naktinis 01:30 arba make transcribe-pending.")
            self.lbl_idle.set_text(idle)
        self.cur_box.set_visible(j is not None)
        if j is not None:
            self.lbl_file.set_text(f"{j.name} · {progress.fmt_clock(j.audio_sec)} garso")
            self.lbl_phase.set_text(progress.phase_text(j)
                                    + ("" if j.exact else " (eiga nežinoma — prognozė tik pagal laiką)"))
            self.bar_file.set_fraction(j.fraction)
            self.bar_file.set_text(f"{int(j.fraction * 100)} %")
            self.lbl_file_eta.set_text(f"Praėjo {progress.fmt_clock(now - j.start)} · liko "
                                       f"{progress.fmt_eta(j.left, now)}")
        self.fill_wave(j)
        self.tot_box.set_visible(snap.active)
        if snap.active:
            n = len(snap.jobs)
            self.lbl_total.set_text(f"Visa eilė: {n} f. · {progress.fmt_clock(snap.audio_total)} garso"
                                    + (f" · jau baigta {snap.batch_done}" if snap.batch_done else ""))
            self.bar_total.set_fraction(snap.total_fraction)
            self.bar_total.set_text(f"{int(snap.total_fraction * 100)} %")
            self.lbl_total_eta.set_text(f"Liko viskam {progress.fmt_eta(snap.left, now)}")
            slow = ""
            if abs(snap.slow - 1.0) > 0.15:
                slow = (f"Dabar {snap.slow:.1f}× {'lėčiau' if snap.slow > 1 else 'greičiau'} nei įprastai "
                        f"({'CPU apkrautas kitų programų?' if snap.slow > 1 else 'CPU laisvas'}) — eilės prognozė "
                        "pakoreguota.")
            self.lbl_slow.set_text(slow)
            self.lbl_slow.set_visible(bool(slow))
        self.model.clear()
        for q in snap.queued:
            self.model.append([q.name, progress.fmt_clock(q.audio_sec), progress.fmt_left(q.left),
                               "naktinis" if q.state == "pending" else ""])
        self.exp_queue.set_label(f"Eilėje ({len(snap.queued)})")
        self.exp_queue.set_visible(bool(snap.queued))
        self.b_skip.set_sensitive(j is not None and not j.server)
        self.b_skip.set_tooltip_text("ASR serverio darbo nutraukti negalima — išjunk ASR serverį arba palauk"
                                     if j is not None and j.server else
                                     "Nutraukti dabartinį failą — eilė tęsiasi; failas liks be teksto (naktinis 01:30)")
        self.b_stop.set_sensitive(snap.active)
        n_hist = snap.rates.get("n", 0) if snap.rates else 0
        self.note.set_text(
            ("Prognozė — pagal tai, kiek šis kompiuteris užtruko anksčiau "
             + (f"({n_hist} transkripc.)" if n_hist else "(istorijos dar nėra — kol kas apytikriai)")
             + " ir pagal tikrą dabartinį greitį; kai CPU apkrautas kitų programų, laikas ilgėja. Sustabdyti failai "
             "lieka be teksto — juos paims naktinis (01:30) arba make transcribe-pending."))
        self.lbl_msg.set_text(self.message)
        self.lbl_msg.set_visible(bool(self.message))

    def fill_wave(self, j) -> None:
        """Dabartinio failo banga ir kiek jos jau apdorota; smailių nėra (dar skaičiuojamos / sena versija) — slepiama."""
        pk = None
        if j is not None:
            pf = progress.peaks_file(j)
            try:
                st = pf.stat()
                key = (str(pf), st.st_mtime_ns, st.st_size)
            except OSError:
                key = None
            if key is not None and key == self._wave_key:
                pk = self.wave.peaks
            elif key is not None:
                pk = waveform.read(pf)
                self._wave_key = key if pk is not None else None
                if pk is not None:
                    self.wave.set_peaks(pk)
        self.wave.set_visible(pk is not None)
        if pk is not None:
            self.wave.set_processed(progress.processed_secs(j, pk.duration, pk.channels))

    def refresh(self) -> bool:
        try:
            self.fill(self.snapshot_fn())
        except Exception as e:                               # eiga — tik informacija; langas nelūžta
            self.lbl_idle.set_text(f"⚠ Nepavyko nuskaityti eigos: {e}")
            self.lbl_idle.show()
        return True

    # ── veiksmai ──
    def run_dialog(self, dlg) -> int:
        """Atskirai — testai jį pakeičia (dialogo nerodo)."""
        return dlg.run()

    def confirm(self, title: str, text: str, ok_label: str) -> bool:
        d = Gtk.MessageDialog(transient_for=self.dlg, modal=True, message_type=Gtk.MessageType.WARNING,
                              buttons=Gtk.ButtonsType.NONE, text=title)
        d.format_secondary_text(text)
        d.add_button("Atšaukti", Gtk.ResponseType.CANCEL)
        d.add_button(ok_label, Gtk.ResponseType.OK).get_style_context().add_class("destructive-action")
        d.set_default_response(Gtk.ResponseType.CANCEL)
        resp = self.run_dialog(d)
        d.destroy()
        return resp == Gtk.ResponseType.OK

    def on_response(self, resp) -> bool:
        """Mygtuko paspaudimas -> True, jei langas lieka atidarytas."""
        snap = self.snap or self.snapshot_fn()
        if resp == SKIP and snap.running is not None:
            j = snap.running
            if self.confirm("Praleisti šį failą?",
                            f"{j.name}: praėjo {progress.fmt_clock(snap.now - j.start)}, liko "
                            f"{progress.fmt_left(j.left)}. Atliktas darbas dings; failas liks be teksto — jį paims "
                            "naktinis (01:30). Eilė tęsis.", "Praleisti"):
                self.message = self.skip_fn(snap)
            self.refresh()
            return True
        if resp == STOP and snap.active:
            if self.confirm("Sustabdyti visas transkripcijas?",
                            f"Bus nutraukta {len(snap.jobs)} f. (liko {progress.fmt_left(snap.left)}). Visi liks be "
                            "teksto — juos paims naktinis (01:30) arba make transcribe-pending.", "Sustabdyti"):
                self.message = self.stop_fn(snap)
            self.refresh()
            return True
        return resp in (SKIP, STOP)

    def _tick(self) -> bool:
        if self._timer is None:
            return False
        return self.refresh()

    def run(self) -> None:
        self.refresh()
        self.dlg.show_all()
        self.fill(self.snap) if self.snap else None          # show_all atidengė paslėptas dalis
        self._timer = GLib.timeout_add(self.interval_ms, self._tick)
        try:
            while self.on_response(self.run_dialog(self.dlg)):
                pass
        finally:
            GLib.source_remove(self._timer)
            self._timer = None
            self.dlg.destroy()
