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
  📊 Statistika (kas kiek kalbėjo), ⏳ Transkripcija (eiga ir prognozė — ui.progress_dialog; mygtuko užrašas kas 2 s
  rodo „43 % · liko ~1 val. · eilėje 4"),
  💾 Eksportuoti (matomas tekstas -> .txt / .md / .srt subtitrai); dešiniu klik — 📋 kopijuoti / 💾 eksportuoti vieną
  sesiją. Tekstą galima redaguoti prieš kopijuojant (failai nekeičiami).
- ✨ Švarus (CLEAN_VIEW, mygtukas „✨ Švarus"): rodoma be užpildų („ee", „mhm", FILLER_WORDS) ir pasikartojimų
  (diktatura.fillers); eilutės iš vien užpildų slepiamos. Paieška ir eksportas — kaip rodoma; failai nekeičiami.
- 🔁 Transkribuoti iš naujo (dešinys klik): sesija iš naujo dabartiniu modeliu ir balsais (bin/transcribe-file.sh,
  DIKTATURA_RETRANSCRIBE=1 — senas tekstas lieka, kol naujas paruoštas; ankstesnis — <tekstas>.prev);
  ↩ Grąžinti ankstesnę transkripciją — sukeičia su .prev.
- Sekami aplankai (diktatura.sources): kiekvienam — atskiras TextPage (source=…) savame skirtuke (ui.app TextTabs):
  tekstai iš <duomenys>/sources/<id>/, viršuje — aplankas, kiek laukia, „🔄 Transkribuoti dabar", „📂 Atidaryti".
- 🌊 Banga (WAVEFORM, mygtukas „🌊 Banga"): virš teksto — vienos sesijos garso banga (ui.waveform_view): naujausios,
  o spragtelėjus eilutę / grojant — tos sesijos (pasirinkta eilutė paryškinta ir bangoje). Spragtelėjus bangą — groja nuo
  ten. Smailės — <bazė>.peaks (diktatura.waveform); jei jų nėra, bet garsas yra — suskaičiuojamos fone (.venv).
"""
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from diktatura import annotations, config, fillers, pause, paths, progress, services, sessions, stats, waveform
from diktatura.speakers import store
from diktatura.ui.gtk import Gdk, GLib, Gtk, Pango, button, flow, group, label
from diktatura.ui.player import SeekPlayer
from diktatura.ui.themes import LIGHT_PALETTE
from diktatura.ui.waveform_view import WaveformView

# Spalvos kalbėtojams (tinka šviesiai ir tamsiai temai); priskiriamos pagal pasirodymą
PALETTE = list(LIGHT_PALETTE)      # tema (on_theme) pakeičia
REFRESH_SEC = 2
PERIODS = (("keep", None), ("today", "Šiandien"), ("yesterday", "Vakar"), ("7", "Pask. 7 d."),
           ("30", "Pask. 30 d."), ("all", "Visas archyvas"))
ALL_SPEAKERS = "__visi__"


def teach_cmd(path, idx: int, name: str) -> list:
    """Balso mokymosi iš pataisytos eilutės komanda (.venv: numpy + sherpa-onnx; UI jų neturi)."""
    return [str(paths.VENV_PY), "-m", "diktatura.speakers.teach", str(path), str(idx), name]


def peaks_cmd(audio, out) -> list:
    """Bangos smailių skaičiavimas fone (.venv: numpy), žemiausiu prioritetu."""
    return ["nice", "-n", "19", str(paths.VENV_PY), "-m", "diktatura.waveform", str(audio), "--out", str(out)]


def line_span(ln, lines) -> tuple:
    """(pradžia, pabaiga) s — eilutė skamba iki kitos eilutės su laiku (ne ilgiau 30 s)."""
    if ln.seconds is None:
        return None, None
    nxt = [x.seconds for x in lines if x.seconds is not None and x.seconds > ln.seconds]
    return ln.seconds, min(min(nxt) if nxt else ln.seconds + 5, ln.seconds + 30)


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
    key: str = ""              # žymių (⭐/☐) raktas: failo vardas; sekamo aplanko — „<id>/<vardas>" (vardai kartojasi)

    def __post_init__(self):
        self.key = self.key or self.path.name

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


def load_session(path: Path, source_label: str = "", key_prefix: str = "") -> Session:
    st = path.stat()
    parsed = sessions.parse_name(path.name)
    s = Session(path, sessions.session_dt(path), parsed[0].upper() if parsed else source_label, ino=st.st_ino,
                key=f"{key_prefix}{path.name}")
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
    def __init__(self, win=None, rec_dir=None, auto_refresh=True, source=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.source = source        # sources.Source — sekamo aplanko skirtukas (None — pokalbiai / įrašai)
        self._alive = True          # langą uždarius fone likę laikmačiai nebeliečia valdiklių
        self.connect("destroy", lambda _w: setattr(self, "_alive", False))
        self._rec = Path(rec_dir) if rec_dir else (source.out_dir if source is not None else None)
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
        self.spk_colors = {}        # kalbėtojas -> spalva (tekstas ir banga)
        self.wave_session = None    # kurios sesijos banga rodoma
        self.wave_pinned = False    # pasirinkta spragtelėjus / grojant (kitaip — naujausia)
        self.wave_line = None
        self._peaks_jobs = {}       # smailių failas -> Popen (skaičiuojama fone)
        self._wave_key = None
        cfg = config.load()
        self.clean = bool(cfg["CLEAN_VIEW"])
        self.clean_words = fillers.parse_words(cfg["FILLER_WORDS"])

        if source is not None:              # sekamas aplankas: iš kur, kiek laukia, „transkribuoti dabar"
            sb = self._row(top=8)
            self.lbl_source = label("", css="dk-help")
            self.lbl_source.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            sb.pack_start(self.lbl_source, True, True, 0)
            self.btn_src_now = button("🔄 Transkribuoti dabar", self.transcribe_source_now,
                                      "Transkribuoti laukiančius šio aplanko failus dabar (nelaukiant nakties)")
            sb.pack_start(self.btn_src_now, False, False, 0)
            sb.pack_start(button("📂 Atidaryti aplanką", self.open_source_folder), False, False, 0)
            self.pack_start(sb, False, False, 0)

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
        self.pack_start(tb, False, False, 0)

        # 2 eilutė: filtrai ir veiksmai — siaurame lange persikelia į kelias eilutes (flow)
        self.cmb_speaker = Gtk.ComboBoxText()
        self.cmb_speaker.connect("changed", self._on_speaker)
        self.cmb_period = Gtk.ComboBoxText()
        for pid, title in PERIODS:
            self.cmb_period.append(pid, title or f"Pask. {self.days} d. (nustatymas)")
        self.cmb_period.set_active_id("keep")
        self.cmb_period.connect("changed", self._on_period)
        self.cb_tagged = Gtk.CheckButton(label="Tik žymėtos ⭐☐")
        self.cb_tagged.connect("toggled", self._on_tagged)
        self.btn_stop = button("⏹ Stabdyti grojimą", self.stop_playback)
        self.btn_stop.set_no_show_all(True)
        self.cb_auto = Gtk.CheckButton(label="Sekti naujus")
        self.cb_auto.set_active(True)
        self.cb_auto.connect("toggled", self._on_autoscroll)
        self.btn_progress = button("⏳ Transkripcija", self.on_progress,
                                   "Kiek liko: dabartinis failas ir visa eilė (galima praleisti ar sustabdyti)")
        self.btn_wave = Gtk.ToggleButton(label="🌊 Banga")
        self.btn_wave.set_tooltip_text("Rodyti / slėpti garso bangą (spragtelėk eilutę — jos sesijos banga)")
        self.btn_wave.set_active(bool(config.load()["WAVEFORM"]))
        self.btn_wave.connect("toggled", self._on_wave_toggled)
        self.btn_clean = Gtk.ToggleButton(label="✨ Švarus")
        self.btn_clean.set_tooltip_text("Rodyti be užpildų („ee\", „mhm\", „nu\"…) ir pasikartojimų — failai nekeičiami")
        self.btn_clean.set_active(self.clean)
        self.btn_clean.connect("toggled", self._on_clean_toggled)
        fb = flow(group(label("Kalbėtojas:"), self.cmb_speaker), group(label("Laikotarpis:"), self.cmb_period),
                  self.cb_tagged, self.btn_stop, self.btn_wave, self.btn_clean,
                  button("📊 Statistika", self.on_stats, "Kas kiek kalbėjo (matomose sesijose)"), self.btn_progress,
                  button("💾 Eksportuoti…", self.on_export, "Išsaugoti matomą tekstą (.txt arba .md)"),
                  button("Kopijuoti viską", self.copy_all), self.cb_auto)
        for m in ("start", "end"):
            getattr(fb, f"set_margin_{m}")(8)
        fb.set_margin_bottom(4)
        self.pack_start(fb, False, False, 0)

        # 🌊 banga: antraštė (kuri sesija) + piešinys; „⤓ Naujausia" — vėl sekti naujausią sesiją
        self.wave = WaveformView(on_seek=self._on_wave_seek)
        self.lbl_wave = label("", css="dk-help")
        self.lbl_wave.set_ellipsize(Pango.EllipsizeMode.END)
        self.btn_wave_latest = button("⤓ Naujausia", self.wave_follow_latest, "Rodyti naujausios sesijos bangą")
        self.btn_wave_latest.set_no_show_all(True)
        head = Gtk.Box(spacing=6)
        head.pack_start(self.lbl_wave, True, True, 0)
        head.pack_end(self.btn_wave_latest, False, False, 0)
        self.wave_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for m in ("start", "end"):
            getattr(self.wave_box, f"set_margin_{m}")(8)
        self.wave_box.set_margin_bottom(4)
        self.wave_box.pack_start(head, False, False, 0)
        self.wave_box.pack_start(self.wave, False, False, 0)
        head.show_all()
        self.wave.show()
        self.wave_box.set_no_show_all(True)          # matomumą valdo „🌊 Banga"
        self.pack_start(self.wave_box, False, False, 0)

        self.sw = Gtk.ScrolledWindow()
        self.sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.tv = Gtk.TextView()
        self.tv.set_wrap_mode(Gtk.WrapMode.WORD)
        self.tv.set_editable(True)
        self.tv.set_left_margin(10)
        self.tv.set_right_margin(10)
        self.tv.set_monospace(True)
        self.tv.connect("button-press-event", self._on_press)
        self.tv.connect("button-release-event", self._on_release)
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
        self.status.set_ellipsize(Pango.EllipsizeMode.END)       # siauras langas — būsena sutrumpinama, ne platina
        self.status.set_margin_start(8)
        self.status.set_margin_bottom(4)
        self.pack_start(self.status, False, False, 0)

        self.refresh()
        self.update_progress_button()
        self.update_source_bar()
        if auto_refresh:
            GLib.timeout_add_seconds(REFRESH_SEC, self._tick)

    def _on_autoscroll(self, cb) -> None:
        self.autoscroll = cb.get_active()
        if self.autoscroll:                       # vėl sekti naujus — ir banga grįžta prie naujausios sesijos
            self.wave_follow_latest()

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
        if not self._alive:
            return False
        if self.source is not None and not self.get_mapped():
            return True                         # nematomas skirtukas — neatnaujinamas (atnaujins atsidarius)
        try:
            self.refresh()
        except Exception as e:                  # langas neturi užlūžti dėl vieno sugadinto failo
            self.status.set_text(f"⚠ {e}")
        self.update_progress_button()
        self.update_source_bar()
        return True

    # ── sekamas aplankas ──
    def update_source_bar(self) -> None:
        if self.source is None:
            return
        from diktatura import sources
        src = sources.get(self.source.id) or self.source
        c = sources.counts(src)
        night = config.load()["MODE"] == "deferred"
        state = ("⚠ aplanko nėra" if not src.dir.is_dir() else "išjungtas (nesekamas)" if not src.enabled
                 else f"laukia {c['pending']}" + (" — transkribuos naktį" if night and c["pending"] else ""))
        self.lbl_source.set_text(f"📂 {sources.short_path(src.path)} · failų {c['files']}, tekstų {c['texts']} · {state}")
        self.btn_src_now.set_sensitive(bool(c["pending"]))

    def transcribe_source_now(self) -> None:
        services.spawn_detached(["bash", str(paths.BIN / "transcribe-pending.sh"), "--sources"], "sources")
        self.status.set_text("⏳ Transkribuojami laukiantys šio aplanko failai — eiga: „⏳ Transkripcija\"")

    def open_source_folder(self) -> None:
        try:
            subprocess.Popen(["xdg-open", str(self.source.dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def update_progress_button(self, snap=None) -> None:
        """„⏳ Transkripcija" / „⏳ 43 % · liko ~1 val. · eilėje 4"."""
        try:
            s = progress.summary(snap or progress.snapshot())
        except Exception:                       # eiga — tik informacija
            s = ""
        self.btn_progress.set_label(f"⏳ {s}" if s else "⏳ Transkripcija")

    def on_progress(self) -> None:
        if self.win is not None and hasattr(self.win, "open_progress"):
            self.win.open_progress()
            return
        from diktatura.ui.progress_dialog import ProgressDialog
        ProgressDialog(None).run()
        self.update_progress_button()

    def date_range(self):
        return period_range(self.period, self.days)

    def refresh(self) -> None:
        cfg = config.load()
        self.days = cfg["RETENTION_DAYS"]
        clean, words = bool(cfg["CLEAN_VIEW"]), fillers.parse_words(cfg["FILLER_WORDS"])
        if (clean, words) != (self.clean, self.clean_words):          # pakeista Nustatymuose
            self.clean, self.clean_words = clean, words
            if self.btn_clean.get_active() != clean:
                self.btn_clean.set_active(clean)                       # -> render_all
            else:
                self.render_all()
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
            label_, pre = (self.source.name.upper(), f"{self.source.id}/") if self.source is not None else ("", "")
            if s is None:
                s = self.sessions[f] = load_session(f, label_, pre)
                appended.append((s, s.lines, True))
            elif st.st_ino != s.ino or st.st_size < s.size or (
                    st.st_mtime_ns != s.mtime_ns and st.st_size == s.size and not _still_writing(st)):
                self.sessions[f] = load_session(f, label_, pre)   # perrašytas (pvz. pervadintas kalbėtojas)
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
        self.update_wave()

    def ordered(self) -> list:
        return sorted(self.sessions.values(), key=lambda x: (x.when, x.path.name))

    # ── ✨ švarus rodinys ──
    def display_text(self, ln: Line) -> str:
        """Kaip eilutė rodoma: švariame rodinyje — be užpildų (talpykla eilutėje pagal žodžių sąrašą)."""
        if not self.clean:
            return ln.text
        c = getattr(ln, "_clean", None)
        if c is None or c[0] != self.clean_words:
            c = ln._clean = (self.clean_words, fillers.clean(ln.text, self.clean_words))
        return c[1]

    def _on_clean_toggled(self, btn) -> None:
        self.clean = btn.get_active()
        try:
            if bool(config.load()["CLEAN_VIEW"]) != self.clean:
                config.save({"CLEAN_VIEW": "1" if self.clean else "0"})
        except (OSError, ValueError):
            pass
        self.render_all()
        self._update_status()

    # ── filtrai ──
    def visible(self, ln: Line) -> bool:
        if self.clean and not self.display_text(ln):
            return False                          # eilutė iš vien užpildų („Mhm.")
        if self.f_speaker and ln.speaker != self.f_speaker:
            return False
        if self.f_tagged and not annotations.match(self.ann, ln.session.key, ln.idx, ln.text):
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
        ic = annotations.icon(annotations.match(self.ann, ln.session.key, ln.idx, ln.text))
        if ic:
            self.buf.insert_with_tags(self.buf.get_end_iter(), f"{ic} ", self.t_mark)
        if ln.ts:
            self.buf.insert_with_tags(self.buf.get_end_iter(), f"[{ln.ts}] ", self.t_time)
        if ln.speaker:
            self.buf.insert_with_tags(self.buf.get_end_iter(), f"{ln.speaker}: ", self.spk_tag(ln.speaker))
        self.buf.insert(self.buf.get_end_iter(), self.display_text(ln) + "\n")

    def _after_change(self, keep_vadj=None) -> None:
        if len(self.search.get_text()) >= 3:
            self.highlight_all()
        if self.autoscroll:
            GLib.idle_add(self.scroll_end)
        elif keep_vadj is not None:
            GLib.idle_add(lambda: self.sw.get_vadjustment().set_value(keep_vadj) and False)

    def spk_tag(self, name: str):
        if name not in self.spk_tags:
            pal = getattr(self, "palette", PALETTE)
            color = pal[len(self.spk_tags) % len(pal)]
            self.spk_colors[name] = color
            self.spk_tags[name] = self.buf.create_tag(None, foreground=color, weight=Pango.Weight.BOLD)
        return self.spk_tags[name]

    def spk_color(self, name: str) -> str:
        """Kalbėtojo spalva (ta pati kaip tekste; dar nematytam — priskiriama)."""
        if not name:
            return "#80868b"
        self.spk_tag(name)
        return self.spk_colors[name]

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
        if self.clean:
            flt.append("✨ švarus")
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

    def on_theme(self, theme) -> None:
        """Tema pasikeitė: teksto žymų ir kalbėtojų spalvos (tamsiame fone — šviesesnės, kontraste — sočios)."""
        self.palette = list(theme.palette)
        self.t_sep.props.foreground = theme.text["sep"]
        self.t_time.props.foreground = theme.text["time"]
        self.t_mark.props.foreground = theme.text["mark"]
        for i, (name, tag) in enumerate(self.spk_tags.items()):
            tag.props.foreground = self.spk_colors[name] = self.palette[i % len(self.palette)]
        self.wave.set_size_request(120, 64 if theme.compact else 84)
        self._wave_key = None
        self.update_wave()

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
        a = annotations.match(self.ann, ln.session.key, ln.idx, ln.text)
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
            self._speaker_menu(ln, sub, items)
        items.append(Gtk.SeparatorMenuItem())
        can, why = self.can_retranscribe(ln.session)
        add("🔁 Transkribuoti šią sesiją iš naujo…" if can else f"🔁 Transkribuoti iš naujo ({why})",
            lambda: self.on_retranscribe(ln.session), can)
        if self.prev_text(ln.session).exists():
            add("↩ Grąžinti ankstesnę transkripciją", lambda: self.restore_previous(ln.session))
        add("📋 Kopijuoti šią sesiją", lambda: self.copy_session(ln.session))
        add("💾 Eksportuoti šią sesiją… (.txt / .md / .srt)", lambda: self.on_export(ln.session))
        return items

    def _speaker_menu(self, ln, sub, items) -> None:
        """„✎ Kas kalbėjo?" pomeniu (tu, registruoti ir matomi vardai, kitas vardas…)."""
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

    # ── 🔁 transkribuoti iš naujo ──
    def prev_text(self, session) -> Path:
        return session.path.with_name(session.path.name + ".prev")

    def can_retranscribe(self, session) -> tuple:
        """(galima?, kodėl ne). Garsas turi būti; senas formatas (.clean.dialog.txt) — ne (liktų du tekstai)."""
        if session.path.name.endswith(".dialog.txt"):
            return False, "senas formatas"
        if sessions.audio_for(session.path) is None:
            return False, "garso nebėra"
        busy = {sessions.base_name(j.file.name) for j in self._jobs()}
        if sessions.base_name(session.path.name) in busy:
            return False, "jau transkribuojama"
        return True, ""

    def _jobs(self) -> list:
        try:
            return progress.snapshot().jobs
        except Exception:                       # eiga — tik informacija
            return []

    def retranscribe_cmd(self, session) -> list:
        """bin/transcribe-file.sh <garsas> [<išvesties bazė> — sekamam aplankui]."""
        audio = sessions.audio_for(session.path)
        cmd = ["bash", str(paths.BIN / "transcribe-file.sh"), str(audio)]
        base = session.path.with_name(sessions.base_name(session.path.name))
        if self.source is not None or base.parent != audio.parent:
            cmd.append(str(base))
        return cmd

    def on_retranscribe(self, session) -> bool:
        audio = sessions.audio_for(session.path)
        if audio is None:
            return False
        dur = progress.audio_info(audio)[0]
        try:
            model = config.load()["MODEL"]
            est = progress.estimate_job_total("named" if session.path.name.endswith(".named.txt") else "mono", dur,
                                              progress.rates(model))
            eta = f" Truks ≈ {progress.fmt_left(est)} (šiame kompiuteryje{', po eilėje esančių' if self._jobs() else ''})."
        except Exception:                       # prognozė — tik informacija
            eta = ""
        dlg = Gtk.MessageDialog(transient_for=self.get_toplevel() if self.win else None, modal=True,
                                message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE,
                                text=f"Transkribuoti „{sessions.base_name(session.path.name)}“ iš naujo?")
        dlg.format_secondary_text(
            f"{fmt_dur(dur)} garso — dabartiniu modeliu ir su dabartiniais balsais (vardai gali pasikeisti)."
            f"{eta} Senas tekstas lieka, kol naujas bus paruoštas; ankstesnį galėsi grąžinti (↩). "
            "Žymės ⭐☐ gali nebeatitikti pasikeitusių eilučių.")
        dlg.add_button("Atšaukti", Gtk.ResponseType.CANCEL)
        dlg.add_button("🔁 Transkribuoti", Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        dlg.set_default_response(Gtk.ResponseType.CANCEL)
        resp = self.run_dialog(dlg)
        dlg.destroy()
        if resp != Gtk.ResponseType.OK:
            return False
        return self.retranscribe(session)

    def run_dialog(self, dlg) -> int:
        """Atskirai — testai jį pakeičia (dialogo nerodo)."""
        return dlg.run()

    def retranscribe(self, session) -> bool:
        try:
            services.spawn_detached(self.retranscribe_cmd(session), "retx", {"DIKTATURA_RETRANSCRIBE": "1"})
        except OSError as e:
            self.status.set_text(f"✗ nepavyko paleisti: {e}")
            return False
        self.status.set_text(f"🔁 {sessions.base_name(session.path.name)} transkribuojama iš naujo — eiga: "
                             "„⏳ Transkripcija\"; tekstas atsinaujins pats")
        return True

    def restore_previous(self, session) -> bool:
        """↩ Ankstesnė transkripcija (.prev) <-> dabartinė (galima grąžinti atgal tuo pačiu punktu)."""
        prev, cur = self.prev_text(session), session.path
        if not prev.exists():
            return False
        tmp = cur.with_name(cur.name + ".swap")
        os.replace(cur, tmp)
        os.replace(prev, cur)
        os.replace(tmp, prev)
        self.refresh()
        self.status.set_text(f"↩ Grąžinta ankstesnė transkripcija ({cur.name}); naujesnė — {prev.name}")
        return True

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
        annotations.set_tag(ln.session.key, ln.idx, ln.text, tag)
        self.render_all()

    def toggle_task(self, ln: Line) -> None:
        annotations.toggle_done(ln.session.key, ln.idx, ln.text)
        self.render_all()

    def goto_training(self, pid: str) -> None:
        if self.win is not None:
            self.win.show_page("training")
            self.win.training.select(pid)

    # ── 🌊 banga ──
    def _on_wave_toggled(self, btn) -> None:
        on = btn.get_active()
        try:
            if bool(config.load()["WAVEFORM"]) != on:
                config.save({"WAVEFORM": "1" if on else "0"})
        except (OSError, ValueError):
            pass                                  # nustatymas neįsirašė — rodymas vis tiek perjungiamas
        self._wave_key = None
        self.update_wave()

    def wave_follow_latest(self) -> None:
        self.wave_pinned = False
        self.wave_line = None
        self.update_wave()

    def select_wave(self, session, ln=None) -> None:
        """Rodyti šios sesijos bangą (spragtelėta eilutė / grojama); ln — paryškinti jos vietą."""
        self.wave_session, self.wave_pinned, self.wave_line = session, True, ln
        self.update_wave()

    def wave_peaks_file(self, session) -> Path:
        return waveform.peaks_path(session.path)

    def update_wave(self) -> None:
        """Kurios sesijos banga, jos smailės (jei nėra — skaičiuojamos fone), žymės, paryškinta eilutė."""
        show = self.btn_wave.get_active() and bool(self.sessions)
        self.wave_box.set_visible(show)
        if not show:
            return
        if not self.wave_pinned or self.wave_session is None or self.wave_session.path not in self.sessions:
            self.wave_pinned = False
            self.wave_line = None
            last = self.order[-1] if self.order else max(self.sessions, key=lambda p: self.sessions[p].when)
            self.wave_session = self.sessions.get(last)
        else:
            self.wave_session = self.sessions[self.wave_session.path]      # perkrautas (perrašytas failas)
        s = self.wave_session
        if s is None:
            return
        self.btn_wave_latest.set_visible(self.wave_pinned)
        pf = self.wave_peaks_file(s)
        try:
            st = pf.stat()
            pkey = (st.st_mtime_ns, st.st_size)
        except OSError:
            pkey = None
        key = (s.path, len(s.lines), pkey, id(s))
        if key != self._wave_key:
            self._wave_key = key
            pk = waveform.read(pf) if pkey else None
            audio = sessions.audio_for(s.path)
            if pk is None or (audio is not None and not waveform.is_fresh(pf, audio)):
                if audio is not None:
                    self._start_peaks(audio, pf)
                    self.wave.set_peaks(pk)
                    self.wave.set_message("🌊 skaičiuojama banga…")
                else:
                    self.wave.set_peaks(None)
                    self.wave.set_message("Garso nebėra — bangos nėra (tekstas lieka)")
            elif pk is not self.wave.peaks:
                self.wave.set_peaks(pk)
            self.wave.set_colors(self.spk_color(store.ME), getattr(self, "palette", PALETTE)[-1])
            self.wave.set_lines([(ln.seconds, ln.speaker, self.spk_color(ln.speaker), ln.text) for ln in s.lines],
                                me=store.ME)
        dur = self.wave.duration
        name = sessions.base_name(s.path.name)
        self.lbl_wave.set_text(f"🌊 {s.when:%Y-%m-%d %H:%M} · {s.source + ' · ' if s.source else ''}{name}"
                               + (f" · {fmt_dur(dur)}" if dur else "")
                               + ("" if self.wave_pinned else " · naujausia"))
        a, b = line_span(self.wave_line, s.lines) if self.wave_line is not None else (None, None)
        self.wave.set_band(a, b)

    def _start_peaks(self, audio, out) -> None:
        if out in self._peaks_jobs:
            return
        try:
            p = subprocess.Popen(peaks_cmd(audio, out), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 cwd=str(paths.REPO), env={**os.environ, "PYTHONPATH": str(paths.REPO)})
        except OSError as e:
            self.wave.set_message(f"Bangos nepavyko suskaičiuoti: {e}")
            return
        self._peaks_jobs[out] = p
        GLib.timeout_add(400, self._poll_peaks, out)

    def _poll_peaks(self, out) -> bool:
        p = self._peaks_jobs.get(out)
        if not self._alive or p is None:
            return False
        if p.poll() is None:
            return True
        del self._peaks_jobs[out]
        self._wave_key = None
        if p.returncode != 0 and self.wave_session is not None and self.wave_peaks_file(self.wave_session) == out:
            self.wave.set_message("Bangos nepavyko suskaičiuoti (garso failas sugadintas?)")
            return False
        self.update_wave()
        return False

    def _on_wave_seek(self, sec: float) -> None:
        s = self.wave_session
        if s is None:
            return
        ln = None
        for x in s.lines:
            if x.seconds is not None and x.seconds <= sec + 0.25:
                ln = x
        self.wave_pinned, self.wave_line = True, ln
        self.play_at(s, sec)
        self.update_wave()

    def _on_release(self, tv, ev):
        if ev.button == 1:
            GLib.idle_add(self._wave_from_cursor)
        return False

    def _wave_from_cursor(self) -> bool:
        ln = self.line_at_iter(self.buf.get_iter_at_mark(self.buf.get_insert()))
        if ln is not None and (ln.session is not self.wave_session or ln is not self.wave_line or not self.wave_pinned):
            self.select_wave(ln.session, ln)
        return False

    # ── grojimas ──
    def play_line(self, ln: Line) -> bool:
        if not self.play_at(ln.session, max(0.0, (ln.seconds or 0) - 0.5)):
            return False
        self.wave_line = ln
        self.update_wave()
        return True

    def play_at(self, session, start: float) -> bool:
        audio = sessions.audio_for(session.path)
        if audio is None:
            self.status.set_text("⚠ šios sesijos garso nėra (ištrintas arba neišsaugotas)")
            return False
        try:
            self.player.play(audio, max(0.0, start))
        except OSError as e:
            self.status.set_text(f"✗ nepavyko groti: {e}")
            return False
        first = self.play_session is None
        self.play_session = session
        pause.hold(force=True)                    # VOX neįrašinės grojamo įrašo
        self.btn_stop.show()
        if session is not self.wave_session or not self.wave_pinned:
            self.wave_session, self.wave_pinned = session, True
            self.update_wave()
        self._highlight_playing()
        if first:
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
        if not self._alive:
            return False
        if self.play_session is None:
            return False
        if not self.player.playing():
            self.stop_playback()
            return False
        pause.hold()                              # grojama — pratęsti įrašymo pauzę
        self._highlight_playing()
        if self.play_session is self.wave_session:
            self.wave.set_position(self.player.position())
            ln = self.playing_line()
            if ln is not None and ln is not self.wave_line:          # banga paryškina tai, kas dabar skamba
                self.wave_line = ln
                self.wave.set_band(*line_span(ln, self.wave_session.lines))
        return True

    def stop_playback(self) -> None:
        if self.play_session is not None:
            pause.release()
        self.player.stop()
        self.play_session = None
        s, e = self.buf.get_bounds()
        self.buf.remove_tag(self.t_play, s, e)
        self.btn_stop.hide()
        self.wave.set_position(None)

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

    @staticmethod
    def srt_time(sec: float) -> str:
        h, rem = divmod(int(sec), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d},{int((sec - int(sec)) * 1000):03d}"

    def export_srt(self, lines) -> str:
        """Subtitrai (.srt): eilutė skamba iki kitos eilutės su laiku (ne ilgiau 30 s); be laiko — praleidžiama."""
        out, n = [], 0
        for ln in lines:
            if ln.seconds is None:
                continue
            a, b = line_span(ln, ln.session.lines)
            n += 1
            who = f"{ln.speaker}: " if ln.speaker else ""
            out.append(f"{n}\n{self.srt_time(a)} --> {self.srt_time(b)}\n{who}{self.display_text(ln)}\n")
        return "\n".join(out) + ("\n" if out else "")

    def export_text(self, fmt: str = "txt", lines=None) -> str:
        """Matomas tekstas (arba nurodytos eilutės — viena sesija) kaip txt / md / srt."""
        lines = self.visible_lines() if lines is None else lines
        if fmt == "srt":
            return self.export_srt(lines)
        out = []
        cur = None
        for ln in lines:
            if ln.session is not cur:
                cur = ln.session
                head = f"{cur.when:%Y-%m-%d %H:%M} · {cur.source or '-'} · {sessions.base_name(cur.path.name)}"
                out.append(f"\n## {head}\n" if fmt == "md" else f"\n// {head}\n")
            ic = annotations.icon(annotations.match(self.ann, cur.key, ln.idx, ln.text))
            pre = f"{ic} " if ic else ""
            text = self.display_text(ln)
            if fmt == "md":
                who = f"**{ln.speaker}** " if ln.speaker else ""
                out.append(f"- {pre}{who}`{ln.ts}` {text}" if ln.ts else f"- {pre}{who}{text}")
            else:
                out.append(pre + (f"[{ln.ts}] " if ln.ts else "") + (f"{ln.speaker}: " if ln.speaker else "") + text)
        return "\n".join(out).lstrip("\n") + "\n"

    @staticmethod
    def export_format(path) -> str:
        return {".md": "md", ".srt": "srt"}.get(Path(path).suffix.lower(), "txt")

    def export_to(self, path, session=None) -> Path:
        """Į failą: plėtinys lemia formatą (.txt / .md / .srt); session — tik tos sesijos eilutės."""
        path = Path(path)
        lines = None if session is None else [ln for ln in session.lines if self.visible(ln)]
        path.write_text(self.export_text(self.export_format(path), lines), encoding="utf-8")
        self.status.set_text(f"✓ Eksportuota: {path}")
        return path

    def session_text(self, session, fmt="txt") -> str:
        return self.export_text(fmt, [ln for ln in session.lines if self.visible(ln)])

    def copy_session(self, session) -> None:
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.session_text(session), -1)
        self.status.set_text(f"✓ Nukopijuota sesija {sessions.base_name(session.path.name)}")

    def on_export(self, session=None) -> None:
        name = sessions.base_name(session.path.name) if session is not None else f"diktatura_{date.today():%Y%m%d}"
        dlg = Gtk.FileChooserNative.new("Eksportuoti sesiją" if session is not None else "Eksportuoti tekstą",
                                        self.get_toplevel() if self.win else None,
                                        Gtk.FileChooserAction.SAVE, "Išsaugoti", "Atšaukti")
        dlg.set_do_overwrite_confirmation(True)
        dlg.set_current_name(f"{name}.md")
        for label_, pat in (("Markdown (.md)", "*.md"), ("Tekstas (.txt)", "*.txt"), ("Subtitrai (.srt)", "*.srt")):
            f = Gtk.FileFilter()
            f.set_name(label_)
            f.add_pattern(pat)
            dlg.add_filter(f)
        docs = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
        if docs:
            dlg.set_current_folder(docs)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            self.export_to(dlg.get_filename(), session)
        dlg.destroy()
