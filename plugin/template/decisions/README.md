# Decisions

Decisions that outlive a single feature: conventions, tools, rules for a repo, how the team
works. One file per decision, `NNNN-<title>.md`, numbered in order (`0001-...`, `0002-...`),
created from [`_template.md`](_template.md) with `/hub:decision <title>` or
`hub new-decision "<title>"`.

- **Never rewritten.** A decision records what was decided and why, at that date. When it
  changes, write a new decision that supersedes it; the old one only gets its Status changed to
  "Superseded by NNNN" (the command does that with `--supersedes N`).
- **Status:** Proposed, Accepted, or Superseded by NNNN.
- Decisions about one feature (an endpoint name, a field's semantics) go in that feature's
  decision log in `features/<name>.md`, not here.
