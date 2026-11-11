# hub (Claude Code plugin)

Commands, hook, agent and skill to run an engineering hub: a repo with no product code that
plans cross-repo features contract first, implements them with one agent per repo in parallel
git worktrees, and keeps `progress.md` as the source of truth. Works with GitHub (`gh`) and
GitLab (`glab`).

- Commands: `/hub:init`, `/hub:add-repo`, `/hub:feature`, `/hub:e2e`, `/hub:status`,
  `/hub:portfolio`, `/hub:close`, `/hub:merge`, `/hub:decision`, `/hub:dora`.
- Hook: at SessionStart, inside a hub only, injects Now/Blocked from `progress.md`, the repos
  whose base branch has a red CI run, and your open PRs/MRs across the hub's repos. Outside a hub
  it prints nothing. `HUB_SKIP_CI=1` / `HUB_SKIP_PRS=1` skip the forge calls.
- Agent: `repo-worker`, the fallback per-repo implementer used by `/hub:e2e`.
- Skill: `radar`, to publish and sync the team's request board (a claude.ai artifact).

Install:

```
/plugin install hub --marketplace sawady/hub
```

Scripts in `scripts/` use only the Python standard library and bash (`jq` for merges). Start with
`/hub:init`. Full documentation and the method: https://github.com/sawady/hub

Built for Claude Code: the hook, the agent and the scripts need a local shell, git, `gh` or
`glab`, and your repos. In claude.ai chat only the commands and the skill load, as instructions.

Examples:

- `/hub:init ~/work/acme-hub`, then `/hub:add-repo orders-api ../orders-api`: create a hub for
  the Acme Books web team and register the repos it drives.
- `/hub:feature saved-carts Keep a reader's cart between visits`: write the contract-first plan
  for a feature that touches several repos, in `features/saved-carts.md`.
- `/hub:e2e saved-carts`: implement that plan with one agent per repo in parallel worktrees, then
  check every repo against the contract.

What it runs and sends: the scripts call `git`, and `gh` or `glab` with your own login, to read
CI runs and your open PRs/MRs and, when you ask, to push and merge. DORA metrics come from local
git history. The optional Radar is a claude.ai artifact in your account. There is no telemetry.
Details: https://github.com/sawady/hub/blob/main/PRIVACY.md

Permissions it writes: `/hub:init` creates the new hub's `.claude/settings.json`, which enables
this plugin from the `sawady/hub` marketplace, allows read-only `git`, `gh` and `glab` commands,
asks before merging or marking a PR/MR ready, and denies force pushes and deleting repos.
`/hub:add-repo` adds each repo's directory to `additionalDirectories` there. It only touches the
hub's own settings, never your user settings.

MIT licensed.
