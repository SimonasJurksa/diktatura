"""PE2: pilnas kelias — Teksto langas rodo VOX -> netikro ASR sesijas su banga, paieška, eksportu."""

def test_pe2_text_window_shows_sessions_wave_and_exports(flow, fake_systemd):
    from diktatura.ui import gtk
    from diktatura.ui.app import MainWindow
    w = MainWindow(auto_refresh=False)
    w.show_all()
    gtk.pump(0.05)
    try:
        tp = w.text
        assert len(tp.order) == 2 and tp.text().count("Ona: gerai") == 2
        assert tp.wave.peaks is not None and tp.wave_box.get_visible()
        assert tp.export_text("srt").count("-->") == 4
        tp.search.set_text("migracij")
        tp.highlight_all()
        assert tp.lbl_match.get_text() == "2 rasta"
        assert tp.stats()["Tu"]["lines"] == 2 and tp.stats()["Ona"]["lines"] == 2
        tp.btn_clean.set_active(True)
        assert "labas rytas, migracija pirmadienį" in tp.text()
    finally:
        w.destroy()
        gtk.pump(0.02)


