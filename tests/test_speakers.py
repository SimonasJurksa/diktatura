"""G. Kalbėtojai: panašumas, saugykla (enroll / pending / ignored), vardų priskyrimas ir pervadinimas tekstuose."""
import json

import numpy as np
import pytest

from diktatura.speakers import speakerlib as sl
from diktatura.speakers import store

DIM = 16
SR = 16000


def vec(i, noise=0.0, seed=0):
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    if noise:
        v += np.random.default_rng(seed).normal(0, noise, DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def test_g1_cosine_and_best_match_threshold():
    assert sl.cosine(vec(0), vec(0)) == pytest.approx(1.0)
    assert sl.cosine(vec(0), vec(1)) == pytest.approx(0.0)
    reg = {"Ona": [vec(0)], "Jonas": [vec(1), vec(2)]}           # keli pavyzdžiai — imamas geriausias
    assert sl.best_match(vec(2, 0.1), reg, 0.5)[0] == "Jonas"
    name, sim = sl.best_match(vec(5), reg, 0.5)
    assert name is None and sim < 0.5


def test_g2_enroll_and_pending_roundtrip(env):
    sl.save_enroll({"Ona": [vec(0)]})
    assert set(sl.load_enroll()) == {"Ona"}
    np.testing.assert_allclose(sl.load_enroll()["Ona"][0], vec(0), atol=1e-6)
    pid = sl.add_pending(vec(3), np.zeros(SR * 20, dtype=np.float32), SR, "vox_20261008_120000")
    assert pid == "nez1"
    [p] = store.list_pending()
    assert p.id == "nez1" and p.src == "vox_20261008_120000" and p.wav.exists()
    import wave
    with wave.open(str(p.wav)) as w:
        assert w.getnframes() == SR * 15                          # pavyzdys apkarpomas iki 15 s
    np.testing.assert_allclose(sl.load_pending()["nez1"][0], vec(3), atol=1e-6)


def test_pending_ids_never_reused(env):
    a = sl.add_pending(vec(3), np.zeros(SR), SR, "x")
    b = sl.add_pending(vec(4), np.zeros(SR), SR, "x")
    store.assign(b, "Petras")                                     # nez2 išnyksta iš pending ...
    c = sl.add_pending(vec(5), np.zeros(SR), SR, "x")
    assert (a, b, c) == ("nez1", "nez2", "nez3")                  # ... bet jo numeris nebeišduodamas


def segments_signal(spec):
    """spec: [(start, end, kalbėtojo nr)] -> (signalas, segmentai). Kalbėtojas užkoduotas amplitude."""
    samples = np.zeros(SR * 60, dtype=np.float32)
    segs = []
    for s0, s1, who in spec:
        samples[int(s0 * SR):int(s1 * SR)] = (who + 1) / 100
        segs.append((s0, s1, f"tekstas {s0}"))
    return samples, segs


def fake_embed(seg):
    return vec(int(round(float(seg[len(seg) // 2]) * 100)) - 1, 0.05, seed=len(seg))


def label(env, spec, src="vox_20261008_120000", store_=None, ignored=None):
    samples, segs = segments_signal(spec)
    pending = sl.load_pending()
    return sl.label_segments(segs, samples, store_ or {}, pending, ignored or {}, 0.5,
                             fake_embed, sl.add_pending, src)


def test_g3_same_unknown_voice_one_pending_across_segments_and_files(env):
    rows, new = label(env, [(0, 2, 3), (3, 5, 3), (6, 8, 4), (9, 9.5, 3)])
    assert new == 2
    assert [r[2] for r in rows] == ["Kolega?nez1", "Kolega?nez1", "Kolega?nez2", "Kolega?"]   # < 0.8 s -> be balso
    rows2, new2 = label(env, [(0, 3, 3)], src="vox_20261008_130000")                       # kitas failas
    assert new2 == 0 and rows2[0][2] == "Kolega?nez1"
    assert len(store.list_pending()) == 2


def test_g3_registered_voice_gets_name(env):
    rows, new = label(env, [(0, 2, 1)], store_={"Ona": [vec(1)]})
    assert rows[0][2] == "Ona" and new == 0 and not store.list_pending()


def write_transcript(env, name, text):
    f = env.recordings / name
    f.write_text(text, encoding="utf-8")
    return f


def test_g4_assign_extends_enroll_removes_pending_renames_texts(env):
    sl.save_enroll({"Ona": [vec(0)]})
    for i in range(3):
        sl.add_pending(vec(3 + i), np.zeros(SR), SR, "vox_20261008_120000")       # nez1..nez3
    f = write_transcript(env, "vox_20261008_120000.named.txt",
                         "[0:00:01] Kolega?nez3: labas, Kolega?nez3: čia tekste\n"
                         "[0:00:02] Kolega?nez31: kitas balsas\n[0:00:03] Tu: sveiki\n")
    n = store.assign("nez3", "Darius")
    assert n == 1
    text = f.read_text(encoding="utf-8")
    assert "[0:00:01] Darius: labas, Kolega?nez3: čia tekste" in text            # tik kalbėtojo vietoje
    assert "Kolega?nez31:" in text                                                # nez31 ≠ nez3
    assert store.counts() == {"Ona": 1, "Darius": 1}
    assert [p.id for p in store.list_pending()] == ["nez1", "nez2"]
    assert store.load_assigned() == {"nez3": "Darius"}


def test_g4_assign_to_existing_name_adds_sample(env):
    sl.save_enroll({"Ona": [vec(0)]})
    sl.add_pending(vec(1), np.zeros(SR), SR, "x")
    store.assign("nez1", "Ona")
    assert store.counts() == {"Ona": 2}


def test_g5_discard_keeps_enroll_and_ignores_future(env):
    sl.save_enroll({"Ona": [vec(0)]})
    before = (env.speakers / "enroll.json").read_text()
    rows, _ = label(env, [(0, 2, 6)])                                             # triukšmas -> nez1
    f = write_transcript(env, "vox_20261008_120000.named.txt", "[0:00:00] Kolega?nez1: šššš\n")
    store.discard("nez1")
    assert not store.list_pending()
    assert (env.speakers / "enroll.json").read_text() == before
    assert f.read_text(encoding="utf-8") == "[0:00:00] Kolega?: šššš\n"
    rows, new = label(env, [(0, 2, 6)], ignored=sl.load_ignored())               # tas pats garsas vėl
    assert new == 0 and rows[0][2] == "Kolega?"


def test_rename_and_merge_speaker(env):
    sl.save_enroll({"Rūta": [vec(0)], "Ruta": [vec(0, 0.1)]})
    f = write_transcript(env, "vox_20261008_120000.named.txt", "[0:00:01] Ruta: labas\n[0:00:02] Rūta: sveiki\n")
    assert store.rename_speaker("Ruta", "Rūta") == 1
    assert store.counts() == {"Rūta": 2}
    assert f.read_text(encoding="utf-8").count("Rūta:") == 2
    with pytest.raises(KeyError):
        store.rename_speaker("Nėra", "X")
    store.delete_speaker("Rūta")
    assert store.counts() == {}


@pytest.mark.parametrize("bad", ["", "  ", "Kolega?x"])
def test_invalid_names_rejected(env, bad):
    with pytest.raises(ValueError):
        store.clean_name(bad)


def test_clean_name_strips_colon_and_spaces():
    assert store.clean_name("  Jonas:  Petraitis \n") == "Jonas Petraitis"


def test_resolve_labels_after_assign_during_transcription(env):
    sl.add_pending(vec(3), np.zeros(SR), SR, "x")
    sl.add_pending(vec(4), np.zeros(SR), SR, "x")
    store.assign("nez1", "Matas")
    store.discard("nez2")
    rows = store.resolve_labels([(0, 1, "Kolega?nez1", "a"), (1, 2, "Kolega?nez2", "b"), (2, 3, "Tu", "c")])
    assert [r[2] for r in rows] == ["Matas", "Kolega?", "Tu"]


def test_occurrences_lists_context(env):
    write_transcript(env, "vox_20261008_120000.named.txt", "[0:00:01] Kolega?nez1: pirmas\n[0:00:02] Tu: x\n")
    write_transcript(env, "slack_20261007_090000.named.txt", "[0:10:00] Kolega?nez1: senesnis\n")
    occ = store.occurrences("Kolega?nez1")
    assert [(f.name, ts, tx) for f, ts, tx in occ] == [
        ("slack_20261007_090000.named.txt", "0:10:00", "senesnis"),
        ("vox_20261008_120000.named.txt", "0:00:01", "pirmas")]


def test_corrupt_store_files_do_not_crash(env):
    env.speakers.mkdir(parents=True, exist_ok=True)
    (env.speakers / "enroll.json").write_text("{sugadinta")
    env.pending.mkdir(parents=True, exist_ok=True)
    (env.pending / "nez9.json").write_text("ne json")
    (env.pending / "nez8.json").write_text(json.dumps({"src": "be embedding"}))
    assert store.load_enroll_raw() == {} and store.list_pending() == []
