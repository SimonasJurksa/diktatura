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
Triukšmo lygis įrašo metu: jei ~10 s įrašo — pastovus fonas garsesnis už išlaikymo slenkstį, grindys pasenusios
(pvz. išmoktos, kai mikrofonas buvo nutilęs, o dabar ūžia ventiliatorius) — jos pakeliamos (VoxGate._refloor), kitaip
įrašas niekada nebeužsidarytų. Įrenginiai: kas ~10 s tikrinama, ar ffmpeg vis dar klauso numatytojo mikrofono ir
garsiakalbių monitoriaus (PulseAudio, dingus/atsiradus dokui, tyliai perkelia srautą — tada „sistemos" kanalas ima
rašyti mikrofoną); jei ne — įrašas uždaromas ir capture paleidžiamas iš naujo.
Pilnas diskas: naujas įrašas nepradedamas, kol laisvos vietos < MIN_FREE_MB (env DIKTATURA_MIN_FREE_MB); jei diskas
užsipildo įrašo viduryje (ENOSPC) — įrašas nutraukiamas, wav antraštė pataisoma pagal tai, kas spėjo įsirašyti (salvage),
ir VOX dirba toliau. Anksčiau čia nulūždavo, systemd perkraudavo, ir kiekvienas bandymas palikdavo 0 B wav.
Išėjimo kodai: 0 — sustabdyta (SIGTERM/SIGINT); 3 — garso capture netikėtai baigėsi (systemd perkrauna).
"""
import datetime as dt
import errno
import fcntl
import os
import re
import shlex
import shutil
import signal
import struct
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
NF_WINDOW = 50            # ~5 s triukšmo grindų langas (mokomasi budint)
REC_NF_WINDOW = 100       # ~10 s įrašo lygių langas: ar „tyla" įraše tikrai tyla (VoxGate._refloor)
REFLOOR_PCT = 10          # tyliausi 10 % lango gabalų = tikrasis fonas (kalboje visada būna pauzių)
STATIONARY_DB = 3         # mediana − 10-tas percentilis ≤ tiek -> lange pastovus garsas (fonas ~0.5–1 dB, kalba 7–12)
CONFIG_EVERY = 50         # nustatymai perskaitomi kas ~5 s (keitimai be restarto)
PAUSE_EVERY = 5           # pauzė (Diktatūra pati groja garsą) tikrinama kas 0.5 s
MIN_FREE_MB = 200         # mažiau laisvos vietos — naujas įrašas nepradedamas
DEVICE_EVERY = 100        # ~10 s: ar capture vis dar klauso tų įrenginių (žr. device_problem)
SWITCH_GAP = 600          # ~60 s tarp capture perjungimų (kad neblaškytų, jei PulseAudio kažkas nuolat keičia)
APP_MIC, APP_SYS = "diktatura-vox-mic", "diktatura-vox-sistema"   # pulse application.name kiekvienam srautui


def rms_db(x: np.ndarray) -> float:
    if x.size == 0:
        return -120.0
    r = np.sqrt(np.mean((x.astype(np.float64) / 32768.0) ** 2))
    return float(20 * np.log10(r + 1e-9))


class VoxGate:
    """Gryna VOX vartų logika su histereze ir adaptyviu triukšmo lygiu.

    step(level) grąžina: "idle" (nerašoma), "open" (pradėti įrašą), "write" (rašyti), "close" (uždaryti).
    Adaptyvus: slenkstis = triukšmo grindys (25-tas percentilis) + atsarga; grindys mokomos budint, o įrašo metu
    tik keliamos, jei pasenusios (_refloor) — kitaip garsesnis už jas fonas laikytų įrašą atvirą amžinai.
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
        self.rec_win = deque(maxlen=REC_NF_WINDOW)   # paskutiniai įrašo lygiai (be dabartinio gabalo)
        self.refloored = None     # (senos, naujos) grindys — main() užrašo į žurnalą ir išvalo
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
                self.rec_win.clear()
                self.rec_win.append(level)
                return "open"
            self.idle_run += 1                     # (adaptyviame režime pirmos 2 s — kalibracija)
            return "idle"
        self.rec_chunks += 1
        self.since_open += 1
        if self.adaptive and len(self.rec_win) >= REC_NF_WINDOW and self._refloor():
            open_thr, close_thr = self.thresholds()
        self.rec_win.append(level)
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

    def _refloor(self) -> bool:
        """Įrašo metu: jei paskutinės ~10 s didžioji dalis — pastovus garsas (mediana ≤ STATIONARY_DB virš tyliausių
        10 %), o net tyliausi gabalai garsesni už išlaikymo slenkstį, triukšmo grindys pasenusios (išmoktos tylesnėje
        aplinkoje / kai mikrofonas buvo nutilęs) ir fonas laikytų įrašą atvirą amžinai (2026-10-13: grindys −92 dB,
        ventiliatorius −66 dB -> 6 val. „įrašas"). Tada grindys pakeliamos iki to fono, o garso trukmė ir tylos
        skaitiklis perskaičiuojami lango gabalams pagal naują slenkstį: kalbai pasibaigus įrašas užsidaro kaip įprastai,
        o jei visas įrašas buvo tik fonas — iškart uždaromas ir (per trumpas) ištrinamas. Kalbos metu mediana daug
        aukščiau pauzių, tad čia nesuveikia. -> True, jei grindys pakeltos."""
        q = float(np.percentile(self.rec_win, REFLOOR_PCT))
        if q <= self.nf + self.close_m or float(np.percentile(self.rec_win, 50)) - q > STATIONARY_DB:
            return False
        self.refloored = (self.nf, q)
        self.nf = q
        self.nf_win.clear()
        self.nf_win.extend([q] * CALIB)            # budint grindys vėl leisis pačios, jei aplinka nurims
        close_thr = q + self.close_m
        win = list(self.rec_win)                    # win[i] = gabalas nr. start + i (nuo atsidarymo)
        start = self.since_open - len(win)
        loud = [i for i, lv in enumerate(win) if lv > close_thr]
        if loud:
            self.voiced = start + loud[-1]
        elif start <= 1:                            # langas apima visą įrašą — garso nebuvo
            self.voiced = 0
        else:
            self.voiced = min(self.voiced, start - 1)
        self.sil = self.since_open - 1 - self.voiced
        return True

    def pause_reset(self) -> None:
        """Pauzė (Diktatūra groja garsą): įrašas nebetęsiamas, skaitikliai nuo nulio. Triukšmo grindys lieka
        tos pačios — grojamas garsas jų nemoko (pauzės metu step() nekviečiamas)."""
        self.recording = False
        self.sil = self.idle_run = self.since_open = 0
        self.rec_win.clear()

    def recalibrate(self) -> None:
        """Kitas garso įrenginys: senos triukšmo grindys nebetinka — vėl 2 s kalibracija."""
        self.pause_reset()
        self.nf_win.clear()

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


def free_mb(path) -> float:
    try:
        return shutil.disk_usage(path).free / 2 ** 20
    except OSError:
        return float("inf")


def min_free_mb() -> float:
    try:
        return float(os.environ.get("DIKTATURA_MIN_FREE_MB", MIN_FREE_MB))
    except ValueError:
        return MIN_FREE_MB


def salvage(path) -> float:
    """Diskas užsipildė įrašo viduryje: wav antraštė dar nepataisyta (duomenų dydis 0). Ją perrašom pagal tai, kas
    spėjo įsirašyti — antraštė jau pirmame (išskirtame) bloke, naujos vietos nereikia. -> išsaugota trukmė s;
    < 1 s ar nepavyko -> failas ištrinamas, 0."""
    try:
        n = path.stat().st_size - 44
        if n >= SR * 4:
            n -= n % 4                               # tik pilni stereo s16 kadrai
            with open(path, "r+b") as fh:
                fh.seek(4)
                fh.write(struct.pack("<I", 36 + n))
                fh.seek(40)
                fh.write(struct.pack("<I", n))
            return n / (SR * 4)
    except OSError:
        pass
    try:
        path.unlink()
    except OSError:
        pass
    return 0.0


def close_quietly(wav) -> None:
    try:
        wav.close()
    except OSError:
        pass


class Stop(Exception):
    """SIGTERM/SIGINT: baigti švariai (uždaryti wav, išvalyti būseną)."""


def _on_signal(*_):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)     # antras signalas nebenutrauks valymo
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise Stop()


def pactl(*args) -> str:
    return subprocess.check_output(["pactl", *args], text=True, timeout=5, stderr=subprocess.DEVNULL,
                                   env={**os.environ, "LC_ALL": "C"})


def capture_devices() -> tuple:
    """(mikrofonas, monitorius) — pulse šaltinių vardai: env arba dabartiniai numatytieji."""
    mic = os.environ.get("DIKTATURA_MIC") or pactl("get-default-source").strip()
    mon = os.environ.get("DIKTATURA_MONITOR") or pactl("get-default-sink").strip() + ".monitor"
    return mic, mon


def capture_cmd(devs: tuple = None) -> tuple:
    """(komanda, aprašas) — iš kur skaityti stereo PCM (L = mikrofonas, R = sistemos garsas)."""
    if os.environ.get("DIKTATURA_CAPTURE_CMD"):
        return shlex.split(os.environ["DIKTATURA_CAPTURE_CMD"]), "DIKTATURA_CAPTURE_CMD"
    mic, mon = devs or capture_devices()
    filt = ("[0:a]pan=mono|c0=0.5*c0+0.5*c1[l];[1:a]pan=mono|c0=0.5*c0+0.5*c1[r];"
            "[l][r]join=inputs=2:channel_layout=stereo[a]")
    # thread_queue_size + didelis pipe buferis: transkripcijos apkrova neturi numesti garso (capture badavimas).
    # -name: atskiri pulse srautų vardai — pagal juos device_problem() tikrina, kur kuris srautas prijungtas
    # (anksčiau abu buvo „Lavf…", ir module-stream-restore juos laikė vienu)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-thread_queue_size", "8192", "-f", "pulse", "-name", APP_MIC, "-i", mic,
           "-thread_queue_size", "8192", "-f", "pulse", "-name", APP_SYS, "-i", mon,
           "-filter_complex", filt, "-map", "[a]", "-ac", "2", "-ar", str(SR), "-f", "s16le", "pipe:1"]
    return cmd, f"mic={mic}, sistema={mon}"


def parse_streams(outputs: str, sources: str, pid: int) -> dict:
    """`pactl list source-outputs` + `pactl list sources short` -> {application.name: šaltinio vardas} proceso pid
    įrašymo srautams."""
    names = {}
    for line in sources.splitlines():
        parts = line.split("\t")
        if len(parts) > 1 and parts[0].strip().isdigit():
            names[parts[0].strip()] = parts[1].strip()
    out = {}
    for block in re.split(r"^Source Output #", outputs, flags=re.M)[1:]:
        src = re.search(r"^\s*Source:\s*(\d+)", block, re.M)
        app = re.search(r'^\s*application\.name = "([^"]*)"', block, re.M)
        proc = re.search(r'^\s*application\.process\.id = "(\d+)"', block, re.M)
        if src and app and proc and int(proc.group(1)) == pid:
            out[app.group(1)] = names.get(src.group(1), f"#{src.group(1)}")
    return out


def mismatch(devs: tuple, want: tuple, streams: dict):
    """Ar capture klauso ne tų įrenginių? -> priežastis (tekstas) arba None. Gryna funkcija.
    devs — ko klausom dabar, want — dabartiniai numatytieji, streams — kur pulse realiai prijungė mūsų srautus."""
    for what, have, need in (("mikrofonas", devs[0], want[0]), ("garsiakalbiai", devs[1], want[1])):
        if have != need:
            return f"pasikeitė numatytieji {what}: {have} → {need}"
    for app, need, what in ((APP_MIC, devs[0], "mikrofono"), (APP_SYS, devs[1], "sistemos garso")):
        got = streams.get(app)
        if got is not None and got != need:
            return f"PulseAudio perkėlė {what} srautą į {got} (turi būti {need})"
    return None


def device_problem(pid: int, devs: tuple):
    """Kas ~10 s: ar ffmpeg vis dar klauso reikiamų įrenginių. 2026-10-13: po doko atjungimo/prijungimo PulseAudio
    perkėlė „sistemos garso" srautą į mikrofoną — R kanalas tyliai rašė mikrofoną (kolegų garso nebūtų). pactl
    nepasiekiamas -> None (nieko nekeičiam)."""
    try:
        return mismatch(devs, capture_devices(),
                        parse_streams(pactl("list", "source-outputs"), pactl("list", "sources", "short"), pid))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def start_capture(devs: tuple = None):
    cmd, desc = capture_cmd(devs)
    ff = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        fcntl.fcntl(ff.stdout.fileno(), getattr(fcntl, "F_SETPIPE_SZ", 1031), 1048576)
    except OSError:
        pass
    return ff, cmd, desc


def stop_capture(ff) -> None:
    if ff.poll() is None:
        ff.terminate()
        try:
            ff.wait(timeout=3)
        except subprocess.TimeoutExpired:
            ff.kill()
    if ff.stdout:
        ff.stdout.close()


def new_recording_path():
    """vox_YYYYMMDD_HHMMSS.wav; jei toks jau yra (uždaryta ir atidaryta tą pačią sekundę) — +1 s, kad neperrašytų."""
    t = dt.datetime.now()
    while True:
        p = paths.RECORDINGS / f"vox_{t:%Y%m%d_%H%M%S}.wav"
        if not p.exists():
            return p
        t += dt.timedelta(seconds=1)


def close_recording(wav, cur, gate) -> None:
    """Uždaryti atidarytą įrašą ne dėl tylos (pauzė, įrenginių perjungimas) — išsaugomas kaip įprastai."""
    try:
        wav.close()
    except OSError:                              # pilnas diskas uždarant
        salvage(cur)
        paths.STATE_RECORDING.unlink(missing_ok=True)
        return
    paths.STATE_RECORDING.unlink(missing_ok=True)
    finish(cur, gate)


def main() -> int:
    paths.ensure_dirs()
    config.ensure()
    gate = VoxGate(config.load())
    track = not os.environ.get("DIKTATURA_CAPTURE_CMD")      # testų sintetinis capture — įrenginių nesekam
    devs = capture_devices() if track else None
    ff, cmd, devices = start_capture(devs)
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
    disk_full = False
    switched = -SWITCH_GAP
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
            if track and n % DEVICE_EVERY == 0 and n - switched >= SWITCH_GAP:
                why = device_problem(ff.pid, devs)
                if why:
                    log(f"🔀 {why} — perjungiu garso capture")
                    if wav is not None:
                        close_recording(wav, cur, gate)
                        wav = cur = None
                    stop_capture(ff)
                    devs = capture_devices()
                    ff, cmd, devices = start_capture(devs)
                    log(f"🎧 klausau iš naujo: {devices}")
                    debug.log("vox", f"capture: {' '.join(cmd)}")
                    gate.recalibrate()
                    preroll.clear()
                    switched = n
                    continue
            if n % PAUSE_EVERY == 0 and pause.active() != paused:
                paused = not paused
                if paused:
                    log("⏸ įrašymas pristabdytas — Diktatūra pati groja garsą (perklausa)")
                    if wav is not None:          # įrašas iki perklausos išsaugomas kaip įprastai
                        close_recording(wav, cur, gate)
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
            if gate.refloored:
                old, new = gate.refloored
                gate.refloored = None
                log(f"↕ fonas garsesnis nei išmoktas triukšmo lygis ({old:.0f} → {new:.0f} dB) — perskaičiuota, "
                    "kas yra tyla")
            if (n % 10 == 0 or decision in ("open", "close")) and debug.enabled():
                o, c = gate.thresholds()
                debug.log("vox", f"L={lv_l:6.1f} R={lv_r:6.1f} dB  triukšmas={gate.nf:6.1f}  "
                                 f"atsidaro>{o:6.1f} laiko>{c:6.1f}  {decision}"
                                 + (f" tyla={gate.sil / 10:.1f}s" if gate.recording else ""))
            if decision == "open":
                free, need = free_mb(paths.RECORDINGS), min_free_mb()
                if free < need:
                    if not disk_full:
                        log(f"⚠ diske liko tik {free:.0f} MB — naujų įrašų nepradedu, kol neatsiras ≥ {need:.0f} MB "
                            "(atlaisvink vietos; įrašų garsui — Nustatymai → Archyvas → „Seno garso trynimas\")")
                        notify("⚠ Diktatūra: diskas pilnas", "Įrašymas sustabdytas, kol neatsiras vietos")
                    disk_full = True
                    gate.pause_reset()
                    decision = "idle"
                elif disk_full:
                    disk_full = False
                    log(f"✓ vietos vėl yra ({free:.0f} MB) — įrašau")
            try:
                if decision == "idle":
                    preroll.append(buf)
                elif decision == "open":
                    cur = new_recording_path()
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
            except OSError as e:
                if e.errno != errno.ENOSPC:
                    raise
                if wav is not None:
                    close_quietly(wav)
                saved = salvage(cur) if cur is not None else 0.0
                paths.STATE_RECORDING.unlink(missing_ok=True)
                log(f"⚠ diskas pilnas — įrašas {cur.name if cur else ''} nutrauktas; "
                    + (f"išsaugota {saved:.0f} s (transkribuos naktinis / make transcribe-pending)" if saved
                       else "nieko neišsaugota, failas ištrintas"))
                notify("⚠ Diktatūra: diskas pilnas", "Įrašymas sustabdytas, kol neatsiras vietos")
                disk_full = True
                wav = cur = None
                gate.pause_reset()
                preroll.clear()
    except Stop:
        stopping = True
    finally:
        if wav is not None:
            try:
                wav.close()
                finish(cur, gate, stopping=True)
            except OSError:                      # pilnas diskas stabdant
                salvage(cur)
            paths.STATE_RECORDING.unlink(missing_ok=True)
        stop_capture(ff)
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
