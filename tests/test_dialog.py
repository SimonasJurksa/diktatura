"""F. De-dup (Tu vs kolegos) ir sesijų / transkripcijos eilučių parsing (grynos funkcijos)."""
from datetime import date, datetime

from diktatura import sessions
from diktatura.asr import dialog


def test_f1_leaked_me_line_removed():
    others = [(10.0, 14.0, "Jonas", "rytoj diegsime naują versiją į serverį")]
    me = [(10.5, 13.5, "rytoj diegsime naują versiją serverį")]       # mikrofonas pagavo Jono garsą
    rows, dropped = dialog.dedup(me, others)
    assert dropped == 1 and [r[2] for r in rows] == ["Jonas"]


def test_f2_real_me_line_kept():
    others = [(10.0, 14.0, "Jonas", "rytoj diegsime naują versiją į serverį")]
    me = [(15.0, 18.0, "gerai, aš paruošiu migracijas ir testus")]
    rows, dropped = dialog.dedup(me, others)
    assert dropped == 0 and [r[2] for r in rows] == ["Jonas", "Tu"]


def test_f2_same_words_far_in_time_kept():
    others = [(10.0, 12.0, "Jonas", "diegsime naują versiją")]
    me = [(60.0, 62.0, "diegsime naują versiją")]                     # tie patys žodžiai, bet kitu metu
    assert dialog.dedup(me, others)[1] == 0


def test_f3_short_reaction_kept_even_if_overlapping():
    others = [(10.0, 14.0, "Jonas", "taip gerai")]
    me = [(11.0, 12.0, "taip gerai")]                                 # < 3 žodžiai — reakcija, ne nutekėjimas
    rows, dropped = dialog.dedup(me, others)
    assert dropped == 0 and len(rows) == 2


def test_rows_sorted_and_formatted():
    rows, _ = dialog.dedup([(5.0, 6.0, "labas")], [(1.0, 2.0, "Ona", "sveiki"), (3661, 3662, "Kolega?nez2", "ate")])
    assert dialog.format_rows(rows) == "[0:00:01] Ona: sveiki\n[0:00:05] Tu: labas\n[1:01:01] Kolega?nez2: ate\n"
    assert dialog.format_rows([]) == ""


def test_session_name_parsing():
    assert sessions.parse_name("vox_20261008_143000.named.txt") == ("vox", datetime(2026, 10, 8, 14, 30))
    assert sessions.parse_name("slack_20261008_010203.mp3")[0] == "slack"
    assert sessions.parse_name("rec_20261399_000000.wav") is None          # neteisinga data
    assert sessions.parse_name("pastabos.txt") is None
    assert sessions.base_name("vox_x.named.txt") == "vox_x"
    assert sessions.base_name("vox_x.clean.dialog.txt") == "vox_x"
    assert sessions.base_name("vox_x.mp3") == "vox_x"


def test_display_text_filter():
    ok = ["a.named.txt", "a.txt", "a.clean.dialog.txt"]
    bad = ["a.dialog.txt", "a.srt", "a.wav"]
    assert all(sessions.is_display_text(n) for n in ok)
    assert not any(sessions.is_display_text(n) for n in bad)


def test_text_files_sorted_by_recording_time_and_since(tmp_path):
    for n in ("vox_20261008_120000.named.txt", "slack_20261007_090000.named.txt",
              "vox_20261008_080000.txt", "vox_20261008_080000.dialog.txt", "vox_20261008_080000.srt"):
        (tmp_path / n).write_text("x")
    names = [f.name for f in sessions.text_files(tmp_path)]
    assert names == ["slack_20261007_090000.named.txt", "vox_20261008_080000.txt", "vox_20261008_120000.named.txt"]
    assert len(sessions.text_files(tmp_path, since=date(2026, 10, 8))) == 2


def test_audio_for_prefers_wav_then_mp3(tmp_path):
    t = tmp_path / "vox_20261008_120000.named.txt"
    t.write_text("x")
    assert sessions.audio_for(t) is None
    (tmp_path / "vox_20261008_120000.mp3").write_bytes(b"")
    assert sessions.audio_for(t).suffix == ".mp3"
    (tmp_path / "vox_20261008_120000.wav").write_bytes(b"")
    assert sessions.audio_for(t).suffix == ".wav"


def test_line_parsing():
    assert sessions.parse_line("[0:01:02] Kolega?nez3: labas: rytas") == ("0:01:02", "Kolega?nez3", "labas: rytas")
    assert sessions.parse_line("be formato") is None
    assert sessions.ts_seconds("1:02:03") == 3723
