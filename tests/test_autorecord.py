"""D. Slack skambučių aptikimas (bin/autorecord.sh) su netikru pactl ir sintetiniu ffmpeg capture."""
import os
import signal
import subprocess
import time

import pytest

import audio
from testenv import REPO

AUTOREC = ["bash", str(REPO / "bin" / "autorecord.sh")]


def wait_for(cond, timeout=10.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


@pytest.fixture
def daemon(env, fake_audio):
    procs = []

    def start(**conf):
        env.write_conf(**{"SLACK_GRACE_SEC": 1, **conf})
        p = subprocess.Popen(AUTOREC, env={**os.environ, "DIKTATURA_POLL": "0.2"},
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        procs.append(p)
        assert wait_for(lambda: "daemon startavo" in env.log("autorecord"), 5)
        return p

    yield start
    for p in procs:
        if p.poll() is None:
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)


def slack_wavs(env):
    return sorted(env.recordings.glob("slack_*.wav"))


def test_d1_call_start_and_stop_after_grace(env, fake_audio, daemon):
    daemon(AUTOTRANSCRIBE=0)
    state = env.run / "recording"
    time.sleep(0.5)
    assert not slack_wavs(env), "be skambučio — neįrašo"
    fake_audio.call("ringrtc")
    assert wait_for(state.exists, 5), "skambutis -> START"
    kind, path = state.read_text().strip().split(" ", 1)
    assert kind == "slack" and path.endswith(".wav")
    time.sleep(1.5)
    fake_audio.hangup()
    assert wait_for(lambda: not state.exists(), 5), "skambučio nebėra -> STOP po grace"
    assert wait_for(lambda: "STOP" in env.log("autorecord"), 5)          # (būsena trinama prieš ffprobe + log)
    assert "START" in env.log("autorecord")
    [f] = slack_wavs(env)
    data, sr = audio.read_wav(f)                            # ffmpeg baigė švariai (SIGINT) -> teisingas wav
    assert data.shape[1] == 2 and 1.0 < len(data) / sr < 6


def test_d1_slack_client_name_matches_but_other_apps_do_not(env, fake_audio, daemon):
    daemon(AUTOTRANSCRIBE=0)
    fake_audio.call("Firefox")
    time.sleep(1.0)
    assert not slack_wavs(env), "kitos programos mikrofonas — ne Slack skambutis"
    fake_audio.call("Slack")
    assert wait_for(lambda: slack_wavs(env), 5)


def test_d2_max_duration_forces_stop_and_waits_for_new_call(env, fake_audio, daemon):
    daemon(AUTOTRANSCRIBE=0, MAX_REC_SEC=2)                  # (tikrame config min 60 s — čia tiesiai faile)
    state = env.run / "recording"
    fake_audio.call()
    assert wait_for(state.exists, 5)
    assert wait_for(lambda: "maksimali trukmė" in env.log("autorecord"), 6)
    assert wait_for(lambda: not state.exists(), 3)
    time.sleep(1.5)
    assert len(slack_wavs(env)) == 1, "pakibęs srautas neturi gaminti naujų failų"
    fake_audio.hangup()
    assert wait_for(lambda: "vėl laukiu" in env.log("autorecord"), 3)
    time.sleep(1.1)                                          # failų vardai — sekundės tikslumu
    fake_audio.call()
    assert wait_for(lambda: len(slack_wavs(env)) == 2, 5), "naujas skambutis -> naujas įrašas"


@pytest.mark.parametrize("conf,expect_text,log_msg", [
    ({"AUTOTRANSCRIBE": 1, "MODE": "immediate"}, True, "auto-transkripciją"),
    ({"AUTOTRANSCRIBE": 1, "MODE": "deferred"}, False, "deferred"),
    ({"AUTOTRANSCRIBE": 0, "MODE": "immediate"}, False, "IŠJUNGTA"),
])
def test_d3_mode_x_autotranscribe(env, fake_audio, fake_asr, daemon, conf, expect_text, log_msg):
    daemon(ARCHIVE_MP3=0, **conf)
    fake_audio.call()
    assert wait_for(lambda: slack_wavs(env), 5)
    time.sleep(1.2)
    fake_audio.hangup()
    assert wait_for(lambda: log_msg in env.log("autorecord"), 6)
    if expect_text:
        assert wait_for(lambda: list(env.recordings.glob("slack_*.named.txt")), 10)
    else:
        time.sleep(1.0)
        assert not list(env.recordings.glob("slack_*.txt"))
        assert len(slack_wavs(env)) == 1, "įrašas lieka eilėje (naktiniam / rankiniam)"
