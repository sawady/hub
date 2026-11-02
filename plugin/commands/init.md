---
description: Create a new hub (CLAUDE.md, progress.md, repos.md, features/, journal/, research/) from the template
argument-hint: "[dir] [--name NAME] [--owner OWNER] [--lang en|es]"
---
Create a hub with: $ARGUMENTS

1. If no directory was given, use the current project directory, but only if it does not already
   have `progress.md` or `repos.md`; otherwise ask where to create it. A hub is its own git repo,
   usually a sibling of the repos it drives (`~/work/hub` next to `~/work/<repo>`).
2. Ask, in one message, only what is missing: the hub name, the owner (a person or team, used in
   CLAUDE.md), and whether notes should be in English or Spanish (`--lang es` uses Spanish headings
   in progress.md; the commands understand both).
3. Run `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" init <dir> --name <name> --owner <owner> --lang <lang>`.
4. Offer to add the repos now. For each one the user names, run
   `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" add-repo <alias> <path> --base <branch> --about "<what it is>" --checks "<command>"`
   from the hub directory. Infer base branch, stack and check commands from each repo
   (`git -C <path> symbolic-ref refs/remotes/origin/HEAD`, its README / CLAUDE.md / package files)
   and show them before writing.
5. Run `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" doctor` from the hub and report problems
   (missing checkouts, unknown forge, `gh` / `glab` not authenticated).
6. If the directory is not a git repo yet, `git init` it and propose a first commit. Do not create
   a remote without asking.
