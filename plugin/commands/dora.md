---
description: DORA metrics per repo (deploy frequency, lead time, change failure rate, time to restore) — never per person
argument-hint: "[alias ...] [--days N]"
---
Compute the DORA metrics for this hub's repos: $ARGUMENTS

1. Run `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/dora.py" --hub . --out .dora $ARGUMENTS`.
   It reads `repos.md` (the optional `Deploys` column says what a production deploy is: `branch`,
   `tag:<glob>` or `env:<environment>`), fetches tags, and uses `gh` / `glab` only for
   `env:` deploys. It writes `.dora/index.json`, `.dora/<alias>.json` and `.dora/report.md`.
2. Show `.dora/report.md`. Point out repos without deploys (probably a wrong `Deploys` setting)
   and failures detected by the heuristic (reverts and hotfixes within 7 days), which can be
   corrected in `dora-overrides.json` at the hub root.
3. Metrics are per repo and for the team. Never break them down by person, and never add author
   data to the output.
