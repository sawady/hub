# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `/hub:portfolio` and `hub portfolio`: one line per repo (project, repo, state, next step) from
  `repos.md` and `progress.md`, without calling any forge. `--json` for the full text and
  `--update FILE` to rewrite a marked block of a file such as `README.md`.

## [0.1.0] - 2026-11-02

First public version.

### Added

- Template for the hub repo: `CLAUDE.md`, `progress.md` (Now / Next / Blocked / Paused / Done and
  "Resume here"), `repos.md`, `features/_template.md` (contract first), `decisions/` (numbered
  records that are never rewritten, only superseded, with `_template.md`), `journal/`,
  `research/`, and `.claude/settings.json` with read-only commands allowed, merges on ask and
  force push denied. Spanish headings with `--lang es`.
- Claude Code plugin and marketplace: `/hub:init`, `/hub:add-repo`, `/hub:feature`, `/hub:e2e`
  (one agent per repo in parallel worktrees, producer first, consistency check against the
  contract), `/hub:status`, `/hub:close`, `/hub:merge`, `/hub:decision` and `/hub:dora`; a
  `repo-worker` agent and a `radar` skill.
- SessionStart hook with Now / Blocked from `progress.md`, a **Red CI** section (repos whose
  latest run on the base branch failed) and your open PRs/MRs. Forge calls run in parallel
  within the hook's time budget; `HUB_SKIP_CI=1` and `HUB_SKIP_PRS=1` turn them off.
- Two flows per repo, from the `Flow` column of `repos.md`: `pr` (default; draft PRs/MRs and
  `/hub:merge`) and `direct` (no PRs/MRs: `/hub:e2e` lands the branch with `land-direct.sh`,
  a fast-forward push gated on the base branch's CI, then watches the CI of the pushed commit).
- GitHub (`gh`) and GitLab (`glab`) support, detected per repo.
- `bin/hub` CLI (`init`, `add-repo`, `repos`, `prs`, `ci`, `doctor`, `sync-settings`, `context`,
  `new-decision`, `merge`, `land`, `dora`) with the same helpers the plugin uses, for use
  without Claude Code.
- Sequential merge (`merge-seq.sh`), DORA metrics per repo (`dora.py`), the Radar request board
  and its markdown mirror (`radar-md.py`).
- `scripts/check-leaks.sh`, a term scan over the tree and the history with the term list kept
  outside the repository.
- An end-to-end example for a fictional bookshop (`examples/acme-hub`).
- Tests (unittest and bats, against fake `gh`/`glab`) and CI with the term scan, gitleaks, tests
  and shellcheck.
- `CONTRIBUTING.md` and this changelog.

[Unreleased]: https://github.com/sawady/hub/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sawady/hub/releases/tag/v0.1.0
