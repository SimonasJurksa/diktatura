# Prisidėti prie Diktatūros

Ačiū, kad nori padėti! Diktatūra — lokalus, privatus lietuviškas balso-į-tekstą įrankis Linux'ui.
Techninis aprašas — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), darbų planas ir QA — [docs/PLAN.md](docs/PLAN.md).

## 1. Aplinka

```bash
git clone https://github.com/SimonasJurksa/diktatura.git && cd diktatura
make hooks           # BŪTINA: privatumo sargas (git hooks) — žr. §4
make deps            # sistemos paketai (sudo apt): ffmpeg, pactl, GTK/AppIndicator, broadwayd (UI testams)
make setup           # .venv (Python 3.10, be torch): faster-whisper, sherpa-onnx, numpy, sklearn, pytest
make models          # kalbėtojų ONNX modeliai (~35 MB, SHA-256)
make fixtures        # LT kalbos testų klipai (Common Voice, CC0, ~220 KB) — tik test-full / e2e
make doctor          # ar viskas vietoje
```

Ąžuolo modelio (`make model-convert`, ~8–10 GB laikinai) reikia tik tikrai transkripcijai ir `make test-full`.

## 2. Struktūra (trumpai)

| Kur | Kas |
|---|---|
| `diktatura/paths.py`, `config.py`, `sessions.py`, `services.py`, `debug.py`, `annotations.py`, `reset.py` | **tik stdlib** — importuoja ir `.venv`, ir sistemos `python3` (UI) |
| `diktatura/audio/` | `vox.py` (VOX daemon'as, `VoxGate` — gryna logika), `prefilter.py` (Silero VAD), `echo.py` (kolegų garso šalinimas iš mikrofono kanalo) |
| `diktatura/asr/` | `transcribe.py` (mono), `transcribe_named.py` (stereo + vardai), `dialog.py` (de-dup), `server.py`/`client.py` (nuolat įkrautas modelis) |
| `diktatura/speakers/` | `store.py` (balsų saugykla, stdlib), `speakerlib.py` (embedding'ai, griežtas vardų priskyrimas), `teach.py` (mokymasis iš pataisymo), `migrate.py` / `relabel.py` (balso modelio keitimas), įrankiai |
| `diktatura/ui/` | GTK (sistemos `python3`): `app.py` (langas), `text_page.py`, `training_page.py`, `settings_page.py`, `tray.py` |
| `bin/` | shell įėjimai (`common.sh` — keliai/nustatymai bash'ui; laikyti sinchronizuotą su `paths.py`) |
| `systemd/*.in` | servisų šablonai (`@REPO@` → `make install-units`) |
| `desktop/*.in` | programų meniu / doko paleidiklis (`@REPO@` → `make desktop`) |
| `tests/` | pytest; `tests/helpers/` — sintetinis garsas, netikri įrankiai (`fakebin/`), `testenv.py` |

Taisyklės:
- **Du interpretatoriai:** `.venv` (daemon'ai, ASR) ir sistemos `python3` (GTK). UI moduliuose — jokio numpy/faster-whisper.
- Keliai — tik per `diktatura/paths.py` / `bin/common.sh` (abu perrašomi `DIKTATURA_DATA/CONFIG_DIR/STATE/RUN`).
- Naujas nustatymas: `config/diktatura.conf.default` + `SCHEMA` (`diktatura/config.py`) — Nustatymų langas jį parodys pats.
- Keičiant balso modelį: `tools/fetch_models.sh` (URL + SHA-256) ir `store.EMB_MODEL` — senų balsų saugykla taps
  nesuderinama (vardai nerašomi), kol vartotojas paleis `make speakers-migrate APPLY=1`.
- Paleidimas — tik kaip modulio: `PYTHONPATH=<repo> python -m diktatura.…`.

## 3. Testai

```bash
make test            # greiti (~1.5 min): nustatymai, VOX, Slack, eilė, VAD, kalbėtojai, ASR serveris, UI, doctor, privatumas
make test-full       # + tikras Ąžuolas su LT garsu (WER ≤ 25 %), ASR serveris, tikras balso modelis
make test-e2e        # tikras VOX + ffmpeg per virtualius PulseAudio įrenginius (tavo garso nekeičia)
make test-privacy    # privatumo sargas
make test T="-k vox" # pytest argumentai
```

- **Saugiklis:** `tests/conftest.py` prieš bet kokį `diktatura.*` importą nukreipia `DIKTATURA_*` į laikiną katalogą ir
  įdeda netikrą `notify-send` — testai neliečia tavo įrašų/balsų/nustatymų ir nerodo pranešimų.
- Fixture'ai: `env` (izoliuota aplinka), `fake_audio` (netikri `pactl`/`ffmpeg`), `fake_asr`, `fake_systemd`,
  `real_models` (tikri modeliai + tikras transkripcijos užraktas).
- UI testai — GTK per `broadwayd` (langai tavo ekrane nerodomi).
- Kiekvienas pakeitimas — su testu; prieš PR: `make test && make test-privacy` (geriausia ir `test-full`, `test-e2e`).

## 4. Privatumas (repo public!)

Sistema dirba su labai asmeniškais duomenimis: pokalbių garsu, transkripcijomis, balsų biometrija.
- Duomenys gyvena **už repo ribų** (`~/.local/share/diktatura` ir kt.) — į repo jie net nepatenka.
- `make hooks` įjungia `.githooks/` (pre-commit + pre-push): blokuoja garsą, transkripcijas, balsų embedding'us,
  modelius, logus, > 2 MB failus ir **asmeninius terminus** iš lokalaus `.private-terms` (kolegų vardai, darbovietė…).
  `.private-terms` niekada nekeliamas į git; formatas — `.githooks/privacy-scan.sh` antraštėje.
- Testuose ir dokumentacijoje — **tik išgalvoti vardai** (Ona, Jonas, Rūta…) ir sintetinis / CC0 garsas.
- `--no-verify` neapeina pre-push patikros.

## 5. Stilius

- Kodas ir komentarai — lietuviškai (kaip esamas kodas); vardai (kintamieji, funkcijos) — angliškai.
- Komentaras aiškina **kodėl**, ne ką. Ilgesni „kodėl" ir pamokos — `docs/ARCHITECTURE.md` §3 ir §5.
- Commit'ai — trumpi, lietuviškai, aiškiai: kas pasikeitė ir kodėl.
