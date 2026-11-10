#!/usr/bin/env python3
"""hub: helpers for an engineering hub repo driven by Claude Code.

A hub is a repo with no product code. It holds `progress.md` (the source of truth for what is
going on), `repos.md` (the map of the repos it orchestrates), `features/` (one file per
cross-repo feature) and a daily `journal/`.

Subcommands:
  context [--no-prs] [--no-ci]
                       print "Now" / "Blocked" from progress.md (without the template's
                       placeholders), the repos whose base branch has a red CI run, and
                       your open PRs/MRs (used by the SessionStart hook; prints nothing
                       outside a hub). HUB_SKIP_PRS=1 / HUB_SKIP_CI=1 skip the
                       forge calls.
  repos [--json]       list the repos in repos.md with their resolved path, base, forge, slug
                       and flow (pr | direct)
  forge <path>         print github | gitlab | unknown for a git checkout
  slug <path>          print owner/repo (or group/.../project) of its origin remote
  prs [--json]         list your open PRs (GitHub) and MRs (GitLab) across the repos
  ci [--json] [--red]  state of the latest CI run on each repo's base branch
  ci-state <path> (--branch B | --sha S) [--forge F]
                       print "<state>\t<url>" for one checkout: success, failure, pending,
                       cancelled, manual, none (no run) or unknown (could not ask the forge)
  portfolio [--json] [--update FILE]
                       one line per repo (project, repo, state, next step) from repos.md and
                       progress.md; --update rewrites the marked block of FILE, usually README.md
  init <dir> [--name N] [--owner O] [--lang en|es] [--force]
                       create a new hub from the template
  add-repo <alias> <path> [--base B] [--flow pr|direct] [--forge F] [--about TEXT]
                       [--checks CMD] [--deploys D]
                       add a repo to repos.md, create .claude/agents/<alias>.md and allow
                       the path in .claude/settings.json
  new-decision <title> [--supersedes N] [--dir DIR]
                       create decisions/NNNN-<slug>.md from decisions/_template.md; DIR (or
                       $HUB_DECISIONS_DIR) is another folder of the hub, such as decisiones
  sync-settings        make .claude/settings.json allow every path in repos.md
  doctor               check repos, forges and CLI auth

Only the standard library is used. Run it with `python3 -I`.
"""
import argparse
import concurrent.futures
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
TEMPLATE = os.path.join(PLUGIN, "template")
SNIPPETS = os.path.join(PLUGIN, "snippets")

# progress.md sections. English is canonical; Spanish headings are accepted too.
SECTIONS = {
    "now": ["Now", "Ahora"],
    "next": ["Next", "Próximo", "Proximo"],
    "blocked": ["Blocked", "Bloqueado"],
    "paused": ["Paused", "Pausado"],
    "done": ["Done", "Hecho"],
}
SPANISH = {
    "## Now": "## Ahora",
    "## Next": "## Próximo",
    "## Blocked": "## Bloqueado",
    "## Paused": "## Pausado",
    "## Done": "## Hecho",
    "### Resume here": "### Retomar acá",
    "Last updated": "Última actualización",
}
SPANISH_DECISION = {
    "# NNNN — <Title>": "# NNNN — <Título>",
    "- **Date:**": "- **Fecha:**",
    "- **Status:** Accepted": "- **Estado:** Aceptada",
    "- **Supersedes:**": "- **Reemplaza a:**",
    "- **Deciders:** <who decided>": "- **Decidió:** <quién decidió>",
    "## Context": "## Contexto",
    "What forces a decision: the problem, the constraints, what was known at the time.":
        "Qué obliga a decidir: el problema, las restricciones, lo que se sabía en ese momento.",
    "## Decision": "## Decisión",
    "What was decided, in one or two sentences, then the details that matter.":
        "Qué se decidió, en una o dos oraciones, y después los detalles que importan.",
    "## Consequences": "## Consecuencias",
    "What gets easier or harder, and what has to be done because of it.":
        "Qué se vuelve más fácil o más difícil, y qué hay que hacer por esto.",
    "## Alternatives considered": "## Alternativas consideradas",
    "- <option> — why not.": "- <opción> — por qué no.",
}
# per-file translations applied by `init --lang es` (path relative to the template)
TRANSLATIONS_ES = {
    "progress.md": SPANISH,
    os.path.join("decisions", "_template.md"): SPANISH_DECISION,
}
MAX_SECTION_LINES = 60
MAX_CONTEXT_CHARS = 9000  # SessionStart output over 10,000 chars is moved to a file by Claude Code
FORGE_WORKERS = 16
FORGE_TIMEOUT = 8      # seconds per gh/glab call
FORGE_BUDGET = 16      # seconds for all the forge calls of `context` (the hook times out at 20)


# ---------------------------------------------------------------- locating the hub

def is_hub(path):
    return os.path.isfile(os.path.join(path, "progress.md")) and os.path.isfile(os.path.join(path, "repos.md"))


def find_hub(start=None):
    """The hub root: $CLAUDE_PROJECT_DIR or the nearest parent with progress.md and repos.md."""
    cands = []
    if start:
        cands.append(start)
    else:
        if os.environ.get("CLAUDE_PROJECT_DIR"):
            cands.append(os.environ["CLAUDE_PROJECT_DIR"])
        cands.append(os.getcwd())
    for c in cands:
        p = os.path.abspath(c)
        while True:
            if is_hub(p):
                return p
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
    return None


# ---------------------------------------------------------------- repos.md

COLUMN_ALIASES = {
    "alias": "alias", "name": "alias", "repo": "alias",
    "path": "path", "ruta": "path",
    "base": "base", "base branch": "base", "rama base": "base",
    "forge": "forge", "forja": "forge", "host": "forge",
    "about": "about", "what": "about", "what it is": "about", "qué es": "about", "que es": "about",
    "checks": "checks", "commands": "checks", "comandos": "checks",
    "deploys": "deploys", "deploy": "deploys",
    "flow": "flow", "flujo": "flow",
}
DEFAULT_COLUMNS = ["Alias", "Path", "Base", "Flow", "Forge", "About", "Checks"]


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def _clean(cell):
    cell = cell.strip()
    if len(cell) >= 2 and cell[0] == "`" and cell[-1] == "`":
        cell = cell[1:-1]
    return cell.replace("\\|", "|").strip()


def parse_repos(text):
    """Rows of the first markdown table in repos.md that has Alias and Path columns."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.strip().startswith("|") or i + 1 >= len(lines):
            continue
        header = [COLUMN_ALIASES.get(_clean(c).lower(), _clean(c).lower()) for c in _cells(line)]
        if "alias" not in header or "path" not in header:
            continue
        if not re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            continue
        rows = []
        for row in lines[i + 2:]:
            if not row.strip().startswith("|"):
                break
            cells = [_clean(c) for c in _cells(row)]
            r = {header[k]: cells[k] if k < len(cells) else "" for k in range(len(header))}
            if not r.get("alias") or r["alias"].startswith("<"):
                continue  # empty or placeholder row
            rows.append(r)
        return rows
    return []


def load_repos(hub):
    path = os.path.join(hub, "repos.md")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        rows = parse_repos(f.read())
    for r in rows:
        p = os.path.expanduser(r.get("path", ""))
        r["abspath"] = os.path.normpath(p if os.path.isabs(p) else os.path.join(hub, p))
    return rows


# ---------------------------------------------------------------- forges

def run(cmd, cwd=None, timeout=10):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return out.returncode, out.stdout


def remote_url(path):
    code, out = run(["git", "-C", path, "remote", "get-url", "origin"])
    return out.strip() if code == 0 else ""


def remote_host(url):
    m = re.match(r"^[\w+.-]+://(?:[^@/]+@)?([^/:]+)", url)  # https://host/..., ssh://git@host:22/...
    if m:
        return m.group(1).lower()
    m = re.match(r"^(?:[^@]+@)?([^:/]+):", url)  # git@host:group/repo.git
    return m.group(1).lower() if m else ""


def remote_slug(url):
    """owner/repo (GitHub) or group/subgroup/project (GitLab) from a remote URL."""
    url = url.strip()
    m = re.match(r"^[\w+.-]+://(?:[^@/]+@)?[^/]+(?::\d+)?/(.+?)(?:\.git)?/?$", url)
    if not m:
        m = re.match(r"^(?:[^@]+@)?[^:/]+:(.+?)(?:\.git)?/?$", url)
    return m.group(1) if m else ""


def normalize_forge(name):
    n = (name or "").strip().lower()
    if n in ("github", "gh", "github.com"):
        return "github"
    if n in ("gitlab", "glab", "gitlab.com"):
        return "gitlab"
    return ""


def detect_forge(path, declared=""):
    """github | gitlab | unknown. A declared value (repos.md Forge column) wins over the remote."""
    f = normalize_forge(declared)
    if f:
        return f
    host = remote_host(remote_url(path))
    if not host:
        return "unknown"
    if "github" in host:
        return "github"
    if "gitlab" in host:
        return "gitlab"
    extra = [h.strip().lower() for h in os.environ.get("HUB_GITLAB_HOSTS", "").split(",") if h.strip()]
    if host in extra:
        return "gitlab"
    extra = [h.strip().lower() for h in os.environ.get("HUB_GITHUB_HOSTS", "").split(",") if h.strip()]
    if host in extra:
        return "github"
    return "unknown"


def normalize_flow(name):
    """pr (the default: branches and PRs/MRs) | direct (land on the base branch, no PRs/MRs) | "" if invalid."""
    n = (name or "").strip().lower()
    if n in ("", "pr", "prs", "mr", "mrs", "pr/mr"):
        return "pr"
    if n in ("direct", "directo", "push"):
        return "direct"
    return ""


def resolve(repo):
    r = dict(repo)
    r["base"] = repo.get("base") or "main"
    r["flow"] = normalize_flow(repo.get("flow")) or "pr"
    r["exists"] = os.path.isdir(r["abspath"])
    r["forge"] = detect_forge(r["abspath"], repo.get("forge", "")) if r["exists"] else (normalize_forge(repo.get("forge", "")) or "unknown")
    r["slug"] = remote_slug(remote_url(r["abspath"])) if r["exists"] else ""
    return r


# ---------------------------------------------------------------- open PRs / MRs

def open_prs(repo, timeout=8):
    """Your open PRs (gh) or MRs (glab) in one repo, as dicts. Empty on any failure."""
    path, forge = repo["abspath"], repo["forge"]
    if forge == "github" and shutil.which("gh"):
        code, out = run(["gh", "pr", "list", "--author", "@me", "--state", "open",
                         "--json", "number,title,isDraft,url,headRefName"], cwd=path, timeout=timeout)
        if code != 0:
            return []
        try:
            return [{"id": f"#{p['number']}", "title": p["title"], "draft": p.get("isDraft", False),
                     "url": p.get("url", ""), "branch": p.get("headRefName", "")} for p in json.loads(out or "[]")]
        except (ValueError, KeyError, TypeError):
            return []
    if forge == "gitlab" and shutil.which("glab"):
        code, out = run(["glab", "mr", "list", "--author=@me", "--output", "json"], cwd=path, timeout=timeout)
        if code == 0:
            try:
                return [{"id": f"!{m['iid']}", "title": m["title"], "draft": m.get("draft", False),
                         "url": m.get("web_url", ""), "branch": m.get("source_branch", "")} for m in json.loads(out or "[]")]
            except (ValueError, KeyError, TypeError):
                pass
        code, out = run(["glab", "mr", "list", "--author=@me"], cwd=path, timeout=timeout)  # older glab
        if code != 0:
            return []
        res = []
        for line in out.splitlines():
            m = re.match(r"^!(\d+)\s+\S*\s*(.*?)\s*(?:\(([^)]*)\))?\s*$", line.strip())
            if m:
                res.append({"id": f"!{m.group(1)}", "title": m.group(2), "draft": "draft" in m.group(2).lower(),
                            "url": "", "branch": ""})
        return res
    return []


def forge_timeout(n_tasks):
    """Per-call timeout so that every wave of FORGE_WORKERS calls fits in FORGE_BUDGET."""
    waves = max(1, -(-n_tasks // FORGE_WORKERS))
    return max(2, min(FORGE_TIMEOUT, FORGE_BUDGET // waves))


def _on_forges(repos, fns):
    """Run fn(repo, timeout=...) for every fn in fns and every repo on a known forge, in parallel.
    Returns (repos, {fn: [result per repo]})."""
    repos = [r for r in repos if r["exists"] and r["forge"] in ("github", "gitlab")]
    tasks = [(fn, r) for fn in fns for r in repos]
    if not tasks:
        return repos, {fn: [] for fn in fns}
    timeout = forge_timeout(len(tasks))
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(FORGE_WORKERS, len(tasks))) as ex:
        futures = [ex.submit(fn, r, timeout=timeout) for fn, r in tasks]
        results = [f.result() for f in futures]
    return repos, {fn: results[i * len(repos):(i + 1) * len(repos)] for i, fn in enumerate(fns)}


def all_prs(repos):
    repos, res = _on_forges(repos, [open_prs])
    return list(zip(repos, res[open_prs]))


# ---------------------------------------------------------------- CI on the base branch

def _gh_run_state(run_):
    if (run_.get("status") or "").lower() != "completed":
        return "pending"
    c = (run_.get("conclusion") or "").lower()
    if c in ("success", "neutral", "skipped"):
        return "success"
    if c in ("failure", "timed_out", "startup_failure"):
        return "failure"
    return "cancelled"  # cancelled, action_required, stale


def _gl_pipeline_state(p):
    s = (p.get("status") or "").lower()
    if s in ("success", "skipped"):
        return "success"
    if s == "failed":
        return "failure"
    if s == "canceled":
        return "cancelled"
    if s == "manual":
        return "manual"
    return "pending"  # created, waiting_for_resource, preparing, pending, running, scheduled


def _aggregate(states):
    if not states:
        return "none"
    for s in ("failure", "pending", "cancelled", "manual"):
        if s in states:
            return s
    return "success"


def ci_state(path, forge, branch=None, sha=None, timeout=8):
    """CI of a checkout, from gh or glab: the latest run on `branch`, or every run for `sha`.

    Returns {"state", "url", "title", "workflow", "sha"}. state is success | failure | pending |
    cancelled | manual | none (no run) | unknown (no CLI, not authenticated, timeout...)."""
    unknown = {"state": "unknown", "url": "", "title": "", "workflow": "", "sha": ""}
    if forge == "github" and shutil.which("gh"):
        cmd = ["gh", "run", "list", "--json", "status,conclusion,workflowName,displayTitle,url,headSha"]
        cmd += ["--commit", sha, "-L", "50"] if sha else ["--branch", branch, "-L", "1"]
        code, out = run(cmd, cwd=path, timeout=timeout)
        if code != 0:
            return unknown
        try:
            runs = [x for x in json.loads(out or "[]") if isinstance(x, dict)]
        except ValueError:
            return unknown
        states = [_gh_run_state(x) for x in runs]
        info = lambda x: (x.get("url"), x.get("displayTitle"), x.get("workflowName"), x.get("headSha"))  # noqa: E731
    elif forge == "gitlab" and shutil.which("glab"):
        cmd = ["glab", "ci", "list", "--output", "json"]
        cmd += ["--sha", sha, "--per-page", "50"] if sha else ["--ref", branch, "--per-page", "1"]
        code, out = run(cmd, cwd=path, timeout=timeout)
        if code != 0:
            return unknown
        try:
            runs = [x for x in json.loads(out or "[]") if isinstance(x, dict)]
        except ValueError:
            return unknown
        states = [_gl_pipeline_state(x) for x in runs]
        info = lambda x: (x.get("web_url"), x.get("name"), f"pipeline {x['id']}" if x.get("id") else "pipeline", x.get("sha"))  # noqa: E731
    else:
        return unknown
    state = _aggregate(states)
    pick = next((x for x, s in zip(runs, states) if s == state), None)
    url, title, workflow, sha_ = info(pick) if pick else ("", "", "", "")
    return {"state": state, "url": url or "", "title": title or "", "workflow": workflow or "", "sha": sha_ or ""}


def base_ci(repo, timeout=8):
    """The latest CI run on the repo's base branch (`gh run list --branch <base> -L 1`)."""
    return ci_state(repo["abspath"], repo["forge"], branch=repo.get("base") or "main", timeout=timeout)


def all_ci(repos):
    repos, res = _on_forges(repos, [base_ci])
    return list(zip(repos, res[base_ci]))


def _ci_lines(ci):
    red = [(r, c) for r, c in ci if c["state"] == "failure"]
    lines = []
    for r, c in red:
        what = " — ".join(x for x in (c["workflow"], c["title"]) if x)
        lines.append(f"- {r['alias']} ({r['base']}): failed{' — ' + what if what else ''}"
                     f"{' — ' + c['url'] if c['url'] else ''}")
    if not lines:
        lines.append("(none)")
    unknown = [r["alias"] for r, c in ci if c["state"] == "unknown"]
    if unknown:
        lines.append(f"(could not read CI for: {', '.join(unknown)})")
    return lines


# ---------------------------------------------------------------- progress.md

def _heading_title(line):
    """The normalized title of a `## <heading>` line ("Now (2026-03-02)" -> "now"), or None."""
    m = re.match(r"^##\s+(.+?)\s*$", line)
    return re.sub(r"\s*[(—-].*$", "", m.group(1)).strip().lower() if m else None


_TEMPLATE_HINTS = None


def _template_hints():
    """The guidance lines of the template's progress.md (neither headings nor bullets), such as
    the sentence under "Resume here", which a fresh hub still has."""
    global _TEMPLATE_HINTS
    if _TEMPLATE_HINTS is None:
        hints = set()
        try:
            with open(os.path.join(TEMPLATE, "progress.md"), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        for t in (text, translate(text, SPANISH)):
            for line in t.splitlines():
                s = line.strip()
                if s and not s.startswith("#") and not re.match(r"^[-*]\s", s):
                    hints.add(s)
        _TEMPLATE_HINTS = hints
    return _TEMPLATE_HINTS


def translate(text, table):
    for en, es in table.items():
        text = text.replace(en, es)
    return text


def is_placeholder(line):
    """A line of progress.md that is still the template's: a top-level bullet that starts with
    `<...>` (`- <feature or task> — ...`), anything with a `YYYY-MM-DD` date, or the template's
    guidance."""
    return bool(re.match(r"^[-*]\s+<", line)) or "YYYY-MM-DD" in line or line.strip() in _template_hints()


def extract_sections(text, keys, max_lines=MAX_SECTION_LINES):
    """The `## <heading>` sections of progress.md for the given keys, in file order. Lines left
    from the template (see is_placeholder) are not part of them."""
    wanted = {h.lower() for k in keys for h in SECTIONS[k]}
    out, cur, count, cut = [], False, 0, False
    for line in text.splitlines():
        title = _heading_title(line)
        if title is not None:
            cur, count, cut = title in wanted, 0, False
        if not cur or is_placeholder(line) or (not line.strip() and out and not out[-1].strip()):
            continue
        if count >= max_lines:
            if not cut:
                out.append("… (truncated; read progress.md for the rest)")
                cut = True
            continue
        out.append(line)
        count += 1
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def context(hub, with_prs=True, with_ci=True):
    with open(os.path.join(hub, "progress.md"), encoding="utf-8") as f:
        text = f.read()
    state = extract_sections(text, ["now", "blocked"])
    if not state:
        state = "(no Now/Blocked sections)"
    elif all(not x.strip() or x.startswith("#") for x in state.splitlines()):
        state = "(Now and Blocked are empty)"
    parts = ["# Hub context (from progress.md)", "", state]
    fns = ([base_ci] if with_ci else []) + ([open_prs] if with_prs else [])
    if fns:
        repos, res = _on_forges([resolve(r) for r in load_repos(hub)], fns)
    if with_ci:
        parts += ["", "## Red CI (latest run on the base branch)", ""] + _ci_lines(list(zip(repos, res[base_ci])))
    if with_prs:
        lines = []
        for r, prs in zip(repos, res[open_prs]):
            if prs:
                lines.append(f"### {r['alias']} ({r['forge']})")
                lines += [f"- {p['id']} {p['title']}{' [draft]' if p['draft'] else ''}"
                          f"{' — ' + p['branch'] if p['branch'] else ''}" for p in prs]
        parts += ["", "## My open PRs / MRs", ""] + (lines or ["(none found)"])
    out = "\n".join(parts)
    if len(out) > MAX_CONTEXT_CHARS:
        out = out[:MAX_CONTEXT_CHARS].rsplit("\n", 1)[0] + "\n… (truncated; read progress.md)"
    return out + "\n"


# ---------------------------------------------------------------- portfolio

PORTFOLIO_SECTIONS = ["now", "blocked", "next", "paused"]  # the order a repo's state is looked up in
PORTFOLIO_START = "<!-- hub:portfolio -->"
PORTFOLIO_END = "<!-- /hub:portfolio -->"
PORTFOLIO_CELL = 140  # characters of state or next step in the table; --json keeps the full text
PORTFOLIO_LABELS = {
    "en": {"head": ["Project", "Repo", "State", "Next step"], "now": "in progress", "queued": "queued", "blocked": "blocked", "paused": "paused"},
    "es": {"head": ["Proyecto", "Repo", "Estado", "Próximo paso"], "now": "en curso", "queued": "en cola", "blocked": "bloqueado", "paused": "pausado"},
}
_NEXT_MARK = re.compile(r"(?:^|(?<=[\s—–;.,(]))(?:next(?: step)?|próximo(?: paso)?|proximo(?: paso)?|siguiente(?: paso)?)\s*:\s*", re.I)


def progress_bullets(text):
    """The top-level bullets of Now/Blocked/Next/Paused as (section key, text); wrapped lines are
    joined, nested bullets and template placeholders are left out."""
    key_of = {h.lower(): k for k in PORTFOLIO_SECTIONS for h in SECTIONS[k]}
    out, key, cur = [], None, None

    def flush():
        nonlocal cur
        if cur is not None and not cur.startswith("<"):
            out.append((key, cur))
        cur = None

    for line in text.splitlines():
        title = _heading_title(line)
        if title is not None:
            flush()
            key = key_of.get(title)
        elif key is None:
            continue
        elif re.match(r"^[-*]\s+", line):
            flush()
            cur = re.sub(r"^[-*]\s+", "", line).strip()
        elif cur is None or not line.strip() or line.startswith("#") or re.match(r"^\s+[-*]\s+", line):
            flush()
        elif line[0].isspace():
            cur += " " + line.strip()
        else:
            flush()
    flush()
    return out


def _plain(text):
    return text.replace("**", "").strip()


def _alias_re(alias):
    # the alias as a whole name: "api" is not in "orders-api" nor in "api-docs"
    return re.compile(r"(?<![\w./-])" + re.escape(alias) + r"(?![\w-]|\.\w|/\w)", re.I)


def _split_next(text):
    """(what is going on, next step) of a bullet written like `<state> — next: <step>`."""
    m = _NEXT_MARK.search(text)
    if not m:
        return text, ""
    step = re.split(r"(?<=[.;])\s+(?=[A-ZÁÉÍÓÚÑ])", text[m.end():])[0]
    step = re.sub(r"\s*\(`features/[^`]*`\)", "", step)
    return text[:m.start()], step.strip().rstrip(".;").strip()


def _strip_head(text, alias):
    """Drop a leading `alias —` from a bullet, and the separators around the rest."""
    text = re.sub(r"^`?" + re.escape(alias) + r"`?\s*(?:[—–:]|-\s)\s*", "", text, flags=re.I)
    return text.strip().strip("—–;,").strip()


def portfolio_row(repo, bullets, labels):
    """One repo's line. A bullet that starts with the alias beats one that only mentions it, and
    within each of those Now beats Blocked, Next and Paused."""
    pat = _alias_re(repo["alias"])
    found = []
    for key, text in bullets:
        plain = _plain(text)
        unticked = plain.replace("`", "")
        hit = pat.search(unticked)
        if hit:
            found.append((hit.start() != 0, PORTFOLIO_SECTIONS.index(key), len(found), key, plain))
    row = {"project": repo["alias"], "repo": repo.get("slug") or repo.get("path", ""),
           "state": "", "next": "", "section": ""}
    if not found:
        return row
    found.sort()
    _, _, _, key, plain = found[0]
    what, step = _split_next(plain)
    what = _strip_head(what, repo["alias"])
    row["section"] = key
    if key == "next":
        row["state"], row["next"] = labels["queued"], step or what
        return row
    row["state"], row["next"] = what or labels["now"], step
    if key in ("blocked", "paused"):
        row["state"] = f"{labels[key]}: {what}" if what else labels[key]
    if not row["next"]:
        later = next((f for f in found if f[3] == "next"), None)
        if later:
            step_what, step_next = _split_next(later[4])
            row["next"] = step_next or _strip_head(step_what, repo["alias"])
    return row


def portfolio(hub):
    """(rows, language of progress.md) for every repo in repos.md, in its order. No forge calls."""
    with open(os.path.join(hub, "progress.md"), encoding="utf-8") as f:
        text = f.read()
    lang = "es" if re.search(r"^##\s+(Ahora|Próximo|Proximo|Bloqueado|Pausado|Hecho)\b", text, re.M) else "en"
    bullets = progress_bullets(text)
    return [portfolio_row(resolve(r), bullets, PORTFOLIO_LABELS[lang]) for r in load_repos(hub)], lang


def _short(text, limit=PORTFOLIO_CELL):
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:—–") + "…"


def portfolio_table(rows, lang):
    head = PORTFOLIO_LABELS[lang]["head"]
    lines = [_row(head), _row(["---"] * len(head))]
    for r in rows:
        lines.append(_row([_cell(r["project"]), f"`{_cell(r['repo'])}`" if r["repo"] else "—",
                           _cell(_short(r["state"])) or "—", _cell(_short(r["next"])) or "—"]))
    return "\n".join(lines)


def update_portfolio_block(path, table):
    """Replace what is between the portfolio markers of a file. Nothing else in it is touched."""
    if not os.path.isfile(path):
        raise SystemExit(f"{path}: no such file")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    a = text.find(PORTFOLIO_START)
    b = text.find(PORTFOLIO_END, a + 1) if a >= 0 else -1
    if a < 0 or b < 0:
        raise SystemExit(f"{path}: add the lines {PORTFOLIO_START} and {PORTFOLIO_END} where the table goes")
    new = text[:a] + PORTFOLIO_START + "\n" + table + "\n" + text[b:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)


# ---------------------------------------------------------------- init / add-repo / settings

def render(text, values):
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def init(target, name, owner, lang="en", force=False):
    target = os.path.abspath(target)
    if os.path.exists(target) and os.listdir(target) and not force:
        existing = [f for f in ("CLAUDE.md", "progress.md", "repos.md") if os.path.exists(os.path.join(target, f))]
        if existing:
            raise SystemExit(f"{target} already has {', '.join(existing)} (use --force to overwrite)")
    values = {"HUB_NAME": name or os.path.basename(target), "OWNER": owner or "the team",
              "LANG": "Spanish (Rioplatense)" if lang == "es" else "English"}
    for root, _dirs, files in os.walk(TEMPLATE):
        rel = os.path.relpath(root, TEMPLATE)
        dest_dir = os.path.join(target, rel) if rel != "." else target
        os.makedirs(dest_dir, exist_ok=True)
        for fn in files:
            src = os.path.join(root, fn)
            dest = os.path.join(dest_dir, fn)
            with open(src, encoding="utf-8") as f:
                text = render(f.read(), values)
            if lang == "es":
                text = translate(text, TRANSLATIONS_ES.get(os.path.normpath(os.path.join(rel, fn)), {}))
            if os.path.exists(dest) and not force:
                continue
            with open(dest, "w", encoding="utf-8") as f:
                f.write(text)
    return target


def _settings_path(hub):
    return os.path.join(hub, ".claude", "settings.json")


def sync_settings(hub):
    """Add every repo path of repos.md to permissions.additionalDirectories. Returns the added ones."""
    path = _settings_path(hub)
    data = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    perms = data.setdefault("permissions", {})
    dirs = perms.setdefault("additionalDirectories", [])
    added = []
    for r in load_repos(hub):
        p = r.get("path", "")
        if p and p not in dirs:
            dirs.append(p)
            added.append(p)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return added


def _row(cells):
    return "| " + " | ".join(cells) + " |"


def _cell(text):
    return (text or "").replace("|", "\\|")


def flow_rule(base, flow):
    """The line about the base branch in a repo's agent."""
    if flow == "direct":
        return (f"Base branch: `{base}`, Flow `direct` (no PRs/MRs). Still work on the branch or worktree "
                f"you are given; the orchestrator lands it on `{base}` (fast-forward and push, CI green). "
                f"Never push to `{base}` yourself, never force-push.")
    return f"Base branch: `{base}`. Never commit to it, never merge: changes reach it through a PR/MR."


def add_repo(hub, alias, path, base="main", forge="", about="", checks="", flow="", deploys=""):
    if not re.match(r"^[a-z0-9][a-z0-9._-]*$", alias):
        raise SystemExit("alias must be lowercase kebab-case (a-z, 0-9, ., _, -)")
    if flow and not normalize_flow(flow):
        raise SystemExit("flow must be pr or direct")
    flow = normalize_flow(flow) if flow else ""
    if any(r["alias"] == alias for r in load_repos(hub)):
        raise SystemExit(f"{alias} is already in repos.md")
    repos_md = os.path.join(hub, "repos.md")
    with open(repos_md, encoding="utf-8") as f:
        lines = f.read().splitlines()
    abspath = os.path.normpath(path if os.path.isabs(path) else os.path.join(hub, path))
    if not forge and os.path.isdir(abspath):
        f = detect_forge(abspath)
        forge = f if f != "unknown" else ""
    # find the repos table (or append one)
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and i + 1 < len(lines):
            header = [COLUMN_ALIASES.get(_clean(c).lower(), "") for c in _cells(line)]
            if "alias" in header and "path" in header:
                start = i
                break
    if start is None:
        lines += ["", _row(DEFAULT_COLUMNS), _row(["---"] * len(DEFAULT_COLUMNS))]
        start = len(lines) - 2
    end = start + 2
    while end < len(lines) and lines[end].strip().startswith("|"):
        end += 1
    head = _cells(lines[start])
    body = [_cells(x) for x in lines[start + 2:end]]
    keys = [COLUMN_ALIASES.get(_clean(c).lower(), _clean(c).lower()) for c in head]
    # a hub created before the Flow column gets it only when a repo needs it
    if flow == "direct" and "flow" not in keys:
        at = keys.index("base") + 1 if "base" in keys else len(keys)
        keys.insert(at, "flow")
        head.insert(at, "Flow")
        body = [row[:at] + [""] + row[at:] for row in body]
    values = {"alias": alias, "path": f"`{path}`", "base": base, "flow": flow or "pr", "forge": forge,
              "about": _cell(about), "checks": f"`{_cell(checks)}`" if checks else "", "deploys": deploys}
    row = [values.get(k, "") for k in keys]
    # drop placeholder rows like "| <alias> | ..."
    body = [x for x in body if not _clean(x[0]).startswith("<")]
    lines = lines[:start] + [_row(head), _row(["---"] * len(head))] + [_row(x) for x in body] + [_row(row)] + lines[end:]
    with open(repos_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    agent = os.path.join(hub, ".claude", "agents", f"{alias}.md")
    if not os.path.exists(agent):
        os.makedirs(os.path.dirname(agent), exist_ok=True)
        with open(os.path.join(SNIPPETS, "repo-agent.md"), encoding="utf-8") as f:
            text = render(f.read(), {"ALIAS": alias, "PATH": path, "BASE": base,
                                     "BASE_RULE": flow_rule(base, flow or "pr"),
                                     "ABOUT": about or "a repo of this hub",
                                     "CHECKS": checks or "the checks listed in its CLAUDE.md / README"})
        with open(agent, "w", encoding="utf-8") as f:
            f.write(text)
    sync_settings(hub)
    return _row(row)


# ---------------------------------------------------------------- decisions

def _slug(title):
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60] or "decision"


DECISIONS_DIR = "decisions"


def decisions_dir(hub, folder=None):
    """The hub's decisions folder: `folder`, else $HUB_DECISIONS_DIR, else decisions/. It must be
    inside the hub."""
    folder = folder or os.environ.get("HUB_DECISIONS_DIR") or DECISIONS_DIR
    root = os.path.abspath(hub)
    path = os.path.normpath(os.path.join(root, os.path.expanduser(folder)))
    if path == root or os.path.commonpath([root, path]) != root:
        raise SystemExit(f"the decisions folder must be a folder inside the hub, not {folder}")
    return path


def new_decision(hub, title, supersedes=None, today=None, folder=None):
    """Create <folder>/NNNN-<slug>.md from <folder>/_template.md (decisions/ unless `folder` or
    $HUB_DECISIONS_DIR say otherwise). Decisions are never rewritten: a superseding one only
    changes the Status line of the old one. Returns the new path."""
    d = decisions_dir(hub, folder)
    os.makedirs(d, exist_ok=True)
    tpl = os.path.join(d, "_template.md")
    if not os.path.isfile(tpl):
        tpl = os.path.join(TEMPLATE, "decisions", "_template.md")
    files = sorted(fn for fn in os.listdir(d) if re.match(r"^\d{4}-.*\.md$", fn))
    n = max([int(fn[:4]) for fn in files], default=0) + 1
    old = None
    if supersedes is not None:
        old = next((fn for fn in files if int(fn[:4]) == int(supersedes)), None)
        if not old:
            raise SystemExit(f"no decision {int(supersedes):04d} in {os.path.relpath(d, os.path.abspath(hub))}/")
    num = f"{n:04d}"
    name = f"{num}-{_slug(title)}.md"
    today = today or datetime.date.today().isoformat()
    with open(tpl, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r"^# NNNN — .*$", lambda m: f"# {num} — {title}", text, count=1, flags=re.M)
    text = re.sub(r"^(- \*\*(?:Date|Fecha):\*\*) .*$", lambda m: f"{m.group(1)} {today}", text, count=1, flags=re.M)
    if old:
        text = re.sub(r"^(- \*\*(?:Supersedes|Reemplaza a):\*\*) .*$",
                      lambda m: f"{m.group(1)} [{old[:4]}]({old})", text, count=1, flags=re.M)
        path_old = os.path.join(d, old)
        with open(path_old, encoding="utf-8") as f:
            prev = f.read()
        prev, k = re.subn(r"^- \*\*(Status|Estado):\*\* .*$",
                          lambda m: f"- **{m.group(1)}:** {'Reemplazada por' if m.group(1) == 'Estado' else 'Superseded by'} [{num}]({name})",
                          prev, count=1, flags=re.M)
        if not k:
            prev = prev.rstrip("\n") + f"\n\nSuperseded by [{num}]({name}).\n"
        with open(path_old, "w", encoding="utf-8") as f:
            f.write(prev)
    path = os.path.join(d, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ---------------------------------------------------------------- doctor

def doctor(hub):
    problems = 0
    lines = [f"hub: {hub}"]
    for x in load_repos(hub):
        r = resolve(x)
        status = "ok"
        if not r["exists"]:
            status, problems = "missing checkout", problems + 1
        elif r["forge"] == "unknown":
            status, problems = "forge unknown (set the Forge column)", problems + 1
        if not normalize_flow(x.get("flow", "")):
            status, problems = f"unknown Flow '{x['flow']}' (use pr or direct)", problems + 1
        lines.append(f"- {r['alias']}: {r['abspath']} [{r['forge']}, {r['flow']}] {r['slug']} — {status}")
    for cli, forge in (("gh", "github"), ("glab", "gitlab")):
        used = any(normalize_forge(r.get("forge", "")) == forge or resolve(r)["forge"] == forge for r in load_repos(hub))
        if not used:
            continue
        if not shutil.which(cli):
            lines.append(f"- {cli}: not installed (needed for {forge} repos)")
            problems += 1
            continue
        code, _ = run([cli, "auth", "status"])
        lines.append(f"- {cli}: {'authenticated' if code == 0 else 'NOT authenticated (run `' + cli + ' auth login`)'}")
        problems += code != 0
    return problems, "\n".join(lines)


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(prog="hub", description=__doc__.split("\n\n")[0])
    ap.add_argument("--hub", metavar="DIR", help="the hub to work on (default: $CLAUDE_PROJECT_DIR, then the current directory and its parents)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("context")
    c.add_argument("--no-prs", action="store_true")
    c.add_argument("--no-ci", action="store_true")
    c = sub.add_parser("repos")
    c.add_argument("--json", action="store_true")
    c = sub.add_parser("forge")
    c.add_argument("path")
    c = sub.add_parser("slug")
    c.add_argument("path")
    c = sub.add_parser("prs")
    c.add_argument("--json", action="store_true")
    c = sub.add_parser("ci")
    c.add_argument("--json", action="store_true")
    c.add_argument("--red", action="store_true", help="only repos whose latest run failed")
    c = sub.add_parser("portfolio")
    c.add_argument("--json", action="store_true")
    c.add_argument("--update", metavar="FILE", help="rewrite the block between the portfolio markers of FILE")
    c = sub.add_parser("ci-state")
    c.add_argument("path")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--branch")
    g.add_argument("--sha")
    c.add_argument("--forge", default="")
    c.add_argument("--timeout", type=int, default=20)
    c = sub.add_parser("init")
    c.add_argument("dir")
    c.add_argument("--name", default="")
    c.add_argument("--owner", default="")
    c.add_argument("--lang", choices=["en", "es"], default="en")
    c.add_argument("--force", action="store_true")
    c = sub.add_parser("add-repo")
    c.add_argument("alias")
    c.add_argument("path")
    c.add_argument("--base", default="main")
    c.add_argument("--flow", default="", help="pr (default) or direct")
    c.add_argument("--forge", default="")
    c.add_argument("--about", default="")
    c.add_argument("--checks", default="")
    c.add_argument("--deploys", default="")
    c = sub.add_parser("new-decision")
    c.add_argument("title")
    c.add_argument("--supersedes", type=int)
    c.add_argument("--dir", default="", help="decisions folder inside the hub (default: $HUB_DECISIONS_DIR, then decisions)")
    sub.add_parser("sync-settings")
    sub.add_parser("doctor")
    a = ap.parse_args(argv)

    if a.cmd == "init":
        t = init(a.dir, a.name, a.owner, a.lang, a.force)
        print(f"hub created at {t}\nnext: add repos with `hub add-repo <alias> <path>` (or /hub:add-repo in Claude Code)")
        return 0
    if a.cmd == "forge":
        print(detect_forge(a.path))
        return 0
    if a.cmd == "slug":
        print(remote_slug(remote_url(a.path)))
        return 0
    if a.cmd == "ci-state":
        forge = normalize_forge(a.forge) or detect_forge(a.path)
        c = ci_state(a.path, forge, branch=a.branch, sha=a.sha, timeout=a.timeout)
        print(f"{c['state']}\t{c['url']}")
        return 0

    if a.hub and not is_hub(a.hub):
        print(f"{a.hub} is not a hub (no progress.md + repos.md)", file=sys.stderr)
        return 1
    hub = os.path.abspath(a.hub) if a.hub else find_hub()
    if a.cmd == "context":
        if hub:  # outside a hub the hook stays silent
            sys.stdout.write(context(hub, with_prs=not a.no_prs and os.environ.get("HUB_SKIP_PRS") != "1",
                                     with_ci=not a.no_ci and os.environ.get("HUB_SKIP_CI") != "1"))
        return 0
    if not hub:
        print("not inside a hub (no progress.md + repos.md found)", file=sys.stderr)
        return 1
    if a.cmd == "repos":
        rows = [resolve(r) for r in load_repos(hub)]
        if a.json:
            print(json.dumps(rows, indent=1, ensure_ascii=False))
        else:
            for r in rows:
                print("\t".join([r["alias"], r["abspath"], r["base"], r["forge"], r["slug"], r["flow"]]))
        return 0
    if a.cmd == "prs":
        res = all_prs([resolve(r) for r in load_repos(hub)])
        if a.json:
            print(json.dumps({r["alias"]: prs for r, prs in res}, indent=1, ensure_ascii=False))
        else:
            for r, prs in res:
                for p in prs:
                    print(f"{r['alias']}\t{p['id']}\t{'draft' if p['draft'] else 'ready'}\t{p['title']}")
        return 0
    if a.cmd == "ci":
        res = all_ci([resolve(r) for r in load_repos(hub)])
        if a.red:
            res = [(r, c) for r, c in res if c["state"] == "failure"]
        if a.json:
            print(json.dumps({r["alias"]: dict(c, base=r["base"]) for r, c in res}, indent=1, ensure_ascii=False))
        else:
            for r, c in res:
                print("\t".join([r["alias"], r["base"], c["state"], c["workflow"], c["url"]]))
        return 0
    if a.cmd == "portfolio":
        rows, lang = portfolio(hub)
        if a.json:
            print(json.dumps(rows, indent=1, ensure_ascii=False))
            return 0
        table = portfolio_table(rows, lang)
        if a.update:
            update_portfolio_block(os.path.join(hub, a.update), table)
        print(table)
        return 0
    if a.cmd == "add-repo":
        print(add_repo(hub, a.alias, a.path, a.base, a.forge, a.about, a.checks, a.flow, a.deploys))
        return 0
    if a.cmd == "new-decision":
        print(os.path.relpath(new_decision(hub, a.title, a.supersedes, folder=a.dir), hub))
        return 0
    if a.cmd == "sync-settings":
        added = sync_settings(hub)
        print("added: " + (", ".join(added) if added else "nothing (already in sync)"))
        return 0
    if a.cmd == "doctor":
        problems, report = doctor(hub)
        print(report)
        return 1 if problems else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
