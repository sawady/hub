# hub

An engineering hub for Claude Code: one repo with **no product code** from which you plan
features that span several repos, implement them with one agent per repo in parallel, and keep a
record of everything. It works with GitHub (`gh`) and GitLab (`glab`), even mixed in one hub.

hub is two things:

- **A template** for the hub repo: `CLAUDE.md`, `progress.md`, `repos.md`, `features/`,
  `journal/`, `research/` and sensible permissions.
- **A Claude Code plugin** with the commands that run the method (`/hub:feature`, `/hub:e2e`,
  `/hub:status`, `/hub:close`, `/hub:merge`, `/hub:dora`), a SessionStart hook that puts
  "where we are" in front of every session, and a generic per-repo agent.

## The method

**A repo without code.** Product repos have their own history, reviewers and rules. The work
that crosses them (what we are doing, why, in what order, what was decided) has no home, so it
ends up in chat threads and in people's heads. The hub is that home: a plain git repo of
markdown files, versioned, diffable, readable by people and by agents. Claude Code sessions start
in the hub and reach into the repos from there.

**`progress.md` is the source of truth.** Now, Next, Blocked, Paused, Done, and a **Resume here**
block written so that a fresh session (or a colleague, or you after a week off) can act on it
without asking anything. The SessionStart hook injects Now and Blocked, plus your open PRs/MRs
across all repos, at the start of every session. `/hub:status` refreshes it from the forges;
`/hub:close` closes the day.

**Contract first.** A feature that spans repos gets a file, `features/<name>.md`, and the first
thing written in it is the contract between repos: endpoints or events, payloads, what every
field and its absence mean, errors, auth, pagination, idempotency. It is approved before any code
exists. That is what makes the next step safe.

**Parallel agents in worktrees.** `/hub:e2e <feature>` creates a `git worktree` per repo (your
own checkouts are never touched), then launches one subagent per repo in a single message, so
they run in parallel. Each gets the contract verbatim and only its part. Producers go before
consumers: the API that publishes an OpenAPI spec finishes before the app that generates a client
from it. When they come back, the orchestrating session checks the diffs **against the
contract** (names, types, enums, errors) before anything is pushed.

**Absolute dates, always.** "Yesterday" is wrong the moment you read it tomorrow. Every entry in
the hub carries `YYYY-MM-DD`.

**People decide; agents prepare.** PRs/MRs are opened as drafts. Merging needs an explicit OK
(`gh pr merge` / `glab mr merge` are set to *ask*), force pushes are denied, and metrics are per
repo and for the team, never per person.

## Quick start

In Claude Code:

```
/plugin install hub --marketplace sawady/hub
/hub:init ~/work/my-hub
```

(On Claude Code before 2.1.275: `/plugin marketplace add sawady/hub`, then `/plugin install hub@hub`.)

`/hub:init` creates the hub from the template, asks which repos it drives, and for each one
infers the base branch, forge, stack and check commands. The hub's `.claude/settings.json`
enables the plugin, so anyone who clones the hub and trusts the folder gets it too.

Without Claude Code (or to script it):

```sh
git clone https://github.com/sawady/hub ~/src/hub
~/src/hub/bin/hub init ~/work/my-hub --name my-hub --owner "the web team"
cd ~/work/my-hub
~/src/hub/bin/hub add-repo orders-api ../orders-api --about "Orders API (Go)" --checks "make lint test"
~/src/hub/bin/hub doctor
```

Requirements: `git`, `python3` (3.8+, standard library only), `jq` for `/hub:merge`, and `gh`
and/or `glab` authenticated for the repos that use them.

## Commands

| Command | What it does |
|---|---|
| `/hub:init [dir]` | Create a hub from the template and add its repos |
| `/hub:add-repo <alias> <path>` | Add a repo: row in `repos.md`, agent in `.claude/agents/<alias>.md`, path allowed in settings |
| `/hub:feature <name>` | Create `features/<name>.md`, draft the contract, branch name, merge order and e2e plan |
| `/hub:e2e <name> [scope]` | One agent per repo in its own worktree, in parallel (producer first), then a consistency check against the contract; asks before pushing |
| `/hub:status` | Standup: branches, worktrees, PRs/MRs and pipelines of every repo; refreshes Now in `progress.md` |
| `/hub:close` | Close the day: `journal/<date>.md`, `progress.md`, feature decision logs, commit |
| `/hub:merge <alias> <n>...` | Merge PRs/MRs in order: mark ready, rebase when behind, wait for the pipeline, merge; stops at the first problem |
| `/hub:dora [alias...]` | DORA metrics per repo (deploy frequency, lead time, change failure rate, time to restore) |

The plugin also ships a `repo-worker` agent (used by `/hub:e2e` when a repo has no agent of its
own) and a `radar` skill (below).

## A hub, file by file

```
CLAUDE.md                 how this hub works; placeholders filled by init
progress.md               Now / Next / Blocked / Paused / Done + "Resume here"
repos.md                  alias, path, base branch, forge, about, checks, deploys
features/_template.md     contract, repos and PRs/MRs, merge order, e2e plan, decision log
features/<name>.md        one per cross-repo feature
journal/YYYY-MM-DD.md     daily notes from /hub:close
research/                 spikes, comparisons, postmortem drafts
.claude/agents/<alias>.md one agent per repo, with the rules that are easy to break there
.claude/settings.json     plugin enabled, read-only commands allowed, merges ask, force push denied
```

`repos.md` is a markdown table. The `Forge` column is optional: when empty, hub reads the
`origin` remote (`github.com` → GitHub, `gitlab.*` → GitLab; self-hosted hosts go in
`HUB_GITHUB_HOSTS` / `HUB_GITLAB_HOSTS`, comma-separated).

## An example, end to end

[`examples/acme-hub`](examples/acme-hub) is a made-up hub for Acme Books, a fictional online
bookshop with three repos: `orders-api` (Go, on GitHub), `storefront` (Next.js, on GitLab, base
branch `develop`) and `notifier` (a Python worker, on GitHub). The feature: **saved carts**.

1. **Monday 2026-02-24.** `/hub:feature saved-carts "customers save their cart and get a reminder"`.
   Claude reads the three repos, finds the existing cart endpoints and the event queue the notifier
   already consumes, and drafts [the contract](examples/acme-hub/features/saved-carts.md#contract-between-repos):
   `PUT/DELETE /v1/carts/{cartId}/saved`, a paginated `GET /v1/me/saved-carts`, the event
   `cart.saved.v1`, what `409 cart_empty` means for the UI. Merge order: orders-api → notifier →
   storefront. Two questions come back; they are answered and logged in the decision log.
2. **Friday 2026-02-27.** `/hub:e2e saved-carts`. Three worktrees under `../.worktrees/`. The
   orders-api agent runs first because the storefront generates its client from `openapi.yaml`;
   then notifier and storefront run in parallel, the storefront agent pointed at the orders-api
   worktree's spec. The consistency check finds that notifier parses `saved_at` while the contract
   says `savedAt`; it is fixed before anything is pushed. On approval, three draft PRs/MRs:
   orders-api #41 (`gh`), notifier #12 (`gh`), storefront !17 (`glab`).
3. **Every morning.** The session starts with Now/Blocked and the three open PRs/MRs already in
   context. `/hub:status` says storefront !17 is 4 commits behind `develop` and orders-api #41
   has two unresolved review threads.
4. **Monday 2026-03-02, evening.** `/hub:close` writes
   [`journal/2026-03-02.md`](examples/acme-hub/journal/2026-03-02.md) and rewrites the
   [Resume here](examples/acme-hub/progress.md) block: what is up, what waits for what, the next
   step.
5. **After the e2e checklist.** "Merge saved carts in order." `/hub:merge orders-api 41`, then
   `notifier 12`, then `storefront 17`: each one is marked ready, rebased if behind, waits for
   its pipeline, merges. Done gets a dated line; the feature's state becomes `prod`.

## Optional pieces

**Sequential merge** (`plugin/scripts/merge-seq.sh`, or `hub merge`). For GitHub:
`gh pr ready`, `gh pr update-branch --rebase` when `BEHIND`, waits on `gh pr checks`, then
`gh pr merge --squash|--rebase|--merge`. For GitLab: the same through the API (server-side
rebase, `head_pipeline` of the current head) and `glab mr merge`. Exit codes: 2 conflict,
3 red pipeline, 4 merge failed.

**DORA metrics** (`/hub:dora`, `plugin/scripts/dora.py`). Per repo, never per person: author
data is not read. What counts as a production deploy comes from the `Deploys` column of
`repos.md`: `branch` (every commit on the base branch, for continuous deployment), `tag:<glob>`,
or `env:<name>` (successful deployments to a GitHub/GitLab environment). Lead time is per commit,
from author date to the first deploy that contains it. A deploy is counted as failed when a later
deploy within 7 days reverts one of its commits or ships a hotfix/rollback; correct the heuristic
in `dora-overrides.json`.

**The Radar** (`radar` skill, `plugin/radar/radar.html`). A request board published as a
claude.ai artifact with a database: anyone with access files requests (each person writes only
their own document), the owner and editors triage, order Priority and move states, and a Metrics
tab shows the DORA table. `radar.md` in the hub is its versioned mirror, regenerated by the skill.
It is the team-facing view; `progress.md` stays the owner's log.

## Using it in Spanish

`hub init --lang es` (or answering "Spanish" in `/hub:init`) writes `progress.md` with Spanish
headings (Ahora, Próximo, Bloqueado, Pausado, Hecho, Retomar acá) and tells agents to write notes
in Spanish. The hook and the commands understand both sets of headings.

## Development

```sh
python3 -m unittest discover -s tests     # hub.py, dora.py, radar-md.py
bats tests/                               # merge-seq.sh against fake gh/glab, check-leaks.sh, the CLI
shellcheck bin/hub scripts/*.sh plugin/scripts/*.sh tests/fakes/*
claude plugin validate plugin && claude plugin validate .
```

`scripts/check-leaks.sh` scans the tree (and with `--history`, every commit) for terms that must
never be published. The term list is never in the repo: it comes from `~/.config/hub/leak-terms.txt`
locally or from the `HUB_LEAK_TERMS` secret in CI, and the report shows only `path:line: term #N`.
CI also runs gitleaks.

## License

MIT. See [LICENSE](LICENSE).
