"""Diktatūra UI — GTK importas vienoje vietoje (versijos) ir bendras stilius.

UI moduliai paleidžiami SISTEMOS python3 (turi gi); .venv jo neturi. Čia — tik stdlib + gi.
"""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402,F401

CSS = b"""
.dk-help { opacity: 0.72; font-size: 0.9em; }
.dk-error { color: #d93025; font-size: 0.9em; }
.dk-ok { color: #188038; }
.dk-intro { padding: 12px 14px; border-radius: 8px; background-color: alpha(@theme_selected_bg_color, 0.10); }
.dk-title { font-weight: bold; font-size: 1.15em; }
.dk-mono { font-family: monospace; }
.dk-pill { padding: 2px 8px; border-radius: 10px; background-color: alpha(@theme_fg_color, 0.08); }
"""
_installed = False


def install_css() -> None:
    global _installed
    if _installed or Gdk.Screen.get_default() is None:
        return
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _installed = True


def label(text="", css=None, xalign=0.0, wrap=False, markup=False, selectable=False) -> Gtk.Label:
    lb = Gtk.Label()
    lb.set_markup(text) if markup else lb.set_text(text)
    lb.set_xalign(xalign)
    lb.set_line_wrap(wrap)
    lb.set_selectable(selectable)
    if css:
        for c in css.split():
            lb.get_style_context().add_class(c)
    return lb


def button(text, cb=None, tooltip=None, css=None) -> Gtk.Button:
    b = Gtk.Button(label=text)
    if cb:
        b.connect("clicked", lambda _w: cb())
    if tooltip:
        b.set_tooltip_text(tooltip)
    if css:
        b.get_style_context().add_class(css)
    return b


def group(*widgets, spacing=4) -> Gtk.Box:
    """Kelis valdiklius laikyti kartu (pvz. „Kalbėtojas:" + sąrašas) — flow() jų neperskiria."""
    b = Gtk.Box(spacing=spacing)
    for w in widgets:
        b.pack_start(w, False, False, 0)
    return b


class WrapBox(Gtk.Container):
    """Valdikliai paeiliui kaip tekstas: kas netelpa — į kitą eilutę (mygtukų / filtrų juostos mažam ekranui ir
    dideliam šriftui). Gtk.FlowBox netinka — jis dėlioja stulpeliais (didelės spragos tarp mygtukų).
    Mažiausias plotis = plačiausias valdiklis; aukštis — pagal plotį (height-for-width)."""
    __gtype_name__ = "DkWrapBox"
    _live = set()          # PyGObject: be Python nuorodos objekto Python dalis (_children) dingsta -> GTK naikindamas
    #                        konteinerį suktųsi be galo (buvo: langas „užlūždavo" uždarant). Laikom iki do_destroy.

    def __init__(self, spacing=6, row_spacing=4):
        super().__init__()
        self.set_has_window(False)
        self.spacing, self.row_spacing = spacing, row_spacing
        self._children = []
        WrapBox._live.add(self)

    def do_destroy(self):
        Gtk.Container.do_destroy(self)      # pirma sunaikinami vaikai (forall)
        WrapBox._live.discard(self)

    def do_add(self, widget):
        self._children.append(widget)
        widget.set_parent(self)
        self.queue_resize()

    def do_remove(self, widget):
        if widget in self._children:
            self._children.remove(widget)
            widget.unparent()
            self.queue_resize()

    def do_forall(self, include_internals, callback, *data):
        for c in list(getattr(self, "_children", ())):
            callback(c, *data)

    def do_child_type(self):
        return Gtk.Widget.__gtype__

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def _visible(self):
        return [c for c in self._children if c.get_visible()]

    def lines(self, width):
        """[[(valdiklis, plotis), ...], ...] — eilutės duotam pločiui."""
        out, x = [[]], 0
        for c in self._visible():
            mn, nat = c.get_preferred_width()
            w = max(mn, min(nat, width))
            if out[-1] and x + self.spacing + w > width:
                out.append([])
                x = 0
            x += (self.spacing if out[-1] else 0) + w
            out[-1].append((c, w))
        return [ln for ln in out if ln]

    def _line_height(self, line):
        return max((c.get_preferred_height_for_width(w)[1] for c, w in line), default=0)

    def do_get_preferred_width(self):
        vis = self._visible()
        mins = [c.get_preferred_width()[0] for c in vis]
        nats = [c.get_preferred_width()[1] for c in vis]
        return max(mins, default=0), sum(nats) + self.spacing * max(0, len(vis) - 1)

    def do_get_preferred_height_for_width(self, width):
        ls = self.lines(width)
        h = sum(self._line_height(ln) for ln in ls) + self.row_spacing * max(0, len(ls) - 1)
        return h, h

    def do_get_preferred_height(self):
        return self.do_get_preferred_height_for_width(self.do_get_preferred_width()[1])

    def do_get_preferred_width_for_height(self, height):
        return self.do_get_preferred_width()

    def do_size_allocate(self, alloc):
        self.set_allocation(alloc)
        y = alloc.y
        for line in self.lines(alloc.width):
            lh, x = self._line_height(line), alloc.x
            for c, w in line:
                r = Gdk.Rectangle()
                r.x, r.y, r.width, r.height = x, y, w, lh
                c.size_allocate(r)
                x += w + self.spacing
            y += lh + self.row_spacing


def flow(*widgets, spacing=6) -> WrapBox:
    """Mygtukų / filtrų eilė, kuri siaurame lange persikelia į kitą eilutę (mažas ekranas, didelis šriftas)."""
    wb = WrapBox(spacing=spacing)
    for w in widgets:
        w.set_valign(Gtk.Align.CENTER)
        wb.add(w)
    return wb


def pump(seconds: float = 0.0) -> None:
    """Apdoroti laukiančius GTK įvykius (testams / nuotraukoms)."""
    import time
    end = time.monotonic() + seconds
    while True:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if time.monotonic() >= end:
            break
        time.sleep(0.01)
