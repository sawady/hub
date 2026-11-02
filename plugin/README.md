# hub (Claude Code plugin)

Commands, hook, agent and skill to run an engineering hub: a repo with no product code that
plans cross-repo features contract first, implements them with one agent per repo in parallel
git worktrees, and keeps `progress.md` as the source of truth. Works with GitHub (`gh`) and
GitLab (`glab`).

- Commands: `/hub:init`, `/hub:add-repo`, `/hub:feature`, `/hub:e2e`, `/hub:status`,
  `/hub:close`, `/hub:merge`, `/hub:dora`.
- Hook: at SessionStart, inside a hub only, injects Now/Blocked from `progress.md` and your open
  PRs/MRs across the hub's repos. Outside a hub it prints nothing.
- Agent: `repo-worker`, the fallback per-repo implementer used by `/hub:e2e`.
- Skill: `radar`, to publish and sync the team's request board (a claude.ai artifact).

Install:

```
/plugin install hub --marketplace sawady/hub
```

Scripts in `scripts/` use only the Python standard library and bash (`jq` for merges). Start with
`/hub:init`. Full documentation and the method: https://github.com/sawady/hub
