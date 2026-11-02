# 0001 — Events are versioned and never changed in place

- **Date:** 2026-02-26
- **Status:** Accepted
- **Supersedes:** —
- **Deciders:** the web team

## Context

The notifier consumes order events from a queue and is deployed on its own schedule, often days
after orders-api. Saved carts adds the first event that the storefront team also wants to read.
A field renamed in place would break whichever consumer deploys last.

## Decision

Every event name carries a version (`cart.saved.v1`). A published version is never changed:
adding an optional field is allowed, anything else is a new version (`cart.saved.v2`) published
next to the old one until every consumer has moved.

## Consequences

- Producers may publish two versions for a while; the feature's merge order says when the old
  one can stop.
- The notifier's agent (`.claude/agents/notifier.md`) carries the rule.

## Alternatives considered

- A schema registry with compatibility checks — more than three repos need for now.
- Versioning the whole queue — one breaking change would move every event.
