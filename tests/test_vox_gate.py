"""C. VOX vartai (VoxGate) — gryna logika su sintetiniais lygiais, be mikrofono."""
import pytest

import audio
from diktatura import config
from diktatura.audio.vox import CALIB, PREROLL, REC_NF_WINDOW, VoxGate, rms_db

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
    # bet tęsti — užtenka (nenukerpa sakinio); < 10 s: idealiai pastovus garsas ilgiau jau laikomas fonu (C9)
    assert set(feed(g, [between] * (REC_NF_WINDOW - 5))) == {"write"}


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


# ── C9: pasenusios triukšmo grindys (2026-10-13: grindys −92 dB, ventiliatorius −66 dB -> 6 val. „įrašas") ──

FAN = -66.0


def wobble(level, n, seed=1):
    import random
    r = random.Random(seed)
    return [level + r.uniform(-0.5, 0.5) for _ in range(n)]


def talk(n, seed=2):
    """Kalba su pauzėmis (tikra kalba: 100 ms gabalų lygiai skiriasi 10+ dB, pauzės nukrenta iki fono)."""
    import random
    r = random.Random(seed)
    return [r.choice([-25.0, -30.0, -35.0, -40.0, -45.0, FAN]) for _ in range(n)]


def stale(cfg, **over):
    g = VoxGate({**cfg, **over})
    feed(g, [-92.0] * CALIB)                            # išmokta, kai mikrofonas buvo nutilęs
    return g


def test_c9_stale_floor_background_only_closes_and_is_too_short(cfg):
    g = stale(cfg)
    out = feed(g, wobble(FAN, 600))
    assert out[0] == "open"                             # fonas virš pasenusių grindų — atsidaro...
    assert out.index("close") == REC_NF_WINDOW          # ...bet po 10 s grindys pakeliamos ir užsidaro
    assert not g.long_enough()                          # garso nebuvo -> failas bus ištrintas
    assert g.refloored[0] == -92.0 and abs(g.refloored[1] - FAN) < 1
    assert "open" not in out[REC_NF_WINDOW + 1:]        # toliau fonas nebeatidaro


def test_c9_stale_floor_speech_then_background_closes_after_silence(cfg):
    g = stale(cfg, VOX_SILENCE_SEC=5)
    out = feed(g, talk(400) + wobble(FAN, 300))
    c = out.index("close")
    assert 400 + 40 <= c <= 400 + 60                    # ~5 s po kalbos pabaigos, kaip įprastai
    assert g.long_enough() and g.voiced_duration > 35   # kalba išsaugoma


def test_c9_correct_floor_conversation_never_refloors(cfg):
    g = VoxGate(cfg)
    feed(g, wobble(FAN, CALIB))
    out = feed(g, [LOUD] + talk(1200, seed=5))          # 2 min pokalbio su pauzėmis
    assert "close" not in out and g.refloored is None


def test_c9_floor_relaxes_again_when_room_gets_quiet(cfg):
    g = stale(cfg)
    feed(g, wobble(FAN, 200))
    assert abs(g.nf - FAN) < 1
    feed(g, [QUIET] * 60)                               # ventiliatorius nurimo (budint grindys vėl mokomos)
    assert g.nf < FAN - 3 and feed(g, [-45.0])[0] == "open"


def test_c9_fixed_mode_does_not_adapt(cfg):
    g = VoxGate({**cfg, "VOX_ADAPTIVE": False, "VOX_GATE_DB": -35.0})
    feed(g, [-30.0])
    assert set(feed(g, [-40.0] * 300)) == {"write"} and g.refloored is None   # vartotojo slenkstis — šventas


def test_c9_recalibrate_needs_calibration_again(cfg):
    g = calibrated(cfg)
    feed(g, [LOUD] * 5)
    g.recalibrate()                                     # kitas įrenginys
    assert not g.recording and set(feed(g, [LOUD] * (CALIB - 1))) == {"idle"}
    assert feed(g, [LOUD])[0] == "idle"                 # kalibruojasi pagal naują garsą (LOUD = fonas)
