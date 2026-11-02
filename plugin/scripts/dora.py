#!/usr/bin/env python3
"""DORA metrics per repo for a hub: deploy frequency, lead time for changes, change failure rate
and time to restore. Per repo and per team; author data is never read or written.

Usage: dora.py [--hub DIR] [--out DIR] [--days N] [--now ISO] [--no-fetch] [alias ...]

What a production deploy is comes from the optional `Deploys` column of repos.md:
  branch        every first-parent commit on the base branch (continuous deployment; default)
  tag:<glob>    every tag matching the glob, e.g. tag:v*  (time = tag date)
  env:<name>    successful deployments to that environment, from GitHub (gh) or GitLab (glab)

Lead time is measured per commit, from its author date to the first deploy that contains it.
A deploy counts as failed (heuristic) when, within 7 days, a later deploy reverts one of its
commits ("This reverts commit ...") or ships a hotfix/rollback/revert; the later deploy restores
it. Correct the heuristic in <hub>/dora-overrides.json:
  {"<alias>": {"<deploy ref>": {"failure": false, "reason": "not a prod incident"}}}

Writes <out>/index.json, <out>/<alias>.json and <out>/report.md. Read-only on the forges; in the
repos it only runs `git fetch origin --tags`.
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub as hublib  # noqa: E402

FAILURE_WINDOW = timedelta(days=7)
RE_REVERT = re.compile(r"This reverts commit ([0-9a-f]{7,40})")
RE_FIX = re.compile(r"\b(hotfix|hot-fix|rollback|roll back|revert)\b", re.I)
MAX_NOT = 50  # previous deploys excluded when listing a deploy's commits


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def git(path, *args):
    out = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {out.stderr.strip()[:300]}")
    return out.stdout


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def from_unix(s):
    return datetime.fromtimestamp(int(s), tz=timezone.utc)


def quantile(values, q):
    """Nearest-rank quantile; None for an empty list."""
    if not values:
        return None
    v = sorted(values)
    k = max(0, min(len(v) - 1, int(round(q * (len(v) - 1)))))
    return v[k]


# ---------------------------------------------------------------- deploy sources

def deploys_branch(path, base):
    ref = f"origin/{base}"
    try:
        git(path, "rev-parse", "--verify", "-q", ref)
    except RuntimeError:
        ref = base
    out = git(path, "log", "--first-parent", "--format=%H%x1f%ct", ref)
    res = []
    for line in out.splitlines():
        sha, ct = line.split("\x1f")
        res.append({"ref": sha[:8], "sha": sha, "t": from_unix(ct)})
    return res


def deploys_tag(path, glob):
    out = git(path, "for-each-ref", "--format=%(refname:short)%1f%(objectname)%1f%(*objectname)%1f%(creatordate:unix)",
              "refs/tags")
    res = []
    for line in out.splitlines():
        name, obj, peeled, t = line.split("\x1f")
        if fnmatch.fnmatchcase(name, glob):
            res.append({"ref": name, "sha": peeled or obj, "t": from_unix(t)})
    return res


def _json(cmd):
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}: {out.stderr.strip()[:300]}")
    # --paginate on gh/glab may print one JSON array per page back to back
    text, dec, items, i = out.stdout.strip(), json.JSONDecoder(), [], 0
    while i < len(text):
        obj, i = dec.raw_decode(text, i)
        items.extend(obj if isinstance(obj, list) else [obj])
        while i < len(text) and text[i].isspace():
            i += 1
    return items


def deploys_env(repo, env, since):
    slug = repo["slug"]
    if repo["forge"] == "github":
        res = []
        for d in _json(["gh", "api", "--paginate", f"repos/{slug}/deployments?environment={env}&per_page=100"]):
            created = parse_time(d.get("created_at"))
            if created and created < since:
                continue
            statuses = _json(["gh", "api", f"repos/{slug}/deployments/{d['id']}/statuses?per_page=100"])
            ok = [parse_time(s["created_at"]) for s in statuses if s.get("state") == "success"]
            if ok:
                res.append({"ref": str(d.get("ref") or d["sha"][:8]), "sha": d["sha"], "t": min(ok)})
        return res
    if repo["forge"] == "gitlab":
        proj = slug.replace("/", "%2F")
        res = []
        for d in _json(["glab", "api", "--paginate",
                        f"projects/{proj}/deployments?environment={env}&status=success&per_page=100"
                        f"&updated_after={iso(since)}"]):
            t = parse_time((d.get("deployable") or {}).get("finished_at") or d.get("finished_at") or d.get("updated_at"))
            if t:
                res.append({"ref": str(d.get("ref") or d["sha"][:8]), "sha": d["sha"], "t": t})
        return res
    raise RuntimeError(f"env: deploys need a GitHub or GitLab repo (forge is {repo['forge']})")


def list_deploys(repo, spec, since):
    path = repo["abspath"]
    if spec == "branch":
        d = deploys_branch(path, repo.get("base") or "main")
    elif spec.startswith("tag:"):
        d = deploys_tag(path, spec[4:] or "*")
    elif spec.startswith("env:"):
        d = deploys_env(repo, spec[4:] or "production", since)
    else:
        raise RuntimeError(f"unknown Deploys value {spec!r} (use branch, tag:<glob> or env:<name>)")
    first = {}
    for x in d:  # one deploy per sha: the first successful one
        if x["sha"] not in first or x["t"] < first[x["sha"]]["t"]:
            first[x["sha"]] = x
    res = sorted(first.values(), key=lambda x: x["t"])
    before = [i for i, x in enumerate(res) if x["t"] < since]
    # keep the last deploy before `since` as the baseline; older history is not analyzed
    return res[before[-1]:] if before else res


# ---------------------------------------------------------------- analysis

def analyze(path, deploys):
    """Fill commits, lead times and failures of each deploy, in place."""
    seen, sha2deploy, reverts = [], {}, []
    for i, d in enumerate(deploys):
        d["leads"], d["commits"] = [], 0
        try:
            git(path, "cat-file", "-e", d["sha"] + "^{commit}")
        except RuntimeError:
            d["missing"] = True
            continue
        if not seen:
            d["first"] = True  # carries all previous history: no lead times
            seen.append(d["sha"])
            for sha in git(path, "rev-list", d["sha"]).split():
                sha2deploy.setdefault(sha, i)
            continue
        out = git(path, "log", "--no-merges", "--format=%H%x1f%at%x1f%s%x1f%b%x1e", d["sha"], "--not", *seen[-MAX_NOT:])
        seen.append(d["sha"])
        for rec in out.split("\x1e"):
            rec = rec.strip("\n")
            if not rec:
                continue
            sha, at, subj, body = (rec.split("\x1f") + ["", ""])[:4]
            if sha in sha2deploy:
                continue
            sha2deploy[sha] = i
            d["commits"] += 1
            d["leads"].append(max(0.0, (d["t"] - from_unix(at)).total_seconds() / 3600))
            for r in RE_REVERT.findall(body):
                reverts.append((i, r))
            if RE_FIX.search(subj):
                d["fix"] = True
        if d["ref"].lower().startswith(("hotfix", "rollback")):
            d["fix"] = True

    def mark(i, j, kind):
        if i < 0 or i >= j or "failure" in deploys[i]:
            return
        if deploys[j]["t"] - deploys[i]["t"] > FAILURE_WINDOW:
            return
        deploys[i]["failure"] = {"kind": kind, "restoredBy": deploys[j]["ref"], "restoredAt": iso(deploys[j]["t"]),
                                 "restoreHours": round((deploys[j]["t"] - deploys[i]["t"]).total_seconds() / 3600, 2)}

    for j, r in reverts:
        i = next((v for k, v in sha2deploy.items() if k.startswith(r)), None)
        if i is not None:
            mark(i, j, "revert")
    for j, d in enumerate(deploys):
        if d.get("fix"):
            mark(j - 1, j, "hotfix")


def apply_overrides(deploys, overrides):
    for d in deploys:
        o = overrides.get(d["ref"])
        if o is None:
            continue
        if o.get("failure") is False:
            d.pop("failure", None)
        elif o.get("failure") is True and "failure" not in d:
            d["failure"] = {"kind": "manual", "restoredBy": None, "restoredAt": None, "restoreHours": o.get("restoreHours")}
        if "failure" in d and o.get("reason"):
            d["failure"]["reason"] = o["reason"]


def metrics(deploys, since, now):
    w = [d for d in deploys if since <= d["t"] <= now and not d.get("first")]
    days = max(1.0, (now - since).total_seconds() / 86400)
    leads = [x for d in w for x in d["leads"]]
    fails = [d for d in w if d.get("failure")]
    restores = [d["failure"]["restoreHours"] for d in fails if d["failure"].get("restoreHours") is not None]
    r = lambda v: None if v is None else round(v, 2)  # noqa: E731
    return {
        "deploys": len(w),
        "deploysPerWeek": round(len(w) / days * 7, 2),
        "leadTimeHours": {"median": r(quantile(leads, 0.5)), "p90": r(quantile(leads, 0.9)), "commits": len(leads)},
        "changeFailureRate": round(len(fails) / len(w), 3) if w else None,
        "failures": len(fails),
        "timeToRestoreHours": {"median": r(quantile(restores, 0.5)), "max": r(max(restores) if restores else None)},
    }


# ---------------------------------------------------------------- report

def fmt_hours(h):
    if h is None:
        return "—"
    if h < 48:
        return f"{h:.1f} h"
    return f"{h / 24:.1f} d"


def report(index):
    L = [f"# DORA metrics — last {index['windowDays']} days", "",
         f"Generated {index['generatedAt']}. Per repo, for the team; never per person.", "",
         "| Repo | Deploys | Per week | Lead time (median / p90) | Change failure rate | Time to restore (median) |",
         "|---|---|---|---|---|---|"]
    for r in index["repos"]:
        if r.get("error"):
            L.append(f"| {r['alias']} | error: {r['error'][:80]} | | | | |")
            continue
        m = r["metrics"]
        cfr = "—" if m["changeFailureRate"] is None else f"{m['changeFailureRate'] * 100:.0f}% ({m['failures']})"
        L.append(f"| {r['alias']} | {m['deploys']} | {m['deploysPerWeek']} | "
                 f"{fmt_hours(m['leadTimeHours']['median'])} / {fmt_hours(m['leadTimeHours']['p90'])} | {cfr} | "
                 f"{fmt_hours(m['timeToRestoreHours']['median'])} |")
    L += ["", "Deploys come from the `Deploys` column of repos.md (default: every commit on the base branch).",
          "Failures are a heuristic (reverts and hotfixes within 7 days); correct them in dora-overrides.json.", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="DORA metrics per repo for a hub")
    ap.add_argument("aliases", nargs="*")
    ap.add_argument("--hub", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--now", default=None, help="end of the window (ISO 8601); default: now")
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args(argv)

    hub = hublib.find_hub(a.hub) if a.hub else hublib.find_hub()
    if not hub:
        log("not inside a hub (no progress.md + repos.md)")
        return 1
    out = a.out or os.path.join(hub, ".dora")
    os.makedirs(out, exist_ok=True)
    now = parse_time(a.now) if a.now else datetime.now(timezone.utc)
    since = now - timedelta(days=a.days)
    overrides = {}
    ov = os.path.join(hub, "dora-overrides.json")
    if os.path.isfile(ov):
        with open(ov, encoding="utf-8") as f:
            overrides = json.load(f)

    index = {"generatedAt": iso(datetime.now(timezone.utc)), "windowDays": a.days, "windowEnd": iso(now), "repos": []}
    for r in hublib.load_repos(hub):
        if a.aliases and r["alias"] not in a.aliases:
            continue
        spec = (r.get("deploys") or "branch").strip() or "branch"
        log(f"== {r['alias']} ({spec})")
        try:
            repo = hublib.resolve(r)
            if not repo["exists"]:
                raise RuntimeError(f"no checkout at {repo['abspath']}")
            if not a.no_fetch:
                try:
                    git(repo["abspath"], "fetch", "origin", "--tags", "--quiet")
                except RuntimeError as e:
                    log(f"   fetch failed ({e}); using local refs")
            deploys = list_deploys(repo, spec, since - FAILURE_WINDOW * 4)
            analyze(repo["abspath"], deploys)
            apply_overrides(deploys, overrides.get(r["alias"], {}))
            m = metrics(deploys, since, now)
        except Exception as e:  # one broken repo does not stop the others
            log(f"   error: {e}")
            index["repos"].append({"alias": r["alias"], "deploys": spec, "error": str(e)[:300]})
            continue
        log(f"   {m['deploys']} deploys in window, {m['failures']} failures")
        index["repos"].append({"alias": r["alias"], "deploys": spec, "metrics": m})
        doc = {"alias": r["alias"], "deploysSpec": spec, "generatedAt": index["generatedAt"], "deploys": [
            {k: v for k, v in {
                "ref": d["ref"], "sha": d["sha"], "t": iso(d["t"]), "commits": d["commits"],
                "leadTimeHours": {"median": quantile(d["leads"], 0.5), "max": max(d["leads"]) if d["leads"] else None},
                "failure": d.get("failure"), "first": d.get("first"), "missing": d.get("missing"),
            }.items() if v is not None}
            for d in deploys]}
        with open(os.path.join(out, f"{r['alias']}.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write(report(index))
    print(os.path.join(out, "report.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
