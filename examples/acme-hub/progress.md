# Progress

Last updated: 2026-03-02

## Now

### Resume here (2026-03-02, evening)

- **saved-carts** — orders-api #41 (draft, checks green) and storefront !17 (draft, pipeline green)
  are up; notifier #12 waits for orders-api #41 to merge because it consumes `cart.saved.v1`.
  Next: e2e checklist on staging, then merge in order orders-api → notifier → storefront
  (`/hub:merge`). Contract: `features/saved-carts.md`.
- **checkout latency** — p95 regression since v87; suspect the tax lookup. Research in
  `research/2026-03-01-checkout-latency.md`.

## Next

- **gift receipts** — needs a contract for the receipt PDF endpoint; product wants it before 2026-04-01.

## Blocked

- **search reindex** — waiting on the data team for the new catalog export, since 2026-02-27.

## Paused

- **dark mode** — paused on 2026-02-20 for saved carts; resume after it ships.

## Done

### Week of 2026-02-23

- 2026-02-26: checkout v2 shipped (orders-api v86, storefront !14).
