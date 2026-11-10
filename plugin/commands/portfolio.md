---
description: One line per project — project, repo, state and next step, from repos.md and progress.md
argument-hint: "[--update README.md]"
---
Show the portfolio of this hub: $ARGUMENTS

1. Run from the hub: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" portfolio $ARGUMENTS`. It
   prints a markdown table with one line per repo in `repos.md`, in that order. It reads
   `progress.md` and asks no forge: for each repo it takes the bullet of Now, Blocked, Next or
   Paused that starts with the repo's alias, or else the first one that mentions it. In a bullet,
   the text after `next:` (or `próximo:`) is the next step.
2. Show the table as it is. Do not fill the cells that come out as `—` by guessing: list those
   repos below the table and say that `progress.md` has nothing on them. Propose a bullet for
   each only if I ask.
3. Run `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" ci --red` and name the repos with a red
   base branch below the table, one line each.
4. `--update <file>` also rewrites the block between the lines `<!-- hub:portfolio -->` and
   `<!-- /hub:portfolio -->` of that file, usually `README.md`, and nothing else in it. If the
   markers are missing, tell me where you would add them and wait for my OK. Do not commit: the
   README follows `progress.md`, so fix a wrong line there and run this again, never the other way around.
