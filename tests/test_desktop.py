"""N. Programų meniu / doko paleidiklis: make desktop (desktop/diktatura.desktop.in) ir bin/diktatura-open.sh."""
import configparser
import os
import shutil
import subprocess

import pytest

from testenv import HELPERS, REPO


def test_n1_make_desktop_installs_valid_launcher(env, tmp_path):
    apps = tmp_path / "apps"
    r = subprocess.run(["make", "-s", "-C", str(REPO), "desktop"], capture_output=True, text=True,
                       env={**os.environ, "DIKTATURA_APPS_DIR": str(apps)}, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    f = apps / "diktatura.desktop"
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(f, encoding="utf-8")
    e = cp["Desktop Entry"]
    assert e["Name"] == "Diktatūra" and e["Type"] == "Application" and e["StartupWMClass"] == "diktatura"
    assert e["Exec"] == str(REPO / "bin" / "diktatura-open.sh") and os.access(e["Exec"], os.X_OK)
    assert (REPO / "icons" / "diktatura-idle.png") == type(REPO)(e["Icon"]) and type(REPO)(e["Icon"]).exists()
    if shutil.which("desktop-file-validate"):
        v = subprocess.run(["desktop-file-validate", str(f)], capture_output=True, text=True)
        assert v.returncode == 0, v.stdout + v.stderr


def test_n2_open_script_restores_icon_and_opens_window(env, tmp_path):
    """Paspaudus „Diktatūra" doke: ikona (diktatura-tray) įjungiama, langas atidaromas norimoje skiltyje."""
    fake = tmp_path / "sd"
    py = tmp_path / "fake-python"
    log = tmp_path / "ui_args"
    py.write_text(f"#!/usr/bin/env bash\necho \"$@\" > {log}\n")
    py.chmod(0o755)
    e = {**os.environ, "DIKTATURA_SYSTEMCTL": str(HELPERS / "fakebin" / "systemctl-fake"), "FAKE_SYSTEMD": str(fake),
         "DIKTATURA_UI_PYTHON": str(py)}
    for page, want in ((None, "text"), ("training", "training")):
        r = subprocess.run(["bash", str(REPO / "bin" / "diktatura-open.sh")] + ([page] if page else []), env=e,
                           capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        assert log.read_text().split() == ["-m", "diktatura.ui.app", "--page", want]
    assert (fake / "diktatura-tray.service.active").exists() or (fake / "diktatura-tray.active").exists()
    assert "start diktatura-tray" in (fake / "calls").read_text()


@pytest.mark.parametrize("name", ["diktatura-idle.png"])
def test_n3_icon_in_repo(name):
    assert (REPO / "icons" / name).stat().st_size > 0
