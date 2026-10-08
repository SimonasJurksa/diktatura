"""H. VAD pre-filtras (diktatura.audio.prefilter + ASR modulių vartai). Silero VAD ateina su faster-whisper.

Tyla / pypsėjimas — sintetiniai; kalba — LT fixture'ai (make fixtures; be jų tie testai praleidžiami).
„Ąžuolas nekrautas" tikrinama paleidžiant ASR modulį su NEEGZISTUOJANČIU modeliu: jei VAD praleido — sėkmė,
jei bandytų krauti — lūžtų.
"""
import os
import subprocess
import sys

import numpy as np
import pytest

import audio
import lt
from diktatura import config
from diktatura.audio import prefilter

SR = 16000
NO_MODEL = "/nonexistent/model"


@pytest.fixture
def speech():
    c = lt.clips()
    if not c:
        pytest.skip("nėra LT fixture'ų — make fixtures")
    return lt.decode(c[0][0])


def run_asr(module, wav, *extra):
    return subprocess.run([sys.executable, "-m", f"diktatura.asr.{module}", str(wav), "--model", NO_MODEL, *extra],
                          capture_output=True, text=True, timeout=120)


# ── grynos funkcijos ──

def test_merge_trim_remap_roundtrip():
    assert prefilter.merge([(5, 6), (0, 1), (0.8, 2), (6, 7)]) == [(0, 2), (5, 7)]
    x = np.arange(10 * SR, dtype=np.float32)
    spans = [(1.0, 2.0), (5.0, 5.5), (8.0, 10.0)]
    trimmed, mapping = prefilter.trim(x, spans)
    assert len(trimmed) == int(3.5 * SR)
    for t in (0.0, 0.3, 0.999, 1.2, 1.49, 2.0, 3.4):                  # kiekvienas apkarpyto garso taškas ...
        orig = prefilter.remap(t, mapping)
        assert trimmed[int(round(t * SR))] == x[int(round(orig * SR))]    # ... rodo į tą patį originalo mėginį
    assert prefilter.remap(1.2, mapping) == pytest.approx(5.2)
    assert prefilter.speech_seconds(spans) == pytest.approx(3.5)


def test_plan_disabled_passes_everything():
    x = audio.silence(3)
    p = prefilter.plan(x, 0.8, 0.2, enabled=False)
    assert not p.skip and len(p.audio) == len(x) and p.to_original(1.5) == pytest.approx(1.5)


# ── H1–H2: ne kalba -> praleista, modelis nekrautas ──

def test_h1_silence_skipped(env):
    assert prefilter.plan(audio.silence(5), 0.8, 0.2).skip
    wav = env.recordings / "vox_20260101_100000.wav"
    audio.write_wav(wav, audio.silence(5), audio.silence(5))
    r = run_asr("transcribe_named", wav)
    assert r.returncode == 0, r.stderr[-1500:]
    assert "modelis nekraunamas" in r.stdout and wav.with_suffix(".named.txt").read_text() == ""


def test_h2_beep_and_noise_skipped(env):
    for sig in (audio.tone(5, 1000, -20), audio.noise(5, -30)):
        p = prefilter.plan(sig, 0.8, 0.2)
        assert p.skip, f"ne kalba palaikyta kalba: {p.speech_sec:.1f}s"
    wav = env.recordings / "rec_20260101_100000.wav"
    audio.write_wav(wav, audio.tone(5, 1000, -20))
    r = run_asr("transcribe", wav)
    assert r.returncode == 0, r.stderr[-1500:]
    assert wav.with_suffix(".txt").read_text() == "" and "modelis nekraunamas" in r.stdout


def test_h1_empty_result_deleted_by_pipeline(env):
    """Visas kelias: transcribe-file.sh + tikras ASR modulis (VAD praleidžia) + DELETE_EMPTY -> įrašas ištrintas."""
    from testenv import REPO
    env.write_conf(DELETE_EMPTY=1)
    wav = env.recordings / "vox_20260101_110000.wav"
    audio.write_wav(wav, audio.silence(3), audio.tone(3, 1000, -25))
    r = subprocess.run(["bash", str(REPO / "bin" / "transcribe-file.sh"), str(wav)], capture_output=True, text=True,
                       timeout=120, env={**os.environ, "DIKTATURA_MODEL": NO_MODEL})
    assert r.returncode == 0, r.stdout + r.stderr
    assert not wav.exists() and "tuščias tekstas" in env.log("transcribe")


# ── H3–H4: kalba praeina, apkarpoma, laikai atgal į originalą ──

def test_h3_speech_passes_and_trimmed_is_shorter(speech):
    x = np.concatenate([audio.silence(6), speech, audio.silence(9), speech, audio.silence(4)])
    p = prefilter.plan(x, 0.8, 0.2)
    assert not p.skip
    assert len(p.audio) < 0.6 * len(x)
    one = prefilter.speech_seconds(prefilter.speech_spans(speech, 0.2))  # kiek kalbos viename klipe
    assert abs(p.speech_sec - 2 * one) < 0.5                            # tyla tarp jų neprideda, kalba neprarandama


def test_h4_remap_puts_speech_back_in_original_time(speech):
    gap1, gap2 = 7.0, 12.0
    x = np.concatenate([audio.silence(gap1), speech, audio.silence(gap2), speech])
    p = prefilter.plan(x, 0.8, 0.2)
    clip_onset = prefilter.speech_spans(speech, 0.0)[0][0]               # kada klipe prasideda kalba
    b_start = gap1 + len(speech) / SR + gap2 + clip_onset              # antro klipo kalbos pradžia originale
    span_b = min(p.spans, key=lambda s: abs(s[0] + 0.2 - b_start))
    t_in_trim = next(t0 for t0, o0, d in p.mapping if o0 == pytest.approx(span_b[0]))
    assert abs(p.to_original(t_in_trim + 0.2) - b_start) < 0.3


# ── H5: tylus R kanalas ──

def test_h5_silent_right_channel_skipped_left_kept(speech):
    left = np.concatenate([speech, audio.silence(2)])
    right = audio.silence(len(left) / SR)
    assert not prefilter.plan(left, 0.8, 0.2).skip
    assert prefilter.plan(right, 0.8, 0.2).skip


# ── H6: nustatymai keičia elgseną ──

def test_h6_settings_change_behaviour(env, speech):
    sec = len(speech) / SR
    config.save({"VAD_MIN_SPEECH_SEC": "0.8"})
    vs = prefilter.settings()
    assert vs.enabled and not vs.trim and not vs.plan(speech).skip
    config.save({"VAD_MIN_SPEECH_SEC": "10"})                           # daugiau nei klipe kalbos
    assert sec < 10 and prefilter.settings().plan(speech).skip
    config.save({"VAD_FILTER": "0"})
    assert not prefilter.settings().plan(audio.silence(2)).skip         # išjungtas — nieko nepraleidžia
    config.save({"VAD_FILTER": "1", "VAD_MIN_SPEECH_SEC": "0.8", "VAD_TRIM": "1", "VAD_PAD_SEC": "0"})
    tight = prefilter.settings().plan(speech)
    config.save({"VAD_PAD_SEC": "1"})
    loose = prefilter.settings().plan(speech)
    assert len(loose.audio) > len(tight.audio)                           # didesnė paraštė — ilgesnis garsas


def test_trim_off_by_default_passes_whole_channel_but_still_gates(env, speech):
    x = np.concatenate([audio.silence(5), speech, audio.silence(5)])
    vs = prefilter.settings()
    p = vs.plan(x)
    assert not vs.trim and not p.skip and len(p.audio) == len(x) and p.to_original(12.3) == pytest.approx(12.3)
    assert vs.plan(audio.silence(5)).skip                               # vartai veikia ir be apkarpymo
    config.save({"VAD_TRIM": "1"})
    assert len(prefilter.settings().plan(x).audio) < len(x)


def test_prefilter_cli_reports_channels(env, speech, tmp_path):
    wav = tmp_path / "s.wav"
    audio.write_wav(wav, np.concatenate([speech, audio.silence(1)]), audio.silence(len(speech) / SR + 1))
    r = subprocess.run([sys.executable, "-m", "diktatura.audio.prefilter", str(wav)], capture_output=True, text=True)
    import json
    d = json.loads(r.stdout)
    assert [c["skip"] for c in d["channels"]] == [False, True]
