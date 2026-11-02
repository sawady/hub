#!/usr/bin/env bash
# Land a branch on its base, for repos with Flow `direct` in repos.md (no PRs/MRs).
# Run it on the worktree the work was done in. It never touches the repo's own checkout and never
# force-pushes: the base moves on the remote only by fast-forward.
#   1. fetch origin; refuse a dirty worktree, and refuse if <base> moved (HEAD must contain origin/<base>)
#   2. wait for the CI of the current tip of origin/<base>; refuse if it is red
#   3. git push origin HEAD:<base>
#   4. wait for the CI of the pushed commit; fail if it goes red (fix forward, never rewrite history)
#
#   land-direct.sh [-C <worktree>] --base <branch> [--forge github|gitlab] [--dry-run] [--no-wait]
#
# Exit codes: 0 landed (or nothing to land) · 1 usage/setup · 2 base moved, rebase needed ·
# 3 CI red, cancelled or still running at the timeout · 4 push rejected.
# Env: HUB_POLL_SECONDS (default 20), HUB_MAX_WAIT_SECONDS (default 3600),
#      HUB_NO_CHECKS_GRACE (seconds to wait for a CI run to appear after the push, default 60).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLL="${HUB_POLL_SECONDS:-20}"
MAX_WAIT="${HUB_MAX_WAIT_SECONDS:-3600}"
GRACE="${HUB_NO_CHECKS_GRACE:-60}"

repo="."; base=""; forge=""; dry=0; wait_after=1
usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1; }
while [ $# -gt 0 ]; do
  case "$1" in
    -C) repo="$2"; shift 2 ;;
    --base) base="$2"; shift 2 ;;
    --forge) forge="$2"; shift 2 ;;
    --dry-run) dry=1; shift ;;
    --no-wait) wait_after=0; shift ;;
    -h|--help) usage ;;
    *) echo "unknown argument $1" >&2; usage ;;
  esac
done
[ -n "$base" ] || usage
cd "$repo" || { echo "no such directory: $repo" >&2; exit 1; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git checkout: $repo" >&2; exit 1; }
[ -n "$forge" ] || forge="$(python3 -I "$HERE/hub.py" forge .)"
case "$forge" in github|gitlab) ;; *) echo "unknown forge for $(pwd); pass --forge github|gitlab" >&2; exit 1 ;; esac

log() { printf '%s %s\n' "$(date +%T)" "$*"; }
die() { log "!! $2"; exit "$1"; }
pause() { [ "$POLL" = "0" ] || sleep "$POLL"; }

# ci_gate <sha> <label> <grace>: returns when the CI of <sha> is green (or there is none after
# <grace> seconds); exits 3 when it is red, cancelled or still running at the timeout.
ci_gate() {
  local sha="$1" label="$2" grace="$3" waited=0 out state url
  while :; do
    out="$(python3 -I "$HERE/hub.py" ci-state . --sha "$sha" --forge "$forge")"
    state="${out%%$'\t'*}"; url="${out#*$'\t'}"
    case "$state" in
      success) log "   CI green on $label ${url}"; return 0 ;;
      manual) log "   CI on $label waits on a manual job; treating it as green ${url}"; return 0 ;;
      failure|cancelled) die 3 "CI $state on $label ${url}" ;;
      unknown) die 1 "cannot read the CI of $label (is the forge CLI installed and authenticated?)" ;;
      none) if [ "$waited" -ge "$grace" ]; then log "   no CI run for $label; going on"; return 0; fi ;;
    esac
    [ "$waited" -lt "$MAX_WAIT" ] || die 3 "CI on $label still $state after ${MAX_WAIT}s ${url}"
    pause; waited=$((waited + POLL)); [ "$POLL" = "0" ] && waited=$((waited + 1))
  done
}

[ -z "$(git status --porcelain --untracked-files=no)" ] || die 1 "uncommitted changes in $(pwd); commit them first"
git fetch -q origin "$base" || die 1 "cannot fetch origin/$base"
head="$(git rev-parse HEAD)"; tip="$(git rev-parse "origin/$base")"
log "== landing $(git rev-parse --abbrev-ref HEAD) ${head:0:8} on $base (${tip:0:8}), $forge"
if git merge-base --is-ancestor "$head" "$tip"; then log "   already on $base; nothing to land"; exit 0; fi
git merge-base --is-ancestor "$tip" "$head" || die 2 "$base moved: rebase on origin/$base, rerun the checks and try again"
log "   $(git rev-list --count "$tip..$head") commit(s) to land, fast-forward"

ci_gate "$tip" "$base (${tip:0:8})" 0
if [ "$dry" = 1 ]; then log "   would push ${head:0:8} to origin/$base (dry run)"; exit 0; fi

out="$(git push origin "HEAD:refs/heads/$base" 2>&1)" || die 4 "push rejected: $out"
log "   pushed ${head:0:8} to origin/$base"
git fetch -q origin "$base" || true
if [ "$wait_after" = 1 ]; then
  ci_gate "$head" "the pushed commit ${head:0:8}" "$GRACE"
fi
log "== landed"
