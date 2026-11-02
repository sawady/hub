#!/usr/bin/env bash
# Scan the repo for terms that must never be published (names of people, companies, internal
# hosts, ids). The list lives OUTSIDE the repo so the list itself does not leak:
#   1. $HUB_LEAK_TERMS            newline-separated terms (in CI: a repository secret)
#   2. --terms FILE / $HUB_LEAK_TERMS_FILE
#   3. ~/.config/hub/leak-terms.txt
# Format: one term per line, case-insensitive. `=term` matches whole words only (use it for
# short names); anything else matches as a substring. Blank lines and `#` comments are ignored.
#
# Reports only "path:line: term #N" — never the term or the matching text, so CI logs stay clean.
#
#   scripts/check-leaks.sh [--history] [--terms FILE] [--allow-missing] [DIR]
#     --history        also scan every commit: patches, messages, author and committer identity
#     --allow-missing  exit 0 (with a warning) when no term list is available
# Exit: 0 clean · 1 hits · 2 no term list
set -euo pipefail

history=0; allow_missing=0; terms_file="${HUB_LEAK_TERMS_FILE:-$HOME/.config/hub/leak-terms.txt}"; dir="."
while [ $# -gt 0 ]; do
  case "$1" in
    --history) history=1; shift ;;
    --allow-missing) allow_missing=1; shift ;;
    --terms) terms_file="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) dir="$1"; shift ;;
  esac
done
cd "$dir"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
if [ -n "${HUB_LEAK_TERMS:-}" ]; then
  printf '%s\n' "$HUB_LEAK_TERMS" > "$tmp/terms"
elif [ -f "$terms_file" ]; then
  cp "$terms_file" "$tmp/terms"
else
  if [ "$allow_missing" = 1 ]; then echo "check-leaks: no term list (set HUB_LEAK_TERMS or $terms_file); skipped" >&2; exit 0; fi
  echo "check-leaks: no term list (set HUB_LEAK_TERMS or create $terms_file)" >&2; exit 2
fi
# normalize: strip CR, comments, surrounding blanks; drop empty lines
sed -e 's/\r$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$tmp/terms" | grep -v -e '^#' -e '^$' > "$tmp/list" || true
n_terms="$(wc -l < "$tmp/list" | tr -d ' ')"
if [ "$n_terms" = 0 ]; then echo "check-leaks: the term list is empty" >&2; exit 2; fi

# files of the working tree: tracked plus untracked-but-not-ignored (or everything outside git)
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git ls-files -z -co --exclude-standard > "$tmp/all"
else
  find . -type f -not -path './.git/*' -print0 > "$tmp/all"
fi
# keep only files that exist (deleted-but-tracked files are skipped)
while IFS= read -r -d '' f; do [ -f "$f" ] && printf '%s\0' "$f"; done < "$tmp/all" > "$tmp/files"

flags_for() {  # flags_for <term> -> sets $pat and $w
  if [ "${1:0:1}" = "=" ]; then pat="${1:1}"; w="-w"; else pat="$1"; w=""; fi
}

hits=0; i=0
while IFS= read -r term; do
  i=$((i + 1))
  flags_for "$term"
  # -o prints only the match, cut keeps path:line, so the matched text never reaches the output
  xargs -0 -r grep -I -n -i -F -o -H ${w:+"$w"} -e "$pat" < "$tmp/files" 2>/dev/null | cut -d: -f1,2 | sort -u > "$tmp/hit" || true
  while IFS= read -r loc; do
    echo "$loc: term #$i"; hits=$((hits + 1))
  done < "$tmp/hit"
done < "$tmp/list"

if [ "$history" = 1 ] && git rev-parse --verify -q HEAD >/dev/null 2>&1; then
  git log --all -p --no-color --format='commit %H%n%an <%ae>%n%cn <%ce>%n%B' > "$tmp/history"
  grep -n '^commit [0-9a-f]\{40\}$' "$tmp/history" | sed 's/:commit / /' > "$tmp/commits" || true
  i=0
  while IFS= read -r term; do
    i=$((i + 1))
    flags_for "$term"
    { grep -I -n -i -F ${w:+"$w"} -e "$pat" "$tmp/history" || true; } | cut -d: -f1 |
      awk -v t="$i" 'NR==FNR { line[NR]=$1; sha[NR]=$2; n=NR; next }
           { s=""; for (k=1; k<=n; k++) { if (line[k] <= $1) s=sha[k]; else break }
             if (!(s in seen)) { seen[s]=1; print "history: commit " substr(s,1,12) ": term #" t } }' "$tmp/commits" - > "$tmp/h" || true
    if [ -s "$tmp/h" ]; then cat "$tmp/h"; hits=$((hits + $(wc -l < "$tmp/h"))); fi
  done < "$tmp/list"
fi

if [ "$hits" -gt 0 ]; then
  echo "check-leaks: $hits hit(s) for $n_terms term(s). Fix them before pushing." >&2
  exit 1
fi
echo "check-leaks: clean ($n_terms terms$([ "$history" = 1 ] && echo ', with history'))"
