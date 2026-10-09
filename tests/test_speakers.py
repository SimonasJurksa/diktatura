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


# ── griežtumas: slenkstis + atsarga; tavo balsas kolegų kanale ──

def test_g6_decide_threshold_margin():
    assert sl.decide([], 0.5, 0.1) == (None, "low")
    assert sl.decide([(0.45, "Ona")], 0.5, 0.1) == (None, "low")
    assert sl.decide([(0.8, "Ona"), (0.75, "Jonas")], 0.5, 0.1) == (None, "close")     # per panašūs
    assert sl.decide([(0.8, "Ona"), (0.65, "Jonas")], 0.5, 0.1) == ("Ona", "ok")
    assert sl.decide([(0.8, "Ona"), (0.79, "Jonas")], 0.5, 0.0) == ("Ona", "ok")       # atsarga išjungta
    reg = {"Ona": [vec(0)], "Jonas": [vec(1), vec(2)], "Tuščias": []}
    assert [n for _, n in sl.ranked(vec(2), reg)] == ["Jonas", "Ona"]                   # be pavyzdžių — praleidžiamas


def mix(a, b, w):
    v = (1 - w) * vec(a) + w * vec(b)
    return v / np.linalg.norm(v)


def label_with(env, spec, embs, store_=None, owner=None, margin=0.1):
    """spec: [(start, end, kalbėtojo nr)]; embs: {nr: embedding} — tiksliai valdomi panašumai."""
    samples, segs = segments_signal(spec)
    emb = lambda seg: embs[int(round(float(seg[len(seg) // 2]) * 100)) - 1]
    return sl.label_segments(segs, samples, store_ or {}, sl.load_pending(), {}, 0.5, emb, sl.add_pending,
                             "vox_20261009_120000", margin=margin, owner=owner)


def test_g6_owner_voice_on_colleague_channel_is_tu(env):
    """Prisijungęs telefonu kalbi per kolegų kanalą: tavo balsas -> „Tu", ne panašiausias kolega."""
    store_ = {"Darius": [vec(1)]}
    embs = {0: mix(0, 1, 0.45), 1: vec(1, 0.05)}       # 0 — tu (Dariui 0.63, sau 0.77), 1 — Darius
    rows, new = label_with(env, [(0, 3, 0), (4, 7, 1)], embs, store_)
    assert [r[2] for r in rows] == ["Darius", "Darius"]                                 # be tavo balso — klaida
    sl.save_enroll(store_)
    store.add_owner(vec(0), "x")
    rows, new = label_with(env, [(0, 3, 0), (4, 7, 1)], embs, store_, owner=sl.load_owner())
    assert [r[2] for r in rows] == ["Tu", "Darius"] and new == 0


def test_g6_ambiguous_known_voices_become_unknown_without_pending(env):
    store_ = {"Rūta": [vec(0)], "Matas": [vec(1)]}
    embs = {0: mix(0, 1, 0.48)}                          # beveik per vidurį tarp Rūtos ir Mato
    rows, new = label_with(env, [(0, 3, 0)], embs, store_)
    assert rows[0][2] == "Kolega?" and new == 0 and not store.list_pending()
    rows, _ = label_with(env, [(0, 3, 0)], embs, store_, margin=0.0)                    # be atsargos — kaip anksčiau
    assert rows[0][2] == "Rūta"


def test_g7_pending_voice_assigned_to_me_goes_to_owner(env):
    sl.add_pending(vec(3), np.zeros(SR), SR, "vox_20261009_120000")
    f = write_transcript(env, "vox_20261009_120000.named.txt", "[0:00:01] Kolega?nez1: dar nespėjau\n")
    assert store.assign("nez1", " tu ") == 1
    assert f.read_text(encoding="utf-8") == "[0:00:01] Tu: dar nespėjau\n"
    assert store.counts() == {} and store.owner_count() == 1 and not store.list_pending()
    np.testing.assert_allclose(sl.load_owner()[0], vec(3), atol=1e-6)
    assert store.load_assigned() == {"nez1": "Tu"}
    with pytest.raises(ValueError):
        store.clean_name("Tu")                                                         # ne kolegos vardas
    sl.save_enroll({"Ona": [vec(0)]})
    with pytest.raises(ValueError):
        store.rename_speaker("Ona", "TU")


def test_g7_owner_samples_capped_and_cleared(env):
    for i in range(store.OWNER_MAX + 5):
        store.add_owner(vec(i % DIM), f"s{i}")
    raw = store.load_owner_raw()
    assert len(raw) == store.OWNER_MAX and raw[0]["src"] == "s5"                       # seniausi išmesti
    store.clear_owner()
    assert store.owner_count() == 0 and sl.load_owner() == []
    (env.speakers / "owner.json").write_text("{sugadinta")
    assert store.load_owner_raw() == []


def test_g8_line_span_and_relabel(env):
    f = write_transcript(env, "vox_20261009_120000.named.txt",
                         "[0:02:40] Darius: kaip sekasi\n[0:02:53] Darius: dar nespėjau\n"
                         "be laiko\n[0:02:58] Matas: ir\n[0:10:00] Matas: vėliau\n")
    assert store.line_span(f, 0) == (160.0, 173.0)
    assert store.line_span(f, 1) == (173.0, 178.0)
    assert store.line_span(f, 3) == (178.0, 198.0)                                     # ≤ 20 s
    assert store.line_span(f, 2) is None and store.line_span(f, 99) is None
    assert store.relabel_line(f, 1, "Darius", "Tu")
    assert not store.relabel_line(f, 1, "Darius", "Matas")                             # eilutė jau pasikeitė
    assert f.read_text(encoding="utf-8").splitlines()[:2] == [
        "[0:02:40] Darius: kaip sekasi", "[0:02:53] Tu: dar nespėjau"]


def test_g3_unknown_voice_no_chaining(env):
    """A -> A' -> A'': kiekvienas panašus į ankstesnį, bet A'' nepanašus į A — NEsuliejama „grandine"
    (kitaip skirtingi žmonės susilieja į vieną nezN; suskaidytą žmogų lengva sujungti tuo pačiu vardu)."""
    a0 = vec(0)
    a1 = mix(0, 1, 0.45)                                   # ~0.77 su a0
    a2 = mix(1, 0, 0.3)                                    # ~0.89 su a1, ~0.39 su a0
    embs = {0: a0, 1: a1, 2: a2}
    rows, new = label_with(env, [(0, 2, 0), (3, 5, 1), (6, 8, 2)], embs, margin=0.1)
    assert [r[2] for r in rows] == ["Kolega?nez1", "Kolega?nez1", "Kolega?nez2"] and new == 2


def test_pending_ids_unique_across_processes(env):
    """Transkripcija ir relabel gali kurti nežinomus balsus vienu metu — id neturi kartotis."""
    import subprocess
    import sys
    code = "from diktatura.speakers import store; print(' '.join(store.next_pending_id() for _ in range(25)))"
    ps = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True) for _ in range(4)]
    ids = [i for p in ps for i in p.communicate(timeout=60)[0].split()]
    assert len(ids) == 100 and len(set(ids)) == 100
