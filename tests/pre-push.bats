#!/usr/bin/env bats
# scripts/git-hooks/pre-push, installed as documented in CONTRIBUTING.md, with made-up terms.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  T="$BATS_TEST_TMPDIR"
  unset HUB_LEAK_TERMS
  export HOME="$T/home"
  export HUB_LEAK_TERMS_FILE="$T/terms"
  printf 'acmecorp\n' > "$HUB_LEAK_TERMS_FILE"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
  git init -q --bare "$T/origin.git"
  git clone -q "$T/origin.git" "$T/r" 2>/dev/null
  git -C "$T/r" checkout -q -b main
  mkdir -p "$T/r/scripts/git-hooks"
  cp "$ROOT/scripts/check-leaks.sh" "$T/r/scripts/"
  cp "$ROOT/scripts/git-hooks/pre-push" "$T/r/scripts/git-hooks/"
  echo "Acme Books" > "$T/r/README.md"
  git -C "$T/r" add -A && git -C "$T/r" commit -qm one
  git -C "$T/r" config core.hooksPath scripts/git-hooks
}

origin_main() { git -C "$T/origin.git" rev-parse -q --verify main || echo none; }

@test "a clean history is pushed" {
  run git -C "$T/r" push -q origin main
  [ "$status" -eq 0 ]
  [ "$(origin_main)" = "$(git -C "$T/r" rev-parse main)" ]
}

@test "a hit stops the push and never prints the term" {
  git -C "$T/r" push -q origin main
  pushed="$(origin_main)"
  echo "talk to ACMECorp" > "$T/r/notes.md"
  git -C "$T/r" add notes.md && git -C "$T/r" commit -qm notes
  run git -C "$T/r" push origin main
  [ "$status" -ne 0 ]
  [[ "$output" == *"notes.md:1: term #1"* ]]
  [[ "$output" == *"push stopped"* ]]
  [[ "$output" != *"cmecorp"* ]]
  [ "$(origin_main)" = "$pushed" ]
}

@test "a hit only in the history stops the push too" {
  echo "acmecorp" > "$T/r/notes.md"
  git -C "$T/r" add notes.md && git -C "$T/r" commit -qm notes
  git -C "$T/r" rm -q notes.md && git -C "$T/r" commit -qm "drop notes"
  run git -C "$T/r" push origin main
  [ "$status" -ne 0 ]
  [[ "$output" == *"history: commit"*"term #1"* ]]
  [ "$(origin_main)" = none ]
}

@test "no term list stops the push" {
  rm "$HUB_LEAK_TERMS_FILE"
  run git -C "$T/r" push origin main
  [ "$status" -ne 0 ]
  [[ "$output" == *"no term list"* ]]
  [[ "$output" == *"exited 2; push stopped"* ]]
  [ "$(origin_main)" = none ]
}

@test "it also runs from a worktree" {
  git -C "$T/r" worktree add -q "$T/wt" -b feat/x
  echo "acmecorp" > "$T/wt/x.md"
  git -C "$T/wt" add x.md && git -C "$T/wt" commit -qm x
  run git -C "$T/wt" push origin feat/x
  [ "$status" -ne 0 ]
  [[ "$output" == *"x.md:1: term #1"* ]]
}

@test "linked from .git/hooks instead of core.hooksPath" {
  git -C "$T/r" config --unset core.hooksPath
  ln -s ../../scripts/git-hooks/pre-push "$T/r/.git/hooks/pre-push"
  run git -C "$T/r" push -q origin main
  [ "$status" -eq 0 ]
  echo "acmecorp" > "$T/r/notes.md"
  git -C "$T/r" add notes.md && git -C "$T/r" commit -qm notes
  run git -C "$T/r" push origin main
  [ "$status" -ne 0 ]
  [[ "$output" == *"push stopped"* ]]
}
