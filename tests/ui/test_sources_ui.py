"""T10–T13: sekami aplankai lange — Nustatymų skiltis (➕ / išjungti / ✕) ir atskiri Teksto skirtukai."""
import os
import time

import pytest

import audio


@pytest.fixture
def gtk():
    from diktatura.ui import gtk as g
    return g


@pytest.fixture
def phone(tmp_path):
    d = tmp_path / "Telefonas"
    d.mkdir()
    return d


def rec(path, age=3600):
    audio.write_wav(path, audio.speech(1.0, -20))
    t = time.time() - age
    os.utime(path, (t, t))
    return path


@pytest.fixture
def win(env, fake_systemd, gtk):
    from diktatura.ui.app import MainWindow
    w = MainWindow(auto_refresh=False)
    w.show_all()
    gtk.pump(0.05)
    yield w
    w.destroy()
    gtk.pump(0.02)


def tab_titles(w):
    nb = w.text_tabs.nb
    return [nb.get_tab_label_text(nb.get_nth_page(i)) for i in range(nb.get_n_pages())]


def test_t10_no_sources_no_tab_bar(win):
    assert tab_titles(win) == ["🎙 Pokalbiai"] and not win.text_tabs.nb.get_show_tabs()
    assert win.text is win.text_tabs.main and win.text_tabs.current() is win.text


def test_t11_add_via_settings_creates_tab_and_timer(win, phone, fake_systemd, gtk):
    from diktatura import services, sources
    from diktatura.ui.gtk import Gtk
    st = win.settings
    rec(phone / "Įrašas 1.wav")
    st.choose_folder = lambda: str(phone)
    seen = {}

    def run(dlg):
        if isinstance(dlg, Gtk.Dialog) and not isinstance(dlg, Gtk.MessageDialog):
            entry, checks = None, []
            for c in dlg.get_content_area().get_children():
                if isinstance(c, Gtk.Entry):
                    entry = c
                elif isinstance(c, Gtk.CheckButton):
                    checks.append(c)
            seen["name"], seen["existing"] = entry.get_text(), checks[1].get_label()
            seen["default_on"] = checks[1].get_active()
            entry.set_text("Mano telefonas")
            return Gtk.ResponseType.OK
        return Gtk.ResponseType.CANCEL
    st.run_dialog = run
    assert st.on_add_source()
    assert seen == {"name": "Telefonas", "existing": "Transkribuoti ir jau esančius failus (1)", "default_on": True}
    [src] = sources.load()
    assert src.name == "Mano telefonas" and src.since == 0
    assert services.is_enabled(services.SOURCES_TIMER) and "Sekamas aplankas" in st.msg.get_text()
    assert tab_titles(win) == ["🎙 Pokalbiai", "📁 Mano telefonas"] and win.text_tabs.nb.get_show_tabs()
    assert win.text_tabs.current() is win.text                      # naujas skirtukas neperjungia
    rows = st.src_list.get_children()
    assert len(rows) == 1 and "laukia 1" in rows[0].get_children()[1].get_children()[1].get_text()
    assert not st.add_source(str(phone), "Dar kartą") and "jau sekamas" in st.msg.get_text()


def test_t11_disable_and_remove(win, phone, fake_systemd, gtk):
    from diktatura import services, sources
    from diktatura.ui.gtk import Gtk
    st = win.settings
    assert st.add_source(str(phone), "Laikrodis")
    sw = st.src_list.get_children()[0].get_children()[0]
    sw.set_active(False)
    assert not sources.load()[0].enabled and not services.is_enabled(services.SOURCES_TIMER)
    assert tab_titles(win) == ["🎙 Pokalbiai"]                      # išjungtas ir be tekstų — skirtuko nėra
    sources.load()[0].out_dir.mkdir(parents=True)
    win.reload_sources()
    assert tab_titles(win) == ["🎙 Pokalbiai", "📁 Laikrodis"]       # turi tekstų — lieka matomas
    st.run_dialog = lambda d: Gtk.ResponseType.CANCEL
    assert not st.on_remove_source("laikrodis") and sources.load()
    st.run_dialog = lambda d: Gtk.ResponseType.OK
    assert st.on_remove_source("laikrodis") and sources.load() == [] and tab_titles(win) == ["🎙 Pokalbiai"]
    assert phone.exists()


def test_t12_source_tab_texts_audio_header_and_now(win, env, phone, monkeypatch, gtk):
    from diktatura import annotations, services, sources
    a = rec(phone / "Įrašas 2026-10-14 10.15.00.wav")
    rec(phone / "laukia.wav")
    src = sources.add("Telefonas", phone)
    base = sources.out_base(src, a)
    sources.write_meta(src, a, base)
    sources.with_suffix(base, ".named.txt").write_text("[0:00:01] Tu: labas iš telefono\n[0:00:04] Ona: sveikas\n",
                                                       encoding="utf-8")
    env.write_conf(RETENTION_DAYS=365)                                  # failo vardo data — fiksuota
    win.reload_sources()
    tp = win.text_tabs.tabs["telefonas"]
    win.text_tabs.show_source("telefonas")
    gtk.pump(0.05)
    assert win.text_tabs.current() is tp and "labas iš telefono" in tp.text()
    assert "2026-10-14 10:15:00 · TELEFONAS · Įrašas 2026-10-14 10.15.00.wav" in tp.text()
    assert "labas iš telefono" not in win.text.text()                # pagrindiniame — ne
    assert "laukia 1" in tp.lbl_source.get_text() and tp.btn_src_now.get_sensitive()
    ln = tp.visible_lines()[0]
    from diktatura import sessions
    assert sessions.audio_for(ln.session.path) == a.resolve()
    tp.tag_line(ln, "star")
    assert annotations.match(annotations.load(), "telefonas/" + ln.session.path.name, ln.idx, ln.text)
    calls = []
    monkeypatch.setattr(services, "spawn_detached", lambda cmd, name: calls.append((cmd[-1], name)))
    tp.transcribe_source_now()
    assert calls == [("--sources", "sources")] and "Transkribuojami" in tp.status.get_text()
    assert win.text_tabs.current() is tp
    from diktatura.ui.gtk import Gdk
    ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    ev.keyval, ev.state = Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK
    assert win._on_key(win, ev) and tp.search.is_focus()            # Ctrl+F — matomo skirtuko paieška


def test_t13_window_opens_on_main_tab_with_sources(env, fake_systemd, gtk, phone):
    from diktatura import sources
    from diktatura.ui.app import MainWindow
    sources.add("Telefonas", phone)
    w = MainWindow(auto_refresh=False)
    w.show_all()
    gtk.pump(0.05)
    try:
        assert w.text_tabs.current() is w.text                      # ne „Telefonas" (GTK pirmas matomas puslapis)
    finally:
        w.destroy()
        gtk.pump(0.02)


def test_t13_theme_reaches_source_tabs(win, phone):
    from diktatura import sources
    sources.add("Studija", phone)
    win.reload_sources()
    tp = win.text_tabs.tabs["studija"]
    t = win.apply_theme("dark")
    assert tp.palette == list(t.palette)
