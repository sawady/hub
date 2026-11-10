---
description: Record a decision in decisions/ (numbered, never rewritten; a new one supersedes an old one)
argument-hint: "<title> [--supersedes N] [--dir DIR]"
---
Record a decision in this hub: $ARGUMENTS

1. Decisions here outlive a feature (conventions, tools, rules for a repo, how we work). If this
   one is about a single feature, write it in that feature's decision log instead and stop.
2. The decisions folder is `decisions/`, unless I passed `--dir DIR` or `HUB_DECISIONS_DIR` is set
   (`echo "$HUB_DECISIONS_DIR"`; a hub sets it in the `env` of `.claude/settings.json`), always
   relative to the hub. Read that folder (it is created if missing). If the decision changes an
   earlier one, find its number; never edit an earlier decision's text.
3. Run from the hub:
   `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hub.py" new-decision "<title>" [--supersedes <N>] [--dir <DIR>]`.
   It creates `<folder>/NNNN-<slug>.md` from `<folder>/_template.md` (or the plugin's template if
   the folder has none) with the next number and today's date, and with `--supersedes` changes
   only the Status line of the old one.
4. Fill Context, Decision, Consequences and Alternatives from this conversation, briefly. Ask only
   what is missing (who decided, the alternatives that were discarded). Status is Accepted unless
   I say it is only a proposal. If the folder has no `_template.md` and its decisions follow
   another format or language, write the new one like the latest of them, keeping its number,
   title and date.
5. If the decision changes how agents must work in a repo, add the rule to that repo's agent
   (`.claude/agents/<alias>.md`) and link the decision. Mention it in today's entry of
   `progress.md` (Done or the Resume here block).
