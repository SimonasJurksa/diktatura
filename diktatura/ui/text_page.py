"""Diktatūra — 📄 Tekstas: gyvas transkripcijų vaizdas (pagrindinio lango skiltis).

- Rodo <duomenys>/recordings transkripcijas (*.named.txt, mono *.txt, *.clean.dialog.txt); numatytai paskutines
  RETENTION_DAYS dienų, filtru — šiandien / vakar / 7 / 30 d. / visas archyvas. Nauji/papildyti failai — kas 2 s.
- Modelis: sesija (failas) -> eilutės. Failas papildytas -> pridedamos tik naujos pilnos eilutės; perrašytas
  (pvz. Apmokymuose „Kolega?nez3" -> „Jonas") -> perpiešiama.
- Skyrikliai „// ── data · VOX/SLACK/REC · failas ──", kalbėtojai spalvomis, paieška (nuo 3 simb.; ◀ ▶, Enter /
  Shift+Enter, Ctrl+F; „Regex"), filtras pagal kalbėtoją, „Tik žymėtos", „Kopijuoti viską", „Sekti naujus".
- Dešinys klik ant eilutės: ▶ Groti nuo čia (įrašas groja nuo tos vietos, einama eilutė paryškinama; kol groja,
  VOX neįrašinėja — diktatura.pause),
  ⭐ svarbu / ☐ užduotis (☑ atlikta), 🎓 priskirti vardą nežinomam balsui, ✎ Kas kalbėjo? (pataisyti kalbėtoją:
  eilutė pervadinama, o jos balsas išmokstamas tam žmogui / tau — diktatura.speakers.teach, fone per .venv).
  📊 Statistika (kas kiek kalbėjo),
  💾 Eksportuoti (matomas tekstas -> .txt / .md). Tekstą galima redaguoti prieš kopijuojant (failai nekeičiami).
"""
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from diktatura import annotations, config, pause, paths, sessions, stats
from diktatura.speakers import store
from diktatura.ui.gtk import Gdk, GLib, Gtk, Pango, button, label
from diktatura.ui.player import SeekPlayer

# Spalvos kalbėtojams (tinka šviesiai ir tamsiai temai); priskiriamos pagal pasirodymą
PALETTE = ["#1a73e8", "#188038", "#d93025", "#9334e6", "#e37400",
           "#00897b", "#c5221f", "#7cb342", "#6d4c41"]
REFRESH_SEC = 2
PERIODS = (("keep", None), ("today", "Šiandien"), ("yesterday", "Vakar"), ("7", "Pask. 7 d."),
           ("30", "Pask. 30 d."), ("all", "Visas archyvas"))
ALL_SPEAKERS = "__visi__"


def teach_cmd(path, idx: int, name: str) -> list:
    """Balso mokymosi iš pataisytos eilutės komanda (.venv: numpy + sherpa-onnx; UI jų neturi)."""
    return [str(paths.VENV_PY), "-m", "diktatura.speakers.teach", str(path), str(idx), name]


@dataclass
class Line:
    session: "Session"
    idx: int                   # eilutės nr. faile
    ts: str                    # „H:MM:SS" arba "" (be laiko)
    speaker: str               # "" — jei eilutė be kalbėtojo
    text: str

    @property
    def seconds(self):
        return sessions.ts_seconds(self.ts) if self.ts else None


@dataclass
class Session:
    path: Path
    when: datetime
    source: str                # VOX / SLACK / REC / ""
    size: int = 0              # perskaityta baitų (iki paskutinės pilnos eilutės)
    ino: int = 0
    mtime_ns: int = 0
    lines: list = field(default_factory=list)

    def parse(self, chunk: str) -> list:
        out = []
        for raw in chunk.splitlines():
            if not raw.strip():
                continue
            p = sessions.parse_line(raw)
            ts, spk, txt = p if p else ("", "", raw)
            out.append(Line(self, len(self.lines) + len(out), ts, spk, txt))
        self.lines += out
        return out


def load_session(path: Path) -> Session:
    st = path.stat()
    parsed = sessions.parse_name(path.name)
    s = Session(path, sessions.session_dt(path), parsed[0].upper() if parsed else "", ino=st.st_ino)
    read_more(s, st)
    return s


def read_more(s: Session, st) -> list:
    """Perskaityti naujas PILNAS eilutes nuo s.size (pusiau įrašyta paskutinė eilutė paliekama kitam kartui)."""
    with open(s.path, "rb") as fh:
        fh.seek(s.size)
        data = fh.read()
    cut = data.rfind(b"\n") + 1
    if cut < len(data) and not _still_writing(st):
        cut = len(data)                       # paskutinė eilutė be „\n", bet failas seniai nekeistas — imam viską
    s.size += cut
    s.mtime_ns = st.st_mtime_ns
    return s.parse(data[:cut].decode("utf-8", errors="replace"))


def _still_writing(st) -> bool:
    return (datetime.now().timestamp() - st.st_mtime) < 3


def retention_days() -> int:
    return config.load()["RETENTION_DAYS"]


def period_range(period: str, retention: int, today: date = None):
    """-> (nuo, iki) datos imtinai; None = be ribos."""
    today = today or date.today()
    if period == "today":
        return today, today
    if period == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if period in ("7", "30"):
        return today - timedelta(days=int(period) - 1), None
    if period == "all":
        return None, None
    return today - timedelta(days=retention - 1), None


def fmt_dur(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class TextPage(Gtk.Box):
    def __init__(self, win=None, rec_dir=None, auto_refresh=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self._alive = True          # langą uždarius fone likę laikmačiai nebeliečia valdiklių
        self.connect("destroy", lambda _w: setattr(self, "_alive", False))
        self._rec = Path(rec_dir) if rec_dir else None
        self.sessions = {}          # Path -> Session
        self.order = []             # atvaizduotos sesijos (sena -> nauja)
        self.mark_line = {}         # TextMark -> Line (eilutės pradžia; išlieka redaguojant)
        self.line_mark = {}         # id(Line) -> TextMark
        self.spk_tags = {}
        self.autoscroll = True
        self.days = retention_days()
        self.matches, self.match_idx = [], -1
        self.period = "keep"
        self.f_speaker = None
        self.f_tagged = False
        self.ann = annotations.load()
        self.player = SeekPlayer()
        self.play_session = None
        self._menu_line = None
        self._building = False

        # 1 eilutė: paieška
        tb = self._row()
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Ieškoti… (Ctrl+F) — nuo 3 simbolių")
        self.search.connect("search-changed", lambda _w: self.highlight_all())
        self.search.connect("activate", lambda _w: self.goto_match(1))
        tb.pack_start(self.search, True, True, 0)
        self.cb_regex = Gtk.CheckButton(label="Regex")
        self.cb_regex.set_tooltip_text("Paieška reguliariąja išraiška (be didžiųjų/mažųjų skirtumo), pvz. diegim\\w+|migracij")
        self.cb_regex.connect("toggled", lambda _w: self.highlight_all())
        tb.pack_start(self.cb_regex, False, False, 0)
        tb.pack_start(button("◀", lambda: self.goto_match(-1), "Ankstesnis (Shift+Enter)"), False, False, 0)
        tb.pack_start(button("▶", lambda: self.goto_match(1), "Kitas (Enter)"), False, False, 0)
        self.lbl_match = label("")
        tb.pack_start(self.lbl_match, False, False, 6)
        tb.pack_start(button("Kopijuoti viską", self.copy_all), False, False, 0)
        self.cb_auto = Gtk.CheckButton(label="Sekti naujus")
        self.cb_auto.set_active(True)
        self.cb_auto.connect("toggled", lambda w: setattr(self, "autoscroll", w.get_active()))
        tb.pack_start(self.cb_auto, False, False, 0)
        self.pack_start(tb, False, False, 0)

        # 2 eilutė: filtrai ir veiksmai
        fb = self._row(top=0)
        fb.pack_start(label("Kalbėtojas:"), False, False, 0)
        self.cmb_speaker = Gtk.ComboBoxText()
        self.cmb_speaker.connect("changed", self._on_speaker)
        fb.pack_start(self.cmb_speaker, False, False, 0)
        fb.pack_start(label("Laikotarpis:"), False, False, 6)
        self.cmb_period = Gtk.ComboBoxText()
        for pid, title in PERIODS:
            self.cmb_period.append(pid, title or f"Pask. {self.days} d. (nustatymas)")
        self.cmb_period.set_active_id("keep")
        self.cmb_period.connect("changed", self._on_period)
        fb.pack_start(self.cmb_period, False, False, 0)
        self.cb_tagged = Gtk.CheckButton(label="Tik žymėtos ⭐☐")
        self.cb_tagged.connect("toggled", self._on_tagged)
        fb.pack_start(self.cb_tagged, False, False, 6)
        self.btn_stop = button("⏹ Stabdyti grojimą", self.stop_playback)
        self.btn_stop.set_no_show_all(True)
        fb.pack_start(self.btn_stop, False, False, 0)
        fb.pack_end(button("💾 Eksportuoti…", self.on_export, "Išsaugoti matomą tekstą (.txt arba .md)"), False, False, 0)
        fb.pack_end(button("📊 Statistika", self.on_stats, "Kas kiek kalbėjo (matomose sesijose)"), False, False, 0)
        self.pack_start(fb, False, False, 0)

        self.sw = Gtk.ScrolledWindow()
        self.sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.tv = Gtk.TextView()
        self.tv.set_wrap_mode(Gtk.WrapMode.WORD)
        self.tv.set_editable(True)
        self.tv.set_left_margin(10)
        self.tv.set_right_margin(10)
        self.tv.set_monospace(True)
        self.tv.connect("button-press-event", self._on_press)
        self.tv.connect("populate-popup", self._on_popup)
        self.buf = self.tv.get_buffer()
        self.t_sep = self.buf.create_tag("sep", foreground="#888888", weight=Pango.Weight.BOLD)
        self.t_time = self.buf.create_tag("time", foreground="#999999")
        self.t_mark = self.buf.create_tag("mark", foreground="#e37400")
        self.t_hl = self.buf.create_tag("hl", background="#fde047", foreground="#000000")
        self.t_cur = self.buf.create_tag("cur", background="#fb923c", foreground="#000000")
        self.t_play = self.buf.create_tag("play", background="#bfdbfe", foreground="#000000")
        self.sw.add(self.tv)
        self.pack_start(self.sw, True, True, 0)

        self.status = label("Kraunu…")
        self.status.set_margin_start(8)
        self.status.set_margin_bottom(4)
        self.pack_start(self.status, False, False, 0)

        self.refresh()
        if auto_refresh:
            GLib.timeout_add_seconds(REFRESH_SEC, self._tick)

    def _row(self, top=6):
        b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        b.set_margin_top(top)
        for m in ("bottom", "start", "end"):
            getattr(b, f"set_margin_{m}")(6)
        return b

    # ── duomenys ──
    def rec_dir(self) -> Path:
        return self._rec or paths.RECORDINGS

    def _tick(self):
        try:
            self.refresh()
        except Exception as e:                  # langas neturi užlūžti dėl vieno sugadinto failo
            self.status.set_text(f"⚠ {e}")
        return True

    def date_range(self):
        return period_range(self.period, self.days)

    def refresh(self) -> None:
        self.days = retention_days()
        self.cmb_period.get_model()[0][0] = f"Pask. {self.days} d. (nustatymas)"
        since, until = self.date_range()
        files = [f for f in sessions.text_files(self.rec_dir(), since)
                 if until is None or sessions.session_dt(f).date() <= until]
        current = set(files)
        rerender = False
        appended = []                           # (sesija, naujos eilutės, nauja_sesija)
        for gone in [p for p in self.sessions if p not in current]:
            del self.sessions[gone]
            rerender = True
        for f in files:
            try:
                st = f.stat()
            except OSError:
                continue
            s = self.sessions.get(f)
            if s is None:
                s = self.sessions[f] = load_session(f)
                appended.append((s, s.lines, True))
            elif st.st_ino != s.ino or st.st_size < s.size or (
                    st.st_mtime_ns != s.mtime_ns and st.st_size == s.size and not _still_writing(st)):
                self.sessions[f] = load_session(f)             # perrašytas (pvz. pervadintas kalbėtojas)
                rerender = True
            elif st.st_size > s.size:
                new = read_more(s, st)
                if new:
                    appended.append((s, new, False))
        ordered = self.ordered()
        if not rerender:
            # greitas kelias: tik pridėjimai gale (naujos sesijos po visų esamų / paskutinės sesijos pildymas)
            if [s.path for s in ordered][:len(self.order)] != self.order:
                rerender = True
            else:
                rerender = any(not is_new and self.order and s.path != self.order[-1] for s, _, is_new in appended)
        if rerender:
            self.render_all(ordered)
        elif appended:
            for s, new, is_new in appended:
                if is_new:
                    self.order.append(s.path)
                    self._insert_header(s)
                for ln in new:
                    self._insert_line(ln)
            self._after_change()
        self._update_speakers()
        self._update_status()

    def ordered(self) -> list:
        return sorted(self.sessions.values(), key=lambda x: (x.when, x.path.name))

    # ── filtrai ──
    def visible(self, ln: Line) -> bool:
        if self.f_speaker and ln.speaker != self.f_speaker:
            return False
        if self.f_tagged and not annotations.match(self.ann, ln.session.path.name, ln.idx, ln.text):
            return False
        return True

    def visible_lines(self) -> list:
        return [ln for s in self.ordered() for ln in s.lines if self.visible(ln)]

    def set_speaker_filter(self, name) -> None:
        self.f_speaker = name or None
        self.render_all()

    def set_period(self, period: str) -> None:
        self.period = period
        self.refresh()

    def set_tagged_only(self, on: bool) -> None:
        self.f_tagged = bool(on)
        self.render_all()

    def _on_speaker(self, cmb):
        if not self._building:
            sid = cmb.get_active_id()
            self.set_speaker_filter(None if sid in (None, ALL_SPEAKERS) else sid)

    def _on_period(self, cmb):
        self.set_period(cmb.get_active_id() or "keep")

    def _on_tagged(self, cb):
        self.set_tagged_only(cb.get_active())

    def _update_speakers(self) -> None:
        names = self.speakers()
        if getattr(self, "_speaker_names", None) == names:
            return
        self._speaker_names = names
        self._building = True
        try:
            self.cmb_speaker.remove_all()
            self.cmb_speaker.append(ALL_SPEAKERS, "Visi")
            for n in names:
                self.cmb_speaker.append(n, n)
            self.cmb_speaker.set_active_id(self.f_speaker if self.f_speaker in names else ALL_SPEAKERS)
        finally:
            self._building = False

    # ── atvaizdavimas ──
    def render_all(self, ordered=None) -> None:
        ordered = ordered if ordered is not None else self.ordered()
        vadj = self.sw.get_vadjustment().get_value()
        self.ann = annotations.load()
        self.buf.set_text("")
        for m in self.mark_line:
            if not m.get_deleted():
                self.buf.delete_mark(m)
        self.mark_line.clear()
        self.line_mark.clear()
        self.order = []
        for s in ordered:
            self.order.append(s.path)
            lines = [ln for ln in s.lines if self.visible(ln)]
            if lines or not (self.f_speaker or self.f_tagged):
                self._insert_header(s)
            for ln in lines:
                self._insert_line(ln, checked=True)
        self._after_change(keep_vadj=vadj)

    def _insert_header(self, s: Session) -> None:
        when = s.when.strftime("%Y-%m-%d %H:%M:%S")
        mid = f"{when} · {s.source} · {sessions.base_name(s.path.name)}" if s.source else sessions.base_name(s.path.name)
        self.buf.insert_with_tags(self.buf.get_end_iter(), f"\n// ───────────────  {mid}  ───────────────\n\n", self.t_sep)

    def _insert_line(self, ln: Line, checked=False) -> None:
        if not checked and not self.visible(ln):
            return
        end = self.buf.get_end_iter()
        mark = self.buf.create_mark(None, end, True)
        self.mark_line[mark] = ln
        self.line_mark[id(ln)] = mark
        ic = annotations.icon(annotations.match(self.ann, ln.session.path.name, ln.idx, ln.text))
        if ic:
            self.buf.insert_with_tags(self.buf.get_end_iter(), f"{ic} ", self.t_mark)
        if ln.ts:
            self.buf.insert_with_tags(self.buf.get_end_iter(), f"[{ln.ts}] ", self.t_time)
        if ln.speaker:
            self.buf.insert_with_tags(self.buf.get_end_iter(), f"{ln.speaker}: ", self.spk_tag(ln.speaker))
        self.buf.insert(self.buf.get_end_iter(), ln.text + "\n")

    def _after_change(self, keep_vadj=None) -> None:
        if len(self.search.get_text()) >= 3:
            self.highlight_all()
        if self.autoscroll:
            GLib.idle_add(self.scroll_end)
        elif keep_vadj is not None:
            GLib.idle_add(lambda: self.sw.get_vadjustment().set_value(keep_vadj) and False)

    def spk_tag(self, name: str):
        if name not in self.spk_tags:
            color = PALETTE[len(self.spk_tags) % len(PALETTE)]
            self.spk_tags[name] = self.buf.create_tag(None, foreground=color, weight=Pango.Weight.BOLD)
        return self.spk_tags[name]

    def line_at_iter(self, it):
        it = it.copy()
        it.set_line_offset(0)
        for m in it.get_marks():
            if m in self.mark_line:
                return self.mark_line[m]
        return None

    def line_range(self, ln: Line):
        m = self.line_mark.get(id(ln))
        if m is None or m.get_deleted():
            return None
        s = self.buf.get_iter_at_mark(m)
        e = s.copy()
        e.forward_to_line_end()
        return s, e

    def speakers(self) -> list:
        return sorted({ln.speaker for s in self.sessions.values() for ln in s.lines if ln.speaker}, key=str.casefold)

    def _update_status(self) -> None:
        since, until = self.date_range()
        if since is None:
            per = "visas archyvas"
        elif until == since:
            per = since.strftime("%Y-%m-%d")
        else:
            per = f"nuo {since:%Y-%m-%d}"
        flt = []
        if self.f_speaker:
            flt.append(f"kalbėtojas: {self.f_speaker}")
        if self.f_tagged:
            flt.append("tik žymėtos")
        self.status.set_text(f"Rodoma {len(self.order)} sesijų ({per}) · kalbėtojų: {len(self.speakers())} · "
                             + (" · ".join(flt) + " · " if flt else "")
                             + ("seka naujus" if self.autoscroll else "nestabdoma"))

    def text(self) -> str:
        s, e = self.buf.get_bounds()
        return self.buf.get_text(s, e, True)

    # ── paieška ──
    def on_key(self, ev) -> bool:
        if (ev.state & Gdk.ModifierType.CONTROL_MASK) and ev.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.search.grab_focus()
            self.search.select_region(0, -1)
            return True
        if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.search.has_focus():
            self.goto_match(-1 if ev.state & Gdk.ModifierType.SHIFT_MASK else 1)
            return True
        return False

    def find_ranges(self, q: str) -> list:
        """[(pradžios, pabaigos) simbolių offset'ai] — be didžiųjų/mažųjų skirtumo; „Regex" — reguliarioji išraiška."""
        if self.cb_regex.get_active():
            rx = re.compile(q, re.IGNORECASE)
            return [(m.start(), m.end()) for m in rx.finditer(self.text()) if m.end() > m.start()]
        out = []
        it = self.buf.get_start_iter()
        while True:
            found = it.forward_search(q, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
            if not found:
                break
            ms, me = found
            out.append((ms.get_offset(), me.get_offset()))
            it = me
        return out

    def highlight_all(self) -> None:
        q = self.search.get_text()
        s, e = self.buf.get_bounds()
        self.buf.remove_tag(self.t_hl, s, e)
        self.buf.remove_tag(self.t_cur, s, e)
        self.matches, self.match_idx = [], -1
        if len(q) < 3:
            self.lbl_match.set_text("")
            return
        try:
            self.matches = self.find_ranges(q)
        except re.error as err:
            self.lbl_match.set_text(f"klaidinga regex: {err.msg}")
            return
        for so, eo in self.matches:
            self.buf.apply_tag(self.t_hl, self.buf.get_iter_at_offset(so), self.buf.get_iter_at_offset(eo))
        self.lbl_match.set_text(f"{len(self.matches)} rasta" if self.matches else "nerasta")

    def goto_match(self, delta: int) -> None:
        if not self.matches:
            return
        self.match_idx = (self.match_idx + delta) % len(self.matches)
        so, eo = self.matches[self.match_idx]
        ms, me = self.buf.get_iter_at_offset(so), self.buf.get_iter_at_offset(eo)
        s, e = self.buf.get_bounds()
        self.buf.remove_tag(self.t_cur, s, e)
        self.buf.apply_tag(self.t_cur, ms, me)
        self.tv.scroll_to_iter(ms, 0.2, False, 0, 0)
        self.lbl_match.set_text(f"{self.match_idx + 1}/{len(self.matches)}")

    def scroll_end(self):
        end = self.buf.get_end_iter()
        self.buf.place_cursor(end)
        self.tv.scroll_to_iter(end, 0, False, 0, 0)
        return False

    def copy_all(self) -> None:
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.text(), -1)
        self.status.set_text("✓ Nukopijuota viskas į iškarpinę")

    # ── kontekstinis meniu (dešinys klik) ──
    def _on_press(self, tv, ev):
        if ev.button == 3:
            x, y = tv.window_to_buffer_coords(Gtk.TextWindowType.TEXT, int(ev.x), int(ev.y))
            res = tv.get_iter_at_location(x, y)
            it = res[1] if isinstance(res, tuple) else res
            self._menu_line = self.line_at_iter(it) if it else None
        return False

    def _on_popup(self, tv, menu):
        ln = self._menu_line or self.line_at_iter(self.buf.get_iter_at_mark(self.buf.get_insert()))
        self._menu_line = None
        if not isinstance(menu, Gtk.Menu) or ln is None:
            return
        for it in self.menu_items(ln):
            menu.append(it)
        menu.show_all()

    def menu_items(self, ln: Line) -> list:
        """Kontekstinio meniu punktai eilutei (atskirai — testuojama)."""
        items = [Gtk.SeparatorMenuItem()]

        def add(text, cb, sensitive=True):
            mi = Gtk.MenuItem(label=text)
            mi.connect("activate", lambda _w: cb())
            mi.set_sensitive(sensitive)
            items.append(mi)

        audio = sessions.audio_for(ln.session.path)
        add(f"▶ Groti nuo čia ({ln.ts or '0:00:00'})", lambda: self.play_line(ln), audio is not None)
        a = annotations.match(self.ann, ln.session.path.name, ln.idx, ln.text)
        if not a or a.get("tag") != "star":
            add("⭐ Pažymėti: svarbu", lambda: self.tag_line(ln, "star"))
        if not a or a.get("tag") != "task":
            add("☐ Pažymėti: užduotis", lambda: self.tag_line(ln, "task"))
        else:
            add("☑ Užduotis atlikta" if not a.get("done") else "☐ Užduotis neatlikta", lambda: self.toggle_task(ln))
        if a:
            add("✕ Pašalinti žymę", lambda: self.tag_line(ln, None))
        if ln.speaker.startswith(store.UNKNOWN) and len(ln.speaker) > len(store.UNKNOWN):
            pid = ln.speaker[len(store.UNKNOWN):]
            add(f"🎓 Priskirti vardą balsui {pid}…", lambda: self.goto_training(pid))
        if ln.speaker and ln.ts:
            sub = Gtk.Menu()
            for name, text in self.correction_choices(ln):
                mi = Gtk.MenuItem(label=text)
                mi.connect("activate", lambda _w, n=name: self.correct_speaker(ln, n))
                sub.append(mi)
            other = Gtk.MenuItem(label="✎ Kitas vardas…")
            other.connect("activate", lambda _w: self._ask_and_correct(ln))
            sub.append(other)
            top = Gtk.MenuItem(label=f"✎ Kas kalbėjo? (ne {ln.speaker})")
            top.set_submenu(sub)
            items.append(top)
        return items

    # ── kalbėtojo pataisymas ──
    def correction_choices(self, ln: Line) -> list:
        """[(vardas, meniu tekstas)]: tu, registruoti ir matomi tekste vardai, nežinomas — be dabartinio."""
        names = {n for n in store.names()} | {n for n in self.speakers()
                                              if n != store.ME and not n.startswith(store.UNKNOWN)}
        out = [(store.ME, "🙋 Tu (aš)")] if ln.speaker != store.ME else []
        out += [(n, n) for n in sorted(names, key=str.casefold) if n != ln.speaker]
        if ln.speaker != store.UNKNOWN:
            out.append((store.UNKNOWN, "Kolega? (nežinomas — nemokyti)"))
        return out

    def ask_name(self, ln: Line):
        """Dialogas: kas iš tikro kalbėjo (užbaigimas — registruoti ir tekstuose matomi vardai). -> vardas | None."""
        dlg = Gtk.MessageDialog(transient_for=self.get_toplevel() if self.win else None, modal=True,
                                message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL,
                                text=f"Kas sakė: „{ln.text[:60]}“?",
                                secondary_text="Eilutė bus pataisyta, o balsas išmoktas šiam žmogui.")
        e = Gtk.Entry()
        model = Gtk.ListStore(str)
        for n in sorted(set(store.names()) | store.text_speakers(), key=str.casefold):
            model.append([n])
        comp = Gtk.EntryCompletion()
        comp.set_model(model)
        comp.set_text_column(0)
        e.set_completion(comp)
        e.set_activates_default(True)
        dlg.set_default_response(Gtk.ResponseType.OK)
        dlg.get_message_area().pack_start(e, False, False, 0)
        dlg.show_all()
        resp, name = dlg.run(), e.get_text()
        dlg.destroy()
        return name if resp == Gtk.ResponseType.OK and name.strip() else None

    def _ask_and_correct(self, ln: Line) -> None:
        name = self.ask_name(ln)
        if not name:
            return
        try:
            new = store.ME if store.is_me(name) else store.clean_name(name)
        except ValueError as e:
            self.status.set_text(f"✗ {e}")
            return
        self.correct_speaker(ln, new)

    def correct_speaker(self, ln: Line, new: str) -> bool:
        """Eilutės kalbėtojas -> new; jei new — žmogus (ar tu), jo balsas išmokstamas iš tos eilutės garso."""
        path = ln.session.path
        if not store.relabel_line(path, ln.idx, ln.speaker, new):
            self.status.set_text("⚠ eilutė jau pasikeitė — palauk atnaujinimo ir bandyk dar kartą")
            return False
        msg = f"✓ [{ln.ts}] {ln.speaker} → {new}"
        self.refresh()
        if new == store.UNKNOWN:
            self.status.set_text(msg)
            return True
        try:
            p = subprocess.Popen(teach_cmd(path, ln.idx, new), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, cwd=str(paths.REPO), env={**os.environ, "PYTHONPATH": str(paths.REPO)})
        except OSError as e:
            self.status.set_text(f"{msg} · balso neišmokau: {e}")
            return True
        self.status.set_text(f"{msg} · mokausi balso…")
        GLib.timeout_add(300, self._poll_teach, p, msg)
        return True

    def _poll_teach(self, p, msg):
        if not self._alive:                 # langas uždarytas — mokymasis baigsis pats, rodyti nebėra kur
            return False
        if p.poll() is None:
            return True
        try:
            r = json.loads((p.stdout.read() or "").strip().splitlines()[-1])
        except (ValueError, IndexError, OSError):
            r = {}
        if p.returncode == 0:
            self.status.set_text(f"{msg} · balsas išmoktas ({r.get('channel', '?')} kanalas, "
                                 f"{r.get('speech_sec', '?')} s kalbos; {r.get('who', '')} pavyzdžių: {r.get('count', '?')})")
        else:
            self.status.set_text(f"{msg} · balso neišmokau: {r.get('error') or f'klaida ({p.returncode})'}")
        if self.win is not None:
            self.win.training.reload()
        return False

    # ── žymės ──
    def tag_line(self, ln: Line, tag) -> None:
        annotations.set_tag(ln.session.path.name, ln.idx, ln.text, tag)
        self.render_all()

    def toggle_task(self, ln: Line) -> None:
        annotations.toggle_done(ln.session.path.name, ln.idx, ln.text)
        self.render_all()

    def goto_training(self, pid: str) -> None:
        if self.win is not None:
            self.win.show_page("training")
            self.win.training.select(pid)

    # ── grojimas ──
    def play_line(self, ln: Line) -> bool:
        audio = sessions.audio_for(ln.session.path)
        if audio is None:
            self.status.set_text("⚠ šios sesijos garso nėra (ištrintas arba neišsaugotas)")
            return False
        start = max(0.0, (ln.seconds or 0) - 0.5)
        try:
            self.player.play(audio, start)
        except OSError as e:
            self.status.set_text(f"✗ nepavyko groti: {e}")
            return False
        self.play_session = ln.session
        pause.hold(force=True)                    # VOX neįrašinės grojamo įrašo
        self.btn_stop.show()
        self._highlight_playing()
        GLib.timeout_add(250, self._play_tick)
        return True

    def playing_line(self):
        """Eilutė, kurią dabar girdi (paskutinė su laiku ≤ grojimo pozicija)."""
        if not self.play_session:
            return None
        pos = self.player.position()
        cur = None
        for ln in self.play_session.lines:
            if ln.seconds is not None and ln.seconds <= pos + 0.25:
                cur = ln
        return cur or (self.play_session.lines[0] if self.play_session.lines else None)

    def _highlight_playing(self) -> None:
        s, e = self.buf.get_bounds()
        self.buf.remove_tag(self.t_play, s, e)
        ln = self.playing_line()
        r = self.line_range(ln) if ln else None
        if r:
            self.buf.apply_tag(self.t_play, *r)
            self.tv.scroll_to_iter(r[0], 0.25, False, 0, 0)

    def _play_tick(self):
        if not self.player.playing():
            self.stop_playback()
            return False
        pause.hold()                              # grojama — pratęsti įrašymo pauzę
        self._highlight_playing()
        return True

    def stop_playback(self) -> None:
        if self.play_session is not None:
            pause.release()
        self.player.stop()
        self.play_session = None
        s, e = self.buf.get_bounds()
        self.buf.remove_tag(self.t_play, s, e)
        self.btn_stop.hide()

    # ── statistika / eksportas ──
    def stats(self) -> dict:
        """Kas kiek kalbėjo matomose eilutėse, pasakytose po nunulinimo (jei nunulinta)."""
        since = stats.reset_time()
        rows = [(id(ln.session), ln.seconds, ln.speaker, ln.text) for ln in self.visible_lines()
                if stats.counts(ln.session.when, ln.seconds, since)]
        return sessions.speaker_stats(rows)

    def stats_rows(self) -> list:
        """Statistikos lentelės eilutės: (kalbėtojas, eilučių, žodžių, ≈ laikas, dalis), daugiausiai kalbėjęs pirmas."""
        st = self.stats()
        total = sum(v["seconds"] for v in st.values()) or 1
        return [(name, v["lines"], v["words"], fmt_dur(v["seconds"]), f"{100 * v['seconds'] / total:.0f} %")
                for name, v in sorted(st.items(), key=lambda kv: -kv[1]["seconds"])]

    def stats_note(self) -> str:
        since = stats.reset_time()
        frm = f"nuo {since:%Y-%m-%d %H:%M} (nunulinta)" if since else "nuo pradžių (matomose sesijose)"
        return f"Skaičiuojama {frm}. Matomos sesijos: {len(self.order)}. Laikas — apytikslis (pagal eilučių laikus)."

    def reset_stats(self) -> None:
        stats.reset()

    def clear_stats_reset(self) -> None:
        stats.clear()

    def on_stats(self) -> None:
        RESET, ALL = 1, 2
        dlg = Gtk.Dialog(title="📊 Kas kiek kalbėjo", transient_for=self.get_toplevel() if self.win else None, modal=True)
        b_reset = dlg.add_button("↺ Nunulinti", RESET)
        b_reset.set_tooltip_text("Skaičiuoti tik nuo dabar. Tekstai nekeičiami ir netrinami.")
        b_all = dlg.add_button("Skaičiuoti viską", ALL)
        b_all.set_tooltip_text("Pamiršti nunulinimą — vėl skaičiuoti visas matomas eilutes")
        dlg.add_button("Uždaryti", Gtk.ResponseType.CLOSE)
        model = Gtk.ListStore(str, int, int, str, str)
        tv = Gtk.TreeView(model=model)
        for i, title in enumerate(("Kalbėtojas", "Eilučių", "Žodžių", "≈ Laikas", "Dalis")):
            tv.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i))
        note = label("", css="dk-help", wrap=True)
        box = dlg.get_content_area()
        box.set_spacing(8)
        box.pack_start(note, False, False, 0)
        box.pack_start(tv, True, True, 0)

        def fill():
            model.clear()
            for r in self.stats_rows():
                model.append(list(r))
            note.set_text(self.stats_note())
            b_all.set_sensitive(stats.reset_time() is not None)

        fill()
        dlg.show_all()
        while True:
            resp = dlg.run()
            if resp == RESET:
                self.reset_stats()
            elif resp == ALL:
                self.clear_stats_reset()
            else:
                break
            fill()
        dlg.destroy()

    def export_text(self, fmt: str = "txt") -> str:
        out = []
        cur = None
        for ln in self.visible_lines():
            if ln.session is not cur:
                cur = ln.session
                head = f"{cur.when:%Y-%m-%d %H:%M} · {cur.source or '-'} · {sessions.base_name(cur.path.name)}"
                out.append(f"\n## {head}\n" if fmt == "md" else f"\n// {head}\n")
            ic = annotations.icon(annotations.match(self.ann, cur.path.name, ln.idx, ln.text))
            pre = f"{ic} " if ic else ""
            if fmt == "md":
                who = f"**{ln.speaker}** " if ln.speaker else ""
                out.append(f"- {pre}{who}`{ln.ts}` {ln.text}" if ln.ts else f"- {pre}{who}{ln.text}")
            else:
                out.append(pre + (f"[{ln.ts}] " if ln.ts else "") + (f"{ln.speaker}: " if ln.speaker else "") + ln.text)
        return "\n".join(out).lstrip("\n") + "\n"

    def export_to(self, path) -> Path:
        path = Path(path)
        path.write_text(self.export_text("md" if path.suffix.lower() == ".md" else "txt"), encoding="utf-8")
        self.status.set_text(f"✓ Eksportuota: {path}")
        return path

    def on_export(self) -> None:
        dlg = Gtk.FileChooserNative.new("Eksportuoti tekstą", self.get_toplevel() if self.win else None,
                                        Gtk.FileChooserAction.SAVE, "Išsaugoti", "Atšaukti")
        dlg.set_do_overwrite_confirmation(True)
        dlg.set_current_name(f"diktatura_{date.today():%Y%m%d}.md")
        docs = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
        if docs:
            dlg.set_current_folder(docs)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            self.export_to(dlg.get_filename())
        dlg.destroy()
