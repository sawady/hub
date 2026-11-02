#!/usr/bin/env bats
# bin/hub end to end: init a hub, add repos, list them, build the session context.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  W="$BATS_TEST_TMPDIR/work"
  mkdir -p "$W"
  git init -q "$W/orders-api" && git -C "$W/orders-api" remote add origin git@github.com:acme/orders-api.git
  git init -q "$W/storefront" && git -C "$W/storefront" remote add origin https://gitlab.com/acme/web/storefront.git
  export FAKE_DIR="$BATS_TEST_TMPDIR/fake"; mkdir -p "$FAKE_DIR"; : > "$FAKE_DIR/calls"
  export PATH="$ROOT/tests/fakes:$PATH"
  unset CLAUDE_PROJECT_DIR
}

@test "help" {
  run "$ROOT/bin/hub" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"hub init"* ]]
}

@test "init, add-repo, repos, context" {
  run "$ROOT/bin/hub" init "$W/hq" --name acme-hub --owner "the web team"
  [ "$status" -eq 0 ]
  [ -f "$W/hq/CLAUDE.md" ] && [ -f "$W/hq/progress.md" ] && [ -f "$W/hq/features/_template.md" ]
  grep -q "acme-hub — engineering hub of the web team" "$W/hq/CLAUDE.md"
  cd "$W/hq"
  run "$ROOT/bin/hub" add-repo orders-api ../orders-api --about "Orders API" --checks "make test"
  [ "$status" -eq 0 ]
  run "$ROOT/bin/hub" add-repo storefront ../storefront --base develop
  [ "$status" -eq 0 ]
  [ -f .claude/agents/orders-api.md ] && [ -f .claude/agents/storefront.md ]
  run "$ROOT/bin/hub" repos
  [ "$status" -eq 0 ]
  [[ "$output" == *$'orders-api\t'*$'\tmain\tgithub\tacme/orders-api'* ]]
  [[ "$output" == *$'storefront\t'*$'\tdevelop\tgitlab\tacme/web/storefront'* ]]
  echo '[{"number":41,"title":"Saved carts API","isDraft":true,"url":"u","headRefName":"feat/saved-carts"}]' > "$FAKE_DIR/pr-list.json"
  echo '[{"iid":17,"title":"Saved carts page","draft":false,"web_url":"u","source_branch":"feat/saved-carts"}]' > "$FAKE_DIR/mr-list.json"
  run "$ROOT/bin/hub" context
  [ "$status" -eq 0 ]
  [[ "$output" == *"## Now"* ]]
  [[ "$output" == *"## Blocked"* ]]
  [[ "$output" != *"## Done"* ]]
  [[ "$output" == *"#41 Saved carts API [draft]"* ]]
  [[ "$output" == *"!17 Saved carts page"* ]]
}

@test "context is silent outside a hub" {
  cd "$BATS_TEST_TMPDIR"
  run "$ROOT/bin/hub" context
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "init refuses to overwrite an existing hub" {
  "$ROOT/bin/hub" init "$W/hq" >/dev/null
  run "$ROOT/bin/hub" init "$W/hq"
  [ "$status" -ne 0 ]
}

@test "doctor reports a missing checkout" {
  "$ROOT/bin/hub" init "$W/hq" >/dev/null
  cd "$W/hq"
  "$ROOT/bin/hub" add-repo ghost ../ghost --forge github >/dev/null
  run "$ROOT/bin/hub" doctor
  [ "$status" -eq 1 ]
  [[ "$output" == *"ghost"*"missing checkout"* ]]
}
