# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). There are no
tagged releases yet; the plugin manifest says 0.1.0.

## [Unreleased]

### Added

- Template for the hub repo: `CLAUDE.md`, `progress.md` (Now / Next / Blocked / Paused / Done and
  "Resume here"), `repos.md`, `features/_template.md` (contract first), `journal/`, `research/`,
  and `.claude/settings.json` with read-only commands allowed, merges on ask and force push
  denied. Spanish headings with `--lang es`.
- Claude Code plugin and marketplace: `/hub:init`, `/hub:add-repo`, `/hub:feature`, `/hub:e2e`
  (one agent per repo in parallel worktrees, producer first, consistency check against the
  contract), `/hub:status`, `/hub:close`, `/hub:merge` and `/hub:dora`; a SessionStart hook with
  Now / Blocked and open PRs/MRs; a `repo-worker` agent and a `radar` skill.
- GitHub (`gh`) and GitLab (`glab`) support, detected per repo.
- `bin/hub` CLI (`init`, `add-repo`, `repos`, `prs`, `doctor`, `sync-settings`, `context`, `merge`,
  `dora`) with the same helpers the plugin uses, for use without Claude Code.
- Sequential merge (`merge-seq.sh`), DORA metrics per repo (`dora.py`), the Radar request board
  and its markdown mirror (`radar-md.py`).
- `scripts/check-leaks.sh`, a term scan over the tree and the history with the term list kept
  outside the repository.
- An end-to-end example for a fictional bookshop (`examples/acme-hub`).
- Tests (unittest and bats) and CI with the term scan, gitleaks, tests and shellcheck.
- `CONTRIBUTING.md` and this changelog.

### Changed

- CI actions moved to Node 24 (`actions/checkout@v5`, `actions/setup-python@v6`).

[Unreleased]: https://github.com/sawady/hub/commits/main
