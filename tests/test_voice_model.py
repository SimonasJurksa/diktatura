"""G10. Balso modelio žymė, perėjimas prie naujo modelio (migrate), kalbėtojų perskaičiavimas (relabel),
vardų priskyrimas transkripcijoje (name_colleagues). Embedding — netikras; relabel — su LT fixture'ais (VAD tikras)."""
import json

import numpy as np
import pytest

import audio
import lt
from diktatura.speakers import migrate, relabel, store
from diktatura.speakers import speakerlib as sl

SR = 16000
DIM = 8


def vec(i):
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def legacy_store(env):
    """Kaip iki 2026-10-09: balsai be model.json žymės."""
    env.speakers.mkdir(parents=True, exist_ok=True)
    (env.speakers / "enroll.json").write_text(json.dumps({"Ona": [vec(0).tolist()], "Jonas": [vec(1).tolist()]}))
    (env.speakers / "ignored.json").write_text(json.dumps([vec(7).tolist()]))
    (env.speakers / "assigned.json").write_text(json.dumps({"nez1": "Ona"}))


def test_g10_model_marker_fresh_legacy_and_claim(env):
    assert store.model_id() is None and store.compatible()
    legacy_store(env)
    assert store.model_id() == store.LEGACY_MODEL and not store.compatible()
    with pytest.raises(RuntimeError, match="speakers-migrate"):
        store.claim_model()
    with pytest.raises(RuntimeError):
        sl.add_pending(vec(2), np.zeros(SR), SR, "x")                     # seno modelio saugyklos negadinam
    store.mark_model()
    assert store.model_id() == store.EMB_MODEL and store.compatible()


def test_g10_first_new_voice_marks_fresh_store(env):
    sl.add_pending(vec(2), np.zeros(SR), SR, "x")
    assert store.model_id() == store.EMB_MODEL


def test_g10_migrate_archives_legacy_and_reembeds_pending(env):
    legacy_store(env)
    env.pending.mkdir(parents=True, exist_ok=True)
    audio.write_wav(env.pending / "nez4.wav", audio.speech(2))
    for pid in ("nez4", "nez5"):                                          # nez5 — be garso
        (env.pending / f"{pid}.json").write_text(json.dumps({"embedding": vec(3).tolist(), "src": "vox_x"}))
    t = env.recordings / "vox_20261009_120000.named.txt"
    t.write_text("[0:00:01] Ona: labas\n", encoding="utf-8")
    p = migrate.plan()
    assert p["needed"] and p["from"] == store.LEGACY_MODEL and p["enroll"] == {"Ona": 1, "Jonas": 1}
    assert p["pending_reembed"] == ["nez4"] and p["pending_drop"] == ["nez5"] and p["ignored"] == 1
    seen = []
    dst = migrate.apply(embed=lambda x: (seen.append(len(x)), vec(5))[1])
    assert dst.name.startswith(f"legacy-{store.LEGACY_MODEL}-")
    assert sorted(f.name for f in dst.iterdir()) == ["enroll.json", "ignored.json", "pending"]
    assert sorted(f.name for f in (dst / "pending").iterdir()) == ["nez4.json", "nez5.json"]
    assert store.counts() == {} and store.load_ignored() == [] and store.compatible()
    assert [v.id for v in store.list_pending()] == ["nez4"] and seen == [2 * SR]
    np.testing.assert_allclose(sl.load_pending()["nez4"][0], vec(5))
    assert store.load_assigned() == {"nez1": "Ona"}                        # istorija lieka
    assert t.read_text(encoding="utf-8") == "[0:00:01] Ona: labas\n"       # tekstai nekeičiami
    assert migrate.apply(embed=lambda x: vec(5)) is None                   # antrą kartą — nieko


def test_g10_name_colleagues_legacy_store_writes_no_names(env):
    from diktatura.asr.transcribe_named import name_colleagues
    legacy_store(env)
    rows, new = name_colleagues([(0.0, 2.0, "labas")], np.ones(3 * SR, np.float32) * 0.1, "vox_x",
                                embed=lambda x: vec(0))
    assert rows == [(0.0, 2.0, "Kolega?", "labas")] and new == 0 and not store.list_pending()


def test_g10_name_colleagues_uses_settings_and_owner(env):
    from diktatura.asr.transcribe_named import name_colleagues
    sl.save_enroll({"Ona": [vec(0)]})
    store.add_owner(vec(1), "x")
    segs = [(0.0, 2.0, "a"), (3.0, 5.0, "b")]
    x = np.zeros(6 * SR, np.float32)
    x[3 * SR:] = 0.5                                                       # antras segmentas — tu
    emb = lambda s: vec(1) if s.mean() > 0.1 else vec(0)                  # noqa: E731
    rows, _ = name_colleagues(segs, x, "vox_x", embed=emb)
    assert [r[2] for r in rows] == ["Ona", "Tu"]
    env.write_conf(SPEAKER_THRESHOLD="0.95")
    near = vec(0) * 0.9 + vec(2) * 0.43                                    # Onai ~0.9 < 0.95 -> nežinomas
    rows, new = name_colleagues(segs[:1], x, "vox_x", embed=lambda s: near / np.linalg.norm(near))
    assert rows[0][2] == "Kolega?nez1" and new == 1


# ── relabel: tikras VAD + LT kalba, netikras embedding ──

@pytest.fixture
def speech():
    c = lt.clips()
    if len(c) < 2:
        pytest.skip("nėra LT fixture'ų — make fixtures")
    return [lt.decode(f) for f, _ in c[:2]]


def test_g10_relabel_recent_texts(env, speech):
    """Seni klaidingi vardai -> perskaičiuota: žinomas -> vardas, nežinomas -> Kolega?nezN; „Tu" eilutės neliečiamos;
    peržiūra nieko nekeičia; originalai — į backup."""
    a, b = speech
    n = SR * 30
    left, right = np.zeros(n, np.float32), np.zeros(n, np.float32)
    right[SR:SR + min(len(a), 8 * SR)] = a[:8 * SR]                         # 0:00:01 — Ona
    right[12 * SR:12 * SR + min(len(b), 8 * SR)] = b[:8 * SR]               # 0:00:12 — nežinomas
    left[22 * SR:22 * SR + 3 * SR] = a[:3 * SR]                             # 0:00:22 — tu
    from datetime import datetime
    base = f"vox_{datetime.now():%Y%m%d}_100000"
    audio.write_wav(env.recordings / f"{base}.wav", left, right)
    txt = env.recordings / f"{base}.named.txt"
    original = "[0:00:01] Jonas: pirmas\n[0:00:12] Jonas: antras\n[0:00:22] Tu: trečias\n"
    txt.write_text(original, encoding="utf-8")
    level = {}

    def emb(x):                                                            # balsas pagal garso „parašą"
        k = round(float(np.abs(x).mean()), 4)
        level.setdefault(k, len(level))
        return vec(level[k] % DIM)

    sl.save_enroll({"Jonas": [vec(7)]})
    ea = emb(relabel.teach.speech_only(right[SR:9 * SR])[0])               # Onos „parašas" registruojamas
    store.add_embedding("Ona", ea.tolist())

    r = relabel.run(1, apply=False, embed=emb, out=lambda *_: None)
    assert r["changed"] == 2 and r["new_pending"] == 1 and txt.read_text(encoding="utf-8") == original
    assert not store.list_pending()

    r = relabel.run(1, apply=True, embed=emb, out=lambda *_: None)
    assert r["changed"] == 2 and r["backup"]
    assert txt.read_text(encoding="utf-8") == \
        "[0:00:01] Ona: pirmas\n[0:00:12] Kolega?nez1: antras\n[0:00:22] Tu: trečias\n"
    assert [p.id for p in store.list_pending()] == ["nez1"]
    from pathlib import Path
    assert (Path(r["backup"]) / txt.name).read_text(encoding="utf-8") == original
    assert relabel.run(1, apply=True, embed=emb, out=lambda *_: None)["changed"] == 0   # stabilu


def test_g10_relabel_refuses_legacy_store(env):
    legacy_store(env)
    with pytest.raises(SystemExit, match="speakers-migrate"):
        relabel.run(1, apply=False, embed=lambda x: vec(0))
