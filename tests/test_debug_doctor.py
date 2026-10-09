"""Etapas 1: debug žurnalas (diktatura.debug + bash dbg) ir make doctor (diktatura.doctor), servisų valdymas."""
import os
import subprocess
import sys

import pytest

from testenv import PCM_GEN, REPO
from diktatura import config, debug, doctor, services


@pytest.fixture(autouse=True)
def fresh_debug_cache(monkeypatch):
    monkeypatch.delenv("DIKTATURA_DEBUG", raising=False)
    debug._cache[0] = -1e9
    yield
    debug._cache[0] = -1e9


def dlog(env):
    f = env.state / "debug.log"
    return f.read_text(encoding="utf-8") if f.exists() else ""


# ── debug ──

def test_debug_off_by_default_writes_nothing(env):
    assert not debug.enabled()
    debug.log("t", "x")
    assert dlog(env) == ""


def test_debug_setting_and_env_override(env, monkeypatch):
    config.save({"DEBUG": "1"})
    assert debug.enabled()
    debug.log("vox", "labas")
    assert dlog(env).rstrip().endswith("[vox] labas")
    monkeypatch.setenv("DIKTATURA_DEBUG", "0")              # env nugali nustatymą
    assert not debug.enabled()
    config.save({"DEBUG": "0"})
    monkeypatch.setenv("DIKTATURA_DEBUG", "1")
    assert debug.enabled()


def test_debug_log_rotates(env, monkeypatch):
    monkeypatch.setenv("DIKTATURA_DEBUG", "1")
    monkeypatch.setattr(debug, "MAX_BYTES", 200)
    for i in range(20):
        debug.log("t", f"eilutė {i} " + "x" * 20)
    assert (env.state / "debug.log.1").exists()
    assert (env.state / "debug.log").stat().st_size < 400


def test_bash_dbg_respects_setting_and_env(env):
    script = f'. "{REPO}/bin/common.sh"; load_config; DBG_TAG=t; dbg "iš bash"'
    subprocess.run(["bash", "-c", script], check=True)
    assert dlog(env) == ""
    env.write_conf(DEBUG=1)
    subprocess.run(["bash", "-c", script], check=True)
    assert "[t] iš bash" in dlog(env)
    subprocess.run(["bash", "-c", script], check=True, env={**os.environ, "DIKTATURA_DEBUG": "0"})
    assert dlog(env).count("iš bash") == 1


def test_vox_debug_logs_levels_and_decisions(env):
    env.write_conf(AUTOTRANSCRIBE=0, DEBUG=1)
    cap = f"{sys.executable} {PCM_GEN} silence:-70:3 speech:-20:2 silence:-70:6"
    subprocess.run([sys.executable, "-m", "diktatura.audio.vox"], env={**os.environ, "DIKTATURA_CAPTURE_CMD": cap},
                   capture_output=True, timeout=30)
    log = dlog(env)
    assert "[vox] capture:" in log and "triukšmas=" in log
    assert " open" in log and " close" in log


def test_transcribe_debug_traces_pipeline(env, fake_asr):
    import audio
    env.write_conf(DEBUG=1, ARCHIVE_MP3=1)
    f = env.recordings / "vox_20260101_100000.wav"
    audio.write_wav(f, audio.speech(1), audio.silence(1))
    assert env.sh("bash", REPO / "bin" / "transcribe-file.sh", f).returncode == 0
    log = dlog(env)
    assert f"įvestis={f}" in log and "ASR baigtas" in log and "archyvas:" in log


# ── doctor ──

def statuses(results):
    return [r.status for r in results]


def test_doctor_resources_thresholds():
    assert statuses(doctor.check_resources(8, 50, "azuolas-ct2")) == ["ok", "ok"]
    assert statuses(doctor.check_resources(2, 50, "azuolas-ct2")) == ["warn", "ok"]
    assert statuses(doctor.check_resources(2, 50, "medium")) == ["ok", "ok"]
    assert statuses(doctor.check_resources(8, 5, "medium"))[1] == "warn"
    assert statuses(doctor.check_resources(8, 1, "medium"))[1] == "fail"


def test_doctor_tools_missing_required_vs_optional():
    res = doctor.check_tools(which=lambda t: None if t in ("ffmpeg", "uv") else f"/usr/bin/{t}")
    by = {r.title.split()[1] if r.title.startswith("nėra") else r.title.split()[0]: r for r in res}
    assert by["ffmpeg"].status == "fail" and "make deps" in by["ffmpeg"].fix
    assert by["uv"].status == "warn"


def test_doctor_desktop_indicator_extension():
    run = lambda out: (lambda cmd: subprocess.CompletedProcess(cmd, 0, out, ""))  # noqa: E731
    assert doctor.check_desktop(run("ubuntu-appindicators@ubuntu.com\n"), lambda t: "/x")[0].status == "ok"
    assert doctor.check_desktop(run("ding@rastersoft.com\n"), lambda t: "/x")[0].status == "warn"
    assert doctor.check_desktop(run(""), lambda t: None) == []                # ne GNOME — netikrinama


def test_doctor_models_missing_and_corrupt(env):
    cfg = dict(config.load())
    res = doctor.check_models(cfg)
    assert statuses(res) == ["fail", "fail", "fail"] and "make model-convert" in res[0].fix
    assert doctor.check_models({**cfg, "MODEL": "medium"})[0].status == "warn"
    emb = env.data / "models" / "diarization" / "embedding_campplus_zh_en.onnx"
    emb.parent.mkdir(parents=True)
    emb.write_bytes(b"sugadintas")
    assert "SHA-256" in doctor.check_models(cfg)[1].title
    az = env.data / "models" / "azuolas-ct2" / "model.bin"
    az.parent.mkdir(parents=True)
    az.write_bytes(b"x")
    assert doctor.check_models(cfg)[0].status == "ok"


def test_doctor_config_invalid_and_unknown(env):
    assert statuses(doctor.check_config()) == ["warn"]                 # failo nėra
    config.ensure()
    assert statuses(doctor.check_config()) == ["ok"]
    env.write_conf(THREADS="daug", NEZINOMAS="1")
    res = doctor.check_config()
    assert statuses(res) == ["warn", "warn"] and any("NEZINOMAS" in r.title for r in res)


def test_doctor_services(env, fake_systemd):
    cfg = dict(config.load())
    res = doctor.check_services(cfg)
    assert res[0].status == "fail" and "make install-units" in res[0].fix
    fake_systemd.install_units()
    fake_systemd.set("diktatura-vox.service", active=True)
    fake_systemd.set("diktatura-tray.service", active=True)
    fake_systemd.set("diktatura-nightly.timer", enabled=True)
    assert statuses(doctor.check_services(cfg)) == ["ok"] * 4
    (fake_systemd.units_dir / "diktatura-vox.service").write_text("[Unit]\nsena versija\n")
    assert doctor.check_services(cfg)[0].status == "warn"
    fake_systemd.set("diktatura-nightly.timer", enabled=False)
    assert doctor.check_services({**cfg, "MODE": "deferred"})[-1].status == "fail"


def test_doctor_cli_isolated_reports_failures(env, fake_systemd):
    r = subprocess.run(["python3", "-m", "diktatura.doctor"], capture_output=True, text=True, cwd=REPO, timeout=120)
    assert r.returncode == 1
    assert "✗ nėra Ąžuolo modelio" in r.stdout and "→ make model-convert" in r.stdout
    assert "Rezultatas:" in r.stdout


# ── servisai ──

def test_set_recorder_mode_switches_exclusively(env, fake_systemd):
    ok, msg = services.set_recorder_mode("slack")
    assert ok and services.recorder_mode() == "slack"
    ok, _ = services.set_recorder_mode("vox")
    assert ok and services.recorder_mode() == "vox"
    assert not services.is_enabled("diktatura-autorecord.service")
    ok, _ = services.set_recorder_mode("off")
    assert ok and services.recorder_mode() == "off"
    assert services.set_recorder_mode("kita")[0] is False


def test_set_recorder_mode_reports_failure(env, fake_systemd):
    (fake_systemd.state / "diktatura-vox.service.broken").touch()
    ok, msg = services.set_recorder_mode("vox")
    assert not ok and "install-units" in msg


def test_timer_toggle(env, fake_systemd):
    assert services.set_timer(True)[0] and services.is_enabled(services.TIMER)
    assert services.set_timer(False)[0] and not services.is_enabled(services.TIMER)
