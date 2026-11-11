# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Listing details for Anthropic's plugin directory: `displayName`, the icon path, and
  documentation, support and privacy policy links in `plugin.json` (Claude Code ignores the
  last four), plus `PRIVACY.md`. The plugin README now says where the plugin works, gives three
  examples and says what it runs and sends.
- An optional pre-push hook, `scripts/git-hooks/pre-push`, that runs
  `scripts/check-leaks.sh --history` and stops the push unless it exits 0. Install it with
  `git config core.hooksPath scripts/git-hooks` (see CONTRIBUTING.md).
- `land-direct.sh` (`hub land`, `/hub:e2e` with Flow `direct`) runs the repo's leak scan before
  landing when the repo sets one with `git config hub.leakScan "<command>"`, and refuses to land
  (exit 5, nothing pushed) unless it exits 0. Repos without it work as before.
- `/hub:decision` and `hub new-decision` can use another decisions folder of the hub, for hubs
  that already keep them elsewhere (`decisiones/`): `--dir DIR`, or `HUB_DECISIONS_DIR` (for
  example in the `env` of `.claude/settings.json`). The folder must be inside the hub. Without
  either, `decisions/` as before.
- `/hub:merge` and `merge-seq.sh` take `--delete-branch`: after each merge, the PR's branch is
  deleted on the remote through the GitHub API (never a fork's, never the local branch, and a
  failed delete is only a warning), or the MR is merged with `--remove-source-branch` on GitLab.
  Without it, branches stay as before.
- `--hub DIR` on `hub.py` and `bin/hub`, to work on a hub from outside it. `/hub:init <dir>` uses it
  to add the repos and run `doctor`, because a session may not be allowed to `cd` there.
- `/hub:portfolio` and `hub portfolio`: one line per repo (project, repo, state, next step) from
  `repos.md` and `progress.md`, without calling any forge. `--json` for the full text and
  `--update FILE` to rewrite a marked block of a file such as `README.md`.
- A plugin icon (`plugin/.claude-plugin/icon.png`).

### Fixed

- The SessionStart hook no longer injects the template's placeholders as if they were the hub's
  state (`- <feature or task> — ...`, `YYYY-MM-DD`, the guidance under "Resume here"). Right after
  `/hub:init` it says that Now and Blocked are empty.
- Radar: Contributors can file requests again. The page hid the button because it read
  `can("data.write")`, which answers for the root rule and not for `requests/{self}`.
- Radar: a malformed date no longer breaks an item's sheet, nor stops `radar-md.py` from
  regenerating the mirror.
- The `radar` skill now says to edit `<title>` too, the name the artifact gets in the gallery.
- `merge-seq.sh` on GitHub, found against real PRs: a merge state of `UNKNOWN` (what GitHub reports
  right after the previous PR of the sequence merged) is now waited out, so a conflict is exit 2
  and a behind branch gets rebased. The base moving during the checks is handled too, a failure of
  `gh` no longer counts as "no checks", and a conflicting draft stays a draft.

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
