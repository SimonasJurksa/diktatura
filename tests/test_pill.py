"""V1–V5: 💊 įrašymo indikatoriaus logika (ui.pill be GTK): lygiai iš rašomo wav, kas rodoma po įrašo, būsenos."""
import struct
import time
import wave
from pathlib import Path

import numpy as np
import pytest

import audio


@pytest.fixture
def pill(env):
    from diktatura.ui import pill as p
    return p


def growing(path):
    """Kaip VOX: wave.open — antraštė su 0 kadrų, duomenys pridedami (failas dar „rašomas")."""
    w = wave.open(str(path), "wb")
    w.setnchannels(2), w.setsampwidth(2), w.setframerate(16000)
    return w


def frames(left, right):
    return audio.stereo_pcm(left, right)


# ── V1: wav antraštė ──

def test_v1_wav_layout_python_and_ffmpeg_headers(env, pill, tmp_path):
    f = tmp_path / "a.wav"
    audio.write_wav(f, audio.speech(0.5), audio.silence(0.5))
    assert pill.wav_layout(f) == (44, 2, 16000, 2)
    fmt = struct.pack("<HHIIHH", 1, 2, 16000, 64000, 4, 16)
    lst = b"LIST" + struct.pack("<I", 26) + b"INFOISFT" + struct.pack("<I", 14) + b"Lavf58.76.100\0"
    hdr = b"RIFF" + struct.pack("<I", 0) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + lst + b"data" + struct.pack("<I", 0)
    g = tmp_path / "ffmpeg.wav"
    g.write_bytes(hdr + bytes(6400))
    assert pill.wav_layout(g) == (len(hdr), 2, 16000, 2)                  # ffmpeg LIST blokas praleidžiamas
    (tmp_path / "x.wav").write_bytes(b"ne wav")
    assert pill.wav_layout(tmp_path / "x.wav") is None and pill.wav_layout(tmp_path / "nėra.wav") is None


# ── V2: gyvi lygiai iš augančio failo ──

def test_v2_live_levels_read_only_new_chunks(env, pill, tmp_path):
    f = tmp_path / "vox_20261015_100000.wav"
    w = growing(f)
    w.writeframes(frames(audio.speech(1.0, -20), audio.silence(1.0, -70)))
    w._file.flush()
    lv = pill.LiveLevels(f)
    assert lv.poll() == 10 and lv.seconds == pytest.approx(1.0)
    assert all(l > -30 and r < -60 for l, r in lv.levels)                  # tu kalbi, kolegos tyli
    assert lv.poll() == 0                                                  # nieko naujo
    w.writeframes(frames(audio.silence(0.35, -70), audio.speech(0.35, -20)))
    w._file.flush()
    assert lv.poll() == 3 and lv.levels[-1][1] > -30                       # tik pilni gabalai; kolegos kalba
    w.writeframes(frames(audio.silence(0.05, -70), audio.speech(0.05, -20)))
    w._file.flush()
    assert lv.poll() == 1                                                  # likutis + nauja dalis = gabalas
    w.close()


def test_v2_long_file_starts_from_tail(env, pill, tmp_path):
    f = tmp_path / "slack_20261015_100000.wav"
    audio.write_wav(f, np.concatenate([audio.silence(20, -70), audio.speech(2, -20)]), audio.silence(22, -70))
    lv = pill.LiveLevels(f, keep=30)
    assert lv.poll() == 30 and lv.seconds == pytest.approx(22.0)
    assert lv.levels[-1][0] > -30 and lv.levels[0][0] < -60                # paskutinės 3 s
    assert pill.height(-60) == 0 and pill.height(-10) == 1 and 0.4 < pill.height(-35) < 0.6


# ── V3: kas rodoma po įrašo ──

def job(P, name, state="running", left=120.0, total=200.0):
    return P.Job(pid=1, file=Path("/x") / name, state=state, left=left, total=total)


def test_v3_after_text_cases(env, pill):
    from diktatura import progress as P
    rec = env.recordings / "vox_20261015_101500.wav"
    rec.write_bytes(b"x")
    cfg = {"AUTOTRANSCRIBE": True, "MODE": "immediate"}
    snap = P.Snapshot(now=0, running=job(P, rec.name))
    assert pill.after_text(rec, snap, cfg, 100, 101) == ("⏳ Transkribuojama 40 % · liko ~2 min", pytest.approx(0.4))
    snap = P.Snapshot(now=0, running=job(P, "kitas.wav"), queued=[job(P, rec.name, "queued")])
    assert pill.after_text(rec, snap, cfg, 100, 101)[0] == "⏳ Laukia eilėje · prieš jį 1 f."
    empty = P.Snapshot(now=0)
    assert pill.after_text(rec, empty, cfg, 100, 101) == ("⏳ Ruošiamasi transkribuoti…", None)
    assert pill.after_text(rec, empty, cfg, 100, 100 + pill.GONE_AFTER + 1) is None     # niekas neįvyko — slėpti
    night = {**cfg, "MODE": "deferred"}
    assert pill.after_text(rec, empty, night, 100, 102)[0].startswith("🌙")
    assert pill.after_text(rec, empty, night, 100, 100 + pill.DONE_SHOW + 1) is None
    assert pill.after_text(rec, empty, {**cfg, "AUTOTRANSCRIBE": False}, 100, 101)[0].startswith("⏸")
    rec.with_suffix(".named.txt").write_text("[0:00:01] Tu: labas\n")
    assert pill.after_text(rec, empty, cfg, 100, 101)[0].startswith("✅ Tekstas paruoštas")
    rec.with_suffix(".named.txt").unlink()
    rec.unlink()
    assert pill.after_text(rec, empty, cfg, 100, 101) is None              # per trumpas — ištrintas


# ── V4–V5: būsenų mašina ──

class FakeView:
    def __init__(self):
        self.calls, self.mode = [], None

    def show_rec(self, src, sec, levels):
        self.calls.append(("rec", src, round(sec, 1), len(levels)))
        self.mode = "rec"

    def show_after(self, text, frac):
        self.calls.append(("after", text, frac))
        self.mode = "after"

    def hide(self):
        self.calls.append(("hide",))
        self.mode = None


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def test_v4_short_blip_never_shown_long_recording_shown_then_night(env, pill):
    from diktatura import progress as P
    rec = env.recordings / "vox_20261015_102000.wav"
    w = growing(rec)
    state = {"cur": ("vox", rec)}
    clk, view = Clock(), FakeView()
    cfg = {"REC_PILL": True, "AUTOTRANSCRIBE": True, "MODE": "deferred"}
    c = pill.PillController(view, rec_fn=lambda: state["cur"], snap_fn=lambda: P.Snapshot(now=0),
                            cfg_fn=lambda: cfg, clock=clk)
    w.writeframes(frames(audio.speech(1.0, -20), audio.silence(1.0)))
    w._file.flush()
    c.tick()
    assert view.calls[-1] == ("hide",) and c.state == "rec"                # < 1.5 s — dar nerodoma
    w.writeframes(frames(audio.speech(1.0, -20), audio.silence(1.0)))
    w._file.flush()
    c.tick()
    assert view.calls[-1] == ("rec", "vox", 2.0, 20)
    w.close()
    state["cur"] = None
    clk.t += 1
    c.tick()
    assert c.state == "after" and view.calls[-1][0] == "after" and view.calls[-1][1].startswith("🌙")
    clk.t += pill.DONE_SHOW + 1
    c.tick()
    assert c.state == "idle" and view.calls[-1] == ("hide",)


def test_v5_dismiss_and_setting_off(env, pill):
    from diktatura import progress as P
    rec = env.recordings / "vox_20261015_103000.wav"
    audio.write_wav(rec, audio.speech(3.0), audio.silence(3.0))
    state = {"cur": ("slack", rec)}
    cfg = {"REC_PILL": True, "AUTOTRANSCRIBE": True, "MODE": "immediate"}
    clk, view = Clock(), FakeView()
    c = pill.PillController(view, rec_fn=lambda: state["cur"], snap_fn=lambda: P.Snapshot(now=0),
                            cfg_fn=lambda: cfg, clock=clk)
    c.tick()
    assert view.calls[-1][0] == "rec" and view.calls[-1][1] == "slack"
    c.dismiss()
    c.tick()
    assert view.calls[-1] == ("hide",)                                     # ✕ — šiam įrašui nebe
    state["cur"] = None
    c.tick()
    assert view.calls[-1] == ("hide",) and c.state == "idle"
    rec2 = env.recordings / "vox_20261015_104000.wav"
    audio.write_wav(rec2, audio.speech(3.0), audio.silence(3.0))
    state["cur"] = ("vox", rec2)
    c.tick()
    assert view.calls[-1][0] == "rec"                                      # kitas įrašas — vėl rodoma
    cfg["REC_PILL"] = False
    clk.t += 10                                                            # nustatymai perskaitomi kas ~3 s
    c.tick()
    assert view.calls[-1] == ("hide",)
