# Saved carts

- **State:** review
- **Tickets:** SHOP-210
- **Started:** 2026-02-24
- **Branch:** `feat/saved-carts` (same name in every repo)

## Goal

Signed-in customers can save their cart and come back to it on any device, and get one reminder
email after 3 days if they did not.

## Contract between repos

**orders-api** exposes (documented in `openapi.yaml`):

- `PUT /v1/carts/{cartId}/saved` → `204`. Idempotent: saving an already saved cart is a no-op.
  `404 cart_not_found`, `409 cart_empty` (an empty cart cannot be saved), `401` without a session.
- `DELETE /v1/carts/{cartId}/saved` → `204`. Idempotent.
- `GET /v1/me/saved-carts?cursor=` → `200 {items: SavedCart[], nextCursor: string | null}`,
  newest first, 20 per page. `nextCursor: null` means there are no more pages.
- `SavedCart = {cartId: string, savedAt: RFC 3339 UTC, itemCount: int >= 1, subtotal: Money}`;
  `Money = {amount: string (decimal), currency: ISO 4217}`. Prices are the current ones, not the
  ones at save time.

**orders-api** publishes the event `cart.saved.v1` `{cartId, customerId, savedAt}` once per save
(not on the idempotent no-op).

**notifier** sends one reminder 72 h after `cart.saved.v1` unless the cart was checked out or
unsaved in between (it asks `GET /v1/carts/{cartId}` before sending; `404` means do not send).

**storefront** shows "Save for later" on the cart page and a "Saved carts" page that uses the
paginated endpoint. On `409 cart_empty` the button is disabled, not an error toast.

## Repos and PRs/MRs

| Repo | Branch | PR/MR | State | Depends on |
|---|---|---|---|---|
| orders-api | `feat/saved-carts` | #41 | draft, checks green | — |
| notifier | `feat/saved-carts` | #12 | draft, checks green | orders-api #41 (event) |
| storefront | `feat/saved-carts` | !17 | draft, pipeline green | orders-api #41 (client) |

**Merge order:** orders-api → notifier → storefront. The API is backwards compatible, so the
storefront can ship any time after the API.

## E2E test plan

- [x] Save, list, unsave on a fresh account (staging)
- [ ] Save on desktop, open on phone, same cart
- [ ] `409 cart_empty` disables the button
- [ ] Reminder email after 72 h (staging clock override), and no email after checkout
- [ ] Pagination with 25 saved carts

## Open items

- Copy for the reminder email (product, by 2026-03-04).

## Decision log

- 2026-02-24: contract first draft; the event goes through the existing queue, not a webhook,
  because notifier already consumes `order.*` from it.
- 2026-02-25: `subtotal` uses current prices; showing stale prices caused support tickets in checkout v1.
- 2026-02-27: `/hub:e2e saved-carts` ran three agents in parallel (orders-api first: storefront
  waited for its `openapi.yaml`). The consistency check caught `saved_at` vs `savedAt` in
  notifier; fixed before opening PRs.
