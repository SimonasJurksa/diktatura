# Diktatūra — techninė architektūra

Dokumentas skirtas **kūrėjui ar Claude sesijai**, norinčiai suprasti sistemą ir ją tobulinti.
Aprašo DABARTINĮ funkcionalumą techniniu lygiu (ne istoriją). Darbo žurnalas — `STATUS.md` (lokalus).

## 1. Ką daro (santrauka)

Lokalus, privatus balso-į-tekstą Linux'ui. Du įrašymo šaltiniai → transkripcija (lietuviškai,
Ąžuolas) → kalbėtojų atpažinimas vardais → langas „Diktatūra" (gyvas tekstas · balsų apmokymai · nustatymai)
+ status bar ikona. Viskas vietoje.

## 2. Komponentai ir duomenų srautas

```
ĮRAŠYMAS                            ANALIZĖ (po įrašo)                         RODYMAS
──────────                          ─────────────────                         ───────
bin/autorecord.sh   (Slack)  ─┐                                               diktatura.ui.tray (⚪/🔴/🟡)
diktatura.audio.vox (VOX)    ─┼─> *.wav ─> bin/transcribe-file.sh ─┬─> *.named.txt ─> diktatura.ui.app (📄 Tekstas)
bin/rec-toggle.sh   (ranka)  ─┘             (flock eilė, 1x1)      ├─ stereo -> diktatura.asr.transcribe_named
                                                                   └─ mono   -> diktatura.asr.transcribe
                                     nežinomas balsas -> speakers/pending/ ──> diktatura.ui.app (🎓 Apmokymai)
$XDG_RUNTIME_DIR/diktatura/recording  (būsenos failas „<šaltinis> <kelias>"; yra = rašoma)
```

### Kur kas gyvena (kodas ≠ duomenys)

Repo — **tik kodas**. Duomenys — Linux XDG katalogai, kad privatūs įrašai fiziškai negalėtų patekti į git.
Visi keliai apibrėžti **vienoje vietoje**: `diktatura/paths.py` (Python, tik stdlib) ir jo bash atitikmuo
`bin/common.sh` — **laikyti sinchronizuotus**.

| Kas | Kelias | Env perrašymas |
|---|---|---|
| Nustatymai | `~/.config/diktatura/diktatura.conf` (numatytieji: `config/diktatura.conf.default`) | `DIKTATURA_CONFIG_DIR` |
| Įrašai, tekstai | `~/.local/share/diktatura/recordings/` | `DIKTATURA_DATA` (visai duomenų šakniai) |
| Balsai | `~/.local/share/diktatura/speakers/{enroll.json,owner.json,pending/,ignored.json,assigned.json}` | ↑ |
| Žymės (⭐/☐), statistikos nunulinimas | `~/.local/share/diktatura/{annotations,stats_reset}.json` | ↑ |
| Modeliai | `~/.local/share/diktatura/models/{azuolas-ct2,diarization,hf}` | ↑ |
| Logai | `~/.local/state/diktatura/{autorecord,transcribe,debug}.log` | `DIKTATURA_STATE` |
| Runtime | `$XDG_RUNTIME_DIR/diktatura/{recording,transcribe.lock,rec-toggle.pid,asr.sock,pause}` | `DIKTATURA_RUN` |

Testai ir eksperimentai nustato šiuos env į laikinus katalogus — realūs duomenys nepaliečiami.

- **Įrašymas** visada **STEREO 16 kHz**: kairys = mikrofonas (tu), dešinys = sistemos garsas (monitor = kolegos).
- **`bin/transcribe-file.sh`** — centrinis „analizatorius": `flock` eilė (tik 1 transkripcija vienu metu, kad neOOM'intų),
  priima wav arba mp3; modelis/gijos iš nustatymų (`DIKTATURA_MODEL`/`DIKTATURA_THREADS` perrašo); tuščias tekstas →
  trina (jei `DELETE_EMPTY`), su tekstu → wav virsta mp3 (jei `ARCHIVE_MP3`); `nice 19 + ionice idle`
  (kad garso capture nebadautų). `DIKTATURA_ASR_CMD` — ASR imitacija testams.

### Įrašymo daemon'ai (systemd --user; veikia tik vienas — `Conflicts=`)
- `bin/autorecord.sh` (`diktatura-autorecord.service`, `make mode-slack`): aptinka Slack skambutį per PulseAudio
  `source-output`, kurio `application.name` ∈ {`ringrtc`, `Slack`, `WEBRTC VoiceEngine`} (žr. §5). Pradeda/sustabdo
  įrašymą (`SLACK_GRACE_SEC`). `MAX_REC_SEC` saugiklis nuo pakibusio huddle: įrašas sustabdomas ir **naujas
  nepradedamas, kol srautas nedings** (kitaip pakibęs srautas gamintų begalę failų). Testams: `DIKTATURA_PACTL`
  (imitacija), `DIKTATURA_MATCH`, `DIKTATURA_POLL`.
- `diktatura.audio.vox` (`diktatura-vox.service`, `make mode-vox`): balso aktyvumo įrašymas. Vienas `ffmpeg`
  (mic+monitor → stereo s16le → `pipe:1`), Python skaito 100 ms gabalus, skaičiuoja RMS dBFS.
  Sprendimus priima **`VoxGate`** (gryna klasė, be I/O → testuojama sintetiniais lygiais):
  **adaptyvus gate su histereze** — triukšmo grindys (rolling 25-tas percentilis, 5 s, mokomasi tik budint) +
  `VOX_OPEN_MARGIN` (START) / `VOX_CLOSE_MARGIN` (SUSTAIN). 2 s kalibracija prieš leidžiant įrašyti. Pre-roll 0.8 s.
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
- `bin/rec-toggle.sh` (`make rec-toggle`, galima susieti su klavišu): rankinis start/stop → `rec_*.wav`.

### ASR + kalbėtojų atpažinimas (`.venv`)
- **VAD vartai** (`diktatura.audio.prefilter`, Silero per `faster_whisper.vad`): ASR moduliai pirmiausia randa kalbą
  kiekviename kanale ir **tik tada** krauna modelį. Kanalas be kalbos (< `VAD_MIN_SPEECH_SEC`) praleidžiamas; jei
  visas įrašas be kalbos — tuščias tekstas, modelis nekraunamas (`DELETE_EMPTY` jį ištrina). `VAD_TRIM=1` — Whisper'iui
  tik kalbos atkarpos su laikų perskaičiavimu (`remap`); numatytai 0 (matavimas — PLAN Etapas 2).
- ASR moduliai turi `run(argv, get_model)` — modelį paduoda `diktatura.asr.models.load` (atskiras procesas) arba
  nuolatinis serveris (`diktatura.asr.server`, žr. žemiau).
- `diktatura.asr.transcribe_named` (pagrindinis): `loudnorm` kiekvienam kanalui → VAD → Whisper(Ąžuolas) L ir R →
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
  Meniu: „⚙ Nustatymai" (viršuje), „🎓 Apmokymai paruošti (N)" (kai yra), „📄 Rodyti nuskaitytą tekstą", būsena,
  režimas, įrašų aplankas. **Vidurinis klik → Nustatymai.** Ubuntu AppIndicator paspaudus visada atidaro meniu —
  langas tiesiai neatsidaro, todėl Nustatymai meniu viršuje. Testams `Tray(indicator=…, opener=…)` (be D-Bus ikonos).
- `diktatura.ui.app`: **vienas langas** „Diktatūra" (Gtk.Application, vienas egzempliorius per D-Bus — antras
  paleidimas `--page <skiltis>` tik perjungia skiltį), skiltys `Gtk.Stack` + „◀ Atgal". `--shot <png>` — nuotrauka.
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
  - `ui.training_page` (🎓 Apmokymai): pending sąrašas + kontekstas (`store.occurrences_many`), ▶ grojimas
    (`paplay`; testams `DIKTATURA_PLAYER`), vardas su autocomplete → `store.assign`; „🙋 Tai aš" → `store.assign_owner`;
    „Ne žmogus" → `store.discard`; registruoti balsai: tavo balsas (pamiršti) + kolegos: pervadinti/sujungti/pamiršti.
    Po pakeitimų perpiešia Teksto skiltį.
  - `ui.settings_page` (⚙ Nustatymai): laukai generuojami iš `config.SCHEMA` (naujas raktas schemoje atsiranda
    automatiškai), įrašymo režimas per `services`, validacija prie laukų, „Atkurti numatytus".
- `ui.gtk`: GTK versijos ir bendras CSS vienoje vietoje. UI moduliuose — jokio numpy/faster-whisper.

### Valdymas / konfigūracija
- `Makefile` — visos komandos (`make help`). Keliai jame išvedami taip pat kaip `paths.py` (XDG + `DIKTATURA_*`).
- `make doctor` (`diktatura.doctor`, tik skaito): įrankiai, garsas, `.venv`, GTK/AppIndicator, modeliai (+SHA-256),
  nustatymai, servisų failai vs šablonai, režimas/ikona/naktinis, hooks, RAM/diskas → ✓/⚠/✗ + patarimas.
- `diktatura.services` (stdlib): systemd --user vienoje vietoje (režimas vox/slack/off, timer, unit'ų būklė).
  Testams `DIKTATURA_SYSTEMCTL` / `DIKTATURA_SYSTEMD_DIR`.
- **Debug:** `diktatura.debug` + bash `dbg` (`bin/common.sh`) → `~/.local/state/diktatura/debug.log` (> 5 MB → `.1`).
  Įjungiama nustatymu `DEBUG` (`make debug-on`) arba `DIKTATURA_DEBUG=1|0` (env nugali). `make dlogs` — gyvai.
- **Nustatymai** — `diktatura/config.py`: `SCHEMA` (tipas, ribos, LT aprašas kiekvienam raktui), `load()` (netinkama
  reikšmė → numatytoji, sistema nelūžta), `save()` (validacija + atominis rašymas), `reset()`. CLI:
  `python3 -m diktatura.config show|get|set|reset|path` (`make config`, `make set S="K=V"`).
  **Taikoma be restarto:** VOX perskaito kas ~5 s, Slack daemon — kiekvieną ciklą, teksto langas — kiekvieną atnaujinimą.
  Bash skriptai config `source`'ina (`load_config` iš `common.sh`): pirma numatytieji, tada vartotojo.
- systemd šablonai `systemd/*.in` su `@REPO@` → `make install-units` įrašo į `~/.config/systemd/user/`
  (repo galima klonuoti bet kur).
- Naktinis `diktatura-nightly.timer` (01:30) → `bin/transcribe-pending.sh` (visi įrašai be teksto; praleidžia
  rašomą failą ir `.skip`).
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
- **`pending/.next` po `flock`:** nežinomus balsus vienu metu gali kurti transkripcija ir `make speakers-relabel`.
- **Testų LT fixture'ai — vienas kalbėtojas** (Common Voice klipai) — „skirtingų žmonių" testams netinka.
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
| `make test` | greiti: nustatymai, VOX (sintetinis capture), Slack (netikras `pactl`/`ffmpeg`), eilė (netikras ASR), de-dup, kalbėtojai (griežtumas, tavo balsas, pataisymai, modelio perėjimas), doctor, UI, privatumas | ~1.5 min |
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
