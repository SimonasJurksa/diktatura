#!/usr/bin/env python3
"""VOX — balso aktyvumo įrašymas (BE Slack). Diktavimui / bet kokiam garsui.

Nuolat klauso mic + sistemos garso (monitor). Kai garsas praeina GATE (lygis) →
pradeda įrašyti STEREO failą (L=mic, R=sistema). Kai tyla VOX_SILENCE_SEC → uždaro.
Trumpi blyksniai (< min trukmės) atmetami. Po uždarymo — pagal wispr.conf
(immediate → transkribuoja; deferred → laukia 01:30; auto-off → tik įrašo).

Failai: recordings/vox_YYYYMMDD_HHMMSS.wav
Nustatymai (wispr.conf): VOX_GATE_DB (def -35), VOX_SILENCE_SEC (def 60), VOX_MIN_SEC (def 1.5)
Stop: Ctrl+C / systemctl --user stop wispr-vox
"""
import datetime as dt
import fcntl
import os
import signal
import subprocess
import sys
import wave
from collections import deque
from pathlib import Path

import numpy as np

REC = Path.home() / "wispr" / "recordings"
CONF = Path.home() / "wispr" / "wispr.conf"
STATE = REC / ".recording"   # būsenos failas ikonai (yra = rašoma)
CALIB = 20                   # chunk'ų (2s) triukšmui išmokti prieš leidžiant įrašyti
SR = 16000
CHUNK = SR // 10  # 100 ms
PREROLL = 8       # 0.8 s prieš gate atidarymą (kad nenukąstų pirmo žodžio)


def conf():
    d = {"VOX_GATE_DB": "-35", "VOX_GATE_OPEN": "", "VOX_GATE_CLOSE": "",
         "VOX_ADAPTIVE": "1", "VOX_OPEN_MARGIN": "15", "VOX_CLOSE_MARGIN": "8",
         "VOX_SILENCE_SEC": "60", "VOX_MIN_SEC": "1.5"}
    if CONF.exists():
        for ln in CONF.read_text(encoding="utf-8").splitlines():
            ln = ln.split("#")[0].strip()
            if "=" in ln:
                k, v = ln.split("=", 1); d[k.strip()] = v.strip()
    return d


def rms_db(x):
    if x.size == 0:
        return -120.0
    r = np.sqrt(np.mean((x.astype(np.float64) / 32768.0) ** 2))
    return 20 * np.log10(r + 1e-9)


def log(m):
    line = f"{dt.datetime.now():%F %T} [vox] {m}"
    print(line, flush=True)
    try:
        with open(REC / "autorecord.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main():
    REC.mkdir(parents=True, exist_ok=True)
    c = conf()
    SIL = float(c["VOX_SILENCE_SEC"]); MINS = float(c["VOX_MIN_SEC"])
    ADAPTIVE = c["VOX_ADAPTIVE"] == "1"
    OPEN_M = float(c["VOX_OPEN_MARGIN"]); CLOSE_M = float(c["VOX_CLOSE_MARGIN"])
    # Fiksuotas režimas (jei ADAPTIVE=0): histerezė OPEN/CLOSE.
    base = float(c["VOX_GATE_DB"])
    FIX_OPEN = float(c["VOX_GATE_OPEN"]) if c["VOX_GATE_OPEN"] else base
    FIX_CLOSE = float(c["VOX_GATE_CLOSE"]) if c["VOX_GATE_CLOSE"] else base - 12
    mic = subprocess.check_output(["pactl", "get-default-source"], text=True).strip()
    mon = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip() + ".monitor"
    filt = ("[0:a]pan=mono|c0=0.5*c0+0.5*c1[l];[1:a]pan=mono|c0=0.5*c0+0.5*c1[r];"
            "[l][r]join=inputs=2:channel_layout=stereo[a]")
    # thread_queue_size — didesnis įvesties buferis, kad transkripcijos (Ąžuolas) metu
    # capture nenumestų buferių (apsauga nuo garso „badavimo").
    ff = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-thread_queue_size", "8192", "-f", "pulse", "-i", mic,
         "-thread_queue_size", "8192", "-f", "pulse", "-i", mon,
         "-filter_complex", filt, "-map", "[a]",
         "-ac", "2", "-ar", str(SR), "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    # Didelis pipe buferis (RAM) — kad transkripcijos apkrovos metu Python spėtų
    # paskui ir niekas nenumestų garso (iki /proc/sys/fs/pipe-max-size, įprastai 1 MB ≈ 16s).
    try:
        fcntl.fcntl(ff.stdout.fileno(), getattr(fcntl, "F_SETPIPE_SZ", 1031), 1048576)
    except Exception:
        pass

    def _shutdown(*_):
        try: STATE.unlink()
        except Exception: pass
        try: ff.terminate()
        except Exception: pass
        os._exit(0)
    signal.signal(signal.SIGTERM, _shutdown)

    if ADAPTIVE:
        log(f"VOX startavo (ADAPTYVUS: triukšmas +{OPEN_M}/+{CLOSE_M}dB, tyla={SIL}s, min={MINS}s)")
    else:
        log(f"VOX startavo (FIKSUOTAS open={FIX_OPEN}dB close={FIX_CLOSE}dB, tyla={SIL}s, min={MINS}s)")

    nbytes = CHUNK * 2 * 2  # stereo s16le
    preroll = deque(maxlen=PREROLL)
    nf_win = deque(maxlen=50)  # ~5s triukšmo grindims (atnaujinam tik kai NErašom)
    nf = -55.0
    wav = None; cur = None; sil_chunks = 0; rec_chunks = 0
    sil_limit = int(SIL * 10); min_chunks = int(MINS * 10)

    def open_wav():
        nonlocal wav, cur, rec_chunks, sil_chunks
        cur = REC / f"vox_{dt.datetime.now():%Y%m%d_%H%M%S}.wav"
        wav = wave.open(str(cur), "wb"); wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(SR)
        for ch in preroll:
            wav.writeframes(ch)
        rec_chunks = len(preroll); sil_chunks = 0
        try: STATE.write_text("vox")   # ikonai: rašoma
        except Exception: pass
        log(f"🔴 garsas aptiktas (triukšmas≈{nf:.0f}dB) → {cur.name}")
        subprocess.run(["notify-send", "🔴 VOX įrašymas", cur.name], check=False,
                       stderr=subprocess.DEVNULL)

    def close_wav(keep):
        nonlocal wav, cur
        wav.close()
        try: STATE.unlink()            # ikonai: nebevyksta
        except Exception: pass
        dur = rec_chunks / 10.0
        if keep and rec_chunks >= min_chunks:
            log(f"🛑 tyla → uždaryta {cur.name} ({dur:.0f}s)")
            subprocess.run(["notify-send", "🛑 VOX baigta", f"{cur.name} {dur:.0f}s"],
                           check=False, stderr=subprocess.DEVNULL)
            if (os.environ.get("WISPR_AUTOTRANSCRIBE", conf().get("AUTOTRANSCRIBE", "1")) == "1"
                    and conf().get("MODE", "deferred") == "immediate"):
                subprocess.Popen(["bash", str(Path.home() / "wispr/scripts/transcribe-file.sh"), str(cur)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            log(f"per trumpas ({dur:.1f}s) — trinu")
            try: cur.unlink()
            except Exception: pass
        wav = None; cur = None

    try:
        while True:
            buf = ff.stdout.read(nbytes)
            if not buf or len(buf) < nbytes:
                break
            a = np.frombuffer(buf, dtype=np.int16).reshape(-1, 2)
            level = max(rms_db(a[:, 0]), rms_db(a[:, 1]))
            # Slenksčiai: adaptyvūs (triukšmo grindys + atsarga) arba fiksuoti
            if ADAPTIVE:
                if nf_win:
                    nf = float(np.percentile(nf_win, 25))
                open_thr = nf + OPEN_M; close_thr = nf + CLOSE_M
            else:
                open_thr = FIX_OPEN; close_thr = FIX_CLOSE
            if wav is None:
                preroll.append(buf)
                nf_win.append(level)       # triukšmo grindis mokomės tik budint
                # START: tik kai triukšmas IŠMOKTAS (≥CALIB) ir garsas aiškiai virš jo
                if ADAPTIVE and len(nf_win) < CALIB:
                    pass                   # dar kalibruojam (pirmos ~2s)
                elif level > open_thr:
                    open_wav()
            else:
                wav.writeframes(buf); rec_chunks += 1
                if level > close_thr:      # SUSTAIN: net tyli kalba (>triukšmas+CLOSE) laiko atvirą
                    sil_chunks = 0
                else:
                    sil_chunks += 1
                    if sil_chunks >= sil_limit:
                        close_wav(keep=True)
    except KeyboardInterrupt:
        pass
    finally:
        if wav is not None:
            close_wav(keep=True)
        if ff.poll() is None:
            ff.terminate()
        log("VOX sustabdytas")


if __name__ == "__main__":
    main()
