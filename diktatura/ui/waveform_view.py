"""Diktatūra UI — 🌊 garso banga (Gtk.DrawingArea + cairo; sistemos python3, be numpy).

Juostos: stereo — viršuje „Tu" (L, mikrofonas), apačioje kolegos (R, sistemos garsas); mono — viena. Kolegų (ir mono)
juosta nuspalvinta pagal tai, kieno eilutė tuo metu (kalbėtojų spalvos kaip tekste); viršuje — eilučių žymės.
Spragtelėjus — on_seek(sekundė) (Tekstas groja nuo ten). Ratukas — artinti / tolinti ties pele, Shift+ratukas (ar
horizontalus) — slinkti; dvigubas spragtelėjimas — visa sesija. Užvedus pelę — laikas ir ta eilutė.
⏳ langelis: set_processed([L s, R s]) — neapdorota dalis išblukusi.
Gryna logika (laikas ↔ x, eilutė ties laiku, spalvos, artinimas) — be piešimo, testuojama.
"""
import bisect

import gi

gi.require_version("PangoCairo", "1.0")
from gi.repository import PangoCairo  # noqa: E402

from diktatura import waveform  # noqa: E402
from diktatura.ui.gtk import Gdk, Gtk, Pango  # noqa: E402

MIN_VIEW = 10.0          # s — labiausiai priartinus
SEG_MAX = 30.0           # s — kiek ilgiausiai po eilutės laiko juosta dažoma jos kalbėtojo spalva
PLAYHEAD = (0.89, 0.11, 0.28)


def fmt_t(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def hex_rgb(color: str) -> tuple:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (0.5, 0.5, 0.5)


class WaveformView(Gtk.DrawingArea):
    def __init__(self, on_seek=None, height: int = 84):
        super().__init__()
        self.on_seek = on_seek
        self.set_size_request(120, height)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK
                        | Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.set_has_tooltip(True)
        self.peaks = None
        self.scales = []
        self.duration = 0.0
        self.view = (0.0, 0.0)
        self.lines = []          # [(s, kalbėtojas, spalva, tekstas)] laiko tvarka
        self._times = []
        self.me = "Tu"
        self.lane_names = ("Tu", "Kolegos")
        self.me_color = "#1a73e8"
        self.other_color = "#80868b"
        self.position = None     # grojimo vieta (s)
        self.processed = None    # [L s, R s] — ⏳: kiek kanalo jau apdorota
        self.band = None         # (pradžia, pabaiga) s — pasirinkta eilutė
        self.message = ""        # rodoma vietoj bangos (pvz. „skaičiuojama…")
        self._cache = None
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_press)
        self.connect("scroll-event", self._on_scroll)
        self.connect("query-tooltip", self._on_tooltip)

    # ── duomenys ──
    def set_peaks(self, pk) -> None:
        self.peaks = pk
        self.scales = [waveform.scale_of(pk.channel(i)) for i in range(pk.channels)] if pk else []
        self.duration = pk.duration if pk else 0.0
        self.view = (0.0, self.duration)
        self.message = ""
        self._cache = None
        self.queue_draw()

    def set_lines(self, lines, me: str = None) -> None:
        self.lines = sorted((ln for ln in lines if ln[0] is not None), key=lambda ln: ln[0])
        self._times = [ln[0] for ln in self.lines]
        if me:
            self.me = me
        self._cache = None
        self.queue_draw()

    def set_colors(self, me_color: str = None, other_color: str = None) -> None:
        self.me_color = me_color or self.me_color
        self.other_color = other_color or self.other_color
        self._cache = None
        self.queue_draw()

    def set_position(self, sec) -> None:
        if sec is not None and self.duration and not (self.view[0] <= sec <= self.view[1]):
            span = self.view[1] - self.view[0]                 # grojimas išėjo už rodomos dalies — slenkam kartu
            self.set_view(sec - span * 0.1, sec + span * 0.9)
        self.position = sec
        self.queue_draw()

    def set_processed(self, secs) -> None:
        self.processed = list(secs) if secs is not None else None
        self.queue_draw()

    def set_band(self, start, end) -> None:
        self.band = (start, end) if start is not None else None
        self.queue_draw()

    def set_message(self, text: str) -> None:
        self.message = text
        self.queue_draw()

    # ── gryna logika ──
    def width(self) -> int:
        return max(1, self.get_allocated_width())

    def x_to_sec(self, x: float, width: int = None) -> float:
        w = width or self.width()
        v0, v1 = self.view
        return max(0.0, min(self.duration, v0 + (v1 - v0) * max(0.0, min(1.0, x / w))))

    def sec_to_x(self, sec: float, width: int = None) -> float:
        w = width or self.width()
        v0, v1 = self.view
        return (sec - v0) / ((v1 - v0) or 1.0) * w

    def line_at(self, sec: float):
        """Eilutė, kuri skamba ties sec (paskutinė prasidėjusi), arba None."""
        i = bisect.bisect_right(self._times, sec + 0.25) - 1
        return self.lines[i] if i >= 0 else None

    def segment_color(self, sec: float, lane: int, lanes: int) -> str:
        """Juostos spalva ties sec: „Tu" juosta — tavo spalva; kolegų / mono — tuo metu kalbančiojo."""
        if lanes == 2 and lane == 0:
            return self.me_color
        ln = self.line_at(sec)
        if ln is None or sec - ln[0] > SEG_MAX:
            return self.other_color
        if lanes == 2 and ln[1] == self.me:            # stereo: tavo eilutė kolegų juostos nedažo
            return self.other_color
        return ln[2]

    def set_view(self, v0: float, v1: float) -> None:
        span = max(MIN_VIEW, v1 - v0) if self.duration > MIN_VIEW else self.duration
        span = min(span, self.duration) if self.duration else 0.0
        v0 = max(0.0, min(v0, self.duration - span))
        self.view = (v0, v0 + span)
        self._cache = None
        self.queue_draw()

    def zoom(self, factor: float, at_x: float = None) -> None:
        """factor < 1 — artinti, > 1 — tolinti; ties at_x išlieka tas pats laikas."""
        if not self.duration:
            return
        w = self.width()
        at = self.x_to_sec(at_x if at_x is not None else w / 2, w)
        v0, v1 = self.view
        span = (v1 - v0) * factor
        frac = (at - v0) / ((v1 - v0) or 1.0)
        self.set_view(at - span * frac, at - span * frac + span)

    def pan(self, frac: float) -> None:
        v0, v1 = self.view
        d = (v1 - v0) * frac
        self.set_view(v0 + d, v1 + d)

    def reset_view(self) -> None:
        self.set_view(0.0, self.duration)

    def columns(self, width: int) -> list:
        """[[aukščiai 0..1] kanalui] matomai daliai (talpykla pagal plotį ir vaizdą)."""
        key = (width, self.view, id(self.peaks))
        if self._cache and self._cache[0] == key:
            return self._cache[1]
        pk = self.peaks
        cols = []
        if pk and pk.frames:
            a, b = int(self.view[0] * pk.rate), int(round(self.view[1] * pk.rate))
            for i in range(pk.channels):
                cols.append(waveform.columns(pk.channel(i), width, a, max(a + 1, b), self.scales[i]))
        self._cache = (key, cols)
        return cols

    # ── piešimas ──
    def _on_draw(self, _w, cr) -> bool:
        w, h = self.get_allocated_width(), self.get_allocated_height()
        fg = self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.05)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        if not self.peaks or not self.peaks.frames:
            self._text(cr, self.message or "Bangos nėra", w / 2, h / 2, fg, center=True)
            return False
        cols = self.columns(w)
        lanes = len(cols)
        top, bottom = 6, h - 14                       # viršuje — eilučių žymės, apačioje — laikai
        lane_h = (bottom - top) / lanes
        if self.band:
            x0, x1 = self.sec_to_x(self.band[0], w), self.sec_to_x(self.band[1], w)
            sel = self.get_style_context().lookup_color("theme_selected_bg_color")
            c = sel[1] if sel[0] else fg
            cr.set_source_rgba(c.red, c.green, c.blue, 0.22)
            cr.rectangle(x0, 0, max(2.0, x1 - x0), h)
            cr.fill()
        sec_per_px = (self.view[1] - self.view[0]) / w
        for lane, heights in enumerate(cols):
            mid = top + lane_h * (lane + 0.5)
            done = self.processed[lane] if self.processed and lane < len(self.processed) else None
            runs = {}
            for x, v in enumerate(heights):
                t = self.view[0] + x * sec_per_px
                col = self.segment_color(t, lane, lanes)
                faded = done is not None and t > done
                bh = max(1.0, v * (lane_h / 2 - 1))
                runs.setdefault((col, faded, v < 0.03), []).append((x, mid - bh, 2 * bh))
            for (col, faded, quiet), rects in runs.items():
                r, g, b = hex_rgb(col)
                cr.set_source_rgba(r, g, b, (0.28 if faded else 0.9) * (0.4 if quiet else 1.0))
                for x, y, hh in rects:
                    cr.rectangle(x, y, 1, hh)
                cr.fill()
            if lanes == 2:
                self._text(cr, self.lane_names[lane], 4, mid - lane_h / 2 + 1, fg, alpha=0.75, bg=True)
        for s, _spk, color, _txt in self.lines:      # eilučių žymės
            if self.view[0] <= s <= self.view[1]:
                r, g, b = hex_rgb(color)
                cr.set_source_rgb(r, g, b)
                cr.rectangle(self.sec_to_x(s, w) - 1, 0, 2, 5)
                cr.fill()
        if self.position is not None and self.view[0] <= self.position <= self.view[1]:
            cr.set_source_rgb(*PLAYHEAD)
            x = self.sec_to_x(self.position, w)
            cr.rectangle(x - 1, 0, 2, h)
            cr.fill()
        self._text(cr, fmt_t(self.view[0]), 2, h - 13, fg, alpha=0.7)
        zoomed = self.view[1] - self.view[0] < self.duration - 0.5
        right = fmt_t(self.view[1]) + (f"  (iš {fmt_t(self.duration)})" if zoomed else "")
        self._text(cr, right, w - 2, h - 13, fg, alpha=0.7, right=True)
        return False

    def _text(self, cr, text, x, y, fg, alpha=0.8, center=False, right=False, bg=False) -> None:
        layout = PangoCairo.create_layout(cr)
        fd = self.get_pango_context().get_font_description().copy()
        fd.set_size(int(fd.get_size() * 0.8) or 8 * Pango.SCALE)
        layout.set_font_description(fd)
        layout.set_text(text, -1)
        tw, th = layout.get_pixel_size()
        if center:
            x, y = x - tw / 2, y - th / 2
        elif right:
            x -= tw
        if bg:                                         # užrašas virš bangos — su fonu, kad būtų įskaitomas
            ok, c = self.get_style_context().lookup_color("theme_bg_color")
            if ok:
                cr.set_source_rgba(c.red, c.green, c.blue, 0.8)
                cr.rectangle(x - 2, y, tw + 4, th)
                cr.fill()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, alpha)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, layout)

    # ── įvykiai ──
    def _on_press(self, _w, ev) -> bool:
        if ev.button != 1 or not self.duration:
            return False
        if ev.type == Gdk.EventType._2BUTTON_PRESS:
            self.reset_view()
            return True
        if self.on_seek:
            self.on_seek(self.x_to_sec(ev.x))
        return True

    def _on_scroll(self, _w, ev) -> bool:
        if not self.duration:
            return False
        dy = 0.0
        if ev.direction == Gdk.ScrollDirection.SMOOTH:
            ok, dx, dy = ev.get_scroll_deltas()
            if abs(dx) > abs(dy):
                self.pan(0.1 * dx)
                return True
        elif ev.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
            dy = -1.0 if ev.direction == Gdk.ScrollDirection.UP else 1.0
        elif ev.direction in (Gdk.ScrollDirection.LEFT, Gdk.ScrollDirection.RIGHT):
            self.pan(-0.1 if ev.direction == Gdk.ScrollDirection.LEFT else 0.1)
            return True
        if not dy:
            return False
        if ev.state & Gdk.ModifierType.SHIFT_MASK:
            self.pan(0.1 * dy)
        else:
            self.zoom(1.5 if dy > 0 else 1 / 1.5, ev.x)
        return True

    def tooltip_text(self, x: float) -> str:
        t = self.x_to_sec(x)
        ln = self.line_at(t)
        tip = fmt_t(t)
        if ln is not None and t - ln[0] <= SEG_MAX:
            tip += f" · {ln[1]}: {ln[3][:90]}" if ln[1] else f" · {ln[3][:90]}"
        return tip + "\nSpragtelėk — groti nuo čia · ratukas — artinti · 2× spragtelėk — visa sesija"

    def _on_tooltip(self, _w, x, _y, _kb, tooltip) -> bool:
        if not self.duration:
            return False
        tooltip.set_text(self.tooltip_text(x))
        return True
