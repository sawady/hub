---
description: Start a cross-repo feature from the template, contract first
argument-hint: "<kebab-name> [short description]"
---
Create `features/$1.md` from `features/_template.md` for the feature: $ARGUMENTS

1. Ask only the minimum that is missing to fill Goal, Tickets and which repos it touches (infer
   what you can from `repos.md` and the description).
2. Draft the **contract between repos** in the Contract section. Search the repos for existing
   endpoints, events, models and conventions that can be reused, and cite their paths. Be precise:
   field names and types, what each field and its absence mean, errors, auth, pagination,
   idempotency. List the open questions at the end of the section.
3. Propose one branch name for every repo (`feat/$1`) and a merge order: producers before
   consumers (the repo that publishes a schema or generated client merges before the one that uses
   it), and backwards-compatible steps when repos deploy independently.
4. Draft the e2e test plan from the contract.
5. Add the feature to **Next** (or **Now** if work starts today) in `progress.md`, with today's
   date in absolute form, and a decision-log entry in the feature file.

Do not create branches or worktrees: `/hub:e2e` does that once the contract is approved.
