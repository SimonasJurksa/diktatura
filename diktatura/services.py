"""Diktatūra — systemd --user servisų valdymas (tik stdlib: naudoja ikona, Nustatymai, doctor).

Įrašymo režimas = kuris įrašymo servisas aktyvus: vox (diktatura-vox), slack (diktatura-autorecord) arba off.
Vienu metu — tik vienas (servisuose Conflicts=). Naktinis — diktatura-nightly.timer. Sekami aplankai (telefonas…) —
diktatura-sources.timer (kas ~2 min, tik MODE=immediate); įjungiamas pridėjus pirmą aplanką (Nustatymai).
Testams: DIKTATURA_SYSTEMCTL — netikra systemctl komanda; DIKTATURA_SYSTEMD_DIR — kur „įdiegti" unit'ai.
"""
import os
import shlex
import subprocess
from pathlib import Path

from diktatura import paths

RECORDERS = {"vox": "diktatura-vox.service", "slack": "diktatura-autorecord.service"}
MODE_LABELS = {"vox": "VOX — balso aktyvumas (diktavimas, pagauna ir skambučius)",
               "slack": "Slack — tik skambučiai (aptinka pradžią/pabaigą)",
               "off": "Išjungta — neįrašinėti"}
TRAY = "diktatura-tray.service"
TIMER = "diktatura-nightly.timer"
ASR = "diktatura-asr.service"
SOURCES_TIMER = "diktatura-sources.timer"
UNITS = ("diktatura-autorecord.service", "diktatura-vox.service", "diktatura-tray.service",
         "diktatura-nightly.service", "diktatura-nightly.timer", "diktatura-asr.service",
         "diktatura-sources.service", "diktatura-sources.timer")


def systemctl(*args, timeout=20) -> subprocess.CompletedProcess:
    cmd = shlex.split(os.environ.get("DIKTATURA_SYSTEMCTL") or "systemctl") + ["--user", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def is_active(unit: str) -> bool:
    return systemctl("is-active", unit).stdout.strip() == "active"


def is_enabled(unit: str) -> bool:
    return systemctl("is-enabled", unit).stdout.strip() == "enabled"


def recorder_mode() -> str:
    """Dabar veikiantis įrašymo režimas: vox | slack | off."""
    for mode, unit in RECORDERS.items():
        if is_active(unit):
            return mode
    return "off"


def set_recorder_mode(mode: str) -> tuple:
    """Perjungti režimą (ir po perkrovimo): kitas išjungiamas, pasirinktas įjungiamas. -> (ok, pranešimas)."""
    if mode not in MODE_LABELS:
        return False, f"Nežinomas režimas: {mode}"
    for m, unit in RECORDERS.items():
        if m != mode:
            systemctl("disable", "--now", unit)
    if mode == "off":
        return True, "Įrašymas išjungtas"
    r = systemctl("enable", "--now", RECORDERS[mode])
    if r.returncode != 0:
        return False, f"Nepavyko įjungti {RECORDERS[mode]}: {(r.stderr or r.stdout).strip()} (make install-units?)"
    return True, f"Režimas: {MODE_LABELS[mode].split(' — ')[0]}"


def set_timer(enabled: bool) -> tuple:
    r = systemctl("enable" if enabled else "disable", "--now", TIMER)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()
    return True, f"Naktinė transkripcija 01:30 {'įjungta' if enabled else 'išjungta'}"


def set_asr_server(enabled: bool) -> tuple:
    r = systemctl("enable" if enabled else "disable", "--now", ASR)
    if r.returncode != 0:
        return False, f"ASR serverio {'įjungti' if enabled else 'išjungti'} nepavyko: {(r.stderr or r.stdout).strip()}"
    return True, f"ASR serveris {'įjungtas (modelis bus laikomas atmintyje)' if enabled else 'išjungtas'}"


def spawn_detached(cmd: list, name: str = "darbas", env: dict = None) -> None:
    """Paleisti ilgą darbą (transkripciją) atskirai nuo lango / ikonos: per `systemd-run --user` (savas cgroup —
    neužmuš uždarius langą ar perkrovus ikoną); be systemd-run (ar testuose) — nauja sesija. env — papildomi kintamieji."""
    import shutil
    import time
    extra = {"PYTHONPATH": str(paths.REPO), **(env or {})}
    for k in ("DIKTATURA_CONFIG_DIR", "DIKTATURA_DATA", "DIKTATURA_STATE", "DIKTATURA_RUN"):
        if os.environ.get(k):
            extra.setdefault(k, os.environ[k])          # ta pati aplinka (testai / kitas duomenų katalogas)
    if shutil.which("systemd-run") and not os.environ.get("DIKTATURA_SYSTEMCTL"):
        unit = f"diktatura-{name}-{int(time.time() * 1000)}"
        subprocess.Popen(["systemd-run", "--user", "--collect", "--quiet", f"--unit={unit}",
                          *[f"--setenv={k}={v}" for k, v in extra.items()], "--", *cmd],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                         env={**os.environ, **extra}, cwd=str(paths.REPO))


def units_dir() -> Path:
    return Path(os.environ.get("DIKTATURA_SYSTEMD_DIR") or Path.home() / ".config" / "systemd" / "user")


def render_unit(name: str) -> str:
    """systemd/<name>.in su @REPO@ -> šio repo kelias (taip, kaip daro `make install-units`)."""
    return (paths.REPO / "systemd" / f"{name}.in").read_text(encoding="utf-8").replace("@REPO@", str(paths.REPO))


def install_units() -> tuple:
    """Kaip `make install-units`: šablonai -> <systemd user>/ + daemon-reload. -> (ok, pranešimas)."""
    d = units_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        for u in UNITS:
            (d / u).write_text(render_unit(u), encoding="utf-8")
    except OSError as e:
        return False, f"servisų įdiegti nepavyko: {e}"
    r = systemctl("daemon-reload")
    return r.returncode == 0, "servisai įdiegti / atnaujinti" if r.returncode == 0 else (r.stderr or r.stdout).strip()


def set_sources_timer(enabled: bool) -> tuple:
    """Sekamų aplankų timer'is (diktatura-sources.timer). Jei unit'ų dar nėra (senas diegimas) — įdiegiami."""
    if enabled and units_status().get(SOURCES_TIMER) != "ok":
        ok, m = install_units()
        if not ok:
            return False, m
    r = systemctl("enable" if enabled else "disable", "--now", SOURCES_TIMER)
    if r.returncode != 0:
        return False, f"sekamų aplankų timer'io {'įjungti' if enabled else 'išjungti'} nepavyko: " \
                      f"{(r.stderr or r.stdout).strip()}"
    return True, f"sekami aplankai {'tikrinami kas ~2 min' if enabled else 'nebetikrinami'}"


def units_status() -> dict:
    """{unit: 'ok' | 'missing' | 'stale'} — ar įdiegti unit'ai atitinka šablonus."""
    out = {}
    for u in UNITS:
        f = units_dir() / u
        if not f.exists():
            out[u] = "missing"
        else:
            out[u] = "ok" if f.read_text(encoding="utf-8") == render_unit(u) else "stale"
    return out
