---
description: Record a decision in decisions/ (numbered, never rewritten; a new one supersedes an old one)
argument-hint: "<title> [--supersedes N]"
---
Record a decision in this hub: $ARGUMENTS

1. Decisions here outlive a feature (conventions, tools, rules for a repo, how we work). If this
   one is about a single feature, write it in that feature's decision log instead and stop.
2. Read `decisions/` (create it if missing). If the decision changes an earlier one, find its
   number; never edit an earlier decision's text.
3. Run from the hub:
   `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" new-decision "<title>" [--supersedes <N>]`.
   It creates `decisions/NNNN-<slug>.md` from `decisions/_template.md` with the next number and
   today's date, and with `--supersedes` changes only the Status line of the old one.
4. Fill Context, Decision, Consequences and Alternatives from this conversation, briefly. Ask only
   what is missing (who decided, the alternatives that were discarded). Status is Accepted unless
   I say it is only a proposal.
5. If the decision changes how agents must work in a repo, add the rule to that repo's agent
   (`.claude/agents/<alias>.md`) and link the decision. Mention it in today's entry of
   `progress.md` (Done or the Resume here block).
