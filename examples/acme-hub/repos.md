# Repos

| Alias | Path | Base | Forge | About | Checks | Deploys |
|---|---|---|---|---|---|---|
| orders-api | `../orders-api` | main | github | Orders and carts API (Go, Postgres); publishes `openapi.yaml` | `make lint test` | tag:v* |
| storefront | `../storefront` | develop | gitlab | Customer web app (Next.js); generates its API client from orders-api | `pnpm lint && pnpm test` | branch |
| notifier | `../notifier` | main | github | Email and push worker (Python), consumes order events | `make check` | env:production |

## Notes per repo

- **orders-api:** after changing an endpoint run `make openapi` and commit `openapi.yaml`; the
  storefront generates its client from it.
- **storefront:** `pnpm api:generate --spec ../orders-api/openapi.yaml` (or the orders-api worktree
  path). Feature MRs target `develop`; `main` is promoted weekly.
- **notifier:** events are versioned (`cart.saved.v1`); never change a published event in place.
