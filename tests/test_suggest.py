"""Apmokymų pertikrinimas (diktatura.speakers.suggest) ir sekamų aplankų tekstai balsų saugykloje.

Regresija (2026-10-25): sekamo aplanko (pvz. susirinkimo įrašo) nežinomų balsų sąraše buvo „0 kart. · 0 sesij.",
o priskirtas vardas tų tekstų nepasiekdavo — store ieškojo tik įrašų kataloge. Embedding'ai — netikri (ortogonalūs
vektoriai), profiliams — tikra kalba (LT fixture'ai, make fixtures) ir tikras VAD, embedding netikras.
"""
import json
import os
import subprocess
import sys
import time

import numpy as np
import pytest

import audio
import lt
from diktatura.speakers import store
from diktatura.speakers import suggest
from diktatura.speakers import teach

SR = 16000
SRC = "susirinkimas"


def emb(*pairs, dim=8):
    """emb((0, 0.8), (2, 0.6)) -> normuotas vektorius su tomis komponentėmis."""
    v = np.zeros(dim)
    for i, x in pairs:
        v[i] = x
    return (v / np.linalg.norm(v)).tolist()


def pending(env, pid, vec, src=SRC):
    env.pending.mkdir(parents=True, exist_ok=True)
    audio.write_wav(env.pending / f"{pid}.wav", audio.speech(1, -20))
    (env.pending / f"{pid}.json").write_text(json.dumps({"embedding": vec, "src": src, "added": "2026-10-25T10:00:00"}))


def source_text(env, text, name="Susirinkimas 20260613.wav", audio_path="/nera/garso.wav"):
    d = env.data / "sources" / "telefonas"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.src.json").write_text(json.dumps({"audio": audio_path, "recorded": "2026-06-13T12:34:43",
                                                    "source": "telefonas"}))
    f = d / f"{name}.named.txt"
    f.write_text(text, encoding="utf-8")
    return f


def enroll(env, **names):
    (env.speakers / "enroll.json").write_text(json.dumps(names))
    store.mark_model()                                    # dabartinis balso modelis (be žymės — senas)


MEETING = ("[0:00:00] Kolega?nez5: labas rytas\n[0:00:04] Kolega?: kas\n[0:00:06] Kolega?nez5: pradedam\n"
           "[0:00:10] Kolega?nez6: balsuojam\n[0:00:15] Kolega?nez7: aš prieš\n[0:00:20] Kolega?nez9: o aš už\n")


# ── store: sekamų aplankų tekstai ──

def test_occurrences_and_names_include_followed_folder_texts(env):
    """Buvo „0 kart. · 0 sesij.": nežinomo balso eilutės sekamo aplanko tekste nerandamos."""
    f = source_text(env, MEETING + "[0:00:25] Ona: ačiū\n")
    rec = env.recordings / "slack_20261025_090000.named.txt"
    rec.write_text("[0:00:01] Kolega?nez5: ir čia\n", encoding="utf-8")
    assert store.transcript_files() == [rec, f]
    occ = store.occurrences("Kolega?nez5", with_idx=True)
    assert [(o[0], o[1], o[2], o[3]) for o in occ] == [(rec, "0:00:01", "ir čia", 0), (f, "0:00:00", "labas rytas", 0),
                                                        (f, "0:00:06", "pradedam", 2)]
    assert [len(o) for o in store.occurrences("Kolega?nez5")] == [3, 3, 3]          # be with_idx — kaip anksčiau
    assert store.text_speakers() == {"Ona"}


def test_assign_renames_in_followed_folder_texts(env):
    f = source_text(env, MEETING)
    pending(env, "nez5", emb((1, 1)))
    assert store.assign("nez5", "Petras") == 2
    assert f.read_text().count("Petras:") == 2 and "nez5" not in f.read_text()


def test_apply_assigned_repairs_texts_and_is_idempotent(env):
    """Anksčiau priskirti (assigned.json), bet tekstų nepasiekę vardai pritaikomi; laukiantys nekeičiami."""
    f = source_text(env, MEETING)
    pending(env, "nez9", emb((3, 1)))
    (env.speakers / "assigned.json").write_text(json.dumps({"nez5": "Petras", "nez6": "", "nez7": "Tu",
                                                            "nez9": "Klaida"}, ensure_ascii=False))
    assert store.apply_assigned() == 4
    t = f.read_text()
    assert "[0:00:00] Petras: labas rytas" in t and "[0:00:06] Petras: pradedam" in t
    assert "[0:00:10] Kolega?: balsuojam" in t and "[0:00:15] Tu: aš prieš" in t
    assert "[0:00:20] Kolega?nez9: o aš už" in t                                    # dar laukia — nekeičiama
    assert store.apply_assigned() == 0


def test_assign_many_without_learning(env):
    f = source_text(env, MEETING)
    for pid in ("nez5", "nez6", "nez7"):
        pending(env, pid, emb((int(pid[3:]) - 4, 1)))
    enroll(env, Petras=[emb((0, 1))])
    before = (env.speakers / "enroll.json").read_text()
    n = store.assign_many([("nez5", "Petras"), ("nez6", ""), ("nez7", " tu "), ("nez404", "Ona")])
    assert n == 4 and store.list_pending() == []
    assert (env.speakers / "enroll.json").read_text() == before and store.owner_count() == 0 and not store.load_ignored()
    assert store.load_assigned() == {"nez5": "Petras", "nez6": "", "nez7": "Tu"}
    assert f.read_text().count("Petras:") == 2 and "Tu: aš prieš" in f.read_text()
    assert store.assign_many([("nez5", "Ona")]) == 0                                 # jau nebelaukia


def test_assign_learn_false_keeps_enroll(env):
    pending(env, "nez5", emb((1, 1)))
    enroll(env, Ona=[emb((0, 1))])
    store.assign("nez5", "Ona", learn=False)
    assert store.counts() == {"Ona": 1} and store.load_assigned() == {"nez5": "Ona"}


def test_suggestions_file_staleness_and_filter(env):
    pending(env, "nez5", emb((1, 1)))
    enroll(env, Ona=[emb((0, 1))])
    assert store.suggestions_stale(0.5, 0.1, 0.4)                                    # dar nėra
    store._atomic_write(store.suggestions_file(), json.dumps({
        "started": time.time(), "voices": store.voices_signature(), "threshold": 0.5, "margin": 0.1, "suggest": 0.4,
        "checked": ["nez5"],
        "items": {"nez5": {"name": "Ona", "sim": 0.45}, "nez1": {"name": "Ona", "sim": 0.9}, "nez2": "blogas"}}))
    assert not store.suggestions_stale(0.5, 0.1, 0.4)
    assert store.suggestions_stale(0.5, 0.1, 0.45)                                   # kitas slenkstis
    assert set(store.load_suggestions({"nez5"})) == {"nez5"} and set(store.load_suggestions()) == {"nez5", "nez1"}
    pending(env, "nez6", emb((2, 1)))
    assert store.suggestions_stale(0.5, 0.1, 0.4)                                    # naujas netikrintas
    (env.pending / "nez6.json").unlink()
    assert not store.suggestions_stale(0.5, 0.1, 0.4)
    future = time.time() + 5
    os.utime(env.speakers / "enroll.json", (future, future))
    assert store.suggestions_stale(0.5, 0.1, 0.4)                                    # pasikeitė registruoti balsai


def test_suggestions_stale_after_voices_deleted(env):
    """„Ištrinti balsus" (reset VOICES) — seni pasiūlymai su nebeegzistuojančiais vardais nebegalioja."""
    pending(env, "nez5", emb((0, 1)))
    enroll(env, Ona=[emb((0, 1))])
    suggest.run(profiles=False, out=lambda s: None)
    assert not store.suggestions_stale(0.5, 0.1, 0.4)
    (env.speakers / "enroll.json").unlink()
    assert store.suggestions_stale(0.5, 0.1, 0.4)


# ── suggest.judge ──

ONA, JONAS = [np.array(emb((0, 1)))], [np.array(emb((1, 1)))]
NOISE = [np.array(emb((5, 1)))]


def j(vec, **kw):
    a = dict(threshold=0.5, margin=0.1, suggest=0.4)
    a.update(kw)
    return suggest.judge(np.array(vec), {"Ona": ONA, "Jonas": JONAS, "Tu": [np.array(emb((7, 1)))]}, NOISE, **a)


def test_judge_strong_weak_close_and_owner():
    s = j(emb((0, 0.8), (3, 0.6)))
    assert s["name"] == "Ona" and s["strong"] and s["sim"] == pytest.approx(0.8) and s["alt_sim"] == 0
    s = j(emb((0, 0.45), (3, 0.893)))
    assert s["name"] == "Ona" and not s["strong"] and s["sim"] == pytest.approx(0.45, abs=1e-3)
    assert j(emb((0, 0.45), (1, 0.43), (3, 0.78))) is None                           # du per panašūs
    assert j(emb((7, 0.7), (3, 0.71)))["name"] == "Tu"
    assert j(emb((3, 1))) is None                                                    # niekam nepanašus


def test_judge_noise_only_when_no_name_fits():
    s = j(emb((5, 0.6), (3, 0.8)))
    assert s["name"] == "" and s["strong"] and s["sim"] == pytest.approx(0.6)
    s = j(emb((5, 0.42), (3, 0.907)))
    assert s["name"] == "" and not s["strong"]
    s = j(emb((0, 0.5), (5, 0.6), (3, 0.62)))                                         # vardas tinka -> ne triukšmas
    assert s["name"] == "Ona"


# ── suggest.run ──

def test_run_writes_suggestions_without_profiles(env):
    source_text(env, MEETING)
    pending(env, "nez5", emb((0, 0.8), (3, 0.6)))         # Ona, užtikrintai
    pending(env, "nez6", emb((1, 0.45), (3, 0.893)))      # Jonas?
    pending(env, "nez7", emb((5, 0.6), (3, 0.8)))         # triukšmas
    pending(env, "nez9", emb((4, 1)))                     # nieko
    enroll(env, Ona=[emb((0, 1))], Jonas=[emb((1, 1))])
    (env.speakers / "ignored.json").write_text(json.dumps([emb((5, 1))]))
    r = suggest.run(profiles=False, out=lambda s: None)
    assert r == {"ok": True, "pending": 4, "suggested": 3, "strong": 2, "noise": 1, "profiles": 0,
                 "by_name": {"Ona": 1, "Jonas": 1}}
    d = json.loads(store.suggestions_file().read_text())
    assert d["checked"] == ["nez5", "nez6", "nez7", "nez9"] and (d["threshold"], d["margin"], d["suggest"]) == (0.5, 0.1, 0.4)
    assert d["items"]["nez5"]["basis"] == "sample" and d["items"]["nez5"]["lines"] == 2
    assert d["items"]["nez6"]["name"] == "Jonas" and not d["items"]["nez6"]["strong"]
    assert not store.suggestions_stale(0.5, 0.1, 0.4)


def test_run_refuses_old_voice_model(env):
    pending(env, "nez5", emb((0, 1)))
    (env.speakers / "model.json").write_text(json.dumps({"embedding_model": store.LEGACY_MODEL}))
    r = suggest.run(profiles=False, out=lambda s: None)
    assert not r["ok"] and "speakers-migrate" in r["error"] and not store.suggestions_file().exists()


def test_cli_prints_progress_and_json_summary(env):
    pending(env, "nez5", emb((0, 1)))
    enroll(env, Ona=[emb((0, 1))])
    p = subprocess.run([sys.executable, "-m", "diktatura.speakers.suggest", "--no-profiles"], capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    r = json.loads(p.stdout.strip().splitlines()[-1])
    assert r["ok"] and r["suggested"] == 1 and r["strong"] == 1


# ── balso profilis iš visų eilučių ──

@pytest.fixture
def speech():
    c = lt.clips()
    if not c:
        pytest.skip("nėra LT fixture'ų — make fixtures")
    return lt.decode(c[0][0])


def test_profile_from_all_lines_cached_and_used(env, speech, tmp_path):
    """≥ 2 eilutės -> embedding'as iš jų visų kalbos (mono — 0 kanalas); antrą kartą — iš kešo; eilutėms
    pasikeitus — iš naujo. Pasiūlymas remiasi profiliu (basis "profile")."""
    x = np.zeros(SR * 20, dtype=np.float32)
    seg = speech[: SR * 3]
    x[SR * 1: SR * 1 + len(seg)] = seg
    x[SR * 11: SR * 11 + len(seg)] = seg
    wav = tmp_path / "susirinkimas.wav"
    audio.write_wav(wav, x)
    f = source_text(env, "[0:00:01] Kolega?nez5: pirma\n[0:00:06] Kolega?: tyla\n[0:00:11] Kolega?nez5: antra\n"
                         "[0:00:16] Kolega?nez6: viena\n", audio_path=str(wav))
    pending(env, "nez5", emb((3, 1)))                     # trumpas pavyzdys — niekam nepanašus
    pending(env, "nez6", emb((3, 1)))
    enroll(env, Ona=[emb((0, 1))])
    calls = []

    def fake(samples):
        calls.append(len(samples) / SR)
        return np.array(emb((0, 1)), dtype=np.float32)    # profilis — Onos balsas
    r = suggest.run(embed=fake, out=lambda s: None)
    assert r["profiles"] == 1 and r["suggested"] == 1 and len(calls) == 1
    one = teach.speech_only(seg)[1]
    assert one > 0.5 and calls[0] == pytest.approx(2 * one, abs=0.6)   # abiejų eilučių kalba, be tylos
    item = store.load_suggestions()["nez5"]
    assert item["name"] == "Ona" and item["basis"] == "profile" and item["lines"] == 2 and item["strong"]
    suggest.run(embed=fake, out=lambda s: None)
    assert len(calls) == 1                                 # iš kešo
    f.write_text(f.read_text().replace("[0:00:16] Kolega?nez6", "[0:00:16] Kolega?nez5"), encoding="utf-8")
    suggest.run(embed=fake, out=lambda s: None)
    assert len(calls) == 2                                 # eilutės pasikeitė -> perskaičiuota
    assert set(json.loads((env.speakers / "profiles.json").read_text())) == {"nez5"}


def test_profile_failure_falls_back_to_sample(env, speech, tmp_path):
    source_text(env, "[0:00:01] Kolega?nez5: a\n[0:00:05] Kolega?nez5: b\n", audio_path=str(tmp_path / "nera.wav"))
    pending(env, "nez5", emb((0, 0.8), (3, 0.6)))
    enroll(env, Ona=[emb((0, 1))])

    def boom(_x):
        raise RuntimeError("nėra modelio")
    r = suggest.run(embed=boom, out=lambda s: None)
    assert r["ok"] and r["profiles"] == 0 and store.load_suggestions()["nez5"]["basis"] == "sample"
