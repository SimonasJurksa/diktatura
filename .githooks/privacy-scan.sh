#!/usr/bin/env bash
# Diktatūra — privatumo sargas (antras saugos sluoksnis po .gitignore).
#
# Neleidžia į git įtraukti: garso įrašų, transkripcijų, balsų biometrijos (enroll.json, owner.json, pending),
# modelių, logų, lokalaus config, asmeninių darbo dokumentų, per didelių failų ir asmeninių
# terminų (kolegų vardai, darbovietė, email) — terminai laikomi LOKALIAME .private-terms (gitignore).
#
# Naudojimas:
#   privacy-scan.sh staged          # pre-commit: tikrina staged pakeitimus
#   privacy-scan.sh commit <sha>    # pre-push: vieno commit'o pakeitimai + autoriaus/committer email
#   privacy-scan.sh audit [rev]     # auditas: visas medis (numatyta HEAD) + visų commit'ų email
#   privacy-scan.sh audit-index     # auditas: BŪSIMO commit'o turinys (staged index medis)
#   privacy-scan.sh audit-worktree  # auditas: kas patektų į git po `git add -A` (laikinas index; tikras nekeičiamas)
#
# .private-terms formatas: viena eilutė = ERE šablonas, be didžiųjų/mažųjų skirtumo, tikrinamas
# ŽODŽIO PRADŽIOJE: "Petr" pagaus Petras/Petro/Petrui, bet ne "kompetrija". Eilutė su # — komentaras.
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel)"
MAX_KB="${DIKTATURA_MAX_FILE_KB:-2048}"
TERMS_FILE="${DIKTATURA_PRIVATE_TERMS:-$ROOT/.private-terms}"
EMPTY_TREE="$(git hash-object -t tree /dev/null)"

# Draudžiami keliai / plėtiniai (taikoma failo keliui)
DENY='(^|/)(recordings|speakers|speakers_samples|models|logs)/|(^|/)\.venv/'
DENY+='|\.(wav|mp3|m4a|flac|ogg|opus|webm|aac|wma)$'
DENY+='|\.(named|dialog)\.txt$|(^|/)(enroll|owner|ignored|assigned|annotations)\.json$|\.(diar|clusters|reclust)\.json$'
DENY+='|\.(onnx|bin|ggml|pt|safetensors|ckpt)$|\.log$'
DENY+='|(^|/)\.private-terms$|(^|/)\.recording$|(^|/)config/diktatura\.conf$'
DENY+='|^(STATUS|CLAUDE)\.md$'
# Išimtis: kodo paketo .py failai (pvz. diktatura/speakers/enroll.py — katalogo vardas sutampa su duomenų
# katalogu „speakers/"). Terminų ir dydžio patikros jiems vis tiek taikomos; ne-.py failai pakete — DENY kaip visur.
ALLOW='^diktatura/([a-z0-9_]+/)*[a-z0-9_]+\.py$'

TERMS=""
if [ -f "$TERMS_FILE" ]; then
  TERMS="$(grep -vE '^[[:space:]]*(#|$)' "$TERMS_FILE" | paste -sd'|' -)"
fi
TERM_RE="(^|[^[:alnum:]_])(${TERMS})"

fail=0; warn=0
bad(){  printf '  ✗ %s\n' "$*" >&2; fail=1; }
note(){ printf '  ⚠ %s\n' "$*" >&2; warn=1; }

check_paths(){   # stdin: failų keliai
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    printf '%s\n' "$f" | grep -qE "$ALLOW" || { printf '%s\n' "$f" | grep -qiE "$DENY" && bad "draudžiamas failas (privatūs duomenys/garsas/modelis): $f"; }
    # _ . / - → tarpai: kitaip „Vardas_pastabos.md" neturėtų žodžio ribos (_ yra žodžio simbolis)
    [ -n "$TERMS" ] && printf '%s\n' "$f" | sed 's/[_./-]/ /g' | grep -qiE "$TERM_RE" && bad "asmeninis terminas failo varde: $f"
  done
  return 0
}

check_sizes(){   # $1 = objekto prefiksas (":" = index, "<rev>:" = commit); stdin: failai
  local pre="$1" f sz
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    sz=$(git cat-file -s "${pre}${f}" 2>/dev/null || echo 0)
    [ "$sz" -gt $((MAX_KB * 1024)) ] && bad "per didelis failas ($((sz / 1024)) KB > ${MAX_KB} KB): $f"
  done
  return 0
}

check_terms(){   # $@ = git diff komanda (be failo); stdin: failai
  [ -z "$TERMS" ] && return 0
  local f m
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    m=$("$@" -- "$f" 2>/dev/null | grep -E '^\+' | grep -vE '^\+\+\+ ' | sed 's/_/ /g' | grep -iE "$TERM_RE" | head -3)
    if [ -n "$m" ]; then
      bad "asmeninis terminas pridedamame tekste: $f"
      printf '%s\n' "$m" | cut -c1-160 | sed 's/^/        /' >&2
    fi
  done
  return 0
}

check_meta(){    # $1 = commit; $2 = bad|note
  [ -z "$TERMS" ] && return 0
  local meta; meta="$(git log -1 --format='%an <%ae> | %cn <%ce>' "$1")"
  if printf '%s\n' "$meta" | grep -qiE "$TERM_RE"; then
    "$2" "commit $(git rev-parse --short "$1") autorius/email atitinka privatų terminą: $meta"
    "$2" "  → sprendimas: git config user.email <ID>+<user>@users.noreply.github.com (repo lygiu)"
  fi
  return 0
}

# SVARBU: funkcijas maitinam per here-string (<<<), NE per pipe — pipe paleistų jas subshell'e ir
# `fail=1` neišliktų (sargas praneštų, bet neblokuotų). Tai pagavo tests/privacy_guard_test.sh.
mode="${1:-staged}"
case "$mode" in
  staged)
    files="$(git diff --cached --name-only --diff-filter=ACMR)"
    check_paths <<< "$files"
    check_sizes ":" <<< "$files"
    check_terms git diff --cached -U0 --diff-filter=ACMR <<< "$files"
    ;;
  commit)
    sha="${2:?reikia commit sha}"
    parent="$(git rev-parse -q --verify "${sha}^" 2>/dev/null || echo "$EMPTY_TREE")"
    files="$(git diff --name-only --diff-filter=ACMR "$parent" "$sha")"
    check_paths <<< "$files"
    check_sizes "${sha}:" <<< "$files"
    check_terms git diff -U0 --diff-filter=ACMR "$parent" "$sha" <<< "$files"
    check_meta "$sha" bad
    ;;
  audit)
    rev="${2:-HEAD}"
    files="$(git ls-tree -r --name-only "$rev")"
    check_paths <<< "$files"
    check_sizes "${rev}:" <<< "$files"
    check_terms git diff -U0 "$EMPTY_TREE" "$rev" <<< "$files"
    for c in $(git rev-list "$rev"); do check_meta "$c" note; done
    ;;
  audit-index|audit-worktree)
    if [ "$mode" = audit-worktree ]; then
      tmpidx="$(mktemp)"; trap 'rm -f "$tmpidx"' EXIT
      cp "$(git rev-parse --git-path index)" "$tmpidx" 2>/dev/null || true
      (cd "$ROOT" && GIT_INDEX_FILE="$tmpidx" git add -A . >/dev/null 2>&1)
      tree="$(GIT_INDEX_FILE="$tmpidx" git write-tree)"
    else
      tree="$(git write-tree)"
    fi
    files="$(git ls-tree -r --name-only "$tree")"
    check_paths <<< "$files"
    check_sizes "${tree}:" <<< "$files"
    check_terms git diff -U0 "$EMPTY_TREE" "$tree" <<< "$files"
    ;;
  *) echo "naudojimas: $0 staged | commit <sha> | audit [rev] | audit-index | audit-worktree" >&2; exit 2 ;;
esac

if [ "$fail" -ne 0 ]; then
  cat >&2 <<'EOF'
⛔ Diktatūra privatumo sargas: veiksmas sustabdytas.
   Failai/tekstas atrodo privatūs (įrašai, balsai, transkripcijos, modeliai, asmeniniai terminai).
   • Pašalink iš staging:   git restore --staged <failas>
   • Klaidingas suveikimas? Patikslink .private-terms arba .githooks/privacy-scan.sh
   • Apeiti --no-verify NEREKOMENDUOJAMA (pre-push vis tiek patikrins kiekvieną commit'ą).
EOF
  exit 1
fi
exit 0
