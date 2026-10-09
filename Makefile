# Diktatūra — lietuviškas balso-į-tekstą (lokaliai, privačiai). Valdymas be Claude.
# Naudojimas:  make <komanda>   (make help — visos komandos)
#
# Kodas — šiame repo; duomenys — už jo ribų (XDG, žr. diktatura/paths.py ir bin/common.sh):
#   ~/.config/diktatura/diktatura.conf, ~/.local/share/diktatura/{recordings,speakers,models},
#   ~/.local/state/diktatura/*.log
SHELL := /bin/bash
REPO := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
CONFIG_DIR := $(or $(DIKTATURA_CONFIG_DIR),$(or $(XDG_CONFIG_HOME),$(HOME)/.config)/diktatura)
DATA_DIR := $(or $(DIKTATURA_DATA),$(or $(XDG_DATA_HOME),$(HOME)/.local/share)/diktatura)
STATE_DIR := $(or $(DIKTATURA_STATE),$(or $(XDG_STATE_HOME),$(HOME)/.local/state)/diktatura)
RUN_DIR := $(or $(DIKTATURA_RUN),$(if $(XDG_RUNTIME_DIR),$(XDG_RUNTIME_DIR)/diktatura,/tmp/diktatura-$(shell id -u)))
REC := $(DATA_DIR)/recordings
PENDING := $(DATA_DIR)/speakers/pending
MODELS := $(DATA_DIR)/models

PY := $(REPO)/.venv/bin/python
RUN := PYTHONPATH=$(REPO) HF_HOME=$(MODELS)/hf $(PY) -m
CFG := PYTHONPATH=$(REPO) /usr/bin/python3 -m diktatura.config
SYSD := $(HOME)/.config/systemd/user
APPS := $(or $(DIKTATURA_APPS_DIR),$(or $(XDG_DATA_HOME),$(HOME)/.local/share)/applications)
SC := systemctl --user
UNITS := diktatura-autorecord.service diktatura-vox.service diktatura-tray.service \
         diktatura-nightly.service diktatura-nightly.timer diktatura-asr.service
RECORDERS := diktatura-vox diktatura-autorecord

.DEFAULT_GOAL := help

## ——— Pagalba ———
help: ## Parodyti visas komandas
	@echo "Diktatūra — komandos:"
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	 awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-20s\033[0m %s\n",$$1,$$2}'
	@echo; echo "Nustatymai:"; $(CFG) show 2>/dev/null || true

## ——— Būsena ———
doctor: ## Sistemos savitikra: įrankiai, garsas, modeliai, servisai, resursai (✓/⚠/✗ + ką daryti)
	@cd $(REPO) && PYTHONPATH=$(REPO) /usr/bin/python3 -m diktatura.doctor
debug-on: ## Įjungti debug žurnalą (~/.local/state/diktatura/debug.log)
	@$(CFG) set DEBUG=1 && echo "🐞 debug įjungtas: tail -f $(STATE_DIR)/debug.log  (išjungti: make debug-off)"
debug-off: ## Išjungti debug žurnalą
	@$(CFG) set DEBUG=0
dlogs: ## Gyvas debug žurnalas (Ctrl+C išeiti)
	@tail -n 50 -f $(STATE_DIR)/debug.log
status: ## Bendra būsena (režimas, servisai, nustatymai, įrašai, RAM/diskas)
	@echo "═══ DIKTATŪRA — BŪSENA ═══"
	@printf "Režimas: "; if $(SC) is-active -q diktatura-vox; then echo "🎙️ VOX (balso aktyvumas)"; \
	 elif $(SC) is-active -q diktatura-autorecord; then echo "💬 SLACK (skambučių aptikimas)"; else echo "įrašymas išjungtas"; fi
	@for u in $(RECORDERS) diktatura-tray diktatura-nightly.timer; do \
	  e=$$($(SC) is-enabled $$u 2>/dev/null); printf "  %-26s %s / %s\n" "$$u" "$$($(SC) is-active $$u 2>/dev/null)" "$${e:-neįdiegtas}"; done
	@$(SC) list-timers diktatura-nightly.timer --no-pager 2>/dev/null | grep diktatura-nightly | sed 's/^/  naktinis: /' || true
	@echo "─ Nustatymai ─"; $(CFG) show
	@echo "─ Vyksta dabar ─"; \
	 if [ -f "$(RUN_DIR)/recording" ]; then echo "  🔴 įrašoma: $$(basename "$$(cut -d' ' -f2- "$(RUN_DIR)/recording")")"; fi; \
	 (pgrep -af "diktatura[.]asr[.]" | grep -oE "(slack|vox|rec)_[0-9_]+\.(wav|mp3)" | sed 's/^/  ⏳ transkribuojama: /') || true; \
	 echo "  (jei tuščia virš — nieko nevyksta)"
	@echo "─ Įrašai ─"; $(MAKE) -s recordings
	@echo "─ Resursai ─"; free -h | awk '/Mem/{printf "  RAM: %s laisva / %s\n",$$7,$$2}'; \
	 df -h "$(DATA_DIR)" | awk 'NR==2{printf "  Diskas: %s laisva (%s)\n",$$4,$$5}'

recordings: ## Įrašų sąrašas (💾 mp3 archyvas, ✓ tekstas+wav, ○ laukia teksto)
	@shopt -s nullglob; p=0; a=0; \
	for m in $(REC)/*.mp3; do a=$$((a+1)); done; \
	for w in $(REC)/{slack,vox,rec}_*.wav; do \
	  b=$${w%.wav}; \
	  if [ -f "$$b.named.txt" ] || [ -f "$$b.clean.dialog.txt" ] || [ -f "$$b.dialog.txt" ] || [ -f "$$b.txt" ]; then m="✓ (wav+tekstas)"; \
	  elif [ -f "$$b.skip" ]; then m="⤼ praleistas"; else m="○ laukia teksto"; p=$$((p+1)); fi; \
	  printf "  %s  %s\n" "$$m" "$$(basename $$w)"; \
	done; echo "  —— laukia teksto: $$p ; mp3 archyve: $$a ($(REC))"

logs: ## Gyvi įrašymo logai (Ctrl+C išeiti)
	@tail -n 30 -f $(STATE_DIR)/autorecord.log
tlogs: ## Transkripcijos logai
	@tail -n 40 $(STATE_DIR)/transcribe.log
text: ## Atidaryti langą: 📄 Tekstas (tas pats kaip ikonos meniu „Rodyti nuskaitytą tekstą")
	@cd $(REPO) && PYTHONPATH=$(REPO) setsid /usr/bin/python3 -m diktatura.ui.app --page text >/dev/null 2>&1 &
settings: ## Atidaryti langą: ⚙ Nustatymai
	@cd $(REPO) && PYTHONPATH=$(REPO) setsid /usr/bin/python3 -m diktatura.ui.app --page settings >/dev/null 2>&1 &
training: ## Atidaryti langą: 🎓 Apmokymai (nežinomų balsų vardai)
	@cd $(REPO) && PYTHONPATH=$(REPO) setsid /usr/bin/python3 -m diktatura.ui.app --page training >/dev/null 2>&1 &

## ——— Įrašymas (režimai) ———
mode-vox: install-units ## Režimas: VOX — įrašo, kai kalbama (diktavimas; pagauna ir skambučius)
	@$(SC) disable --now diktatura-autorecord 2>/dev/null || true; $(SC) enable --now diktatura-vox && \
	 echo "🎙️ režimas: VOX (garsas → įrašo; tyla → uždaro). Jautrumas: make config / make set"
mode-slack: install-units ## Režimas: SLACK — įrašo tik Slack skambučius (aptinka start/stop)
	@$(SC) disable --now diktatura-vox 2>/dev/null || true; $(SC) enable --now diktatura-autorecord && \
	 echo "💬 režimas: SLACK (aptinka skambučius)"
mode-off: ## Išjungti įrašymą visam (ir po perkrovimo)
	@$(SC) disable --now $(RECORDERS) 2>/dev/null; echo "🛑 įrašymas išjungtas (įjungti: make mode-vox / make mode-slack)"
start: ## Paleisti įjungtą įrašymo režimą
	@u=$$(for s in $(RECORDERS); do $(SC) is-enabled -q $$s 2>/dev/null && echo $$s; done | head -1); \
	 test -n "$$u" || { echo "Nė vienas režimas neįjungtas: make mode-vox arba make mode-slack"; exit 1; }; \
	 $(SC) start $$u && echo "✓ paleista: $$u"
stop: ## Laikinai sustabdyti įrašymą (po perkrovimo vėl įsijungs; visam — make mode-off)
	@$(SC) stop $(RECORDERS) && echo "🛑 įrašymas sustabdytas"
restart: ## Perkrauti įrašymo servisą (po kodo pakeitimų; nustatymams nereikia)
	@for s in $(RECORDERS); do $(SC) is-enabled -q $$s 2>/dev/null && $(SC) restart $$s && echo "✓ perkrauta: $$s"; done; true
rec-toggle: ## Rankinis įrašymas: 1-as kartas pradeda, 2-as sustabdo
	@bash $(REPO)/bin/rec-toggle.sh

## ——— Nustatymai (keitimai veikia be restarto) ———
config: ## Parodyti nustatymus (* = pakeista nuo numatytos)
	@$(CFG) show
set: ## Pakeisti nustatymą:  make set S="VOX_SILENCE_SEC=3 MODE=deferred"
	@test -n "$(S)" || { echo 'Nurodyk S="KEY=VALUE ..." (sąrašas: make config)'; exit 1; }; $(CFG) set $(S)
config-edit: ## Atidaryti nustatymų failą redaktoriuje
	@$${EDITOR:-nano} "$$($(CFG) path)"
config-reset: ## Atkurti numatytus nustatymus
	@$(CFG) reset
auto-on: ## Įjungti automatinį transkribavimą
	@$(CFG) set AUTOTRANSCRIBE=1
auto-off: ## Išjungti auto-transkribavimą (tik įrašys, teksto negamins)
	@$(CFG) set AUTOTRANSCRIBE=0
immediate: ## Transkribuoti iškart po įrašo
	@$(CFG) set MODE=immediate
defer: ## Atidėti transkripciją nakčiai (01:30)
	@$(CFG) set MODE=deferred && echo "🌙 įsitikink, kad naktinis įjungtas: make nightly-on"
model-azuolas: ## Naudoti Ąžuolą (geriausia LT kokybė)
	@$(CFG) set MODEL=azuolas-ct2
model-medium: ## Naudoti Whisper medium (greičiau, mažiau RAM)
	@$(CFG) set MODEL=medium
asr-server-on: install-units ## Nuolat įkrautas modelis: greitesnis tekstas po diktavimo (~3 GB RAM, kol yra darbo)
	@$(CFG) set ASR_SERVER=1 && $(SC) enable --now diktatura-asr && echo "⚡ ASR serveris įjungtas (iškrauna po ASR_SERVER_IDLE_MIN min be darbo)"
asr-server-off: ## Išjungti ASR serverį (kiekviena transkripcija krauna modelį pati)
	@$(CFG) set ASR_SERVER=0 && $(SC) disable --now diktatura-asr 2>/dev/null; echo "ASR serveris išjungtas"

## ——— Transkripcija rankiniu būdu ———
transcribe-pending: ## Sutranskribuoti VISUS įrašus be teksto dabar
	@bash $(REPO)/bin/transcribe-pending.sh
transcribe: ## Sutranskribuoti vieną failą:  make transcribe FILE=.../vox_xxx.wav
	@test -n "$(FILE)" || { echo "Nurodyk FILE=..."; exit 1; }; bash $(REPO)/bin/transcribe-file.sh "$(FILE)"
stop-transcribe: ## Sustabdyti vykstančias transkripcijas
	@k=0; pkill -f "bin/transcribe-pending[.]sh" && k=1; pkill -f "bin/transcribe-file[.]sh" && k=1; \
	 pkill -f "diktatura[.]asr[.]" && k=1; [ $$k = 1 ] && echo "🛑 transkripcijos sustabdytos" || echo "(nebuvo ką stabdyti)"

## ——— Naktinis timer (01:30) ———
nightly-on: install-units ## Įjungti naktinę transkripciją 01:30
	@$(SC) enable --now diktatura-nightly.timer && echo "🌙 naktinis 01:30 ĮJUNGTAS"
nightly-off: ## Išjungti naktinę transkripciją
	@$(SC) disable --now diktatura-nightly.timer && echo "naktinis IŠJUNGTAS"
nightly-now: ## Paleisti naktinę transkripciją dabar (testui)
	@$(SC) start --no-block diktatura-nightly.service && echo "paleista; logai: make tlogs"

## ——— Status bar ikona ———
tray-on: install-units ## Įjungti status bar ikoną (⚪/🔴/🟡)
	@$(SC) enable --now diktatura-tray && echo "✓ ikona įjungta (viršuje, status bar)"
tray-off: ## Išjungti ikoną
	@$(SC) disable --now diktatura-tray && echo "ikona išjungta"
tray-restart: ## Perkrauti ikoną
	@$(SC) restart diktatura-tray && echo "✓ ikona perkrauta"

## ——— Balsai (kalbėtojų vardai) ———
speakers: ## Parodyti registruotus balsus
	@PYTHONPATH=$(REPO) $(PY) -c "from diktatura.speakers import speakerlib as s; d=s.load_enroll(); print('Registruoti:', {k: len(v) for k, v in d.items()} or 'nėra')"
name-unknown: ## Parodyti nežinomus balsus (pending), laukiančius vardo
	@shopt -s nullglob; n=0; for j in $(PENDING)/*.json; do \
	  id=$$(basename $$j .json); n=$$((n+1)); \
	  src=$$(grep -oE '"src": "[^"]*"' $$j | cut -d'"' -f4); \
	  printf "  \033[1m%s\033[0m (iš %s)\n    ▶ klausyti:  paplay %s/%s.wav\n    ✎ priskirti: make assign ID=%s NAME=Vardas\n" "$$id" "$$src" "$(PENDING)" "$$id" "$$id"; \
	done; [ $$n -eq 0 ] && echo "  (nežinomų balsų nėra)" || echo "  —— viso: $$n  (patogiau: make training — perklausa, kontekstas, vardai)"
assign: ## Priskirti nežinomą balsą vardui:  make assign ID=nez3 NAME=Jonas
	@test -n "$(ID)" -a -n "$(NAME)" || { echo "Nurodyk ID=nez3 NAME=Vardas"; exit 1; }; \
	 $(RUN) diktatura.speakers.enroll --name "$(NAME)" --from-pending "$(ID)"
enroll: ## Registruoti balsą iš švaraus įrašo:  make enroll NAME=Vardas WAV=/kelias.wav (16 kHz mono)
	@test -n "$(NAME)" -a -n "$(WAV)" || { echo "Nurodyk NAME=... WAV=..."; exit 1; }; \
	 $(RUN) diktatura.speakers.enroll --name "$(NAME)" --wav "$(WAV)"
speakers-migrate: ## Pereiti prie naujo balso modelio (seni balsai -> archyvas):  make speakers-migrate [APPLY=1]
	@$(RUN) diktatura.speakers.migrate $(if $(APPLY),--apply)
speakers-relabel: ## Perskaičiuoti kalbėtojus paskut. dienų tekstuose:  make speakers-relabel [DAYS=2] [APPLY=1]
	@$(RUN) diktatura.speakers.relabel --days $(or $(DAYS),2) $(if $(APPLY),--apply)

## ——— Diegimas ———
deps: ## Įdiegti sistemos paketus (sudo apt): ffmpeg (+ffplay), pactl/paplay, notify-send, GTK/AppIndicator, broadwayd
	sudo apt install -y ffmpeg pulseaudio-utils libnotify-bin python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 \
	  libgtk-3-bin curl bzip2
setup: ## Sukurti .venv (Python 3.10, be torch) ir įdiegti priklausomybes
	@command -v uv >/dev/null || { echo "Reikia uv: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	@cd $(REPO) && { test -x .venv/bin/python || uv venv .venv --python 3.10; } && VIRTUAL_ENV=.venv uv pip install -q -r requirements.txt
	@$(RUN) diktatura.paths >/dev/null && PYTHONPATH=$(REPO) $(PY) -c "import faster_whisper, sherpa_onnx, sklearn" && echo "✓ .venv paruoštas"
models: ## Atsisiųsti kalbėtojų modelius (~35 MB, SHA-256 tikrinami)
	@bash $(REPO)/tools/fetch_models.sh
model-convert: ## Ąžuolą konvertuoti į CT2 int8 (vienkartinis; reikia ~8–10 GB laisvo disko)
	@bash $(REPO)/tools/convert_azuolas.sh
desktop: ## Įdiegti „Diktatūra" į programų meniu (prisegama prie doko; grąžina ikoną ir atidaro langą)
	@mkdir -p $(APPS) && sed 's|@REPO@|$(REPO)|g' $(REPO)/desktop/diktatura.desktop.in > $(APPS)/diktatura.desktop && \
	 (command -v update-desktop-database >/dev/null && update-desktop-database -q $(APPS) || true) && \
	 echo "✓ programų meniu: Diktatūra ($(APPS)/diktatura.desktop) — prisegti: dešinys klik → „Pridėti prie mėgstamiausių“"
install-units: ## Įdiegti/atnaujinti systemd --user servisus (iš systemd/*.in šablonų)
	@mkdir -p $(SYSD); for u in $(UNITS); do sed 's|@REPO@|$(REPO)|g' $(REPO)/systemd/$$u.in > $(SYSD)/$$u; done; \
	 $(SC) daemon-reload && echo "✓ servisai įdiegti/atnaujinti ($(SYSD))"
install: hooks setup models install-units desktop ## Pilnas įdiegimas: venv, modeliai, servisai, ikona, naktinis, meniu
	@$(SC) enable --now diktatura-tray diktatura-nightly.timer
	@for s in $(RECORDERS); do $(SC) is-enabled -q $$s 2>/dev/null && exit 0; done; $(MAKE) -s mode-slack
	@test -f $(MODELS)/azuolas-ct2/model.bin || echo "⚠ Ąžuolo modelio nėra: make model-convert (arba make model-medium)"
	@echo "✓ įdiegta. Būsena: make status"
uninstall: ## Pašalinti servisus (duomenys ir nustatymai lieka)
	@$(SC) disable --now $(UNITS) 2>/dev/null; for u in $(UNITS); do rm -f $(SYSD)/$$u; done; $(SC) daemon-reload; \
	 rm -f $(APPS)/diktatura.desktop; \
	 echo "✓ servisai pašalinti. Duomenys liko: $(DATA_DIR) , nustatymai: $(CONFIG_DIR)"

## ——— Privatumas / testai ———
hooks: ## Įjungti privatumo sargą (git hooks) — BŪTINA kiekvienam kūrėjui po clone
	@cd $(REPO) && chmod +x .githooks/* && git config core.hooksPath .githooks && echo "✓ privatumo sargas įjungtas (.githooks: pre-commit + pre-push)"
test-privacy: ## Privatumo sargo testai (gitignore + hooks + darbinio medžio auditas)
	@bash $(REPO)/tests/privacy_guard_test.sh
test: ## Greiti testai (be modelių, < 1 min): nustatymai, VOX, Slack, eilė, kalbėtojai, UI, privatumas
	@cd $(REPO) && $(PY) -m pytest -m "not full and not e2e" $(T)
test-full: fixtures ## + testai su tikrais modeliais (Ąžuolas, VAD, kalbėtojų ONNX) ir LT garsu, ~5–10 min
	@cd $(REPO) && $(PY) -m pytest -m "full" $(T)
test-e2e: ## E2E: virtualus garsas (PulseAudio null-sink) + tikri daemon'ai (tavo garso nekeičia), ~3 min
	@cd $(REPO) && $(PY) -m pytest -m "e2e" $(T)
fixtures: ## Atsisiųsti LT kalbos testų klipus (Common Voice, CC0, ~220 KB; ne į repo)
	@bash $(REPO)/tools/fetch_fixtures.sh

.PHONY: help desktop speakers-migrate speakers-relabel doctor debug-on debug-off dlogs status recordings logs tlogs text settings training mode-vox mode-slack mode-off start stop restart rec-toggle \
        config set config-edit config-reset auto-on auto-off immediate defer model-azuolas model-medium \
        asr-server-on asr-server-off \
        transcribe-pending transcribe stop-transcribe nightly-on nightly-off nightly-now \
        tray-on tray-off tray-restart speakers name-unknown assign enroll \
        deps setup models model-convert install-units install uninstall hooks test-privacy \
        test test-full test-e2e fixtures
