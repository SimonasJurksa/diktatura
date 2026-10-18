"""B10–B13: balsų atsarginė kopija (diktatura.backup): archyvas, sąrašas, atkūrimas, automatinė prieš trynimą."""
import json
import tarfile

import pytest

from diktatura import backup, reset
from diktatura.speakers import store


@pytest.fixture
def voices(env):
    store.mark_model()
    env.pending.mkdir(parents=True, exist_ok=True)
    (env.speakers / "enroll.json").write_text(json.dumps({"Ona": [[1.0, 0.0]], "Jonas": [[0.0, 1.0]]}))
    (env.speakers / "owner.json").write_text(json.dumps([[0.5, 0.5]]))
    (env.pending / "nez1.json").write_text(json.dumps({"embedding": [1.0, 0.0], "src": "vox_x"}))
    (env.pending / "nez1.wav").write_bytes(b"RIFF" + bytes(40))
    (env.pending / ".next").write_text("2")
    return env


def test_b10_create_describe_and_keep_limit(voices, monkeypatch):
    out = backup.create("testas")
    assert out.parent == voices.data / "backups" and out.name.startswith("voices-")
    with tarfile.open(out) as tar:
        names = sorted(tar.getnames())
    assert names == ["backup.json", "speakers/enroll.json", "speakers/model.json", "speakers/owner.json",
                     "speakers/pending/.next", "speakers/pending/nez1.json", "speakers/pending/nez1.wav"]
    d = backup.describe(out)
    assert d["voices"] == 2 and d["pending"] == 1 and d["reason"] == "testas" and d["created"]
    monkeypatch.setattr(backup, "KEEP", 2)
    for i in range(3):
        (voices.data / "backups" / f"voices-2020010{i}_000000.tar.gz").write_bytes(b"x")
    backup.create("dar")
    assert len(backup.list_backups()) == 2                                      # laikoma tik KEEP naujausių


def test_b11_restore_replaces_and_keeps_current(voices):
    out = backup.create("prieš")
    (voices.speakers / "enroll.json").write_text(json.dumps({"Rūta": [[1.0, 1.0]]}))
    (voices.pending / "nez1.json").unlink()
    (voices.pending / "nez7.json").write_text("{}")
    d = backup.restore(out)
    assert d["voices"] == 2 and store.counts() == {"Ona": 1, "Jonas": 1}
    assert (voices.pending / "nez1.json").exists() and not (voices.pending / "nez7.json").exists()
    assert len(backup.list_backups()) == 2                                      # dabartiniai išsaugoti prieš atkūrimą
    assert backup.describe(backup.list_backups()[-1])["voices"] == 1          # ta kopija — su Rūta
    with pytest.raises(ValueError):
        bad = voices.data / "backups" / "voices-x.tar.gz"
        with tarfile.open(bad, "w:gz") as tar:
            pass
        backup.restore(bad, keep_current=False)


def test_b12_cli(voices, capsys):
    assert backup.main(["create"]) == 0 and "balsų: 2" in capsys.readouterr().out
    assert backup.main(["list"]) == 0 and "voices-" in capsys.readouterr().out
    assert backup.main(["restore"]) == 0 and "atkurta" in capsys.readouterr().out
    assert backup.main(["restore", "/nėra/x.tar.gz"]) == 1 and backup.main(["xyz"]) == 2


def test_b13_reset_voices_makes_backup_first(voices, monkeypatch):
    monkeypatch.setattr(reset, "running_transcriptions", lambda: [])
    assert backup.list_backups() == []
    reset.run([reset.VOICES])
    [b] = backup.list_backups()
    assert backup.describe(b)["voices"] == 2 and "Ištrinti" in backup.describe(b)["reason"]
    assert store.counts() == {}
    reset.run([reset.RECORDINGS])
    assert len(backup.list_backups()) == 1                                      # tik balsų trynimas daro kopiją
