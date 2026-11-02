#!/usr/bin/env bats
# check-leaks.sh with made-up terms.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  R="$BATS_TEST_TMPDIR/r"
  git init -q "$R"
  printf 'acmecorp\n=zed\n# a comment\n\n' > "$BATS_TEST_TMPDIR/terms"
  unset HUB_LEAK_TERMS
  export HOME="$BATS_TEST_TMPDIR/home"
}

commit() { git -C "$R" add -A && git -C "$R" -c user.email=t@example.com -c user.name=t commit -qm "${1:-c}"; }

@test "clean tree passes" {
  echo "nothing to see" > "$R/a.md"
  run "$ROOT/scripts/check-leaks.sh" --terms "$BATS_TEST_TMPDIR/terms" "$R"
  [ "$status" -eq 0 ]
  [[ "$output" == *"clean (2 terms)"* ]]
}

@test "substring terms are found case-insensitively, and the term is never printed" {
  printf 'line one\nwe use ACMECorp internally\n' > "$R/a.md"
  run "$ROOT/scripts/check-leaks.sh" --terms "$BATS_TEST_TMPDIR/terms" "$R"
  [ "$status" -eq 1 ]
  [[ "$output" == *"a.md:2: term #1"* ]]
  [[ "$output" != *"cmecorp"* ]]
  [[ "$output" != *"internally"* ]]
}

@test "=terms match whole words only" {
  printf 'zedonk and amazed\n' > "$R/a.md"
  run "$ROOT/scripts/check-leaks.sh" --terms "$BATS_TEST_TMPDIR/terms" "$R"
  [ "$status" -eq 0 ]
  printf 'ask Zed.\n' > "$R/b.md"
  run "$ROOT/scripts/check-leaks.sh" --terms "$BATS_TEST_TMPDIR/terms" "$R"
  [ "$status" -eq 1 ]
  [[ "$output" == *"b.md:1: term #2"* ]]
}

@test "terms can come from HUB_LEAK_TERMS (CI secret)" {
  echo "hello acmecorp" > "$R/a.md"
  HUB_LEAK_TERMS=$'acmecorp' run "$ROOT/scripts/check-leaks.sh" "$R"
  [ "$status" -eq 1 ]
}

@test "ignored files are not scanned" {
  echo "secret.txt" > "$R/.gitignore"
  echo "acmecorp" > "$R/secret.txt"
  run "$ROOT/scripts/check-leaks.sh" --terms "$BATS_TEST_TMPDIR/terms" "$R"
  [ "$status" -eq 0 ]
}

@test "--history finds terms in old commits, messages and identities" {
  echo "acmecorp" > "$R/a.md"; commit
  echo "fine" > "$R/a.md"; commit "talk to zed"
  run "$ROOT/scripts/check-leaks.sh" --terms "$BATS_TEST_TMPDIR/terms" "$R"
  [ "$status" -eq 0 ]
  run "$ROOT/scripts/check-leaks.sh" --history --terms "$BATS_TEST_TMPDIR/terms" "$R"
  [ "$status" -eq 1 ]
  [[ "$output" == *"history: commit"*"term #1"* ]]
  [[ "$output" == *"history: commit"*"term #2"* ]]
}

@test "missing term list exits 2, or 0 with --allow-missing" {
  run "$ROOT/scripts/check-leaks.sh" "$R"
  [ "$status" -eq 2 ]
  run "$ROOT/scripts/check-leaks.sh" --allow-missing "$R"
  [ "$status" -eq 0 ]
}
