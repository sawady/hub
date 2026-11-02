# Repos

The repos this hub drives. Paths are relative to the hub (siblings are the usual layout:
`~/work/<hub>` next to `~/work/<repo>`). The `Forge` column is optional: `github` or `gitlab`;
when empty it is detected from the `origin` remote. Add rows with `/hub:add-repo` or
`hub add-repo`, which also creates the repo's agent and allows the path in `.claude/settings.json`.

| Alias | Path | Base | Forge | About | Checks |
|---|---|---|---|---|---|
| <alias> | `../<repo>` | main | github | <what it is, stack> | `<lint && test command>` |

## Notes per repo

Rules that are easy to break, generated code to regenerate after a change, environments, and who
deploys what. Keep this short: the repo's own CLAUDE.md / AGENTS.md is the real reference.

- **<alias>:** ...

## Deploys (optional, for DORA metrics)

The `Deploys` column, if present, tells `/hub:dora` what counts as a production deploy:
`branch` (every commit on the base branch; continuous deployment), `tag:<glob>` (e.g. `tag:v*`)
or `env:<name>` (successful deployments to that GitHub/GitLab environment). Default: `branch`.
