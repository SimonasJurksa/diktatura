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


RUNNING_CODE = {TRAY: ("diktatura/ui", "diktatura/paths.py", "diktatura/config.py", "diktatura/progress.py",
                       "diktatura/sources.py", "diktatura/services.py", "diktatura/speakers/store.py"),
                RECORDERS["vox"]: ("diktatura/audio/vox.py", "diktatura/pause.py", "diktatura/config.py", "diktatura/paths.py"),
                RECORDERS["slack"]: ("bin/autorecord.sh", "bin/common.sh"),
                ASR: ("diktatura/asr", "diktatura/speakers", "diktatura/audio", "diktatura/progress.py")}
RESTART_CMD = {TRAY: "make tray-restart", RECORDERS["vox"]: "make restart", RECORDERS["slack"]: "make restart",
               ASR: "make asr-server-on"}


def code_mtime(parts) -> float:
    """Naujausias kodo failo keitimo laikas (katalogas — rekursyviai .py / .sh)."""
    newest = 0.0
    for part in parts:
        p = paths.REPO / part
        files = [f for f in p.rglob("*") if f.suffix in (".py", ".sh")] if p.is_dir() else [p]
        for f in files:
            try:
                newest = max(newest, f.stat().st_mtime)
            except OSError:
                pass
    return newest


def unit_started(unit: str):
    """Kada servisas paleistas (s nuo epochos) — iš jo pagrindinio proceso; neveikia / nežinoma -> None."""
    r = systemctl("show", "-p", "MainPID", "--value", unit)
    pid = r.stdout.strip() if r.returncode == 0 else ""
    if not pid.isdigit() or int(pid) <= 0:
        return None
    from diktatura import progress
    p = progress.scan_procs().get(int(pid))
    return p.start if p else None


def stale_units(started=None, code=None) -> list:
    """[(unit, komanda)] — veikiantys servisai, paleisti ANKSČIAU nei paskutinis jų kodo pakeitimas (seną kodą
    vykdo tol, kol neperkrauti). started / code — testams: {unit: laikas}."""
    out = []
    for unit, parts in RUNNING_CODE.items():
        t = (started or {}).get(unit) if started is not None else unit_started(unit)
        if t is None:
            continue
        c = (code or {}).get(unit) if code is not None else code_mtime(parts)
        if c and c > t + 1:
            out.append((unit, RESTART_CMD[unit]))
    return out


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


# ── make off / make on: viską išjungti, kai trūksta resursų, ir grąžinti tai, kas buvo įjungta ──
POWER_UNITS = (RECORDERS["vox"], RECORDERS["slack"], TIMER, SOURCES_TIMER, ASR, TRAY)
POWER_LABELS = {RECORDERS["vox"]: "įrašymas VOX", RECORDERS["slack"]: "įrašymas Slack", TIMER: "naktinis 01:30",
                SOURCES_TIMER: "sekami aplankai", ASR: "ASR serveris", TRAY: "ikona"}
JOB_UNITS = ("diktatura-nightly.service", "diktatura-sources.service")   # vykstančios transkripcijos (cgroup)
APP_ID = "lt.diktatura.Diktatura"                                        # = diktatura.ui.app.APP_ID (čia be gi)


def power_file() -> Path:
    return paths.STATE_DIR / "off.json"


def power_state():
    """Ką `make off` išjungė: {"units": [...], "at": "..."} arba None (neišjungta)."""
    import json
    try:
        d = json.loads(power_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("units"), list) else None
    except (OSError, ValueError):
        return None


def close_window() -> bool:
    """Uždaryti atidarytą langą (Gtk.Application „quit" veiksmas per D-Bus). Lango nėra — False."""
    app_id = os.environ.get("DIKTATURA_APP_ID") or APP_ID
    cmd = shlex.split(os.environ.get("DIKTATURA_GDBUS") or "gdbus") + [
        "call", "--session", "--dest", app_id, "--object-path", "/" + app_id.replace(".", "/"),
        "--method", "org.gtk.Actions.Activate", "quit", "[]", "{}"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def power_off() -> tuple:
    """Viską išjungti (ir po perkrovimo): įrašymą, naktinį, sekamus aplankus, ASR serverį, ikoną, langą ir vykstančias
    transkripcijas (garsas lieka — tekstą padarys vėliau). Kas buvo įjungta — įsimenama `make on`. -> (ok, pranešimas)."""
    import json
    from datetime import datetime

    from diktatura import progress
    was = [u for u in POWER_UNITS if is_enabled(u) or is_active(u)]
    if was:                                       # antras `make off` iš eilės neperrašo įsimintos būsenos tuščia
        f = power_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"units": was, "at": datetime.now().isoformat(timespec="seconds")},
                                ensure_ascii=False), encoding="utf-8")
    lines = []
    snap = progress.snapshot()
    if snap.active:
        lines.append(progress.stop_all(snap))
    r = systemctl("disable", "--now", *POWER_UNITS)
    systemctl("stop", *JOB_UNITS)
    if close_window():
        lines.append("langas uždarytas")
    if r.returncode != 0:
        return False, f"išjungti nepavyko: {(r.stderr or r.stdout).strip()}"
    off = ", ".join(POWER_LABELS[u] for u in was) or "jau buvo išjungta"
    return True, "\n".join([f"⏻ Diktatūra išjungta: {off}", *lines, "Įjungti atgal: make on"])


def power_on() -> tuple:
    """Grąžinti tai, ką išjungė `make off`. Be įsimintos būsenos — paleidžia tai, kas įjungta (enabled)."""
    st = power_state()
    units = [u for u in (st or {}).get("units", []) if u in POWER_UNITS] or [u for u in POWER_UNITS if is_enabled(u)]
    if not units:
        return False, "Nėra ką įjungti (make off nenaudotas, nė vienas servisas neįjungtas): " \
                      "make mode-vox (arba mode-slack), make nightly-on, make tray-on"
    r = systemctl("enable", "--now", *units)
    if r.returncode != 0:
        return False, f"įjungti nepavyko: {(r.stderr or r.stdout).strip()} (make install-units?)"
    power_file().unlink(missing_ok=True)
    return True, f"⏻ Diktatūra įjungta: {', '.join(POWER_LABELS[u] for u in units)}"


def main(argv=None) -> int:
    import sys
    args = sys.argv[1:] if argv is None else argv
    if args not in (["off"], ["on"]):
        print("Naudojimas: python3 -m diktatura.services off|on", file=sys.stderr)
        return 2
    ok, msg = power_off() if args == ["off"] else power_on()
    print(msg, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
