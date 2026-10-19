"""HM4, HM7: ikonos gryna logika ir Teksto lango failų skaitymas (reikia gi -> tests/ui)."""
import os
import time


# ── HM4: ikona ──

def test_hm4_tray_pure(env):
    from diktatura import progress
    from diktatura.ui import tray
    assert tray.compute_state(True, True) == "rec" and tray.compute_state(False, True) == "proc"
    assert tray.compute_state(False, False) == "idle"
    assert tray.icon_name("rec", 0, 1) == "diktatura-rec" and tray.icon_name("idle", 2, 1) == "diktatura-idle-dim"
    assert tray.icon_name("idle", 2, 2) == "diktatura-idle"
    assert tray.training_label(3) == "🎓 Apmokymai paruošti (3)"
    assert tray.progress_label(progress.Snapshot(now=0)) == ""
    assert tray.current_state() == "idle"
    (env.run / "recording").write_text("vox /x.wav")
    assert tray.current_state(progress.Snapshot(now=0)) == "rec"
    for lb in tray.LABELS.values():
        assert lb[0] in "🔴🟡⚪"



# ── HM7: teksto lango failų skaitymas (tail) ──

def test_hm7_text_page_read_more_partial_lines(env):
    from diktatura.ui import text_page as tp
    f = env.recordings / "vox_20261012_100000.named.txt"
    f.write_text("[0:00:01] Tu: pirma\n[0:00:02] Ona: pusė", encoding="utf-8")
    s = tp.load_session(f)
    assert [ln.text for ln in s.lines] == ["pirma"]                              # pusinė eilutė — dar ne
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(" eilutė\n[0:00:03] Tu: trečia\n")
    new = tp.read_more(s, f.stat())
    assert [ln.text for ln in new] == ["pusė eilutė", "trečia"] and s.lines[1].idx == 1
    g = env.recordings / "rec_20261012_100100.txt"
    g.write_text("be galo", encoding="utf-8")
    old = time.time() - 10
    os.utime(g, (old, old))
    s2 = tp.load_session(g)
    assert [ln.text for ln in s2.lines] == ["be galo"]                           # seniai nekeistas — imama viskas
    assert tp.TextPage.srt_time(3725.5) == "01:02:05,500" and tp.fmt_dur(0) == "0:00"
    assert tp.retention_days() == 2
    assert tp.peaks_cmd("/a.wav", "/a.peaks")[-3:] == ["/a.wav", "--out", "/a.peaks"] and tp.peaks_cmd("a", "b")[0] == "nice"


