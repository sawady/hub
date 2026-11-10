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
  HUB_SKIP_CI=1 HUB_SKIP_PRS=1 run "$ROOT/bin/hub" context
  [ "$status" -eq 0 ]
  [[ "$output" == *"(Now and Blocked are empty)"* ]]   # the template's placeholders are not state
  [[ "$output" != *"<feature or task>"* ]]
  [[ "$output" != *"YYYY-MM-DD"* ]]
  printf '## Now\n\n- saved-carts — API PR in review\n\n## Blocked\n\n- <item> — blocked on <who/what>, since YYYY-MM-DD\n' > progress.md
  run "$ROOT/bin/hub" context
  [ "$status" -eq 0 ]
  [[ "$output" == *"- saved-carts — API PR in review"* ]]
  [[ "$output" != *"<item>"* ]]
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

@test "flow direct, red CI in the context, ci --red" {
  "$ROOT/bin/hub" init "$W/hq" >/dev/null
  cd "$W/hq"
  "$ROOT/bin/hub" add-repo orders-api ../orders-api >/dev/null
  run "$ROOT/bin/hub" add-repo storefront ../storefront --base master --flow direct
  [ "$status" -eq 0 ]
  [[ "$output" == "| storefront | \`../storefront\` | master | direct | gitlab |"* ]]
  run "$ROOT/bin/hub" repos
  [[ "$output" == *$'\tmain\tgithub\tacme/orders-api\tpr'* ]]
  [[ "$output" == *$'\tmaster\tgitlab\tacme/web/storefront\tdirect'* ]]
  grep -q 'Flow `direct`' .claude/agents/storefront.md
  echo '[{"status":"completed","conclusion":"success","workflowName":"ci","url":"u"}]' > "$FAKE_DIR/runs-branch-main.json"
  echo '[{"id":5,"status":"failed","web_url":"https://example.com/p/5"}]' > "$FAKE_DIR/pipelines-ref-master.json"
  run "$ROOT/bin/hub" context
  [ "$status" -eq 0 ]
  [[ "$output" == *"## Red CI"*"- storefront (master): failed — pipeline 5 — https://example.com/p/5"* ]]
  [[ "$output" != *"orders-api (main)"* ]]
  run "$ROOT/bin/hub" ci --red
  [ "$status" -eq 0 ]
  [ "$output" = $'storefront\tmaster\tfailure\tpipeline 5\thttps://example.com/p/5' ]
  HUB_SKIP_CI=1 run "$ROOT/bin/hub" context
  [[ "$output" != *"Red CI"* ]]
  run "$ROOT/bin/hub" context --no-ci --no-prs
  [[ "$output" != *"Red CI"* && "$output" != *"open PRs"* ]]
}

@test "new-decision numbers decisions and supersedes without rewriting" {
  "$ROOT/bin/hub" init "$W/hq" --lang es >/dev/null
  cd "$W/hq"
  run "$ROOT/bin/hub" new-decision "Trabajo directo en main"
  [ "$status" -eq 0 ]
  [ "$output" = "decisions/0001-trabajo-directo-en-main.md" ]
  grep -q "^# 0001 — Trabajo directo en main$" decisions/0001-trabajo-directo-en-main.md
  grep -q "^- \*\*Fecha:\*\* $(date +%F)$" decisions/0001-trabajo-directo-en-main.md
  run "$ROOT/bin/hub" new-decision "Volver a PRs" --supersedes 1
  [ "$output" = "decisions/0002-volver-a-prs.md" ]
  grep -q "Reemplazada por \[0002\](0002-volver-a-prs.md)" decisions/0001-trabajo-directo-en-main.md
  run "$ROOT/bin/hub" new-decision "x" --supersedes 7
  [ "$status" -ne 0 ]
}

@test "portfolio: one line per repo, json, and the marked block of a file" {
  "$ROOT/bin/hub" init "$W/hq" >/dev/null
  cd "$W/hq"
  "$ROOT/bin/hub" add-repo orders-api ../orders-api >/dev/null
  "$ROOT/bin/hub" add-repo storefront ../storefront --base develop >/dev/null
  cat > progress.md <<'MD'
# Progress

## Now

- **orders-api** — saved carts in review — next: merge #41

## Next

- storefront — dark mode
MD
  run "$ROOT/bin/hub" portfolio
  [ "$status" -eq 0 ]
  [ "${lines[0]}" = "| Project | Repo | State | Next step |" ]
  [ "${lines[2]}" = '| orders-api | `acme/orders-api` | saved carts in review | merge #41 |' ]
  [ "${lines[3]}" = '| storefront | `acme/web/storefront` | queued | dark mode |' ]
  [ "${#lines[@]}" -eq 4 ]
  run "$ROOT/bin/hub" portfolio --json
  [ "$status" -eq 0 ]
  [ "$(printf '%s' "$output" | jq -r '.[1].repo')" = "acme/web/storefront" ]
  [ ! -s "$FAKE_DIR/calls" ]  # the portfolio asks no forge
  printf '# Hub\n\n<!-- hub:portfolio -->\nstale\n<!-- /hub:portfolio -->\n\nKeep this.\n' > README.md
  run "$ROOT/bin/hub" portfolio --update README.md
  [ "$status" -eq 0 ]
  [ "$(grep -c stale README.md)" -eq 0 ]
  grep -q '^| orders-api | ' README.md
  grep -q '^Keep this.$' README.md
}

@test "portfolio --update needs the markers; outside a hub it fails" {
  "$ROOT/bin/hub" init "$W/hq" >/dev/null
  cd "$W/hq"
  echo "# Hub" > README.md
  run "$ROOT/bin/hub" portfolio --update README.md
  [ "$status" -ne 0 ]
  [[ "$output" == *"hub:portfolio"* ]]
  [ "$(cat README.md)" = "# Hub" ]
  cd "$BATS_TEST_TMPDIR"
  run "$ROOT/bin/hub" portfolio
  [ "$status" -eq 1 ]
}

@test "--hub works on a hub from outside it, and refuses a directory that is not one" {
  "$ROOT/bin/hub" init "$BATS_TEST_TMPDIR/h" --name h >/dev/null
  git init -q "$BATS_TEST_TMPDIR/app"
  git -C "$BATS_TEST_TMPDIR/app" remote add origin git@github.com:acme/app.git
  cd "$BATS_TEST_TMPDIR"
  run "$ROOT/bin/hub" --hub "$BATS_TEST_TMPDIR/h" add-repo app ../app
  [ "$status" -eq 0 ]
  grep -q '| app | `../app` |' "$BATS_TEST_TMPDIR/h/repos.md"
  run "$ROOT/bin/hub" --hub "$BATS_TEST_TMPDIR/h" repos
  [ "$status" -eq 0 ]
  [[ "$output" == app$'\t'"$BATS_TEST_TMPDIR/app"* ]]
  mkdir "$BATS_TEST_TMPDIR/plain"
  run "$ROOT/bin/hub" --hub "$BATS_TEST_TMPDIR/plain" repos
  [ "$status" -eq 1 ]
  [[ "$output" == *"is not a hub"* ]]
}
