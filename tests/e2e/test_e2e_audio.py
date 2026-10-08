"""J [e2e]: tikras VOX daemon'as + tikras ffmpeg/PulseAudio capture per VIRTUALIUS įrenginius (null-sink).

Tavo garso nustatymai nekeičiami: sukuriami du laikini null-sink'ai („diktatura_test_mic/sys"), numatytieji
įrenginiai patikrinami prieš/po ir atstatomi. Tikras VOX servisas jų negirdi (klauso tavo įrenginių).
ASR — netikras (greitis); tikras Ąžuolas — make test-full.
"""
import os
import signal
import subprocess
import sys
import time

import numpy as np
import pytest

import audio
import lt
from testenv import REAL, REPO

pytestmark = pytest.mark.e2e
PACTL = REAL["pactl"]
MIC, SYS = "diktatura_test_mic", "diktatura_test_sys"


def pactl(*args):
    return subprocess.run([PACTL, *args], capture_output=True, text=True, timeout=10)


def defaults():
    return pactl("get-default-sink").stdout.strip(), pactl("get-default-source").stdout.strip()


@pytest.fixture(scope="module")
def vsinks():
    if not PACTL or pactl("info").returncode != 0:
        pytest.skip("nėra PulseAudio (pactl info)")
    before = defaults()
    mods, keepalive = [], []
    try:
        for name in (MIC, SYS):
            r = pactl("load-module", "module-null-sink", f"sink_name={name}",
                      f"sink_properties=device.description={name}")
            assert r.returncode == 0, r.stderr
            mods.append(r.stdout.strip())
            # Nepertraukiama tyla: null-sink be grojimo užmiega (SUSPENDED) ir jo monitor neduoda duomenų,
            # tada ffmpeg „join" stringa. Tikras įrenginys su VOX capture lieka RUNNING — imituojam tai.
            keepalive.append(subprocess.Popen(["pacat", "--playback", f"--device={name}", "--raw",
                                               "--format=s16le", "--rate=16000", "--channels=2"],
                                              stdin=open("/dev/zero", "rb"), stderr=subprocess.DEVNULL))
        after = defaults()
        if after != before:                                   # module-switch-on-connect galėjo perjungti
            pactl("set-default-sink", before[0])
            pactl("set-default-source", before[1])
        time.sleep(0.5)
        yield {"before": before, "after_load": after}
    finally:
        for k in keepalive:
            k.kill()
        for m in mods:
            pactl("unload-module", m)
        if defaults() != before:
            pactl("set-default-sink", before[0])
            pactl("set-default-source", before[1])


@pytest.fixture
def clip(tmp_path):
    c = lt.clips()
    if not c:
        pytest.skip("nėra LT fixture'ų — make fixtures")
    f = tmp_path / "clip.wav"
    audio.write_wav(f, lt.decode(c[0][0]))
    return f


@pytest.fixture
def vox(env, vsinks):
    procs = []

    def start(**conf):
        env.write_conf(**conf)
        p = subprocess.Popen([sys.executable, "-m", "diktatura.audio.vox"],
                             env={**os.environ, "DIKTATURA_MIC": f"{MIC}.monitor", "DIKTATURA_MONITOR": f"{SYS}.monitor"},
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(p)
        time.sleep(3.0)                                       # 2 s kalibracija
        return p

    yield start
    for p in procs:
        if p.poll() is None:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=10)


def play(path, device=MIC):
    subprocess.run([REAL["paplay"], f"--device={device}", str(path)], check=True, timeout=120)


def wait_for(cond, timeout=10.0, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def test_virtual_devices_do_not_change_your_defaults(vsinks):
    assert vsinks["after_load"] == vsinks["before"], "null-sink perjungė numatytąjį įrenginį (atstatyta)"
    assert defaults() == vsinks["before"]


def test_j1_vox_records_closes_and_transcribes(env, vox, clip, fake_asr):
    vox(VOX_SILENCE_SEC=2, MODE="immediate", AUTOTRANSCRIBE=1, ARCHIVE_MP3=1)
    play(clip)
    assert wait_for(lambda: list(env.recordings.glob("vox_*.named.txt")), 20), env.log("autorecord")
    assert wait_for(lambda: list(env.recordings.glob("vox_*.mp3")) and not list(env.recordings.glob("vox_*.wav")), 10)


def tail_silence(wav) -> float:
    """Kiek sekundžių faile po paskutinio NE nulinio mėginio (null-sink tyla = tikri nuliai; VOX garsu laiko ir
    tylų klipo galą virš triukšmo + atsargos) — turi būti = VOX_SILENCE_SEC."""
    data, sr = audio.read_wav(wav)
    loud = np.flatnonzero(np.abs(data).max(axis=1) > 0)
    return (len(data) - loud[-1]) / sr


def record_once(env, clip, n_before):
    state = env.run / "recording"
    play(clip)
    # null-sink capture vėluoja kelias sekundes (tikri įrenginiai ~1 s) — laukiam pagal failus, ne laikrodį
    assert wait_for(lambda: len(list(env.recordings.glob("vox_*.wav"))) > n_before and not state.exists(), 30), \
        env.log("autorecord")


def test_j2_silence_setting_changes_close_delay_live(env, vox, clip):
    vox(VOX_SILENCE_SEC=5, AUTOTRANSCRIBE=0)
    record_once(env, clip, 0)
    env.write_conf(VOX_SILENCE_SEC=2, AUTOTRANSCRIBE=0)       # be restarto
    time.sleep(7)                                             # daemon'as perskaito kas ~5 s garso
    record_once(env, clip, 1)
    a, b = sorted(env.recordings.glob("vox_*.wav"))
    tails = [round(tail_silence(a), 2), round(tail_silence(b), 2)]
    assert abs(tails[0] - 5) < 0.3 and abs(tails[1] - 2) < 0.3, f"tylos uodegos faile: {tails} (tikėtasi 5 ir 2)"


def test_j3_deferred_then_pending(env, vox, clip, fake_asr):
    state = env.run / "recording"
    vox(VOX_SILENCE_SEC=2, MODE="deferred", AUTOTRANSCRIBE=1)
    play(clip)
    assert wait_for(lambda: list(env.recordings.glob("vox_*.wav")) and not state.exists(), 10)
    time.sleep(1)
    assert not list(env.recordings.glob("vox_*.txt")), "deferred — po įrašo teksto dar nėra"
    [w] = env.recordings.glob("vox_*.wav")
    old = time.time() - 120
    os.utime(w, (old, old))                                   # „senas" (pending praleidžia ką tik keistus)
    r = env.sh("bash", REPO / "bin" / "transcribe-pending.sh")
    assert r.returncode == 0, r.stderr
    assert list(env.recordings.glob("vox_*.named.txt"))


def test_j4_no_dropouts_while_cpu_is_busy(env, vox, tmp_path):
    vox(VOX_SILENCE_SEC=2, AUTOTRANSCRIBE=0)
    tone = tmp_path / "tone.wav"
    audio.write_wav(tone, audio.tone(15, 997, -20))          # 997 Hz: jokių tikslių nulių mėginiuose
    burn = [subprocess.Popen(["nice", "-n", "19", sys.executable, "-c", "while True: pass"])
            for _ in range(os.cpu_count() or 4)]                   # kaip transkripcija: visos branduolių gijos
    try:
        play(tone)
        assert wait_for(lambda: list(env.recordings.glob("vox_*.wav")) and not (env.run / "recording").exists(), 10)
    finally:
        for b in burn:
            b.kill()
    [w] = env.recordings.glob("vox_*.wav")
    data, sr = audio.read_wav(w)
    left = data[:, 0]
    loud = np.abs(left) > 0.01
    first, last = np.argmax(loud), len(loud) - np.argmax(loud[::-1])
    seg = left[first:last]
    assert abs(len(seg) / sr - 15) < 0.5, f"įrašytas tonas {len(seg) / sr:.2f}s (dingo garso?)"
    zeros = np.mean(np.abs(seg) < 1e-4)
    assert zeros < 0.01, f"nulių (dropout) {zeros:.1%}"
