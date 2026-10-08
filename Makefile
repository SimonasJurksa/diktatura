# Diktatūra — lietuviškas balso-į-tekstą (buv. vidinis id: wispr). Valdymas be Claude.
# Naudojimas:  make <komanda>   (make help — visos komandos)
SHELL := /bin/bash
W := $(HOME)/wispr
CONF := $(W)/wispr.conf
SYSD := $(HOME)/.config/systemd/user
SC := systemctl --user

.DEFAULT_GOAL := help

## ——— Pagalba ———
help: ## Parodyti visas komandas
	@echo "Wispr komandos:"
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	 awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-20s\033[0m %s\n",$$1,$$2}'
	@echo
	@echo "Dabartinė config:"; sed 's/^/  /' $(CONF) 2>/dev/null | grep -vE '^\s*#|^\s*$$' || true

## ——— Būsena ———
status: ## Bendra būsena (daemon, config, įrašai, transkripcijos, RAM/diskas)
	@echo "═══ WISPR BŪSENA ═══"
	@printf "Režimas: "; if $(SC) is-active wispr-vox >/dev/null 2>&1; then echo "🎙️ VOX (balso aktyvumas, be Slack)"; elif $(SC) is-active wispr-autorecord >/dev/null 2>&1; then echo "💬 SLACK (skambučių aptikimas)"; else echo "nė vienas neaktyvus"; fi
	@printf "Slack daemon: "; $(SC) is-active wispr-autorecord 2>/dev/null || true
	@printf "VOX daemon  : "; $(SC) is-active wispr-vox 2>/dev/null || true
	@printf "Naktinis timer   : "; $(SC) is-active wispr-nightly.timer 2>/dev/null || true; \
	 $(SC) list-timers wispr-nightly.timer --no-pager 2>/dev/null | grep wispr-nightly || true
	@echo "─ Config ─"; grep -vE '^\s*#|^\s*$$' $(CONF) 2>/dev/null | sed 's/^/  /'
	@echo "─ Vyksta dabar ─"; \
	 (pgrep -af "ffmpeg.*join=inputs" | grep -oE "slack_[0-9_]+\.wav" | sed 's/^/  🔴 įrašoma: /') || true; \
	 (pgrep -af "transcribe_named|transcribe_stereo" | grep -oE "slack_[0-9_]+\.wav" | sed 's/^/  ⏳ transkribuojama: /') || true; \
	 echo "  (jei tuščia virš — nieko nevyksta)"
	@echo "─ Įrašai ─"; $(MAKE) -s recordings
	@echo "─ Resursai ─"; free -h | awk '/Mem/{printf "  RAM: %s laisva / %s\n",$$7,$$2}'; \
	 df -h / | awk 'NR==2{printf "  Diskas: %s laisva (%s)\n",$$4,$$5}'

recordings: ## Įrašų sąrašas (💾 mp3 archyvas, ✓ tekstas+wav, ○ laukia)
	@shopt -s nullglob; p=0; \
	for m in $(W)/recordings/*.mp3; do printf "  💾 %s\n" "$$(basename $$m)"; done; \
	for w in $(W)/recordings/slack_*.wav $(W)/recordings/vox_*.wav; do \
	  b=$${w%.wav}; \
	  if [ -f "$$b.named.txt" ] || [ -f "$$b.clean.dialog.txt" ] || [ -f "$$b.dialog.txt" ] || [ -f "$$b.txt" ]; then m="✓ (wav+tekstas)"; else m="○ laukia teksto"; p=$$((p+1)); fi; \
	  printf "  %s  %s\n" "$$m" "$$(basename $$w)"; \
	done; echo "  —— laukia teksto: $$p ; archyvas: $(W)/recordings/*.mp3"

logs: ## Gyvi daemon logai (Ctrl+C išeiti)
	@tail -n 30 -f $(W)/recordings/autorecord.log

tlogs: ## Transkripcijos logai
	@tail -n 40 $(W)/recordings/transcribe.log

## ——— Daemon (įrašymas) ———
start: ## Įjungti įrašymo daemon
	@$(SC) start wispr-autorecord && echo "✓ daemon paleistas"
stop: ## Sustabdyti įrašymo daemon (nebeįrašinės)
	@$(SC) stop wispr-autorecord && echo "🛑 daemon sustabdytas (įrašymas IŠJUNGTAS)"
restart: ## Perkrauti daemon (po skriptų pakeitimų)
	@$(SC) restart wispr-autorecord && echo "✓ daemon perkrautas"

## ——— Auto-transkripcija ———
auto-on: ## Įjungti automatinį transkribavimą
	@sed -i 's/^AUTOTRANSCRIBE=.*/AUTOTRANSCRIBE=1/' $(CONF) && echo "✓ auto-transkripcija ĮJUNGTA"
auto-off: ## Išjungti auto-transkribavimą (tik įrašys, teksto negamins)
	@sed -i 's/^AUTOTRANSCRIBE=.*/AUTOTRANSCRIBE=0/' $(CONF) && echo "⏸ auto-transkripcija IŠJUNGTA (tik įrašo)"
immediate: ## Transkribuoti iškart po skambučio
	@sed -i 's/^MODE=.*/MODE=immediate/' $(CONF) && echo "✓ režimas: IŠKART po skambučio"
defer: ## Atidėti transkripciją nakčiai (01:30)
	@sed -i 's/^MODE=.*/MODE=deferred/' $(CONF) && echo "🌙 režimas: NAKTĮ 01:30 (įjunk timer: make nightly-on)"

model-azuolas: ## Naudoti Ąžuolą (geriausia LT kokybė)
	@sed -i 's/^MODEL=.*/MODEL=azuolas-ct2/' $(CONF) && echo "✓ modelis: Ąžuolas"
model-medium: ## Naudoti medium (greičiau, mažiau RAM)
	@sed -i 's/^MODEL=.*/MODEL=medium/' $(CONF) && echo "✓ modelis: medium"

## ——— Transkripcija rankiniu būdu ———
transcribe-pending: ## Sutranskribuoti VISUS įrašus be teksto dabar
	@bash $(W)/scripts/transcribe-pending.sh
transcribe: ## Sutranskribuoti vieną failą:  make transcribe FILE=recordings/xxx.wav
	@test -n "$(FILE)" || { echo "Nurodyk FILE=..."; exit 1; }; bash $(W)/scripts/transcribe-file.sh "$(FILE)"
stop-transcribe: ## Sustabdyti vykstančias transkripcijas (jei persigalvojai)
	@pkill -f "transcribe_named|transcribe_stereo|transcribe\.py" 2>/dev/null && echo "🛑 transkripcijos sustabdytos" || echo "(nebuvo ką stabdyti)"

## ——— Režimas: Slack vs VOX ———
mode-slack: install-units ## Režimas: Slack skambučių aptikimas (numatyta)
	@$(SC) disable --now wispr-vox 2>/dev/null || true; $(SC) enable --now wispr-autorecord && echo "💬 režimas: SLACK (aptinka skambučius)"
mode-vox: install-units ## Režimas: VOX balso aktyvumas (diktavimui, be Slack)
	@$(SC) disable --now wispr-autorecord 2>/dev/null || true; $(SC) enable --now wispr-vox && echo "🎙️ režimas: VOX (garsas>gate → įrašo; tyla → uždaro). Gate keisti: wispr.conf VOX_GATE_DB"
vox-gate: ## Nustatyti VOX jautrumą:  make vox-gate DB=-40  (žemesnis=jautriau)
	@test -n "$(DB)" || { echo "Nurodyk DB=... (pvz -40)"; exit 1; }; sed -i 's/^VOX_GATE_DB=.*/VOX_GATE_DB=$(DB)/' $(CONF) && echo "✓ VOX gate: $(DB) dB (perkrauk: make restart-vox)"
restart-vox: ## Perkrauti VOX daemon (po nustatymų)
	@$(SC) restart wispr-vox && echo "✓ VOX perkrautas"

## ——— Naktinis timer (01:30) ———
nightly-on: install-units ## Įjungti naktinę transkripciją 01:30
	@$(SC) enable --now wispr-nightly.timer && echo "🌙 naktinis 01:30 ĮJUNGTAS" && $(SC) list-timers wispr-nightly.timer --no-pager | grep wispr || true
nightly-off: ## Išjungti naktinę transkripciją
	@$(SC) disable --now wispr-nightly.timer && echo "naktinis IŠJUNGTAS"
nightly-now: ## Paleisti naktinę transkripciją dabar (testui)
	@$(SC) start wispr-nightly.service && echo "paleista; logai: make tlogs"

## ——— Status bar ikona ———
tray-on: install-units ## Įjungti status bar ikoną (⚪/🔴/🟡)
	@$(SC) enable --now wispr-tray && echo "✓ ikona įjungta (viršuje, status bar)"
tray-off: ## Išjungti ikoną
	@$(SC) disable --now wispr-tray && echo "ikona išjungta"
tray-restart: ## Perkrauti ikoną
	@$(SC) restart wispr-tray && echo "✓ ikona perkrauta"

## ——— Diegimas ———
install-units: ## Įdiegti/atnaujinti systemd units (daemon + timer)
	@mkdir -p $(SYSD); cp $(W)/scripts/wispr-autorecord.service $(W)/scripts/wispr-vox.service $(W)/scripts/wispr-nightly.service $(W)/scripts/wispr-nightly.timer $(W)/scripts/wispr-tray.service $(SYSD)/; \
	 $(SC) daemon-reload && echo "✓ units įdiegti/atnaujinti"
install: install-units ## Pilnas įdiegimas (daemon enable+start)
	@$(SC) enable --now wispr-autorecord && echo "✓ daemon įdiegtas ir paleistas (startuos po perkrovimo)"

enroll: ## Registruoti balsą:  make enroll NAME=Vardas WAV=/kelias.wav
	@test -n "$(NAME)" -a -n "$(WAV)" || { echo "Nurodyk NAME=... WAV=..."; exit 1; }; \
	 $(W)/plans/F/.venv/bin/python $(W)/plans/F/enroll.py --name "$(NAME)" --wav "$(WAV)"
speakers: ## Parodyti registruotus balsus
	@$(W)/plans/A/.venv/bin/python -c "import sys;sys.path.insert(0,'$(W)/plans/F');import speakerlib as s;d=s.load_enroll();print('Registruoti:',{k:len(v) for k,v in d.items()} or 'nėra')"
name-unknown: ## Parodyti nežinomus balsus (pending), laukiančius vardo
	@shopt -s nullglob; n=0; for j in $(W)/speakers/pending/*.json; do \
	  id=$$(basename $$j .json); n=$$((n+1)); \
	  src=$$(grep -oE '"src": "[^"]*"' $$j | cut -d'"' -f4); \
	  printf "  \033[1m%s\033[0m (iš %s)\n    ▶ klausyti:  paplay %s/speakers/pending/%s.wav\n    ✎ priskirti: make assign ID=%s NAME=Vardas\n" "$$id" "$$src" "$(W)" "$$id" "$$id"; \
	done; [ $$n -eq 0 ] && echo "  (nežinomų balsų nėra)" || echo "  —— viso: $$n"
assign: ## Priskirti nežinomą balsą vardui:  make assign ID=nez3 NAME=Jonas
	@test -n "$(ID)" -a -n "$(NAME)" || { echo "Nurodyk ID=nez3 NAME=Vardas"; exit 1; }; \
	 $(W)/plans/F/.venv/bin/python $(W)/plans/F/enroll.py --name "$(NAME)" --from-pending "$(ID)"

.PHONY: help status recordings logs tlogs start stop restart auto-on auto-off immediate defer \
        model-azuolas model-medium transcribe-pending transcribe stop-transcribe \
        nightly-on nightly-off nightly-now install-units install enroll speakers \
        mode-slack mode-vox vox-gate restart-vox tray-on tray-off tray-restart \
        name-unknown assign
