# Privacy

hub is free software that runs on your machine, inside Claude Code. The author does not operate
any service for it and collects nothing: there is no telemetry, no analytics, no account and no
phone-home.

## What it stores

Everything hub writes is plain files in your hub repository (`progress.md`, `repos.md`,
`features/`, `journal/`, `decisions/`, `radar.md`, `.dora/`) and git commits in the repos you
point it at. They stay where you put them; pushing them anywhere is up to you.

## What it reads and sends, and where

- **Your forge, through your own CLI login**: the SessionStart hook and the commands call `gh`
  (GitHub) and `glab` (GitLab), already authenticated by you, to read CI runs and your open
  pull/merge requests. `/hub:merge` and `/hub:e2e` also merge, push and, with `--delete-branch`,
  delete branches, always on repos you listed and after you ask. `HUB_SKIP_CI=1` and
  `HUB_SKIP_PRS=1` keep the hook off the network.
- **git remotes**: commands that land work push to the remotes your repos already have.
- **DORA metrics** (`/hub:dora`) are computed from local git history. For repos that measure
  deploys from a forge environment, it reads that environment's deployments through `gh` or
  `glab`. It does not read or store commit authors or subjects.
- **The Radar (optional)**: if you publish it, the Radar is a claude.ai artifact in your own
  account, and its items and requests are stored in that artifact's database on claude.ai. People
  you share it with see the names on their claude.ai profiles next to the requests they file.
  The page loads its fonts from Google Fonts, so viewers' browsers contact Google.
- **Your AI assistant**: Claude Code sends what the commands and the hook produce to its model as
  part of your session, like any other context. Anthropic's privacy policy covers that.

## Contact

Questions or concerns: open an issue at <https://github.com/sawady/hub/issues>. For a security
problem, open an issue that asks for a private channel and leave the details out of it.
