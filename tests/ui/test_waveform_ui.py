"""W6–W12: 🌊 bangos valdiklis (ui.waveform_view) ir banga Teksto skiltyje."""
import time
from datetime import datetime, timedelta

import pytest

import audio
from testenv import HELPERS


@pytest.fixture
def gtk():
    from diktatura.ui import gtk as g
    return g


def day(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y%m%d")


def peaks(sec=60, loud=()):
    """Sintetinės stereo smailės: (s, e, kanalas) — garsu, kitur — tylu."""
    from diktatura import waveform
    data = bytearray()
    for i in range(int(sec * waveform.RATE)):
        t = i / waveform.RATE
        for ch in (0, 1):
            data.append(220 if any(s <= t < e and c == ch for s, e, c in loud) else 40)
    return waveform.Peaks(waveform.RATE, 2, bytes(data))


@pytest.fixture
def view(gtk):
    from diktatura.ui.waveform_view import WaveformView
    seeks = []
    v = WaveformView(on_seek=seeks.append)
    v.seeks = seeks
    v.set_peaks(peaks(60, [(0, 10, 0), (20, 40, 1)]))
    v.set_lines([(1, "Tu", "#00aa00", "labas"), (21, "Ona", "#aa0000", "sveikas, kaip sekasi"),
                 (31, "Tu", "#00aa00", "gerai")], me="Tu")
    v.set_colors("#00aa00", "#888888")
    return v


# ── W6: gryna logika ──

def test_w6_time_x_mapping_zoom_and_pan(view):
    from diktatura.ui import waveform_view as wv
    assert view.duration == 60 and view.view == (0, 60)
    assert view.x_to_sec(300, 600) == 30 and view.sec_to_x(15, 600) == 150 and view.x_to_sec(-5, 600) == 0
    view.get_allocated_width = lambda: 600
    view.zoom(0.5, at_x=150)                                   # artinti ties 15 s
    assert view.view == pytest.approx((7.5, 37.5)) and view.x_to_sec(150) == pytest.approx(15)
    for _ in range(20):
        view.zoom(0.5, at_x=300)
    assert view.view[1] - view.view[0] == pytest.approx(wv.MIN_VIEW)
    view.pan(100)                                              # už galo — prispaudžiama
    assert view.view[1] == pytest.approx(60)
    view.reset_view()
    assert view.view == (0, 60)


def test_w6_lines_colors_and_tooltip(view):
    assert view.line_at(0.5) is None and view.line_at(25)[1] == "Ona" and view.line_at(31)[1] == "Tu"
    assert view.segment_color(25, 0, 2) == "#00aa00"           # „Tu" juosta — visada tavo spalva
    assert view.segment_color(25, 1, 2) == "#aa0000"           # kolegų juosta — tuo metu kalbančio Onos
    assert view.segment_color(33, 1, 2) == "#888888"           # tavo eilutė kolegų juostos nedažo
    assert view.segment_color(25, 0, 1) == "#aa0000"           # mono — kalbančiojo
    assert view.segment_color(55, 1, 2) == "#888888"           # > 30 s po eilutės — nebe jos
    view.get_allocated_width = lambda: 600
    assert view.tooltip_text(250).startswith("0:25 · Ona: sveikas, kaip sekasi")


def test_w6_position_follows_when_zoomed(view):
    view.get_allocated_width = lambda: 600
    view.set_view(0, 20)
    view.set_position(45)
    assert view.view[0] <= 45 <= view.view[1] and view.position == 45


# ── W7: piešimas (cairo) ──

def test_w7_draw_lanes_colors_playhead_and_processed(view, gtk):
    import cairo
    win = gtk.Gtk.OffscreenWindow()
    win.add(view)
    win.set_size_request(600, 84)
    win.show_all()
    gtk.pump(0.05)
    view.set_position(30)

    def draw():
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 600, 84)
        view._on_draw(view, cairo.Context(surf))
        data = surf.get_data()
        px = lambda x, y: tuple(data[(y * surf.get_stride()) + x * 4 + i] for i in (2, 1, 0))   # noqa: E731
        return px
    px = draw()
    green, red = px(50, 23), px(300 * 25 // 30, 58)            # L kalba 0–10 s viršuje; Onos 20–40 s apačioje
    assert green[1] > 120 and green[0] < 80 and red[0] > 120 and red[1] < 80
    assert px(300, 10)[0] > 180                                # grojimo žymeklis ties 30 s
    view.set_processed([60, 22])                                # kolegų kanalas apdorotas iki 22 s
    view.set_position(None)
    px = draw()
    assert px(450, 58)[0] < red[0] - 40                        # 45 s — dar neapdorota: išblukusi
    view.set_peaks(None)
    view.set_message("skaičiuojama…")
    draw()                                                     # be smailių — tik tekstas, nelūžta
    win.destroy()


def test_w7_click_seeks_and_double_click_resets(view, gtk):
    from types import SimpleNamespace as NS

    from diktatura.ui.gtk import Gdk
    view.get_allocated_width = lambda: 600
    assert view._on_press(view, NS(button=1, x=150.0, type=Gdk.EventType.BUTTON_PRESS)) and view.seeks == [15.0]
    assert not view._on_press(view, NS(button=3, x=150.0, type=Gdk.EventType.BUTTON_PRESS))   # dešinys — ne grojimas
    view.set_view(10, 30)
    view._on_press(view, NS(button=1, x=150.0, type=Gdk.EventType._2BUTTON_PRESS))
    assert view.view == (0, 60) and view.seeks == [15.0]
    up = NS(direction=Gdk.ScrollDirection.UP, state=0, x=300.0)
    assert view._on_scroll(view, up) and view.view[1] - view.view[0] == pytest.approx(40)    # ratukas — artina


# ── W8–W12: Teksto skiltis ──

@pytest.fixture
def demo(env):
    from diktatura import waveform
    r = env.recordings
    new, old = f"slack_{day(0)}_100000", f"vox_{day(1)}_090000"
    (r / f"{new}.named.txt").write_text("[0:00:01] Ona: rytoj diegimas\n[0:00:21] Tu: gerai\n[0:00:31] Ona: ačiū\n",
                                        encoding="utf-8")
    waveform.write(r / f"{new}.peaks", peaks(60, [(1, 20, 1), (21, 30, 0), (31, 40, 1)]))
    (r / f"{old}.named.txt").write_text("[0:00:02] Tu: vakarykštė pastaba\n[0:00:09] Tu: dar viena\n",
                                        encoding="utf-8")
    audio.write_wav(r / f"{old}.wav", audio.speech(12), audio.silence(12))
    return new, old


@pytest.fixture
def win(env, demo, fake_systemd, monkeypatch, tmp_path, gtk):
    from diktatura.ui.app import MainWindow
    monkeypatch.setenv("DIKTATURA_SEEK_PLAYER", f"{HELPERS / 'fakebin' / 'player-fake'} {{start}} {{file}}")
    monkeypatch.setenv("FAKE_PLAYER_LOG", str(tmp_path / "played"))
    env.write_conf(RETENTION_DAYS=3)
    w = MainWindow(auto_refresh=False)
    w.show_all()
    gtk.pump(0.05)
    yield w
    w.text.stop_playback()
    w.destroy()
    gtk.pump(0.02)


def wait(gtk, cond, sec=15):
    end = time.monotonic() + sec
    while time.monotonic() < end and not cond():
        gtk.pump(0.05)
    return cond()


def test_w8_newest_session_wave_with_text_colors(win, demo):
    tp = win.text
    new, _ = demo
    assert tp.btn_wave.get_active() and tp.wave_box.get_visible()
    assert tp.wave_session.path.name == f"{new}.named.txt" and not tp.wave_pinned
    assert new in tp.lbl_wave.get_text() and "naujausia" in tp.lbl_wave.get_text() and "1:00" in tp.lbl_wave.get_text()
    assert tp.wave.peaks.frames == 600 and not tp.btn_wave_latest.get_visible()
    assert [(s, spk, c) for s, spk, c, _ in tp.wave.lines] == [
        (1, "Ona", tp.spk_colors["Ona"]), (21, "Tu", tp.spk_colors["Tu"]), (31, "Ona", tp.spk_colors["Ona"])]
    assert tp.wave.me_color == tp.spk_colors["Tu"]


def test_w9_click_line_selects_session_and_band(win, demo, gtk):
    tp = win.text
    _, old = demo
    ln = next(x for x in tp.visible_lines() if x.text == "dar viena")
    tp.buf.place_cursor(tp.buf.get_iter_at_mark(tp.line_mark[id(ln)]))
    tp._wave_from_cursor()
    assert tp.wave_session is ln.session and tp.wave_pinned and tp.wave_line is ln
    assert tp.wave.band == (9, 14) and tp.btn_wave_latest.get_visible()     # paskutinė eilutė — +5 s
    assert "naujausia" not in tp.lbl_wave.get_text()
    assert wait(gtk, lambda: tp.wave.peaks is not None)                     # smailių nebuvo — suskaičiuotos fone
    assert tp.wave.peaks.frames == 120 and (tp.rec_dir() / f"{old}.peaks").exists()
    tp.wave_follow_latest()
    assert not tp.wave_pinned and tp.wave_session.path.name.startswith("slack_") and tp.wave.band is None
    tp.select_wave(ln.session, ln)
    tp.cb_auto.set_active(False)
    tp.cb_auto.set_active(True)                                             # vėl „Sekti naujus" — banga irgi
    assert not tp.wave_pinned


def test_w10_click_wave_plays_from_there(win, demo, tmp_path, gtk, monkeypatch):
    from diktatura import pause
    tp = win.text
    _, old = demo
    ln = next(x for x in tp.visible_lines() if x.text == "vakarykštė pastaba")
    tp.select_wave(ln.session, ln)
    tp._on_wave_seek(9.4)
    time.sleep(0.2)
    start, f = (tmp_path / "played").read_text().split()
    assert float(start) == pytest.approx(9.4) and f.endswith(f"{old}.wav") and pause.active()
    assert tp.wave_line.text == "dar viena" and tp.play_session is ln.session
    monkeypatch.setattr(tp.player, "position", lambda: 10.5)
    tp._play_tick()
    assert tp.wave.position == 10.5 and tp.wave.band == (9, 14)
    tp.stop_playback()
    assert tp.wave.position is None and tp.play_session is None


def test_w11_no_audio_no_peaks_and_broken_audio(win, demo, env, gtk):
    tp = win.text
    r = env.recordings
    (r / f"rec_{day(0)}_120000.txt").write_text("mono be laiko\n", encoding="utf-8")
    tp.refresh()
    assert tp.wave_session.path.name == f"rec_{day(0)}_120000.txt"
    assert tp.wave.peaks is None and "Garso nebėra" in tp.wave.message
    (r / f"rec_{day(0)}_130000.txt").write_text("sugadintas garsas\n", encoding="utf-8")
    (r / f"rec_{day(0)}_130000.wav").write_bytes(b"RIFF" + bytes(100))
    tp.refresh()
    assert wait(gtk, lambda: "nepavyko" in tp.wave.message)


def test_w12_toggle_hides_and_remembers(win, env):
    from diktatura import config
    tp = win.text
    tp.btn_wave.set_active(False)
    assert not tp.wave_box.get_visible() and config.load()["WAVEFORM"] is False
    tp.refresh()
    assert not tp.wave_box.get_visible()
    tp.btn_wave.set_active(True)
    assert tp.wave_box.get_visible() and config.load()["WAVEFORM"] is True
