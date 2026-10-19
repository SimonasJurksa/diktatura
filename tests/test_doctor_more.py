"""DC1–DC6: make doctor patikros su netikromis komandomis (kiekviena šaka: ✓ / ⚠ / ✗ ir patarimas)."""
import json
import subprocess

from diktatura import config, doctor, paths
from diktatura.speakers import store


def fake_run(table):
    """run(cmd) -> CompletedProcess pagal pirmą sutampantį raktą komandoje."""
    def run(cmd, timeout=15):
        joined = " ".join(map(str, cmd))
        for key, (rc, out, err) in table.items():
            if key in joined:
                return subprocess.CompletedProcess(cmd, rc, out, err)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


def statuses(res):
    return [r.status for r in res]


def test_dc1_audio_checks():
    ok = fake_run({"pactl info": (0, "Server", ""), "get-default-source": (0, "mic.in\n", ""),
                   "get-default-sink": (0, "spk\n", ""), "list sources short": (0, "1\tspk.monitor\n2\tmic.in\n", "")})
    res = doctor.check_audio(ok)
    assert statuses(res) == [doctor.OK, doctor.OK] and "spk.monitor" in res[1].title
    assert statuses(doctor.check_audio(fake_run({"pactl info": (1, "", "Connection refused")}))) == [doctor.FAIL]
    no_mon = fake_run({"pactl info": (0, "", ""), "get-default-source": (0, "mic\n", ""),
                       "get-default-sink": (0, "spk\n", ""), "list sources short": (0, "2\tmic\n", "")})
    res = doctor.check_audio(no_mon)
    assert statuses(res) == [doctor.OK, doctor.FAIL] and res[1].fix
    no_src = fake_run({"pactl info": (0, "", ""), "get-default-source": (0, "", "")})
    assert doctor.check_audio(no_src)[0].status == doctor.FAIL


def test_dc2_python_checks(env, monkeypatch):
    monkeypatch.setattr(paths, "VENV_PY", env.root / "nėra" / "python")
    [r] = doctor.check_python(fake_run({}))
    assert r.status == doctor.FAIL and r.fix == "make setup"
    monkeypatch.setattr(paths, "VENV_PY", paths.REPO / ".venv" / "bin" / "python")
    res = doctor.check_python(fake_run({"faster_whisper": (1, "", "ModuleNotFoundError: No module named 'x'"),
                                        "import gi": (0, "", "")}))
    assert statuses(res) == [doctor.FAIL, doctor.OK] and "No module" in res[0].title
    res = doctor.check_python(fake_run({"import gi": (1, "", "ValueError")}))
    assert statuses(res) == [doctor.OK, doctor.FAIL] and res[1].fix == "make deps"


def test_dc3_git_checks(monkeypatch):
    res = doctor.check_git(fake_run({"core.hooksPath": (0, ".githooks\n", "")}))
    assert res[0].status == doctor.OK
    res = doctor.check_git(fake_run({"core.hooksPath": (1, "", "")}))
    assert res[0].status == doctor.WARN and res[0].fix == "make hooks"
    monkeypatch.setattr(paths, "REPO", paths.REPO / "nėra")
    assert doctor.check_git(fake_run({})) == []


def test_dc4_voices_checks(env):
    store.mark_model()
    res = doctor.check_voices()
    assert statuses(res) == [doctor.OK, doctor.WARN] and "registruota 0" in res[0].title
    store.add_embedding("Ona", [1.0, 0.0])
    store.add_owner([0.0, 1.0], "x")
    res = doctor.check_voices()
    assert statuses(res) == [doctor.OK, doctor.OK] and "registruota 1" in res[0].title
    (env.speakers / "model.json").write_text(json.dumps({"model": "senas-modelis"}))
    [r] = doctor.check_voices()
    assert r.status == doctor.FAIL and "speakers-migrate" in r.fix


def test_dc5_runtime_checks(env, monkeypatch):
    assert doctor.check_runtime(fake_run({})) == []
    (env.run / "recording").write_text("vox /x.wav")
    [r] = doctor.check_runtime(fake_run({"pgrep": (1, "", "")}))
    assert r.status == doctor.WARN and "pakibęs" in r.title and str(env.run / "recording") in r.fix
    [r] = doctor.check_runtime(fake_run({"pgrep": (0, "1 x", "")}))
    assert r.status == doctor.OK
    (env.run / "recording").unlink()
    env.write_conf(DEBUG=1)
    [r] = doctor.check_runtime(fake_run({}))
    assert r.status == doctor.WARN and "debug" in r.title.lower()
    monkeypatch.setenv("DIKTATURA_DEBUG", "0")
    env.write_conf(DEBUG=0)
    assert doctor.check_runtime(fake_run({})) == []


def test_dc6_resources_helpers_and_run_all(env, monkeypatch, capsys):
    assert doctor.mem_available_gb() > 0.1 and doctor.disk_free_gb(paths.DATA_DIR) > 0.01
    assert doctor.disk_free_gb(env.root / "nėra") >= 0.0                        # nėra kelio — be išimties
    res = doctor.check_resources(1.0, 100.0, "azuolas-ct2")
    assert any(r.status in (doctor.WARN, doctor.FAIL) and "RAM" in r.title for r in res)
    res = doctor.check_resources(8.0, 1.0, "azuolas-ct2")
    assert any(r.status in (doctor.WARN, doctor.FAIL) and "disk" in r.title.lower() for r in res)
    sections = doctor.run_all()
    assert [s for s, _ in sections][:3] == ["Sistemos įrankiai", "Garsas", "Python aplinkos"]
    assert "Kodo versija" in [s for s, _ in sections] and all(isinstance(rs, list) for _, rs in sections)
    monkeypatch.setattr(doctor, "run_all", lambda: [("A", [doctor.R(doctor.OK, "gerai")]),
                                                    ("B", [doctor.R(doctor.FAIL, "blogai", "daryk X")])])
    assert doctor.main() == 1
    out = capsys.readouterr().out
    assert "✗ blogai" in out and "daryk X" in out and "1 ✗" in out
    monkeypatch.setattr(doctor, "run_all", lambda: [("A", [doctor.R(doctor.WARN, "hm")])])
    assert doctor.main() == 0
    assert config.load()["MODEL"] in ("azuolas-ct2", "medium")
