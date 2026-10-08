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
