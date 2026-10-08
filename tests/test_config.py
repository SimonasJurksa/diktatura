"""B. Konfigūracija / nustatymai (diktatura.config + bash load_config)."""
import subprocess

import pytest

from testenv import REPO
from diktatura import config


def test_b1_defaults_match_schema_and_parse(env):
    d = config.defaults()
    assert set(d) == set(config.BY_KEY), "SCHEMA raktai turi sutapti su config/diktatura.conf.default"
    for s in config.SCHEMA:
        config.coerce(s.key, d[s.key])                  # numatytoji reikšmė praeina savo validaciją
        assert s.label and s.group
        if s.kind in ("int", "float"):
            assert s.lo is not None and s.hi is not None and s.lo < s.hi, s.key
        if s.kind == "choice":
            assert d[s.key] in s.choices


def test_b2_save_load_roundtrip_keeps_comments(env):
    config.ensure()
    config.save({"VOX_SILENCE_SEC": "3.5", "MODE": "deferred", "ARCHIVE_MP3": "0", "THREADS": "4"})
    cur = config.load()
    assert cur["VOX_SILENCE_SEC"] == 3.5 and cur["MODE"] == "deferred"
    assert cur["ARCHIVE_MP3"] is False and cur["THREADS"] == 4
    text = env.conf_file.read_text(encoding="utf-8")
    assert "# ── Įrašymas ──" in text, "komentarai iš numatytųjų šablono turi išlikti"
    assert "VOX_SILENCE_SEC=3.5\n" in text and "THREADS=4\n" in text
    # išsaugojus antrą kartą tą pačią reikšmę — failas identiškas
    before = text
    config.save({"THREADS": "4"})
    assert env.conf_file.read_text(encoding="utf-8") == before


def test_b3_reset_restores_default_file(env):
    config.save({"MODE": "deferred"})
    config.reset()
    assert env.conf_file.read_bytes() == (REPO / "config" / "diktatura.conf.default").read_bytes()
    assert config.load()["MODE"] == "immediate"


@pytest.mark.parametrize("key,value,fragment", [
    ("VOX_SILENCE_SEC", "-1", "leistina"),
    ("VOX_SILENCE_SEC", "penki", "skaičius"),
    ("THREADS", "2.5", "sveikasis"),
    ("MODE", "vakare", "galimos reikšmės"),
    ("AUTOTRANSCRIBE", "gal", "1 (taip) arba 0"),
    ("NERA_TOKIO", "1", "Nežinomas"),
])
def test_b4_invalid_value_rejected_old_kept(env, key, value, fragment):
    config.save({"VOX_SILENCE_SEC": "7"})
    before = env.conf_file.read_text(encoding="utf-8")
    with pytest.raises(ValueError) as e:
        config.save({key: value})
    assert fragment in str(e.value)
    assert env.conf_file.read_text(encoding="utf-8") == before


def test_b4_cross_field_rule(env):
    with pytest.raises(ValueError, match="mažesnė už pradžios"):
        config.save({"VOX_CLOSE_MARGIN": "20"})          # numatyta pradžios atsarga 15
    config.save({"VOX_OPEN_MARGIN": "25", "VOX_CLOSE_MARGIN": "20"})
    assert config.load()["VOX_CLOSE_MARGIN"] == 20


def test_b4_bad_value_in_file_falls_back_to_default(env):
    env.write_conf(VOX_SILENCE_SEC="abc", THREADS="999")
    cur = config.load()
    assert cur["VOX_SILENCE_SEC"] == 5 and cur["THREADS"] == 6


def test_b5_missing_config_created_from_defaults(env):
    assert not env.conf_file.exists()
    assert config.load()["MODEL"] == "azuolas-ct2"      # veikia ir be failo
    config.ensure()
    assert env.conf_file.read_bytes() == (REPO / "config" / "diktatura.conf.default").read_bytes()


def test_cli_set_get_show(env):
    run = lambda *a: subprocess.run(["python3", "-m", "diktatura.config", *a],  # noqa: E731
                                    capture_output=True, text=True, cwd=REPO)
    r = run("set", "VOX_SILENCE_SEC=3", "MODE=deferred")
    assert r.returncode == 0, r.stderr
    assert run("get", "MODE").stdout.strip() == "deferred"
    show = run("show").stdout
    assert "* VOX_SILENCE_SEC" in show and "  MODEL" in show      # * = pakeista
    r = run("set", "THREADS=abc")
    assert r.returncode == 1 and "skaičius" in r.stderr
    assert run("get", "NERA").returncode == 2


def test_bash_and_python_read_same_values(env):
    """bin/common.sh load_config (bash `.`) ir config.load_raw() turi matyti tas pačias reikšmes."""
    env.write_conf(VOX_SILENCE_SEC="2.5", MODE="deferred")
    keys = " ".join(f"{k}=${k}" for k in config.BY_KEY)
    out = subprocess.run(["bash", "-c", f'. "{REPO}/bin/common.sh"; load_config; echo "{keys}"'],
                         capture_output=True, text=True, check=True).stdout.split()
    assert dict(kv.split("=", 1) for kv in out) == config.load_raw()
