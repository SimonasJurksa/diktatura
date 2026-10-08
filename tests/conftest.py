"""Bendri testų fixture'ai.

SAUGIKLIS: dar prieš importuojant bet kurį diktatura.* modulį visi DIKTATURA_* keliai nukreipiami į
laikiną katalogą, o PATH priekyje — netikras notify-send. Todėl joks testas (net pamiršęs `env`
fixture'ą) neliečia tikrų įrašų, balsų, nustatymų ir nerodo pranešimų darbalaukyje.
"""
import atexit
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))
from testenv import (AUDIO_BIN, FAKE_ASR, HELPERS, PCM_GEN, QUIET_BIN, REAL, REAL_LOCK, REAL_MODELS,  # noqa: E402,F401
                     REPO, ROOT_KEYS)

# ── Sesijos saugiklis (vykdoma importuojant conftest, prieš testų modulius) ──
_SESSION = Path(tempfile.mkdtemp(prefix="diktatura-test-"))
atexit.register(shutil.rmtree, _SESSION, True)
for _k in [k for k in os.environ if k.startswith("DIKTATURA_")]:
    del os.environ[_k]
for _k, _sub in zip(ROOT_KEYS, ("config", "data", "state", "run")):
    os.environ[_k] = str(_SESSION / "default" / _sub)
os.environ["PATH"] = f"{QUIET_BIN}:{os.environ['PATH']}"
os.environ["PYTHONPATH"] = str(REPO) + (":" + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")


@dataclass
class Env:
    """Izoliuota Diktatūros aplinka vienam testui (visi keliai — tmp)."""
    root: Path
    config: Path
    data: Path
    state: Path
    run: Path

    @property
    def recordings(self) -> Path:
        return self.data / "recordings"

    @property
    def speakers(self) -> Path:
        return self.data / "speakers"

    @property
    def pending(self) -> Path:
        return self.speakers / "pending"

    @property
    def conf_file(self) -> Path:
        return self.config / "diktatura.conf"

    def write_conf(self, **kv) -> None:
        """Vartotojo config = numatytieji + kv (tekstu, BE validacijos — testams su kraštinėmis reikšmėmis)."""
        lines = (REPO / "config" / "diktatura.conf.default").read_text(encoding="utf-8").splitlines()
        out, seen = [], set()
        for ln in lines:
            k = ln.split("=", 1)[0].strip()
            if not ln.lstrip().startswith("#") and "=" in ln and k in kv:
                out.append(f"{k}={kv[k]}")
                seen.add(k)
            else:
                out.append(ln)
        out += [f"{k}={v}" for k, v in kv.items() if k not in seen]
        self.conf_file.parent.mkdir(parents=True, exist_ok=True)
        self.conf_file.write_text("\n".join(out) + "\n", encoding="utf-8")

    def log(self, name: str) -> str:
        p = self.state / f"{name}.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def sh(self, *args, timeout=60, **kw) -> subprocess.CompletedProcess:
        """Paleisti komandą su šia aplinka (os.environ jau nukreiptas)."""
        return subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout, **kw)


@pytest.fixture
def env(tmp_path):
    """DIKTATURA_* -> tmp_path; diktatura.paths perkraunamas (kiti moduliai kelius ima kvietimo metu)."""
    saved = {k: os.environ.get(k) for k in ROOT_KEYS}
    e = Env(tmp_path, tmp_path / "config", tmp_path / "data", tmp_path / "state", tmp_path / "run")
    for k, p in zip(ROOT_KEYS, (e.config, e.data, e.state, e.run)):
        os.environ[k] = str(p)
    from diktatura import paths
    importlib.reload(paths)
    paths.ensure_dirs()
    yield e
    for k, v in saved.items():
        os.environ[k] = v
    importlib.reload(paths)


@pytest.fixture
def fake_audio(env, monkeypatch, tmp_path):
    """Netikri pactl/ffmpeg (Slack daemon'o testams). Grąžina valdymo objektą."""
    state = tmp_path / "pactl_state"

    class Ctl:
        def call(self, app="ringrtc"):
            state.write_text(app)

        def hangup(self):
            state.write_text("")

    monkeypatch.setenv("PATH", f"{AUDIO_BIN}:{os.environ['PATH']}")
    monkeypatch.setenv("REAL_FFMPEG", REAL["ffmpeg"])
    monkeypatch.setenv("FAKE_PACTL_STATE", str(state))
    ctl = Ctl()
    ctl.hangup()
    return ctl


@pytest.fixture
def fake_asr(env, monkeypatch, tmp_path):
    """DIKTATURA_ASR_CMD -> tests/helpers/fake_asr.sh; grąžina trace failo kelią."""
    trace = tmp_path / "asr_trace"
    monkeypatch.setenv("DIKTATURA_ASR_CMD", f"bash {FAKE_ASR}")
    monkeypatch.setenv("FAKE_ASR_TRACE", str(trace))
    return trace


@pytest.fixture
def real_models(env):
    """Tikri modeliai (Ąžuolas, kalbėtojų ONNX) per symlink į izoliuotą aplinką + TIKRAS transkripcijos užraktas:
    sunkus ASR testas laukia, kol baigsis tikra transkripcija (du Ąžuolai vienu metu = OOM)."""
    import fcntl
    if not (REAL_MODELS / "azuolas-ct2" / "model.bin").exists():
        pytest.skip(f"nėra Ąžuolo modelio ({REAL_MODELS}/azuolas-ct2) — make model-convert")
    shutil.rmtree(env.data / "models", ignore_errors=True)        # tuščias katalogas iš ensure_dirs()
    (env.data / "models").symlink_to(REAL_MODELS, target_is_directory=True)
    REAL_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(REAL_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield REAL_MODELS


@pytest.fixture
def fake_systemd(env, monkeypatch, tmp_path):
    """Netikras systemctl (DIKTATURA_SYSTEMCTL) + tmp unit'ų katalogas. Grąžina valdymo objektą."""
    d = tmp_path / "systemd_state"
    d.mkdir()
    units = tmp_path / "units"
    units.mkdir()
    monkeypatch.setenv("DIKTATURA_SYSTEMCTL", str(HELPERS / "fakebin" / "systemctl-fake"))
    monkeypatch.setenv("FAKE_SYSTEMD", str(d))
    monkeypatch.setenv("DIKTATURA_SYSTEMD_DIR", str(units))

    class Ctl:
        state, units_dir = d, units

        def set(self, unit, active=None, enabled=None):
            for flag, val in (("active", active), ("enabled", enabled)):
                if val is not None:
                    f = d / f"{unit}.{flag}"
                    f.touch() if val else f.unlink(missing_ok=True)

        def calls(self):
            p = d / "calls"
            return p.read_text().splitlines() if p.exists() else []

        def install_units(self):
            from diktatura import services
            for u in services.UNITS:
                (units / u).write_text(services.render_unit(u), encoding="utf-8")

    return Ctl()
