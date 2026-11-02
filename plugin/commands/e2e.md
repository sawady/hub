---
description: Implement a cross-repo feature in parallel, one agent per repo in its own git worktree
argument-hint: "<feature-name> [which part to implement in this run]"
---
Implement the feature `features/$1.md`. Scope of this run: $ARGUMENTS

1. Read `features/$1.md` and `repos.md`. If the contract is not closed (open questions, fields
   without semantics, undecided errors), stop and list what has to be decided. Do not guess.
2. Read each affected repo's row in `repos.md`, including its **Flow** (`pr`, the default, or
   `direct`; `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" repos` prints it last). Both flows
   work the same until step 6. For each affected repo, create a worktree so the branch checked out
   in the repo is never touched. Worktrees live outside the repos, in a `.worktrees/` folder next to them:
   `git -C <repo> fetch origin && git -C <repo> worktree add <repo>/../.worktrees/<alias>-<branch> -b <branch> origin/<base>`
   (without `-b` if the branch already exists). Reuse an existing worktree for the same branch.
3. Work out the order. If a repo consumes what another produces (a generated client from an
   OpenAPI spec, a shared schema, a published package), the producer goes first and the consumer
   gets the producer's worktree path. Everything else runs **in parallel: launch all independent
   subagents in a single message**, one per repo, using the repo's agent (`.claude/agents/<alias>.md`;
   fall back to the `hub:repo-worker` agent). Give each one:
   - the worktree path and branch,
   - the contract, copied verbatim from the feature file,
   - exactly the part it owns, and what the other repos will do,
   - to finish with the repo's checks green (from `repos.md`) and a commit, without pushing.
4. When they return, check **consistency against the contract**: field names and types on both
   sides, enums, error codes and HTTP statuses, nullability, pagination, auth. Read the diffs
   (`git -C <worktree> diff origin/<base>...HEAD`), do not trust the summaries alone. Fix or send
   back what does not match.
5. Update the Repos and PRs/MRs table and Open items in `features/$1.md`, the decision log if
   something was decided, and **Now** in `progress.md`.
6. Show a short summary per repo and ask before pushing, opening PRs/MRs or landing anything.
   - **Flow `pr`:** when approved, push the branch and open drafts: `gh pr create --draft` for
     GitHub repos, `glab mr create --draft` for GitLab repos (the forge is in `repos.md`). Link the
     feature's other PRs/MRs in each description and note the merge order.
   - **Flow `direct`:** there is no PR/MR. Landing pushes to the base branch, so it needs an
     explicit OK for that repo, like a merge. Land in the merge order (producers first), one repo
     at a time, running in the background:
     `"${CLAUDE_PLUGIN_ROOT}/scripts/land-direct.sh" -C <worktree> --base <base>`.
     It refuses a dirty worktree, refuses if `<base>` moved (exit 2: rebase the branch on
     `origin/<base>`, rerun the checks, ask again), waits for the CI of the current tip of
     `<base>` and refuses if it is red (exit 3: the base must be fixed first), pushes `HEAD:<base>`
     as a fast-forward (never forced), and waits for the CI of the pushed commit (exit 3 if it goes
     red: report it, fix forward, never rewrite history; exit 4 if the push is rejected).
     When it lands, record the commit in the feature's table (`direct` + short sha) and remove the
     worktree and branch (`git -C <repo> worktree remove <worktree>`, `git -C <repo> branch -d <branch>`).
     The repo's own checkout is not touched; say so, in case its base branch should be pulled.
