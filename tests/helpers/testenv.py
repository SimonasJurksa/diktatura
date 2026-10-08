"""Testų konstantos (bendros visiems tests/**): keliai, tikri įrankiai, tikri modeliai ir užraktas.

Importuojama iš tests/conftest.py PRIEŠ sesijos saugiklį (kuris nukreipia DIKTATURA_*) — todėl REAL_* rodo į
tikrą sistemą. Testų moduliuose:  from testenv import REPO, PCM_GEN, ...  (ne „from conftest" — tests/ui turi savo).
"""
import os
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HELPERS = REPO / "tests" / "helpers"
QUIET_BIN = HELPERS / "fakebin" / "quiet"
AUDIO_BIN = HELPERS / "fakebin" / "audio"
FAKE_ASR = HELPERS / "fake_asr.sh"
PCM_GEN = HELPERS / "pcm_gen.py"
ROOT_KEYS = ("DIKTATURA_CONFIG_DIR", "DIKTATURA_DATA", "DIKTATURA_STATE", "DIKTATURA_RUN")
REAL = {t: shutil.which(t) for t in ("ffmpeg", "ffprobe", "pactl", "paplay")}
# Tikri (vieši) modeliai ir tikras transkripcijos užraktas — apskaičiuojami PRIEŠ nukreipiant DIKTATURA_*.
# (ta pati logika kaip diktatura/paths.py)
REAL_MODELS = Path(os.environ.get("DIKTATURA_DATA") or
                   Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "diktatura") / "models"
if os.environ.get("DIKTATURA_RUN"):
    REAL_LOCK = Path(os.environ["DIKTATURA_RUN"]) / "transcribe.lock"
elif os.environ.get("XDG_RUNTIME_DIR"):
    REAL_LOCK = Path(os.environ["XDG_RUNTIME_DIR"]) / "diktatura" / "transcribe.lock"
else:
    REAL_LOCK = Path(f"/tmp/diktatura-{os.getuid()}") / "transcribe.lock"
