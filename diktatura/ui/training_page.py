"""Diktatūra — 🎓 Apmokymai: nežinomų balsų vardai (pagrindinio lango skiltis).

Kai pokalbyje kalba neatpažintas balsas, transkripcija jį pažymi „Kolega?nezN" ir išsaugo balso pavyzdį
(<duomenys>/speakers/pending). Čia: paklausyti (▶), pamatyti, ką ir kada sakė (kontekstas iš transkripcijų),
įrašyti vardą (automatinis užbaigimas iš esamų) -> balsas registruojamas, pending pašalinamas, VISOSE
transkripcijose „Kolega?nezN" -> vardas, pereinama prie kito. „Ne žmogus / triukšmas" -> pavyzdys ištrinamas ir
panašus garsas nebesiūlomas. Apačioje — registruoti balsai: pervadinti / sujungti (pvz. „Ruta" -> „Rūta") / pamiršti.

Duomenų logika — diktatura.speakers.store (tik stdlib). Grojimas — `paplay` (testams DIKTATURA_PLAYER).
"""
import os
import shlex
import subprocess
from datetime import datetime

from diktatura import sessions
from diktatura.speakers import store
from diktatura.ui.gtk import GLib, Gtk, button, label

INTRO = ("Kai pokalbyje kalba žmogus, kurio balso Diktatūra dar nežino, tekste jis pažymimas "
         "<b>„Kolega?nezN“</b>, o jo balso pavyzdys išsaugomas čia. Paklausyk, perskaityk, ką jis sakė, ir įrašyk "
         "vardą — nuo šiol šis balsas bus atpažįstamas automatiškai, o jau esamuose tekstuose „Kolega?nezN“ "
         "pasikeis į vardą. Jei tai ne žmogus (triukšmas, muzika, pyptelėjimas) — spausk „Ne žmogus“: panašus garsas "
         "nebebus siūlomas. Balsų „pirštų atspaudai“ saugomi tik tavo kompiuteryje.")
MAX_CONTEXT = 60
POLL_SEC = 3


def player_cmd() -> list:
    return shlex.split(os.environ.get("DIKTATURA_PLAYER") or "paplay")


def fmt_when(iso_or_src: str) -> str:
    p = sessions.parse_name(iso_or_src or "")
    if p:
        return f"{p[1]:%Y-%m-%d %H:%M} · {p[0].upper()}"
    try:
        return datetime.fromisoformat(iso_or_src).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return iso_or_src or "?"


class TrainingPage(Gtk.Box):
    def __init__(self, win=None, auto_refresh=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.win = win
        self.voices = []            # [PendingVoice]
        self.cur = None             # dabartinis PendingVoice
        self.occ = []               # dabartinio konteksto eilutės
        self.player = None
        for m in ("top", "start", "end"):
            getattr(self, f"set_margin_{m}")(12)

        intro = label(INTRO, css="dk-intro", wrap=True, markup=True)
        self.pack_start(intro, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        # kairė: sąrašas
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.lbl_count = label("", css="dk-title")
        left.pack_start(self.lbl_count, False, False, 0)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.set_placeholder(label("✓ Nežinomų balsų nėra —\nvisi priskirti.", xalign=0.5, css="dk-help"))
        self.list.connect("row-selected", self._on_row)
        lsw = Gtk.ScrolledWindow()
        lsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        lsw.set_size_request(260, -1)
        lsw.add(self.list)
        left.pack_start(lsw, True, True, 0)
        paned.pack1(left, False, False)

        # dešinė: detalės
        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.detail.set_margin_start(12)
        self.lbl_title = label("", css="dk-title")
        self.lbl_info = label("", css="dk-help", wrap=True)
        self.detail.pack_start(self.lbl_title, False, False, 0)
        self.detail.pack_start(self.lbl_info, False, False, 0)
        prow = Gtk.Box(spacing=6)
        self.btn_play = button("▶ Groti pavyzdį", self.play, "Paklausyti balso pavyzdžio (iki 15 s)")
        self.btn_stop = button("⏹ Stabdyti", self.stop)
        self.btn_stop.set_sensitive(False)
        prow.pack_start(self.btn_play, False, False, 0)
        prow.pack_start(self.btn_stop, False, False, 0)
        self.detail.pack_start(prow, False, False, 0)
        self.detail.pack_start(label("Ką sakė (iš transkripcijų):", css="dk-help"), False, False, 0)
        self.ctx = Gtk.TextView()
        self.ctx.set_editable(False)
        self.ctx.set_cursor_visible(False)
        self.ctx.set_wrap_mode(Gtk.WrapMode.WORD)
        self.ctx.set_left_margin(6)
        self.ctx.set_monospace(True)
        csw = Gtk.ScrolledWindow()
        csw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        csw.set_min_content_height(140)
        csw.add(self.ctx)
        self.detail.pack_start(csw, True, True, 0)

        nrow = Gtk.Box(spacing=6)
        nrow.pack_start(label("Vardas:"), False, False, 0)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("pvz. Jonas — Enter įrašo")
        self.names_model = Gtk.ListStore(str)
        comp = Gtk.EntryCompletion()
        comp.set_model(self.names_model)
        comp.set_text_column(0)
        comp.set_minimum_key_length(1)
        comp.set_match_func(lambda c, key, it, _d: c.get_model()[it][0].casefold().startswith(key.casefold()), None)
        self.entry.set_completion(comp)
        self.entry.connect("activate", lambda _w: self.assign())
        nrow.pack_start(self.entry, True, True, 0)
        self.btn_assign = button("✔ Įrašyti", self.assign, "Registruoti balsą šiuo vardu ir pakeisti tekstuose",
                                 css="suggested-action")
        nrow.pack_start(self.btn_assign, False, False, 0)
        self.detail.pack_start(nrow, False, False, 0)

        arow = Gtk.Box(spacing=6)
        arow.pack_start(button("◀ Ankstesnis", lambda: self.move(-1)), False, False, 0)
        arow.pack_start(button("Kitas ▶", lambda: self.move(1)), False, False, 0)
        arow.pack_start(button("⏭ Praleisti", self.skip, "Palikti vėlesniam laikui — nieko nekeičia"), False, False, 0)
        arow.pack_start(button("🗑 Ne žmogus / triukšmas", self.not_human,
                               "Ištrinti pavyzdį; panašus garsas nebebus siūlomas"), False, False, 0)
        arow.pack_end(button("📄 Grįžti į tekstą", lambda: self.win and self.win.show_page("text")), False, False, 0)
        self.detail.pack_start(arow, False, False, 0)
        self.msg = label("", wrap=True)
        self.detail.pack_start(self.msg, False, False, 0)
        paned.pack2(self.detail, True, False)
        self.pack_start(paned, True, True, 0)

        # registruoti balsai
        self.exp = Gtk.Expander()
        self.known = Gtk.ListBox()
        self.known.set_selection_mode(Gtk.SelectionMode.NONE)
        ksw = Gtk.ScrolledWindow()
        ksw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        ksw.set_min_content_height(120)
        ksw.add(self.known)
        self.exp.add(ksw)
        self.pack_start(self.exp, False, False, 0)

        self.reload()
        if auto_refresh:
            GLib.timeout_add_seconds(POLL_SEC, self._tick)
            GLib.timeout_add(300, self._poll_player)

    # ── duomenys ──
    def reload(self, keep_index=None) -> None:
        sel_id = self.cur.id if self.cur else None
        self.voices = store.list_pending()
        for r in self.list.get_children():
            self.list.remove(r)
        occ_all = store.occurrences_many([v.label for v in self.voices])
        for v in self.voices:
            occ = occ_all[v.label]
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            for m in ("top", "bottom", "start", "end"):
                getattr(box, f"set_margin_{m}")(6)
            box.pack_start(label(f"<b>{v.id}</b>", markup=True), False, False, 0)
            box.pack_start(label(f"girdėtas {fmt_when(v.src) if v.src else fmt_when(v.added)}", css="dk-help"),
                           False, False, 0)
            box.pack_start(label(f"{len(occ)} kart. · {len({f for f, _, _ in occ})} sesij.", css="dk-help"),
                           False, False, 0)
            row.add(box)
            row.voice_id = v.id
            self.list.add(row)
        self.list.show_all()
        self.lbl_count.set_text(f"Laukia vardo: {len(self.voices)}")
        self.names_model.clear()
        for n in store.names():
            self.names_model.append([n])
        self._reload_known()
        if not self.voices:
            self.cur = None
            self._show(None)
            return
        idx = next((i for i, v in enumerate(self.voices) if v.id == sel_id), None)
        if idx is None:
            idx = min(keep_index or 0, len(self.voices) - 1)
        self.list.select_row(self.list.get_row_at_index(idx))

    def _tick(self):
        if [v.id for v in store.list_pending()] != [v.id for v in self.voices]:
            self.reload()
        return True

    def on_shown(self) -> None:
        self.reload()

    def select(self, pid: str) -> bool:
        """Parodyti konkretų nežinomą balsą (pvz. iš Teksto skilties dešinio klik meniu)."""
        self.reload()
        for i, v in enumerate(self.voices):
            if v.id == pid:
                self.list.select_row(self.list.get_row_at_index(i))
                return True
        self.set_msg(f"Balso {pid} nebėra laukiančių sąraše (jau priskirtas?)", "dk-error")
        return False

    def _on_row(self, _lb, row) -> None:
        if row is None:
            return
        self.stop()
        self.cur = next((v for v in self.voices if v.id == row.voice_id), None)
        self._show(self.cur)

    def _show(self, v) -> None:
        self.detail.set_sensitive(v is not None)
        buf = self.ctx.get_buffer()
        if v is None:
            self.lbl_title.set_text("Nėra nežinomų balsų")
            self.lbl_info.set_text("Naujų atsiras po pokalbių, kuriuose kalbės neregistruoti žmonės.")
            buf.set_text("")
            return
        self.occ = store.occurrences(v.label)
        pos = self.voices.index(v) + 1
        self.lbl_title.set_text(f"Nežinomas balsas {v.id}  ({pos} / {len(self.voices)})")
        first = fmt_when(v.src) if v.src else fmt_when(v.added)
        nses = len({f for f, _, _ in self.occ})
        self.lbl_info.set_text(f"Pirmą kartą girdėtas: {first}. Tekstuose kalbėjo {len(self.occ)} kart. "
                               f"{nses} sesijose." + ("" if v.wav.exists() else " (garso pavyzdžio nėra)"))
        lines = []
        for f, ts, tx in self.occ[-MAX_CONTEXT:]:
            p = sessions.parse_name(f.name)
            when = f"{p[1]:%m-%d %H:%M}" if p else f.name
            lines.append(f"{when} [{ts}] {tx}")
        buf.set_text("\n".join(lines) if lines else "(tekstuose šio balso eilučių nerasta)")
        self.btn_play.set_sensitive(v.wav.exists())
        self.entry.set_text("")
        self.entry.grab_focus()

    def _reload_known(self) -> None:
        for r in self.known.get_children():
            self.known.remove(r)
        counts = store.counts()
        self.exp.set_label(f"Registruoti balsai ({len(counts)}) — pervadinti, sujungti, pamiršti")
        for name in sorted(counts, key=str.casefold):
            row = Gtk.Box(spacing=8)
            for m in ("top", "bottom", "start", "end"):
                getattr(row, f"set_margin_{m}")(4)
            row.pack_start(label(f"<b>{GLib.markup_escape_text(name)}</b>", markup=True), False, False, 0)
            row.pack_start(label(f"pavyzdžių: {counts[name]}", css="dk-help"), False, False, 0)
            row.pack_end(button("🗑 Pamiršti", lambda n=name: self._confirm_delete(n)), False, False, 0)
            row.pack_end(button("✎ Pervadinti / sujungti", lambda n=name: self._ask_rename(n)), False, False, 0)
            row.speaker = name
            self.known.add(row)
        self.known.show_all()

    # ── veiksmai ──
    def set_msg(self, text, css=None) -> None:
        ctx = self.msg.get_style_context()
        for c in ("dk-error", "dk-ok"):
            ctx.remove_class(c)
        if css:
            ctx.add_class(css)
        self.msg.set_text(text)

    def _after_change(self, idx) -> None:
        self.cur = None
        self.reload(keep_index=idx)
        if self.win is not None:
            self.win.text.refresh()             # tekstuose vardai pasikeitė — perpiešti

    def assign(self) -> bool:
        if not self.cur:
            return False
        name = self.entry.get_text()
        try:
            clean = store.clean_name(name)
            idx = self.voices.index(self.cur)
            pid = self.cur.id
            n = store.assign(pid, clean)
        except (ValueError, KeyError) as e:
            self.set_msg(f"✗ {e}", "dk-error")
            return False
        self.stop()
        self._after_change(idx)
        self.set_msg(f"✓ {pid} → {clean} (tekstuose pakeista eilučių: {n}). Ateityje bus atpažįstamas automatiškai.",
                     "dk-ok")
        return True

    def not_human(self) -> bool:
        if not self.cur:
            return False
        idx, pid = self.voices.index(self.cur), self.cur.id
        self.stop()
        n = store.discard(pid)
        self._after_change(idx)
        self.set_msg(f"✓ {pid} pašalintas kaip triukšmas (tekstuose -> „{store.UNKNOWN}“: {n} eil.)", "dk-ok")
        return True

    def skip(self) -> None:
        self.move(1)
        self.set_msg("")

    def move(self, delta: int) -> None:
        if not self.voices:
            return
        idx = (self.voices.index(self.cur) + delta) % len(self.voices) if self.cur in self.voices else 0
        self.list.select_row(self.list.get_row_at_index(idx))

    def play(self) -> None:
        self.stop()
        if self.cur and self.cur.wav.exists():
            try:
                self.player = subprocess.Popen(player_cmd() + [str(self.cur.wav)],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                self.set_msg(f"✗ nepavyko groti: {e}", "dk-error")
                return
            self.btn_play.set_sensitive(False)
            self.btn_stop.set_sensitive(True)

    def stop(self) -> None:
        if self.player and self.player.poll() is None:
            self.player.terminate()
            try:
                self.player.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.player.kill()
        self.player = None
        self.btn_stop.set_sensitive(False)
        self.btn_play.set_sensitive(bool(self.cur and self.cur.wav.exists()))

    def _poll_player(self):
        if self.player and self.player.poll() is not None:
            self.stop()
        return True

    def rename(self, old: str, new: str) -> int:
        n = store.rename_speaker(old, new)
        self._after_change(self.voices.index(self.cur) if self.cur in self.voices else 0)
        self.set_msg(f"✓ „{old}“ → „{store.clean_name(new)}“ (tekstuose pakeista eilučių: {n})", "dk-ok")
        return n

    def forget(self, name: str) -> None:
        store.delete_speaker(name)
        self._reload_known()
        self.names_model.clear()
        for n in store.names():
            self.names_model.append([n])
        self.set_msg(f"✓ „{name}“ balsas pamirštas (tekstai nekeisti)", "dk-ok")

    def _dialog(self, text, secondary, buttons=Gtk.ButtonsType.OK_CANCEL):
        return Gtk.MessageDialog(transient_for=self.get_toplevel() if self.win else None, modal=True,
                                 message_type=Gtk.MessageType.QUESTION, buttons=buttons, text=text,
                                 secondary_text=secondary)

    def _ask_rename(self, old: str) -> None:
        dlg = self._dialog(f"Pervadinti „{old}“", "Jei įvesi jau esantį vardą — balsai bus sujungti "
                                                  "(pvz. „Ruta“ → „Rūta“). Tekstuose vardas pasikeis visur.")
        e = Gtk.Entry()
        e.set_text(old)
        e.set_activates_default(True)
        dlg.set_default_response(Gtk.ResponseType.OK)
        dlg.get_message_area().pack_start(e, False, False, 0)
        dlg.show_all()
        resp, new = dlg.run(), e.get_text()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK and new.strip() and new.strip() != old:
            try:
                self.rename(old, new)
            except (ValueError, KeyError) as err:
                self.set_msg(f"✗ {err}", "dk-error")

    def _confirm_delete(self, name: str) -> None:
        dlg = self._dialog(f"Pamiršti „{name}“ balsą?", "Balsas nebebus atpažįstamas (tekstai nesikeis). "
                                                        "Vėl išmokti galėsi Apmokymuose.", Gtk.ButtonsType.YES_NO)
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.YES:
            self.forget(name)
