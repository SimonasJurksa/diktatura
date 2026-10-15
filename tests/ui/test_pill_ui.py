"""V6–V7: 💊 įrašymo indikatoriaus langelis (ui.pill.PillView) ir ikonos reakcija į spragtelėjimą."""
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def gtk():
    from diktatura.ui import gtk as g
    return g


def test_v6_view_rec_after_hide_and_draw(env, gtk):
    import cairo

    from diktatura.ui import pill
    clicks, closes = [], []
    v = pill.PillView(on_click=lambda: clicks.append(1), on_close=lambda: closes.append(1))
    try:
        levels = [(-20.0, -70.0)] * 40 + [(-70.0, -15.0)] * 40
        v.show_rec("vox", 42.3, levels)
        gtk.pump(0.05)
        assert v.win.get_visible() and v.lbl.get_text() == "🔴 VOX · 0:42" and v.mode == "rec"
        assert v.area.get_visible() and not v.bar.get_visible()
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 150, 30)
        v.area.get_allocated_width = lambda: 150
        v.area.get_allocated_height = lambda: 30
        v._draw(v.area, cairo.Context(surf))
        data, stride = surf.get_data(), surf.get_stride()
        px = lambda x, y, c: data[y * stride + x * 4 + c]         # noqa: E731  (BGRA)
        blue = max(px(x, 7, 0) for x in range(15, 30))             # kairė (senesni gabalai) viršuje — tu kalbėjai
        green = max(px(x, 26, 1) for x in range(120, 140))         # dešinė apačioje — kolegos kalba dabar
        assert blue > 180 and green > 100
        assert max(px(x, 26, 1) for x in range(15, 30)) < 60       # kolegos tada tylėjo (tik pagrindo linija)
        v.show_after("⏳ Transkribuojama 43 %", 0.43)
        assert v.mode == "after" and v.bar.get_visible() and v.bar.get_fraction() == pytest.approx(0.43)
        assert not v.area.get_visible() and v.lbl.get_text() == "⏳ Transkribuojama 43 %"
        v.show_after("🌙 Išsaugota — transkribuos naktį (01:30)", None)
        assert not v.bar.get_visible()
        v.hide()
        assert not v.win.get_visible() and v.mode is None
    finally:
        v.win.destroy()


def test_v7_tray_pill_click_opens_progress_or_text(env, gtk):
    from diktatura import progress
    from diktatura.ui import tray
    from test_main_window import FakeIndicator
    opened = []
    fake = NS(state="rec", view=NS(mode="rec", bar=NS(get_visible=lambda: False)))
    t = tray.Tray(indicator=FakeIndicator(), opener=opened.append, state_fn=lambda: "rec", mode_fn=lambda: "vox",
                  pending_fn=lambda: 0, timers=False, progress_fn=lambda: progress.Snapshot(now=0), pill=fake)
    t.on_pill_click()
    fake.state, fake.view.mode, fake.view.bar = "after", "after", NS(get_visible=lambda: True)
    t.on_pill_click()
    assert opened == ["text", "progress"]
    fake.pill_tick_error = True
    t.pill = NS(tick=lambda: 1 / 0)
    assert t._pill_tick() is True                                   # indikatoriaus klaida — ikona nelūžta
