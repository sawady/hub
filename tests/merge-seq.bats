#!/usr/bin/env bats
# merge-seq.sh against fake gh/glab (tests/fakes): no network, no real forge.

refute_grep() { ! grep -q "$@"; }

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  export FAKE_DIR="$BATS_TEST_TMPDIR/fake"
  mkdir -p "$FAKE_DIR"
  : > "$FAKE_DIR/calls"
  export PATH="$ROOT/tests/fakes:$PATH"
  export HUB_POLL_SECONDS=0 HUB_SETTLE_SECONDS=0 HUB_NO_CHECKS_GRACE=2 HUB_MAX_WAIT_SECONDS=50
  REPO="$BATS_TEST_TMPDIR/repo"
  git init -q "$REPO"
}

gh_pr() {  # gh_pr <n> <isDraft> <mergeStateStatus> [state]
  printf '{"state":"%s","isDraft":%s,"mergeStateStatus":"%s","headRefOid":"abc"}\n' "${4:-OPEN}" "$2" "$3" > "$FAKE_DIR/view-$1.json"
}

@test "github: draft and behind PR is marked ready, rebased, waits for checks and merges" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 7 true BEHIND
  printf '%s\n' '[{"bucket":"pending"}]' '[{"bucket":"pass"},{"bucket":"skipping"}]' > "$FAKE_DIR/checks-7"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 7
  [ "$status" -eq 0 ]
  grep -q '^gh pr ready 7$' "$FAKE_DIR/calls"
  grep -q '^gh pr update-branch 7 --rebase$' "$FAKE_DIR/calls"
  grep -q '^gh pr merge 7 --squash$' "$FAKE_DIR/calls"
  [ "$(grep -c '^gh pr checks 7' "$FAKE_DIR/calls")" -eq 2 ]
  [[ "$output" == *"merged abcdef01"* ]]
}

@test "github: --method rebase is passed to gh pr merge" {
  git -C "$REPO" remote add origin https://github.com/acme/app.git
  gh_pr 3 false CLEAN
  echo '[{"bucket":"pass"}]' > "$FAKE_DIR/checks-3"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" --method rebase "#3"
  [ "$status" -eq 0 ]
  grep -q '^gh pr merge 3 --rebase$' "$FAKE_DIR/calls"
}

@test "github: failing checks stop with exit 3 and nothing is merged" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 7 false CLEAN
  gh_pr 8 false CLEAN
  echo '[{"bucket":"pass"},{"bucket":"fail"}]' > "$FAKE_DIR/checks-7"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 7 8
  [ "$status" -eq 3 ]
  refute_grep 'pr merge' "$FAKE_DIR/calls"
  refute_grep ' 8' "$FAKE_DIR/calls"
}

@test "github: conflicts stop with exit 2" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 5 false DIRTY
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 5
  [ "$status" -eq 2 ]
}

@test "github: a failed rebase stops with exit 2" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 5 false BEHIND
  echo 1 > "$FAKE_DIR/update-exit"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 5
  [ "$status" -eq 2 ]
}

@test "github: already merged PRs are skipped" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 4 false CLEAN MERGED
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 4
  [ "$status" -eq 0 ]
  [[ "$output" == *"already merged"* ]]
}

@test "github: no checks at all merges after the grace period" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 9 false CLEAN
  echo NONE > "$FAKE_DIR/checks-9"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 9
  [ "$status" -eq 0 ]
  [[ "$output" == *"no checks reported"* ]]
}

@test "github: a gh error while reading checks never counts as no checks" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 9 false CLEAN
  printf '%s\n' ERROR ERROR ERROR ERROR '[{"bucket":"fail"}]' > "$FAKE_DIR/checks-9"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 9
  [ "$status" -eq 3 ]
  refute_grep 'pr merge' "$FAKE_DIR/calls"
}

@test "github: checks that stay unreadable time out with exit 3 and nothing is merged" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 9 false CLEAN
  echo ERROR > "$FAKE_DIR/checks-9"
  HUB_MAX_WAIT_SECONDS=3 run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 9
  [ "$status" -eq 3 ]
  refute_grep 'pr merge' "$FAKE_DIR/calls"
}

@test "github: UNKNOWN merge state is polled, so a conflict after the previous merge is exit 2" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 5 false UNKNOWN
  printf '%s\n' UNKNOWN UNKNOWN DIRTY > "$FAKE_DIR/mss-5"
  echo '[{"bucket":"pass"}]' > "$FAKE_DIR/checks-5"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 5
  [ "$status" -eq 2 ]
  refute_grep 'pr merge' "$FAKE_DIR/calls"
}

@test "github: UNKNOWN that settles on BEHIND is rebased before merging" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 5 false UNKNOWN
  printf '%s\n' UNKNOWN BEHIND CLEAN > "$FAKE_DIR/mss-5"
  echo '[{"bucket":"pass"}]' > "$FAKE_DIR/checks-5"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 5
  [ "$status" -eq 0 ]
  grep -q '^gh pr update-branch 5 --rebase$' "$FAKE_DIR/calls"
  grep -q '^gh pr merge 5 --squash$' "$FAKE_DIR/calls"
}

@test "github: base moving during the checks rebases and waits again" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 5 false CLEAN
  printf '%s\n' BEHIND CLEAN > "$FAKE_DIR/mss-5"
  echo '[{"bucket":"pass"}]' > "$FAKE_DIR/checks-5"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 5
  [ "$status" -eq 0 ]
  [ "$(grep -c '^gh pr update-branch 5' "$FAKE_DIR/calls")" -eq 1 ]
  [ "$(grep -c '^gh pr checks 5' "$FAKE_DIR/calls")" -eq 2 ]
}

@test "github: a base that keeps moving stops with exit 2" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 5 false CLEAN
  echo BEHIND > "$FAKE_DIR/mss-5"
  echo '[{"bucket":"pass"}]' > "$FAKE_DIR/checks-5"
  HUB_MAX_REBASES=2 run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 5
  [ "$status" -eq 2 ]
  [ "$(grep -c '^gh pr update-branch 5' "$FAKE_DIR/calls")" -eq 2 ]
  refute_grep 'pr merge' "$FAKE_DIR/calls"
}

@test "github: a merge rejected for conflicts is exit 2" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 5 false CLEAN
  printf '%s\n' CLEAN DIRTY > "$FAKE_DIR/mss-5"
  echo '[{"bucket":"pass"}]' > "$FAKE_DIR/checks-5"
  touch "$FAKE_DIR/merge-conflict-5"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 5
  [ "$status" -eq 2 ]
}

@test "github: a draft with conflicts is left as a draft" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 5 true DIRTY
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 5
  [ "$status" -eq 2 ]
  refute_grep 'pr ready' "$FAKE_DIR/calls"
}

@test "github: dry run touches nothing" {
  git -C "$REPO" remote add origin git@github.com:acme/app.git
  gh_pr 7 true BEHIND
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" --dry-run 7
  [ "$status" -eq 0 ]
  refute_grep -e 'pr ready' -e 'update-branch' -e 'pr merge' "$FAKE_DIR/calls"
}

@test "gitlab: draft and diverged MR is readied, rebased on the server, waits for the pipeline and merges" {
  git -C "$REPO" remote add origin git@gitlab.com:acme/platform/api.git
  echo '{"state":"opened","draft":true,"diverged_commits_count":3}' > "$FAKE_DIR/mr-12.json"
  printf '%s\n' '{"rebase_in_progress":true,"merge_error":null}' '{"rebase_in_progress":false,"merge_error":null}' > "$FAKE_DIR/rebase-12"
  printf '%s\n' running success > "$FAKE_DIR/pipeline-12"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" '!12'
  [ "$status" -eq 0 ]
  grep -q '^glab mr update 12 --ready$' "$FAKE_DIR/calls"
  grep -q 'projects/acme%2Fplatform%2Fapi/merge_requests/12/rebase -X PUT' "$FAKE_DIR/calls"
  grep -q '^glab mr merge 12 --yes --squash$' "$FAKE_DIR/calls"
  [[ "$output" == *"merged 01234567"* ]]
}

@test "gitlab: a rebase error stops with exit 2" {
  git -C "$REPO" remote add origin https://gitlab.com/acme/api.git
  echo '{"state":"opened","draft":false,"diverged_commits_count":1}' > "$FAKE_DIR/mr-2.json"
  echo '{"rebase_in_progress":false,"merge_error":"conflict"}' > "$FAKE_DIR/rebase-2"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 2
  [ "$status" -eq 2 ]
  refute_grep 'mr merge' "$FAKE_DIR/calls"
}

@test "gitlab: a failed pipeline stops with exit 3" {
  git -C "$REPO" remote add origin https://gitlab.com/acme/api.git
  echo '{"state":"opened","draft":false,"diverged_commits_count":0}' > "$FAKE_DIR/mr-2.json"
  printf '%s\n' pending failed > "$FAKE_DIR/pipeline-2"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 2
  [ "$status" -eq 3 ]
  refute_grep 'mr merge' "$FAKE_DIR/calls"
}

@test "gitlab: --method merge passes no squash/rebase flag" {
  git -C "$REPO" remote add origin https://gitlab.com/acme/api.git
  echo '{"state":"opened","draft":false,"diverged_commits_count":0}' > "$FAKE_DIR/mr-2.json"
  echo success > "$FAKE_DIR/pipeline-2"
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" --method merge 2
  [ "$status" -eq 0 ]
  grep -q '^glab mr merge 2 --yes$' "$FAKE_DIR/calls"
}

@test "unknown forge without --forge fails with exit 1" {
  git -C "$REPO" remote add origin git@git.example.org:acme/api.git
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO" 1
  [ "$status" -eq 1 ]
}

@test "usage error without numbers" {
  run "$ROOT/plugin/scripts/merge-seq.sh" -C "$REPO"
  [ "$status" -eq 1 ]
}
