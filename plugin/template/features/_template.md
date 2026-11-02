# <Feature name>

- **State:** design | implementing | review | staging | prod
- **Tickets:** <links or ids>
- **Started:** YYYY-MM-DD
- **Branch:** `feat/<name>` (same name in every repo)

## Goal

What problem it solves and for whom, in 2-3 lines.

## Contract between repos

Written and approved **before** any code. Endpoints or events, payloads, the meaning of every
field (and of its absence), errors, auth, pagination, idempotency, versioning. Whoever implements
a repo reads only this section to know what the other side expects.

## Repos and PRs/MRs

| Repo | Branch | PR/MR | State | Depends on |
|---|---|---|---|---|
| <alias> | `feat/<name>` | | | |

**Merge order:** <producer first, e.g. api → client → app>

## E2E test plan

- [ ] Happy path across all repos
- [ ] Errors from the contract (each documented error is reachable)
- [ ] Backwards compatibility while repos are deployed one at a time

## Open items

- ...

## Decision log

- YYYY-MM-DD: decision, and why.
