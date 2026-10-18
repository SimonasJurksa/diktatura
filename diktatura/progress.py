"""Diktatūra — transkripcijos eiga ir prognozė (⏳ langelis, ikonos meniu, `make progress`). Tik stdlib.

KAS VYKSTA — iš procesų (ne iš atskirų „eilės" failų: nulūžę ar nužudyti darbai dingsta patys):
  bin/transcribe-file.sh <failas> — vienas darbas; jo vaikas `flock` = laukia eilėje, kitaip — vykdomas
  (palikuonis diktatura.asr.transcribe* — transkribuoja, ffmpeg libmp3lame — archyvuoja, diktatura.asr.client — ASR
  serveryje). Skaičiuojami tik šios aplinkos darbai (tas pats <runtime> katalogas = ta pati eilė).
  bin/transcribe-pending.sh (naktinis / make transcribe-pending) — jo dar nepaleisti failai rodomi kaip laukiantys.
EIGA — <runtime>/progress/<bazė>.json, kurį rašo ASR modulis (Reporter): etapas, kiek jo atlikta, garso / kalbos s.
PROGNOZĖ — kiek šis kompiuteris užtrunka (<state>/timing.json: paskutinės transkripcijos, etapų trukmės ir garso /
  kalbos kiekiai -> greičiai, kaip sumų santykis — ilgi įrašai sveria daugiau) × šio failo garso / kalbos trukmė.
  Vykdomam etapui su eiga (Whisper) — tikras greitis, sumaišytas su įprastu; likusiems etapams ir visai eilei —
  sulėtėjimas: kiek dabartinis failas eina lėčiau / greičiau nei įprastai (pvz. CPU apkrautas kitų programų).
BENDRA EIGA (kaip Midnight Commander kopijuojant): praėjęs laikas nuo serijos pradžios / (praėjęs + likęs). Serija —
  iš eilės (tarpai < BATCH_GAP) baigtos transkripcijos timing.json + dabartinė.
STABDYMAS: skip_current() — nutraukia vykdomo darbo ASR / ffmpeg (failas lieka be teksto -> naktinis), eilė tęsiasi;
  stop_all() — dar ir naktinį ciklą bei laukiančius eilėje (bash pirma, tada jo `flock`, kad neitų toliau be eilės).
CLI: python3 -m diktatura.progress   (make progress)
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from diktatura import paths, sessions

NAMED_PHASES = ("prep", "vad", "load", "asr_me", "asr_them", "names")
MONO_PHASES = ("vad", "load", "asr")
PHASE_LABELS = {
    "queued": "Laukia eilėje", "pending": "Laukia (naktinis)", "start": "Pradedama",
    "prep": "Ruošiamas garsas (aidas, garsumas)", "vad": "Ieškoma kalbos (VAD)", "load": "Kraunamas modelis",
    "asr_me": "Transkribuojama: Tu (mikrofonas)", "asr_them": "Transkribuojama: kolegos", "asr": "Transkribuojama",
    "names": "Atpažįstami kalbėtojai", "archive": "Archyvuojama (mp3)", "server": "Transkribuoja ASR serveris",
}
# Numatytieji greičiai (kol istorijos nėra; matuota šiame kompiuteryje — i7-1165G7, Ąžuolas int8, 6 gijos):
#   prep, vad, archive — s / garso s;  asr — s / kalbos s;  names — s / kolegų kalbos s;  load, overhead — s;
#   speech — kalbos dalis kanale.
DEFAULTS = {"prep": 0.03, "vad": 0.02, "load": 6.0, "asr": 1.5, "names": 0.05, "archive": 0.01,
            "overhead": 4.0, "speech": 0.5}
MODEL_ASR = {"azuolas-ct2": 1.5, "medium": 0.6}
# Švelninimas: išmoktas greitis = (Σ trukmių + numatytasis × K) / (Σ vienetų + K) — kol istorijoje mažai garso, lieka
# arti numatytojo (kelios 10 s įrašų be kalbos neturi „išmokyti", kad kalbos nebūna). K — garso / kalbos sekundės.
PRIOR_K = {"prep": 600.0, "vad": 600.0, "asr": 300.0, "names": 300.0, "speech": 600.0}
HISTORY_MAX = 50
BATCH_GAP = 120.0           # s tarp transkripcijų — dar ta pati serija
WRITE_EVERY = 1.0           # s — eigos failas rašomas ne dažniau
TMP_PREFIX = "diktatura-asr-"   # ASR laikinas katalogas: <tmp>/diktatura-asr-<pid>-… (skip_current jį išvalo)


# ── eigos failas (rašo ASR modulis) ──

def progress_file(audio) -> Path:
    return paths.PROGRESS_DIR / f"{sessions.base_name(Path(audio).name)}.json"


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class Reporter:
    """ASR modulio eigos rašytojas:  with Reporter(garsas, "named", modelis, gijos) as rep: rep.phase("prep") …
    Etapų trukmės kaupiamos; sėkmingai baigus (finish) — įrašas į timing.json (prognozei), eigos failas ištrinamas.
    Klaida / išimtis — eigos failas ištrinamas, istorija nepildoma."""

    def __init__(self, audio, kind: str, model: str = "", threads: int = 0, clock=time.time):
        self.clock = clock
        self.path = progress_file(audio)
        self.kind = kind
        model = Path(model).name if model else ""      # transcribe-file.sh paduoda modelio katalogo kelią
        now = clock()
        self.data = {"file": str(audio), "kind": kind, "pid": os.getpid(), "model": model, "threads": threads,
                     "started": now, "phase": "start", "phase_started": now, "done": 0.0, "total": 0.0,
                     "phases": list(NAMED_PHASES if kind == "named" else MONO_PHASES), "times": {},
                     "audio_sec": None, "speech": None, "updated": now,
                     # 🌊 bangos failas (transcribe-file.sh žino tikrą išvesties bazę — pvz. sekamų aplankų)
                     "peaks": os.environ.get("DIKTATURA_PEAKS") or None}
        self._last_write = 0.0
        self.finished = False

    def __enter__(self):
        self._write(force=True)
        return self

    def __exit__(self, exc_type, *_):
        if not self.finished:
            self.path.unlink(missing_ok=True)
        return False

    def _write(self, force=False) -> None:
        now = self.clock()
        if force or now - self._last_write >= WRITE_EVERY:
            self.data["updated"] = now
            try:
                _write_json(self.path, self.data)
            except OSError:
                pass                                  # eiga — tik informacija; transkripcija dėl jos nelūžta
            self._last_write = now

    def _close_phase(self) -> None:
        ph = self.data["phase"]
        if ph and ph != "start":
            self.data["times"][ph] = self.data["times"].get(ph, 0.0) + self.clock() - self.data["phase_started"]

    def phase(self, name: str, total: float = 0.0) -> None:
        self._close_phase()
        self.data.update(phase=name, phase_started=self.clock(), done=0.0, total=float(total), pos=0.0)
        self._write(force=True)

    def advance(self, done: float, pos: float = None) -> None:
        """done — kiek etapo darbo (apkarpyto kanalo s); pos — iki kur ORIGINALAUS įrašo jau apdorota (🌊 bangai)."""
        self.data["done"] = float(done)
        if pos is not None:
            self.data["pos"] = float(pos)
        self._write()

    def set(self, **kw) -> None:
        self.data.update(kw)
        self._write(force=True)

    def finish(self) -> None:
        """Sėkmingai baigta: etapų trukmės -> timing.json; eigos failas ištrinamas."""
        self._close_phase()
        self.finished = True
        self.path.unlink(missing_ok=True)
        d = self.data
        if not d.get("audio_sec"):
            return
        t = d["times"]
        rec = {"model": d["model"], "kind": d["kind"], "threads": d["threads"], "audio": round(d["audio_sec"], 2),
               "speech": [round(x, 2) for x in (d.get("speech") or [])], "started": round(d["started"], 2),
               "finished": round(self.clock(), 2), "file": Path(d["file"]).name,
               "phases": {"prep": t.get("prep", 0.0), "vad": t.get("vad", 0.0), "load": t.get("load", 0.0),
                          "asr": t.get("asr_me", 0.0) + t.get("asr_them", 0.0) + t.get("asr", 0.0),
                          "names": t.get("names", 0.0)}}
        rec["phases"] = {k: round(v, 2) for k, v in rec["phases"].items()}
        add_history(rec)


def history() -> list:
    h = _read_json(paths.TIMING, [])
    return h if isinstance(h, list) else []


def add_history(rec: dict) -> None:
    h = history()
    h.append(rec)
    try:
        _write_json(paths.TIMING, h[-HISTORY_MAX:])
    except OSError:
        pass


# ── greičiai ir prognozė ──

def rates(model: str = None, hist: list = None) -> dict:
    """Šio kompiuterio greičiai iš istorijos (sumų santykiai — ilgi įrašai sveria daugiau); trūkstami — DEFAULTS."""
    r = dict(DEFAULTS)
    if model in MODEL_ASR:
        r["asr"] = MODEL_ASR[model]
    recs = [x for x in (history() if hist is None else hist) if isinstance(x, dict) and x.get("audio")
            and (model is None or x.get("model") == model)]
    r["n"] = len(recs)
    if not recs:
        return r
    chans = lambda x: 2 if x.get("kind") == "named" else 1                  # noqa: E731
    sp_all = lambda x: sum(x.get("speech") or [])                            # noqa: E731
    sp_them = lambda x: (x.get("speech") or [0, 0])[-1] if x.get("kind") == "named" else 0   # noqa: E731
    named = [x for x in recs if x.get("kind") == "named"]
    for key, unit, pool in (("prep", lambda x: x["audio"], named), ("vad", lambda x: x["audio"] * chans(x), recs),
                            ("asr", sp_all, recs), ("names", sp_them, named)):
        r[key] = _ratio(pool, lambda x, k=key: float(x.get("phases", {}).get(k, 0.0)), unit, r[key], PRIOR_K[key])
    loads = sorted(float(x.get("phases", {}).get("load", 0.0)) for x in recs
                   if float(x.get("phases", {}).get("load", 0.0)) > 0)          # be kalbos modelis nekrautas — 0
    if loads:
        r["load"] = loads[len(loads) // 2]
    sp = _ratio([x for x in recs if x.get("speech")], sp_all, lambda x: x["audio"] * chans(x), r["speech"],
                PRIOR_K["speech"])
    r["speech"] = min(1.0, max(0.05, sp))
    return r


def prediction_error(hist: list = None, model: str = None, last: int = 10):
    """Kiek ankstesnės prognozės skyrėsi nuo tikrovės: kiekvienai iš paskutinių `last` transkripcijų SU KALBA prognozė
    daroma iš ANKSTESNIŲ įrašų greičių (kaip tada būtų buvę), jau žinant VAD kalbos kiekį (tokią prognozę rodo ⏳
    langelis didžiąją laiko dalį), ir lyginama su tikra trukme. Įrašai be kalbos (modelis nekrautas, ~1 s) neįtraukiami —
    jie iškreiptų. -> (medianinė santykinė paklaida, įrašų sk.) arba (None, 0), kai tokių įrašų mažiau nei 3."""
    recs = [x for x in (history() if hist is None else hist) if isinstance(x, dict) and x.get("audio")
            and x.get("phases") and (model is None or x.get("model") == model)]
    spoken = [i for i, x in enumerate(recs) if float(x["phases"].get("asr", 0)) > 0 and x.get("speech")]
    if len(spoken) < 3:
        return None, 0
    errs = []
    for i in spoken[-last:]:
        if i < 2:
            continue
        rec, before = recs[i], recs[:i]
        r = rates(rec.get("model"), before)
        actual = sum(float(v) for v in rec["phases"].values())
        speech = [float(v) for v in rec["speech"]]
        pred = sum(phase_plan(rec.get("kind", "named"), float(rec["audio"]), r, speech, [v <= 0 for v in speech]).values())
        errs.append(abs(pred - actual) / actual)
    if not errs:
        return None, 0
    errs.sort()
    return errs[len(errs) // 2], len(errs)


def fmt_error(err, n: int) -> str:
    return f"ankstesnių {n} prognozių paklaida ±{int(round(err * 100))} %" if err is not None else ""


def _ratio(pool, value, unit, default: float, k: float) -> float:
    """(Σ value + default × k) / (Σ unit + k): ilgi įrašai sveria daugiau nei trumpi su pastoviomis sąnaudomis, o kol
    istorijos mažai — arti numatytojo."""
    num, den = default * k, k
    for x in pool:
        u = unit(x)
        if u and u > 0:
            num += value(x)
            den += u
    return num / den


def phase_plan(kind: str, audio_sec: float, r: dict, speech=None, skip=None) -> dict:
    """Numatoma kiekvieno etapo trukmė (s). speech — VAD kalbos s kanaluose (jei jau žinoma), skip — praleisti kanalai."""
    ch = 2 if kind == "named" else 1
    sp = list(speech) if speech else [audio_sec * r["speech"]] * ch
    skip = list(skip) if skip else [False] * ch
    sp = [0.0 if (i < len(skip) and skip[i]) else float(s) for i, s in enumerate(sp)]
    if kind == "named":
        sp += [0.0] * (2 - len(sp))
        return {"prep": audio_sec * r["prep"], "vad": audio_sec * 2 * r["vad"], "load": r["load"] if any(sp) else 0.0,
                "asr_me": sp[0] * r["asr"], "asr_them": sp[1] * r["asr"], "names": sp[1] * r["names"]}
    return {"vad": audio_sec * r["vad"], "load": r["load"] if any(sp) else 0.0, "asr": sp[0] * r["asr"]}


def estimate_job_total(kind: str, audio_sec: float, r: dict, slow: float = 1.0) -> float:
    """Visas eilėje laukiančio darbo laikas: etapai × sulėtėjimas + paleidimas + mp3 archyvas."""
    return (sum(phase_plan(kind, audio_sec, r).values()) * slow + r["overhead"]
            + audio_sec * r["archive"])


def estimate_running(info: dict, r: dict, now: float):
    """Vykdomas darbas su eigos failu -> (likęs s, sulėtėjimas). Sulėtėjimas — baigtų etapų tikra / numatyta trukmė
    ir dabartinio Whisper etapo tikras / įprastas greitis (CPU apkrova)."""
    kind = info.get("kind", "named")
    audio = float(info.get("audio_sec") or 0.0)
    plan = phase_plan(kind, audio, r, info.get("speech"), info.get("skip"))
    order = list(info.get("phases") or plan)
    ph = info.get("phase", "start")
    times = info.get("times", {})
    act = sum(float(times.get(p, 0.0)) for p in order if p != "load" and p in times)
    pred = sum(plan.get(p, 0.0) for p in order if p != "load" and p in times)
    elapsed_ph = max(0.0, now - float(info.get("phase_started", now)))
    done, total = float(info.get("done", 0.0)), float(info.get("total", 0.0))
    live = None
    if ph.startswith("asr") and total > 0 and done > 0:
        live = elapsed_ph / done                                    # s / apdorotos garso s (šiame kanale)
        prior = plan.get(ph, 0.0) / total if total else 0.0
        if prior > 0:
            w = min(1.0, done / max(total * 0.15, 30.0))            # nuo ~15 % (ar 30 s garso) — tikras greitis
            act += elapsed_ph * w
            pred += done * prior * w
    slow = min(6.0, max(0.25, act / pred)) if pred > 1.0 else 1.0
    # dabartinis etapas
    if ph in plan:
        if live is not None:
            prior_rate = plan[ph] / total * slow
            w = min(1.0, done / max(total * 0.15, 30.0))
            left = (total - done) * (w * live + (1 - w) * prior_rate)
        else:
            exp = plan[ph] * (1.0 if ph == "load" else slow)
            left = max(exp - elapsed_ph, min(exp, 0.1 * elapsed_ph + 2.0))   # užtruko ilgiau nei numatyta — dar kiek
    else:
        left = 0.0
    nxt = order.index(ph) + 1 if ph in order else 0
    left += sum(plan.get(p, 0.0) * (1.0 if p == "load" else slow) for p in order[nxt:])
    left += audio * r["archive"]
    return max(0.0, left), slow


# ── kas vyksta (procesai) ──

@dataclass
class Proc:
    pid: int
    ppid: int
    cmd: list
    start: float


@dataclass
class Job:
    pid: int
    file: Path
    state: str                      # running | queued | pending
    start: float = 0.0              # darbo pradžia (vykdomo — apdorojimo, kitų — kada įstojo į eilę)
    phase: str = "queued"
    kind: str = "named"
    audio_sec: float = 0.0
    info: dict = field(default_factory=dict)
    server: bool = False
    left: float = 0.0               # likęs laikas, s
    total: float = 0.0              # visa trukmė (praėjęs + likęs), s
    exact: bool = True              # False — eigos failo nėra (sena versija / dar nepradėta), tik pagal laiką

    @property
    def fraction(self) -> float:
        return 0.0 if self.total <= 0 else min(1.0, max(0.0, 1.0 - self.left / self.total))

    @property
    def name(self) -> str:
        return self.file.name


def peaks_file(job: Job) -> Path:
    """Vykdomo darbo 🌊 smailių failas: eigos faile nurodytas (transcribe-file.sh) arba <bazė>.peaks šalia garso."""
    p = (job.info or {}).get("peaks")
    if p:
        return Path(p)
    from diktatura import waveform
    return waveform.peaks_path(job.file)


def processed_secs(job: Job, duration: float, channels: int) -> list:
    """Kiek kiekvieno bangos kanalo jau apdorota (s) — ⏳ bangai. Stereo: [Tu, kolegos] (pirma Tu, tada kolegos);
    vienas kanalas (mono / sekamo aplanko failas) — jo etapo eiga; eigos failo nėra — pagal laiką (fraction)."""
    info = job.info or {}
    if not info or not job.exact:
        return [duration * job.fraction] * channels
    ph = info.get("phase") or job.phase
    pos = max(0.0, min(duration, float(info.get("pos") or 0.0)))
    if info.get("kind") == "mono":
        return [pos if ph == "asr" else duration if ph in ("names", "archive") else 0.0] * channels
    me, them = {"asr_me": (pos, 0.0), "asr_them": (duration, pos),
                "names": (duration, duration), "archive": (duration, duration)}.get(ph, (0.0, 0.0))
    if (info.get("skip") or [False])[0] and ph in ("asr_me", "asr_them"):
        me = duration                                   # „Tu" kanalas praleistas (tyla / sekamas aplankas)
    return [them] if channels == 1 else [me, them]


@dataclass
class Snapshot:
    now: float
    running: Job = None
    queued: list = field(default_factory=list)       # laukia eilėje (bash + flock) ir naktinio sąraše
    waiting_night: list = field(default_factory=list)   # be teksto, niekas jų nedaro (laukia 01:30)
    slow: float = 1.0
    rates: dict = field(default_factory=dict)
    batch_start: float = 0.0
    batch_done: int = 0
    pending_pids: list = field(default_factory=list)

    @property
    def jobs(self) -> list:
        return ([self.running] if self.running else []) + self.queued

    @property
    def left(self) -> float:
        return sum(j.left for j in self.jobs)

    @property
    def total_fraction(self) -> float:
        if not self.jobs:
            return 0.0
        el = max(0.0, self.now - self.batch_start) if self.batch_start else 0.0
        return el / (el + self.left) if el + self.left > 0 else 0.0

    @property
    def audio_total(self) -> float:
        return sum(j.audio_sec for j in self.jobs)

    @property
    def active(self) -> bool:
        return bool(self.jobs)


def _boot_time() -> float:
    try:
        for ln in open("/proc/stat"):
            if ln.startswith("btime"):
                return float(ln.split()[1])
    except OSError:
        pass
    return 0.0


def scan_procs() -> dict:
    """{pid: Proc} — visi matomi procesai (cmdline, tėvas, pradžios laikas)."""
    out, boot, hz = {}, _boot_time(), os.sysconf("SC_CLK_TCK")
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/cmdline", "rb") as fh:
                cmd = [c.decode("utf-8", "replace") for c in fh.read().split(b"\0") if c]
            with open(f"/proc/{d}/stat") as fh:
                st = fh.read()
        except OSError:
            continue
        f = st[st.rfind(")") + 2:].split()
        out[int(d)] = Proc(int(d), int(f[1]), cmd, boot + int(f[19]) / hz)
    return out


def _run_dir_of(pid: int):
    """Proceso <runtime> katalogas (pagal jo aplinką, kaip paths.py) — kad testai nematytų tikrų darbų ir atvirkščiai."""
    try:
        with open(f"/proc/{pid}/environ", "rb") as fh:
            env = dict(x.split(b"=", 1) for x in fh.read().split(b"\0") if b"=" in x)
    except OSError:
        return None
    if env.get(b"DIKTATURA_RUN"):
        return Path(os.path.expanduser(env[b"DIKTATURA_RUN"].decode()))
    if env.get(b"XDG_RUNTIME_DIR"):
        return Path(env[b"XDG_RUNTIME_DIR"].decode()) / "diktatura"
    return Path(f"/tmp/diktatura-{os.getuid()}")


def _script_arg(p: Proc, script: str):
    """bash …/bin/<script> [arg] -> arg ('' jei be argumento) arba None."""
    for i, c in enumerate(p.cmd[:3]):
        if c.endswith("/" + script) or c == script:
            return p.cmd[i + 1] if i + 1 < len(p.cmd) else ""
    return None


def children_map(procs: dict) -> dict:
    kids = {}
    for p in procs.values():
        kids.setdefault(p.ppid, []).append(p.pid)
    return kids


def descendants(pid: int, procs: dict, kids: dict = None) -> list:
    kids = kids or children_map(procs)
    out, stack = [], list(kids.get(pid, []))
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(kids.get(c, []))
    return out


_dur_cache = {}


def audio_info(path: Path):
    """(trukmė s, kanalai) — wav iš antraštės (greita), kita per ffprobe (talpykla pagal dydį ir laiką)."""
    try:
        st = path.stat()
    except OSError:
        return 0.0, 2
    key = (str(path), st.st_size, st.st_mtime)
    if key in _dur_cache:
        return _dur_cache[key]
    res = (0.0, 2)
    if path.suffix == ".wav":
        try:
            with wave.open(str(path)) as w:
                res = (w.getnframes() / float(w.getframerate()), w.getnchannels())
        except (OSError, EOFError, wave.Error):
            res = (max(0.0, (st.st_size - 44) / 64000.0), 2)
    else:
        try:
            out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                  "stream=channels:format=duration", "-of", "default=nw=1", str(path)],
                                 capture_output=True, text=True, timeout=10).stdout
            kv = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
            res = (float(kv.get("duration", 0) or 0), int(kv.get("channels", 2) or 2))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    _dur_cache[key] = res
    return res


def pending_files(exclude=()) -> list:
    """Įrašai be teksto (kaip transcribe-pending.sh): {slack,vox,rec}_*.wav be .named.txt/.txt/... ir be .skip, tada
    sekamų aplankų (diktatura.sources) laukiantys failai."""
    try:
        active = Path(paths.STATE_RECORDING.read_text().split(maxsplit=1)[1].strip())
    except (OSError, IndexError):
        active = None
    ex = {Path(e) for e in exclude}
    out = []
    for f in sorted(paths.RECORDINGS.glob("*_*.wav")):
        if not any(f.name.startswith(src + "_") for src in sessions.SOURCES) or f in ex or f == active:
            continue
        base = f.with_name(sessions.base_name(f.name))
        if any(base.with_name(base.name + s).exists()
               for s in (".named.txt", ".clean.dialog.txt", ".dialog.txt", ".txt", ".skip")):
            continue
        out.append(f)
    from diktatura import sources
    out += [a for a, _ in sources.all_pending() if a not in ex]
    return out


def _batch_start(hist: list, running_start: float) -> tuple:
    """Serijos pradžia: dabartinis + iš eilės (tarpai < BATCH_GAP) prieš jį baigti iš istorijos. -> (pradžia, baigta)."""
    start, n = running_start, 0
    done = sorted((x for x in hist if isinstance(x, dict) and x.get("finished")
                   and float(x["finished"]) <= running_start + 1), key=lambda x: -float(x["finished"]))
    for rec in done:
        if start - float(rec["finished"]) > BATCH_GAP:
            break
        start, n = min(start, float(rec.get("started", rec["finished"]))), n + 1
    return start, n


def queue_busy() -> bool:
    """Ar kas nors laiko transkripcijos užraktą (vykdo ar laukia eilėje). Greita (be /proc skenavimo): ikona
    klausia kas 2 s, o visų procesų skaitymas be reikalo kainuotų CPU. Užraktas tik patikrinamas — neperimamas."""
    import fcntl
    try:
        with open(paths.TRANSCRIBE_LOCK, "a+") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(fh, fcntl.LOCK_UN)
            return False
    except OSError:
        return True                                  # nežinia — tegul skenuoja


def snapshot(now: float = None, procs: dict = None) -> Snapshot:
    """Kas dabar transkribuojama, kas laukia, kiek liko (žr. modulio aprašą)."""
    now = time.time() if now is None else now
    if procs is None and not queue_busy():           # niekas netranskribuoja — be /proc skenavimo
        snap = Snapshot(now=now, rates=rates(_model_setting(), history()))
        snap.waiting_night = pending_files()
        return snap
    procs = scan_procs() if procs is None else procs
    kids = children_map(procs)
    run_dir = paths.RUN_DIR.resolve()
    mine = lambda pid: (_run_dir_of(pid) or Path("/nonexistent")).resolve() == run_dir   # noqa: E731
    jobs, pend_pids = [], []
    for p in procs.values():
        arg = _script_arg(p, "transcribe-file.sh")
        if arg and mine(p.pid):
            jobs.append((p, Path(arg)))
        elif _script_arg(p, "transcribe-pending.sh") is not None and mine(p.pid):
            pend_pids.append(p.pid)
    snap = Snapshot(now=now, pending_pids=pend_pids)
    hist = history()
    queued = []
    for p, f in sorted(jobs, key=lambda x: (x[0].start, x[0].pid)):
        desc = [procs[c] for c in descendants(p.pid, procs, kids) if c in procs]
        direct = [procs[c] for c in kids.get(p.pid, []) if c in procs]
        dur, ch = audio_info(f)
        job = Job(pid=p.pid, file=f, state="running", start=p.start, audio_sec=dur, kind="named" if ch == 2 else "mono")
        if any(Path(c.cmd[0]).name == "flock" for c in direct if c.cmd):
            job.state, job.phase = "queued", "queued"
            queued.append(job)
            continue
        joined = [" ".join(c.cmd) for c in desc]
        asr = [c for c in desc if any("diktatura.asr.transcribe" in a for a in c.cmd)]
        job.server = any("diktatura.asr.client" in j for j in joined)
        info = _read_json(progress_file(f), None)
        if info and info.get("file") == str(f):
            job.info, job.phase = info, info.get("phase", "start")
            job.start = float(info.get("started", p.start))
            job.kind = info.get("kind", job.kind)
        elif any("libmp3lame" in j for j in joined):
            job.phase, job.exact = "archive", True
            ff = [c for c in desc if any("libmp3lame" in a for a in c.cmd)]
            job.start = ff[0].start if ff else p.start
        else:
            job.phase = "server" if job.server else ("asr" if asr else "start")
            job.exact = False
            if asr:
                job.start = asr[0].start
        if snap.running is None:
            snap.running = job
        else:                                        # neturėtų būti (flock) — rodom kaip laukiantį
            job.state = "queued"
            queued.append(job)
    model = (snap.running.info.get("model") if snap.running and snap.running.info else None) or _model_setting()
    r = rates(model, hist)
    snap.rates = r
    # vykdomas
    if snap.running:
        j = snap.running
        el = max(0.0, now - j.start)
        if j.info:
            j.left, snap.slow = estimate_running(j.info, r, now)
        elif j.phase == "archive":
            j.left = max(1.0, j.audio_sec * r["archive"] - el)
        else:
            j.left = max(estimate_job_total(j.kind, j.audio_sec, r) - el, 0.1 * el + 5.0)
        j.total = el + j.left
        snap.batch_start, snap.batch_done = _batch_start(hist, j.start)
    # laukiantys: eilėje (bash) + naktinio sąrašas (dar nepaleisti)
    if pend_pids:
        taken = {j.file for j in queued} | ({snap.running.file} if snap.running else set())
        for f in pending_files(exclude=taken):
            dur, ch = audio_info(f)
            queued.append(Job(pid=0, file=f, state="pending", phase="pending", audio_sec=dur,
                              kind="named" if ch == 2 else "mono"))
    for j in queued:
        j.left = j.total = estimate_job_total(j.kind, j.audio_sec, r, snap.slow)
    snap.queued = queued
    if not pend_pids:
        taken = {j.file for j in snap.jobs}
        snap.waiting_night = pending_files(exclude=taken)
    if snap.running is None and queued:
        snap.batch_start = now
    return snap


def _model_setting() -> str:
    try:
        from diktatura import config
        return config.load()["MODEL"]
    except Exception:
        return "azuolas-ct2"


# ── formatavimas ──

def fmt_left(sec: float) -> str:
    """Likęs laikas žmogui: „< 1 min", „~7 min", „~1 val. 05 min", „~12 val."."""
    if sec < 60:
        return "< 1 min"
    m = int(round(sec / 60.0))
    if m < 60:
        return f"~{m} min"
    h, m = divmod(m, 60)
    return f"~{h} val." if h >= 10 else f"~{h} val. {m:02d} min"


def fmt_clock(sec: float) -> str:
    """Trukmė H:MM:SS / M:SS."""
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_eta(sec: float, now: float) -> str:
    """„~1 val. 05 min (≈ 15:40)" — laikrodis rodomas, kai liko > 10 min (kitą dieną — su data)."""
    s = fmt_left(sec)
    if sec > 600:
        end = datetime.fromtimestamp(now + sec)
        day = "" if end.date() == datetime.fromtimestamp(now).date() else f"{end:%m-%d} "
        s += f" (≈ {day}{end:%H:%M})"
    return s


def phase_text(job: Job) -> str:
    """„Etapas 4/6: Transkribuojama: kolegos — 12:30 / 47:10 garso"."""
    info = job.info or {}
    order = info.get("phases") or []
    label_ = PHASE_LABELS.get(job.phase, job.phase)
    s = f"Etapas {order.index(job.phase) + 1}/{len(order)}: {label_}" if job.phase in order else label_
    if job.phase.startswith("asr") and info.get("total"):
        s += f" — {fmt_clock(info.get('done', 0))} / {fmt_clock(info['total'])} garso"
    return s


def summary(snap: Snapshot) -> str:
    """Viena eilutė (ikonos meniu, Teksto mygtukas): „43 % · liko ~1 val. 20 min · eilėje 4"."""
    if not snap.active:
        return ""
    s = f"{int(snap.running.fraction * 100)} % · " if snap.running else ""
    s += f"liko {fmt_left(snap.left)}"
    if snap.queued:
        s += f" · eilėje {len(snap.queued)}"
    return s


def describe(snap: Snapshot) -> list:
    """Tekstinis vaizdas (CLI)."""
    if not snap.active:
        out = ["Šiuo metu niekas netranskribuojama."]
        if snap.waiting_night:
            secs = sum(audio_info(f)[0] for f in snap.waiting_night)
            out.append(f"Be teksto: {len(snap.waiting_night)} įr. ({fmt_clock(secs)} garso) — transkribuos naktinis "
                       "01:30 arba make transcribe-pending")
        return out
    out = []
    if snap.running:
        j = snap.running
        out += [f"▶ {j.name}  ({fmt_clock(j.audio_sec)} garso)" + ("" if j.exact else "  [eiga nežinoma — pagal laiką]"),
                f"  {phase_text(j)}",
                f"  {bar(j.fraction)} {int(j.fraction * 100):3d} %   praėjo {fmt_clock(snap.now - j.start)} · "
                f"liko {fmt_eta(j.left, snap.now)}"]
    out += [f"Visa eilė: {len(snap.jobs)} f. ({fmt_clock(snap.audio_total)} garso)",
            f"  {bar(snap.total_fraction)} {int(snap.total_fraction * 100):3d} %   liko {fmt_eta(snap.left, snap.now)}"]
    for j in snap.queued:
        out.append(f"  · {j.name:<28} {fmt_clock(j.audio_sec):>8}  {fmt_left(j.left):>14}"
                   + ("  (naktinis)" if j.state == "pending" else ""))
    if abs(snap.slow - 1.0) > 0.15:
        out.append(f"Dabar {snap.slow:.1f}× {'lėčiau' if snap.slow > 1 else 'greičiau'} nei įprastai (CPU apkrova).")
    e = fmt_error(*prediction_error())
    if e:
        out.append(f"({e[0].upper() + e[1:]})")
    return out


def bar(frac: float, width: int = 30) -> str:
    n = int(round(max(0.0, min(1.0, frac)) * width))
    return "[" + "█" * n + "░" * (width - n) + "]"


# ── stabdymas ──

def _kill(pids, sig=signal.SIGTERM) -> int:
    n = 0
    for pid in pids:
        try:
            os.kill(pid, sig)
            n += 1
        except (ProcessLookupError, PermissionError):
            pass
    return n


def _wait_gone(pids, timeout=3.0) -> None:
    end = time.monotonic() + timeout
    left = list(pids)
    while left and time.monotonic() < end:
        left = [p for p in left if Path(f"/proc/{p}").exists() and _state(p) != "Z"]
        if left:
            time.sleep(0.05)
    _kill(left, signal.SIGKILL)


def _state(pid) -> str:
    try:
        st = open(f"/proc/{pid}/stat").read()
        return st[st.rfind(")") + 2]
    except OSError:
        return ""


def log(msg: str) -> None:
    try:
        paths.LOG_TRANSCRIBE.parent.mkdir(parents=True, exist_ok=True)
        with open(paths.LOG_TRANSCRIBE, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%F %T} {msg}\n")
    except OSError:
        pass


def skip_current(snap: Snapshot = None) -> str:
    """Nutraukti vykdomą transkripciją (jos ASR / ffmpeg procesus). bash skriptas pats baigia („garsas paliktas"),
    eilė tęsiasi; failas lieka be teksto — paims naktinis (01:30) arba make transcribe-pending."""
    snap = snap or snapshot()
    j = snap.running
    if j is None:
        return "Nėra vykdomos transkripcijos."
    if j.server:
        return "ASR serverio darbo nutraukti negalima — išjunk ASR serverį (Nustatymai) arba palauk."
    procs = scan_procs()
    victims = descendants(j.pid, procs)
    _kill(victims)
    _wait_gone(victims)
    progress_file(j.file).unlink(missing_ok=True)
    for pid in victims:                              # ASR laikini failai (ilgo įrašo kanalai — šimtai MB)
        for d in Path(tempfile.gettempdir()).glob(f"{TMP_PREFIX}{pid}-*"):
            shutil.rmtree(d, ignore_errors=True)
    if j.phase == "archive":                         # tekstas jau yra — nutrauktas tik mp3 (pusinis failas trinamas)
        mp3 = j.file.with_suffix(".mp3")
        if j.file.suffix == ".wav" and j.file.exists():
            mp3.unlink(missing_ok=True)
        log(f"⏭ vartotojas nutraukė mp3 archyvavimą: {j.name} (tekstas yra, garsas lieka wav)")
        return f"Nutrauktas mp3 archyvavimas: {j.name} (tekstas jau yra)."
    log(f"⏭ vartotojas praleido: {j.name} (po {fmt_clock(snap.now - j.start)}; liks naktiniam)")
    return f"Praleista: {j.name} — liks be teksto (naktinis 01:30)."


def stop_all(snap: Snapshot = None) -> str:
    """Sustabdyti visą eilę: naktinį ciklą, laukiančius (bash, tada jų flock) ir vykdomą darbą."""
    snap = snap or snapshot()
    procs = scan_procs()
    kids = children_map(procs)
    _kill(snap.pending_pids)
    waiting = [j.pid for j in snap.queued if j.pid]
    _kill(waiting)                                   # bash pirma — kad nutraukus flock neitų toliau be eilės
    _wait_gone(waiting, 2.0)
    _kill([c for pid in waiting for c in kids.get(pid, [])])
    n = len(waiting) + sum(1 for j in snap.queued if j.state == "pending")
    if snap.running and not snap.running.server:
        skip_current(snap)
        n += 1
    log(f"⏹ vartotojas sustabdė transkripcijas: {n} f. (liks naktiniam)")
    extra = " (ASR serveris dabartinį baigs)" if snap.running and snap.running.server else ""
    return f"Sustabdyta: {n} f. — liks be teksto (naktinis 01:30){extra}."


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    snap = snapshot()
    if "--json" in args:
        print(json.dumps({"running": snap.running and snap.running.__dict__, "left": snap.left,
                          "queued": [j.__dict__ for j in snap.queued]}, default=str, ensure_ascii=False, indent=1))
    else:
        print("\n".join(describe(snap)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
