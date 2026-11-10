#!/usr/bin/env python3
"""Regenerate radar.md, the versioned mirror of the Radar artifact, from a dump of its database.

Usage: radar-md.py [--dump DIR] [--out FILE] [--title TITLE] [--url URL] [--tz +HH:MM]
  --dump   directory with items/<id>.json and requests/<uid>.json (default: .radar-db), as
           written by ArtifactData `list` with `out_dir`
  --out    default: radar.md
  --url    the Radar artifact URL, linked at the top
  --tz     offset used for dates in the mirror (default: UTC)

The mirror never names who filed a request (creators are opaque ids in the database); it keeps
the free-text "asked by" label (a team or role) that the request itself carries.
"""
import argparse
import glob
import json
import os
import re
from datetime import datetime, timedelta, timezone

STATES = ["Priority", "In progress", "In review", "Inbox", "Later", "Shipped", "Dropped"]


def tz_from(s):
    m = re.match(r"^([+-])(\d{2}):?(\d{2})$", s or "")
    if not m:
        return timezone.utc
    d = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    return timezone(d if m.group(1) == "+" else -d)


def ymd(t, tz):
    if not t:
        return ""
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00")).astimezone(tz).strftime("%Y-%m-%d")
    except ValueError:  # anyone with Contributor access can write their own documents
        return ""


def load(dump):
    items = []
    for f in sorted(glob.glob(os.path.join(dump, "items", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        d.setdefault("id", os.path.splitext(os.path.basename(f))[0])
        items.append(d)
    ids = {i["id"] for i in items}
    for f in sorted(glob.glob(os.path.join(dump, "requests", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            doc = json.load(fh)
        for rid, r in (doc.get("items") or {}).items():
            if rid not in ids:
                items.append({**r, "id": rid, "state": "Inbox", "kind": r.get("kind") or "Request", "pending": True})
    return items


def safe_links(i):
    return [l for l in i.get("links") or [] if str(l.get("url", "")).startswith(("http://", "https://"))]


def line(i, tz, rank=None):
    head = (f"**#{rank}** " if rank else "") + f"**{(i.get('title') or '').strip()}**"
    meta = []
    if i.get("kind") == "Tech task":
        meta.append("tech task")
    if i.get("requestedBy"):
        meta.append(f"asked by {i['requestedBy']}")
    if i.get("waitingOn"):
        meta.append("**waiting on " + ", ".join(i["waitingOn"]) + "**")
    if i.get("pending"):
        meta.append("new, untriaged")
    filed = ymd(i.get("createdAt"), tz)
    if filed:
        meta.append(f"filed {filed}")
    s = head + (" — " + " · ".join(meta) if meta else "")
    links = [f"[{l.get('label') or l['url']}]({l['url']})" for l in safe_links(i)]
    if links:
        s += "  \n  " + " · ".join(links)
    desc = (i.get("description") or "").strip().replace("\n", " ")
    if desc:
        s += f"  \n  {desc}"
    return f"- {s}"


def by_order(i):
    return (i.get("order") is None, i.get("order") or 0, i.get("createdAt") or "")


def render(items, title, url, tz, now=None):
    by = {s: [i for i in items if i.get("state") == s] for s in STATES}
    when = (now or datetime.now(tz)).astimezone(tz).strftime("%Y-%m-%d %H:%M %z")
    src = f"[{title}]({url})" if url else title
    L = [f"# {title} (mirror)", "",
         f"> Versioned mirror of {src}, which is the source of truth. Do not edit by hand: the `radar`",
         f"> skill regenerates it. Generated {when} with {len(items)} items.", "",
         "Summary: " + " · ".join(f"{s} {len(by[s])}" for s in STATES), ""]

    def by_area(lst):
        if not lst:
            L.extend(["- Nothing.", ""])
            return
        for a in sorted({i.get("area") or "No area" for i in lst}):
            L.extend([f"### {a}", ""])
            sub = sorted((i for i in lst if (i.get("area") or "No area") == a), key=lambda i: i.get("createdAt") or "")
            L.extend(line(i, tz) for i in sub)
            L.append("")

    L += ["## Priority", "", "In the order they will be tackled.", ""]
    L += [line(i, tz, n + 1) for n, i in enumerate(sorted(by["Priority"], key=by_order))] or ["- Nothing."]
    L.append("")
    for s in ("In progress", "In review"):
        L += [f"## {s}", ""]
        L += [line(i, tz) for i in sorted(by[s], key=by_order)] or ["- Nothing."]
        L.append("")
    L += ["## Inbox", "", "Not triaged yet, by area.", ""]
    by_area(by["Inbox"])
    L += ["## Later", ""]
    by_area(by["Later"])
    L += ["## Shipped", "", "| Date | Item | Area | Asked by | Links |", "|---|---|---|---|---|"]
    for i in sorted(by["Shipped"], key=lambda i: i.get("shippedAt") or "", reverse=True):
        links = " ".join(f"[{l.get('label') or 'link'}]({l['url']})" for l in safe_links(i))
        cell = lambda v: str(v or "").replace("|", "\\|")  # noqa: E731
        L.append(f"| {ymd(i.get('shippedAt'), tz) or 'no date'} | {cell(i.get('title'))} | {cell(i.get('area'))} | "
                 f"{cell(i.get('requestedBy'))} | {links} |")
    L += ["", "## Dropped", ""]
    L += [line(i, tz) for i in by["Dropped"]] or ["- Nothing."]
    L.append("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dump", default=".radar-db")
    ap.add_argument("--out", default="radar.md")
    ap.add_argument("--title", default="Radar")
    ap.add_argument("--url", default="")
    ap.add_argument("--tz", default="+00:00")
    a = ap.parse_args(argv)
    items = load(a.dump)
    text = render(items, a.title, a.url, tz_from(a.tz))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"{a.out}: {len(items)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
