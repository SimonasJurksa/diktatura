#!/usr/bin/env bash
# Diktatūra — privatumo sargo testai (QA sritis A).
#  1) .githooks elgsena laikiname git repo (tikro repo nekeičia), su IŠGALVOTAIS terminais.
#  2) Realaus repo apsauga: hooks įjungti, .gitignore tikrai ignoruoja privačius kelius
#     (regresija: buvo klaida su komentarais toje pačioje eilutėje), HEAD auditas.
# Paleisti: bash tests/privacy_guard_test.sh   (arba: make test-privacy)
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS="$REPO/.githooks"
Z=0000000000000000000000000000000000000000
pass=0; failc=0
ok(){ echo "  ✓ $1"; pass=$((pass + 1)); }
ko(){ echo "  ✗ $1"; failc=$((failc + 1)); }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
cd "$T" || exit 1
git init -q && git config core.hooksPath "$HOOKS"
git config user.name "Test User" && git config user.email "test@example.com"
# Išgalvoti testiniai „privatūs" terminai (NE tikri vardai)
make_terms(){ printf '# testas\nZuik(is|io|iui|į)\\b\nslaptprojekt\n' > .private-terms; }
make_terms

attempt(){  # $1 = blocked|allowed, $2 = aprašas, $3.. = failai (jau sukurti)
  local want="$1" desc="$2" got; shift 2
  git add -f -- "$@" >/dev/null 2>&1
  if git commit -q -m "t" >/dev/null 2>&1; then got=allowed; else got=blocked; git reset -q; fi
  [ "$got" = "$want" ] && ok "$desc" || ko "$desc (tikėtasi $want, gauta $got)"
  [ "$got" = "blocked" ] && rm -rf -- "$@"
  return 0
}

echo "── pre-commit: draudžiami failai (net su git add -f) ──"
printf 'RIFF' > a.wav;                                   attempt blocked "garso failas .wav" a.wav
printf 'ID3' > a.mp3;                                    attempt blocked "garso failas .mp3" a.mp3
mkdir -p recordings && echo "[0:00] Tu: x" > recordings/x.named.txt
                                                         attempt blocked "transkripcija recordings/*.named.txt" recordings/x.named.txt
mkdir -p speakers && echo '{}' > speakers/enroll.json;   attempt blocked "balsų biometrija speakers/enroll.json" speakers/enroll.json
mkdir -p speakers && echo '[]' > speakers/owner.json;    attempt blocked "tavo balso biometrija speakers/owner.json" speakers/owner.json
echo '{}' > annotations.json;                            attempt blocked "žymės su teksto ištraukomis annotations.json" annotations.json
echo '[]' > ignored.json;                                attempt blocked "triukšmo embedding'ai ignored.json" ignored.json
mkdir -p models && printf 'x' > models/m.onnx;           attempt blocked "modelis models/*.onnx" models/m.onnx
echo "log" > debug.log;                                  attempt blocked "logas *.log" debug.log
echo "{}" > s.diar.json;                                 attempt blocked "diarizacijos išvestis *.diar.json" s.diar.json
mkdir -p config && echo "MODE=x" > config/diktatura.conf; attempt blocked "lokalus config/diktatura.conf" config/diktatura.conf
echo "# x" > STATUS.md;                                  attempt blocked "asmeninis STATUS.md (root)" STATUS.md
attempt blocked "pats .private-terms" .private-terms
make_terms   # attempt užblokavus ištrina failą — atkuriam tolesniems testams
head -c 3145728 /dev/zero > big.dat;                     attempt blocked "per didelis failas (3 MB)" big.dat

echo "── pre-commit: asmeniniai terminai ──"
echo "Šiandien kalbėjo Zuikis apie planą" > n1.md;       attempt blocked "terminas tekste (Zuikis)" n1.md
echo "ZUIKIO pastaba" > n2.md;                           attempt blocked "be didžiųjų/mažųjų skirtumo (ZUIKIO)" n2.md
echo "SlaptProjektas v2" > n3.md;                        attempt blocked "stemas (slaptprojekt…)" n3.md
echo "x" > Zuikis_pastabos.md;                           attempt blocked "terminas failo varde" Zuikis_pastabos.md
echo "zuikis_notes = load()" > n4.py;                    attempt blocked "terminas snake_case identifikatoriuje" n4.py
echo "nezuikis ir paleidimas" > ok1.md;                  attempt allowed "nėra klaidingo suveikimo žodžio viduryje" ok1.md
echo "print('labas')" > ok2.py;                          attempt allowed "įprastas kodas praleidžiamas" ok2.py
mkdir -p docs/img && printf '\x89PNG' > docs/img/x.png;  attempt allowed "maža PNG iliustracija leidžiama" docs/img/x.png
# Regresija: kodo paketas diktatura/speakers/ neturi būti painiojamas su duomenų katalogu speakers/
mkdir -p diktatura/speakers && echo "def f(): pass" > diktatura/speakers/lib.py
                                                         attempt allowed "kodo paketas diktatura/speakers/*.py leidžiamas" diktatura/speakers/lib.py
mkdir -p diktatura/speakers && echo '{}' > diktatura/speakers/enroll.json
                                                         attempt blocked "enroll.json kodo pakete vis tiek blokuojamas" diktatura/speakers/enroll.json
mkdir -p diktatura/speakers && printf 'RIFF' > diktatura/speakers/x.wav
                                                         attempt blocked "garsas kodo pakete vis tiek blokuojamas" diktatura/speakers/x.wav

echo "── pre-push: kiekvienas stumiamas commit'as ──"
clean="$(git rev-parse HEAD)"
out=$(printf 'refs/heads/main %s refs/heads/main %s\n' "$clean" "$Z" | "$HOOKS/pre-push" origin x 2>&1); rc=$?
[ $rc -eq 0 ] && ok "švari istorija praleidžiama" || ko "švari istorija praleidžiama (rc=$rc) $out"
printf 'RIFF' > b.wav && git add -f b.wav && git commit -q --no-verify -m "apeitas sargas"
bad="$(git rev-parse HEAD)"
printf 'refs/heads/main %s refs/heads/main %s\n' "$bad" "$clean" | "$HOOKS/pre-push" origin x >/dev/null 2>&1
[ $? -ne 0 ] && ok "blokuoja .wav, commit'intą su --no-verify" || ko "blokuoja .wav, commit'intą su --no-verify"
# Neigiamas audito testas: auditas PRIVALO aptikti privatų failą (apsauga nuo „klaidingai žalio" audito)
"$HOOKS/privacy-scan.sh" audit "$bad" >/dev/null 2>&1
[ $? -ne 0 ] && ok "auditas aptinka privatų failą istorijoje" || ko "auditas aptinka privatų failą istorijoje"
git reset -q --hard "$clean"
echo "x" > m.md && git add m.md && git -c user.email="zuikis@corp.example" commit -q --no-verify -m "email"
emailc="$(git rev-parse HEAD)"
printf 'refs/heads/main %s refs/heads/main %s\n' "$emailc" "$clean" | "$HOOKS/pre-push" origin x >/dev/null 2>&1
[ $? -ne 0 ] && ok "blokuoja commit'ą su privačiu autoriaus email" || ko "blokuoja commit'ą su privačiu autoriaus email"

echo "── realus repo: apsaugos įjungtos ──"
cd "$REPO" || exit 1
[ "$(git config core.hooksPath)" = ".githooks" ] && ok "core.hooksPath = .githooks" || ko "core.hooksPath nenustatytas (make hooks)"
bad_ign=0
for p in recordings/x.wav recordings/a.named.txt recordings/a.mp3 speakers/enroll.json speakers/pending/n.wav \
         models/a/model.bin models/hf/blob STATUS.md CLAUDE.md .private-terms config/diktatura.conf logs/a.log \
         x.diar.json tests/fixtures/private/me.wav diktatura/speakers/enroll.json diktatura/speakers/pending/n.wav \
         annotations.json assigned.json ignored.json owner.json tests/fixtures/cv/a.mp3; do
  git check-ignore -q --no-index "$p" || { ko ".gitignore NEignoruoja: $p"; bad_ign=1; }
done; [ $bad_ign -eq 0 ] && ok ".gitignore ignoruoja visus privačius kelius (21)"
bad_ign=0
for p in README.md Makefile docs/PLAN.md .githooks/privacy-scan.sh tests/privacy_guard_test.sh \
         diktatura/speakers/__init__.py diktatura/speakers/speakerlib.py diktatura/paths.py; do
  git check-ignore -q --no-index "$p" && { ko ".gitignore klaidingai ignoruoja: $p"; bad_ign=1; }
done; [ $bad_ign -eq 0 ] && ok "versijuojami failai (įsk. diktatura/speakers/) neignoruojami"
# Darbinis medis: viskas, kas patektų į git po `git add -A` (įsk. naujus failus), turi būti švaru.
if out=$("$HOOKS/privacy-scan.sh" audit-worktree 2>&1); then ok "darbinio medžio auditas (git add -A): švaru"
else ko "darbinio medžio auditas (git add -A)"; printf '%s\n' "$out" | grep -E '✗' | head -5; fi
# Istorija (jau padaryti commit'ai) — tik informacija: ją taiso istorijos perrašymas prieš push (PLAN Q3).
if ! hist=$("$HOOKS/privacy-scan.sh" audit HEAD 2>&1) || printf '%s\n' "$hist" | grep -q '⚠'; then
  echo "  ⚠ informacija: HEAD/istorijoje yra privačių dalykų (sutvarkys švarus commit'as prieš push):"
  printf '%s\n' "$hist" | grep -E '✗|⚠' | head -3 | sed 's/^ */      /'
fi

echo
echo "Rezultatas: $pass ✓ / $failc ✗"
[ "$failc" -eq 0 ]
