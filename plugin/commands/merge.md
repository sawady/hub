---
description: Merge a list of PRs/MRs in order — mark ready, rebase when behind, wait for the pipeline, merge
argument-hint: "<alias> <pr-or-mr-number> [<number> ...] [--method squash|rebase|merge] [--delete-branch]"
---
Merge in order, in repo `$1`: $ARGUMENTS

1. This merges to a base branch: only proceed if I explicitly asked to merge these numbers in this
   message or the previous one. Otherwise list what would be merged and ask.
2. Resolve the repo path, forge and flow with `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" repos`.
   Check the order against the feature's merge order (`features/*.md`): producers first.
   If `$1` has Flow `direct`, it has no PRs/MRs: do not run merge-seq. Check whether the
   feature's branch already landed (`git -C <path> fetch -q origin && git -C <path> merge-base --is-ancestor <branch> origin/<base>`).
   If it did, record it and go on with the next repo in the merge order; if a worktree branch is
   still waiting, offer to land it with `land-direct.sh` as in `/hub:e2e` step 6 (explicit OK,
   base CI green) instead of merging.
3. Run `"${CLAUDE_PLUGIN_ROOT}/scripts/merge-seq.sh" -C <path> [--method <m>] [--delete-branch] <numbers...>`
   in the background (it can take a while: it waits for every pipeline). For each PR/MR it marks
   it ready, rebases it on the server if it is behind, waits for the pipeline and merges. It stops
   at the first conflict (exit 2), red pipeline (exit 3) or failed merge (exit 4).
   Pass `--delete-branch` only if I passed it or asked to delete the branches: after each merge it
   deletes that PR/MR's branch on the remote (never a fork's, never the local branch or a
   worktree). Without it the branches stay; do not delete them some other way. A failed delete is
   a warning in its output, not a stop: report it.
4. If it stops, say which one and why, and propose the fix; do not retry blindly.
5. Update the feature's PR/MR table, the decision log if the order changed, and Done in
   `progress.md` with today's date.
