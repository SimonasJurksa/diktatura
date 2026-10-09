"""M. Duomenų išvalymas „pradėti iš naujo" (diktatura.reset): kas trinama, kas lieka, vykstantys įrašai neliečiami."""
import json

import pytest

from diktatura import reset
from diktatura.speakers import store


@pytest.fixture
def data(env):
    r = env.recordings
    for n in ("vox_20261009_100000.wav", "vox_20261009_100000.named.txt", "vox_20261008_090000.mp3",
              "vox_20261008_090000.named.txt", "rec_20261008_080000.txt", "rec_20261008_080000.srt",
              "slack_20261006_114101.skip", "vox_20261009_120000.wav"):                   # paskutinis — rašomas dabar
        (r / n).write_bytes(b"x" * 10)
    (r / "bench").mkdir()
    (r / "bench" / "a.txt").write_text("x")
    (env.data / "annotations.json").write_text("{}")
    (env.data / "stats_reset.json").write_text("{}")
    (env.data / "backup" / "relabel-1").mkdir(parents=True)
    (env.data / "backup" / "relabel-1" / "vox.named.txt").write_text("x")
    env.pending.mkdir(parents=True, exist_ok=True)
    for pid in ("nez1", "nez2"):
        (env.pending / f"{pid}.wav").write_bytes(b"w")
        (env.pending / f"{pid}.json").write_text(json.dumps({"embedding": [1.0, 0.0], "src": "x"}))
    (env.pending / ".next").write_text("3")
    (env.speakers / "enroll.json").write_text(json.dumps({"Ona": [[1.0, 0.0]], "Jonas": [[0.0, 1.0]]}))
    store.add_owner([0.5, 0.5], "x")
    (env.speakers / "ignored.json").write_text("[]")
    (env.speakers / "assigned.json").write_text(json.dumps({"nez0": "Ona"}))
    store.mark_model()
    (env.speakers / "legacy-senas-20261009_121315").mkdir()
    (env.speakers / "legacy-senas-20261009_121315" / "enroll.json").write_text("{}")
    env.write_conf(THREADS=3)
    (env.run).mkdir(parents=True, exist_ok=True)
    (env.run / "recording").write_text(f"vox {r / 'vox_20261009_120000.wav'}")
    return env


def test_m1_plan_counts_and_keeps_busy(data, monkeypatch):
    monkeypatch.setattr(reset, "running_transcriptions", lambda: [data.recordings / "vox_20261009_100000.wav"])
    p = reset.plan()
    assert p[reset.RECORDINGS].count == 5                     # 9 failų - 3 vykstantys (rašomas + transkribuojamas su tekstu) - bench/
    assert sorted(f.name for f in p["kept"]) == ["vox_20261009_100000.named.txt", "vox_20261009_100000.wav",
                                                 "vox_20261009_120000.wav"]
    assert p[reset.PENDING].count == 2 and p[reset.VOICES].count == 3   # Ona, Jonas + tavo balsas
    assert p[reset.RECORDINGS].size > 0


def test_m2_recordings_only_keeps_names(data, monkeypatch):
    monkeypatch.setattr(reset, "running_transcriptions", lambda: [])
    res = reset.run([reset.RECORDINGS])
    assert res["deleted"] == {reset.RECORDINGS: 7} and not res["errors"]
    assert [f.name for f in data.recordings.iterdir()] == ["vox_20261009_120000.wav"]      # rašomas — paliktas
    assert not (data.data / "annotations.json").exists() and not (data.data / "stats_reset.json").exists()
    assert not (data.data / "backup").exists()
    assert store.counts() == {"Ona": 1, "Jonas": 1} and store.owner_count() == 1          # vardai lieka
    assert len(store.list_pending()) == 2
    assert (data.conf_file.read_text().count("THREADS=3") == 1)                           # nustatymai lieka


def test_m3_pending_and_voices(data, monkeypatch):
    monkeypatch.setattr(reset, "running_transcriptions", lambda: [])
    reset.run([reset.PENDING, reset.VOICES])
    assert not store.list_pending() and (data.pending / ".next").read_text() == "3"      # numeriai nekartojami
    assert store.counts() == {} and store.owner_count() == 0 and store.load_ignored() == []
    assert not list(data.speakers.glob("legacy-*"))
    assert (data.speakers / "assigned.json").exists() and store.model_id() == store.EMB_MODEL
    assert len(list(data.recordings.iterdir())) == 9                                      # įrašai neliesti
    assert (data.data / "models").exists()


def test_m4_unknown_category_and_empty_dirs(env):
    with pytest.raises(ValueError):
        reset.run(["viskas"])
    assert reset.run([reset.RECORDINGS, reset.PENDING, reset.VOICES], busy=set())["errors"] == []


def test_m5_running_transcriptions_parses_process_args(monkeypatch):
    import subprocess

    class R:
        stdout = ("123 python -m diktatura.asr.transcribe_named /d/rec/vox_20261009_100000.wav --model x\n"
                  "124 ffmpeg -y -i /d/rec/vox_20261009_090000.wav -c:a libmp3lame /d/rec/vox_20261009_090000.mp3\n")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R)
    names = sorted(p.name for p in reset.running_transcriptions())
    assert names == ["vox_20261009_090000.mp3", "vox_20261009_090000.wav", "vox_20261009_100000.wav"]


def test_m6_human_size():
    assert reset.human_size(512) == "512 B" and reset.human_size(2048) == "2.0 KB"
    assert reset.human_size(3 * 1024 ** 3) == "3.0 GB"
