#!/usr/bin/env bats
# land-direct.sh (Flow direct): a local bare repo as origin, fake gh/glab for CI. No network.

refute_grep() { ! grep "$@"; }

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  export FAKE_DIR="$BATS_TEST_TMPDIR/fake"; mkdir -p "$FAKE_DIR"; : > "$FAKE_DIR/calls"
  export PATH="$ROOT/tests/fakes:$PATH"
  export HUB_POLL_SECONDS=0 HUB_NO_CHECKS_GRACE=2 HUB_MAX_WAIT_SECONDS=50
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
  T="$BATS_TEST_TMPDIR"
  git init -q --bare "$T/origin.git"
  git clone -q "$T/origin.git" "$T/repo" 2>/dev/null
  git -C "$T/repo" checkout -q -b master
  echo one > "$T/repo/a.txt"; git -C "$T/repo" add a.txt; git -C "$T/repo" commit -qm one
  git -C "$T/repo" push -q origin master
  git -C "$T/repo" worktree add -q "$T/wt" -b feat/x origin/master
  echo two > "$T/wt/b.txt"; git -C "$T/wt" add b.txt; git -C "$T/wt" commit -qm two
  TIP="$(git -C "$T/repo" rev-parse master)"
  HEAD="$(git -C "$T/wt" rev-parse HEAD)"
}

runs() {  # runs <sha> <json-array>... : one CI answer per poll (the last one repeats)
  local sha="$1"; shift; printf '%s\n' "$@" > "$FAKE_DIR/runs-commit-$sha"
}
GREEN='[{"status":"completed","conclusion":"success","url":"https://example.com/r/1"}]'
RED='[{"status":"completed","conclusion":"failure","url":"https://example.com/r/2"}]'
RUNNING='[{"status":"in_progress","conclusion":"","url":"https://example.com/r/3"}]'

land() { run "$ROOT/plugin/scripts/land-direct.sh" -C "$T/wt" --base master --forge github "$@"; }
origin_master() { git -C "$T/origin.git" rev-parse master; }

@test "lands by fast-forward when the base CI and the pushed commit's CI are green" {
  runs "$TIP" "$GREEN"
  runs "$HEAD" "[]" "$RUNNING" "$GREEN"
  land
  [ "$status" -eq 0 ]
  [ "$(origin_master)" = "$HEAD" ]
  [ "$(git -C "$T/repo" rev-parse master)" = "$TIP" ]   # the repo's own checkout is not touched
  grep -q "^gh run list .*--commit $TIP" "$FAKE_DIR/calls"
  [ "$(grep -c "^gh run list .*--commit $HEAD" "$FAKE_DIR/calls")" -eq 3 ]
  [[ "$output" == *"1 commit(s) to land"* ]]
  [[ "$output" == *"== landed"* ]]
}

@test "hub land is the same script" {
  runs "$TIP" "$GREEN"; runs "$HEAD" "$GREEN"
  run "$ROOT/bin/hub" land -C "$T/wt" --base master --forge github
  [ "$status" -eq 0 ]
  [ "$(origin_master)" = "$HEAD" ]
}

@test "refuses when the base moved (exit 2) and pushes nothing" {
  echo three > "$T/repo/c.txt"; git -C "$T/repo" add c.txt; git -C "$T/repo" commit -qm three
  git -C "$T/repo" push -q origin master
  moved="$(origin_master)"
  land
  [ "$status" -eq 2 ]
  [[ "$output" == *"master moved: rebase on origin/master"* ]]
  [ "$(origin_master)" = "$moved" ]
}

@test "refuses when the base branch CI is red (exit 3) and pushes nothing" {
  runs "$TIP" "$RED"
  land
  [ "$status" -eq 3 ]
  [[ "$output" == *"CI failure on master"*"https://example.com/r/2"* ]]
  [ "$(origin_master)" = "$TIP" ]
}

@test "waits for a running base CI before pushing" {
  runs "$TIP" "$RUNNING" "$RUNNING" "$GREEN"
  runs "$HEAD" "$GREEN"
  land
  [ "$status" -eq 0 ]
  [ "$(grep -c "^gh run list .*--commit $TIP" "$FAKE_DIR/calls")" -eq 3 ]
}

@test "reports a red CI on the pushed commit (exit 3) without rewriting history" {
  runs "$TIP" "$GREEN"
  runs "$HEAD" "$RUNNING" "$RED"
  land
  [ "$status" -eq 3 ]
  [ "$(origin_master)" = "$HEAD" ]
  [[ "$output" == *"CI failure on the pushed commit"* ]]
  refute_grep -q -- "--force" "$FAKE_DIR/calls"
}

@test "a repo without CI lands after the grace period" {
  land
  [ "$status" -eq 0 ]
  [ "$(origin_master)" = "$HEAD" ]
  [[ "$output" == *"no CI run for the pushed commit"* ]]
}

@test "dirty worktree, dry run, already landed, rejected push" {
  echo dirty >> "$T/wt/b.txt"
  land
  [ "$status" -eq 1 ]
  [[ "$output" == *"uncommitted changes"* ]]
  git -C "$T/wt" checkout -q -- b.txt

  runs "$TIP" "$GREEN"
  land --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"would push"* ]]
  [ "$(origin_master)" = "$TIP" ]

  printf '#!/bin/sh\necho "protected branch" >&2\nexit 1\n' > "$T/origin.git/hooks/pre-receive"
  chmod +x "$T/origin.git/hooks/pre-receive"
  land
  [ "$status" -eq 4 ]
  [[ "$output" == *"push rejected"*"protected branch"* ]]
  rm "$T/origin.git/hooks/pre-receive"

  runs "$HEAD" "$GREEN"
  land
  [ "$status" -eq 0 ]
  land
  [ "$status" -eq 0 ]
  [[ "$output" == *"nothing to land"* ]]
}

@test "gitlab: pipelines of the base tip and the pushed commit" {
  printf '%s\n' '[{"id":1,"status":"success","web_url":"https://example.com/p/1"}]' > "$FAKE_DIR/pipelines-sha-$TIP"
  printf '%s\n' '[{"id":2,"status":"running"}]' '[{"id":2,"status":"failed","web_url":"https://example.com/p/2"}]' > "$FAKE_DIR/pipelines-sha-$HEAD"
  run "$ROOT/plugin/scripts/land-direct.sh" -C "$T/wt" --base master --forge gitlab
  [ "$status" -eq 3 ]
  [[ "$output" == *"CI failure on the pushed commit"*"https://example.com/p/2"* ]]
  grep -q "^glab ci list --output json --sha $TIP" "$FAKE_DIR/calls"
  [ "$(origin_master)" = "$HEAD" ]
}

@test "usage errors" {
  run "$ROOT/plugin/scripts/land-direct.sh" -C "$T/wt"
  [ "$status" -eq 1 ]
  run "$ROOT/plugin/scripts/land-direct.sh" -C "$T/wt" --base master
  [ "$status" -eq 1 ]
  [[ "$output" == *"unknown forge"* ]]
}
