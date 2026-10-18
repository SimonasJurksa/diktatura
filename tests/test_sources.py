"""T1–T8: sekami aplankai (diktatura.sources) — telefono / laikrodžio / studijos įrašai, atskiri tekstai, tavo failai
nepaliečiami; eilė (transcribe-file.sh <garsas> <bazė>, transcribe-pending.sh --sources), timer'is, trynimas, doctor."""
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest

import audio
from testenv import REPO

TFILE = REPO / "bin" / "transcribe-file.sh"
TPENDING = REPO / "bin" / "transcribe-pending.sh"


@pytest.fixture
def S(env):
    from diktatura import sources
    return sources


@pytest.fixture
def phone(tmp_path):
    d = tmp_path / "Telefonas"
    d.mkdir()
    return d


def rec(path, sec=1.0, age=3600, stereo=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    audio.write_wav(path, audio.speech(sec, -20), audio.silence(sec) if stereo else None)
    t = time.time() - age
    os.utime(path, (t, t))
    return path


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest(), Path(p).stat().st_mtime


# ── T1: aplankų sąrašas ──

def test_t1_add_update_remove_and_guards(env, S, phone, tmp_path):
    a = S.add("Telefonas", phone)
    assert a.id == "telefonas" and a.enabled and a.since == 0 and S.load() == [a]
    other = tmp_path / "laikrodis"
    other.mkdir()
    b = S.add("Telefonas", other, recursive=True, include_existing=False)
    assert b.id == "telefonas-2" and b.recursive and b.since > 0             # tas pats vardas — kitas id
    assert a.out_dir == env.data / "sources" / "telefonas"
    with pytest.raises(ValueError, match="jau sekamas"):
        S.add("Kitas", phone)
    with pytest.raises(ValueError, match="Nėra tokio aplanko"):
        S.add("X", tmp_path / "nėra")
    with pytest.raises(ValueError, match="duomenų"):
        S.add("X", env.recordings)
    with pytest.raises(ValueError, match="pavadinimą"):
        S.add("  ", other)
    assert S.update("telefonas", enabled=False, path="/kitur").enabled is False
    assert S.get("telefonas").path == str(phone.resolve())                  # kelias nekeičiamas per update
    S.remove("telefonas")
    assert [s.id for s in S.load()] == ["telefonas-2"]
    assert S.slug("Studijos Ąžuolas mic") == "studijos-azuolas-mic" and S.slug("!!!") == "aplankas"
    assert S.short_path(Path.home() / "Telefonas") == "~/Telefonas" and S.short_path("/mnt/x") == "/mnt/x"
    (env.config / "sources.json").write_text("sugadinta")
    assert S.load() == []


# ── T2: kurie failai laukia ──

def test_t2_scan_filters_pending_since_recursive_stable(env, S, phone):
    good = rec(phone / "Recording_20261014_101500.m4a.wav")
    rec(phone / ".paslėptas.wav")
    rec(phone / "siunčiamas.wav.part")
    (phone / "pastabos.txt").write_text("ne garsas")
    sub = rec(phone / "2026" / "spalis.mp3.wav")
    fresh = rec(phone / "ką_tik.wav", age=5)                                # dar sinchronizuojamas
    src = S.add("Telefonas", phone)
    assert [p.name for p in S.scan(src)] == ["Recording_20261014_101500.m4a.wav", "ką_tik.wav"]
    assert [a for a, _ in S.pending(src)] == [good]
    assert S.pending(src, now=time.time() + 120)[-1][0] == fresh            # po minutės — jau ir jis
    S.update(src.id, recursive=True)
    src = S.get(src.id)
    pend = dict(S.pending(src))
    assert sub in pend and pend[sub] == src.out_dir / f"2026{S.SUB_SEP}spalis.mp3.wav"
    S.with_suffix(pend[good], ".named.txt").parent.mkdir(parents=True, exist_ok=True)
    S.with_suffix(pend[good], ".named.txt").write_text("[0:00:01] Tu: labas\n")
    S.with_suffix(pend[sub], ".skip").write_text("")
    assert S.pending(src) == [] and S.counts(src) == {"files": 3, "texts": 1, "pending": 0}
    S.update(src.id, enabled=False)
    assert S.pending(S.get(src.id), now=time.time() + 120) == []


def test_t2_only_new_files_when_existing_excluded(env, S, phone):
    rec(phone / "senas.wav", age=7200)
    src = S.add("Telefonas", phone, include_existing=False)
    assert S.pending(src, now=time.time() + 120) == []
    new = rec(phone / "naujas.wav", age=0)
    assert [a for a, _ in S.pending(src, now=time.time() + 120)] == [new]


# ── T3: įrašymo laikas ir metaduomenys ──

def test_t3_recorded_time_from_name_metadata_or_mtime(env, S, phone):
    assert S.time_from_name("Voice 2026-10-14 10.15.00.m4a") == datetime(2026, 10, 14, 10, 15)
    assert S.time_from_name("VoiceNote_20261014T101500.ogg") == datetime(2026, 10, 14, 10, 15)
    assert S.time_from_name("20261399_101500.m4a") is None and S.time_from_name("Įrašas 7.m4a") is None
    plain = rec(phone / "Įrašas 7.wav")
    tagged = phone / "Naujas įrašas.m4a"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(plain), "-metadata",
                    "creation_time=2026-10-01T08:30:00Z", str(tagged)], check=True)
    assert S.recorded_time(tagged).date() == datetime(2026, 10, 1).date()   # iš metaduomenų (vietinis laikas)
    assert S.recorded_time(plain) == datetime.fromtimestamp(plain.stat().st_mtime)
    src = S.add("Telefonas", phone)
    base = S.out_base(src, tagged)
    S.write_meta(src, tagged, base)
    meta = json.loads(S.with_suffix(base, ".src.json").read_text())
    assert meta["audio"] == str(tagged.resolve()) and meta["source"] == "telefonas"
    txt = S.with_suffix(base, ".named.txt")
    txt.write_text("[0:00:01] Ona: labas\n")
    from diktatura import sessions
    assert sessions.audio_for(txt) == tagged.resolve()                      # garsas — tavo aplanke
    assert sessions.session_dt(txt).date() == datetime(2026, 10, 1).date()
    assert sessions.base_name(txt.name) == "Naujas įrašas.m4a" and S.meta_for(txt)["source"] == "telefonas"
    assert S.source_of_audio(tagged) == (src, base) and S.source_of_audio(env.recordings / "x.wav") is None


# ── T4: transkripcija — tavo failas nepaliečiamas ──

def test_t4_transcribe_file_with_out_base_keeps_audio(env, S, phone, fake_asr):
    env.write_conf(ARCHIVE_MP3=1, DELETE_EMPTY=1)
    a = rec(phone / "Įrašas 7.wav", stereo=True)
    before = digest(a)
    src = S.add("Telefonas", phone)
    base = S.out_base(src, a)
    r = env.sh("bash", TFILE, a, base)
    assert r.returncode == 0, r.stdout + r.stderr
    assert S.with_suffix(base, ".named.txt").read_text() == "[0:00:01] Tu: labas rytas"
    assert S.with_suffix(base, ".peaks").exists() and digest(a) == before           # garsas — nepaliestas
    assert sorted(p.name for p in phone.iterdir()) == ["Įrašas 7.wav"]            # jokio mp3, jokių tekstų
    assert "→ " + str(src.out_dir) in env.log("transcribe") or str(src.out_dir) in env.log("transcribe")


def test_t4_empty_or_zero_byte_source_is_skipped_not_deleted(env, S, phone, fake_asr, monkeypatch):
    env.write_conf(DELETE_EMPTY=1)
    src = S.add("Telefonas", phone)
    a = rec(phone / "triukšmas.wav")
    monkeypatch.setenv("FAKE_ASR_TEXT", " \n")
    assert env.sh("bash", TFILE, a, S.out_base(src, a)).returncode == 0
    assert a.exists() and S.with_suffix(S.out_base(src, a), ".skip").exists()
    assert not S.with_suffix(S.out_base(src, a), ".named.txt").exists()
    z = phone / "nulis.wav"
    z.write_bytes(b"")
    assert env.sh("bash", TFILE, z, S.out_base(src, z)).returncode == 0
    assert z.exists() and S.with_suffix(S.out_base(src, z), ".skip").exists()


# ── T5: eilė (naktinis / timer'is) ──

def test_t5_pending_script_sources_and_modes(env, S, phone, fake_asr):
    from diktatura import progress
    env.write_conf(ARCHIVE_MP3=0, MODE="deferred")
    rec(phone / "a.wav")
    b = rec(phone / "sub" / "b.wav")
    vox = rec(env.recordings / "vox_20261014_090000.wav", stereo=True)
    S.add("Telefonas", phone)
    assert [p.name for p in progress.pending_files()] == ["vox_20261014_090000.wav", "a.wav"]
    r = subprocess.run(["bash", str(TPENDING), "--sources", "--if-immediate"], capture_output=True, text=True)
    assert r.returncode == 0 and not fake_asr.exists() and r.stderr == ""          # naktinis režimas — nieko
    env.write_conf(ARCHIVE_MP3=0, MODE="immediate")
    r = subprocess.run(["bash", str(TPENDING), "--sources", "--if-immediate"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    done = [ln.split()[2] for ln in fake_asr.read_text().splitlines() if ln.startswith("start")]
    assert done == ["a.wav"] and vox.exists() and not vox.with_suffix(".named.txt").exists()   # tik aplankai
    assert (env.data / "sources" / "telefonas" / "a.wav.src.json").exists()
    r = subprocess.run(["bash", str(TPENDING), "--sources"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stderr == ""                                    # nieko naujo — tylu
    rec(phone / "c.wav")
    r = subprocess.run(["bash", str(TPENDING)], capture_output=True, text=True)    # naktinis: įrašai + aplankai
    done = [ln.split()[2] for ln in fake_asr.read_text().splitlines() if ln.startswith("start")]
    assert done == ["a.wav", "vox_20261014_090000.wav", "c.wav"] and b.exists()
    assert progress.pending_files() == []


# ── T6: timer'is ir unit'ai ──

def test_t6_sources_timer_installs_missing_units(env, fake_systemd):
    from diktatura import services
    assert services.units_status()[services.SOURCES_TIMER] == "missing"
    ok, msg = services.set_sources_timer(True)
    assert ok and "kas ~2 min" in msg and services.is_enabled(services.SOURCES_TIMER)
    assert all(v == "ok" for v in services.units_status().values())
    assert "--sources --if-immediate" in (fake_systemd.units_dir / "diktatura-sources.service").read_text()
    assert "daemon-reload" in fake_systemd.calls()
    ok, _ = services.set_sources_timer(False)
    assert ok and not services.is_enabled(services.SOURCES_TIMER)


def test_t6_spawn_detached_without_systemd_run(env, monkeypatch, tmp_path):
    from diktatura import services
    monkeypatch.setenv("DIKTATURA_SYSTEMCTL", "true")                        # testuose — be systemd-run
    out = tmp_path / "ok"
    services.spawn_detached(["bash", "-c", f"echo $PYTHONPATH > '{out}'"], "testas")
    for _ in range(50):
        if out.exists() and out.read_text().strip():
            break
        time.sleep(0.05)
    assert out.read_text().strip() == str(REPO)


# ── T7–T8: trynimas ir doctor ──

def test_t7_reset_deletes_source_texts_never_your_audio(env, S, phone):
    from diktatura import reset
    a = rec(phone / "a.wav")
    src = S.add("Telefonas", phone)
    base = S.out_base(src, a)
    S.write_meta(src, a, base)
    S.with_suffix(base, ".named.txt").write_text("[0:00:01] Tu: labas\n")
    p = reset.plan(busy=set())
    assert S.with_suffix(base, ".named.txt") in p[reset.RECORDINGS].targets and p[reset.RECORDINGS].count == 2
    reset.run([reset.RECORDINGS], busy=set())
    assert a.exists() and not S.with_suffix(base, ".named.txt").exists() and S.load() == [src]


def test_t8_doctor_sources(env, S, phone, fake_systemd):
    from diktatura import config, doctor
    assert doctor.check_sources(config.load())[0].title.startswith("sekamų aplankų nėra")
    rec(phone / "a.wav")
    S.add("Telefonas", phone)
    env.write_conf(MODE="immediate")
    res = doctor.check_sources(config.load())
    assert res[0].status == doctor.OK and "laukia 1" in res[0].title
    assert res[-1].status == doctor.WARN and "timer" in res[-1].title          # „iškart", bet timer'is išjungtas
    phone.rename(phone.with_name("dingo"))
    assert doctor.check_sources(config.load())[0].status == doctor.WARN
