---
name: radar
description: Set up or sync the hub's Radar, a claude.ai artifact with a database where anyone on the team files requests and the team triages them. Use it to publish the Radar the first time, to refresh radar.md (its versioned mirror), to propose Radar state changes from progress.md, or to upload DORA metrics. Runs at the end of /hub:close when the hub has a Radar.
---

# Radar

The Radar is a request board published as a claude.ai artifact with a database. It is the
team-facing view; `progress.md` stays the owner's work log. `radar.md` in the hub is its
versioned mirror. The page lives at `${CLAUDE_PLUGIN_ROOT}/radar/radar.html`.

Database layout:

| Path | What | Who writes |
|---|---|---|
| `items/<id>` | Triaged items: `title`, `description`, `area`, `state` (Priority, In progress, In review, Inbox, Later, Shipped, Dropped), `kind` (Request or Tech task), `waitingOn[]`, `order`, `requestedBy` (a team or role, free text), `createdBy` (opaque id), `links[]`, `createdAt`, `shippedAt`, `history[]` | Editors and the owner |
| `requests/<viewer id>` | `{items: {<id>: {...}}}`: new requests each person filed, still untriaged | Each person their own; Editors and the owner all |
| `dora/index` | Output of `/hub:dora` (`.dora/index.json`) | Editors and the owner |

## First time: publish it

1. Copy `${CLAUDE_PLUGIN_ROOT}/radar/radar.html` into the hub (`radar/radar.html`) and edit its
   `<title>` and its `radar-config` block (title, subtitle and areas). Nothing else needs changing.
2. Publish it with the Artifact tool (`file_path` = that copy) and these capabilities:
   `{"db": {"rules": [{"path": "", "read": "view", "write": "admin"}, {"path": "requests", "read": "view", "write": "admin"}, {"path": "requests/{self}", "read": "view", "write": "interact"}]}, "user": {"scopes": ["profile"]}}`.
   Then the owner shares it: Contributor for people who should file requests, Editor for people
   who triage.
3. Write the artifact URL into the hub's `CLAUDE.md` (uncomment the Radar line) and commit.

## Sync

1. **Dump the database.** Remove `.radar-db/` and dump with `ArtifactData` (`action: "list"`,
   `out_dir: <hub>/.radar-db`) the collections `items` and `requests`.
2. **Regenerate the mirror:**
   `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/radar-md.py" --dump .radar-db --out radar.md --title "<title>" --url <artifact URL>`.
   Show `git diff --stat radar.md` and a summary of what changed state.
3. **Propose changes from what happened** (never apply them without the owner's OK): compare with
   "Resume here" in `progress.md` and the features touched. An item that shipped → `Shipped`
   with `shippedAt` and a `history` entry; new technical work → a `Tech task` in `Inbox`; someone
   unblocked something → clear `waitingOn`. With the OK, write with `ArtifactData` (`update`, or
   `batch` for several).
4. **Metrics (optional):** run `/hub:dora`, then `ArtifactData` `set` of `dora/index` with
   `file_path: .dora/index.json`.
5. If `/hub:close` did not call this skill: commit `radar.md` in the hub (`radar sync YYYY-MM-DD`).

## Rules

- Moving states and ordering Priority is the owner's (or the Editors') call. New requests stay in
  Inbox until someone triages them.
- Do not delete items or requests without OK. Dates are absolute (YYYY-MM-DD; ISO 8601 in UTC in
  the database).
- Nothing with exploitable security detail, credentials, or sensitive information about people:
  everyone with access reads the Radar.
- Metrics are per repo, for the team. Never per person.
