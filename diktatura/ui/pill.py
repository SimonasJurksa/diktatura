"""Diktatūra UI — 💊 įrašymo indikatorius ekrano kampe (REC_PILL; veikia ikonos procese, sistemos python3).

Kol įrašoma (VOX ar Slack) — mažas langelis: 🔴, šaltinis, laikmatis ir GYVA abiejų kanalų banga (paskutinės ~8 s:
viršuje tu, apačioje kolegos) — atsakymas į „ar mane girdi?". Lygiai skaičiuojami iš rašomo wav failo galo (VOX ir
Slack rašo stereo 16 kHz wav), todėl įrašymo daemon'ų keisti nereikia.
Įrašui pasibaigus: „⏳ Transkribuojama 43 % · liko ~2 min" (diktatura.progress), „🌙 Transkribuos naktį", „✅ Tekstas
paruoštas"; jei įrašas buvo per trumpas (ištrintas) — tiesiog dingsta.
Rodomas tik įrašui trunkant ≥ SHOW_AFTER s (kosulys ar spragtelėjimas indikatoriaus nemirkčioja).
Spragtelėjus — atidaromas Tekstas (transkribuojant — ⏳ langelis); ✕ — paslėpti iki kito įrašo.
Gryna logika (lygiai iš failo galo, kas rodoma) — be GTK, testuojama.
"""
import array
import math
import struct
import sys
import time
from collections import deque
from pathlib import Path

from diktatura import config, paths, progress, sessions

CHUNK_SEC = 0.1
KEEP = 80                  # gabalų (8 s) gyvoje bangoje
SHOW_AFTER = 1.5           # s — trumpesni įrašai indikatoriaus nerodo
DONE_SHOW = 6.0            # s — „✅ Tekstas paruoštas" / „🌙 naktį" rodoma tiek, paskui dingsta
GONE_AFTER = 90.0          # s — jei po įrašo niekas nevyksta (nei eilė, nei tekstas) — paslėpti
TICK_MS = 100


def wav_layout(path):
    """(duomenų pradžia, kanalai, dažnis, baitai mėginiui) iš wav antraštės; nežinomas formatas -> None.
    ffmpeg (Slack) antraštėje gali būti papildomų blokų (LIST), todėl ieškoma „data" bloko."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return None
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return None
    pos, fmt = 12, None
    while pos + 8 <= len(head):
        cid, size = head[pos:pos + 4], struct.unpack_from("<I", head, pos + 4)[0]
        if cid == b"fmt " and pos + 24 <= len(head):
            _tag, ch, rate, _br, _align, bits = struct.unpack_from("<HHIIHH", head, pos + 8)
            fmt = (ch, rate, bits // 8)
        if cid == b"data":
            return (pos + 8, *fmt) if fmt and fmt[2] == 2 else None
        pos += 8 + size + (size & 1)
    return None


def level_db(samples) -> float:
    if not samples:
        return -120.0
    acc = sum(x * x for x in samples) / len(samples)
    return 20 * math.log10(math.sqrt(acc) / 32768.0 + 1e-9)


class LiveLevels:
    """Augančio wav failo galas -> kanalų lygiai (dBFS) kas 100 ms. Skaito tik naujus baitus."""

    def __init__(self, path, keep: int = KEEP):
        self.path = Path(path)
        self.levels = deque(maxlen=keep)            # [(L, R)] arba [(M,)]
        self.layout = None
        self.pos = None
        self.size = 0

    @property
    def seconds(self) -> float:
        if not self.layout:
            return 0.0
        off, ch, rate, width = self.layout
        return max(0, self.size - off) / (ch * rate * width)

    def poll(self) -> int:
        """Nuskaityti naujus pilnus 100 ms gabalus. -> kiek naujų."""
        if self.layout is None:
            self.layout = wav_layout(self.path)
            if self.layout is None:
                return 0
        off, ch, rate, width = self.layout
        try:
            self.size = self.path.stat().st_size
        except OSError:
            return 0
        step = int(rate * CHUNK_SEC) * ch * width
        if self.pos is None:                         # pirmą kartą — tik paskutinės KEEP gabalų
            self.pos = max(off, off + ((self.size - off) // step - self.levels.maxlen) * step)
        avail = (self.size - self.pos) // step
        if avail <= 0:
            return 0
        n = min(avail, self.levels.maxlen)
        start = self.pos + (avail - n) * step         # atsilikus (pvz. langas buvo paslėptas) — tik naujausi
        try:
            with open(self.path, "rb") as fh:
                fh.seek(start)
                data = fh.read(n * step)
        except OSError:
            return 0
        for i in range(len(data) // step):
            a = array.array("h", data[i * step:(i + 1) * step])
            if sys.byteorder != "little":
                a.byteswap()
            self.levels.append(tuple(level_db(a[c::ch]) for c in range(ch)))
        self.pos = start + (len(data) // step) * step
        return len(data) // step


def height(db: float) -> float:
    """dBFS -> juostos aukštis 0..1 (−60 dB tyla, −10 dB — pilna)."""
    return max(0.0, min(1.0, (db + 60.0) / 50.0))


def recording_now():
    """(šaltinis, kelias) iš <runtime>/recording arba None."""
    try:
        src, path = paths.STATE_RECORDING.read_text().split(maxsplit=1)
        return src, Path(path.strip())
    except (OSError, ValueError):
        return None


def after_text(rec: Path, snap, cfg: dict, ended: float, now: float):
    """Kas rodoma po įrašo: (tekstas, eigos dalis | None) arba None — slėpti. Gryna funkcija."""
    base = sessions.base_name(rec.name)
    texts = [rec.with_name(base + s) for s in (".named.txt", ".txt")]
    if any(t.exists() and t.stat().st_size > 0 for t in texts):
        return ("✅ Tekstas paruoštas — spragtelėk", None) if now - ended < DONE_SHOW + 30 else None
    audio_left = any(rec.with_name(base + s).exists() for s in (".wav", ".mp3"))
    if snap is not None:
        for j in snap.jobs:
            if sessions.base_name(j.file.name) == base:
                if j.state == "running":
                    return (f"⏳ Transkribuojama {int(j.fraction * 100)} % · liko {progress.fmt_left(j.left)}",
                            j.fraction)
                return (f"⏳ Laukia eilėje · prieš jį {snap.jobs.index(j)} f.", 0.0)
    if not audio_left:
        return None                                  # per trumpas / be kalbos — ištrintas
    if now - ended > GONE_AFTER:
        return None
    if not cfg.get("AUTOTRANSCRIBE", True):
        return ("⏸ Išsaugota (auto-transkripcija išjungta)", None) if now - ended < DONE_SHOW else None
    if cfg.get("MODE") == "deferred":
        return ("🌙 Išsaugota — transkribuos naktį (01:30)", None) if now - ended < DONE_SHOW else None
    return ("⏳ Ruošiamasi transkribuoti…", None)


class PillController:
    """Būsenų mašina (be GTK): idle -> rec (įrašoma ≥ SHOW_AFTER) -> after (eiga / naktį / tekstas) -> idle.
    view — objektas su show_rec(šaltinis, sek, lygiai), show_after(tekstas, dalis), hide()."""

    def __init__(self, view, rec_fn=recording_now, snap_fn=progress.snapshot, cfg_fn=config.load, clock=time.time):
        self.view, self.rec_fn, self.snap_fn, self.cfg_fn, self.clock = view, rec_fn, snap_fn, cfg_fn, clock
        self.state = "idle"
        self.rec = None              # (šaltinis, kelias)
        self.levels = None
        self.ended = 0.0
        self.dismissed = None        # ✕ — šiam įrašui nebe rodyti
        self._cfg, self._cfg_t, self._snap_t = {}, -1e9, -1e9
        self._snap = None

    def cfg(self) -> dict:
        now = self.clock()
        if now - self._cfg_t > 3:
            try:
                self._cfg = self.cfg_fn()
            except (OSError, ValueError):
                pass
            self._cfg_t = now
        return self._cfg

    def snap(self):
        now = self.clock()
        if now - self._snap_t > 1:
            try:
                self._snap = self.snap_fn()
            except Exception:                       # eiga — tik informacija
                self._snap = None
            self._snap_t = now
        return self._snap

    def dismiss(self) -> None:
        self.dismissed = self.rec[1] if self.rec else None
        self.state = "idle" if self.state == "after" else self.state
        self.view.hide()

    def tick(self) -> bool:
        cfg = self.cfg()
        cur = self.rec_fn()
        now = self.clock()
        if cur is not None and (self.rec is None or cur[1] != self.rec[1]):
            self.rec, self.levels, self.state = cur, LiveLevels(cur[1]), "rec"
        if self.state == "rec":
            if cur is None or cur[1] != self.rec[1]:
                self.state, self.ended = "after", now
            else:
                self.levels.poll()
                if not cfg.get("REC_PILL", True) or self.dismissed == self.rec[1] or self.levels.seconds < SHOW_AFTER:
                    self.view.hide()
                else:
                    self.view.show_rec(self.rec[0], self.levels.seconds, list(self.levels.levels))
                return True
        if self.state == "after":
            shown = self.levels is not None and self.levels.seconds >= SHOW_AFTER
            what = after_text(self.rec[1], self.snap(), cfg, self.ended, now) if shown else None
            if what is None or not cfg.get("REC_PILL", True) or self.dismissed == self.rec[1]:
                self.state = "idle"
                self.view.hide()
            else:
                self.view.show_after(*what)
        return True


class PillView:
    """GTK langelis (POPUP — be rėmelio, visada viršuje, fokuso nevagia) apatiniame dešiniajame ekrano kampe."""

    def __init__(self, on_click=None, on_close=None):
        from diktatura.ui.gtk import Gtk, install_css
        install_css()
        self.Gtk = Gtk
        self.on_click = on_click
        self.win = Gtk.Window(type=Gtk.WindowType.POPUP)
        self.win.get_style_context().add_class("dk-pillwin")
        self.win.set_accept_focus(False)
        box = Gtk.Box(spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(6)
        self.lbl = Gtk.Label(xalign=0)          # be trumpinimo: langas mažinamas iki minimumo, tekstai trumpi
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(150, 30)
        self.area.connect("draw", self._draw)
        self.bar = Gtk.ProgressBar()
        self.bar.set_valign(Gtk.Align.CENTER)
        self.bar.set_size_request(80, -1)
        close = Gtk.Button(label="✕")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("Paslėpti iki kito įrašo (Nustatymai → Išvaizda — išjungti visai)")
        close.connect("clicked", lambda _w: on_close and on_close())
        ev = Gtk.EventBox()
        inner = Gtk.Box(spacing=8)
        inner.pack_start(self.lbl, True, True, 0)
        inner.pack_start(self.area, False, False, 0)
        inner.pack_start(self.bar, False, False, 0)
        ev.add(inner)
        ev.connect("button-press-event", lambda *_: self.on_click and self.on_click())
        box.pack_start(ev, True, True, 0)
        box.pack_start(close, False, False, 0)
        self.win.add(box)
        box.show_all()
        self.levels = []
        self.mode = None

    def _place(self) -> None:
        from diktatura.ui.gtk import Gdk
        disp = Gdk.Display.get_default()
        mon = disp.get_primary_monitor() or disp.get_monitor(0)
        if mon is None:
            return
        wa = mon.get_workarea()
        w, h = self.win.get_size()
        self.win.move(wa.x + wa.width - w - 16, wa.y + wa.height - h - 16)

    def show_rec(self, source: str, seconds: float, levels: list) -> None:
        m, s = divmod(int(seconds), 60)
        self.lbl.set_text(f"🔴 {source.upper()} · {m}:{s:02d}")
        self.levels = levels
        self.area.show()
        self.bar.hide()
        self.area.queue_draw()
        self._present("rec")

    def show_after(self, text: str, fraction) -> None:
        self.lbl.set_text(text)
        self.area.hide()
        self.bar.set_visible(fraction is not None)
        if fraction is not None:
            self.bar.set_fraction(fraction)
        self._present("after")

    def _present(self, mode) -> None:
        if not self.win.get_visible() or mode != self.mode:
            self.mode = mode
            self.win.resize(1, 1)
            self.win.show()
            self._place()

    def hide(self) -> None:
        self.mode = None
        if self.win.get_visible():
            self.win.hide()

    def _draw(self, area, cr) -> bool:
        w, h = area.get_allocated_width(), area.get_allocated_height()
        lv = self.levels[-KEEP:]
        if not lv:
            return False
        bw = w / KEEP
        lanes = len(lv[0])
        colors = ((0.10, 0.45, 0.91), (0.09, 0.50, 0.22))       # tu — mėlyna, kolegos — žalia
        for lane in range(lanes):
            mid = h * (lane + 0.5) / lanes
            r, g, b = colors[lane % 2]
            cr.set_source_rgba(r, g, b, 0.9)
            for i, row in enumerate(lv):
                bh = round(max(1.0, height(row[lane]) * (h / lanes / 2 - 1)))
                x0, x1 = round(w - (len(lv) - i) * bw), round(w - (len(lv) - i - 1) * bw)
                cr.rectangle(x0, round(mid) - bh, max(1, x1 - x0 - 1), 2 * bh)   # sveiki pikseliai — ryškūs
            cr.fill()
        return False
