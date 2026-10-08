"""Diktatūra — nuolat įkrautas ASR serveris (nebūtinas: nustatymas ASR_SERVER=1, systemd diktatura-asr.service).

Kam: kiekviena transkripcija atskiru procesu kas kartą krauna modelį (Ąžuolas ~3 GB: nuo disko — dešimtys
sekundžių). Serveris laiko modelį atmintyje, todėl trumpi VOX diktavimai tekstą gauna greičiau. Po
ASR_SERVER_IDLE_MIN minučių be darbo modelis IŠKRAUNAMAS (RAM grąžinama) — kitas darbas jį vėl užkrauna.

Protokolas: Unix lizdas <runtime>/asr.sock; viena JSON eilutė į kiekvieną pusę:
  -> {"module": "named" | "mono", "argv": ["<garsas>", "--model", "azuolas-ct2", "--threads", "6"]}
  <- {"ok": true, "rc": 0, "log": "<modulio išvestis>", "load_sec": 0.0}
Darbai vykdomi po vieną (o transcribe-file.sh dar laiko ir flock eilę). Klientas — diktatura.asr.client.
Paleidimas: python -m diktatura.asr.server   (prioritetas — kaip transkripcijos: systemd Nice=19, IO idle)
"""
import contextlib
import gc
import io
import json
import os
import signal
import socket
import threading
import time
import traceback

from diktatura import config, debug, paths

MODULES = {"named": "diktatura.asr.transcribe_named", "mono": "diktatura.asr.transcribe"}


def socket_path():
    return paths.RUN_DIR / "asr.sock"


class ModelCache:
    """Vienas įkrautas modelis (raktas: vardas, compute, gijos); iškraunamas po idle_sec be darbo."""

    def __init__(self, loader, idle_sec: float):
        self.loader, self.idle_sec = loader, idle_sec
        self.key = self.model = None
        self.last_used = time.monotonic()
        self.lock = threading.Lock()
        self.loads = 0

    def get(self, name, compute, threads):
        key = (name, compute, int(threads))
        if self.model is None or self.key != key:
            self.model = None
            gc.collect()
            t0 = time.monotonic()
            self.model = self.loader(name, compute, int(threads))
            self.key = key
            self.loads += 1
            debug.log("asr-server", f"modelis {name} užkrautas per {time.monotonic() - t0:.1f}s")
        self.last_used = time.monotonic()
        return self.model

    def unload_if_idle(self) -> bool:
        with self.lock:
            if self.model is not None and time.monotonic() - self.last_used >= self.idle_sec:
                self.model = self.key = None
                gc.collect()
                debug.log("asr-server", "modelis iškrautas (ilgai be darbo)")
                return True
        return False


def handle(req: dict, cache: ModelCache) -> dict:
    """Įvykdyti vieną užklausą (modulio run() su talpyklos modeliu); išvestis grąžinama kaip log."""
    import importlib
    mod = MODULES.get(req.get("module"))
    if mod is None or not isinstance(req.get("argv"), list):
        return {"ok": False, "rc": 2, "log": f"bloga užklausa: {req!r}"}
    buf = io.StringIO()
    loads_before = cache.loads
    t0 = time.monotonic()
    with cache.lock, contextlib.redirect_stdout(buf):
        try:
            rc = importlib.import_module(mod).run([str(a) for a in req["argv"]], get_model=cache.get)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
            if not isinstance(e.code, int) and e.code:
                print(e.code)
        except Exception:
            rc = 1
            print(traceback.format_exc())
        cache.last_used = time.monotonic()
    return {"ok": rc == 0, "rc": rc or 0, "log": buf.getvalue(), "loaded": cache.loads > loads_before,
            "sec": round(time.monotonic() - t0, 2)}


def serve(cache: ModelCache, sock_path, stop: threading.Event = None, ready: threading.Event = None) -> None:
    stop = stop or threading.Event()
    sock_path = os.fspath(sock_path)
    os.makedirs(os.path.dirname(sock_path), exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(sock_path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    os.chmod(sock_path, 0o600)
    srv.listen(4)
    srv.settimeout(1.0)
    if ready:
        ready.set()
    n = 0
    try:
        while not stop.is_set():
            n += 1
            if n % 10 == 0:                      # nustatymas ASR_SERVER_IDLE_MIN — gyvai (kas ~10 s)
                with contextlib.suppress(Exception):
                    cache.idle_sec = config.load()["ASR_SERVER_IDLE_MIN"] * 60
            cache.unload_if_idle()
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            with conn:
                conn.settimeout(None)
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                try:
                    resp = handle(json.loads(data.decode("utf-8")), cache)
                except ValueError as e:
                    resp = {"ok": False, "rc": 2, "log": f"bloga JSON užklausa: {e}"}
                with contextlib.suppress(OSError):
                    conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        srv.close()
        with contextlib.suppress(FileNotFoundError):
            os.unlink(sock_path)


def main() -> int:
    from diktatura.asr import models
    paths.ensure_dirs()
    idle = config.load()["ASR_SERVER_IDLE_MIN"] * 60
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    print(f"ASR serveris: {socket_path()} (modelis iškraunamas po {idle / 60:g} min be darbo)", flush=True)
    serve(ModelCache(models.load, idle), socket_path(), stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
