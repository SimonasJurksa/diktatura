"""Diktatūra — lango temos (Nustatymai → Išvaizda → THEME). Tik gi + stdlib (sistemos python3).

Tema = GTK tema (arba sistemos) + tamsus variantas + šrifto mastelis (gtk-xft-dpi, tik šiam procesui) + papildomas CSS
mūsų klasėms + kalbėtojų / teksto lango spalvos (tamsiame fone tamsiai mėlynas vardas neįskaitomas, dideliame
kontraste — reikia sočių tamsių spalvų ir be „pritemdyto" pagalbinio teksto).
  light    — kaip sistemoje (numatytoji);
  dark     — sistemos temos tamsus variantas;
  contrast — GTK „HighContrast" (juoda ant baltos), šriftas ×1.4, storas fokuso rėmelis, pagalbinis tekstas nepritemdytas;
  compact  — šriftas ×0.85, mažesni mygtukai ir tarpai, Apmokymuose be įžangos (mažam ekranui).
apply() pirmą kartą įsimena sistemos reikšmes — grįžtant į „light" jos atstatomos.
"""
from dataclasses import dataclass, field

from diktatura.ui.gtk import Gdk, Gtk

LIGHT_PALETTE = ("#1a73e8", "#188038", "#d93025", "#9334e6", "#e37400", "#00897b", "#c5221f", "#7cb342", "#6d4c41")


@dataclass(frozen=True)
class Theme:
    name: str
    gtk_theme: str = None           # None — sistemos
    dark: bool = None               # None — kaip sistemoje
    scale: float = 1.0              # šrifto mastelis
    css: bytes = b""
    palette: tuple = LIGHT_PALETTE  # kalbėtojų vardų spalvos teksto lange
    text: dict = field(default_factory=lambda: {"sep": "#888888", "time": "#999999", "mark": "#e37400"})
    compact: bool = False


THEMES = {
    "light": Theme("light"),
    "dark": Theme(
        "dark", dark=True,
        css=b""".dk-error { color: #f28b82; } .dk-ok { color: #81c995; }
.dk-intro { background-color: alpha(@theme_selected_bg_color, 0.22); }""",
        palette=("#8ab4f8", "#81c995", "#f28b82", "#c58af9", "#fcad70", "#78d9ec", "#ff8bcb", "#c5e1a5", "#d7b7a5"),
        text={"sep": "#9aa0a6", "time": "#80868b", "mark": "#fcad70"}),
    "contrast": Theme(
        "contrast", gtk_theme="HighContrast", dark=False, scale=1.4,
        css=b""".dk-help { opacity: 1; font-size: 1em; }
.dk-error { color: #a30000; font-weight: bold; } .dk-ok { color: #005c00; font-weight: bold; }
.dk-intro { background-color: #ffffcc; border: 2px solid #000000; }
.dk-title { font-size: 1.25em; }
*:focus { outline-style: solid; outline-width: 3px; outline-color: #000000; outline-offset: 1px; }""",
        palette=("#0000b3", "#005c00", "#a30000", "#5c0099", "#7a3d00", "#00555c", "#8f0047", "#3d5c00", "#4d2e1f"),
        text={"sep": "#000000", "time": "#333333", "mark": "#7a3d00"}),
    "compact": Theme(
        "compact", scale=0.85, compact=True,
        css=b"""button { padding: 2px 6px; min-height: 22px; min-width: 22px; }
entry, spinbutton { min-height: 24px; }
headerbar { min-height: 32px; padding-top: 0; padding-bottom: 0; }
.dk-intro { padding: 4px 6px; } .dk-title { font-size: 1.05em; }"""),
}
NAMES = tuple(THEMES)

_orig = None                        # (gtk-theme-name, prefer-dark, xft-dpi) — sistemos, iki pirmo apply()
_prov = None


def get(name) -> Theme:
    return THEMES.get(name, THEMES["light"])


def apply(name) -> Theme:
    """Pritaikyti temą visam procesui (visiems langams). Be ekrano (testai be GTK) — tik grąžina temą."""
    global _orig, _prov
    t = get(name)
    s, screen = Gtk.Settings.get_default(), Gdk.Screen.get_default()
    if s is None or screen is None:
        return t
    if _orig is None:
        _orig = (s.props.gtk_theme_name, s.props.gtk_application_prefer_dark_theme, s.props.gtk_xft_dpi)
    theme, dark, dpi = _orig
    s.props.gtk_theme_name = t.gtk_theme or theme
    s.props.gtk_application_prefer_dark_theme = dark if t.dark is None else t.dark
    base = dpi if dpi and dpi > 0 else 96 * 1024
    s.props.gtk_xft_dpi = int(base * t.scale)
    if _prov is not None:
        Gtk.StyleContext.remove_provider_for_screen(screen, _prov)
    _prov = Gtk.CssProvider()
    _prov.load_from_data(t.css or b"* {}")
    Gtk.StyleContext.add_provider_for_screen(screen, _prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    return t
