#!/usr/bin/env bash
# Merge PRs (GitHub) or MRs (GitLab) of one repo, in order.
# For each one: mark it ready, rebase it on the server if it is behind its base, wait for its
# pipeline/checks on the current head, merge. Stops at the first problem.
#
#   merge-seq.sh [-C <repo-path>] [--forge github|gitlab] [--method squash|rebase|merge] [--dry-run] <n> [<n> ...]
#
# Exit codes: 0 all merged · 1 usage/setup · 2 conflict or rebase failed · 3 pipeline failed or
# timed out · 4 merge failed or PR/MR closed.
# Env: HUB_POLL_SECONDS (default 20), HUB_MAX_WAIT_SECONDS (default 3600),
#      HUB_SETTLE_SECONDS (wait after a rebase, default 10), HUB_NO_CHECKS_GRACE (default 60).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLL="${HUB_POLL_SECONDS:-20}"
MAX_WAIT="${HUB_MAX_WAIT_SECONDS:-3600}"
SETTLE="${HUB_SETTLE_SECONDS:-10}"
GRACE="${HUB_NO_CHECKS_GRACE:-60}"

repo="."; forge=""; method="squash"; dry=0; nums=()
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1; }
while [ $# -gt 0 ]; do
  case "$1" in
    -C) repo="$2"; shift 2 ;;
    --forge) forge="$2"; shift 2 ;;
    --method) method="$2"; shift 2 ;;
    --dry-run) dry=1; shift ;;
    -h|--help) usage ;;
    -*) echo "unknown option $1" >&2; usage ;;
    *) nums+=("${1#[#!]}"); shift ;;
  esac
done
[ ${#nums[@]} -gt 0 ] || usage
case "$method" in squash|rebase|merge) ;; *) echo "--method must be squash, rebase or merge" >&2; exit 1 ;; esac
cd "$repo" || { echo "no such repo: $repo" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
[ -n "$forge" ] || forge="$(python3 -I "$HERE/hub.py" forge .)"

log() { printf '%s %s\n' "$(date +%T)" "$*"; }
die() { log "!! $2"; exit "$1"; }
pause() { [ "$POLL" = "0" ] || sleep "$POLL"; }

# ------------------------------------------------------------------ GitHub (gh)
gh_one() {
  local n="$1" info state draft mss waited=0 checks fail pending total out
  info="$(gh pr view "$n" --json state,isDraft,mergeStateStatus,headRefOid)" || die 4 "#$n: cannot read PR"
  state="$(jq -r .state <<<"$info")"; draft="$(jq -r .isDraft <<<"$info")"; mss="$(jq -r .mergeStateStatus <<<"$info")"
  [ "$state" = "MERGED" ] && { log "   #$n already merged"; return 0; }
  [ "$state" = "OPEN" ] || die 4 "#$n is $state"
  if [ "$dry" = 1 ]; then log "   #$n draft=$draft mergeState=$mss (dry run)"; return 0; fi
  if [ "$draft" = "true" ]; then gh pr ready "$n" >/dev/null || die 4 "#$n: cannot mark ready"; log "   ready"; fi
  if [ "$mss" = "DIRTY" ]; then die 2 "#$n has conflicts with its base"; fi
  if [ "$mss" = "BEHIND" ]; then
    out="$(gh pr update-branch "$n" --rebase 2>&1)" || die 2 "#$n rebase failed: $out"
    log "   rebased"
    [ "$SETTLE" = "0" ] || sleep "$SETTLE"
  fi
  while :; do
    checks="$(gh pr checks "$n" --json bucket 2>/dev/null)" || true
    [ -n "$checks" ] || checks="[]"
    total="$(jq length <<<"$checks")"
    fail="$(jq '[.[] | select(.bucket=="fail" or .bucket=="cancel")] | length' <<<"$checks")"
    pending="$(jq '[.[] | select(.bucket=="pending")] | length' <<<"$checks")"
    [ "$fail" = "0" ] || die 3 "#$n checks failed"
    if [ "$total" = "0" ] && [ "$waited" -ge "$GRACE" ]; then log "   no checks reported; merging"; break; fi
    if [ "$total" != "0" ] && [ "$pending" = "0" ]; then log "   checks ok"; break; fi
    [ "$waited" -lt "$MAX_WAIT" ] || die 3 "#$n checks still pending after ${MAX_WAIT}s"
    pause; waited=$((waited + POLL)); [ "$POLL" = "0" ] && waited=$((waited + 1))
  done
  out="$(gh pr merge "$n" "--$method" 2>&1)" || die 4 "#$n merge: $out"
  state="$(gh pr view "$n" --json state --jq .state)"
  [ "$state" = "MERGED" ] || die 4 "#$n is $state after merge (merge queue or branch protection?): $out"
  log "   merged $(gh pr view "$n" --json mergeCommit --jq '.mergeCommit.oid // ""' | cut -c1-8)"
}

# ------------------------------------------------------------------ GitLab (glab)
gl_proj() {
  local slug
  slug="$(python3 -I "$HERE/hub.py" slug .)"
  [ -n "$slug" ] || die 1 "cannot work out the GitLab project from the origin remote"
  jq -rn --arg s "$slug" '$s | @uri'
}
gl_api() { glab api "projects/$PROJ/$1" "${@:2}"; }

gl_one() {
  local n="$1" mr state draft behind s err st p waited=0 out
  mr="$(gl_api "merge_requests/$n?include_diverged_commits_count=true")" || die 4 "!$n: cannot read MR"
  state="$(jq -r .state <<<"$mr")"; draft="$(jq -r '.draft // .work_in_progress' <<<"$mr")"
  behind="$(jq -r '.diverged_commits_count // 0' <<<"$mr")"
  [ "$state" = "merged" ] && { log "   !$n already merged"; return 0; }
  [ "$state" = "opened" ] || die 4 "!$n is $state"
  if [ "$dry" = 1 ]; then log "   !$n draft=$draft behind=$behind (dry run)"; return 0; fi
  if [ "$draft" = "true" ]; then glab mr update "$n" --ready >/dev/null || die 4 "!$n: cannot mark ready"; log "   ready"; fi
  if [ "$(jq -r '.has_conflicts // false' <<<"$mr")" = "true" ]; then die 2 "!$n has conflicts with its base"; fi
  if [ "$behind" != "0" ] && [ "$behind" != "null" ]; then
    gl_api "merge_requests/$n/rebase" -X PUT >/dev/null || die 2 "!$n: rebase request failed"
    while :; do
      s="$(gl_api "merge_requests/$n?include_rebase_in_progress=true" | jq -r '"\(.rebase_in_progress)|\(.merge_error)"')"
      [ "${s%%|*}" = "false" ] && break
      [ "$waited" -lt "$MAX_WAIT" ] || die 2 "!$n rebase still running after ${MAX_WAIT}s"
      pause; waited=$((waited + POLL + 1))
    done
    err="${s#*|}"
    if [ "$err" != "null" ] && [ -n "$err" ]; then die 2 "!$n rebase failed: $err"; fi
    log "   rebased"
    [ "$SETTLE" = "0" ] || sleep "$SETTLE"
  fi
  waited=0
  while :; do
    st="$(gl_api "merge_requests/$n" | jq -r '"\(.head_pipeline.status)|\(.head_pipeline.sha)|\(.sha)"')"
    p="${st%%|*}"; local rest="${st#*|}"
    if [ "$p" = "null" ] && [ "$waited" -ge "$GRACE" ]; then log "   no pipeline; merging"; break; fi
    if [ "${rest%%|*}" = "${rest#*|}" ]; then
      case "$p" in
        success|skipped) log "   pipeline $p"; break ;;
        failed|canceled) die 3 "!$n pipeline $p" ;;
      esac
    fi
    [ "$waited" -lt "$MAX_WAIT" ] || die 3 "!$n pipeline still $p after ${MAX_WAIT}s"
    pause; waited=$((waited + POLL)); [ "$POLL" = "0" ] && waited=$((waited + 1))
  done
  local flag=()
  case "$method" in squash) flag=(--squash) ;; rebase) flag=(--rebase) ;; esac
  out="$(glab mr merge "$n" --yes "${flag[@]}" 2>&1)" || die 4 "!$n merge: $out"
  state="$(gl_api "merge_requests/$n" | jq -r .state)"
  [ "$state" = "merged" ] || die 4 "!$n is $state after merge: $out"
  log "   merged $(gl_api "merge_requests/$n" | jq -r '.merge_commit_sha // .squash_commit_sha // ""' | cut -c1-8)"
}

case "$forge" in
  github) command -v gh >/dev/null || die 1 "gh is not installed"; one=gh_one; sigil="#" ;;
  gitlab) command -v glab >/dev/null || die 1 "glab is not installed"; PROJ="$(gl_proj)"; one=gl_one; sigil="!" ;;
  *) die 1 "unknown forge for $(pwd); pass --forge github|gitlab" ;;
esac

for n in "${nums[@]}"; do
  log "== $sigil$n"
  "$one" "$n"
done
log "== done (${#nums[@]})"
