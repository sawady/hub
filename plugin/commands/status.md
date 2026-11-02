---
description: Standup — branches, PRs/MRs and pipelines across the hub's repos; refreshes Now in progress.md
---
Build the current state of the work.

1. List the repos: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" repos` (alias, path, base,
   forge, slug). For each one, in parallel where possible:
   - `git -C <path> fetch -q`, the current branch, uncommitted changes, unpushed commits, and
     worktrees (`git -C <path> worktree list`).
   - Your open PRs/MRs: GitHub → `gh pr list --author @me --json number,title,isDraft,reviewDecision,mergeStateStatus,statusCheckRollup,url`;
     GitLab → `glab mr list --author=@me` and `glab mr view <iid>` / `glab ci status` for each.
     Note draft or ready, the last pipeline/check state, unresolved review threads, and how far
     behind the base branch it is.
2. Compare against `progress.md` and `features/*.md`: what changed, what is stale, what merged.
3. Update **Now** (and **Blocked** if needed) in `progress.md`, the "Resume here" block and the
   "Last updated" date. Do not touch **Done** unless something merged; then move it to the current
   week with its absolute date.
4. Reply with at most 10 lines: what is ready to move, what is red, what needs a decision.
