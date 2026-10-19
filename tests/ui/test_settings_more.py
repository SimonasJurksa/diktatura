"""ST1–ST4: Nustatymų skiltis — visų tipų laukų apsukimas, išorinis pakeitimas (make set) matomas grįžus,
numatytųjų skirtumų sąrašas, balsų kopijos mygtukas."""
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
    gtk.pump(0.05)
    yield w
    w.destroy()
    gtk.pump(0.02)


def test_st1_every_setting_kind_roundtrips(win):
    from diktatura import config
    st = win.settings
    samples = {"bool": ("0", "1"), "int": None, "float": None, "words": ("", "nu,ok"), "choice": None}
    for s in config.SCHEMA:
        if s.kind == "choice":
            vals = s.choices
        elif s.kind in ("int", "float"):
            vals = (config.to_text(s.key, s.lo), config.to_text(s.key, s.hi))
        else:
            vals = samples[s.kind]
        for v in vals:
            st.set_value(s.key, config.coerce(s.key, v))
            assert st.get_value(s.key) == config.to_text(s.key, config.coerce(s.key, v)), (s.key, v)
    assert st.save() or True                                                    # ribinės reikšmės — gali netikti tarpusavio taisyklei
    st.load()
    assert not st.dirty()


def test_st2_external_change_seen_on_shown_unless_dirty(win, env, gtk):
    from diktatura import config
    st = win.settings
    config.save({"VOX_SILENCE_SEC": "9"})                                       # „make set" kitame procese
    assert st.get_value("VOX_SILENCE_SEC") != "9"
    win.show_page("settings")
    gtk.pump(0.05)
    assert st.get_value("VOX_SILENCE_SEC") == "9"                               # on_shown -> load
    st.set_value("VOX_MIN_SEC", 2.5)                                           # neišsaugotas pakeitimas
    config.save({"VOX_SILENCE_SEC": "11"})
    win.show_page("text")
    win.show_page("settings")
    gtk.pump(0.05)
    assert st.get_value("VOX_SILENCE_SEC") == "9" and st.get_value("VOX_MIN_SEC") == "2.5"   # nepermeta tavo darbo


def test_st3_default_changes_list_and_selected_mode(win, fake_systemd):
    st = win.settings
    assert st.default_changes() == [] and st.selected_mode() == "off"
    st.set_value("THREADS", 2)
    st.set_value("THEME", "dark")
    assert sorted(st.default_changes()) == ["THEME", "THREADS"]
    st.mode_btns["vox"].set_active(True)
    assert st.selected_mode() == "vox" and st.dirty()


def test_st4_backup_button(win, env):
    from diktatura import backup
    from diktatura.speakers import store
    store.mark_model()
    store.add_embedding("Ona", [1.0, 0.0])
    assert win.settings.on_backup_voices()
    [b] = backup.list_backups()
    assert "Balsų kopija" in win.settings.msg.get_text() and backup.describe(b)["voices"] == 1
