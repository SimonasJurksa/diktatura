# Diktatūra — techninė architektūra

Dokumentas skirtas **kūrėjui ar Claude sesijai**, norinčiai suprasti sistemą ir ją tobulinti.
Aprašo DABARTINĮ funkcionalumą techniniu lygiu (ne istoriją). Darbo žurnalas — `STATUS.md` (lokalus).

## 1. Ką daro (santrauka)

Lokalus, privatus balso-į-tekstą Linux'ui. Du įrašymo šaltiniai (+ sekami aplankai: telefonas, laikrodis…) →
transkripcija (lietuviškai, Ąžuolas) → kalbėtojų atpažinimas vardais → langas „Diktatūra" (gyvas tekstas su garso
banga · balsų apmokymai · nustatymai) + status bar ikona + įrašymo indikatorius. Viskas vietoje; pasirinktinai —
MCP serveris AI klientui (tik skaito).

## 2. Komponentai ir duomenų srautas

```
ĮRAŠYMAS                            ANALIZĖ (po įrašo)                         RODYMAS
──────────                          ─────────────────                         ───────
bin/autorecord.sh   (Slack)  ─┐                                               diktatura.ui.tray (⚪/🔴/🟡)
diktatura.audio.vox (VOX)    ─┼─> *.wav ─> bin/transcribe-file.sh ─┬─> *.named.txt ─> diktatura.ui.app (📄 Tekstas)
bin/rec-toggle.sh   (ranka)  ─┘             (flock eilė, 1x1)      ├─ stereo -> diktatura.asr.transcribe_named
sekami aplankai (telefonas…) ─> transcribe-file.sh <garsas> <bazė> ├─ mono   -> diktatura.asr.transcribe
  (diktatura.sources; garsas lieka tavo aplanke)                    └─ aplankas -> transcribe_named --source
                                     -> <bazė>.peaks (🌊, diktatura.waveform) — PRIEŠ transkripciją
                                     nežinomas balsas -> speakers/pending/ ──> diktatura.ui.app (🎓 Apmokymai)
$XDG_RUNTIME_DIR/diktatura/recording  (būsenos failas „<šaltinis> <kelias>"; yra = rašoma; 💊 ui.pill skaito wav galą)
```

### Kur kas gyvena (kodas ≠ duomenys)

Repo — **tik kodas**. Duomenys — Linux XDG katalogai, kad privatūs įrašai fiziškai negalėtų patekti į git.
Visi keliai apibrėžti **vienoje vietoje**: `diktatura/paths.py` (Python, tik stdlib) ir jo bash atitikmuo
`bin/common.sh` — **laikyti sinchronizuotus**.

| Kas | Kelias | Env perrašymas |
|---|---|---|
| Nustatymai | `~/.config/diktatura/diktatura.conf` (numatytieji: `config/diktatura.conf.default`) | `DIKTATURA_CONFIG_DIR` |
| Įrašai, tekstai | `~/.local/share/diktatura/recordings/` (+ `<bazė>.peaks` — 🌊 banga, `<tekstas>.prev` — prieš „🔁 iš naujo") | `DIKTATURA_DATA` (visai duomenų šakniai) |
| Sekamų aplankų tekstai | `~/.local/share/diktatura/sources/<id>/<failas>.{named.txt,peaks,src.json,skip}` (garsas — tavo aplanke) | ↑ |
| Sekami aplankai | `~/.config/diktatura/sources.json` | `DIKTATURA_CONFIG_DIR` |
| Balsai | `~/.local/share/diktatura/speakers/{enroll.json,owner.json,pending/,ignored.json,assigned.json}` | ↑ |
| Žymės (⭐/☐), statistikos nunulinimas | `~/.local/share/diktatura/{annotations,stats_reset}.json` | ↑ |
| Modeliai | `~/.local/share/diktatura/models/{azuolas-ct2,diarization,hf}` | ↑ |
| Logai, transkripcijų trukmės (prognozei) | `~/.local/state/diktatura/{autorecord,transcribe,debug}.log`, `timing.json` | `DIKTATURA_STATE` |
| Runtime | `$XDG_RUNTIME_DIR/diktatura/{recording,transcribe.lock,rec-toggle.pid,asr.sock,pause,progress/}` | `DIKTATURA_RUN` |

Testai ir eksperimentai nustato šiuos env į laikinus katalogus — realūs duomenys nepaliečiami.

- **Įrašymas** visada **STEREO 16 kHz**: kairys = mikrofonas (tu), dešinys = sistemos garsas (monitor = kolegos).
- **`bin/transcribe-file.sh`** — centrinis „analizatorius": `flock` eilė (tik 1 transkripcija vienu metu, kad neOOM'intų),
  priima wav arba mp3; modelis/gijos iš nustatymų (`DIKTATURA_MODEL`/`DIKTATURA_THREADS` perrašo); tuščias tekstas →
  trina (jei `DELETE_EMPTY`), su tekstu → wav virsta mp3 (jei `ARCHIVE_MP3`); `nice 19 + ionice idle`
  (kad garso capture nebadautų). Tuščias failas (≤ 44 B — įrašymas nutrūko) netranskribuojamas, o ištrinamas.
  Pabaigoje (`trap EXIT`, dar laikant eilės užraktą) — **seno garso valymas** `diktatura.cleanup` (žr. žemiau).
  `DIKTATURA_ASR_CMD` — ASR imitacija testams. Gavus užraktą, PIRMIAUSIA — 🌊 smailės `<bazė>.peaks`
  (`diktatura.waveform`, ~1 % transkripcijos laiko; nepavyko — ne bėda; nužudytas signalu — darbas baigtas, žr.
  gotchas), kelias perduodamas ASR moduliui `DIKTATURA_PEAKS` (eigos failui → ⏳ banga).
  Antras argumentas — **išvesties bazė** (sekami aplankai): tekstas / banga / `.skip` rašomi ten, `--source` (visas
  garsas — vienas kanalas su vardais pagal balsus), garsas niekada netrinamas / nekonvertuojamas, tuščias → `.skip`.
  `DIKTATURA_RETRANSCRIBE=1` (🔁): ASR rašo į `<tekstas>.retx` (ne `.txt` galas — Tekstas nerodo kaip sesijos),
  pavykus — senas → `<tekstas>.prev`, naujas į vietą; tuščias / klaida — senas lieka, nieko netrinama.
  ASR moduliai priima `--out` (ir mono `--srt`).
- **`diktatura.progress`** (stdlib; ⏳ langelis, ikonos meniu, `make progress`): KAS vyksta — iš procesų
  (`transcribe-file.sh <failas>`: vaikas `flock` = laukia eilėje, kitaip vykdomas; `transcribe-pending.sh` — jo dar
  nepaleisti failai), tik tos pačios aplinkos (`/proc/<pid>/environ` → tas pats `<runtime>` = ta pati eilė); EIGA —
  `<runtime>/progress/<bazė>.json`, kurį rašo ASR modulis (`Reporter`: etapai `prep → vad → load → asr_me → asr_them →
  names`, mono `vad → load → asr`; Whisper etapuose — kiek kanalo garso apdorota, po kiekvieno segmento, ≤ 1 kartą/s;
  `pos` — iki kur ORIGINALAUS įrašo (VAD apkarpymas atstatytas) ir `peaks` — bangos failas: `processed_secs()` /
  `peaks_file()` ⏳ bangai);
  PROGNOZĖ — etapų greičiai iš `timing.json` (paskutinės 50 transkripcijų; sumų santykis + švelninimas numatytaisiais,
  kol istorijos mažai) × garso / VAD kalbos trukmė; Whisper etape — tikras greitis; sulėtėjimas (baigtų etapų ir
  dabartinio tikra / numatyta trukmė) taikomas likusiems etapams ir visai eilei (CPU apkrova). Bendra juosta — laikas
  nuo serijos pradžios (iš eilės baigtos transkripcijos) / (praėjęs + likęs). `skip_current()` — nužudo vykdomo darbo
  ASR / ffmpeg (bash baigia pats: „garsas paliktas"; laikini `diktatura-asr-<pid>-*` išvalomi), `stop_all()` — dar
  naktinį ciklą ir laukiančius (bash PIRMA, tada jo `flock` — kitaip bash eitų toliau be užrakto). ASR serverio darbo
  nutraukti negalima (mygtukas pilkas). ASR moduliai SIGTERM verčia `SystemExit` (sutvarko laikinus failus).
- **`diktatura.cleanup`** (stdlib; Nustatymai → Archyvas → `AUDIO_CLEANUP`): trina tik **garsą** (`*.wav`, `*.mp3`;
  wav+mp3 su ta pačia baze — vienas įrašas), tekstai lieka. `off` / `age` (senesnis nei `AUDIO_KEEP_DAYS`, laikas iš
  failo vardo) / `size` (kol `recordings/` failai — garsas + tekstai, be pakatalogių — > `AUDIO_MAX_GB`, trinami
  seniausi; **naujausias niekada**, net jei vienas viršija ribą). Niekada: rašomas / transkribuojamas
  (`reset.busy_bases`), ką tik keistas (< 60 s), be teksto ir be `.skip`, kol `AUTOTRANSCRIBE=1`. Tušti failai trinami
  visada (ir su `off`). Kviečia: `transcribe-file.sh` ir `transcribe-pending.sh` pabaigoje, `make cleanup [DRY=1]`,
  Nustatymų „Išsaugoti" (pakeitus trynimo nustatymus — su patvirtinimu). Žurnalas — `transcribe.log` („🧹").

### Įrašymo daemon'ai (systemd --user; veikia tik vienas — `Conflicts=`)
- `bin/autorecord.sh` (`diktatura-autorecord.service`, `make mode-slack`): aptinka Slack skambutį per PulseAudio
  `source-output`, kurio `application.name` ∈ {`ringrtc`, `Slack`, `WEBRTC VoiceEngine`} (žr. §5). Pradeda/sustabdo
  įrašymą (`SLACK_GRACE_SEC`). `MAX_REC_SEC` saugiklis nuo pakibusio huddle: įrašas sustabdomas ir **naujas
  nepradedamas, kol srautas nedings** (kitaip pakibęs srautas gamintų begalę failų). Testams: `DIKTATURA_PACTL`
  (imitacija), `DIKTATURA_MATCH`, `DIKTATURA_POLL`. Kol laisvos vietos < `DIKTATURA_MIN_FREE_MB` (200) — skambutis
  neįrašomas (pranešama vieną kartą).
- `diktatura.audio.vox` (`diktatura-vox.service`, `make mode-vox`): balso aktyvumo įrašymas. Vienas `ffmpeg`
  (mic+monitor → stereo s16le → `pipe:1`), Python skaito 100 ms gabalus, skaičiuoja RMS dBFS.
  Sprendimus priima **`VoxGate`** (gryna klasė, be I/O → testuojama sintetiniais lygiais):
  **adaptyvus gate su histereze** — triukšmo grindys (rolling 25-tas percentilis, 5 s, mokomasi budint) +
  `VOX_OPEN_MARGIN` (START) / `VOX_CLOSE_MARGIN` (SUSTAIN). 2 s kalibracija prieš leidžiant įrašyti. Pre-roll 0.8 s.
  **Įrašo metu grindys tik keliamos** (`VoxGate._refloor`): jei paskutinės ~10 s — pastovus garsas (mediana ≤ 3 dB
  virš tyliausių 10 %; kalboje skirtumas 7–12 dB), o net tyliausi gabalai virš išlaikymo slenksčio, grindys pasenusios
  → pakeliamos iki to fono, garso trukmė ir tylos skaitiklis perskaičiuojami (kalbai baigusis užsidaro kaip įprastai;
  jei visas įrašas buvo tik fonas — „per trumpas", ištrinamas). Žurnale: „↕ fonas garsesnis nei išmoktas triukšmo
  lygis". Fiksuotame režime (`VOX_ADAPTIVE=0`) — neliečiama.
  **Įrenginių sekimas:** ffmpeg srautai pavadinti `-name diktatura-vox-mic` / `diktatura-vox-sistema`; kas ~10 s
  `device_problem()` (`pactl list source-outputs`, `LC_ALL=C`) tikrina, ar mūsų srautai prijungti prie reikiamų
  šaltinių ir ar nepasikeitė numatytasis mikrofonas / garsiakalbiai. Jei ne — „🔀 … perjungiu garso capture":
  atidarytas įrašas uždaromas ir išsaugomas, ffmpeg paleidžiamas iš naujo su dabartiniais numatytaisiais, vėl 2 s
  kalibracija (ne dažniau nei kas 60 s; `pactl` nepasiekiamas — nieko nekeičiama; testų `DIKTATURA_CAPTURE_CMD` —
  nesekama). Failo vardas niekada neperrašomas (`new_recording_path`: ta pati sekundė → +1 s).
  1 MB pipe buferis + `thread_queue_size` (apsauga nuo capture-badavimo). `VOX_MIN_SEC` tikrina **garso** trukmę
  (nuo atsidarymo iki paskutinio garsaus gabalo), ne failo — kitaip kosulys + tylos uodega praeitų.
  **Pauzė perklausai** (`diktatura.pause`, `<runtime>/pause` su galiojimo laiku): kol Diktatūra pati groja garsą
  (Apmokymų ▶, Teksto „▶ Groti nuo čia"), VOX kas 0.5 s tai mato — naujo įrašo nepradeda, atidarytą uždaro, triukšmo
  lygio iš grojamo garso nesimoko (kitaip perklausa per kolonėles taptų nauju „pokalbiu" ir nežinomu balsu). UI
  pratęsia pauzę kas ~1 s; sustojus — 1.5 s uodega; nulūžus UI — pauzė pasibaigia pati po ~3 s. Slack režimas
  nepaliečiamas (įrašo tik skambučius; pristabdžius dingtų skambučio garsas).
  SIGTERM/SIGINT → švarus uždarymas (wav antraštė, būsenos failas), transkripcija tada nepaleidžiama (systemd ją
  nužudytų kartu su servisu — įrašą paims naktinis). Išėjimo kodai: 0 sustabdyta; 3 capture netikėtai baigėsi
  (systemd `Restart=on-failure` perkrauna). Testams: `DIKTATURA_MIC`/`DIKTATURA_MONITOR` (virtualūs įrenginiai),
  `DIKTATURA_CAPTURE_CMD` (komanda su stereo s16le PCM vietoj ffmpeg).
  **Pilnas diskas:** laisvos vietos < `MIN_FREE_MB` (200; `DIKTATURA_MIN_FREE_MB`) — naujas įrašas nepradedamas
  (vienas pranešimas, kol vietos atsiras); `ENOSPC` įrašo viduryje — įrašas nutraukiamas, `salvage()` perrašo wav
  antraštę pagal tai, kas spėjo įsirašyti (antraštė jau išskirtame bloke — vietos nereikia; < 1 s — trinama), VOX
  dirba toliau. Išsaugotą dalį transkribuoja naktinis.
- `bin/rec-toggle.sh` (`make rec-toggle`, galima susieti su klavišu): rankinis start/stop → `rec_*.wav`.

### ASR + kalbėtojų atpažinimas (`.venv`)
- **VAD vartai** (`diktatura.audio.prefilter`, Silero per `faster_whisper.vad`): ASR moduliai pirmiausia randa kalbą
  kiekviename kanale ir **tik tada** krauna modelį. Kanalas be kalbos (< `VAD_MIN_SPEECH_SEC`) praleidžiamas; jei
  visas įrašas be kalbos — tuščias tekstas, modelis nekraunamas (`DELETE_EMPTY` jį ištrina). `VAD_TRIM=1` — Whisper'iui
  tik kalbos atkarpos su laikų perskaičiavimu (`remap`); numatytai 0 (matavimas — PLAN Etapas 2).
- ASR moduliai turi `run(argv, get_model)` — modelį paduoda `diktatura.asr.models.load` (atskiras procesas) arba
  nuolatinis serveris (`diktatura.asr.server`, žr. žemiau).
- `diktatura.asr.transcribe_named` (pagrindinis): L — **kolegų garso kopijos atėmimas** (`ECHO_CANCEL`,
  `diktatura.audio.echo`, žr. §3) → `loudnorm` kiekvienam kanalui → VAD → Whisper(Ąžuolas) L ir R →
  kiekvienam R (kolegų) segmentui **balso embedding** (sherpa-onnx) → cosine su `enroll.json` ir tavo balsu
  (`owner.json`); **griežtas sprendimas** (`speakerlib.decide`): vardas tik jei panašumas ≥ `SPEAKER_THRESHOLD` IR
  bent `SPEAKER_MARGIN` didesnis nei antro kandidato — kitaip `Kolega?` (du žinomi balsai per panašūs → ne naujas
  žmogus, į pending nededama). Tavo balsas R kanale (prisijungęs telefonu) → `Tu`.
  Nežinomas → išsaugo pavyzdį `speakers/pending/` ir žymi `Kolega?nezN`. Tada **de-dup**: „Tu" eilutės,
  kurių ≥60% žodžių yra laike persidengiančiose „Kolegos" eilutėse → nutekėjimas → išmetama.
- `diktatura.asr.transcribe`: mono įrašams (be kalbėtojų) → `.txt` + `.srt`.
- `diktatura.speakers.speakerlib`: embedding (3D-Speaker CAM++ zh-en „advanced" ONNX, `paths.EMB_MODEL_FILE`), cosine,
  `ranked` / `decide` (slenkstis +
  atsarga), `label_segments` (gryna vardų priskyrimo logika: registruotas → vardas; tavo balsas → `Tu`; per panašūs →
  `Kolega?`; „triukšmas" (ignored) → `Kolega?`; nežinomas → `Kolega?nezN` + pending).
- `diktatura.speakers.teach` (.venv): **mokymasis iš pataisymo** — Teksto „✎ Kas kalbėjo?" → UI pervadina eilutę
  (`store.relabel_line`) ir fone paleidžia `teach <tekstas> <eilutė> <vardas|Tu>`: eilutės atkarpa (iki kitos eilutės,
  ≤ 20 s) iš wav/mp3, R kanalas jei jame yra kalbos (kitaip L), tik kalba (VAD) → embedding → `enroll.json` arba
  `owner.json`. Išėjimo kodai: 0 išmokta, 3 per mažai kalbos (< 1.5 s), 2 nėra garso/eilutės.
- `diktatura.speakers.store` (**tik stdlib** — naudoja ir UI): `enroll.json`, `owner.json` (tavo balsas, paskutiniai
  40 pavyzdžių), `pending/` (id niekada nekartojami — `pending/.next`), `ignored.json`, `assigned.json`;
  `assign` (vardas „Tu" → `assign_owner`) / `discard` / `rename_speaker` / `relabel_line` ir **retroaktyvus
  pervadinimas tekstuose** (`Kolega?nezN` → vardas, tik kalbėtojo vietoje). `resolve_labels` — jei vardas priskirtas
  transkripcijos metu, nauja transkripcija pasitaiso.
- `diktatura.asr.dialog` (stdlib): de-dup ir eilučių formatavimas; `diktatura.sessions` (stdlib): įrašų vardai/datos,
  rodomi tekstų failai, `[H:MM:SS] Kas: tekstas` eilutės.
- `diktatura.speakers.{enroll,diarize,recluster,name_clusters}`: registracijos ir diarizacijos įrankiai
  (`make assign`, `make enroll`; inference metu užtenka per-segmento embedding'o, klasterizavimo nereikia).
- Modelio vardas → kelias: `paths.model_path()` / `common.sh model_path` (`azuolas-ct2` → lokalus CT2 katalogas,
  kita — faster-whisper vardas, pvz. `medium`).
- **Nuolat įkrautas modelis (nebūtina, `ASR_SERVER=1`):** `diktatura.asr.server` (`diktatura-asr.service`, Nice=19,
  IO idle) laiko modelį atmintyje ir priima darbus per Unix lizdą `<runtime>/asr.sock` (JSON eilutė); po
  `ASR_SERVER_IDLE_MIN` be darbo modelis iškraunamas. `transcribe-file.sh` (vis dar su `flock`) siunčia darbą per
  `diktatura.asr.client`; serverio nėra → kodas 75 → transkribuojama atskiru procesu kaip anksčiau. Kaina — ~3 GB RAM
  kol yra darbo, todėl numatytai išjungta (`make asr-server-on/off` arba Nustatymai).

### UI (SISTEMOS `python3` — turi gi/GTK; `.venv` jo neturi)
- `diktatura.ui.tray` (`diktatura-tray.service`): AyatanaAppIndicator3. Būsena: runtime `recording` failas = 🔴,
  vyksta `diktatura.asr.*` arba mp3 konversija = 🟡, kitaip ⚪ (`compute_state` — gryna funkcija). Kol yra nežinomų
  balsų (`speakers/pending/`) — **pulsuoja** (pilna ↔ `*-dim.png` tos pačios spalvos, ~1 s; `icon_name()`).
  Meniu: „⚙ Nustatymai" (viršuje), „🎓 Apmokymai paruošti (N)" (kai yra), „📄 Rodyti nuskaitytą tekstą", „⏳ 43 % · liko …" (kol transkribuojama — eigos langelis), būsena,
  režimas, įrašų aplankas, „Išeiti" (uždaro tik ikoną — įrašymo servisas veikia toliau; grąžinti: doko
  „Diktatūra" arba `make tray-on`). **Vidurinis klik → Nustatymai.** Ubuntu AppIndicator paspaudus visada atidaro
  meniu — langas tiesiai neatsidaro, todėl Nustatymai meniu viršuje. Testams `Tray(indicator=…, opener=…)`.
  **💊 Įrašymo indikatorius** (`ui.pill`, `REC_PILL`; ikonos procese, laikmatis 100 ms): kol `<runtime>/recording`
  rodo įrašą ≥ 1.5 s — POPUP langelis apačioje dešinėje: 🔴, šaltinis, laikmatis, gyva abiejų kanalų banga (8 s).
  Lygiai — iš rašomo wav GALO (`LiveLevels`: antraštė → „data" blokas, ffmpeg LIST praleidžiamas; skaitomi tik nauji
  pilni 100 ms gabalai) — VOX ir Slack daemon'ų keisti nereikėjo. Po įrašo (`after_text`, gryna): „⏳ Transkribuojama
  43 %" (diktatura.progress), „⏳ Laukia eilėje", „🌙 transkribuos naktį", „✅ Tekstas paruoštas", ištrintas (per
  trumpas) — dingsta. Spragtelėjus — Tekstas (transkribuojant — ⏳), ✕ — iki kito įrašo. `PillController` — būsenos be
  GTK (testuojama), `PillView` — GTK.
- **Programų meniu / dokas:** `make desktop` (`desktop/diktatura.desktop.in` → `~/.local/share/applications/`;
  įeina į `make install`) → `bin/diktatura-open.sh`: įjungia `diktatura-tray` (jei uždaryta) ir atidaro langą.
  Langas `GLib.set_prgname("diktatura")` → WM_CLASS sutampa su `StartupWMClass` — dokas jį rodo prie prisegtos ikonos.
- `diktatura.ui.app`: **vienas langas** „Diktatūra" (Gtk.Application, vienas egzempliorius per D-Bus — antras
  paleidimas `--page <skiltis>` tik perjungia skiltį), skiltys `Gtk.Stack` + „◀ Atgal". `--shot <png>` — nuotrauka.
  📄 Tekstas — `TextTabs` (Gtk.Notebook): „🎙 Pokalbiai" (`win.text`) + po `TextPage(source=…)` kiekvienam sekamam
  aplankui (išjungtas, bet su tekstais — lieka); be aplankų skirtukų juosta paslėpta. Nematomas skirtukas
  neatnaujinamas (atsidarius — atnaujinamas). Ctrl+F — matomo skirtuko / Nustatymų paieška.
  - `ui.text_page` (📄 Tekstas): modelis sesija → eilutės; tail'ina `recordings/*.named.txt|*.txt|*.clean.dialog.txt`
    (`sessions.text_files`), papildymas → tik naujos pilnos eilutės; perrašytas failas (kitas inode, pvz. Apmokymuose
    pervadintas kalbėtojas) → perpiešiama. Skyrikliai, kalbėtojai spalvomis, paieška (nuo 3 simb., ◀▶, Ctrl+F, Regex),
    filtrai (kalbėtojas; laikotarpis — pask. `RETENTION_DAYS` d. / šiandien / vakar / 7 / 30 d. / visas archyvas;
    tik žymėtos). Eilutės pradžioje `TextMark` → `line_at_iter()` (išlieka redaguojant) — ant jo remiasi dešinio klik
    meniu: ▶ groti nuo eilutės (`ui.player.SeekPlayer` — ffplay; grojama eilutė paryškinama), ⭐/☐/☑ žymės
    (`diktatura.annotations`, `<duomenys>/annotations.json`), 🎓 priskirti vardą `Kolega?nezN`, ✎ Kas kalbėjo?
    (pataisyti kalbėtoją + išmokti balsą fone — `speakers.teach`, komanda `text_page.teach_cmd`). 📊 statistika
    (`sessions.speaker_stats`; „↺ Nunulinti" — `diktatura.stats`: skaičiuoja tik eilutes po įsiminto laiko, nieko
    netrina), 💾 eksportas (.txt/.md).
    🌊 **Banga** (`WAVEFORM`, „🌊 Banga"; `ui.waveform_view.WaveformView` — DrawingArea + cairo, be numpy): naujausios
    sesijos, o spragtelėjus eilutę / grojant — tos (pažymėta; „⤓ Naujausia" / „Sekti naujus" — atgal). Stereo — dvi
    juostos (Tu / kolegos), kolegų — tuo metu kalbančio spalva (`segment_color`), viršuje eilučių žymės, pasirinkta
    eilutė — juosta, grojimo žymeklis (grojimas išeina už vaizdo — slenka). Spragtelėjus — `play_at()`, ratukas —
    artinti ties pele (≥ 10 s), Shift+ratukas — slinkti, 2× — visa sesija; tooltip — laikas + eilutė. Smailės —
    `<bazė>.peaks` (`diktatura.waveform`: uint8 dBFS kas 100 ms kanalui, 2 val. ≈ 144 KB; piešiant — fonas (20-tas
    percentilis) = 0, garsiausia (99,5-tas) = pilna); nėra, bet garsas yra — skaičiuojamos fone (`.venv`, nice 19).
    ✨ **Švarus** (`CLEAN_VIEW`, `FILLER_WORDS`; `diktatura.fillers`): rodomas tekstas be šnekos garsų (e, ee, mhm, aaa…;
    „e." lieka), vartotojo žodžių ir pasikartojimų; eilutė iš vien užpildų slepiama; paieška / eksportas — kaip rodoma;
    `Line.text` ir failai nekeičiami (žymės ⭐☐ ir toliau sutampa).
    🔁 **Transkribuoti iš naujo** (dešinys klik; garsas turi būti, ne `.clean.dialog.txt`, ne vykdomas) — patvirtinimas
    su trukmės prognoze → `services.spawn_detached` (`systemd-run --user` — savas cgroup, neužmuš uždarius langą)
    `transcribe-file.sh` su `DIKTATURA_RETRANSCRIBE=1`; „↩ Grąžinti ankstesnę transkripciją" — sukeičia su `.prev`.
    Sekamo aplanko skirtukas: viršuje aplankas, failų / tekstų / laukia, „🔄 Transkribuoti dabar"
    (`transcribe-pending.sh --sources`, atskirai), „📂 Atidaryti"; antraštėse — aplanko pavadinimas; žymių raktas
    `<id>/<failas>` (skirtingų aplankų failų vardai gali sutapti).
  - `ui.training_page` (🎓 Apmokymai): pending sąrašas + kontekstas (`store.occurrences_many`), ▶ grojimas
    (`paplay`; testams `DIKTATURA_PLAYER`), vardas su autocomplete → `store.assign`; „🙋 Tai aš" → `store.assign_owner`;
    „Ne žmogus" → `store.discard`; registruoti balsai: tavo balsas (pamiršti) + kolegos: pervadinti/sujungti/pamiršti.
    Po pakeitimų perpiešia Teksto skiltį.
  - `ui.progress_dialog` (⏳ Transkripcija; Teksto mygtukas — jo užrašas kas 2 s „43 % · liko ~1 val. · eilėje 4",
    ikonos meniu punktas, `app --progress`): modalinis kaip 📊 Statistika; dvi juostos (failas / visa eilė), praėjęs,
    likęs, pabaiga laikrodžiu, eilės lentelė su prognozėmis, sulėtėjimo pastaba; „⏭ Praleisti šį" / „⏹ Sustabdyti
    viską" su patvirtinimu (numatytasis „Atšaukti"); atsinaujina kas 1 s. 🌊 dabartinio failo banga: apdorota dalis
    ryški, likusi išblukusi (`progress.processed_secs`; stereo — pirma Tu, tada kolegos); smailių nėra — nerodoma.
  - `ui.settings_page` (⚙ Nustatymai): laukai generuojami iš `config.SCHEMA` (naujas raktas schemoje atsiranda
    automatiškai), įrašymo režimas per `services`, validacija prie laukų. „Archyvas" — gyva seno garso trynimo
    suvestinė (`cleanup.summary`: kiek užima, ką ištrintų lange pasirinkti nustatymai), nereikalingas laukas pilkas;
    pakeitus trynimo nustatymus „Išsaugoti" paklausia („Išsaugoti ir ištrinti") ir trina iškart. Apačioje, toli nuo „Išsaugoti" —
    „Atstatymas ir duomenys": „Atkurti numatytus nustatymus…" (patvirtinimas su pasikeisiančių sąrašu) ir „Ištrinti
    įrašus ir tekstus…" (`diktatura.reset`: varnelės įrašai+tekstai / laukiantys vardo balsai / vardų atpažinimas;
    numatytai — tik pirma). Abiejuose dialoguose numatytasis mygtukas — „Atšaukti" (Enter neištrina).
    🔍 **Paieška** viršuje (Ctrl+F, Esc): kiekvienas nustatymas — paieškos elementas (pavadinimas + laukas +
    paaiškinimas, raktas); lyginama be didžiųjų ir lietuviškų raidžių skirtumo (`fold()` — NFKD be diakritikų, su
    vietomis originale → paryškinimas `<span background>` tiksliai ant originalaus teksto); grupės pavadinimo
    atitikmuo — visa grupė; grupės be atitikmenų slepiamos. Paslėpti laukai išsaugomi kaip įprastai.
    **Sekami aplankai** (po „Transkripcija"): sąrašas (jungiklis, pavadinimas, kelias, failų / tekstų / laukia, 📂, ✕),
    „➕ Pridėti aplanką…" (pavadinimas, poaplankiai, „ir jau esančius failus" — numatytai tik jei jų ≤ 20) — taikoma
    iškart, ne per „Išsaugoti"; pirmas aplankas įjungia `diktatura-sources.timer` (trūkstant unit'ų — `install_units()`).
- `diktatura.reset` (stdlib): ką trinti pagal kategoriją; niekada — nustatymų, modelių, logų, `model.json`,
  `assigned.json`, DABAR rašomo (`<runtime>/recording`) ir DABAR transkribuojamo / archyvuojamo įrašo (pagal
  `pgrep` argumentus) — kitaip transkripcija po valymo „atgaivintų" seną tekstą. Eilėje laukę ištrinti įrašai
  praleidžiami (`transcribe-file.sh`: „PRALEISTA").
- `ui.gtk`: GTK versijos ir bendras CSS vienoje vietoje; `WrapBox` / `flow()` — mygtukų juosta, kuri siaurame lange
  persikelia kaip tekstas (Gtk.FlowBox netiko — dėlioja stulpeliais). UI moduliuose — jokio numpy/faster-whisper.
- `ui.themes` (Nustatymai → Išvaizda → `THEME`): light (kaip sistemoje) / dark (sistemos temos tamsus variantas) /
  contrast (GTK „HighContrast", šriftas ×1.4, storas fokuso rėmelis, pagalbinis tekstas nepritemdytas) / compact
  (šriftas ×0.85, mažesni mygtukai, Apmokymuose be įžangos). `themes.apply()` keičia `Gtk.Settings` tik šiam procesui
  (gtk-theme-name, prefer-dark, gtk-xft-dpi) + temos CSS; `MainWindow.apply_theme()` — paleidžiant ir išsaugojus;
  skiltys persidažo per `on_theme()` (teksto lango kalbėtojų spalvos — tamsiame fone šviesesnės, kontraste sočios).
- **Mažas ekranas:** kiekviena skiltis — vertikaliai slenkamoje srityje (`MIN_PAGE_HEIGHT`): GTK3 langą leidžia
  sumažinti tik iki aukščio, kurio reikėtų siauriausiam langui (buvo ≥ 733 px), dabar ~320 px. Mažiausias plotis
  ~670 px (buvo 1127): juostos — `flow()`, nustatymų pavadinimai laužomi, teksto būsena sutrumpinama (…).
  Apmokymuose — du skirtukai „🔎 Laukia vardo (N)" / „👥 Registruoti balsai (M)" (per visą aukštį), įžanga sutraukiama.

### Valdymas / konfigūracija
- `Makefile` — visos komandos (`make help`). Keliai jame išvedami taip pat kaip `paths.py` (XDG + `DIKTATURA_*`).
- `make doctor` (`diktatura.doctor`, tik skaito): įrankiai, garsas, `.venv`, GTK/AppIndicator, modeliai (+SHA-256),
  nustatymai, servisų failai vs šablonai, režimas/ikona/naktinis, hooks, RAM/diskas → ✓/⚠/✗ + patarimas.
- `diktatura.services` (stdlib): systemd --user vienoje vietoje (režimas vox/slack/off, timer'iai, unit'ų būklė,
  `install_units()` kaip `make install-units`, `spawn_detached()` — ilgi darbai iš lango per `systemd-run --user`).
  Testams `DIKTATURA_SYSTEMCTL` / `DIKTATURA_SYSTEMD_DIR`.
- **Sekami aplankai** (`diktatura.sources`, stdlib; `make sources`): `sources.json` — id (slug), pavadinimas, kelias,
  įjungtas, poaplankiai, `since` (senesni failai ignoruojami). Garso failai (m4a, mp3, wav, ogg, opus, flac, aac, amr,
  3gp, wma, webm; be `.part` / paslėptų), nekeisti ≥ 60 s (sinchronizuojami). Išvesties bazė
  `<duomenys>/sources/<id>/<failas>` (poaplankis — „ ⁄ "), `<bazė>.src.json` — garso kelias ir įrašymo laikas (iš vardo
  `20261014_101500` / `2026-10-14 10.15.00`, tada ffprobe `creation_time`, tada mtime) — `sessions.audio_for` /
  `session_dt` jį naudoja. Transkripcija: naktinis (`transcribe-pending.sh` — įrašai, tada aplankai) ir
  `diktatura-sources.timer` kas 2 min (`--sources --if-immediate`: tik MODE=immediate + AUTOTRANSCRIBE; tylus, kai nėra
  ką daryti). ⏳ eiga (`progress.pending_files`) juos mato. „Ištrinti įrašus ir tekstus" trina ir aplankų tekstus
  (garso — niekada). `doctor` — ar aplankai pasiekiami, ar „iškart" režimui įjungtas timer'is.
- **MCP serveris** (`diktatura.mcp_server`, `bin/mcp-server.sh`, `make mcp` — tik parodo registravimo komandą):
  JSON-RPC 2.0 per stdio (versijos 2025-06-18 / 2025-03-26 / 2024-11-05), TIK SKAITO: `list_sessions`, `search`
  (regex, kalbėtojas, laikotarpis, šaltinis, clean), `get_transcript` (laiko intervalas, ≤ 1500 eil.),
  `speaker_stats`, `list_sources`. Duomenys — `diktatura.transcripts` (pokalbiai + sekami aplankai, be GTK). Klaida
  įrankyje → `isError`, serveris nelūžta. Privatumas: niekur nejungia pats; ką perskaito klientas — jo pokalbyje.
- **Debug:** `diktatura.debug` + bash `dbg` (`bin/common.sh`) → `~/.local/state/diktatura/debug.log` (> 5 MB → `.1`).
  Įjungiama nustatymu `DEBUG` (`make debug-on`) arba `DIKTATURA_DEBUG=1|0` (env nugali). `make dlogs` — gyvai.
- **Nustatymai** — `diktatura/config.py`: `SCHEMA` (tipas, ribos, LT aprašas kiekvienam raktui), `load()` (netinkama
  reikšmė → numatytoji, sistema nelūžta), `save()` (validacija + atominis rašymas), `reset()`. CLI:
  `python3 -m diktatura.config show|get|set|reset|path` (`make config`, `make set S="K=V"`).
  **Taikoma be restarto:** VOX perskaito kas ~5 s, Slack daemon — kiekvieną ciklą, teksto langas — kiekvieną atnaujinimą.
  Bash skriptai config `source`'ina (`load_config` iš `common.sh`): pirma numatytieji, tada vartotojo.
- systemd šablonai `systemd/*.in` su `@REPO@` → `make install-units` įrašo į `~/.config/systemd/user/`
  (repo galima klonuoti bet kur).
- Naktinis `diktatura-nightly.timer` (01:30) → `bin/transcribe-pending.sh` (visi įrašai be teksto, tada sekamų
  aplankų failai; praleidžia rašomą failą ir `.skip`; pabaigoje — seno garso valymas, net jei transkribuoti nebuvo ką).
- Modeliai: `make models` (`tools/fetch_models.sh` — kalbėtojų ONNX, SHA-256 tikrinami), `make model-convert`
  (`tools/convert_azuolas.sh` — Ąžuolas → CT2 int8; torch tik laikiname venv).

## 3. Kodėl tokie sprendimai (esminiai „kodėl")

- **Ąžuolas** (`akisviete/azuolas-whisper-lt`, whisper-large-v3 + LIEPA-3) — **geriausia LT kokybė**
  (~4.6% WER CV LT). Benchmark ant realaus pokalbio: medium 4/5 (RTF 1.1), large-v3 4.5/5 (RTF 2.4),
  **Ąžuolas 4.7/5** (RTF ~3.2) — taiso LT-specifinius žodžius (branduolys, siurbti, diegimų, it). Riba visų —
  angliškas žargonas (code-switching), neišvengiama. Savininkas pasirinko Ąžuolą (kokybė > greitis).
- **faster-whisper (CTranslate2, int8)** — greitas CPU, be runtime torch. Ąžuolas konvertuotas į CT2
  (`tools/convert_azuolas.sh`, torch reikia tik konversijai — laikiname venv).
- **sherpa-onnx diarizacijai/embeddingams** — ONNX, **be torch**, be HF tokeno → lengva šiai geležei.
  Embedding: **3D-Speaker CAM++ zh-en „advanced"** (nuo 2026-10-09; anksčiau CAM++ en VoxCeleb). Pasirinkta
  matuojant savininko įrašuose (vienkartinis tyrimas, 7 sherpa-onnx modeliai; tavo „Tu" segmentai iš skirtingų
  pokalbių vs kolegų segmentai): EER — CAM++ VoxCeleb ~13 %, wespeaker CAM++ LM ~13 %, ResNet34 LM ~8 %,
  **CAM++ zh-en advanced ~0–1 %**, TitaNet large ~0–1 % (2.6× lėtesnis), ERes2NetV2 ~0–1 % (7× lėtesnis).
  Tas pats dydis (28 MB) ir greitis kaip buvusio. Pastebėta: seno modelio vardai tekstuose buvo beveik atsitiktiniai
  (tos pačios žymės eilutės tarpusavyje ne panašesnės nei skirtingų; naujas modelis vakarykščiuose pokalbiuose rado
  ~7 balsus, kuriuos senas beveik visus vadino vienu vardu). Todėl senų balsų „neperkeliam" — `make speakers-migrate`
  juos archyvuoja, vardai išmokstami iš naujo (Apmokymai, „✎ Kas kalbėjo?", `make speakers-relabel`).
  Žymė `speakers/model.json`: skirtingų modelių vektoriai nesulyginami — nesuderinama saugykla → vardai nerašomi.
- **STEREO (L=mic, R=monitor)** — leidžia „Tu vs kolegos" atskyrimą be diarizacijos; kolegų kanalas švarus.
- **De-dup (žodžių persidengimas)** — headset mic pagauna kolegų garsą (nutekėjimas į L); kadangi tavo balso
  R kanale paprastai nėra, dubliuotos „Tu" eilutės = nutekėjimas → šalinamos. **Išimtis** — prisijungęs prie to paties
  skambučio telefonu: tavo balsas ateina ir per R. Tada R eilutė žymima „Tu" (jei tavo balsas žinomas), o L kopija
  išmetama kaip dublis.
- **Aidas tavo kanale = ausinių lizdo persiklojimas, ne ausinės ir ne tvarkyklė (2026-10-09).** „Tu" eilutėse buvo
  kolegų žodžių. Matuota (HP EliteBook 850 G8, Realtek ALC285, laidinės ausinės su mikrofonu): L kanale — tiesinė R
  kopija −20…−28 dB, koherencija iki 0.9, dažnių atsakas plokščias 100 Hz–1.6 kHz (akustinis iš ausinių būtų „spalvotas"),
  proporcinga garsumui (kontroliuotas testas 52 % garsumu: −44 dB). ALSA/PulseAudio loopback'o nėra — kita tvarkyklė
  nepadėtų. Sprendimas — `diktatura.audio.echo`: kiekvienam įrašui poslinkis (kryžminė koreliacija) ir pastovus kelias
  H(f) (du etapai: antrame — tik kadrai, kur L ≈ nuotėkis), L' = L − h * R; prieš loudnorm (jis dinamiškai keičia
  stiprinimą ir tiesinį ryšį sugadintų). Rezultatas WAV įraše: L lygis kolegoms kalbant −49.5 → −66 dB (= triukšmo
  lygis), gaubtinių koreliacija su R 0.86 → 0.15, Whisper L kanale 22 segmentai radijo → 0, tavo žodžiai 94 % → 94 %.
  Kintantis (akustinis) kelias nuslopinamas tik iki triukšmo lygio — keli segmentai dar atpažįstami (PLAN Etapas 8).
  Kita išeitis — vidinis mikrofonų masyvas (DMIC) ar USB ausinės.
  Atmesta: ffmpeg `-probesize/-analyzeduration` kanalų poslinkiui (0.75 → 0.5 s, ne 0).
- **Griežti vardai (2026-10-09)** — klaidingas vardas blogiau už „Kolega?". Anksčiau: geriausias panašumas ≥ 0.5 →
  vardas, net jei antras kandidatas beveik toks pat, o tavo balso R kanale nebuvo su kuo palyginti (prisijungus
  telefonu tavo eilutė gavo kolegos vardą). Dabar: slenkstis + atsarga iki antro + tavo balsas kaip kandidatas;
  tavo balsas mokomas iš pataisymų (iš to paties kelio, t. y. telefono garso R kanale): matuota — tavo mikrofono
  balso vidurkis su tavo balsu per telefoną panašus tik ~0.3–0.6 (visi 7 modeliai), mažiau nei su kuriuo nors kolega,
  todėl „išmokti tave iš mikrofono" automatiškai nepadėtų.
- **Adaptyvus VOX gate** — mic lygis driftuoja (Slack AGC / Ubuntu), tad fiksuoti dB slenksčiai trapūs;
  adaptyvus (triukšmas + atsarga) prisitaiko.
- **`deferred` režimas + flock eilė + nice/ionice + buferiai** — **svarbiausia pamoka:** transkripcija
  (Ąžuolas ~3.3 GB) ĮRAŠYMO metu sukelia swap thrashing → PulseAudio numeta capture buferius → sugadintas
  (tylus) įrašas. Sprendimas: niekada netranskribuoti lygiagrečiai su įrašymu (naktinis režimas), o jei
  immediate — capture turi pirmenybę (buferiai + žemas transkripcijos prioritetas).
- **mp3 archyvas** (64 kbps) po transkripcijos — vietos taupymui; tušti įrašai trinami.
- **🌊 Smailės atskirame faile, ne iš garso kaskart:** UI veikia sistemos python3 be numpy; 6.4 val. mp3 dekoduoti
  trunka ~26 s (nice 19), o skaityti `.peaks` (≈ 460 KB) ir paruošti 1000 stulpelių — kelias ms. Be to banga lieka
  ištrynus seną garsą. Skaičiuojama transkripcijos pradžioje — kad ⏳ langelis jau ją rodytų.
- **💊 Lygiai iš wav galo, ne iš VOX:** tas pats veikia VOX ir Slack (abu rašo stereo wav), daemon'ų keisti nereikia,
  o ikonos procesas jau veikia visada.
- **Sekami aplankai — tekstai atskirai, garsas vietoje (savininko sprendimas 2026-10-15):** „nemesti į bendrą pool'ą" —
  studijos, laikrodžio, telefono įrašai analizuojami atskirai (skirtukai). Garsas nekopijuojamas (vieta diske) ir
  nekeičiamas — sinchronizuojami aplankai gali grįžti į telefoną. Vietoj vienkartinio „📥 įkelti failą" (Etapo 13 4
  punktas) — sekami aplankai: įkelti = įmesti failą į aplanką.
- **Užpildai taisyklėmis, ne LLM:** LLM anksčiau atmestas (privatumas, RAM); tikruose tekstuose dažniausi „nu" (852),
  „žinai" (509), „tipo" (163), „mhm", „e/ee", „aaa" — šnekos garsai valomi visada, kalbos žodžiai — tik pasirinkti
  („žinai" dažnai prasmingas).

## 4. Geležies realybė (dizaino apribojimai)

Intel i7-1165G7 (4C/8T), **be CUDA** (tik Iris Xe), 15 GB RAM (dažnai įtempta, swap naudojamas), ribotas diskas.
→ int8 modeliai, gijų ribojimas, batch (ne realus laikas) dideliems modeliams, atminties saugikliai.

## 5. Gotchas (ką žinoti prieš keičiant)

- **Slack detekcija:** Slack laiko bendrą mic `RecordStream` atvirą IR ne skambučio metu → `MATCH=Slack`
  gali duoti false positive (buvo 228 min pakibęs įrašas). `ringrtc` = tikras huddle. `MAX_REC` saugiklis.
  Tikri skambučiai realiai sekami per `ringrtc`; „Slack" paliktas dėl visų atvejų — jei kartosis pakibimai,
  svarstyti tik `ringrtc` + audio-energijos gating'ą.
- **Capture-badavimas:** žr. §3 (transkripcija įrašymo metu). Nematuok „ar tyla" tik pagal uodegą — tikrink
  VISO įrašo garsą (buvo klaida palaikius realų įrašą tuščiu).
- **VOX kalibracija:** įrašymas leidžiamas tik po 2 s triukšmo mokymosi (kitaip close_thr per žemas → nesustoja).
- **Nesibaigiantis VOX įrašas + „sistemos" kanale mikrofonas (2026-10-13):** `vox_20261013_101730.wav` rašėsi 6.4 val.
  (1.4 GB), nors savininkas seniai nekalbėjo. Priežastis — dvi grandinės iš to paties įvykio: 2026-10-12 20:51 HP
  USB-C dokas atsijungė ir vėl prisijungė; nuo tada mikrofono kanalas davė −94 dB (praktiškai skaitmeninė tyla — ką
  kalbėta 20:51–10:13, į L kanalą nepateko; R kanalas veikė), ir VOX išmoko grindis −92 dB. ~10:14 mikrofonas vėl
  „atgijo", o kambario fonas (ventiliatorius, pastovus −49…−66 dB) buvo 26 dB virš grindžių → virš išlaikymo slenksčio
  (−84) → tyla niekada nebuvo „tyla". Grindys mokomos tik budint, o fonas iškart atidarydavo naują įrašą, tad jos
  nebeatsistatė; tą rytą įrašai užsidarydavo tik dėl Apmokymų perklausos pauzės, o po paskutinės (10:17:30) — niekada.
  Tuo pačiu PulseAudio perkėlė „sistemos garso" srautą į mikrofoną (R = L su 1.76 s vėlavimu, koreliacija 0.97) —
  kolegų garsas nebūtų įrašytas. Abu ffmpeg srautai vadinosi „Lavf58.76.100", tad ir `module-stream-restore` juos laikė
  vienu. **Taisymas:** `_refloor` (grindys keliamos įrašo metu), įrenginių sekimas + atskiri srautų vardai (žr. §3).
  Patikrinta perleidus tą patį 6 val. įrašą per naują logiką: užsidaro ~12:17, kai kalba baigėsi; likusios 4 val.
  ventiliatoriaus — jokio įrašo. **Atmesta hipotezė:** mikrofono garsumas (27 %, gal Slack AGC) — ne priežastis;
  lemia ne absoliutus lygis, o tai, kad grindys išmoktos vienomis sąlygomis ir nebeatsinaujina. Pastovumo riba (3 dB)
  parinkta pagal tikrą įrašą: pastovus fonas 0.5–1 dB, kalba 7–12 dB; 5 dB jau kartais suveikdavo sintetinei kalbai.
- **Du interpretatoriai:** `.venv` (Python 3.10: faster-whisper, sherpa-onnx, numpy, sklearn — daemon'ai ir ASR) ir
  **sistemos `python3`** (gi/GTK — tray ir teksto langas). Todėl `paths.py` ir `config.py` — **tik stdlib**
  (juos importuoja abu). UI moduliuose neimportuoti numpy/faster-whisper.
- **Paleidimas tik kaip modulio** (`python -m diktatura.…`) su `PYTHONPATH=<repo>` (`bin/common.sh` jį eksportuoja,
  systemd — `Environment=PYTHONPATH=@REPO@`). `python diktatura/asr/x.py` neveiks (paketų importai).
- **`pkill -f <šablonas>`** užmuša ir savo shell'ą, jei šablonas yra komandos eilutėje → naudoti `[.]` triuką
  (`pkill -f "diktatura[.]asr[.]"` — šablonas nesutampa su savo paties tekstu).
- **systemd --user:** `pactl`/DISPLAY prieinami tik prisijungus (ne prieš login); linger nereikia.
- **Virtualūs garso įrenginiai (E2E):** PulseAudio `module-null-sink` be grojimo užmiega (SUSPENDED) → jo monitor
  neduoda duomenų → ffmpeg `join` (mic+monitor) stringa. Be to null-sink capture vėluoja 6–9 s (tikri įrenginiai ~1 s
  tik paleidžiant). Todėl E2E: į abu null-sink'us leidžiama nepertraukiama tyla, o laikai matuojami įrašo turiniu
  (pvz. tylos uodega faile), ne laikrodžiu.
- **Kolegų vardai kode/testuose** — draudžiami (repo public): sargas blokuoja `.private-terms` terminus. Testuose —
  tik išgalvoti vardai (Ona, Jonas, Rūta…).
- **Balso modelis ir saugykla — pora:** embedding'ai iš skirtingų modelių nesulyginami. Keičiant modelį — naujas
  `store.EMB_MODEL` + `tools/fetch_models.sh` (URL, SHA-256); senų balsų saugykla tampa nesuderinama (vardai
  nerašomi, doctor — FAIL) iki `make speakers-migrate APPLY=1`. Balsų garso pavyzdžiai (išskyrus pending) nesaugomi,
  todėl seni balsai neperskaičiuojami — tik archyvuojami.
- **Nežinomi balsai — be „grandinės":** naujas segmentas lyginamas tik su pirmu nezN pavyzdžiu. Bandyta kaupti
  variantus (mažiau skaldymo) — 2 dienų tekstuose ~9 balsai susiliejo į 2 (A~A', A'~B…). Suskaidytą žmogų sujungti
  lengva (tas pats vardas Apmokymuose), suliejimo — ne.
- **L ir R įraše pasislinkę ~0.5–1 s** (ffmpeg du `-f pulse` įėjimai + `join`: mikrofonas pradedamas skaityti
  anksčiau; poslinkis pastovus per vieną VOX paleidimą, bet kinta tarp paleidimų). Kanalų laikų nelyginti tiesiogiai:
  de-dup turi 2 s atsargą, aido šalinimas poslinkį skaičiuoja pats.
- **`pending/.next` po `flock`:** nežinomus balsus vienu metu gali kurti transkripcija ir `make speakers-relabel`.
- **Testų LT fixture'ai — vienas kalbėtojas** (Common Voice klipai) — „skirtingų žmonių" testams netinka.
- **PyGObject + savas Gtk.Container (`WrapBox`):** jei Python nuorodos į objektą nėra, jo Python dalis (`_children`)
  dingsta — GTK naikindamas langą sukosi be galo (testai „pakibdavo"). Todėl `WrapBox._live` laiko objektus iki
  `do_destroy`. Taip pat `Gtk.Viewport` savo vaiko nesunaikina — `MainWindow._on_destroy` skiltis naikina aiškiai.
- **Pilnas diskas = 0 B wav lavina (2026-10-10):** VOX `wave.writeframes` gaudavo `ENOSPC`, procesas lūždavo, systemd
  perkraudavo, kitas garsas — vėl naujas failas ir vėl lūžis: per 45 min liko 19 tuščių `vox_*.wav`, o naktinis juos
  kas naktį bandė transkribuoti („Invalid data"). Diską užpildė ne Diktatūra (įrašų katalogas ~0.4 GB). Dabar: VOX
  tikrina vietą ir pergyvena `ENOSPC`, tušti failai trinami (`transcribe-file.sh`, `diktatura.cleanup`).
- **Niekada `pkill -f` su bendru šablonu (2026-10-12):** bandymo `pkill -f "^flock 9$"` nužudė TIKROS eilės `flock`
  vaikus → ~22 laukę darbai praėjo užraktą ir transkribavo lygiagrečiai šalia 2 val. įrašo (4 Ąžuolo krovimai ≈ OOM
  rizika; du sustabdyti SIGKILL ir grąžinti į eilę). Stabdyti tik pagal PID; `diktatura.progress` atrenka darbus pagal
  `<runtime>` ir pirma stabdo bash, tik tada `flock`. Tie lygiagretūs darbai dar ir „išmokė" prognozę netikrų greičių
  (10× lėtesnis paruošimas, „kalbos nėra") — todėl greičiai švelninami numatytaisiais, o užteršta istorija išvalyta.
- **`bin/*.sh` keisti ne vietoje, kai jie veikia:** bash skriptą skaito dalimis pagal poslinkį faile (fd 255), todėl
  perrašius `transcribe-file.sh` tame pačiame inode, vykstanti (ar eilėje laukianti) transkripcija toliau skaitytų
  pasislinkusį tekstą — atsitiktines komandas. Rašyti į laikiną failą ir `mv`/`os.replace` (naujas inode — veikiantys
  procesai skaito seną). Pagauta 2026-10-12: perrašius skriptą vietoje, vykstančiai 2 val. įrašo transkripcijai
  (sena versija) kitas tekstas būtų prasidėjęs eilutės viduryje — tame inode baitai sulygiuoti, švari versija padėta
  per rename. `make restart` VOX'ui nutraukia ir jo paleistas transkripcijas (tas pats systemd cgroup).
- **„Ar vyksta transkripcija?" — `pgrep -f` randa ir save (2026-10-15):** tikrinant prieš keičiant `bin/*.sh`,
  `pgrep -f "[t]ranscribe-(file|pending)\.sh"` vis tiek rado mano paties `bash -c …` (toje pačioje komandoje buvo
  `chmod --reference=bin/transcribe-file.sh` — `[t]` triukas gelbsti tik nuo paties šablono teksto). Tikri darbai
  paleidžiami kaip `bash /…/bin/transcribe-file.sh …`, tad tikrinti eilutės PRADŽIĄ:
  `pgrep -f '^(/usr/bin/|/bin/)?bash /[^ ]*/bin/[t]ranscribe-(file|pending)[.]sh'`.
- **⏭ „Praleisti" nužudo tik VAIKĄ:** bash tęsia kitą komandą. Iki ASR tai buvo gerai (nėra išvesties → „garsas
  paliktas"), bet 🌊 smailių žingsnis (prieš ASR) nužudytas „Praleisti" metu būtų leidęs transkripcijai prasidėti —
  todėl `transcribe-file.sh` signalu nutrauktą žingsnį (rc ≥ 128) laiko darbo pabaiga (testas Q9b).
- **Rašomas wav — antraštėje 0 B:** Python `wave` ir ffmpeg duomenų dydį įrašo tik uždarant, o ffmpeg dar prideda
  `LIST` bloką (antraštė ne 44 B). Gyvai skaitant (💊) — ieškoti „data" bloko ir skaičiuoti iš failo dydžio.
- **systemd oneshot = cgroup:** `diktatura-sources.service` transkribuoja pats (sinchroniškai), ne paleidžia ir išeina —
  išėjus servisui systemd nužudytų jo vaikus. Iš lango paleidžiami ilgi darbai (🔁, „🔄 Transkribuoti dabar") — per
  `systemd-run --user` (`services.spawn_detached`), kad neužmuštų uždarius langą ar perkrovus ikoną.
- **Sekamų aplankų failų vardai kartojasi** („Recording 1.m4a" telefone ir laikrodyje) — žymių raktas `<id>/<failas>`,
  tekstai atskiruose kataloguose; ne-ASCII ir tarpai varduose — normalu (testai su „Įrašas 7").
- **GTK laikmačiai po lango uždarymo:** `GLib.timeout_add` gyvena ilgiau už langą — sunaikintų valdiklių lietimas =
  segfault (pagauta UI testuose: „✎ Kas kalbėjo?" mokymosi laikmatis). Laikmačio callback'ai tikrina `self._alive`.

## 6. Privatumo sargas (git)

Repo public, o sistema dirba su labai asmeniškais duomenimis (pokalbių garsas, transkripcijos, balsų
biometrija). Apsauga sluoksniais — kiekvienas veikia net jei kitas sugenda:

0. **Duomenys už repo ribų** (XDG, §2) — įrašai, balsai, modeliai, logai repo kataloge net neatsiranda.
1. **`.gitignore`** (antras sluoksnis) — `recordings/`, `speakers/`, `models/`, `logs/`, `*.wav/mp3…`, `*.named.txt`,
   `enroll.json`, `ignored.json`, `assigned.json`, `annotations.json`, `tests/fixtures/{cv,private}/`,
   `STATUS.md`, `CLAUDE.md`, `.private-terms`, `config/diktatura.conf`.
   ⚠️ Komentarus rašyti TIK atskiroje eilutėje: `recordings/  # x` NEVEIKIA (git `#` atpažįsta tik eilutės pradžioje) —
   tokia klaida jau buvo ir išjungė apsaugą.
2. **`.githooks/`** (įjungiama `make hooks` → `git config core.hooksPath .githooks`; būtina po kiekvieno clone):
   - `privacy-scan.sh` — bendras skeneris: draudžiami keliai/plėtiniai, failai > 2 MB, asmeniniai terminai
     pridedamame tekste ir failų varduose, autoriaus/committer email. Režimai: `staged`, `commit <sha>`, `audit [rev]`.
   - `pre-commit` → `staged`; `pre-push` → kiekvienas stumiamas commit'as (pagauna ir `--no-verify`).
   - Funkcijos maitinamos here-string'u (`f <<< "$x"`), NE pipe — pipe paleistų jas subshell'e ir `fail=1` dingtų
     (sargas praneštų, bet neblokuotų). Šią klaidą pagavo testas.
3. **`.private-terms`** (lokalus, niekada į git) — kolegų vardai, darbovietė, darbo email, senasis vidinis projekto
   pavadinimas (kad negrįžtų); ERE, žodžio pradžioje,
   be didžiųjų/mažųjų skirtumo; `_ . / -` normalizuojami (pagauna `vardas_pastabos.md`, bet ne „paleidimas").
4. **Testai:** `make test-privacy` (`tests/privacy_guard_test.sh`) — laikiname repo su išgalvotais terminais +
   realaus repo `.gitignore`/hooks + **darbinio medžio auditas** (`privacy-scan.sh audit-worktree`: laikinas index,
   tarsi `git add -A` — pagauna ir dar neįtrauktus failus). Istorijos (HEAD) radiniai — tik informacija.

## 7. Testai

| Komanda | Kas | Trukmė |
|---|---|---|
| `make test` | greiti: nustatymai, VOX (sintetinis capture, pasenusios grindys, įrenginių perjungimas), 🌊 bangos (smailės, piešimas, Tekstas, ⏳), 💊 indikatorius, sekami aplankai (eilė, skirtukai, tavo failai nepaliečiami), 🔁 iš naujo, ✨ užpildai, MCP (tikras stdio), 🔍 Nustatymų paieška, Slack (netikras `pactl`/`ffmpeg`), eilė (netikras ASR), eiga ir prognozė (tikra eilė, praleidimas, stabdymas), seno garso trynimas ir pilnas diskas, de-dup, kalbėtojai (griežtumas, tavo balsas, pataisymai, modelio perėjimas), doctor, UI, regresija (užrakinta matoma elgsena), privatumas | ~2.5 min |
| `make test-full` | tikras Ąžuolas + LT kalba (Common Voice CC0, `make fixtures`), WER ≤ 25 %; tikras balso modelis; tavo balsas R kanale → „Tu" | ~1–5 min |
| `make test-e2e` | tikras VOX + ffmpeg per virtualius PulseAudio įrenginius | ~2 min |
| `make test-privacy` | privatumo sargas | ~10 s |

- **Saugiklis:** `tests/conftest.py` prieš bet kokį `diktatura.*` importą nukreipia `DIKTATURA_*` į laikiną katalogą ir
  į PATH priekį įdeda netikrą `notify-send` — testai neliečia tikrų duomenų ir nerodo pranešimų.
- Netikri įrankiai: `tests/helpers/fakebin/` (`notify-send`, `pactl`, `ffmpeg`, `systemctl-fake`), `fake_asr.sh`
  (`DIKTATURA_ASR_CMD`), `pcm_gen.py` (`DIKTATURA_CAPTURE_CMD`). Sintetinis garsas — `tests/helpers/audio.py`.
- `real_models` fixture: tikri modeliai per symlink + **tikras** transkripcijos `flock` (nesutaps su tikra transkripcija).
- UI testai — GTK per `broadway` (be tavo ekrano), sistemos `gi` per `.venv` (tas pats interpretatorius).

## 8. Kaip paleisti / tobulinti

```bash
make deps                      # sistemos paketai (sudo apt): ffmpeg, pactl, notify-send, GTK/AppIndicator
make install                   # hooks + .venv + kalbėtojų modeliai + servisai (ikona, naktinis, Slack režimas)
make model-convert             # Ąžuolas -> CT2 (vienkartinis, ~8–10 GB laikinai; arba make model-medium)
make mode-vox                  # arba likti Slack režime
make status                    # būsena;  make help — visos komandos
```
Po kodo pakeitimų: `make restart` (įrašymo daemon) / `make tray-restart`. Nustatymams restarto nereikia.
Nustatymai — `make config` / `make set`. Logai — `make logs`, `make tlogs` (`~/.local/state/diktatura/`).
