"""Q. Transkripcijos eiga ir prognozė (diktatura.progress): Reporter, greičiai, prognozė, procesų radimas, stabdymas.

Procesų testai paleidžia TIKRĄ bin/transcribe-file.sh su netikru ASR (FAKE_ASR_SLEEP) — eilė, flock ir stabdymas
tikri; stabdomi tik šio testo procesai (atrenkami pagal testo <runtime> katalogą, ne pagal pavadinimą).
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

import audio
from testenv import REPO

TFILE = REPO / "bin" / "transcribe-file.sh"
TPENDING = REPO / "bin" / "transcribe-pending.sh"


@pytest.fixture
def P(env):
    from diktatura import progress
    progress._dur_cache.clear()
    return progress


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def make_wav(env, name, sec=2.0, stereo=True, age=3600):
    f = env.recordings / name
    audio.write_wav(f, audio.speech(sec, -20), audio.silence(sec) if stereo else None)
    t = time.time() - age
    os.utime(f, (t, t))
    return f


def wait_for(cond, timeout=10.0, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


# ── Q1: Reporter ──

def test_q1_reporter_phases_file_and_history(env, P):
    clk = Clock()
    f = env.recordings / "vox_20261012_101456.wav"
    with P.Reporter(f, "named", "/x/models/azuolas-ct2", 6, clock=clk) as rep:
        pf = P.progress_file(f)
        assert json.loads(pf.read_text())["phase"] == "start"
        for ph, dt in (("prep", 30), ("vad", 20), ("load", 6)):
            rep.phase(ph)
            clk.t += dt
        rep.set(audio_sec=1000.0, speech=[300.0, 500.0], skip=[False, False])
        rep.phase("asr_me", total=1000)
        clk.t += 2
        rep.advance(10)                                                # 2 s nuo paskutinio rašymo — rašoma
        d = json.loads(pf.read_text())
        assert d["phase"] == "asr_me" and d["done"] == 10 and d["total"] == 1000 and d["times"]["prep"] == 30
        clk.t += 0.2
        rep.advance(20)                                                # per dažnai — nerašoma
        assert json.loads(pf.read_text())["done"] == 10
        clk.t += 447.8
        rep.phase("asr_them", total=1000)
        clk.t += 700
        rep.phase("names")
        clk.t += 25
        rep.finish()
    assert not pf.exists()
    [rec] = P.history()
    assert rec["model"] == "azuolas-ct2" and rec["kind"] == "named" and rec["audio"] == 1000
    assert rec["phases"] == {"prep": 30, "vad": 20, "load": 6, "asr": 1150, "names": 25}
    assert rec["finished"] - rec["started"] == pytest.approx(1231)


def test_q1_reporter_exception_removes_file_no_history(env, P):
    f = env.recordings / "vox_20261012_101500.wav"
    with pytest.raises(RuntimeError):
        with P.Reporter(f, "mono", "medium", 4) as rep:
            rep.phase("vad")
            raise RuntimeError("lūžo")
    assert not P.progress_file(f).exists() and P.history() == []


def test_q1_history_capped(env, P):
    for i in range(P.HISTORY_MAX + 7):
        P.add_history({"audio": 1, "n": i})
    h = P.history()
    assert len(h) == P.HISTORY_MAX and h[-1]["n"] == P.HISTORY_MAX + 6


# ── Q2–Q3: greičiai ir etapų planas ──

def test_q2_rates_defaults_and_learned_ratio_of_sums(env, P):
    r = P.rates("azuolas-ct2", [])
    assert r["n"] == 0 and r["asr"] == P.MODEL_ASR["azuolas-ct2"] and P.rates("medium", [])["asr"] == 0.6
    hist = [  # ilgas įrašas: asr 2 s / kalbos s; trumpas — 10 s / s (pastovios sąnaudos) — sveria mažai
        {"model": "azuolas-ct2", "kind": "named", "audio": 1000, "speech": [300, 500],
         "phases": {"prep": 40, "vad": 20, "load": 8, "asr": 1600, "names": 50}},
        {"model": "azuolas-ct2", "kind": "named", "audio": 10, "speech": [2, 0],
         "phases": {"prep": 1, "vad": 1, "load": 4, "asr": 20, "names": 0}},
        {"model": "medium", "kind": "mono", "audio": 100, "speech": [50], "phases": {"asr": 10, "vad": 2, "load": 2}},
    ]
    r = P.rates("azuolas-ct2", hist)
    D, K = P.DEFAULTS, P.PRIOR_K
    sm = lambda num, den, d, k: (num + d * k) / (den + k)                     # noqa: E731
    assert r["n"] == 2
    assert r["asr"] == pytest.approx(sm(1620, 802, 1.5, K["asr"]))
    assert r["prep"] == pytest.approx(sm(41, 1010, D["prep"], K["prep"]))
    assert r["vad"] == pytest.approx(sm(21, 2020, D["vad"], K["vad"]))
    assert r["names"] == pytest.approx(sm(50, 500, D["names"], K["names"])) and r["load"] == 8
    assert r["speech"] == pytest.approx(sm(802, 2020, D["speech"], K["speech"]))
    assert P.rates("medium", hist)["asr"] == pytest.approx(sm(10, 50, 0.6, K["asr"]))
    long_hist = [dict(hist[0], audio=100000, speech=[30000, 50000],
                      phases={"prep": 4000, "vad": 2000, "load": 8, "asr": 160000, "names": 5000})]
    assert P.rates("azuolas-ct2", long_hist)["asr"] == pytest.approx(2.0, rel=0.01)   # daug istorijos — tikras greitis


def test_q2_few_empty_clips_do_not_teach_no_speech(P):
    """20 įrašų po 10 s be kalbos (VAD praleido): kalbos dalis 0.5 -> 0.3 (ne 0.05 kaip be švelninimo); krovimas ne 0."""
    hist = [{"model": "azuolas-ct2", "kind": "named", "audio": 10, "speech": [0, 0],
             "phases": {"prep": 0.5, "vad": 0.2, "load": 0.0, "asr": 0.0, "names": 0.0}}] * 20
    r = P.rates("azuolas-ct2", hist)
    assert r["speech"] >= 0.29 and r["load"] == P.DEFAULTS["load"] and r["asr"] == P.MODEL_ASR["azuolas-ct2"]


def test_q3_phase_plan_named_mono_and_skips(P):
    r = dict(P.DEFAULTS)
    p = P.phase_plan("named", 100, r, speech=[40, 60])
    assert p["asr_me"] == 40 * r["asr"] and p["asr_them"] == 60 * r["asr"] and p["names"] == 60 * r["names"]
    assert p["prep"] == 100 * r["prep"] and p["vad"] == 200 * r["vad"] and p["load"] == r["load"]
    p = P.phase_plan("named", 100, r, speech=[40, 60], skip=[False, True])
    assert p["asr_them"] == 0 and p["names"] == 0
    assert P.phase_plan("named", 100, r, speech=[0, 0])["load"] == 0                # be kalbos modelis nekraunamas
    m = P.phase_plan("mono", 100, r)
    assert set(m) == {"vad", "load", "asr"} and m["asr"] == 100 * r["speech"] * r["asr"]


# ── Q4: vykdomo darbo prognozė ──

def info(phase, done=0, total=0, times=None, started=0.0, phase_started=0.0, speech=(500, 500)):
    return {"kind": "named", "audio_sec": 1000.0, "speech": list(speech), "skip": [False, False],
            "phases": ["prep", "vad", "load", "asr_me", "asr_them", "names"], "phase": phase, "done": done,
            "total": total, "times": times or {}, "started": started, "phase_started": phase_started}


def test_q4_estimate_normal_speed_matches_plan(P):
    r = dict(P.DEFAULTS)
    plan = P.phase_plan("named", 1000, r, [500, 500])
    t = {"prep": plan["prep"], "vad": plan["vad"], "load": plan["load"]}
    # asr_me: įprastu greičiu (plan / 1000 s per garso s), pusė apdorota
    el = plan["asr_me"] / 2
    left, slow = P.estimate_running(info("asr_me", 500, 1000, t, phase_started=100), r, now=100 + el)
    expect = plan["asr_me"] / 2 + plan["asr_them"] + plan["names"] + 1000 * r["archive"]
    assert slow == pytest.approx(1.0, abs=0.01) and left == pytest.approx(expect, rel=0.02)


def test_q4_cpu_load_slows_whole_estimate(P):
    """Paruošimas užtruko 2× ilgiau, Whisper eina 2× lėčiau -> likę etapai ir eilė × ~2."""
    r = dict(P.DEFAULTS)
    plan = P.phase_plan("named", 1000, r, [500, 500])
    t = {"prep": plan["prep"] * 2, "vad": plan["vad"] * 2, "load": plan["load"]}
    el = plan["asr_me"] / 2 * 2
    left, slow = P.estimate_running(info("asr_me", 500, 1000, t, phase_started=0), r, now=el)
    assert slow == pytest.approx(2.0, rel=0.05)
    assert left == pytest.approx(2 * (plan["asr_me"] / 2 + plan["asr_them"] + plan["names"]) + 1000 * r["archive"],
                                 rel=0.05)


def test_q4_live_rate_dominates_after_enough_progress(P):
    """Whisper realiai 3× greitesnis nei įprasta: nuo ~15 % apdoroto garso dabartinio etapo likutis — pagal tikrą."""
    r = dict(P.DEFAULTS)
    plan = P.phase_plan("named", 1000, r, [500, 500])
    rate = plan["asr_me"] / 1000 / 3                                 # s / garso s
    left, slow = P.estimate_running(info("asr_me", 400, 1000, {}, phase_started=0), r, now=400 * rate)
    cur = left - plan["asr_them"] * slow - plan["names"] * slow - 1000 * r["archive"]
    assert cur == pytest.approx(600 * rate, rel=0.02) and slow < 0.5


def test_q4_overrun_phase_still_positive_and_decreasing(P):
    r = dict(P.DEFAULTS)
    lefts = []
    for now in (10, 100, 1000):                                      # prep užtruko daug ilgiau nei numatyta
        left, _ = P.estimate_running(info("prep", phase_started=0), r, now=now)
        lefts.append(left)
    assert all(x > 0 for x in lefts)
    left_a, _ = P.estimate_running(info("asr_them", 100, 1000, {}, phase_started=0), r, now=100)
    left_b, _ = P.estimate_running(info("asr_them", 600, 1000, {}, phase_started=0), r, now=600)
    assert left_b < left_a                                           # pastoviu greičiu — mažėja


def test_q4_estimate_queued_job_scaled_by_slowdown(P):
    r = dict(P.DEFAULTS)
    a = P.estimate_job_total("named", 600, r)
    b = P.estimate_job_total("named", 600, r, slow=2.0)
    assert b - r["overhead"] - 600 * r["archive"] == pytest.approx(2 * (a - r["overhead"] - 600 * r["archive"]))


def test_q4_batch_start_chains_back_to_back_jobs(P):
    hist = [{"started": 0, "finished": 100}, {"started": 400, "finished": 500},
            {"started": 530, "finished": 600}, {"started": 650, "finished": 700}, {"started": 900, "finished": 990}]
    start, n = P._batch_start(hist, running_start=760)               # 990 — po dabartinio pradžios: ignoruojamas
    assert (start, n) == (400, 3)                                    # 100 -> 400: tarpas 300 > BATCH_GAP
    assert P._batch_start([], 50) == (50, 0)


# ── Q5: formatavimas ──

def test_q5_formatting(P):
    assert P.fmt_left(30) == "< 1 min" and P.fmt_left(7 * 60) == "~7 min"
    assert P.fmt_left(65 * 60) == "~1 val. 05 min" and P.fmt_left(12 * 3600) == "~12 val."
    assert P.fmt_clock(6750) == "1:52:30" and P.fmt_clock(65) == "1:05"
    assert P.bar(0.5, 10) == "[█████░░░░░]" and P.bar(2, 4) == "[████]" and P.bar(-1, 4) == "[░░░░]"
    now = time.mktime((2026, 10, 12, 13, 0, 0, 0, 0, -1))
    assert P.fmt_eta(300, now) == "~5 min"                          # < 10 min — be laikrodžio
    assert P.fmt_eta(2 * 3600, now) == "~2 val. 00 min (≈ 15:00)"
    assert P.fmt_eta(14 * 3600, now) == "~14 val. (≈ 10-13 03:00)"  # kitą dieną — su data


def test_q5_summary_and_describe(P):
    now = 1000.0
    run = P.Job(pid=1, file=Path("/x/vox_20261012_101456.wav"), state="running", start=now - 600, phase="asr_me",
                audio_sec=6750, info={"phases": list(P.NAMED_PHASES), "done": 600, "total": 6750}, left=1800, total=2400)
    q = [P.Job(pid=2, file=Path("/x/vox_20261012_121811.wav"), state="queued", audio_sec=9, left=30),
         P.Job(pid=0, file=Path("/x/slack_20261012_140000.wav"), state="pending", audio_sec=1800, left=2700)]
    snap = P.Snapshot(now=now, running=run, queued=q, batch_start=now - 600, slow=2.0)
    assert P.summary(snap) == "25 % · liko ~1 val. 16 min · eilėje 2"
    assert P.summary(P.Snapshot(now=now)) == ""
    text = "\n".join(P.describe(snap))
    assert "vox_20261012_101456.wav" in text and "Etapas 4/6: Transkribuojama: Tu" in text and "10:00 / 1:52:30" in text
    assert "Visa eilė: 3 f." in text and "(naktinis)" in text and "2.0× lėčiau" in text
    assert snap.total_fraction == pytest.approx(600 / (600 + 4530))


# ── Q6–Q8: procesų radimas (tikras transcribe-file.sh) ──

@pytest.fixture
def jobs(env, fake_asr, monkeypatch):
    """Paleisti transcribe-file.sh darbus (netikras ASR „dirba" FAKE_ASR_SLEEP s); po testo — sustabdyti likusius."""
    env.write_conf(ARCHIVE_MP3=0)
    procs = []

    def start(*names, sleep="20", sec=2.0):
        monkeypatch.setenv("FAKE_ASR_SLEEP", sleep)
        for n in names:
            f = make_wav(env, n, sec=sec)
            procs.append(subprocess.Popen(["bash", str(TFILE), str(f)], stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, start_new_session=True))
            time.sleep(0.15)                                         # eilės tvarka
        return procs

    yield start
    for p in procs:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()


def test_q6_snapshot_finds_running_and_queued_in_order(env, P, jobs, fake_asr):
    jobs("vox_20261012_100000.wav", "vox_20261012_100100.wav", "vox_20261012_100200.wav", sec=3.0)
    assert wait_for(lambda: fake_asr.exists() and P.snapshot().running is not None
                    and len(P.snapshot().queued) == 2, 10)
    s = P.snapshot()
    assert s.running.name == "vox_20261012_100000.wav" and s.running.state == "running"
    assert [j.name for j in s.queued] == ["vox_20261012_100100.wav", "vox_20261012_100200.wav"]
    assert all(j.state == "queued" and j.audio_sec == pytest.approx(3.0, abs=0.01) for j in s.queued)
    assert not s.running.exact and s.running.left > 0 and s.left > s.running.left
    assert 0 <= s.running.fraction < 1 and P.summary(s).endswith("eilėje 2")


def test_q6_other_environment_jobs_invisible(env, P, jobs, tmp_path):
    """Kitos aplinkos (kitas <runtime>) darbai — ne mūsų eilė: nerodomi ir nestabdomi (tikri darbai testuose)."""
    other = tmp_path / "other"
    f = make_wav(env, "vox_20261012_090000.wav")
    e = {**os.environ, "DIKTATURA_RUN": str(other / "run"), "DIKTATURA_STATE": str(other / "state"),
         "DIKTATURA_ASR_CMD": f"bash {REPO}/tests/helpers/fake_asr.sh", "FAKE_ASR_SLEEP": "20"}
    p = subprocess.Popen(["bash", str(TFILE), str(f)], env=e, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    try:
        time.sleep(1.0)
        s = P.snapshot()
        assert s.running is None and s.queued == []
        assert P.stop_all(s).startswith("Sustabdyta: 0") and p.poll() is None    # svetimas darbas liko gyvas
    finally:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()


def test_q7_progress_file_used_for_running_job(env, P, jobs, fake_asr):
    jobs("vox_20261012_110000.wav", sec=4.0)
    assert wait_for(lambda: P.snapshot().running is not None, 10)
    f = env.recordings / "vox_20261012_110000.wav"
    now = time.time()
    P._write_json(P.progress_file(f), {**info("asr_them", 300, 1000, started=now - 120, phase_started=now - 30),
                                       "file": str(f), "model": "azuolas-ct2"})
    s = P.snapshot()
    assert s.running.exact and s.running.phase == "asr_them" and s.running.start == pytest.approx(now - 120)
    assert "Etapas 5/6: Transkribuojama: kolegos — 5:00 / 16:40 garso" == P.phase_text(s.running)


def test_q8_nightly_pending_files_listed(env, P, fake_asr, monkeypatch):
    env.write_conf(ARCHIVE_MP3=0)
    monkeypatch.setenv("FAKE_ASR_SLEEP", "20")
    for n in ("vox_20261012_080000.wav", "vox_20261012_080100.wav", "slack_20261012_080200.wav"):
        make_wav(env, n)
    p = subprocess.Popen(["bash", str(TPENDING)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    try:
        assert wait_for(lambda: P.snapshot().running is not None, 10)
        s = P.snapshot()
        assert s.pending_pids and s.running.name == "slack_20261012_080200.wav"   # glob tvarka: slack, vox
        assert [(j.name, j.state) for j in s.queued] == [("vox_20261012_080000.wav", "pending"),
                                                       ("vox_20261012_080100.wav", "pending")]
        assert s.waiting_night == []
    finally:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()


def test_q8_waiting_for_night_when_idle(env, P):
    make_wav(env, "vox_20261012_070000.wav")
    done = make_wav(env, "vox_20261012_070100.wav")
    done.with_suffix(".named.txt").write_text("[0:00:01] Tu: yra")
    sk = make_wav(env, "vox_20261012_070200.wav")
    sk.with_suffix(".skip").write_text("")
    s = P.snapshot()
    assert not s.active and [f.name for f in s.waiting_night] == ["vox_20261012_070000.wav"]
    assert "transkribuos naktinis" in "\n".join(P.describe(s))


# ── Q9–Q10: stabdymas ──

def test_q9_skip_current_next_continues(env, P, jobs, fake_asr):
    jobs("vox_20261012_120000.wav", "vox_20261012_120100.wav", sleep="30")
    assert wait_for(lambda: P.snapshot().running is not None and len(P.snapshot().queued) == 1, 10)
    s = P.snapshot()
    victim = s.running
    tmpd = Path(tempfile.gettempdir()) / f"{P.TMP_PREFIX}{P.descendants(victim.pid, P.scan_procs())[0]}-x"
    tmpd.mkdir()
    msg = P.skip_current(s)
    assert msg.startswith("Praleista: vox_20261012_120000.wav")
    assert wait_for(lambda: "garsas paliktas: vox_20261012_120000.wav" in env.log("transcribe"), 10)
    assert wait_for(lambda: (P.snapshot().running or victim).name == "vox_20261012_120100.wav", 10)
    assert (env.recordings / "vox_20261012_120000.wav").exists()
    assert not (env.recordings / "vox_20261012_120000.named.txt").exists()
    assert "vartotojas praleido" in env.log("transcribe") and not tmpd.exists()


def test_q9_skip_during_waveform_step_stops_the_job(env, P, jobs, fake_asr):
    """„Praleisti" bangos skaičiavimo metu (prieš ASR): darbas baigiamas, ASR nepaleidžiamas (anksčiau būtų tęsęs)."""
    jobs("vox_20261012_121000.wav", sleep="1", sec=900.0)           # 15 min — smailės skaičiuojamos ~1 s
    def peaks_running():
        s = P.snapshot()
        procs = P.scan_procs()
        return s.running is not None and any("diktatura.waveform" in " ".join(procs[d].cmd)
                                             for d in P.descendants(s.running.pid, procs) if d in procs)
    assert wait_for(peaks_running, 10, 0.01)
    assert P.skip_current(P.snapshot()).startswith("Praleista: vox_20261012_121000.wav")
    assert wait_for(lambda: "nutraukta (bangos skaičiavimo metu) — garsas paliktas: vox_20261012_121000.wav"
                    in env.log("transcribe"), 10)
    assert wait_for(lambda: not P.snapshot().active, 10)
    assert not fake_asr.exists() or "start" not in fake_asr.read_text()       # ASR nepradėtas
    assert (env.recordings / "vox_20261012_121000.wav").exists()


def test_q10_stop_all_running_queued_and_nightly(env, P, jobs, fake_asr):
    jobs("vox_20261012_130000.wav", "vox_20261012_130100.wav", "vox_20261012_130200.wav", sleep="30")
    assert wait_for(lambda: P.snapshot().running is not None and len(P.snapshot().queued) == 2, 10)
    msg = P.stop_all(P.snapshot())
    assert msg.startswith("Sustabdyta: 3 f.")
    assert wait_for(lambda: not P.snapshot().active, 10)
    time.sleep(1.0)
    starts = [ln for ln in fake_asr.read_text().splitlines() if ln.startswith("start")]
    assert len(starts) == 1                                          # laukę eilėje NEPRADĖJO (be užrakto)
    assert not list(env.recordings.glob("*.named.txt"))
    assert len(list(env.recordings.glob("*.wav"))) == 3 and "vartotojas sustabdė" in env.log("transcribe")


def test_q10_stop_all_when_idle_is_harmless(env, P):
    assert P.skip_current(P.snapshot()) == "Nėra vykdomos transkripcijos."
    assert P.stop_all(P.snapshot()).startswith("Sustabdyta: 0")


# ── Q11: ASR moduliai praneša etapus ──

class FakeSeg:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class FakeModel:
    def transcribe(self, audio_, **kw):
        dur = len(audio_) / 16000
        segs = [FakeSeg(0.2, dur / 2, " labas rytas"), FakeSeg(dur / 2, dur - 0.1, " kaip sekasi")]
        return iter(segs), type("I", (), {"duration": dur})()


def test_q11_named_module_reports_phases_and_history(env, P, monkeypatch):
    from diktatura.asr import transcribe_named
    env.write_conf(VAD_FILTER=0, ECHO_CANCEL=0)
    f = env.recordings / "vox_20261012_140000.wav"
    audio.write_wav(f, audio.speech(3.0, -20), audio.silence(3.0, -90))
    seen, adv, positions = [], [], []
    orig, orig_adv = P.Reporter._write, P.Reporter.advance

    def spy(self, force=False):
        seen.append((self.data["phase"], self.data["done"]))
        return orig(self, force)

    def spy_adv(self, done, pos=None):
        adv.append((self.data["phase"], done))
        if pos is not None:
            positions.append((self.data["phase"], pos))
        return orig_adv(self, done, pos)
    monkeypatch.setattr(P.Reporter, "_write", spy)
    monkeypatch.setattr(P.Reporter, "advance", spy_adv)
    monkeypatch.setattr(transcribe_named, "name_colleagues", lambda them, *a, **k: ([], 0))
    rc = transcribe_named.run([str(f), "--model", "azuolas-ct2"], get_model=lambda *a: FakeModel())
    assert rc == 0 and "labas rytas" in f.with_suffix(".named.txt").read_text()
    phases = [p for p, _ in seen]
    assert [p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]] == \
        ["start", "prep", "vad", "load", "asr_me", "asr_them", "names"]
    assert adv == [("asr_me", 1.5), ("asr_me", 2.9), ("asr_them", 1.5), ("asr_them", 2.9)]   # po kiekvieno segmento
    assert positions == adv                       # be VAD apkarpymo — originalo laikas sutampa (⏳ bangai)
    assert not P.progress_file(f).exists()
    [rec] = P.history()
    assert rec["kind"] == "named" and rec["audio"] == pytest.approx(3.0) and rec["speech"] == [3.0, 3.0]


def test_q11_named_source_mode_and_out_path(env, P, monkeypatch, tmp_path):
    """Sekamo aplanko failas (--source): bet koks vardas / formatas, mono; tekstas — į --out; „Tu" kanalas tuščias."""
    from diktatura.asr import transcribe_named
    env.write_conf(VAD_FILTER=1, ECHO_CANCEL=1)
    f = tmp_path / "telefonas" / "Įrašas 7.wav"
    f.parent.mkdir()
    audio.write_wav(f, audio.speech(3.0, -20))
    out = tmp_path / "out" / "Įrašas 7.wav.named.txt"
    out.parent.mkdir()
    got = {}

    def names(them, *a, **k):
        got["them"] = them
        return [(s0, s1, "Ona", tx) for s0, s1, tx in them], 0
    monkeypatch.setattr(transcribe_named, "name_colleagues", names)
    monkeypatch.setattr(transcribe_named.prefilter, "settings", lambda: _NoVad())
    rc = transcribe_named.run([str(f), "--source", "--out", str(out)], get_model=lambda *a: FakeModel())
    assert rc == 0 and not f.with_suffix(".named.txt").exists()
    assert out.read_text() == "[0:00:00] Ona: labas rytas\n[0:00:01] Ona: kaip sekasi\n"
    assert [tx for _, _, tx in got["them"]] == ["labas rytas", "kaip sekasi"]
    [rec] = P.history()
    assert rec["speech"][0] == 0                  # „Tu" kanalo nėra


class _NoVad:
    """VAD be modelio: viskas kalba, išskyrus visišką tylą (testui)."""
    enabled, trim, min_speech = True, False, 0.8

    def plan(self, x):
        import numpy as np
        from diktatura.audio.prefilter import ChannelPlan
        dur = len(x) / 16000
        if not len(x) or float(np.abs(x).max()) < 1e-4:
            return ChannelPlan(0.0, True, x[:0], [], [], dur)
        return ChannelPlan(dur, False, x, [(0.0, 0.0, dur)], [(0.0, dur)], dur)


def test_q11_mono_out_and_srt_paths(env, P, tmp_path):
    from diktatura.asr import transcribe
    env.write_conf(VAD_FILTER=0)
    f = env.recordings / "rec_20261012_140300.wav"
    audio.write_wav(f, audio.speech(2.0, -20))
    out, srt = tmp_path / "x.txt.retx", tmp_path / "x.srt.retx"
    assert transcribe.run([str(f), "--out", str(out), "--srt", str(srt)], get_model=lambda *a: FakeModel()) == 0
    assert out.read_text().startswith("labas rytas") and "-->" in srt.read_text()
    assert not f.with_suffix(".txt").exists() and not f.with_suffix(".srt").exists()


def test_q11_mono_module_reports_phases(env, P, monkeypatch):
    from diktatura.asr import transcribe
    env.write_conf(VAD_FILTER=0)
    f = env.recordings / "rec_20261012_140100.wav"
    audio.write_wav(f, audio.speech(2.0, -20))
    rc = transcribe.run([str(f), "--model", "medium"], get_model=lambda *a: FakeModel())
    assert rc == 0 and f.with_suffix(".txt").read_text().startswith("labas rytas")
    [rec] = P.history()
    assert rec["kind"] == "mono" and rec["model"] == "medium" and set(rec["phases"]) >= {"vad", "load", "asr"}


def test_q11_failed_module_leaves_no_progress(env, P):
    from diktatura.asr import transcribe_named
    env.write_conf(VAD_FILTER=0, ECHO_CANCEL=0)
    f = env.recordings / "vox_20261012_140200.wav"
    audio.write_wav(f, audio.speech(1.0, -20), audio.silence(1.0))

    def boom(*a):
        raise RuntimeError("modelis nepasikrovė")
    with pytest.raises(RuntimeError):
        transcribe_named.run([str(f)], get_model=boom)
    assert not P.progress_file(f).exists() and P.history() == []


def test_q12_cli_prints_state(env):
    r = subprocess.run([sys.executable, "-m", "diktatura.progress"], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and "niekas netranskribuojama" in r.stdout


# ── Q19: 🌊 banga ⏳ langelyje — kur smailės ir kiek apdorota ──

def test_q19_processed_secs_per_phase(P):
    def job(**info):
        return P.Job(pid=1, file=Path("/x/vox_a.wav"), state="running", info=info, left=10, total=20)
    named = dict(kind="named", skip=[False, False])
    assert P.processed_secs(job(phase="prep", **named), 100, 2) == [0, 0]
    assert P.processed_secs(job(phase="asr_me", pos=30, **named), 100, 2) == [30, 0]
    assert P.processed_secs(job(phase="asr_them", pos=40, **named), 100, 2) == [100, 40]
    assert P.processed_secs(job(phase="names", **named), 100, 2) == [100, 100]
    assert P.processed_secs(job(phase="asr_them", pos=500, **named), 100, 2) == [100, 100]   # ribojama trukme
    me_skipped = dict(kind="named", skip=[True, False])                     # tylus „Tu" / sekamas aplankas
    assert P.processed_secs(job(phase="asr_them", pos=40, **me_skipped), 100, 2) == [100, 40]
    assert P.processed_secs(job(phase="asr_them", pos=40, **me_skipped), 100, 1) == [40]     # mono banga
    assert P.processed_secs(job(phase="asr", pos=12, kind="mono"), 50, 1) == [12]
    assert P.processed_secs(job(phase="vad", kind="mono"), 50, 1) == [0]
    old = P.Job(pid=1, file=Path("/x/a.wav"), state="running", exact=False, left=30, total=40)  # sena versija
    assert P.processed_secs(old, 100, 2) == [25, 25]


def test_q19_peaks_file_from_progress_or_next_to_audio(env, P, monkeypatch):
    j = P.Job(pid=1, file=env.recordings / "vox_20261012_150000.wav", state="running")
    assert P.peaks_file(j) == env.recordings / "vox_20261012_150000.peaks"
    j.info = {"peaks": "/kitur/Įrašas 7.m4a.peaks"}
    assert P.peaks_file(j) == Path("/kitur/Įrašas 7.m4a.peaks")
    monkeypatch.setenv("DIKTATURA_PEAKS", "/out/x.peaks")                  # transcribe-file.sh perduoda Reporter'iui
    assert P.Reporter(env.recordings / "x.wav", "named").data["peaks"] == "/out/x.peaks"


# ── Q20: greitas kelias — be /proc skenavimo, kai eilė laisva ──

def test_q20_snapshot_fast_path_when_lock_free(env, P, monkeypatch, jobs, fake_asr):
    scans = []
    orig = P.scan_procs
    monkeypatch.setattr(P, "scan_procs", lambda: scans.append(1) or orig())
    assert not P.queue_busy()
    s = P.snapshot()
    assert not s.active and scans == [] and s.rates["n"] == 0                   # niekas neskenuota
    make_wav(env, "vox_20261019_100000.wav")
    assert [f.name for f in P.snapshot().waiting_night] == ["vox_20261019_100000.wav"]
    jobs("vox_20261019_100100.wav", sleep="5")
    assert wait_for(P.queue_busy, 5)
    s = P.snapshot()
    assert s.running is not None and scans                                       # užimta — skenuojama


# ── Q21: prognozės paklaida iš istorijos ──

def test_q21_prediction_error(P):
    def rec(audio, speech, asr, prep=0.03):
        return {"kind": "named", "model": "azuolas-ct2", "audio": audio, "speech": speech,
                "phases": {"prep": prep * audio, "vad": 0.02 * audio * 2, "load": 6.0, "asr": asr, "names": 0.05 * speech[1]}}
    assert P.prediction_error([]) == (None, 0)
    silent = [rec(10, [0.0, 0.0], 0.0) for _ in range(20)]                      # be kalbos — neįtraukiama
    assert P.prediction_error(silent) == (None, 0)
    steady = [rec(100, [40.0, 40.0], 120.0) for _ in range(8)]                 # RTF 1.5 — kaip numatyta
    err, n = P.prediction_error(silent + steady)
    assert n == 8 and err < 0.15                                                # ankstesni įrašai nuspėja tiksliai
    slow = steady + [rec(100, [40.0, 40.0], 360.0)]                             # paskutinis 3× lėtesnis
    err2, _ = P.prediction_error(slow, last=1)
    assert err2 > 0.5
    assert P.fmt_error(0.274, 10) == "ankstesnių 10 prognozių paklaida ±27 %" and P.fmt_error(None, 0) == ""
