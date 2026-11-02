#!/usr/bin/env python3
"""hub: helpers for an engineering hub repo driven by Claude Code.

A hub is a repo with no product code. It holds `progress.md` (the source of truth for what is
going on), `repos.md` (the map of the repos it orchestrates), `features/` (one file per
cross-repo feature) and a daily `journal/`.

Subcommands:
  context              print "Now" / "Blocked" from progress.md and your open PRs/MRs
                       (used by the SessionStart hook; prints nothing outside a hub)
  repos [--json]       list the repos in repos.md with their resolved path, base and forge
  forge <path>         print github | gitlab | unknown for a git checkout
  slug <path>          print owner/repo (or group/.../project) of its origin remote
  prs [--json]         list your open PRs (GitHub) and MRs (GitLab) across the repos
  init <dir> [--name N] [--owner O] [--lang en|es] [--force]
                       create a new hub from the template
  add-repo <alias> <path> [--base B] [--forge F] [--about TEXT] [--checks CMD]
                       add a repo to repos.md, create .claude/agents/<alias>.md and allow
                       the path in .claude/settings.json
  sync-settings        make .claude/settings.json allow every path in repos.md
  doctor               check repos, forges and CLI auth

Only the standard library is used. Run it with `python3 -I`.
"""
import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys

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
MAX_SECTION_LINES = 60
MAX_CONTEXT_CHARS = 9000  # SessionStart output over 10,000 chars is moved to a file by Claude Code


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
}


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


def resolve(repo):
    r = dict(repo)
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


def all_prs(repos):
    repos = [r for r in repos if r["exists"] and r["forge"] in ("github", "gitlab")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(8, len(repos)))) as ex:
        results = list(ex.map(open_prs, repos))
    return [(r, prs) for r, prs in zip(repos, results)]


# ---------------------------------------------------------------- progress.md

def extract_sections(text, keys, max_lines=MAX_SECTION_LINES):
    """The `## <heading>` sections of progress.md for the given keys, in file order."""
    wanted = {h.lower() for k in keys for h in SECTIONS[k]}
    out, cur, count, cut = [], False, 0, False
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m and not line.startswith("###"):
            title = re.sub(r"\s*[(—-].*$", "", m.group(1)).strip().lower()
            cur, count, cut = title in wanted, 0, False
        if not cur:
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


def context(hub, with_prs=True):
    with open(os.path.join(hub, "progress.md"), encoding="utf-8") as f:
        text = f.read()
    parts = ["# Hub context (from progress.md)", "", extract_sections(text, ["now", "blocked"]) or "(no Now/Blocked sections)"]
    if with_prs:
        repos = [resolve(r) for r in load_repos(hub)]
        lines = []
        for r, prs in all_prs(repos):
            if prs:
                lines.append(f"### {r['alias']} ({r['forge']})")
                lines += [f"- {p['id']} {p['title']}{' [draft]' if p['draft'] else ''}"
                          f"{' — ' + p['branch'] if p['branch'] else ''}" for p in prs]
        parts += ["", "## My open PRs / MRs", ""] + (lines or ["(none found)"])
    out = "\n".join(parts)
    if len(out) > MAX_CONTEXT_CHARS:
        out = out[:MAX_CONTEXT_CHARS].rsplit("\n", 1)[0] + "\n… (truncated; read progress.md)"
    return out + "\n"


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
            dest = os.path.join(dest_dir, "progress.md" if fn == "progress.md" else fn)
            with open(src, encoding="utf-8") as f:
                text = render(f.read(), values)
            if lang == "es" and fn == "progress.md":
                for en, es in SPANISH.items():
                    text = text.replace(en, es)
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


def add_repo(hub, alias, path, base="main", forge="", about="", checks=""):
    if not re.match(r"^[a-z0-9][a-z0-9._-]*$", alias):
        raise SystemExit("alias must be lowercase kebab-case (a-z, 0-9, ., _, -)")
    if any(r["alias"] == alias for r in load_repos(hub)):
        raise SystemExit(f"{alias} is already in repos.md")
    repos_md = os.path.join(hub, "repos.md")
    with open(repos_md, encoding="utf-8") as f:
        lines = f.read().splitlines()
    abspath = os.path.normpath(path if os.path.isabs(path) else os.path.join(hub, path))
    if not forge and os.path.isdir(abspath):
        f = detect_forge(abspath)
        forge = f if f != "unknown" else ""
    row = f"| {alias} | `{path}` | {base} | {forge} | {about} | {('`' + checks + '`') if checks else ''} |"
    # insert after the last row of the repos table (or after its separator)
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and i + 1 < len(lines):
            header = [COLUMN_ALIASES.get(_clean(c).lower(), "") for c in _cells(line)]
            if "alias" in header and "path" in header:
                start = i
                break
    if start is None:
        lines += ["", "| Alias | Path | Base | Forge | About | Checks |", "|---|---|---|---|---|---|"]
        start = len(lines) - 2
    end = start + 2
    while end < len(lines) and lines[end].strip().startswith("|"):
        end += 1
    # drop a placeholder row like "| <alias> | ..." if it is the only row
    body = [x for x in lines[start + 2:end] if not _clean(_cells(x)[0]).startswith("<")]
    lines = lines[:start + 2] + body + [row] + lines[end:]
    with open(repos_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    agent = os.path.join(hub, ".claude", "agents", f"{alias}.md")
    if not os.path.exists(agent):
        os.makedirs(os.path.dirname(agent), exist_ok=True)
        with open(os.path.join(SNIPPETS, "repo-agent.md"), encoding="utf-8") as f:
            text = render(f.read(), {"ALIAS": alias, "PATH": path, "BASE": base,
                                     "ABOUT": about or "a repo of this hub",
                                     "CHECKS": checks or "the checks listed in its CLAUDE.md / README"})
        with open(agent, "w", encoding="utf-8") as f:
            f.write(text)
    sync_settings(hub)
    return row


# ---------------------------------------------------------------- doctor

def doctor(hub):
    problems = 0
    lines = [f"hub: {hub}"]
    for r in (resolve(x) for x in load_repos(hub)):
        status = "ok"
        if not r["exists"]:
            status, problems = "missing checkout", problems + 1
        elif r["forge"] == "unknown":
            status, problems = "forge unknown (set the Forge column)", problems + 1
        lines.append(f"- {r['alias']}: {r['abspath']} [{r['forge']}] {r['slug']} — {status}")
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
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("context")
    c.add_argument("--no-prs", action="store_true")
    c = sub.add_parser("repos")
    c.add_argument("--json", action="store_true")
    c = sub.add_parser("forge")
    c.add_argument("path")
    c = sub.add_parser("slug")
    c.add_argument("path")
    c = sub.add_parser("prs")
    c.add_argument("--json", action="store_true")
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
    c.add_argument("--forge", default="")
    c.add_argument("--about", default="")
    c.add_argument("--checks", default="")
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

    hub = find_hub()
    if a.cmd == "context":
        if hub:  # outside a hub the hook stays silent
            sys.stdout.write(context(hub, with_prs=not a.no_prs and os.environ.get("HUB_SKIP_PRS") != "1"))
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
                print("\t".join([r["alias"], r["abspath"], r.get("base", "") or "main", r["forge"], r["slug"]]))
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
    if a.cmd == "add-repo":
        print(add_repo(hub, a.alias, a.path, a.base, a.forge, a.about, a.checks))
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
