# Diktatūra — tobulinimo planas (v2)

> **Pavadinimų taisyklė:** `diktatura` — CLI, failai, servisai, env (`DIKTATURA_*`), kodas.
> „Diktatūra" — žmogui skaitomas tekstas (README, UI). Senasis vidinis pavadinimas pašalintas visur ir įtrauktas
> į `.private-terms` — privatumo sargas jo nebeįleidžia į repo.
> **Skip:** ❌ santrauka/ollama, ❌ globalus diktavimas.
> **Commit + push:** tarpinių commit'ų nedarom — viskas vienu commit'u kartu su paskutiniu pakeitimu;
> push tik savininkui pasakius „done" ir kai visi testai žali (ne tarpiniais etapais).
> **Klausimai savininkui** pažymėti ❓ — atsakyk po klausimu `→ …` arba pasakyk.

Statusai: ⬜ nepradėta · 🟡 vyksta · ✅ padaryta

---

## Ką radau tikrindamas (2026-10-08)

1. 🔴 **`.gitignore` buvo sugedęs** (mano klaida): komentarai buvo toje pačioje eilutėje kaip šablonai
   (`recordings/   # …`), o git'e `#` komentaras tik eilutės pradžioje → `recordings/`, `speakers/`, `models/`,
   `STATUS.md`, `CLAUDE.md` **nebuvo ignoruojami**. Pirmas push'as švarus tik todėl, kad failai pridėti
   pavieniui (ne `git add -A`). ✅ Sutaisyta ir apsaugota testu (žr. Etapas P).
2. 🟠 **Public commit'o metaduomenyse matosi darbo email** (`…@<darbovietė>.lt`) — GitHub'e viešas. Žr. ❓Q3.
3. 🟠 **Git istorijoje lieka senasis vidinis pavadinimas** (pirmo commit'o failų varduose), net ir po pervadinimo. Žr. ❓Q3.
4. ℹ️ **Ubuntu status bar (AppIndicator) apribojimas:** paspaudus ikoną VISADA atsidaro meniu — langas tiesiai
   neatsidaro. Sprendimas: kairys klik → meniu, kurio viršuje „⚙ Nustatymai" (ir „🎓 Apmokymai paruošti", kai yra
   pending); **vidurinis klik → iškart Nustatymai**.

## Sprendimai (iš tavo atsakymų)

- Debug: `make doctor` + `DIKTATURA_DEBUG=1` + atskiras debug logas — ✅ tinka.
- VAD: min kalbos 0.8–1.0 s, paddingas 0.2 s — numatytieji, keičiami Nustatymuose.
- Pulsavimas: **jokių naujų spalvų** — ikona pulsuoja (bet kurios esamos spalvos ⚪/🔴/🟡), kol yra pending.
  Meniu rodo „Apmokymai paruošti"; apmokymas vyksta UI (perklausa + vardas), be failų naršyklės.
- Apmokymų vaizdas: **pilna navigacija + kontekstas ir paaiškinimai lietuviškai**.
- Nustatymai: „Atkurti numatytus" mygtukas; numatytieji = dabartiniai nustatymai.
- Pagrindinis aplankas → `~/diktatura`; config failas nebe repo šaknyje.
- Eiliškumas: **pirma pilnas pervadinimas ir senojo pavadinimo pašalinimas**.

## Peržiūra: ką pakeičiau plane ir kodėl

1. **Privatumo sargas padarytas iš karto** (Etapas P ✅) — repo public, o radinys #1 parodė, kad vien `.gitignore` nepakanka.
2. **Testų karkasas statomas iškart po pervadinimo** (Etapas Q0), ne pabaigoje — kad kiekvienas etapas būtų patikrintas.
   Pats testų aprašas — šio dokumento gale (kaip prašei).
3. **Nustatymai perkelti prieš Apmokymus ir VAD** — VAD slenksčiai ir tray paspaudimas priklauso nuo jų.
4. **Vienas pagrindinis langas su navigacija** (📄 Tekstas · 🎓 Apmokymai · ⚙ Nustatymai) vietoj trijų langų.
5. **Nustatymai taikomi be restarto** — daemon'ai periodiškai perskaito config (VOX kas ~5 s, Slack kiekvieną ciklą,
   teksto langas kiekvieną atnaujinimą) → „Taikyti/restart" mygtuko nereikia. (Vietoj SIGHUP — paprasčiau, veikia ir be signalų.)
6. **Retroaktyvus pervadinimas:** priskyrus vardą balsui, esamuose tekstuose `Kolega?nezN` → vardas.

## Vykdymo tvarka

**P ✅ → R ✅ → Q0 ✅ → 1 ✅ → 4 ✅ → 3 ✅ → 2 ✅ → 5 ✅ → 6 ✅ → D ✅ → 7 ✅ → 8 ✅ → 9 ✅ → 10 ✅**

---

## Etapas P — Privatumo sargas git'e ✅

Gynybos sluoksniai (kiekvienas veikia net jei kitas sugenda):

1. **Duomenys už repo ribų** (XDG, Etapas R ✅) — fiziškai neįmanoma įstumti.
2. **`.gitignore`** — sutaisytas; testas tikrina 14 privačių kelių su `git check-ignore`.
3. **Git hooks** (`.githooks/`, įjungiama `make hooks`, veikia net su `git add -f`):
   - `pre-commit` — blokuoja: garsą (`*.wav/mp3/m4a/flac/ogg/opus/webm`), transkripcijas (`*.named.txt`,
     `*.dialog.txt`, `recordings/`), balsų biometriją (`speakers/`, `enroll.json`, `*.diar/clusters/reclust.json`),
     modelius (`models/`, `*.onnx/bin/pt/safetensors`), logus, lokalų config, `STATUS.md`/`CLAUDE.md`, `.private-terms`,
     failus > 2 MB, **asmeninius terminus** pridedamame tekste ir failų varduose.
   - `pre-push` — iš naujo tikrina **kiekvieną** stumiamą commit'ą (pagauna ir `--no-verify`) + autoriaus/committer email.
   - Asmeniniai terminai (kolegų vardai, darbovietė, email) — **lokaliame** `.private-terms` (niekada į git).
     Tikrinama žodžio pradžioje, `_ . / -` normalizuojami (pagauna `vardas_pastabos.md`, bet ne „paleidimas").
4. **Testai:** `make test-privacy` — **32 ✓ / 0 ✗** (įsk. neigiamą audito testą, regresiją dėl `.gitignore` ir
   darbinio medžio auditą `audit-worktree`, 2026-10-08).

`make install` kartu įjungia `make hooks` (Etapas R ✅). Liko: `make doctor` patikra (Etapas 1).

## Etapas R — Pilnas pervadinimas + švari struktūra ✅ (2026-10-08)

Tikslas: senasis vidinis pavadinimas pašalintas visur (failuose, keliuose, servisuose, env, UI); kodas tvarkingas kitiems devams.

Struktūra (įgyvendinta):

```
~/diktatura/                        repo (tik kodas)
├── diktatura/                      python paketas
│   ├── paths.py                    visi keliai (XDG + DIKTATURA_* env perrašymai); tik stdlib
│   ├── config.py                   schema, numatytieji + vartotojo config, validacija, reset, CLI
│   ├── asr/                        transcribe (mono), transcribe_named (stereo + vardai + de-dup)
│   ├── speakers/                   speakerlib, enroll, diarize, recluster, name_clusters
│   ├── audio/                      vox (VoxGate — gryna logika + I/O), prefilter (VAD, Etapas 2)
│   └── ui/                         tray, app (📄 Tekstas · 🎓 Apmokymai · ⚙ Nustatymai)
├── bin/                            shell įėjimai: common.sh, autorecord, transcribe-file, transcribe-pending, rec-toggle
├── tools/                          convert_azuolas (laikinas torch venv), fetch_models (SHA-256), bench
├── systemd/                        diktatura-*.service.in / .timer.in (@REPO@ → `make install-units`)
├── config/diktatura.conf.default   versijuojami numatytieji
├── icons/diktatura-*.png · docs/ · tests/ · .githooks/
└── Makefile · requirements.txt · README.md · LICENSE
```

Kas padaryta:

1. Atsarginė kopija → seni servisai sustabdyti ir pašalinti → `mv` į `~/diktatura` → duomenys perkelti į XDG
   (`~/.config/diktatura`, `~/.local/share/diktatura/{recordings,speakers,models}`, `~/.local/state/diktatura`).
2. Kodas → paketas (`python -m diktatura.…`), keliai tik per `paths.py` / `bin/common.sh`; env `DIKTATURA_*`
   (`DIKTATURA_DATA/CONFIG_DIR/STATE/RUN`, ~~`DIKTATURA_REC`, `DIKTATURA_SHOT`~~ → Etape 4 `DIKTATURA_DATA` ir `--shot`, `DIKTATURA_MIC/MONITOR`, `DIKTATURA_MATCH/POLL/PACTL`,
   `DIKTATURA_MODEL/THREADS`, `DIKTATURA_ASR_CMD`); tray id ir ikonos → `diktatura`.
3. Vienas `.venv` (Python 3.10, be torch, ~630 MB); seni venv'ai ištrinti (~1.5 GB). Ąžuolo konversijai torch
   diegiamas į laikiną venv, kuris po konversijos ištrinamas.
4. Servisai `diktatura-*` iš šablonų; VOX ir Slack režimai tarpusavyje `Conflicts=`; `make install` = hooks + setup +
   models + servisai. Nustatymai: `make config` / `make set S="K=V"` (validuojama per `diktatura.config`).
5. Testams paruošta: `VoxGate` — gryna klasė; `config` — grynos funkcijos; visi keliai perrašomi env.
6. Patikra: visi moduliai importuojasi (`.venv` ir sistemos python3); E2E transkripcija izoliuotame `DIKTATURA_DATA`
   (Ąžuolas + vardo atpažinimas) ✓; servisai aktyvūs ✓; senasis pavadinimas repo nerandamas (sargas jį blokuoja) ✓.

## Etapas Q0 — Testų karkasas ✅ (2026-10-08)

- `pytest` (`.venv`), `pytest.ini` su žymėmis `full` / `e2e` / `ui`. Komandos: `make test` (greiti, ~40 s),
  `make test-full` (tikras Ąžuolas + LT garsas), `make test-e2e` (virtualus garsas), `make test-privacy`, `make fixtures`.
- **Saugiklis:** `tests/conftest.py` dar prieš importuojant `diktatura.*` nukreipia visus `DIKTATURA_*` į laikiną katalogą,
  o PATH priekyje — netikras `notify-send`: joks testas neliečia tikrų įrašų/balsų/nustatymų ir nerodo pranešimų.
  Fixture'ai: `env` (izoliuota aplinka), `fake_audio` (netikri `pactl`/`ffmpeg`), `fake_asr`, `fake_systemd`, `real_models`
  (tikri modeliai per symlink + **tikras transkripcijos užraktas** — du Ąžuolai vienu metu = OOM).
- Refaktoringas testuojamumui: `diktatura/sessions.py` (failų vardai, datos, eilutės), `diktatura/asr/dialog.py` (de-dup),
  `diktatura/speakers/store.py` (balsų saugykla be numpy), `speakerlib.label_segments` (vardų priskyrimas — gryna funkcija),
  VOX `DIKTATURA_CAPTURE_CMD` (sintetinis capture), keliai imami kvietimo metu (ne importo).
- Fixture'ai: sintetinis garsas (`tests/helpers/audio.py`, `pcm_gen.py`); LT kalba — **Mozilla Common Voice 22.0 lt (CC0)**,
  4 klipai, `make fixtures` parsisiunčia tik baitų intervalus (~220 KB) ir tikrina SHA-256 (`tests/fixtures/cv_lt.tsv`).
- Rezultatai: `make test` 89 ✓; `make test-full` 2 ✓ (**Ąžuolo WER 2.4 %**); `make test-e2e` 5 ✓; `make test-privacy` 30 ✓.
- **Testai rado ir sutaisyta:** (1) VOX „min. įrašo trukmė" niekada nesuveikdavo — trukmė skaičiuota su 5 s tylos uodega ir
  pre-roll, tad kosulys = „6 s įrašas"; dabar tikrinama tik garso trukmė. (2) VOX po SIGTERM nedarydavo `wav.close()`
  (`os._exit`) — sugadinta antraštė; dabar švarus uždarymas, o capture nutrūkus — kodas 3 (systemd perkrauna; anksčiau 0 →
  neperkraudavo). (3) Slack `MAX_REC_SEC`: pakibęs srautas iškart pradėdavo naują įrašą (begalė failų); dabar laukia, kol
  srautas dings. (4) tuščias mono tekstas palikdavo `.srt`. (5) Privatumo sargas pagavo kolegų vardus mano testuose —
  pakeista išgalvotais; auditas dabar tikrina ir darbinį medį (`audit-worktree`, tarsi `git add -A`).

## Etapas 1 — Debug + `make doctor` ✅ (2026-10-08)

- `diktatura/debug.py` + bash `dbg` (`bin/common.sh`): `DIKTATURA_DEBUG=1|0` arba nustatymas `DEBUG` (`make debug-on/off`,
  `make dlogs`) → `~/.local/state/diktatura/debug.log` (> 5 MB → `.1`). Rašo: capture komandą ir įrenginius, VOX lygius
  kas 1 s + atsidarymo/uždarymo sprendimus, nustatymų pasikeitimus, Slack srautų pasikeitimus, kiekvieno failo kelią per
  pipeline (laukta eilėje, ASR trukmė, archyvas), modelio krovimą, RTF, kalbėtojų panašumą.
- `make doctor` (`diktatura/doctor.py`, tik skaito): įrankiai, garso įrenginiai, `.venv` paketai, GTK/AppIndicator, GNOME
  plėtinys, modeliai (+SHA-256), nustatymų validumas, servisų failai vs šablonai, režimas/ikona/naktinis, hooks,
  RAM/diskas, pakibęs būsenos failas, ar įjungtas debug. ✓/⚠/✗ + patarimas; kodas 1 jei yra ✗. Tikroje sistemoje: 27 ✓.
- `diktatura/services.py` — systemd valdymas vienoje vietoje (doctor, ikona, Nustatymai): režimas vox/slack/off, timer.

## Etapas 4 — Pagrindinis langas + Nustatymai ✅ (2026-10-08)

- `diktatura/ui/app.py` — vienas langas „Diktatūra" (Gtk.Application, **vienas egzempliorius** per D-Bus): 📄 Tekstas ·
  🎓 Apmokymai · ⚙ Nustatymai + „◀ Atgal" (istorija). `--page <skiltis>` antru paleidimu tik perjungia skiltį;
  `--shot <png>` — nuotrauka (README). `make text` / `make settings` / `make training`.
- `ui/text_page.py` — teksto langas perrašytas su modeliu (sesija → eilutės): papildymas → tik naujos eilutės, pusiau
  įrašyta eilutė laukia; failas perrašytas (pvz. pervadintas kalbėtojas) → perpiešiama; eilutės pradžioje žymė
  (`line_at_iter` — Etapo 6 grojimui/žymėms; išlieka redaguojant).
- `ui/settings_page.py` — generuojama iš `config.SCHEMA` (grupės, tipai, ribos, LT paaiškinimai, `choice_labels`):
  įrašymo režimas (VOX / Slack / išjungta → `services`), „Išsaugoti" (klaidos prie lauko, failas nekeičiamas),
  „Atkurti numatytus" (su patvirtinimu; nuo Etapo 9 — apačioje, toli nuo „Išsaugoti"), `MODE=deferred` automatiškai
  įjungia naktinį timer. Pelės ratukas virš lauko slenka puslapį (ne reikšmę). Taikymas be restarto — kaip ir anksčiau (daemon'ai perskaito patys).
- Tray: meniu viršuje „⚙ Nustatymai", „🎓 Apmokymai paruošti (N)" (kai yra), „📄 Rodyti nuskaitytą tekstą";
  **vidurinis klik → Nustatymai** (`set_secondary_activate_target`).
- Testai (broadway, langai tavo ekrane nerodomi): `tests/ui/test_main_window.py` — I1–I4, I6, CLI (vienas egzempliorius).

## Etapas 3 — Apmokymai (balsų registracija UI) ✅ (2026-10-08)

- `ui/training_page.py`: paaiškinimas LT; nežinomų balsų sąrašas (kada/kurioje sesijoje girdėtas, kiek kartų ir
  sesijų); kontekstas — šio balso eilutės iš transkripcijų; ▶ Groti / ⏹ Stabdyti (`paplay`); vardas su automatiniu
  užbaigimu (esami vardai); ✔ Įrašyti (Enter) → registracija + pending pašalinamas + **visose transkripcijose
  `Kolega?nezN` → vardas** + automatiškai kitas; ⏭ Praleisti; 🗑 „Ne žmogus / triukšmas" (pavyzdys trinamas,
  panašus garsas nebesiūlomas — `ignored.json`); ◀ ▶ navigacija; „📄 Grįžti į tekstą".
- „Registruoti balsai": pervadinti / **sujungti** (pvz. „Ruta" → „Rūta" — taip sutvarkomas ir STATUS minėtas
  dubliuotas vardas) / pamiršti. Tekstuose vardas pakeičiamas visur.
- Pulsavimas: kol `pending/` ne tuščias — ikona kaitalioja pilną/blankią tos pačios spalvos versiją (~1 s ciklas;
  `icons/*-dim.png`, `tools/make_dim_icons.py`); baigus — sustoja. Meniu „🎓 Apmokymai paruošti (N)".
- Duomenų sluoksnis — `diktatura/speakers/store.py` (Q0), UI dirba sistemos python3 be numpy.
- **Pauzė perklausai** (2026-10-09, savininko prašymu): kol groja perklausa (Apmokymuose ar Teksto „▶ Groti nuo čia"),
  VOX neįrašinėja (`diktatura/pause.py`) — kitaip perklausa per kolonėles būtų įrašyta kaip naujas pokalbis, o tas
  pats balsas vėl atsidurtų tarp nežinomų. Testai: `tests/test_pause.py`, UI testai.
- Testai: `tests/ui/test_training.py` (I5, G4/G5 per UI, grojimas su netikru grotuvu), `tests/test_speakers.py`.

## Etapas 2 — VAD pre-filtras ✅ (2026-10-08)

- `diktatura/audio/prefilter.py` — Silero VAD per `faster_whisper.vad` (modelis ateina su faster-whisper, nieko
  nesiunčiama). ASR moduliai pirmiausia išskiria kanalus ir paleidžia VAD, **tik tada** (jei reikia) krauna modelį.
- **Vartai:** kanale kalbos < `VAD_MIN_SPEECH_SEC` (0.8 s) → kanalas praleidžiamas; jei abu (arba mono) — tekstas
  tuščias, **Ąžuolas nekraunamas**, o `transcribe-file.sh` tuščią įrašą tvarko pagal `DELETE_EMPTY` (trina).
  Tylus / be kalbos sistemos (R) kanalas diktuojant — netranskribuojamas.
- **Trim + remap** įgyvendinta (`VAD_TRIM`, `VAD_PAD_SEC` 0.2 s): Whisper gauna tik kalbos atkarpas, segmentų laikai
  perskaičiuojami į originalą (H4 testas ±0.3 s). **Numatytai išjungta** — žr. matavimą.
- Nustatymai Nustatymų lange (grupė „VAD"): `VAD_FILTER`, `VAD_MIN_SPEECH_SEC`, `VAD_PAD_SEC`, `VAD_TRIM`.
- **Matavimas (tikri įrašai, Ąžuolas, 4 gijos; `tools/vad_bench.sh`):**

  | Įrašas | be VAD | su VAD + trim | Pastaba |
  |---|---|---|---|
  | skambučio ištrauka 120 s (L 103 s kalbos, R 23 s) | 214 s (RTF 1.78) | 209 s (RTF 1.75) | −2 %; tekste ~10 žodžių kitaip |
  | VOX diktavimas 25 s (R tylus) | 22.8 s | 21.9 s | −4 % (kartojant: 24 s vs 28 s — triukšmo ribose) |

  **Išvada:** tikslas „≥ 2x ilgiems skambučiams" per VAD **nepasiekiamas** — prielaida buvo klaidinga: faster-whisper jau
  naudoja vidinį VAD (`vad_filter=True`), tad tyla ir anksčiau nebuvo transkribuojama. Apkarpymas keičia Whisper
  kontekstą (keli žodžiai kitaip, kokybės kryptis neaiški) → `VAD_TRIM=0`. Tikra VAD nauda — **vartai**: įrašai be kalbos
  (VOX blyksniai, triukšmas, muzika) nebekrauna ~3 GB modelio. Didesnio greičio šaltiniai — Etapas 5 (serveris) ir
  idėja: mikrofono kanalo nutekėjimo (kolegų balsas L kanale, ~100 s iš 120 s ištraukoje) neatpažinti iš naujo.
- Testai: `tests/test_prefilter.py` (H1–H6 + kelias per `transcribe-file.sh`), `tests/full/` (Ąžuolas per VAD).

## Etapas D — Dokumentacija + push ✅ (2026-10-09)

- ✅ `CONTRIBUTING.md` (aplinka, `make hooks`, testai, struktūra, privatumas, stilius); `docs/ARCHITECTURE.md` atnaujinta
  kiekvienam etapui; README — naujos funkcijos ir **naujos nuotraukos** (`tools/screenshots.sh` — išgalvoti
  `tools/demo_data.py` duomenys, broadway, tikri duomenys neliečiami): Tekstas, Apmokymai, Nustatymai.
- ✅ Visi testai žali (žr. žemiau „Kaip paleisti"); `make doctor` tikroje sistemoje žalias.
- ⬜ Rankinis GUI checklist — dalis tik savininkui (tikras diktavimas, ikonos meniu, perkrovimas) — žr. žemiau.
- ✅ **Push** — paprastas (be istorijos perrašymo), savininko sprendimu (Q3: „darbo el. paštas nesvarbu"). Pirmame
  commit'e lieka darbo email ir senasis pavadinimas failų varduose — sąmoningai paliekama. Visas darbas — vienas commit'as.
- (Neprivaloma) GitHub Action su `privacy-scan.sh audit` — nepridėta: serveryje nėra `.private-terms`, o kelių/dydžio
  patikras jau daro pre-push. Galima pridėti vėliau.
- Vykdymo tvarka pakeista: D užbaigiamas paskutinis (po 5 ir 6), kad nuotraukos ir dokumentacija atitiktų galutinį UI.

## Etapas 5 — Optimizacijos ✅ (2026-10-08)

- **Nuolat įkrautas modelis** (`diktatura/asr/server.py`, `client.py`, `diktatura-asr.service`; nustatymai `ASR_SERVER`,
  `ASR_SERVER_IDLE_MIN`; `make asr-server-on/off`): modelis laikomas atmintyje, po N min be darbo iškraunamas;
  `transcribe-file.sh` siunčia darbą per Unix lizdą (eilė/flock išlieka), serverio nėra → atskiras procesas kaip anksčiau.
  ASR moduliai pertvarkyti į `run(argv, get_model)`. **Numatytai išjungta** — kaina ~3 GB RAM, kol yra darbo.
  Matavimas (6.7 s LT klipas, šiltas disko cache): 1-as darbas 15.5 s → 2-as 13.1 s (−2.4 s). Šaltas modelio krovimas
  (po perkrovimo / išstumtas iš cache) — iki ~30 s, tad nauda didžiausia pirmam diktavimui po pertraukos.
- **`BatchedInferencePipeline` matavimas** (`tools/batched_bench.py`, Ąžuolas, 4 gijos, CPU):

  | Garsas | įprastas | batched b=4 | batched b=8 | tekstų skirtumas |
  |---|---|---|---|---|
  | švari LT kalba (Common Voice, 31 s) | 29.7 s | 28.5 s (x1.04) | 29.1 s (x1.02) | 0 % |
  | skambutis, kolegų kanalas (120 s, ~23 s kalbos) | 18.3 s | 19.6 s (x0.94) | 17.8 s (x1.03) | 0 % |
  | skambutis, tavo mikrofonas (120 s, ~100 s „kalbos" su nutekėjimu) | 138 s | 108 s (x1.28) | 118 s (x1.17) | **33 %** (319 vs 249 žodž.) |

  **Išvada:** nenaudojama. Švarioje kalboje naudos nėra; triukšmingame kanale +17–28 % greičio, bet tekstas stipriai
  kitoks (batched neperduoda ankstesnio konteksto, todėl pagauna daugiau nutekėjusios kolegų kalbos). Be etalono
  kokybės nesprendžiam.

## Etapas 6 — Teksto funkcijos ✅ (2026-10-08)

- **Grojimas sinchr. su tekstu:** dešinys klik ant eilutės → „▶ Groti nuo čia" (ffplay, be lango, stereo sumaišytas į
  abi ausis, pradeda 0.5 s prieš eilutę); grojama eilutė paryškinama ir sekama; „⏹ Stabdyti grojimą".
- **Filtrai:** kalbėtojas (Visi / vardai), laikotarpis (pask. N d. — nustatymas / šiandien / vakar / 7 / 30 d. /
  visas archyvas — archyvas užkraunamas pagal poreikį), „Tik žymėtos".
- **Žymės / užduotys:** ⭐ svarbu, ☐ užduotis → ☑ atlikta, „Pašalinti žymę" (`diktatura/annotations.py`,
  `<duomenys>/annotations.json`; žymė išlieka pervadinus kalbėtoją).
- **Eksportas:** „💾 Eksportuoti…" — matomas (filtruotas) tekstas į `.txt` arba `.md` (su žymėmis).
- **Statistika:** „📊 Statistika" — kas kiek kalbėjo matomose sesijose (eilutės, žodžiai, ≈ laikas, dalis %).
  „↺ Nunulinti" (2026-10-09, savininko prašymu) — skaičiuoti tik nuo dabar (tekstai netrinami; laikas
  `<duomenys>/stats_reset.json`, `diktatura/stats.py`), „Skaičiuoti viską" — atšaukia.
- **Regex paieška:** „Regex" varnelė (be didžiųjų/mažųjų skirtumo; klaidinga išraiška — pranešimas, ne lūžis).
- **Nežinomo balso vardas iš teksto:** dešinys klik ant `Kolega?nezN` → „🎓 Priskirti vardą…" → Apmokymai su tuo balsu.
- Testai: `tests/ui/test_text_features.py` (16).

---

## Etapas 7 — Griežti vardai + tikslesnis balso modelis ✅ (2026-10-09)

Savininko pastebėjimas: prisijungus prie skambučio telefonu, jo paties eilutė (dešiniame kanale) gavo kolegos vardą;
reikia griežčiau ir tiksliau.
- **Priežastys:** (1) vardas rašytas, jei panašumas ≥ 0.5, net kai antras kandidatas beveik toks pat; (2) tavo balso
  R kanale nebuvo su kuo palyginti; (3) silpnas modelis — matavimas parodė, kad seno modelio vardai tekstuose beveik
  atsitiktiniai.
- **Griežtumas:** `speakerlib.decide` — vardas tik jei ≥ `SPEAKER_THRESHOLD` IR bent `SPEAKER_MARGIN` aukščiau už antrą
  kandidatą (taip pat ir už tave); kitaip `Kolega?`. Nustatymai → „Kalbėtojai".
- **Tavo balsas R kanale:** `speakers/owner.json`; atpažintas → `Tu`. Mokomas iš pataisymų: Teksto „✎ Kas kalbėjo?"
  (`speakers.teach` — eilutės garsas, R kanalas) arba Apmokymų „🙋 Tai aš".
- **Modelis:** 3D-Speaker CAM++ zh-en „advanced" (EER tavo įrašuose ~0–1 % vs buvusio ~13 %; matavimas —
  ARCHITECTURE §3). Žymė `speakers/model.json`; `make speakers-migrate` archyvuoja seno modelio balsus,
  `make speakers-relabel` perskaičiuoja paskutinių dienų tekstų kalbėtojus (nauji balsai → Apmokymai). `make doctor`
  rodo „Balsai".
- Testai: `tests/test_speakers.py` (G6–G8), `tests/test_teach.py` (G9), `tests/test_voice_model.py` (G10),
  UI — `tests/ui/test_training.py`, `tests/ui/test_text_features.py`.
- Pastebėta matuojant: ~1/5 „Tu" eilučių pokalbiuose iš tikro yra kolegų balsas — priežastis rasta Etape 8
  (ausinių lizdo persiklojimas), šalinama prieš transkripciją.

---

## Etapas 8 — Aidas tavo kanale (kolegų garsas mikrofone) ✅ (2026-10-09)

Savininkas: „nemanau, kad ausinių garsas pereina į mikrofoną — čia draiverių klausimas".
- **Matavimas** (WAV + mp3 įrašai, kontroliuotas testas su VOX pauze): L kanale — tiesinė R kopija −20…−28 dB,
  koherencija iki 0.9, plokščias dažnių atsakas, proporcinga garsumui → elektrinis persiklojimas kombinuotame ausinių
  lizde (Realtek ALC285). ALSA/PulseAudio loopback'o nėra — tvarkyklės keitimas nepadėtų. Be to rasta: L ir R įraše
  pasislinkę ~0.5–1 s (ffmpeg dviejų pulse srautų startas).
- **Sprendimas:** `diktatura/audio/echo.py` — poslinkis ir pastovus kelias kiekvienam įrašui, kopija atimama prieš
  loudnorm (`transcribe_named.extract_me`); nustatymas `ECHO_CANCEL` (numatytai 1). Nuotėkio nėra — nieko nedaroma.
- **Rezultatas:** WAV įraše (radijas ausinėse) L lygis kolegoms kalbant −49.5 → −66 dB (triukšmo lygis), gaubtinių
  koreliacija su R 0.86 → 0.15; **Whisper L kanale: 22 segmentai (17 — aiškios radijo kopijos, 515 žodž.) → 0**
  (VAD kalbos neranda, modelis nekraunamas). Tavo kalba išlieka: vakarykščio pokalbio 5 min — tavo žodžių rasta 94 %
  prieš ir 94 % po. Sintetiniuose testuose likutis −38…−49 dB, tavo balsas nepakitęs (koreliacija > 0.995).
- **Riba:** vakar (koherencija tik 0.1–0.3 — kintantis, greičiausiai akustinis kelias) nuotėkis nuslopintas iki
  triukšmo lygio, bet keli trumpi kolegų frazių segmentai L dar atpažįstami (4 → 5 per 5 min). Bandyta: ilgesnis FIR
  (iki 512 ms) — jokio skirtumo; filtras kas 8–60 s — +1.4 dB, nepridėta. MP3 archyvas kanalų nemaišo (patikrinta).
  Kitas žingsnis, jei kartosis: liekamojo aido slopinimas (post-filtras) — su rizika tavo kalbai, matuoti.
- Trumpi įrašai (VOX gabalai skambučio metu, nuo ~6 s) irgi valomi (vienas blokas, griežtesnis slenkstis).
- Testai: `tests/test_echo.py` (L1–L5, L4b).

---

## Etapas 9 — Atstatymas: ištrinti įrašus ir tekstus, atkurti numatytus (su patvirtinimu) ✅ (2026-10-09)

Savininkas: „pratrinti visus įrašus ir tekstus ir pradėti iš naujo kaupti; RESET mygtukas su confirm; atkurti
numatytus — ne taip arti Išsaugoti ir su patvirtinimu".
- Nustatymų apačioje rėmelis „Atstatymas ir duomenys"; apatinėje juostoje liko tik „Išsaugoti".
- „Atkurti numatytus nustatymus…" — dialogas su pasikeisiančių nustatymų sąrašu (jei nieko — be dialogo).
- „Ištrinti įrašus ir tekstus…" — `diktatura/reset.py`; varnelės: įrašai ir tekstai (+ žymės, statistika, tekstų
  kopijos; pažymėta), laukiantys vardo balsai, vardų atpažinimas (registruoti balsai, tavo balsas, seni archyvai).
  Vardai pagal nutylėjimą NEtrinami. Vykstantys įrašymas ir transkripcija paliekami; eilėje laukę — praleidžiami.
- Abiejuose dialoguose numatytasis mygtukas „Atšaukti", trynimo mygtukas raudonas.
- Testai: `tests/test_reset.py` (M1–M6), `tests/test_transcribe_pipeline.py` (E8), `tests/ui/test_main_window.py`.
- Kartu (savininkui netyčia uždarius ikoną): meniu punktas „Išeiti iš ikonos" → „Išeiti" (uždaro tik ikoną);
  „Diktatūra" programų meniu ir doke (`make desktop`, `bin/diktatura-open.sh`: grąžina ikoną + atidaro langą).
  Testai: `tests/test_desktop.py` (N1–N3).

---

## Etapas 10 — Temos ir mažas ekranas ✅ (2026-10-09)

Savininkas: „dark tema + kelios temos skirtingiems poreikiams (regos negalia, ypač mažas ekranas); Apmokymuose
registruoti balsai apačioje vos matosi — vertikaliai siaura".
- **Temos** (`THEME`, Nustatymai → Išvaizda, `diktatura/ui/themes.py`): šviesi, tamsi, didelis kontrastas ir šriftas
  (HighContrast, ×1.4, fokuso rėmelis, nepritemdytas pagalbinis tekstas), kompaktiška (×0.85, be įžangų).
  Taikoma iškart išsaugojus; teksto lango kalbėtojų spalvos — pagal temą.
- **Apmokymai:** „Registruoti balsai" — atskiras skirtukas per visą aukštį; įžanga — sutraukiama „ℹ Kaip tai veikia?".
- **Mažas ekranas** (matuota): mažiausias langas 1127×733 → 667×319 (šviesi), 621×313 (kompaktiška), 849×319
  (kontrastas). Priemonės: juostos persikelia (`WrapBox`), skiltys slenkamos, nustatymų pavadinimai laužomi.
- Rasta pakeliui: PyGObject savo konteineris be Python nuorodos — amžinas ciklas naikinant (pataisyta, testas O7);
  `Gtk.FlowBox` atmestas (stulpeliai, spragos).
- Testai: `tests/ui/test_themes.py` (O1–O7), README nuotraukos (`theme-dark.png`, `theme-contrast.png`).

---

## ❓ Nauji klausimai (su mano rekomendacija)

- ❓ **Q1 — Kur laikyti duomenis po pervadinimo?**
  (a) *Rekomenduoju:* **už repo ribų** (Linux standartas XDG): nustatymai `~/.config/diktatura/`, įrašai/balsai/modeliai
  `~/.local/share/diktatura/`, logai `~/.local/state/diktatura/`. Repo lieka tik kodas → fiziškai neįmanoma įstumti
  įrašų; kitas žmogus klonuoja bet kur. Meniu „Atidaryti įrašų aplanką" ves ten.
  (b) Viskas `~/diktatura/` viduje (kaip dabar), saugo `.gitignore` + hooks.
  → a varijantas

- ❓ **Q2 — Kodo struktūra:** `plans/A` + `plans/F` → paketas `diktatura/` + vienas `.venv` (seni venv su torch
  ištrinami, ~2–3 GB). *Rekomenduoju* daryti kartu su pervadinimu (viena lūžio vieta, ne dvi). OK?
  → ok

- ❓ **Q3 — Public istorija ir tapatybė:**
  
  - Pirmame public commit'e: senasis pavadinimas failų varduose + autoriaus email `…@<darbovietė>.lt`.
  - *Rekomenduoju:* prieš kitą push — istoriją perrašyti į vieną švarų commit'ą (`force-push`; repo naujas,
    1 commit'as, klonų greičiausiai nėra) ir nustatyti **repo-lokalų GitHub noreply email**
    (`<ID>+SimonasJurksa@users.noreply.github.com`). Sargas jau dabar **blokuos** push'ą su darbo email.
  - LICENSE: `Copyright (c) 2026 Simonas Jurksa` — palikti vardą ar „Diktatūra contributors"?
    → simonas.jurksa@gmail.com el. paštas gali būti. Palik mano vardą ir pavardę
    → (2026-10-09) darbo el. paštas istorijoje nesvarbu — paprastas push, istorijos neperrašom.

- ❓ **Q4 — LT kalbos garsas testams** (ASR kokybės ir E2E patikrai):
  (a) *Rekomenduoju:* CC0 lietuviškas klipas iš Mozilla Common Voice, parsisiunčiamas `make fixtures` (repo neįtraukiamas).
  (b) Tavo įrašyta testinė frazė — lieka `tests/fixtures/private/` (niekada į git).
  → a

---

## 🧪 Kokybės užtikrinimas (QA) — testų planas

### Kaip paleisti

| Komanda             | Kas                                                           | Trukmė          |
| ------------------- | ------------------------------------------------------------- | --------------- |
| `make test`         | greiti testai be modelių (A–D, F, G, I, K, L, M, N)           | ~1.5 min ✅     |
| `make test-full`    | + ASR ir balso modelis su tikrais modeliais (E5–E8, H)        | ~1–5 min ✅     |
| `make test-e2e`     | virtualus garsas (PulseAudio null-sink), realūs daemon'ai (J) | ~2 min ✅       |
| `make test-privacy` | privatumo sargas (A)                                          | ✅ veikia, ~10 s |
| `make doctor`       | sistemos savitikra                                            | < 10 s ✅       |

Po **kiekvieno** pakeitimo: `make test`. Prieš push: `make test-full && make test-e2e && make test-privacy` + rankinis checklist.

### A. Privatumas / git ✅ — `tests/privacy_guard_test.sh` (per `tests/test_privacy.py`)

| #   | Atvejis                                                                             | Tikimasi     |
| --- | ----------------------------------------------------------------------------------- | ------------ |
| A1  | commit'inti `*.wav/*.mp3` (net `git add -f`)                                        | blokuojama   |
| A2  | `recordings/*`, `*.named.txt`, `*.dialog.txt`                                       | blokuojama   |
| A3  | `speakers/enroll.json`, `pending/*`, `*.diar.json`                                  | blokuojama   |
| A4  | modeliai (`*.onnx/bin`), failas > 2 MB                                              | blokuojama   |
| A5  | asmeninis terminas tekste / failo varde / `snake_case`; be didžiųjų/mažųjų skirtumo | blokuojama   |
| A6  | terminas žodžio viduryje („paleidimas")                                             | praleidžiama |
| A7  | `pre-push`: commit'as su `--no-verify` ir privačiu failu; privatus autoriaus email  | blokuojama   |
| A8  | auditas: privatus failas istorijoje aptinkamas; tracked HEAD švarus                 | ✗ / ✓        |
| A9  | `.gitignore` ignoruoja 14 privačių kelių; hooks įjungti                             | ✓            |
| A10 | (po R) senasis pavadinimas repo (terminas `.private-terms`) → `privacy-scan.sh audit` | ✓            |

### B. Konfigūracija / nustatymai ✅ — `tests/test_config.py`, B6: `tests/test_vox_daemon.py`

| #   | Atvejis                                                            | Tikimasi                           |
| --- | ------------------------------------------------------------------ | ---------------------------------- |
| B1  | numatytasis config parsinasi; kiekvienas raktas turi tipą ir ribas | ✓                                  |
| B2  | išsaugoti → perskaityti (roundtrip)                                | identiška                          |
| B3  | „Atkurti numatytus"                                                | failas = `diktatura.conf.default`  |
| B4  | neteisinga reikšmė (neigiamos sek., tekstas vietoj skaičiaus)      | atmesta, aiški klaida, senas lieka |
| B5  | config nėra                                                        | sukuriamas iš numatytųjų           |
| B6  | pakeistas config veikiant daemon'ui                                | per ≤ 5 s naudoja naują reikšmę    |

### C. VOX gate (sintetinis garsas, be mikrofono) ✅ — `tests/test_vox_gate.py`, `tests/test_vox_daemon.py`

| #   | Atvejis                                                          | Tikimasi                                    |
| --- | ---------------------------------------------------------------- | ------------------------------------------- |
| C1  | tyla                                                             | neatsidaro                                  |
| C2  | kalbos imitacija (moduliuotas triukšmas, −20 dB) po kalibracijos | atsidaro                                    |
| C3  | garsas pirmas 2 s (kalibracija)                                  | neatsidaro                                  |
| C4  | tyla ≥ / < tylos sekundžių                                       | uždaro / neuždaro                           |
| C5  | tylesnė kalba tarp išlaikymo ir atsidarymo slenksčių             | neuždaro (histerezė)                        |
| C6  | blyksnis < min trukmės                                           | failas ištrinamas                           |
| C7  | pre-roll                                                         | failo pradžioje 0.8 s prieš atsidarymą      |
| C8  | būsenos failas; SIGTERM                                          | sukuriamas/ištrinamas; po SIGTERM išvalytas |

### D. Slack detekcija (imituota `pactl` išvestis) ✅ — `tests/test_autorecord.py`

| #   | Atvejis                                       | Tikimasi                         |
| --- | --------------------------------------------- | -------------------------------- |
| D1  | `ringrtc`/`Slack` srautas atsiranda / dingsta | START / STOP po grace            |
| D2  | įrašas viršija max trukmę                     | priverstinis STOP                |
| D3  | režimas × auto (iškart / naktį / išjungta)    | transkribuojama / eilėje / nieko |

### E. Transkripcijos pipeline ✅ — `tests/test_transcribe_pipeline.py`, E5–E6: `tests/full/test_asr_full.py`

| #   | Atvejis                              | Tikimasi                                            |
| --- | ------------------------------------ | --------------------------------------------------- |
| E1  | dvi užklausos vienu metu             | vykdomos po vieną (flock)                           |
| E2  | tuščias tekstas, trinti=taip / ne    | wav+txt ištrinti / palikti                          |
| E3  | tekstas yra, mp3=taip (kbps=X) / ne  | mp3 su bitrate X / wav lieka                        |
| E4  | transkripcija nepavyko (nėra txt)    | wav paliekamas                                      |
| E5  | [full] LT kalbos fixture su Ąžuolu   | WER ≤ 25 %                                          |
| E6  | [full] stereo: L kalba, R kita kalba | yra „Tu" ir „Kolega" eilutės                        |
| E7  | `transcribe-pending`                 | praleidžia turinčius tekstą/`.skip`, apdoroja kitus |

### F. De-dup ✅ — `tests/test_dialog.py`

| #   | Atvejis                                   | Tikimasi   |
| --- | ----------------------------------------- | ---------- |
| F1  | „Tu" eilutė = kolegų tekstas tuo pat metu | pašalinama |
| F2  | tikra „Tu" eilutė                         | lieka      |
| F3  | trumpa reakcija (< 3 žodžiai)             | lieka      |

### G. Kalbėtojai / apmokymai ✅ — `tests/test_speakers.py`, `tests/test_teach.py`, `tests/ui/test_training.py`, `tests/ui/test_text_features.py`

| #   | Atvejis                                                   | Tikimasi                                                               |
| --- | --------------------------------------------------------- | ---------------------------------------------------------------------- |
| G1  | cosine / best_match virš / po slenksčio                   | vardas / nežinomas                                                     |
| G2  | enroll / pending saugykla (laikinas katalogas)            | roundtrip                                                              |
| G3  | tas pats nežinomas balsas keliuose segmentuose / failuose | vienas pending                                                         |
| G4  | priskirti vardą                                           | enroll papildytas, pending ištrintas, tekstuose `Kolega?nezN` → vardas |
| G5  | „Ne žmogus"                                               | pending ištrintas, enroll nepakitęs                                    |
| G6  | griežtumas: slenkstis + atsarga; tavo balsas R kanale     | per panašūs → `Kolega?` (be pending); tavo balsas → `Tu`               |
| G7  | „🙋 Tai aš" / vardas „Tu"; tavo balso pavyzdžių riba       | `owner.json` (≤ 40), tekstuose → `Tu`; „Tu" nėra kolegos vardas        |
| G8  | eilutės laikas ir pervadinimas („✎ Kas kalbėjo?")         | tik ta eilutė; pasikeitusi eilutė neperrašoma                          |
| G9  | mokymasis iš pataisymo (`speakers.teach`)                 | R kanalas jei yra kalbos, kitaip L; < 1.5 s kalbos → nemokoma (kodas 3) |

### H. VAD pre-filtras [full]

| #   | Atvejis                          | Tikimasi                         |
| --- | -------------------------------- | -------------------------------- |
| H1  | tyla                             | praleista, Ąžuolas nekrautas     |
| H2  | 1 kHz pypsėjimas                 | praleista                        |
| H3  | kalbos fixture                   | praleidžiama; trimmed trumpesnis |
| H4  | timestamp remap                  | žodžio laikas originale ±0.3 s   |
| H5  | tylus R kanalas                  | R netranskribuojamas             |
| H6  | pakeisti slenksčius Nustatymuose | elgsena pasikeičia               |

### I. UI (GTK per broadway, be tavo ekrano) ✅ — `tests/ui/`

| #   | Atvejis                        | Tikimasi                                           |
| --- | ------------------------------ | -------------------------------------------------- |
| I1  | pagrindinis langas (3 skiltys) | sukuriamas be klaidų                               |
| I2  | Tekstas: demo failai           | skyrikliai, spalvos, senesni nei N d. nutrinami |
| I3  | paieška ≥ 3 simb.; ◀ ▶         | paryškinta; ciklas                                 |
| I4  | Nustatymai                     | laukai = config; Išsaugoti rašo; Atkurti atstato   |
| I5  | Apmokymai: demo pending        | sąrašas, navigacija, Įrašyti kviečia registraciją  |
| I6  | tray būsenos + pulsavimas      | ⚪/🔴/🟡 logika; kadrai keičiasi kai pending        |

### J. E2E su virtualiu garsu (nekeičia tavo garso nustatymų) ✅ — `tests/e2e/test_e2e_audio.py`

| #   | Atvejis                                   | Tikimasi                                                       |
| --- | ----------------------------------------- | -------------------------------------------------------------- |
| J1  | fixture grojamas į virtualų šaltinį (VOX) | `vox_*.wav` sukurtas, uždarytas, transkribuotas                |
| J2  | tylos sekundės 5 → 2                      | failas užsidaro po ~2 s (nustatymas veikia)                    |
| J3  | režimas = naktį                           | po įrašo transkripcijos nėra; `transcribe-pending` → atsiranda |
| J4  | įrašymas + transkripcija vienu metu       | įrašas be dropout'ų (nulių < 1 %, RMS ne tyla)                 |

### K. Pervadinimas / sistema ✅ — K1: privatumo testas; K3: `tests/test_debug_doctor.py` + `make doctor`

| #   | Atvejis             | Tikimasi                                      |
| --- | ------------------- | --------------------------------------------- |
| K1  | senasis pavadinimas | auditas švarus (A10)                          |
| K2  | servisai            | `diktatura-*` aktyvūs, senų servisų nėra      |
| K3  | `make doctor`       | visi ✓                                        |

### L. Aido (kolegų garso mikrofone) šalinimas ✅ — `tests/test_echo.py`

| #   | Atvejis                                              | Tikimasi                                              |
| --- | ---------------------------------------------------- | ----------------------------------------------------- |
| L1  | nuotėkis −20 dB, FIR, poslinkis 0.98 / 0 / −0.3 s     | poslinkis ±1 ms, likutis < −35 dB, tavo balsas nepakitęs |
| L2  | nuotėkio nėra / sistemos garsas tylus                | nieko nedaroma                                        |
| L3  | taikymas blokais                                     | tas pats kaip visu                                    |
| L4  | tuščias / labai trumpas įrašas                       | nelūžta                                               |
| L4b | 8 s įrašas su nuotėkiu / be jo                       | valomas / neliečiamas                                 |
| L5  | transkripcijos L paruošimas su / be `ECHO_CANCEL`    | be — R kopija yra; su — nėra                          |

### M. Duomenų išvalymas ✅ — `tests/test_reset.py`, E8, UI — `tests/ui/test_main_window.py`

| #   | Atvejis                                              | Tikimasi                                                  |
| --- | ---------------------------------------------------- | --------------------------------------------------------- |
| M1  | planas su rašomu ir transkribuojamu įrašu            | jie (ir jų tekstai) palikti, kiekiai teisingi             |
| M2  | tik „įrašai ir tekstai"                              | recordings/, žymės, statistika, backup — ištrinta; vardai, nustatymai lieka |
| M3  | laukiantys balsai + vardų atpažinimas                | pending, enroll/owner/ignored, legacy — ištrinta; `.next`, assigned, model.json lieka |
| M4  | nežinoma kategorija / tušti katalogai                | klaida / nelūžta                                          |
| E8  | įrašas ištrintas laukiant eilėje                     | „PRALEISTA", kodas 0, ASR nekviečiamas                    |
| UI  | mygtukai toli nuo „Išsaugoti"; atšaukti / patvirtinti | Atšaukti — nieko; patvirtinus — atlikta; numatytai pažymėti tik įrašai |

### O. Temos ir mažas ekranas ✅ — `tests/ui/test_themes.py`

| #   | Atvejis                                             | Tikimasi                                                      |
| --- | --------------------------------------------------- | ------------------------------------------------------------- |
| O1  | kiekviena tema; grįžimas į šviesią                  | GTK tema / tamsus variantas / šrifto mastelis; atstatoma      |
| O2  | kalbėtojų spalvos tekste                            | pagal temos paletę (tamsi — šviesesnės, kontrastas — juoda)   |
| O3  | kompaktiška tema Apmokymuose                        | be įžangos, siauresnis sąrašas; show_all įžangos neatidengia  |
| O4–O5 | išsaugojus / naujas langas                        | tema pritaikoma iškart / iš nustatymų                         |
| O6  | Apmokymų skirtukai                                  | „Laukia vardo (N)" / „Registruoti balsai (M)"                 |
| O7  | `WrapBox`                                           | persikelia kaip tekstas; naikinimas be Python nuorodos neužstringa |

### Nustatymų pakeitimų matrica (ar kiekvienas nustatymas tikrai veikia)

| Nustatymas                             | Ką turi pakeisti                    | Testai         |
| -------------------------------------- | ----------------------------------- | -------------- |
| tylos sekundės                         | kada uždaromas failas               | C4, J2         |
| VOX jautrumas (atsidarymo / išlaikymo) | kada atsidaro / neuždaro            | C2, C5         |
| min įrašo trukmė                       | trumpų atmetimas                    | C6             |
| max įrašo trukmė                       | priverstinis STOP                   | D2             |
| režimas (iškart / naktį)               | transkripcijos laikas               | D3, J3         |
| auto transkripcija                     | ar transkribuojama                  | D3             |
| modelis                                | kuris modelis kraunamas (debug log) | E5             |
| mp3 / kokybė                           | archyvo formatas, bitrate           | E3             |
| trinti tuščius                         | tuščių likimas                      | E2             |
| teksto laikymas (dienos)               | lango trimingas                     | I2             |
| VAD min kalba / paddingas              | praleidimas / trim                  | H1–H6          |
| vardo slenkstis / atsarga              | vardas ↔ `Kolega?` (griežtumas)     | G6, G10        |
| kolegų garso šalinimas (mikrofone)     | L be R kopijos / kaip anksčiau      | L5             |
| tema                                   | lango išvaizda, šriftas, spalvos    | O1–O5          |
| debug                                  | `debug.log` pildosi                 | `test_debug_doctor.py` |

### Rankinis GUI checklist (prieš push)

Logika ištestuota automatiškai (nurodyta skliaustuose); žmogaus akims / ausims lieka:

- [ ] Ikona keičia spalvas ⚪ → 🔴 → 🟡 → ⚪ realaus diktavimo metu (logika: I6, C8)
- [ ] Pulsuoja, kai yra pending; nustoja, kai visi priskirti (logika: I6)
- [ ] Meniu: ⚙ Nustatymai viršuje; „🎓 Apmokymai paruošti (N)" kai pending; vidurinis klik → Nustatymai (I6)
- [ ] Apmokymai: grojimas girdisi, vardo autocomplete, navigacija, tekstuose vardas atsinaujina (I5, G4)
- [x] Nustatymai: pakeitimas veikia be restarto; „Atkurti numatytus" atstato (I4, B6, J2)
- [x] Teksto langas: paieška, Ctrl+F, ◀ ▶, laikymo trimingas, filtrai, žymės, eksportas (I2, I3, Etapas 6)
- [ ] ▶ Groti nuo eilutės — girdisi teisinga vieta, paryškinama einama eilutė (logika: Etapo 6 testai)
- [ ] Po kompiuterio perkrovimo viskas pasileidžia savaime
- [x] `git status` neturi nė vieno privataus failo; `make test-privacy` žalias (darbinio medžio auditas)

### Definition of Done (kiekvienam etapui)

1. Etapo testai parašyti ir žali (`make test`; jei liečia ASR — ir `make test-full`).
2. `make test-privacy` žalias (įsk. senojo pavadinimo nebuvimą).
3. Dokumentacija atnaujinta (ARCHITECTURE.md, README, šio plano statusas).
4. Etapui aktualūs rankinio checklist punktai patikrinti.


