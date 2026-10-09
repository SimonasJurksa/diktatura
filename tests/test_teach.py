"""G9. Mokymasis iš pataisymo (diktatura.speakers.teach): kanalo parinkimas, „Tu" / vardas, per mažai kalbos.

Kalba — LT fixture'ai (make fixtures; be jų testai praleidžiami), VAD tikras (Silero), embedding — netikras.
"""
import sys

import numpy as np
import pytest

import audio
import lt
from diktatura.speakers import speakerlib as sl
from diktatura.speakers import store
from diktatura.speakers import teach

SR = 16000
FAKE = np.ones(8, dtype=np.float32) / np.sqrt(8)


@pytest.fixture
def speech():
    c = lt.clips()
    if not c:
        pytest.skip("nėra LT fixture'ų — make fixtures")
    return lt.decode(c[0][0])


def recording(env, left, right=None, text="[0:00:00] Darius: dar nespėjau\n[0:00:10] Matas: ir\n"):
    audio.write_wav(env.recordings / "vox_20261009_120000.wav", left, right)
    f = env.recordings / "vox_20261009_120000.named.txt"
    f.write_text(text, encoding="utf-8")
    return f


def pad(x, sec=10):
    out = np.zeros(SR * sec, dtype=np.float32)
    out[SR:SR + len(x[:SR * (sec - 2)])] = x[:SR * (sec - 2)]
    return out


def fake_embed(calls):
    def emb(x):
        calls.append(len(x) / SR)
        return FAKE
    return emb


def test_g9_owner_learned_from_right_channel(env, speech):
    """Kalbėjai per telefoną (R kanalas): pataisymas „Tu" -> tavo balso pavyzdys iš R kanalo kalbos."""
    f = recording(env, np.zeros(SR * 10, dtype=np.float32), pad(speech))
    calls = []
    r = teach.teach(f, 0, " tu ", embed=fake_embed(calls))
    assert r["ok"] and r["who"] == "Tu" and r["channel"] == "R" and r["count"] == 1
    assert store.owner_count() == 1 and store.counts() == {}
    assert store.load_owner_raw()[0]["src"] == "vox_20261009_120000@0"
    assert calls and calls[0] <= min(len(speech) / SR, 8) + 0.5                  # tik kalba, be tylos
    np.testing.assert_allclose(sl.load_owner()[0], FAKE, atol=1e-6)


def test_g9_colleague_learned_from_left_when_right_silent(env, speech):
    f = recording(env, pad(speech), np.zeros(SR * 10, dtype=np.float32))
    r = teach.teach(f, 0, "Matas", embed=fake_embed([]))
    assert r["ok"] and r["channel"] == "L" and store.counts() == {"Matas": 1} and store.owner_count() == 0


def test_g9_mono_and_too_little_speech(env, speech):
    f = recording(env, pad(speech))
    assert teach.teach(f, 0, "Rūta", embed=fake_embed([]))["channel"] == "mono"
    short = np.zeros(SR * 10, dtype=np.float32)
    short[SR:SR + SR // 2] = speech[SR:SR + SR // 2]                              # ~0.5 s kalbos
    f = recording(env, short, short)
    calls = []
    r = teach.teach(f, 0, "Rūta", embed=fake_embed(calls))
    assert not r["ok"] and "per mažai kalbos" in r["error"] and not calls
    assert store.counts() == {"Rūta": 1}                                           # nieko nepridėta


def test_g9_no_audio_or_line(env):
    f = env.recordings / "vox_20261009_120000.named.txt"
    f.write_text("[0:00:00] Darius: labas\n", encoding="utf-8")
    assert not teach.teach(f, 0, "Tu", embed=fake_embed([]))["ok"]                 # garso nėra
    audio.write_wav(env.recordings / "vox_20261009_120000.wav", np.zeros(SR, dtype=np.float32))
    assert not teach.teach(f, 5, "Tu", embed=fake_embed([]))["ok"]                 # eilutės nėra


def test_g9_cli_exit_codes(env, speech, monkeypatch, capsys):
    """UI skaito išėjimo kodą: 0 — išmokta, 3 — per mažai kalbos, 2 — nėra garso / eilutės."""
    monkeypatch.setattr(sl, "compute_embedding", lambda x: FAKE)
    f = recording(env, np.zeros(SR * 10, dtype=np.float32), pad(speech))
    for idx, code in ((0, 0), (1, 3), (7, 2)):
        monkeypatch.setattr(sys, "argv", ["teach", str(f), str(idx), "Tu"])
        with pytest.raises(SystemExit) as e:
            teach.main()
        assert e.value.code == code, capsys.readouterr().out
