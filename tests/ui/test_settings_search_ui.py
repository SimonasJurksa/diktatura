"""N1–N4: 🔍 Nustatymų paieška — filtruoja grupes ir nustatymus, paryškina rastą tekstą (be lietuviškų raidžių
skirtumo), grupės pavadinimas rodo visą grupę, Ctrl+F / Esc."""
import pytest


@pytest.fixture
def gtk():
    from diktatura.ui import gtk as g
    return g


@pytest.fixture
def win(env, fake_systemd, gtk):
    from diktatura.ui.app import MainWindow
    w = MainWindow(auto_refresh=False)
    w.show_all()
    w.show_page("settings")
    gtk.pump(0.05)
    yield w
    w.destroy()
    gtk.pump(0.02)


def visible_frames(st):
    return [t.get_text() for fr, t, _ in st.frames if fr.get_visible()]


def visible_keys(st):
    return [it["key"] for fr, _t, items in st.frames if fr.get_visible() for it in items
            if it["key"] and it["widgets"][0].get_visible()]


def search(st, gtk, q):
    st.search.set_text(q)
    st.apply_search()                         # „search-changed" vėluoja ~150 ms — tiesiogiai
    gtk.pump(0.02)


def test_n1_filter_and_highlight_without_diacritics(win, gtk):
    from diktatura import config
    st = win.settings
    search(st, gtk, "zodzi")
    assert visible_frames(st) == ["Tekstas", "Transkripcija", "VAD (kalbos filtras)"]
    assert visible_keys(st) == ["FILLER_WORDS", "ECHO_CANCEL", "VAD_PAD_SEC"]
    name = next(lb for lb in st._labels(st.frames[2][2][1]["widgets"][0]))    # „Papildomi užpildų žodžiai"
    assert '<span background="#fde047" foreground="#000000">žodži</span>ai' in name.get_label()
    assert st.lbl_found.get_text() == "rasta: 3 · grupių: 3" and not st.intro.get_visible()
    st.search.set_text("")
    st.apply_search()
    assert len(visible_frames(st)) == len(st.frames) and st.intro.get_visible()
    assert name.get_label() == config.BY_KEY["FILLER_WORDS"].label                 # paryškinimas nuimtas
    assert st.lbl_found.get_text() == ""


def test_n2_group_title_key_and_radio_matches(win, gtk):
    st = win.settings
    search(st, gtk, "archyv")
    assert "Archyvas" in visible_frames(st)
    arch = next(items for fr, t, items in st.frames if t.get_text() == "Archyvas")
    assert all(it["widgets"][0].get_visible() for it in arch)                      # visa grupė
    assert st.cleanup_info.get_visible()
    search(st, gtk, "VOX_GATE_DB")
    assert visible_keys(st) == ["VOX_GATE_DB"]                                     # pagal raktą
    search(st, gtk, "neįrašinėti")
    assert visible_frames(st) == ["Įrašymo režimas"] and visible_keys(st) == ["off"]
    search(st, gtk, "qqqq")
    assert visible_frames(st) == [] and st.lbl_found.get_text().startswith("nieko nerasta")


def test_n3_dynamic_sources_rows_are_searchable(win, gtk, tmp_path):
    st = win.settings
    d = tmp_path / "Laikrodis"
    d.mkdir()
    assert st.add_source(str(d), "Laikrodis")
    search(st, gtk, "laikrod")
    assert visible_frames(st) == ["Sekami aplankai"]


def test_n4_ctrl_f_esc_and_save_still_works(win, gtk):
    from diktatura import config
    from diktatura.ui.gtk import Gdk
    st = win.settings
    ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    ev.keyval, ev.state = Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK
    assert win._on_key(win, ev) and st.search.is_focus()
    search(st, gtk, "tylos")
    st.set_value("VOX_SILENCE_SEC", 7)
    assert st.save() and config.load()["VOX_SILENCE_SEC"] == 7                    # paslėpti laukai irgi išsaugomi
    st.search.emit("stop-search")                                                  # Esc
    st.apply_search()
    assert st.search.get_text() == "" and len(visible_frames(st)) == len(st.frames)
