---
description: Close the day — record what happened in progress.md and journal/, then commit the hub
argument-hint: "[notes to include]"
---
Close the day. Extra notes from me: $ARGUMENTS

1. Gather what happened today in the repos of `repos.md` (list them with
   `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" repos`):
   `git -C <path> log --all --author="$(git config user.email)" --since=midnight --format='%h %s'`,
   the PRs/MRs created or updated today (`gh pr list --author @me` / `glab mr list --author=@me`),
   and the changes in `features/*.md` (`git diff` / `git log --since=midnight` in the hub).
2. Write `journal/<YYYY-MM-DD>.md` (today's absolute date): what moved, decisions taken (with
   the why), what is left for tomorrow. Short; link PRs/MRs and feature files.
3. Update `progress.md`: Now (and its "Resume here" block, written so a fresh session can act on
   it without asking), Blocked, Paused, and Done for this week. Update the decision log of every
   feature touched today. If a decision taken today outlives its feature, offer to record it with
   `/hub:decision`.
4. If the hub uses the Radar, run the `radar` skill to propose state changes and refresh `radar.md`
   (and the DORA metrics, if configured). Apply Radar changes only with my OK.
5. Show the diff summary and commit in the hub: `git add -A && git commit -m "close YYYY-MM-DD"`,
   then push if the hub has a remote.
