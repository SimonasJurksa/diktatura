"""C. VOX vartai (VoxGate) — gryna logika su sintetiniais lygiais, be mikrofono."""
import pytest

import audio
from diktatura import config
from diktatura.audio.vox import CALIB, PREROLL, VoxGate, rms_db

QUIET = -70.0       # kambario triukšmas
LOUD = -20.0        # kalba


@pytest.fixture
def cfg(env):
    return dict(config.load())


def feed(gate, levels):
    return [gate.step(lv) for lv in levels]


def calibrated(cfg, **over):
    g = VoxGate({**cfg, **over})
    assert set(feed(g, [QUIET] * CALIB)) == {"idle"}
    return g


def test_rms_db_of_synthetic_speech_matches_level():
    lv = audio.chunk_levels(audio.speech(2, -20))
    assert all(-26 < x < -14 for x in lv)
    import numpy as np
    assert rms_db(np.zeros(0)) == -120.0


def test_c1_silence_never_opens(cfg):
    g = VoxGate(cfg)
    assert set(feed(g, [QUIET] * 600)) == {"idle"}


def test_c2_speech_opens_after_calibration(cfg):
    g = calibrated(cfg)
    levels = audio.chunk_levels(audio.speech(1.0, -20))
    out = feed(g, levels)
    assert out[0] == "open" and set(out[1:]) == {"write"}


def test_c3_sound_during_calibration_does_not_open(cfg):
    g = VoxGate(cfg)
    assert set(feed(g, [LOUD] * 5 + [QUIET] * (CALIB - 5))) == {"idle"}
    assert set(feed(g, [QUIET] * 30)) == {"idle"}        # po kalibracijos tyla vis dar neatidaro
    assert feed(g, [LOUD])[0] == "open"                 # o kalba — atidaro


@pytest.mark.parametrize("silence_sec", [2, 5])
def test_c4_closes_exactly_after_silence_seconds(cfg, silence_sec):
    g = calibrated(cfg, VOX_SILENCE_SEC=silence_sec)
    feed(g, [LOUD] * 10)
    n = int(silence_sec * 10)
    assert set(feed(g, [QUIET] * (n - 1))) == {"write"}  # < tylos sekundžių — dar rašo
    assert feed(g, [QUIET]) == ["close"]                # = tylos sekundžių — uždaro


def test_c4_speech_resets_silence_counter(cfg):
    g = calibrated(cfg, VOX_SILENCE_SEC=2)
    feed(g, [LOUD] * 3 + [QUIET] * 15 + [LOUD] + [QUIET] * 19)
    assert g.recording
    assert feed(g, [QUIET]) == ["close"]


def test_c5_hysteresis_quiet_speech_keeps_open_but_does_not_open(cfg):
    g = calibrated(cfg)                                 # triukšmas −70: atsidaro > −55, laiko > −62
    between = QUIET + (cfg["VOX_CLOSE_MARGIN"] + cfg["VOX_OPEN_MARGIN"]) / 2
    assert set(feed(g, [between] * 30)) == {"idle"}     # per tylu pradėti
    feed(g, [LOUD])
    assert set(feed(g, [between] * 200)) == {"write"}   # bet tęsti — užtenka (nenukerpa sakinio)


def test_c5_fixed_mode_uses_gate_db(cfg):
    g = VoxGate({**cfg, "VOX_ADAPTIVE": False, "VOX_GATE_DB": -35.0})
    assert feed(g, [-30.0])[0] == "open"                # fiksuotame režime kalibracijos nėra
    assert set(feed(g, [-40.0] * 100)) == {"write"}     # išlaikymas = −35 − 12 = −47
    assert "close" in feed(g, [-50.0] * 60)


def test_c6_blip_shorter_than_min_is_too_short(cfg):
    g = calibrated(cfg, VOX_MIN_SEC=1.5, VOX_SILENCE_SEC=5)
    out = feed(g, [LOUD] * 3 + [QUIET] * 50)            # 0.3 s kosulys + 5 s tylos
    assert out[-1] == "close"
    assert g.duration > 5                               # failas ilgas (uodega) ...
    assert not g.long_enough()                          # ... bet garso tik 0.3 s -> trinamas


def test_c6_real_utterance_long_enough(cfg):
    g = calibrated(cfg, VOX_MIN_SEC=1.5, VOX_SILENCE_SEC=5)
    feed(g, [LOUD] * 10 + [QUIET] * 5 + [LOUD] * 10 + [QUIET] * 50)
    assert g.long_enough() and g.voiced_duration == pytest.approx(2.5)


def test_c7_preroll_counted_in_duration(cfg):
    g = calibrated(cfg, VOX_SILENCE_SEC=1)
    feed(g, [LOUD] * 10 + [QUIET] * 10)
    assert g.duration == pytest.approx((PREROLL + 20) / 10)


def test_config_change_applies_to_running_gate(cfg):
    g = calibrated(cfg, VOX_SILENCE_SEC=10)
    feed(g, [LOUD] * 5 + [QUIET] * 10)
    g.update_config({**cfg, "VOX_SILENCE_SEC": 2})      # daemon'as perskaito config kas ~5 s
    assert "close" in feed(g, [QUIET] * 11)
