"""Etapas 5: nuolat įkrautas ASR serveris (diktatura.asr.server/client) su NETIKRU modeliu (greita, be RAM).

Tikras Ąžuolas per serverį — tests/full/test_asr_full.py.
"""
import os
import subprocess
import sys
import threading
import time
from collections import namedtuple

import pytest

import audio
from diktatura import config, doctor, services
from diktatura.asr import client, server
from testenv import REPO

Seg = namedtuple("Seg", "start end text")
Info = namedtuple("Info", "duration")


class FakeModel:
    def __init__(self, key):
        self.key = key

    def transcribe(self, samples, **kw):
        return iter([Seg(0.0, 1.0, " labas rytas")]), Info(len(samples) / 16000)


@pytest.fixture
def srv(env):
    loads = []

    def loader(name, compute, threads):
        loads.append((name, compute, threads))
        return FakeModel((name, threads))

    cache = server.ModelCache(loader, idle_sec=3600)
    stop, ready = threading.Event(), threading.Event()
    sock = env.run / "asr.sock"
    t = threading.Thread(target=server.serve, args=(cache, sock, stop, ready), daemon=True)
    t.start()
    assert ready.wait(5)
    yield cache, loads, sock
    stop.set()
    t.join(5)


def wav(env, name="rec_20260101_100000.wav", stereo=False):
    f = env.recordings / name
    audio.write_wav(f, audio.speech(2), audio.speech(2) if stereo else None)
    return f


def test_server_reuses_model_and_reloads_on_new_params(env, srv):
    cache, loads, sock = srv
    f = wav(env)
    argv = [str(f), "--model", "m1", "--threads", "2", "--vad", "off"]
    r1 = client.request("mono", argv, sock)
    assert r1["rc"] == 0 and r1["loaded"] and f.with_suffix(".txt").read_text().strip() == "labas rytas"
    r2 = client.request("mono", argv, sock)
    assert r2["rc"] == 0 and not r2["loaded"] and len(loads) == 1         # modelis jau atmintyje
    r3 = client.request("mono", [str(f), "--model", "m1", "--threads", "4", "--vad", "off"], sock)
    assert r3["loaded"] and loads[-1] == ("m1", "int8", 4)                # kitos gijos -> perkrauna


def test_server_unloads_after_idle_and_loads_again(env, srv):
    cache, loads, sock = srv
    f = wav(env)
    argv = [str(f), "--model", "m1", "--threads", "2", "--vad", "off"]
    client.request("mono", argv, sock)
    cache.idle_sec = 0.2
    time.sleep(1.5)                                                       # serveris tikrina kas ~1 s
    assert cache.model is None, "po neveikos modelis turi būti iškrautas (RAM)"
    assert client.request("mono", argv, sock)["loaded"] and len(loads) == 2


def test_server_survives_bad_requests(env, srv):
    _, _, sock = srv
    assert client.request("kitas", ["x"], sock)["rc"] == 2
    bad = client.request("mono", [str(env.recordings / "nera.wav"), "--model", "m1"], sock)
    assert bad["rc"] != 0 and "Nėra failo" in bad["log"]
    named_mono = client.request("named", [str(wav(env)), "--model", "m1", "--vad", "off"], sock)
    assert named_mono["rc"] != 0 and "STEREO" in named_mono["log"]          # SystemExit nemuša serverio
    assert client.request("mono", [str(wav(env)), "--model", "m1", "--vad", "off"], sock)["rc"] == 0


def test_client_reports_unavailable_server(env):
    r = subprocess.run([sys.executable, "-m", "diktatura.asr.client", "mono", "x.wav"], capture_output=True, text=True)
    assert r.returncode == client.UNAVAILABLE and "nepasiekiamas" in r.stderr


def test_pipeline_uses_server_when_enabled(env, srv):
    cache, loads, sock = srv
    env.write_conf(ASR_SERVER=1, VAD_FILTER=0, ARCHIVE_MP3=1, MODEL="medium")
    f = wav(env)
    r = env.sh("bash", REPO / "bin" / "transcribe-file.sh", f)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f.with_suffix(".txt").read_text().strip() == "labas rytas" and f.with_suffix(".mp3").exists()
    assert "modelis užkrautas" in env.log("transcribe") and loads[0][0] == "medium"


def test_pipeline_falls_back_without_server(env):
    env.write_conf(ASR_SERVER=1, DELETE_EMPTY=1)                          # serverio nėra (lizdo nėra)
    f = env.recordings / "vox_20260101_100000.wav"
    audio.write_wav(f, audio.silence(2), audio.silence(2))
    r = env.sh("bash", REPO / "bin" / "transcribe-file.sh", f, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not f.exists() and "modelis nekraunamas" in env.log("transcribe")   # atskiras procesas + VAD


def test_settings_toggle_enables_service_and_doctor_warns(env, fake_systemd):
    cfg = dict(config.load())
    assert services.set_asr_server(True)[0] and services.is_active(services.ASR)
    res = doctor.check_services({**cfg, "ASR_SERVER": True})
    assert any("ASR serveris veikia" in r.title for r in res)
    services.set_asr_server(False)
    res = doctor.check_services({**cfg, "ASR_SERVER": True})
    assert any(r.status == "warn" and "ASR_SERVER=1" in r.title for r in res)


def test_server_main_starts_and_stops_on_sigterm(env):
    p = subprocess.Popen([sys.executable, "-m", "diktatura.asr.server"], stdout=subprocess.PIPE, text=True)
    try:
        sock = env.run / "asr.sock"
        end = time.monotonic() + 10
        while not sock.exists() and time.monotonic() < end:
            time.sleep(0.1)
        assert sock.exists()
        p.terminate()
        assert p.wait(timeout=10) == 0 and not sock.exists()
    finally:
        if p.poll() is None:
            p.kill()
