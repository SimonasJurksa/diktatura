"""Diktatūra — ASR serverio klientas (naudoja bin/transcribe-file.sh, kai ASR_SERVER=1).

    python -m diktatura.asr.client <named|mono> <garsas> [modulio argumentai...]

Išėjimo kodai: modulio kodas (0 — gerai); 75 — serverio nėra / neatsako (transcribe-file.sh tada transkribuoja
pats, atskiru procesu). Modulio išvestis spausdinama (patenka į transcribe.log). Tik stdlib — greitas startas.
"""
import json
import socket
import sys

from diktatura import paths

UNAVAILABLE = 75


def request(module: str, argv: list, sock_path=None, timeout=None) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(str(sock_path or paths.RUN_DIR / "asr.sock"))
    s.settimeout(timeout)                    # transkripcija gali trukti ilgai
    with s:
        s.sendall((json.dumps({"module": module, "argv": argv}) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode("utf-8"))


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] not in ("named", "mono"):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        resp = request(args[0], args[1:])
    except (OSError, ValueError) as e:
        print(f"ASR serveris nepasiekiamas ({e}) — transkribuosiu atskiru procesu", file=sys.stderr)
        return UNAVAILABLE
    sys.stdout.write(resp.get("log", ""))
    print(f"(ASR serveris: {'modelis užkrautas' if resp.get('loaded') else 'modelis jau buvo atmintyje'}, "
          f"{resp.get('sec', '?')} s)")
    return int(resp.get("rc", 1))


if __name__ == "__main__":
    raise SystemExit(main())
