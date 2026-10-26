"""Diktatūra — 🎓 Apmokymai: nežinomų balsų vardai (pagrindinio lango skiltis).

Kai pokalbyje kalba neatpažintas balsas, transkripcija jį pažymi „Kolega?nezN" ir išsaugo balso pavyzdį
(<duomenys>/speakers/pending). Čia: paklausyti pavyzdžio (▶) arba tos vietos ĮRAŠE su keliomis sekundėmis prieš ir po
(🔊 ±N s — trumpas pavyzdys dažnai vos sekundės; spragtelėjus „Ką sakė" eilutę groja būtent ji), pamatyti, ką ir kada
sakė (kontekstas iš visų transkripcijų — ir sekamų aplankų), įrašyti vardą (užbaigimas iš registruotų ir tekstuose
matomų) -> balsas registruojamas, pending pašalinamas, VISOSE transkripcijose „Kolega?nezN" -> vardas, pereinama prie
kito. „Ne žmogus / triukšmas" -> pavyzdys ištrinamas ir panašus garsas nebesiūlomas. „🙋 Tai aš" (arba vardas „Tu") ->
tai TAVO balsas (pvz. kalbėjai prisijungęs telefonu): pavyzdys į owner.json, tekstuose -> „Tu".

Klaviatūra (veikia ir rašant vardą; on_key iš MainWindow): Ctrl+Tarpas — groti / stabdyti pavyzdį, Ctrl+Shift+Tarpas —
vieta įraše ±N s; žymeklis lieka vardo laukelyje. Enter — įrašyti vardą ir iškart groti KITĄ (tuščias laukelis — praleisti);
rašant ↓ — esamas vardas iš sąrašo, Enter jį iškart ir priskiria. Po įrašymo / praleidimo / „Kitas" kitas balsas
groja pats (pavyzdys; jo nėra — vieta įraše).

🔄 Pertikrinti pagal išmoktus (diktatura.speakers.suggest, fone per .venv): kiekvienas laukiantis balsas palyginamas
su jau įvardintais (ir su triukšmu) -> 💡 pasiūlymas sąraše ir detalėse, vardas jau įrašytas laukelyje: tinka — Enter.
Paleidžiama ir pati (auto_refresh): atidarius skiltį, jei pasikeitė balsai / atsirado naujų laukiančių, ir po kiekvieno
priskyrimo — įvardinus vieną žmogų, kiti jo fragmentai gauna pasiūlymą. „✔ Priimti užtikrintus" — tik tuos, kuriuos ir
transkripcija atpažintų pati (vardo slenkstis + atsarga); jų balsai neišmokstami. Prieš pertikrinant tekstams
pritaikomi anksčiau priskirti vardai (store.apply_assigned). Rikiavimas: 💡 pasiūlymai pirma (užtikrinti, vardai prieš
triukšmą, pagal panašumą; toliau — dažniausi) / dažniausiai kalbėję / pagal laiką įraše.

Antras skirtukas — registruoti balsai (per visą aukštį): tavo balsas (pamiršti) ir kolegos: pervadinti / sujungti
(pvz. „Ruta" -> „Rūta") / pamiršti; prie vardo — kiek laukiančių į jį panašūs (💡). Tema (on_theme): kompaktiškoje —
be įžangos, siauresnis sąrašas, trumpesnis mygtukas. Įžanga — sutraukiama „ℹ Kaip tai veikia?" (numatytai suskleista).

Duomenų logika — diktatura.speakers.store (tik stdlib). Grojimas: pavyzdys — `paplay` (testams DIKTATURA_PLAYER), vieta
įraše — ffplay per ui.player.command (testams DIKTATURA_SEEK_PLAYER); kol groja, VOX neįrašinėja (diktatura.pause), kad
perklausa nevirstų nauju „pokalbiu".
"""
import json
import os
import shlex
import subprocess
import threading
from collections import Counter
from datetime import datetime

from diktatura import config, pause, paths, sessions
from diktatura.speakers import store
from diktatura.ui import player as seek_player
from diktatura.ui.gtk import GLib, Gtk, button, flow, label

INTRO = ("Kai pokalbyje kalba žmogus, kurio balso Diktatūra dar nežino, tekste jis pažymimas "
         "<b>„Kolega?nezN“</b>, o jo balso pavyzdys išsaugomas čia. Paklausyk (jei pavyzdys per trumpas — "
         "„🔊 Įraše“ groja tą vietą su keliomis sekundėmis prieš ir po), perskaityk, ką jis sakė, ir įrašyk "
         "vardą — nuo šiol šis balsas bus atpažįstamas automatiškai, o jau esamuose tekstuose „Kolega?nezN“ "
         "pasikeis į vardą. Įvardinus kelis, „🔄 Pertikrinti“ palygina likusius su jau žinomais: panašūs gauna "
         "💡 pasiūlymą (vardas jau įrašytas — paklausyk ir spausk Enter). Jei tai ne žmogus (triukšmas, muzika, "
         "pyptelėjimas) — „Ne žmogus“: panašus garsas nebebus siūlomas. Jei tai tu pats (pvz. kalbėjai "
         "prisijungęs telefonu) — „🙋 Tai aš“. Greičiausia — klaviatūra: Ctrl+Tarpas groja, rašai vardą, Enter "
         "įrašo ir groja kitą. Balsų „pirštų atspaudai“ saugomi tik tavo kompiuteryje.")
MAX_CONTEXT = 60
POLL_SEC = 3
PAD_SEC = 3                 # „🔊 Įraše": kiek sekundžių prieš ir po eilutės (keičiama šalia mygtuko)
SORTS = (("suggest", "💡 Pasiūlymai pirma"), ("count", "Dažniausiai kalbėję"), ("time", "Pagal laiką įraše"))
KEYS_HELP = ("⌨ Ctrl+Tarpas — groti / stabdyti pavyzdį · Ctrl+Shift+Tarpas — vieta įraše · rašant ↓ — esamas vardas · "
             "Enter — įrašyti ir groti kitą (tuščias — praleisti)")


def enter_pressed() -> bool:
    """Ar dabar apdorojamas įvykis — Enter klavišas (vardų sąraše pasirinkta klaviatūra, ne pele)."""
    from diktatura.ui.gtk import Gdk
    ev = Gtk.get_current_event()
    if ev is None or ev.get_event_type() != Gdk.EventType.KEY_PRESS:
        return False
    return ev.get_keyval()[1] in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter)


def player_cmd() -> list:
    return shlex.split(os.environ.get("DIKTATURA_PLAYER") or "paplay")


def suggest_cmd() -> list:
    """Pertikrinimas fone (.venv: numpy + balso modelis — UI jų neturi), žemiausiu prioritetu."""
    return ["nice", "-n", "19", str(paths.VENV_PY), "-m", "diktatura.speakers.suggest"]


def fmt_when(iso_or_src: str) -> str:
    p = sessions.parse_name(iso_or_src or "")
    if p:
        return f"{p[1]:%Y-%m-%d %H:%M} · {p[0].upper()}"
    try:
        return datetime.fromisoformat(iso_or_src).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return iso_or_src or "?"


def fmt_sec(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def sugg_who(s: dict) -> str:
    return "triukšmas" if s["name"] == "" else s["name"]


def sugg_short(s: dict) -> str:
    """Pasiūlymas sąrašo eilutėje: „💡 Jonas? · 0.47" / „✔ Jonas · 0.62" (užtikrintas)."""
    return f"✔ {sugg_who(s)} · {s['sim']:.2f}" if s.get("strong") else f"💡 {sugg_who(s)}? · {s['sim']:.2f}"


def sugg_long(s: dict) -> str:
    """Pasiūlymas detalėse: kuo remiamasi ir ką daryti."""
    basis = (f"pagal {s.get('lines')} eilučių balsą" if s.get("basis") == "profile" else "pagal trumpą pavyzdį")
    alt = f"; antras — „{sugg_who({'name': s['alt']})}“ {s['alt_sim']:.2f}" if s.get("alt") is not None else ""
    head = "✔ Užtikrintai" if s.get("strong") else "💡 Panašu"
    if s["name"] == "":
        return (f"{head}: triukšmas / ne žmogus (panašumas {s['sim']:.2f}{alt}; {basis}). "
                "Paklausyk — jei taip, spausk „🗑 Ne žmogus“.")
    who = f"„{s['name']}“" + (" (tavo balsas)" if s["name"] == store.ME else "")
    return f"{head}: {who} (panašumas {s['sim']:.2f}{alt}; {basis}). Paklausyk — jei tinka, spausk Enter."


def recheck_summary(r: dict, fixed: int) -> str:
    if not r.get("ok"):
        return f"✗ Pertikrinti nepavyko: {r.get('error') or '?'}"
    out = [f"✓ Pertikrinta laukiančių balsų: {r.get('pending', 0)}."]
    if r.get("suggested"):
        out.append(f"💡 Pasiūlymų: {r['suggested']} (užtikrintų {r.get('strong', 0)}, panašių į triukšmą "
                   f"{r.get('noise', 0)}) — sąrašo viršuje; paklausyk ir patvirtink Enter.")
    else:
        out.append("Panašių į jau žinomus nerasta — įvardink dar kelis ir pertikrink.")
    if fixed:
        out.append(f"Tekstuose pritaikyti anksčiau priskirti vardai: {fixed} eil.")
    return " ".join(out)


class TrainingPage(Gtk.Box):
    def __init__(self, win=None, auto_refresh=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.win = win
        self.auto = auto_refresh    # pertikrinti pačiam (atidarius / po priskyrimo); testuose — tik kviečiant
        self.voices = []            # [PendingVoice]
        self.cur = None             # dabartinis PendingVoice
        self.occ = []               # dabartinio balso eilutės [(failas, laikas, tekstas, nr.)]
        self.occ_all = {}           # {label: eilutės} — visiems laukiantiems
        self.sugg = {}              # {nezN: pasiūlymas} (store.load_suggestions)
        self.sort = "suggest"
        self.player = None
        self.playing = None         # kas groja: "sample" | "context" (Ctrl+Tarpas / Ctrl+Shift+Tarpas perjungia)
        self.job = None             # 🔄 pertikrinimo procesas
        self.job_lines, self.job_thread, self.job_user, self.job_fixed = [], None, False, 0
        self.job_again = None       # None — nekartoti; False/True — po šio dar kartą (True — vartotojo paspaudimas)
        self._dt = {}               # failas -> įrašymo laikas (rikiavimui pagal laiką)
        self._keep = False          # reload(keep_current) metu: tas pats balsas lieka — negroti iš naujo, neliesti vardo
        self._prefilled = ""        # kokį pasiūlymą įrašėm į vardo laukelį (rašant ranka — nebeperrašom)
        self._alive = True
        self.connect("destroy", lambda _w: setattr(self, "_alive", False))
        for m in ("top", "start", "end"):
            getattr(self, f"set_margin_{m}")(12)

        # įžanga — sutraukiama (aukštis mažame ekrane brangus); kompaktiškoje temoje paslepiama visai
        self.intro = Gtk.Expander(label="ℹ Kaip tai veikia?")
        self.intro.add(label(INTRO, css="dk-intro", wrap=True, markup=True))
        self.intro.set_expanded(False)
        self.intro.set_no_show_all(True)        # show_all jos neatidengia (kompaktiškoje temoje)
        self.intro.get_child().show()
        self.intro.show()
        self.pack_start(self.intro, False, False, 0)
        # du skirtukai: laukiantys vardo / registruoti balsai — kiekvienas per visą aukštį (mažame ekrane
        # registruotų sąrašas apačioje buvo vos kelių eilučių)
        self.tabs = Gtk.Stack()
        self.tabs.set_transition_type(Gtk.StackTransitionType.NONE)
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.tabs)
        switcher.set_halign(Gtk.Align.START)
        self.pack_start(switcher, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        # kairė: sąrašas + pertikrinimas + rikiavimas
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.lbl_count = label("", css="dk-title")
        left.pack_start(self.lbl_count, False, False, 0)
        self.btn_recheck = button("🔄 Pertikrinti pagal išmoktus", lambda: self.recheck(user=True),
                                  "Palyginti visus laukiančius balsus su jau įvardintais (ir su triukšmu): panašūs "
                                  "gauna 💡 pasiūlymą ir atsiduria sąrašo viršuje. Vardai patys nekeičiami — "
                                  "patvirtini Enter. Vyksta ir pati: atidarius skiltį ir po kiekvieno vardo.")
        left.pack_start(self.btn_recheck, False, False, 0)
        self.lbl_sugg = label("", css="dk-help", wrap=True)
        left.pack_start(self.lbl_sugg, False, False, 0)
        self.btn_accept = button("✔ Priimti užtikrintus", self._confirm_accept_strong,
                                 "Pritaikyti vardus, kuriuos ir transkripcija atpažintų pati (vardo slenkstis + "
                                 "atsarga). Balsai neišmokstami — tik vardai tekstuose.")
        self.btn_accept.set_no_show_all(True)
        left.pack_start(self.btn_accept, False, False, 0)
        srow = Gtk.Box(spacing=4)
        srow.pack_start(label("Rikiuoti:", css="dk-help"), False, False, 0)
        self.cmb_sort = Gtk.ComboBoxText()
        for key, text in SORTS:
            self.cmb_sort.append(key, text)
        self.cmb_sort.set_active_id(self.sort)
        self.cmb_sort.connect("changed", lambda c: self.set_sort(c.get_active_id()))
        srow.pack_start(self.cmb_sort, True, True, 0)
        left.pack_start(srow, False, False, 0)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.set_placeholder(label("✓ Nežinomų balsų nėra —\nvisi priskirti.", xalign=0.5, css="dk-help"))
        self.list.connect("row-selected", self._on_row)
        lsw = self.lsw = Gtk.ScrolledWindow()
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
        self.lbl_hint = label("", wrap=True)                 # 💡 pasiūlymas
        self.lbl_hint.set_no_show_all(True)
        self.detail.pack_start(self.lbl_title, False, False, 0)
        self.detail.pack_start(self.lbl_info, False, False, 0)
        self.detail.pack_start(self.lbl_hint, False, False, 0)
        self.btn_play = button("▶ Groti pavyzdį", self.play,
                               "Paklausyti išsaugoto balso pavyzdžio (iki 15 s) — Ctrl+Tarpas (dar kartą — stabdyti)")
        self.btn_ctx = button("🔊 Įraše", self.play_context,
                              "Groti tą vietą originaliame įraše su keliomis sekundėmis prieš ir po (pasirinkta "
                              "„Ką sakė“ eilutė, kitaip — pirmoji). Patogu, kai pavyzdys labai trumpas. "
                              "Ctrl+Shift+Tarpas")
        self.spin_pad = Gtk.SpinButton.new_with_range(0, 30, 1)
        self.spin_pad.set_value(PAD_SEC)
        self.spin_pad.set_tooltip_text("Kiek sekundžių groti prieš ir po eilutės")
        self.btn_stop = button("⏹ Stabdyti", self.stop)
        self.btn_stop.set_sensitive(False)
        self.detail.pack_start(flow(self.btn_play, self.btn_ctx, label("±"), self.spin_pad, label("s"),
                                    self.btn_stop), False, False, 0)
        self.detail.pack_start(label("Ką sakė (iš transkripcijų) — spragtelėk eilutę: groja ta vieta įraše:",
                                     css="dk-help", wrap=True), False, False, 0)
        self.ctx = Gtk.ListBox()
        self.ctx.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.ctx.set_placeholder(label("(tekstuose šio balso eilučių nerasta)", css="dk-help"))
        self.ctx.connect("row-activated", lambda _lb, row: self.play_context(row.occ))
        csw = self.csw = Gtk.ScrolledWindow()
        csw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        csw.set_min_content_height(90)
        csw.add(self.ctx)
        self.detail.pack_start(csw, True, True, 0)

        nrow = Gtk.Box(spacing=6)
        nrow.pack_start(label("Vardas:"), False, False, 0)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("pvz. Jonas — Enter įrašo ir groja kitą")
        self.names_model = Gtk.ListStore(str)
        comp = Gtk.EntryCompletion()
        comp.set_model(self.names_model)
        comp.set_text_column(0)
        comp.set_minimum_key_length(1)
        comp.set_match_func(lambda c, key, it, _d: c.get_model()[it][0].casefold().startswith(key.casefold()), None)
        comp.connect("match-selected", self._on_match)
        self.entry.set_completion(comp)
        self.entry.connect("activate", lambda _w: self.on_enter())
        nrow.pack_start(self.entry, True, True, 0)
        self.btn_assign = button("✔ Įrašyti", self.assign, "Registruoti balsą šiuo vardu ir pakeisti tekstuose",
                                 css="suggested-action")
        nrow.pack_start(self.btn_assign, False, False, 0)
        self.detail.pack_start(nrow, False, False, 0)
        self.lbl_keys = label(KEYS_HELP, css="dk-help", wrap=True)
        self.detail.pack_start(self.lbl_keys, False, False, 0)

        arow = flow(button("◀ Ankstesnis", lambda: self.move(-1)), button("Kitas ▶", lambda: self.move(1)),
                    button("⏭ Praleisti", self.skip, "Palikti vėlesniam laikui — nieko nekeičia"),
                    button("🙋 Tai aš", self.its_me,
                           "Tai TAVO balsas (pvz. kalbėjai prisijungęs telefonu): tekstuose bus „Tu“"),
                    button("🗑 Ne žmogus / triukšmas", self.not_human,
                           "Ištrinti pavyzdį; panašus garsas nebebus siūlomas"),
                    button("📄 Grįžti į tekstą", lambda: self.win and self.win.show_page("text")))
        self.detail.pack_start(arow, False, False, 0)
        self.msg = label("", wrap=True)
        self.detail.pack_start(self.msg, False, False, 0)
        paned.pack2(self.detail, True, False)
        self.pending_page = paned
        self.tabs.add_titled(paned, "pending", "🔎 Laukia vardo")

        # registruoti balsai — atskiras skirtukas
        kbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        kbox.pack_start(label("Pervadinti, sujungti (įvedus jau esantį vardą, pvz. „Ruta“ → „Rūta“) arba pamiršti. "
                              "Tavo balsas — viršuje. 💡 — kiek laukiančių balsų panašūs į šį žmogų.",
                              css="dk-help", wrap=True), False, False, 0)
        self.known_warn = label("", css="dk-error", wrap=True)
        self.known_warn.set_no_show_all(True)
        kbox.pack_start(self.known_warn, False, False, 0)
        self.known = Gtk.ListBox()
        self.known.set_selection_mode(Gtk.SelectionMode.NONE)
        ksw = Gtk.ScrolledWindow()
        ksw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        ksw.add(self.known)
        kbox.pack_start(ksw, True, True, 0)
        self.known_page = kbox
        self.tabs.add_titled(kbox, "known", "👥 Registruoti balsai")
        self.pack_start(self.tabs, True, True, 0)

        self.reload()
        if auto_refresh:
            GLib.timeout_add_seconds(POLL_SEC, self._tick)
            GLib.timeout_add(300, self._poll_player)

    def tab_title(self, name: str) -> str:
        return self.tabs.child_get_property(self.tabs.get_child_by_name(name), "title")

    def on_theme(self, theme) -> None:
        """Kompaktiška tema (mažas ekranas): be įžangos, siauresnis sąrašas, žemesnis kontekstas, trumpesnis mygtukas."""
        self.intro.set_visible(not theme.compact)
        self.lsw.set_size_request(170 if theme.compact else 260, -1)
        self.csw.set_min_content_height(60 if theme.compact else 90)
        self.btn_recheck.set_label("🔄 Pertikrinti" if theme.compact else "🔄 Pertikrinti pagal išmoktus")
        self.lbl_keys.set_text(KEYS_HELP.replace(" · Ctrl+Shift+Tarpas — vieta įraše", "") if theme.compact
                               else KEYS_HELP)

    # ── duomenys ──
    def _session_dt(self, f) -> datetime:
        if f not in self._dt:
            try:
                self._dt[f] = sessions.session_dt(f)
            except OSError:
                self._dt[f] = datetime.max
        return self._dt[f]

    def sort_key(self, v):
        occ = self.occ_all.get(v.label) or []
        num = store._pid_num(v.id)
        if self.sort == "count":
            return (-len(occ), num)
        if self.sort == "time":
            if not occ:
                return (datetime.max, 0, num)
            return (self._session_dt(occ[0][0]), sessions.ts_seconds(occ[0][1]), num)
        s = self.sugg.get(v.id)
        tier = 2 if not s else (0 if s.get("strong") else 1)
        return (tier, bool(s and s["name"] == ""), -(s["sim"] if s else 0.0), -len(occ), num)

    def set_sort(self, key: str) -> None:
        if key in dict(SORTS) and key != self.sort:
            self.sort = key
            self.cmb_sort.set_active_id(key)
            self.reload()

    def reload(self, keep_index=None, keep_current=False) -> None:
        """Perkrauti sąrašą. keep_current — fone (pertikrinimas baigėsi, atsirado naujų): jei dabartinis balsas liko,
        grojimas nestabdomas ir įvestas vardas nekeičiamas (atsinaujina tik pasiūlymas ir pozicija)."""
        sel_id = self.cur.id if self.cur else None
        pend = store.list_pending()
        for r in self.list.get_children():
            self.list.remove(r)
        self.occ_all = store.occurrences_many([v.label for v in pend], with_idx=True)
        self.sugg = store.load_suggestions({v.id for v in pend})
        self.voices = sorted(pend, key=self.sort_key)
        for v in self.voices:
            occ = self.occ_all[v.label]
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            for m in ("top", "bottom", "start", "end"):
                getattr(box, f"set_margin_{m}")(6)
            box.pack_start(label(f"<b>{v.id}</b>", markup=True), False, False, 0)
            box.pack_start(label(f"girdėtas {fmt_when(v.src) if v.src else fmt_when(v.added)}", css="dk-help"),
                           False, False, 0)
            box.pack_start(label(f"{len(occ)} kart. · {len({o[0] for o in occ})} sesij.", css="dk-help"),
                           False, False, 0)
            s = self.sugg.get(v.id)
            if s:
                box.pack_start(label(sugg_short(s), css="dk-ok" if s.get("strong") else None), False, False, 0)
            row.add(box)
            row.voice_id = v.id
            self.list.add(row)
        self.list.show_all()
        self.lbl_count.set_text(f"Laukia vardo: {len(self.voices)}")
        self.tabs.child_set_property(self.pending_page, "title", f"🔎 Laukia vardo ({len(self.voices)})")
        self._update_sugg_summary()
        self._fill_names()
        self._reload_known()
        if not self.voices:
            self.cur = None
            self._show(None)
            return
        idx = next((i for i, v in enumerate(self.voices) if v.id == sel_id), None)
        if idx is None:
            idx = min(keep_index or 0, len(self.voices) - 1)
        self._keep = keep_current
        try:
            self.list.select_row(self.list.get_row_at_index(idx))
        finally:
            self._keep = False

    def strong_pairs(self) -> list:
        """[(nezN, vardas | "" triukšmas)] — užtikrinti pasiūlymai (kaip transkripcijos sprendimas)."""
        return [(v.id, self.sugg[v.id]["name"]) for v in self.voices
                if v.id in self.sugg and self.sugg[v.id].get("strong")]

    def _update_sugg_summary(self) -> None:
        strong = len(self.strong_pairs())
        if self.job is None:
            self.lbl_sugg.set_text(f"💡 pasiūlymų: {len(self.sugg)} · užtikrintų: {strong}" if self.sugg else "")
        self.btn_accept.set_label(f"✔ Priimti užtikrintus ({strong})")
        self.btn_accept.set_visible(strong > 0 and self.job is None)

    def _fill_names(self) -> None:
        """Vardų užbaigimas: registruoti + matomi tekstuose (pvz. po balso modelio keitimo — seni vardai)."""
        self.names_model.clear()
        for n in sorted(set(store.names()) | store.text_speakers(), key=str.casefold):
            self.names_model.append([n])

    def _tick(self):
        if not self._alive:
            return False
        if {v.id for v in store.list_pending()} != {v.id for v in self.voices}:
            self.reload(keep_current=True)
            self.recheck_if_stale()
        return True

    def on_shown(self) -> None:
        self.reload()
        self.recheck_if_stale()

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
        v = next((v for v in self.voices if v.id == row.voice_id), None)
        if self._keep and v is not None and self.cur is not None and v.id == self.cur.id:
            self.cur = v                          # tas pats balsas po perkrovimo fone
            self._show_header(v)
            self._show_hint(v)
            return
        self.stop()
        self.cur = v
        self._show(self.cur)

    def _show_header(self, v) -> None:
        pos = self.voices.index(v) + 1
        self.lbl_title.set_text(f"Nežinomas balsas {v.id}  ({pos} / {len(self.voices)})")
        first = fmt_when(v.src) if v.src else fmt_when(v.added)
        nses = len({o[0] for o in self.occ})
        self.lbl_info.set_text(f"Pirmą kartą girdėtas: {first}. Tekstuose kalbėjo {len(self.occ)} kart. "
                               f"{nses} sesijose." + ("" if v.wav.exists() else " (garso pavyzdžio nėra)"))

    def _show_hint(self, v) -> None:
        """💡 pasiūlymas: paaiškinimas + vardas laukelyje (jei ten ne ranka įvestas tekstas)."""
        s = self.sugg.get(v.id)
        if self.entry.get_text() in ("", self._prefilled):
            self._prefilled = s["name"] if s and s["name"] else ""
            self.entry.set_text(self._prefilled)
        if not s:
            self.lbl_hint.hide()
            return
        self.lbl_hint.set_text(sugg_long(s))
        ctx = self.lbl_hint.get_style_context()
        (ctx.add_class if s.get("strong") else ctx.remove_class)("dk-ok")
        self.lbl_hint.show()

    def _show(self, v) -> None:
        self.detail.set_sensitive(v is not None)
        for r in self.ctx.get_children():
            self.ctx.remove(r)
        self.lbl_hint.hide()
        if v is None:
            self.lbl_title.set_text("Nėra nežinomų balsų")
            self.lbl_info.set_text("Naujų atsiras po pokalbių, kuriuose kalbės neregistruoti žmonės.")
            self.occ = []
            return
        self.occ = self.occ_all.get(v.label)
        if self.occ is None:
            self.occ = store.occurrences(v.label, with_idx=True)
        self._show_header(v)
        for o in self.occ[-MAX_CONTEXT:]:
            row = Gtk.ListBoxRow()
            lb = label(f"▶ {self._session_dt(o[0]):%m-%d %H:%M} [{o[1]}] {o[2]}", wrap=True)
            for m in ("top", "bottom", "start", "end"):
                getattr(lb, f"set_margin_{m}")(3)
            row.add(lb)
            row.occ = o
            row.set_tooltip_text("Spragtelėk — groti šią vietą įraše (± sekundės šalia „🔊 Įraše“)")
            self.ctx.add(row)
        self.ctx.show_all()
        self.btn_play.set_sensitive(v.wav.exists())
        self.btn_ctx.set_sensitive(bool(self.occ))
        self.entry.set_text("")                    # kitas balsas — laukelis iš naujo
        self._show_hint(v)
        self.entry.grab_focus()
        self.entry.select_region(0, -1)            # pasiūlymą perrašai tiesiog rašydamas

    def context_text(self) -> str:
        """„Ką sakė" eilutės tekstu (testams / kopijavimui)."""
        return "\n".join(r.get_child().get_text() for r in self.ctx.get_children())

    def _reload_known(self) -> None:
        for r in self.known.get_children():
            self.known.remove(r)
        counts = store.counts()
        similar = Counter(s["name"] for s in self.sugg.values() if s["name"])
        self.tabs.child_set_property(self.known_page, "title", f"👥 Registruoti balsai ({len(counts)})")
        self.known_warn.set_text("" if store.compatible() else
                                 "⚠ Senas balso modelis — balsai neatpažįstami; paleisk: make speakers-migrate")
        self.known_warn.set_visible(not store.compatible())
        own = store.owner_count()
        row = Gtk.Box(spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(row, f"set_margin_{m}")(4)
        row.pack_start(label(f"<b>🙋 {store.ME}</b> (tavo balsas)", markup=True), False, False, 0)
        row.pack_start(label((f"pavyzdžių: {own}" if own else
                              "dar nežinomas — Tekste ant savo eilutės: ✎ Kas kalbėjo? → Tu")
                             + (f" · 💡 panašių laukia: {similar[store.ME]}" if similar[store.ME] else ""),
                             css="dk-help"), False, False, 0)
        if own:
            row.pack_end(button("🗑 Pamiršti", self._confirm_forget_me), False, False, 0)
        row.speaker = store.ME
        self.known.add(row)
        for name in sorted(counts, key=str.casefold):
            row = Gtk.Box(spacing=8)
            for m in ("top", "bottom", "start", "end"):
                getattr(row, f"set_margin_{m}")(4)
            row.pack_start(label(f"<b>{GLib.markup_escape_text(name)}</b>", markup=True), False, False, 0)
            row.pack_start(label(f"pavyzdžių: {counts[name]}"
                                 + (f" · 💡 panašių laukia: {similar[name]}" if similar[name] else ""),
                                 css="dk-help"), False, False, 0)
            row.pack_end(button("🗑 Pamiršti", lambda n=name: self._confirm_delete(n)), False, False, 0)
            row.pack_end(button("✎ Pervadinti / sujungti", lambda n=name: self._ask_rename(n)), False, False, 0)
            row.speaker = name
            self.known.add(row)
        self.known.show_all()

    # ── 🔄 pertikrinimas pagal išmoktus ──
    def recheck_if_stale(self) -> bool:
        """Pertikrinti pačiam (auto_refresh), jei pasiūlymai pasenę (store.suggestions_stale)."""
        if not self.auto or self.job is not None or not self.voices:
            return False
        c = config.load()
        if not store.suggestions_stale(float(c["SPEAKER_THRESHOLD"]), float(c["SPEAKER_MARGIN"]),
                                       float(c["SPEAKER_SUGGEST"]), {v.id for v in self.voices}):
            return False
        return self.recheck()

    def recheck(self, user: bool = False) -> bool:
        """Anksčiau priskirtus vardus pritaikyti tekstams ir fone perskaičiuoti 💡 pasiūlymus.
        Jei jau vyksta — paleidžiama dar kartą po jo (balsai galėjo pasikeisti)."""
        if self.job is not None:
            self.job_again = bool(self.job_again) or user
            return False
        fixed = store.apply_assigned()
        if fixed and self.win is not None:
            self.win.text.refresh()
        try:
            p = subprocess.Popen(suggest_cmd(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                 cwd=str(paths.REPO), env={**os.environ, "PYTHONPATH": str(paths.REPO)})
        except OSError as e:
            if user:
                self.set_msg(f"✗ Pertikrinti nepavyko: {e}", "dk-error")
            return False
        self.job, self.job_user, self.job_fixed, self.job_lines = p, user, fixed, []
        self.job_thread = threading.Thread(target=self._read_job, args=(p, self.job_lines), daemon=True)
        self.job_thread.start()
        self.btn_recheck.set_sensitive(False)
        self.btn_accept.hide()
        self.lbl_sugg.set_text("⏳ Pertikrinama…")
        GLib.timeout_add(300, self._poll_job)
        return True

    @staticmethod
    def _read_job(p, lines) -> None:
        for ln in p.stdout:
            lines.append(ln.strip())

    def _poll_job(self):
        if not self._alive or self.job is None:
            return False
        p = self.job
        if p.poll() is None:
            last = self.job_lines[-1] if self.job_lines else ""
            if last.startswith("profiliai "):
                self.lbl_sugg.set_text(f"⏳ Pertikrinama… balso profiliai {last.split()[-1]}")
            return True
        self.job_thread.join(timeout=2)
        try:
            r = json.loads(self.job_lines[-1])
        except (ValueError, IndexError):
            r = {"ok": False, "error": f"klaida ({p.returncode})"}
        user, fixed, again = self.job_user, self.job_fixed, self.job_again
        self.job, self.job_again = None, None
        self.btn_recheck.set_sensitive(True)
        self.reload(keep_current=True)
        if user or not r.get("ok"):
            self.set_msg(recheck_summary(r, fixed), "dk-ok" if r.get("ok") else "dk-error")
        if again is not None:
            self.recheck(user=again)
        return False

    def accept_strong(self) -> int:
        """Priimti visus užtikrintus pasiūlymus (be balsų mokymosi). -> kiek balsų priimta."""
        pairs = self.strong_pairs()
        if not pairs:
            return 0
        self.stop()
        n = store.assign_many(pairs)
        self._after_change(0)
        self.set_msg(f"✓ Priimta užtikrintų pasiūlymų: {len(pairs)} (tekstuose pakeista eilučių: {n}). "
                     "Balsai neišmokti — pakeisti tik vardai tekstuose.", "dk-ok")
        return len(pairs)

    def _confirm_accept_strong(self) -> None:
        pairs = self.strong_pairs()
        if not pairs:
            return
        by = Counter(n or "„Ne žmogus“ (triukšmas)" for _, n in pairs)
        dlg = self._dialog(f"Priimti {len(pairs)} užtikrintus pasiūlymus?",
                           "Jie siekia vardo slenksčio ir atsargos — tokius ir transkripcija atpažintų pati. "
                           "Tekstuose bus: " + ", ".join(f"{k} — {v}" for k, v in by.most_common()) + ". "
                           "Balsai neišmokstami; klaidingą eilutę vėliau pataisysi Tekste (✎ Kas kalbėjo?).")
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK:
            self.accept_strong()

    # ── veiksmai ──
    def set_msg(self, text, css=None) -> None:
        ctx = self.msg.get_style_context()
        for c in ("dk-error", "dk-ok"):
            ctx.remove_class(c)
        if css:
            ctx.add_class(css)
        self.msg.set_text(text)

    def _after_change(self, idx, play=False) -> None:
        self.cur = None
        self.reload(keep_index=idx)
        if self.win is not None:
            self.win.text.refresh()             # tekstuose vardai pasikeitė — perpiešti
        if play:
            self.play_current()                 # kitas balsas groja pats — rašai vardą, Enter, ir vėl
        if self.auto:
            self.recheck()                      # įvardinus — kiti to žmogaus fragmentai gauna 💡

    # ── klaviatūra ──
    def on_key(self, ev) -> bool:
        """Ctrl+Tarpas — groti / stabdyti pavyzdį, Ctrl+Shift+Tarpas — vieta įraše; žymeklis — vardo laukelyje.
        Kviečia MainWindow (lango lygiu — veikia ir rašant vardą)."""
        from diktatura.ui.gtk import Gdk
        if ev.keyval != Gdk.KEY_space or self.cur is None or self.tabs.get_visible_child_name() != "pending":
            return False
        M = Gdk.ModifierType
        mods = ev.state & (M.CONTROL_MASK | M.SHIFT_MASK | M.MOD1_MASK | M.SUPER_MASK)
        if not mods & M.CONTROL_MASK or mods & (M.MOD1_MASK | M.SUPER_MASK):
            return False
        self.toggle_play("context" if mods & M.SHIFT_MASK else "sample")
        self.focus_name()
        return True

    def focus_name(self) -> None:
        """Žymeklis į vardo laukelį: pasiūlymas pažymėtas (rašant pakeičiamas), ranka pradėtas vardas — tęsiamas."""
        text = self.entry.get_text()
        self.entry.grab_focus()
        if text and text == self._prefilled:
            self.entry.select_region(0, -1)
        else:
            self.entry.set_position(-1)

    def on_enter(self) -> bool:
        """Enter vardo laukelyje: įrašyti ir groti kitą; tuščias — praleisti (nežinai, kas tai)."""
        if self.cur is not None and not self.entry.get_text().strip():
            self.skip()
            return False
        return self.assign()

    def _on_match(self, _comp, model, it) -> bool:
        """Pasirinktas esamas vardas iš sąrašo: Enter — iškart priskiriamas (kaip Enter laukelyje), pele — tik įrašomas."""
        self.entry.set_text(model[it][0])
        self.entry.set_position(-1)
        if enter_pressed():
            GLib.idle_add(self._assign_idle)
        return True

    def _assign_idle(self) -> bool:
        if self._alive:
            self.assign()
        return False

    def assign(self) -> bool:
        if not self.cur:
            return False
        name = self.entry.get_text()
        if store.is_me(name):
            return self.its_me()
        try:
            clean = store.clean_name(name)
            idx = self.voices.index(self.cur)
            pid = self.cur.id
            n = store.assign(pid, clean)
        except (ValueError, KeyError) as e:
            self.set_msg(f"✗ {e}", "dk-error")
            return False
        self.stop()
        self._after_change(idx, play=True)
        self.set_msg(f"✓ {pid} → {clean} (tekstuose pakeista eilučių: {n}). Ateityje bus atpažįstamas automatiškai.",
                     "dk-ok")
        return True

    def not_human(self) -> bool:
        if not self.cur:
            return False
        idx, pid = self.voices.index(self.cur), self.cur.id
        self.stop()
        n = store.discard(pid)
        self._after_change(idx, play=True)
        self.set_msg(f"✓ {pid} pašalintas kaip triukšmas (tekstuose -> „{store.UNKNOWN}“: {n} eil.)", "dk-ok")
        return True

    def its_me(self) -> bool:
        if not self.cur:
            return False
        idx, pid = self.voices.index(self.cur), self.cur.id
        self.stop()
        n = store.assign_owner(pid)
        self._after_change(idx, play=True)
        self.set_msg(f"✓ {pid} — tavo balsas (tekstuose -> „{store.ME}“: {n} eil.). Kolegų kanale tave atpažins.",
                     "dk-ok")
        return True

    def skip(self) -> None:
        pid = self.cur.id if self.cur else ""
        self.move(1)
        self.set_msg(f"⏭ {pid} praleistas — nieko nekeista" if pid and len(self.voices) > 1 else "")

    def move(self, delta: int, play: bool = True) -> None:
        """◀ / ▶ / praleisti: kitas balsas ir jis groja pats (play)."""
        if not self.voices:
            return
        idx = (self.voices.index(self.cur) + delta) % len(self.voices) if self.cur in self.voices else 0
        self.list.select_row(self.list.get_row_at_index(idx))
        if play:
            self.play_current()

    # ── grojimas ──
    def _spawn(self, cmd) -> bool:
        self.stop()
        try:
            self.player = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
        except OSError as e:
            self.set_msg(f"✗ nepavyko groti: {e}", "dk-error")
            return False
        pause.hold(force=True)                    # VOX neįrašinės perklausos (garsas eina per kolonėles)
        self.btn_play.set_sensitive(False)
        self.btn_stop.set_sensitive(True)
        return True

    def play(self) -> bool:
        if self.cur and self.cur.wav.exists() and self._spawn(player_cmd() + [str(self.cur.wav)]):
            self.playing = "sample"
            return True
        return False

    def play_current(self) -> bool:
        """Groti dabartinį balsą: pavyzdį, o jei jo nėra — vietą įraše."""
        if self.cur is None:
            return False
        return self.play() if self.cur.wav.exists() else self.play_context()

    def is_playing(self) -> bool:
        return self.player is not None and self.player.poll() is None

    def toggle_play(self, kind: str = "sample") -> bool:
        """Ctrl+Tarpas: groja tas pats — sustabdyti; kitaip groti (sample — pavyzdį, context — vietą įraše)."""
        if kind == "sample" and self.cur is not None and not self.cur.wav.exists():
            kind = "context"                      # pavyzdžio nėra — „pavyzdys" yra vieta įraše
        if self.is_playing() and self.playing == kind:
            self.stop()
            return False
        return self.play_context() if kind == "context" else self.play_current()

    def context_span(self, occ):
        """Eilutės vieta įraše su ±spin_pad s -> (garsas, pradžia, trukmė) | None (nėra garso)."""
        f, ts, _tx, idx = occ
        audio = sessions.audio_for(f)
        if audio is None:
            return None
        t0 = float(sessions.ts_seconds(ts))
        span = store.line_span(f, idx) or (t0, t0 + 5.0)
        pad = self.spin_pad.get_value()
        start = max(0.0, span[0] - pad)
        return audio, start, span[1] + pad - start

    def play_context(self, occ=None) -> bool:
        """„🔊 Įraše": groti eilutės vietą originaliame įraše su keliomis sekundėmis prieš ir po
        (occ — spragtelėta „Ką sakė" eilutė; kitaip pasirinkta arba pirmoji)."""
        if occ is None:
            row = self.ctx.get_selected_row()
            occ = row.occ if row is not None else (self.occ[0] if self.occ else None)
        if not self.cur or occ is None:
            return False
        r = self.context_span(occ)
        if r is None:
            self.set_msg("⚠ šio įrašo garso nebėra (ištrintas arba perkeltas)", "dk-error")
            return False
        audio, start, dur = r
        if not self._spawn(seek_player.command(str(audio), start, dur)):
            return False
        self.playing = "context"
        self.set_msg(f"🔊 {sessions.base_name(audio.name)} · {fmt_sec(start)}–{fmt_sec(start + dur)}")
        return True

    def stop(self) -> None:
        was = self.player is not None
        if self.player and self.player.poll() is None:
            self.player.terminate()
            try:
                self.player.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.player.kill()
        self.player = None
        self.playing = None
        if was:
            pause.release()                       # dar trumpa uodega — kol nutils kolonėlės ir buferiai
        self.btn_stop.set_sensitive(False)
        self.btn_play.set_sensitive(bool(self.cur and self.cur.wav.exists()))

    def _poll_player(self):
        if not self._alive:
            return False
        if self.player and self.player.poll() is not None:
            self.stop()
        elif self.player:
            pause.hold()                          # grojama — pratęsti pauzę
        return True

    def rename(self, old: str, new: str) -> int:
        n = store.rename_speaker(old, new)
        self._after_change(self.voices.index(self.cur) if self.cur in self.voices else 0)
        self.set_msg(f"✓ „{old}“ → „{store.clean_name(new)}“ (tekstuose pakeista eilučių: {n})", "dk-ok")
        return n

    def forget(self, name: str) -> None:
        store.delete_speaker(name)
        self._reload_known()
        self._fill_names()
        self.set_msg(f"✓ „{name}“ balsas pamirštas (tekstai nekeisti)", "dk-ok")
        if self.auto:
            self.recheck()

    def forget_me(self) -> None:
        store.clear_owner()
        self._reload_known()
        self.set_msg("✓ Tavo balso pavyzdžiai pamiršti (tekstai nekeisti)", "dk-ok")
        if self.auto:
            self.recheck()

    def _confirm_forget_me(self) -> None:
        dlg = self._dialog("Pamiršti tavo balsą?", "Kolegų kanale tavo balsas nebebus atpažįstamas kaip „Tu“ "
                                                   "(tekstai nesikeis).", Gtk.ButtonsType.YES_NO)
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.YES:
            self.forget_me()

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
