---
description: Add a repo to the hub (repos.md row, per-repo agent, allowed directory)
argument-hint: "<alias> <path> [what it is]"
---
Add the repo `$1` at `$2` to this hub. Extra context: $ARGUMENTS

1. Check that `$2` (relative to the hub) is a git checkout. Infer from it, and show before writing:
   the base branch (`git -C $2 symbolic-ref --short refs/remotes/origin/HEAD`), the forge (from the
   `origin` remote: GitHub or GitLab), the stack, and the check commands (lint, type-check, tests)
   from its README, CLAUDE.md / AGENTS.md, package.json, Makefile, pyproject, etc.
2. Run from the hub:
   `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" add-repo $1 $2 --base <base> --about "<what it is>" --checks "<checks>"`.
   It adds the row to `repos.md`, creates `.claude/agents/$1.md` and allows the path in
   `.claude/settings.json`.
3. Read the repo's CLAUDE.md / AGENTS.md and fill the "easy to break" list in
   `.claude/agents/$1.md` with the 3-6 rules that matter most (generated code, how to run things,
   where its docs live). Keep it short; the repo's own docs stay the reference.
4. Add anything worth knowing across repos to the "Notes per repo" section of `repos.md`.
