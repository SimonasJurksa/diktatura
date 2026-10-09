"""O. Temos (Nustatymai → Išvaizda): šviesi / tamsi / didelis kontrastas / kompaktiška; Apmokymų skirtukai."""
from datetime import datetime

import pytest


@pytest.fixture
def win(env, fake_systemd):
    from diktatura.ui import gtk, themes
    from diktatura.ui.app import MainWindow
    (env.recordings / f"vox_{datetime.now():%Y%m%d}_100000.named.txt").write_text(
        "[0:00:01] Ona: labas\n[0:00:03] Jonas: sveiki\n", encoding="utf-8")
    w = MainWindow(auto_refresh=False)
    w.show_all()
    gtk.pump(0.05)
    yield w
    w.destroy()
    themes.apply("light")                                   # kitiems testams — sistemos reikšmės
    gtk.pump(0.02)


def settings():
    from diktatura.ui.gtk import Gtk
    return Gtk.Settings.get_default().props


def test_o1_each_theme_changes_gtk_and_light_restores(win):
    from diktatura.ui import themes
    base = (settings().gtk_theme_name, settings().gtk_xft_dpi)
    win.apply_theme("dark")
    assert settings().gtk_application_prefer_dark_theme and win.theme.name == "dark"
    win.apply_theme("contrast")
    assert settings().gtk_theme_name == "HighContrast" and not settings().gtk_application_prefer_dark_theme
    dpi = base[1] if base[1] > 0 else 96 * 1024
    assert settings().gtk_xft_dpi == int(dpi * 1.4)                         # didesnis šriftas
    win.apply_theme("compact")
    assert settings().gtk_xft_dpi == int(dpi * 0.85)
    win.apply_theme("light")
    assert (settings().gtk_theme_name, settings().gtk_xft_dpi) == base
    assert themes.get("nėra-tokios").name == "light"


def test_o2_text_speaker_colors_follow_theme(win):
    from diktatura.ui import themes
    tp = win.text
    rgba = lambda tag: tag.props.foreground_rgba.to_string()                # noqa: E731
    win.apply_theme("dark")
    first = rgba(tp.spk_tags["Ona"])
    from diktatura.ui.gtk import Gdk
    want = Gdk.RGBA()
    want.parse(themes.THEMES["dark"].palette[list(tp.spk_tags).index("Ona")])
    assert first == want.to_string()
    win.apply_theme("contrast")
    assert rgba(tp.spk_tags["Ona"]) != first
    assert rgba(tp.t_sep) == "rgb(0,0,0)"                                   # kontraste — juoda


def test_o3_compact_training_layout(win):
    from diktatura.ui import gtk
    tr = win.training
    assert tr.intro.get_visible() and tr.lsw.get_size_request()[0] == 260
    win.apply_theme("compact")
    gtk.pump(0.02)
    assert not tr.intro.get_visible() and tr.lsw.get_size_request()[0] == 170
    win.show_all()                                                           # show_all įžangos neatidengia
    assert not tr.intro.get_visible()
    win.apply_theme("light")
    assert tr.intro.get_visible()


def test_o4_settings_save_applies_theme(env, win):
    from diktatura import config
    st = win.settings
    st.set_value("THEME", "dark")
    assert st.save()
    assert win.theme.name == "dark" and config.load()["THEME"] == "dark" and "tema: Tamsi" in st.msg.get_text()
    st.set_value("THEME", "light")
    st.reset_to_defaults()
    assert win.theme.name == "light"


def test_o5_new_window_uses_saved_theme(env, fake_systemd):
    from diktatura import config
    from diktatura.ui import gtk, themes
    from diktatura.ui.app import MainWindow
    config.save({"THEME": "compact"})
    w = MainWindow(auto_refresh=False)
    try:
        assert w.theme.name == "compact" and not w.training.intro.get_visible()
    finally:
        w.destroy()
        themes.apply("light")
        gtk.pump(0.02)


def test_o6_training_tabs_full_height_lists(win):
    tr = win.training
    assert tr.tab_title("pending").startswith("🔎 Laukia vardo (") and tr.tab_title("known").startswith("👥 Registruoti")
    tr.tabs.set_visible_child_name("known")
    assert tr.tabs.get_visible_child() is tr.known_page
    assert tr.tabs.child_get_property(tr.known_page, "name") == "known"


def test_o7_wrapbox_wraps_like_text_and_destroys_without_python_ref(env):
    """Mygtukų juosta: plačiai — viena eilutė, siaurai — kelios; mažiausias plotis = plačiausias mygtukas.
    Be Python nuorodos (tik GTK laiko) — naikinimas neužstringa (PyGObject spąstai, buvo amžinas ciklas)."""
    import gc
    from diktatura.ui import gtk
    from diktatura.ui.gtk import Gtk, WrapBox, button, flow
    wb = flow(*[button(f"Mygtukas {i}") for i in range(5)])
    wb.show_all()                                           # matomumas — į išdėstymą įeina tik matomi
    mn, nat = wb.get_preferred_width()
    assert mn == max(c.get_preferred_width()[0] for c in wb.get_children()) and nat > 4 * mn
    assert len(wb.lines(nat)) == 1 and len(wb.lines(mn)) == 5
    assert wb.get_preferred_height_for_width(mn)[0] > wb.get_preferred_height_for_width(nat)[0]
    w = Gtk.Window()
    box = Gtk.Box()
    box.add(flow(button("a"), button("b")))                # Python nuorodos į WrapBox nebėra
    gc.collect()
    w.add(box)
    w.show_all()
    gtk.pump(0.05)
    w.destroy()
    gtk.pump(0.05)
    assert not any(isinstance(x, WrapBox) and x.get_parent() is box for x in list(WrapBox._live))
