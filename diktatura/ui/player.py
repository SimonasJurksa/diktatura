"""Diktatūra — garso grojimas nuo nurodyto laiko (teksto lange: „▶ Groti nuo čia").

ffplay (ffmpeg paketas) be lango; stereo įrašas (L = tu, R = kolegos) sumaišomas į abi ausis.
Pozicija skaičiuojama: pradžia + praėjęs laikas (užtenka eilutei paryškinti).
Testams: DIKTATURA_SEEK_PLAYER — komandos šablonas su {start} ir {file} (garsas negroja).
"""
import os
import shlex
import subprocess
import time

MIX = "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1"


def command(path: str, start: float) -> list:
    tpl = os.environ.get("DIKTATURA_SEEK_PLAYER")
    if tpl:
        return [a.format(start=f"{start:.2f}", file=path) for a in shlex.split(tpl)]
    return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-ss", f"{start:.2f}", "-af", MIX, path]


class SeekPlayer:
    def __init__(self):
        self.proc = None
        self.file = None
        self.start = 0.0
        self.t0 = 0.0

    def play(self, path, start: float = 0.0) -> None:
        self.stop()
        self.proc = subprocess.Popen(command(str(path), max(0.0, start)),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.file, self.start, self.t0 = path, max(0.0, start), time.monotonic()

    def playing(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def position(self) -> float:
        return self.start + (time.monotonic() - self.t0) if self.playing() else self.start

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
