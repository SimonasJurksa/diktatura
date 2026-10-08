"""UI testai: GTK per broadway (atskiras „ekranas" atmintyje) — langai NErodomi tavo darbalaukyje.

GDK_BACKEND nustatomas importuojant šį conftest — PRIEŠ bet kokį Gtk importą. Sistemos gi pasiekiamas iš .venv
(tas pats /usr/bin/python3.10 interpretatorius): /usr/lib/python3/dist-packages pridedamas sąrašo GALE
(.venv paketai lieka pirmenybėje).
"""
import atexit
import os
import shutil
import socket
import subprocess
import sys
import time

import pytest

DIST = "/usr/lib/python3/dist-packages"


def _free_display():
    for n in range(41, 80):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", 8080 + n))
                return n
            except OSError:
                continue
    raise RuntimeError("nėra laisvo broadway prievado")


_BROADWAY = None
if shutil.which("broadwayd"):
    _n = _free_display()
    _BROADWAY = subprocess.Popen(["broadwayd", f":{_n}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(_BROADWAY.kill)
    time.sleep(0.5)
    os.environ["GDK_BACKEND"] = "broadway"
    os.environ["BROADWAY_DISPLAY"] = f":{_n}"
    os.environ.pop("DISPLAY", None)
    os.environ.pop("WAYLAND_DISPLAY", None)
if DIST not in sys.path:
    sys.path.append(DIST)


def pytest_collection_modifyitems(items):
    for it in items:
        if "/tests/ui/" in str(it.fspath):
            it.add_marker(pytest.mark.ui)


@pytest.fixture(scope="session", autouse=True)
def gtk_ready():
    if _BROADWAY is None:
        pytest.skip("nėra broadwayd (libgtk-3-bin)")
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    assert Gtk.init_check()[0], "GTK nepasileido (broadway)"
    yield
