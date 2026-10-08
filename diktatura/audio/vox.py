"""Diktatūra — VOX: balso aktyvumo įrašymas (diktavimui, be Slack).

Nuolat klauso mikrofono + sistemos garso (monitor). Kai garsas praeina vartus — pradeda STEREO įrašą
(L = mikrofonas, R = sistema); kai VOX_SILENCE_SEC tyla — uždaro. Trumpesni nei VOX_MIN_SEC atmetami.
Po uždarymo pagal nustatymus: immediate -> transkribuoja; deferred -> laukia 01:30; AUTOTRANSCRIBE=0 -> tik įrašas.

Architektūra: `VoxGate` — gryna logika (lygis dBFS per 100 ms gabalą -> sprendimas), testuojama be garso;
`main()` — I/O (ffmpeg capture, WAV rašymas, būsenos failas, transkripcijos paleidimas).
Paleidimas: python -m diktatura.audio.vox   (systemd: diktatura-vox.service)
Env (nebūtini): DIKTATURA_MIC, DIKTATURA_MONITOR — kiti garso įrenginiai (E2E testams);
  DIKTATURA_CAPTURE_CMD — komanda, kurios stdout = s16le stereo 16 kHz PCM, vietoj ffmpeg/pulse (testams).
Pauzė: kol Diktatūra pati groja garsą (Apmokymų perklausa, „▶ Groti nuo čia"), naujas įrašas nepradedamas, o
atidarytas uždaromas (diktatura.pause, <runtime>/pause) — kitaip perklausa būtų įrašyta kaip naujas pokalbis.
Išėjimo kodai: 0 — sustabdyta (SIGTERM/SIGINT); 3 — garso capture netikėtai baigėsi (systemd perkrauna).
"""
import datetime as dt
import fcntl
import os
import shlex
import signal
import subprocess
import sys
import wave
from collections import deque

import numpy as np

from diktatura import config, debug, pause, paths

SR = 16000
CHUNK = SR // 10          # 100 ms
CALIB = 20                # gabalų (2 s) kambario triukšmui išmokti prieš leidžiant įrašyti
PREROLL = 8               # 0.8 s prieš atsidarymą (kad nenukąstų pirmo žodžio)
NF_WINDOW = 50            # ~5 s triukšmo grindų langas (mokomasi tik budint)
CONFIG_EVERY = 50         # nustatymai perskaitomi kas ~5 s (keitimai be restarto)
PAUSE_EVERY = 5           # pauzė (Diktatūra pati groja garsą) tikrinama kas 0.5 s


def rms_db(x: np.ndarray) -> float:
    if x.size == 0:
        return -120.0
    r = np.sqrt(np.mean((x.astype(np.float64) / 32768.0) ** 2))
    return float(20 * np.log10(r + 1e-9))


class VoxGate:
    """Gryna VOX vartų logika su histereze ir adaptyviu triukšmo lygiu.

    step(level) grąžina: "idle" (nerašoma), "open" (pradėti įrašą), "write" (rašyti), "close" (uždaryti).
    Adaptyvus: slenkstis = triukšmo grindys (25-tas percentilis) + atsarga; grindys mokomos tik budint.
    Trumpumo patikra (long_enough) skaičiuoja tik GARSO trukmę — nuo atsidarymo iki paskutinio gabalo virš
    išlaikymo slenksčio, be pre-roll ir be tylos uodegos (kitaip kosulys + 5 s tylos = „6 s įrašas").
    """

    def __init__(self, cfg: dict, preroll_chunks: int = PREROLL):
        self.preroll_chunks = preroll_chunks
        self.nf_win = deque(maxlen=NF_WINDOW)
        self.nf = -55.0
        self.recording = False
        self.sil = 0
        self.rec_chunks = 0       # visas failas: pre-roll + garsas + tylos uodega
        self.since_open = 0       # gabalai nuo atsidarymo (imtinai)
        self.voiced = 0           # gabalai nuo atsidarymo iki paskutinio garsaus
        self.idle_run = 0         # „idle" gabalai iš eilės (tiek pre-roll realiai turi)
        self.update_config(cfg)

    def update_config(self, cfg: dict) -> None:
        self.adaptive = bool(cfg["VOX_ADAPTIVE"])
        self.open_m = float(cfg["VOX_OPEN_MARGIN"])
        self.close_m = float(cfg["VOX_CLOSE_MARGIN"])
        self.fix_open = float(cfg["VOX_GATE_DB"])
        self.fix_close = self.fix_open - 12
        self.sil_limit = max(1, int(round(float(cfg["VOX_SILENCE_SEC"]) * 10)))
        self.min_chunks = int(round(float(cfg["VOX_MIN_SEC"]) * 10))

    def thresholds(self) -> tuple:
        if self.adaptive:
            return self.nf + self.open_m, self.nf + self.close_m
        return self.fix_open, self.fix_close

    def step(self, level: float) -> str:
        if self.adaptive and self.nf_win:
            self.nf = float(np.percentile(self.nf_win, 25))
        open_thr, close_thr = self.thresholds()
        if not self.recording:
            self.nf_win.append(level)
            if (not self.adaptive or len(self.nf_win) >= CALIB) and level > open_thr:
                self.recording, self.sil = True, 0
                self.rec_chunks = min(self.preroll_chunks, self.idle_run) + 1
                self.since_open = self.voiced = 1
                self.idle_run = 0
                return "open"
            self.idle_run += 1                     # (adaptyviame režime pirmos 2 s — kalibracija)
            return "idle"
        self.rec_chunks += 1
        self.since_open += 1
        if level > close_thr:                      # tyli kalba virš išlaikymo slenksčio laiko atvirą
            self.sil = 0
            self.voiced = self.since_open
            return "write"
        self.sil += 1
        if self.sil >= self.sil_limit:
            self.recording = False
            self.idle_run = 0                      # main() išvalo pre-roll po uždarymo
            return "close"
        return "write"

    def pause_reset(self) -> None:
        """Pauzė (Diktatūra groja garsą): įrašas nebetęsiamas, skaitikliai nuo nulio. Triukšmo grindys lieka
        tos pačios — grojamas garsas jų nemoko (pauzės metu step() nekviečiamas)."""
        self.recording = False
        self.sil = self.idle_run = self.since_open = 0

    def long_enough(self) -> bool:
        return self.voiced >= self.min_chunks

    @property
    def duration(self) -> float:
        """Viso failo trukmė (s)."""
        return self.rec_chunks / 10.0

    @property
    def voiced_duration(self) -> float:
        """Garso trukmė (s): nuo atsidarymo iki paskutinio garsaus gabalo."""
        return self.voiced / 10.0


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%F %T} [vox] {msg}"
    print(line, flush=True)
    try:
        with open(paths.LOG_AUTOREC, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def notify(title: str, body: str) -> None:
    subprocess.run(["notify-send", title, body], check=False, stderr=subprocess.DEVNULL)


class Stop(Exception):
    """SIGTERM/SIGINT: baigti švariai (uždaryti wav, išvalyti būseną)."""


def _on_signal(*_):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)     # antras signalas nebenutrauks valymo
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise Stop()


def capture_cmd() -> tuple:
    """(komanda, aprašas) — iš kur skaityti stereo PCM (L = mikrofonas, R = sistemos garsas)."""
    if os.environ.get("DIKTATURA_CAPTURE_CMD"):
        return shlex.split(os.environ["DIKTATURA_CAPTURE_CMD"]), "DIKTATURA_CAPTURE_CMD"
    mic = os.environ.get("DIKTATURA_MIC") or subprocess.check_output(
        ["pactl", "get-default-source"], text=True).strip()
    mon = os.environ.get("DIKTATURA_MONITOR") or subprocess.check_output(
        ["pactl", "get-default-sink"], text=True).strip() + ".monitor"
    filt = ("[0:a]pan=mono|c0=0.5*c0+0.5*c1[l];[1:a]pan=mono|c0=0.5*c0+0.5*c1[r];"
            "[l][r]join=inputs=2:channel_layout=stereo[a]")
    # thread_queue_size + didelis pipe buferis: transkripcijos apkrova neturi numesti garso (capture badavimas)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-thread_queue_size", "8192", "-f", "pulse", "-i", mic,
           "-thread_queue_size", "8192", "-f", "pulse", "-i", mon,
           "-filter_complex", filt, "-map", "[a]", "-ac", "2", "-ar", str(SR), "-f", "s16le", "pipe:1"]
    return cmd, f"mic={mic}, sistema={mon}"


def main() -> int:
    paths.ensure_dirs()
    config.ensure()
    gate = VoxGate(config.load())
    cmd, devices = capture_cmd()
    ff = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        fcntl.fcntl(ff.stdout.fileno(), getattr(fcntl, "F_SETPIPE_SZ", 1031), 1048576)
    except OSError:
        pass
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    mode = "ADAPTYVUS" if gate.adaptive else "FIKSUOTAS"
    log(f"VOX startavo ({mode}: +{gate.open_m}/+{gate.close_m} dB, tyla={gate.sil_limit / 10}s, "
        f"min={gate.min_chunks / 10}s, {devices})")
    debug.log("vox", f"capture: {' '.join(cmd)}")
    cfg_now = config.load()

    nbytes = CHUNK * 2 * 2   # stereo s16le
    preroll = deque(maxlen=PREROLL)
    wav = cur = None
    n = 0
    stopping = False
    paused = False
    try:
        while True:
            buf = ff.stdout.read(nbytes)
            if not buf or len(buf) < nbytes:
                log("⚠ garso capture baigėsi (įrenginys dingo?) — išeinu, systemd perkraus")
                break
            n += 1
            if n % CONFIG_EVERY == 0:
                new_cfg = config.load()
                if new_cfg != cfg_now:
                    debug.log("vox", "nustatymai pasikeitė: " + ", ".join(
                        f"{k}={new_cfg[k]}" for k in new_cfg if new_cfg[k] != cfg_now.get(k)))
                    cfg_now = new_cfg
                gate.update_config(new_cfg)
            if n % PAUSE_EVERY == 0 and pause.active() != paused:
                paused = not paused
                if paused:
                    log("⏸ įrašymas pristabdytas — Diktatūra pati groja garsą (perklausa)")
                    if wav is not None:          # įrašas iki perklausos išsaugomas kaip įprastai
                        wav.close()
                        paths.STATE_RECORDING.unlink(missing_ok=True)
                        finish(cur, gate)
                        wav = cur = None
                else:
                    log("▶ įrašymas vėl veikia (perklausa baigta)")
                gate.pause_reset()
                preroll.clear()
            if paused:
                continue                         # grojamas garsas: nerašom, triukšmo lygio nesimokom
            a = np.frombuffer(buf, dtype=np.int16).reshape(-1, 2)
            lv_l, lv_r = rms_db(a[:, 0]), rms_db(a[:, 1])
            decision = gate.step(max(lv_l, lv_r))
            if (n % 10 == 0 or decision in ("open", "close")) and debug.enabled():
                o, c = gate.thresholds()
                debug.log("vox", f"L={lv_l:6.1f} R={lv_r:6.1f} dB  triukšmas={gate.nf:6.1f}  "
                                 f"atsidaro>{o:6.1f} laiko>{c:6.1f}  {decision}"
                                 + (f" tyla={gate.sil / 10:.1f}s" if gate.recording else ""))
            if decision == "idle":
                preroll.append(buf)
            elif decision == "open":
                cur = paths.RECORDINGS / f"vox_{dt.datetime.now():%Y%m%d_%H%M%S}.wav"
                wav = wave.open(str(cur), "wb")
                wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(SR)
                for ch in preroll:
                    wav.writeframes(ch)
                wav.writeframes(buf)
                paths.STATE_RECORDING.write_text(f"vox {cur}")
                log(f"🔴 garsas aptiktas (triukšmas≈{gate.nf:.0f} dB) → {cur.name}")
                notify("🔴 VOX įrašymas", cur.name)
            elif decision == "write":
                wav.writeframes(buf)
            elif decision == "close":
                wav.writeframes(buf)
                wav.close()
                paths.STATE_RECORDING.unlink(missing_ok=True)
                finish(cur, gate)
                wav = cur = None
                preroll.clear()
    except Stop:
        stopping = True
    finally:
        if wav is not None:
            wav.close()
            paths.STATE_RECORDING.unlink(missing_ok=True)
            finish(cur, gate, stopping=True)
        if ff.poll() is None:
            ff.terminate()
            try:
                ff.wait(timeout=3)
            except subprocess.TimeoutExpired:
                ff.kill()
        log("VOX sustabdytas")
    return 0 if stopping else 3


def finish(cur, gate: VoxGate, stopping: bool = False) -> None:
    """Uždarytas įrašas: per trumpas -> trinti; kitaip pagal nustatymus — transkribuoti dabar ar vėliau.
    stopping: servisas stabdomas — transkripcijos nepaleidžiam (systemd ją nužudytų kartu su servisu);
    įrašą paims naktinis / `make transcribe-pending`."""
    if not gate.long_enough():
        log(f"per trumpas (garso {gate.voiced_duration:.1f}s < {gate.min_chunks / 10:g}s) — trinu {cur.name}")
        cur.unlink(missing_ok=True)
        return
    log(f"🛑 {'sustabdyta' if stopping else 'tyla'} → uždaryta {cur.name} ({gate.duration:.0f}s)")
    notify("🛑 VOX baigta", f"{cur.name} {gate.duration:.0f}s")
    cfg = config.load()
    if stopping:
        log(f"⏸ servisas stabdomas — {cur.name} transkribuos naktinis / make transcribe-pending")
    elif not cfg["AUTOTRANSCRIBE"]:
        log(f"⏸ auto-transkripcija išjungta — {cur.name} liko be teksto")
    elif cfg["MODE"] == "deferred":
        log(f"🌙 deferred — {cur.name} transkribuos naktį (01:30)")
    else:
        subprocess.Popen(["bash", str(paths.BIN / "transcribe-file.sh"), str(cur)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    sys.exit(main())
