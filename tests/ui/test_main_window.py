"""I1–I4, I6: pagrindinis langas, Tekstas, Nustatymai, status bar ikonos logika."""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

import pytest

from testenv import REPO


@pytest.fixture
def gtk():
    from diktatura.ui import gtk as g
    return g


def write(env, name, text):
    f = env.recordings / name
    f.write_text(text, encoding="utf-8")
    return f


def stamp(days_ago=0, hhmmss="120000"):
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d") + "_" + hhmmss


@pytest.fixture
def win(env, fake_systemd, gtk):
    from diktatura.ui.app import MainWindow
    w = MainWindow(auto_refresh=False)
    w.show_all()
    gtk.pump(0.05)
    yield w
    w.destroy()
    gtk.pump(0.02)


# ── I1: langas ir navigacija ──

def test_i1_main_window_three_pages_and_back(win, gtk):
    assert set(win.pages) == {"text", "training", "settings"}
    assert win.current == "text" and not win.btn_back.get_sensitive()
    win.show_page("settings")
    gtk.pump(0.05)
    assert win.current == "settings" and win.btn_back.get_sensitive()
    win.show_page("training")
    win.go_back()
    assert win.current == "settings"
    win.go_back()
    assert win.current == "text" and not win.btn_back.get_sensitive()


# ── I2–I3: Tekstas ──

def test_i2_text_sessions_speakers_and_retention(env, win, gtk):
    write(env, f"vox_{stamp(0, '090000')}.named.txt", "[0:00:01] Tu: labas rytas\n[0:00:03] Ona: sveikas\n")
    write(env, f"slack_{stamp(0, '100000')}.named.txt", "[0:00:02] Jonas: pradedam susitikimą\n")
    write(env, f"vox_{stamp(5, '090000')}.named.txt", "[0:00:01] Tu: senas tekstas\n")      # už 2 d. ribos
    write(env, f"vox_{stamp(0, '110000')}.dialog.txt", "[0:00:01] Tu: grynas dialog nerodomas\n")
    win.text.refresh()
    t = win.text.text()
    assert "· VOX ·" in t and "· SLACK ·" in t
    assert t.index("labas rytas") < t.index("pradedam")              # sena -> nauja
    assert "senas tekstas" not in t and "nerodomas" not in t
    assert set(win.text.spk_tags) == {"Tu", "Ona", "Jonas"}           # kiekvienas kalbėtojas — sava spalva
    colors = {tag.props.foreground_rgba.to_string() for tag in win.text.spk_tags.values()}
    assert len(colors) == 3
    env.write_conf(RETENTION_DAYS=7)                                  # nustatymas taikomas gyvai
    win.text.refresh()
    assert "senas tekstas" in win.text.text()
    env.write_conf(RETENTION_DAYS=1)
    win.text.refresh()
    assert "senas tekstas" not in win.text.text()


def test_i2_tail_append_and_partial_line(env, win, gtk):
    f = write(env, f"vox_{stamp()}.named.txt", "[0:00:01] Tu: pirma\n")
    win.text.refresh()
    with open(f, "a", encoding="utf-8") as fh:
        fh.write("[0:00:05] Ona: antra\n[0:00:09] Tu: nebaig")
    win.text.refresh()
    t = win.text.text()
    assert "antra" in t and "nebaig" not in t                         # pusiau įrašyta eilutė — dar ne
    with open(f, "a", encoding="utf-8") as fh:
        fh.write("ta\n")
    win.text.refresh()
    assert "Tu: nebaigta" in win.text.text()
    assert win.text.text().count("pirma") == 1


def test_i2_rewritten_file_rerenders_with_new_name(env, win, gtk):
    from diktatura.speakers import store
    write(env, f"vox_{stamp()}.named.txt", "[0:00:01] Kolega?nez3: labas\n[0:00:02] Tu: sveiki\n")
    win.text.refresh()
    assert "Kolega?nez3:" in win.text.text()
    store.rename_in_transcripts("Kolega?nez3", "Rūta")
    win.text.refresh()
    t = win.text.text()
    assert "Rūta: labas" in t and "nez3" not in t and t.count("sveiki") == 1


def test_i3_search_highlight_and_cycle(env, win, gtk):
    write(env, f"vox_{stamp()}.named.txt", "[0:00:01] Tu: Diegimas rytoj\n[0:00:02] Ona: diegimas po pietų\n"
                                           "[0:00:03] Tu: ok diegimas\n")
    win.text.refresh()
    win.text.search.set_text("di")
    win.text.highlight_all()
    assert win.text.matches == [] and win.text.lbl_match.get_text() == ""      # < 3 simbolių
    win.text.search.set_text("DIEG")
    win.text.highlight_all()
    assert len(win.text.matches) == 3 and win.text.lbl_match.get_text() == "3 rasta"
    for want in ("1/3", "2/3", "3/3", "1/3"):
        win.text.goto_match(1)
        assert win.text.lbl_match.get_text() == want
    win.text.goto_match(-1)
    assert win.text.lbl_match.get_text() == "3/3"


def test_line_at_iter_maps_click_to_transcript_line(env, win, gtk):
    write(env, f"vox_{stamp()}.named.txt", "[0:00:01] Tu: pirma\n[0:01:02] Ona: antra eilutė\n")
    win.text.refresh()
    buf = win.text.buf
    s, e = buf.get_bounds()
    off = buf.get_text(s, e, True).index("antra eilutė") + 3
    ln = win.text.line_at_iter(buf.get_iter_at_offset(off))
    assert ln and ln.speaker == "Ona" and ln.ts == "0:01:02" and ln.idx == 1


# ── I4: Nustatymai ──

def test_i4_settings_fields_match_config_and_save(env, win, gtk):
    from diktatura import config
    st = win.settings
    cur = config.load()
    assert set(st.widgets) == set(config.BY_KEY)
    assert st.get_value("VOX_SILENCE_SEC") == config.to_text("VOX_SILENCE_SEC", cur["VOX_SILENCE_SEC"])
    assert st.get_value("MODE") == "immediate" and st.get_value("ARCHIVE_MP3") == "1"
    st.set_value("VOX_SILENCE_SEC", 3)
    st.set_value("ARCHIVE_MP3", False)
    st.set_value("MODEL", "medium")
    assert st.dirty() and "neišsaugotų" in st.msg.get_text()
    assert st.save()
    new = config.load()
    assert new["VOX_SILENCE_SEC"] == 3 and new["ARCHIVE_MP3"] is False and new["MODEL"] == "medium"
    assert not st.dirty()


def test_i4_validation_error_shown_file_unchanged(env, win, gtk):
    from diktatura import config
    config.ensure()
    before = env.conf_file.read_text()
    st = win.settings
    st.set_value("VOX_CLOSE_MARGIN", 20)                              # ≥ pradžios atsargos (15)
    assert not st.save()
    assert st.errors["VOX_CLOSE_MARGIN"].get_text() and st.errors["VOX_CLOSE_MARGIN"].get_visible()
    assert "Neišsaugota" in st.msg.get_text()
    assert env.conf_file.read_text() == before


def test_i4_reset_restores_defaults(env, win, gtk):
    from diktatura import config
    config.save({"VOX_SILENCE_SEC": "9", "MODE": "deferred"})
    win.settings.load()
    assert win.settings.get_value("VOX_SILENCE_SEC") == "9"
    win.settings.reset_to_defaults()
    assert win.settings.get_value("VOX_SILENCE_SEC") == "5" and config.load()["MODE"] == "immediate"
    assert env.conf_file.read_bytes() == (REPO / "config" / "diktatura.conf.default").read_bytes()


def test_i4_mode_switch_and_deferred_enables_timer(env, win, gtk, fake_systemd):
    from diktatura import services
    st = win.settings
    st.mode_btns["slack"].set_active(True)
    st.set_value("MODE", "deferred")
    assert st.save()
    assert services.recorder_mode() == "slack" and services.is_enabled(services.TIMER)
    assert "Slack" in st.msg.get_text() and "01:30" in st.msg.get_text()
    st.mode_btns["off"].set_active(True)
    assert st.save() and services.recorder_mode() == "off"


def test_i4_mode_failure_reported(env, win, gtk, fake_systemd):
    (fake_systemd.state / "diktatura-vox.service.broken").touch()
    win.settings.mode_btns["vox"].set_active(True)
    assert not win.settings.save()
    assert "install-units" in win.settings.msg.get_text()


# ── I6: status bar ikona ──

class FakeIndicator:
    def __init__(self):
        self.icons, self.menu, self.secondary, self.title = [], None, None, ""

    def set_icon_full(self, name, desc):
        self.icons.append(name)

    def set_menu(self, m):
        self.menu = m

    def set_secondary_activate_target(self, it):
        self.secondary = it

    def set_title(self, t):
        self.title = t


def test_i6_tray_states_menu_and_pulse(env, gtk):
    from diktatura.ui import tray
    assert tray.compute_state(True, True) == "rec" and tray.compute_state(False, True) == "proc"
    assert tray.compute_state(False, False) == "idle"
    st = {"state": "idle", "pending": 0}
    opened = []
    ind = FakeIndicator()
    t = tray.Tray(indicator=ind, opener=opened.append, state_fn=lambda: st["state"], mode_fn=lambda: "vox",
                  pending_fn=lambda: st["pending"], timers=False)
    labels = [it.get_label() for it in ind.menu.get_children() if hasattr(it, "get_label") and it.get_label()]
    assert labels[0] == "⚙ Nustatymai"                                # Nustatymai — meniu viršuje
    assert ind.secondary is t.it_settings                              # vidurinis klik -> Nustatymai
    assert not t.it_training.get_visible()
    for _ in range(4):
        t.pulse()
    assert ind.icons == ["diktatura-idle"]                             # be laukiančių — nepulsuoja
    st.update(state="rec", pending=2)
    t.update()
    assert t.it_training.get_visible() and t.it_training.get_label() == "🎓 Apmokymai paruošti (2)"
    for _ in range(4):
        t.pulse()
    assert ind.icons[-4:] == ["diktatura-rec-dim", "diktatura-rec", "diktatura-rec-dim", "diktatura-rec"]
    st.update(pending=0)
    t.update()
    t.pulse()
    assert ind.icons[-1] == "diktatura-rec" and not t.it_training.get_visible()
    t.it_settings.activate()
    t.it_training.activate()
    assert opened == ["settings", "training"]
    assert "Diktatūra — 🔴 Įrašoma" == ind.title


def test_dim_icons_exist_for_every_state():
    for st in ("idle", "rec", "proc"):
        assert (REPO / "icons" / f"diktatura-{st}.png").exists()
        assert (REPO / "icons" / f"diktatura-{st}-dim.png").exists()


# ── programa (vienas egzempliorius, --page, --shot) ──

def test_app_cli_single_instance_page_switch_and_shot(env, fake_systemd, tmp_path):
    app_env = {**os.environ, "DIKTATURA_APP_ID": f"lt.diktatura.Test{os.getpid()}"}
    py = "/usr/bin/python3"
    first = subprocess.Popen([py, "-m", "diktatura.ui.app"], cwd=REPO, env=app_env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(2.0)
        assert first.poll() is None, first.stdout.read()
        shot = tmp_path / "s.png"
        second = subprocess.run([py, "-m", "diktatura.ui.app", "--page", "settings", "--shot", str(shot)],
                                cwd=REPO, env=app_env, capture_output=True, text=True, timeout=20)
        assert second.returncode == 0, second.stderr
        assert first.wait(timeout=15) == 0                             # pirmas egzempliorius nufotografavo ir išėjo
        assert shot.exists() and shot.stat().st_size > 1000
    finally:
        if first.poll() is None:
            first.kill()


def test_i4_mouse_wheel_over_field_scrolls_page_not_value(env, win, gtk):
    from diktatura.ui.gtk import Gdk
    st = win.settings
    win.show_page("settings")
    gtk.pump(0.1)
    spin = st.widgets["VOX_SILENCE_SEC"]
    before_val, adj = spin.get_value(), st.sw.get_vadjustment()
    adj.set_value(0)
    ev = Gdk.Event.new(Gdk.EventType.SCROLL)
    ev.scroll.direction = Gdk.ScrollDirection.DOWN
    ev.scroll.window = spin.get_window()
    assert st._scroll_page(spin, ev) is True
    assert spin.get_value() == before_val and adj.get_value() > 0


def test_i4_asr_server_toggle_controls_service(env, win, gtk, fake_systemd):
    from diktatura import services
    st = win.settings
    st.set_value("ASR_SERVER", True)
    assert st.save() and services.is_active(services.ASR) and "ASR serveris įjungtas" in st.msg.get_text()
    st.set_value("ASR_SERVER", False)
    assert st.save() and not services.is_active(services.ASR)
    st.set_value("THREADS", 4)                                           # kitas nustatymas — serverio neliečia
    calls = len(fake_systemd.calls())
    assert st.save() and not [c for c in fake_systemd.calls()[calls:] if "diktatura-asr" in c]
