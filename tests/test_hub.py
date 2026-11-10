"""Tests for plugin/scripts/hub.py. Run: python3 -m unittest discover -s tests"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugin", "scripts"))
import hub  # noqa: E402

FAKES = os.path.join(ROOT, "tests", "fakes")


def git_repo(path, remote=None):
    subprocess.run(["git", "init", "-q", path], check=True)
    if remote:
        subprocess.run(["git", "-C", path, "remote", "add", "origin", remote], check=True)
    return path


class ParseRepos(unittest.TestCase):
    def test_table_with_backticks_and_extra_columns(self):
        text = """# Repos

Intro.

| Alias | Path | Base | Forge | About | Checks | Deploys |
|---|---|---|---|---|---|---|
| orders-api | `../orders-api` | main | github | Orders API (Go) | `make test` | tag:v* |
| storefront | `../web/storefront` | develop |  | Next.js app | `pnpm lint \\| cat` | |

| Other | Table |
|---|---|
| x | y |
"""
        rows = hub.parse_repos(text)
        self.assertEqual([r["alias"] for r in rows], ["orders-api", "storefront"])
        self.assertEqual(rows[0]["path"], "../orders-api")
        self.assertEqual(rows[0]["deploys"], "tag:v*")
        self.assertEqual(rows[1]["base"], "develop")
        self.assertEqual(rows[1]["forge"], "")
        self.assertEqual(rows[1]["checks"], "pnpm lint | cat")

    def test_spanish_headers_and_placeholder_rows(self):
        text = "| Alias | Ruta | Rama base | Qué es |\n|---|---|---|---|\n| <alias> | `../x` | main | x |\n| api | `../api` | main | API |\n"
        rows = hub.parse_repos(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], "../api")
        self.assertEqual(rows[0]["about"], "API")

    def test_no_table(self):
        self.assertEqual(hub.parse_repos("# nothing here\n"), [])

    def test_flow_column(self):
        text = ("| Alias | Path | Base | Flow | Forge |\n|---|---|---|---|---|\n"
                "| a | `../a` | master | direct | github |\n| b | `../b` | | | |\n| c | `../c` | main | Flujo? | |\n")
        rows = {r["alias"]: hub.resolve(dict(r, abspath="/nonexistent")) for r in hub.parse_repos(text)}
        self.assertEqual((rows["a"]["flow"], rows["a"]["base"]), ("direct", "master"))
        self.assertEqual((rows["b"]["flow"], rows["b"]["base"]), ("pr", "main"))
        self.assertEqual(rows["c"]["flow"], "pr")  # invalid values fall back to pr (doctor reports them)
        self.assertEqual(hub.parse_repos("| Alias | Path | Flujo |\n|---|---|---|\n| x | `../x` | directo |\n")[0]["flow"], "directo")
        self.assertEqual(hub.normalize_flow("Directo"), "direct")
        self.assertEqual(hub.normalize_flow("MR"), "pr")
        self.assertEqual(hub.normalize_flow("trunk"), "")


class Remotes(unittest.TestCase):
    def test_slugs(self):
        cases = {
            "git@github.com:acme/app.git": "acme/app",
            "https://github.com/acme/app": "acme/app",
            "https://user@gitlab.com/acme/platform/api.git": "acme/platform/api",
            "ssh://git@gitlab.example.org:2222/team/sub/svc.git": "team/sub/svc",
            "git@gitlab.example.org:team/svc.git": "team/svc",
        }
        for url, slug in cases.items():
            self.assertEqual(hub.remote_slug(url), slug, url)

    def test_hosts(self):
        self.assertEqual(hub.remote_host("git@github.com:acme/app.git"), "github.com")
        self.assertEqual(hub.remote_host("ssh://git@gitlab.example.org:2222/a/b.git"), "gitlab.example.org")
        self.assertEqual(hub.remote_host("https://code.acme.dev/a/b"), "code.acme.dev")

    def test_detect_forge(self):
        with tempfile.TemporaryDirectory() as d:
            gh = git_repo(os.path.join(d, "gh"), "git@github.com:acme/app.git")
            gl = git_repo(os.path.join(d, "gl"), "https://gitlab.com/acme/api.git")
            own = git_repo(os.path.join(d, "own"), "git@code.acme.dev:acme/api.git")
            none = git_repo(os.path.join(d, "none"))
            self.assertEqual(hub.detect_forge(gh), "github")
            self.assertEqual(hub.detect_forge(gl), "gitlab")
            self.assertEqual(hub.detect_forge(own), "unknown")
            self.assertEqual(hub.detect_forge(none), "unknown")
            self.assertEqual(hub.detect_forge(own, "glab"), "gitlab")  # declared wins
            self.assertEqual(hub.detect_forge(gh, "GitLab"), "gitlab")
            with mock.patch.dict(os.environ, {"HUB_GITLAB_HOSTS": "code.acme.dev"}):
                self.assertEqual(hub.detect_forge(own), "gitlab")


PROGRESS_EN = """# Progress

Last updated: 2026-03-02

## Now

### Resume here (2026-03-02)

- saved-carts — API PR in review

## Next

- gift receipts

## Blocked

- search reindex — waiting on the data team since 2026-02-27

## Paused

- dark mode

## Done

- 2026-02-28: checkout v2
"""


class Progress(unittest.TestCase):
    def test_now_and_blocked_only(self):
        out = hub.extract_sections(PROGRESS_EN, ["now", "blocked"])
        self.assertIn("## Now", out)
        self.assertIn("### Resume here (2026-03-02)", out)
        self.assertIn("search reindex", out)
        self.assertNotIn("gift receipts", out)
        self.assertNotIn("dark mode", out)
        self.assertNotIn("checkout v2", out)

    def test_spanish_headings(self):
        text = "## Ahora\n\n- a\n\n## Próximo\n\n- b\n\n## Bloqueado\n\n- c\n"
        out = hub.extract_sections(text, ["now", "blocked"])
        self.assertIn("- a", out)
        self.assertIn("- c", out)
        self.assertNotIn("- b", out)

    def test_heading_with_suffix(self):
        out = hub.extract_sections("## Now — week 9\n- x\n## Next\n- y\n", ["now"])
        self.assertIn("- x", out)
        self.assertNotIn("- y", out)

    def test_template_placeholders_are_left_out(self):
        with open(os.path.join(hub.TEMPLATE, "progress.md"), encoding="utf-8") as f:
            template = f.read()
        for text in (template, hub.translate(template, hub.SPANISH)):
            out = hub.extract_sections(text, ["now", "blocked"])
            self.assertNotIn("<", out)
            self.assertNotIn("YYYY-MM-DD", out)
            self.assertNotIn("What is in flight", out)
            self.assertNotIn("\n\n\n", out)
        text = template.replace("- <item> — blocked on <who/what>, since YYYY-MM-DD", "- search — blocked on infra, since 2026-03-01")
        out = hub.extract_sections(text, ["now", "blocked"])
        self.assertIn("- search — blocked on infra, since 2026-03-01", out)
        self.assertNotIn("<feature or task>", out)

    def test_real_lines_are_kept(self):
        text = "## Now\n\n### Resume here (2026-03-02)\n\n- api <-> web contract — next: review\n  - <b>nested</b> stays\n"
        out = hub.extract_sections(text, ["now"])
        self.assertIn("### Resume here (2026-03-02)", out)
        self.assertIn("- api <-> web contract — next: review", out)
        self.assertIn("  - <b>nested</b> stays", out)  # only top-level `- <` bullets are placeholders
        self.assertEqual(hub.extract_sections(PROGRESS_EN, ["now", "blocked"]).count("\n\n\n"), 0)

    def test_truncation(self):
        text = "## Now\n" + "".join(f"- line {i}\n" for i in range(200))
        out = hub.extract_sections(text, ["now"], max_lines=10)
        self.assertIn("truncated", out)
        self.assertNotIn("line 50", out)


class HubFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.hub = hub.init(os.path.join(self.d, "hq"), "hq", "the web team")
        git_repo(os.path.join(self.d, "orders-api"), "git@github.com:acme/orders-api.git")
        git_repo(os.path.join(self.d, "storefront"), "https://gitlab.com/acme/storefront.git")

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_files(self):
        for f in ("CLAUDE.md", "progress.md", "repos.md", "features/_template.md", "journal/README.md",
                  "research/README.md", "decisions/README.md", "decisions/_template.md",
                  ".claude/settings.json", ".gitignore"):
            self.assertTrue(os.path.isfile(os.path.join(self.hub, f)), f)
        with open(os.path.join(self.hub, "CLAUDE.md")) as f:
            text = f.read()
        self.assertIn("hq — engineering hub of the web team", text)
        self.assertNotIn("{{", text)
        self.assertIn("decisions/NNNN-<title>.md", text)
        self.assertIn("Flow `direct`", text)
        self.assertEqual(hub.load_repos(self.hub), [])  # placeholder row is not a repo
        with open(os.path.join(self.hub, ".claude", "settings.json")) as f:
            settings = json.load(f)
        self.assertIn("Bash(git push --force*)", settings["permissions"]["deny"])
        self.assertTrue(settings["enabledPlugins"]["hub@hub"])

    def test_init_spanish(self):
        es = hub.init(os.path.join(self.d, "hq-es"), "hq", "yo", lang="es")
        with open(os.path.join(es, "progress.md")) as f:
            text = f.read()
        self.assertIn("## Ahora", text)
        self.assertIn("### Retomar acá", text)
        self.assertIn("## Bloqueado", text)
        self.assertIn("Última actualización", text)
        with open(os.path.join(es, "decisions", "_template.md")) as f:
            text = f.read()
        for h in ("# NNNN — <Título>", "**Estado:** Aceptada", "## Contexto", "## Decisión", "## Consecuencias"):
            self.assertIn(h, text)
        self.assertNotIn("## Context\n", text)
        with open(os.path.join(self.hub, "decisions", "_template.md")) as f:
            self.assertIn("## Consequences", f.read())  # English hub untouched

    def test_init_refuses_existing(self):
        with self.assertRaises(SystemExit):
            hub.init(self.hub, "hq", "x")

    def test_add_repo_and_settings(self):
        hub.add_repo(self.hub, "orders-api", "../orders-api", about="Orders API", checks="make test")
        hub.add_repo(self.hub, "storefront", "../storefront", base="develop")
        rows = [hub.resolve(r) for r in hub.load_repos(self.hub)]
        self.assertEqual([(r["alias"], r["forge"], r["slug"]) for r in rows],
                         [("orders-api", "github", "acme/orders-api"), ("storefront", "gitlab", "acme/storefront")])
        self.assertEqual(rows[1]["base"], "develop")
        with open(os.path.join(self.hub, ".claude", "settings.json")) as f:
            dirs = json.load(f)["permissions"]["additionalDirectories"]
        self.assertEqual(dirs, ["../orders-api", "../storefront"])
        self.assertEqual(hub.sync_settings(self.hub), [])  # idempotent
        with open(os.path.join(self.hub, ".claude", "agents", "orders-api.md")) as f:
            agent = f.read()
        self.assertIn("name: orders-api", agent)
        self.assertIn("make test", agent)
        self.assertNotIn("{{", agent)
        with self.assertRaises(SystemExit):
            hub.add_repo(self.hub, "orders-api", "../orders-api")
        with self.assertRaises(SystemExit):
            hub.add_repo(self.hub, "Bad Alias", "../x")

    def test_add_repo_flow(self):
        hub.add_repo(self.hub, "orders-api", "../orders-api", checks="make lint | cat")
        hub.add_repo(self.hub, "storefront", "../storefront", base="master", flow="direct")
        with open(os.path.join(self.hub, "repos.md")) as f:
            text = f.read()
        self.assertIn("| Alias | Path | Base | Flow | Forge | About | Checks |", text)
        self.assertIn("| orders-api | `../orders-api` | main | pr | github |  | `make lint \\| cat` |", text)
        rows = {r["alias"]: hub.resolve(r) for r in hub.load_repos(self.hub)}
        self.assertEqual(rows["orders-api"]["checks"], "make lint | cat")
        self.assertEqual((rows["storefront"]["flow"], rows["storefront"]["base"]), ("direct", "master"))
        with open(os.path.join(self.hub, ".claude", "agents", "storefront.md")) as f:
            agent = f.read()
        self.assertIn("Flow `direct`", agent)
        self.assertIn("Never push to `master` yourself", agent)
        with open(os.path.join(self.hub, ".claude", "agents", "orders-api.md")) as f:
            self.assertIn("changes reach it through a PR/MR", f.read())
        with self.assertRaises(SystemExit):
            hub.add_repo(self.hub, "x", "../x", flow="trunk")

    def test_add_repo_direct_adds_flow_column_to_an_old_table(self):
        with open(os.path.join(self.hub, "repos.md"), "w") as f:
            f.write("# Repos\n\n| Alias | Path | Base | Forge | About | Checks | Deploys |\n|---|---|---|---|---|---|---|\n"
                    "| orders-api | `../orders-api` | main | github | API | `make test` | tag:v* |\n\n## Notes\n")
        hub.add_repo(self.hub, "notifier", "../notifier", forge="github", deploys="branch")  # pr: no new column
        with open(os.path.join(self.hub, "repos.md")) as f:
            self.assertNotIn("Flow", f.read())
        hub.add_repo(self.hub, "storefront", "../storefront", flow="direct")
        with open(os.path.join(self.hub, "repos.md")) as f:
            text = f.read()
        self.assertIn("| Alias | Path | Base | Flow | Forge | About | Checks | Deploys |", text)
        self.assertIn("\n## Notes\n", text)
        rows = {r["alias"]: r for r in hub.load_repos(self.hub)}
        self.assertEqual(rows["orders-api"]["deploys"], "tag:v*")
        self.assertEqual(rows["orders-api"]["checks"], "make test")
        self.assertEqual(rows["notifier"]["deploys"], "branch")
        self.assertEqual(rows["storefront"]["flow"], "direct")
        self.assertEqual(rows["storefront"]["forge"], "gitlab")
        self.assertEqual([hub.resolve(r)["flow"] for r in hub.load_repos(self.hub)], ["pr", "pr", "direct"])

    def test_doctor_reports_unknown_flow(self):
        with open(os.path.join(self.hub, "repos.md"), "w") as f:
            f.write("| Alias | Path | Flow | Forge |\n|---|---|---|---|\n| orders-api | `../orders-api` | trunk | github |\n")
        problems, report = hub.doctor(self.hub)
        self.assertGreaterEqual(problems, 1)
        self.assertIn("unknown Flow 'trunk'", report)

    def test_find_hub_walks_up(self):
        sub = os.path.join(self.hub, "features")
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""}):
            self.assertEqual(hub.find_hub(sub), self.hub)
        self.assertIsNone(hub.find_hub(self.d))

    def test_context_with_fake_forges(self):
        hub.add_repo(self.hub, "orders-api", "../orders-api")
        hub.add_repo(self.hub, "storefront", "../storefront")
        with open(os.path.join(self.hub, "progress.md"), "w") as f:
            f.write(PROGRESS_EN)
        fake = os.path.join(self.d, "fake")
        os.makedirs(fake)
        with open(os.path.join(fake, "pr-list.json"), "w") as f:
            json.dump([{"number": 41, "title": "Saved carts API", "isDraft": True, "url": "u", "headRefName": "feat/saved-carts"}], f)
        with open(os.path.join(fake, "mr-list.json"), "w") as f:
            json.dump([{"iid": 17, "title": "Saved carts page", "draft": False, "web_url": "u", "source_branch": "feat/saved-carts"}], f)
        with open(os.path.join(fake, "calls"), "w"):
            pass
        env = {"PATH": FAKES + os.pathsep + os.environ["PATH"], "FAKE_DIR": fake}
        with mock.patch.dict(os.environ, env):
            out = hub.context(self.hub)
        self.assertIn("saved-carts — API PR in review", out)
        self.assertIn("#41 Saved carts API [draft] — feat/saved-carts", out)
        self.assertIn("!17 Saved carts page — feat/saved-carts", out)
        self.assertNotIn("checkout v2", out)

    def _fake(self):
        fake = os.path.join(self.d, "fake")
        os.makedirs(fake, exist_ok=True)
        open(os.path.join(fake, "calls"), "a").close()
        return fake, {"PATH": FAKES + os.pathsep + os.environ["PATH"], "FAKE_DIR": fake}

    def test_red_ci_in_context(self):
        git_repo(os.path.join(self.d, "notifier"), "git@github.com:acme/notifier.git")
        hub.add_repo(self.hub, "orders-api", "../orders-api")                 # github, base main: red
        hub.add_repo(self.hub, "storefront", "../storefront", base="develop")  # gitlab, base develop: red
        hub.add_repo(self.hub, "notifier", "../notifier", base="trunk")        # github, base trunk: green
        with open(os.path.join(self.hub, "progress.md"), "w") as f:
            f.write(PROGRESS_EN)
        fake, env = self._fake()
        with open(os.path.join(fake, "runs-branch-main.json"), "w") as f:
            json.dump([{"status": "completed", "conclusion": "failure", "workflowName": "ci",
                        "displayTitle": "Bump deps", "url": "https://example.com/run/1", "headSha": "abc"}], f)
        with open(os.path.join(fake, "runs-branch-trunk.json"), "w") as f:
            json.dump([{"status": "completed", "conclusion": "success", "workflowName": "ci", "displayTitle": "x",
                        "url": "u", "headSha": "def"}], f)
        with open(os.path.join(fake, "pipelines-ref-develop.json"), "w") as f:
            json.dump([{"id": 9, "status": "failed", "web_url": "https://example.com/p/9", "sha": "123", "source": "push"}], f)
        with mock.patch.dict(os.environ, env):
            out = hub.context(self.hub)
            ci = {r["alias"]: c["state"] for r, c in hub.all_ci([hub.resolve(r) for r in hub.load_repos(self.hub)])}
            buf = io.StringIO()
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.hub}), redirect_stdout(buf):
                hub.main(["ci", "--red"])
        self.assertEqual(ci, {"orders-api": "failure", "storefront": "failure", "notifier": "success"})
        self.assertIn("## Red CI (latest run on the base branch)", out)
        self.assertIn("- orders-api (main): failed — ci — Bump deps — https://example.com/run/1", out)
        self.assertIn("- storefront (develop): failed — pipeline 9 — https://example.com/p/9", out)
        self.assertNotIn("notifier (trunk)", out)
        self.assertLess(out.index("## Red CI"), out.index("## My open PRs / MRs"))
        self.assertEqual(sorted(line.split("\t")[0] for line in buf.getvalue().splitlines()), ["orders-api", "storefront"])
        with open(os.path.join(fake, "calls")) as f:
            calls = f.read()
        self.assertIn("gh run list --json status,conclusion,workflowName,displayTitle,url,headSha --branch main -L 1", calls)
        self.assertIn("glab ci list --output json --ref develop --per-page 1", calls)

    def test_red_ci_none_unknown_and_skip(self):
        hub.add_repo(self.hub, "orders-api", "../orders-api")
        fake, env = self._fake()
        with mock.patch.dict(os.environ, env):
            out = hub.context(self.hub, with_prs=False)
            self.assertIn("## Red CI (latest run on the base branch)\n\n(none)", out)
            self.assertNotIn("My open PRs", out)
            open(os.path.join(fake, "gh-fail"), "w").close()
            out = hub.context(self.hub, with_prs=False)
            self.assertIn("(could not read CI for: orders-api)", out)
            os.remove(os.path.join(fake, "gh-fail"))
            open(os.path.join(fake, "calls"), "w").close()
            buf = io.StringIO()
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.hub, "HUB_SKIP_CI": "1", "HUB_SKIP_PRS": "1"}), redirect_stdout(buf):
                hub.main(["context"])
        self.assertNotIn("Red CI", buf.getvalue())
        self.assertNotIn("My open PRs", buf.getvalue())
        with open(os.path.join(fake, "calls")) as f:
            self.assertEqual(f.read(), "")  # no forge calls at all

    def test_ci_state_for_a_commit(self):
        fake, env = self._fake()
        repo = os.path.join(self.d, "orders-api")
        runs = [{"status": "completed", "conclusion": "success", "url": "u1"},
                {"status": "in_progress", "conclusion": "", "url": "u2"}]
        with open(os.path.join(fake, "runs-commit-abc"), "w") as f:
            f.write(json.dumps(runs) + "\n" + json.dumps([runs[0], dict(runs[1], status="completed", conclusion="cancelled")]) + "\n")
        with open(os.path.join(fake, "pipelines-sha-def"), "w") as f:
            f.write(json.dumps([{"status": "manual", "web_url": "w"}]) + "\n")
        with mock.patch.dict(os.environ, env):
            self.assertEqual(hub.ci_state(repo, "github", sha="abc")["state"], "pending")
            c = hub.ci_state(repo, "github", sha="abc")
            self.assertEqual((c["state"], c["url"]), ("cancelled", "u2"))
            self.assertEqual(hub.ci_state(repo, "github", sha="nothing")["state"], "none")
            self.assertEqual(hub.ci_state(repo, "gitlab", sha="def")["state"], "manual")
            self.assertEqual(hub.ci_state(repo, "unknown", sha="def")["state"], "unknown")

    def test_forge_timeout_fits_the_hook(self):
        self.assertEqual(hub.forge_timeout(4), 8)
        self.assertEqual(hub.forge_timeout(16), 8)
        self.assertEqual(hub.forge_timeout(17), 8)   # two waves of 8 s
        self.assertEqual(hub.forge_timeout(40), 5)   # three waves
        self.assertEqual(hub.forge_timeout(400), 2)  # floor
        for n in (1, 16, 17, 32, 33, 48, 64):
            waves = -(-n // hub.FORGE_WORKERS)
            self.assertLessEqual(waves * hub.forge_timeout(n), hub.FORGE_BUDGET, n)

    def test_new_decision(self):
        p1 = hub.new_decision(self.hub, "Work directly on main", today="2026-03-01")
        p2 = hub.new_decision(self.hub, "Licencias: BSD-3 para la librería", today="2026-03-02")
        self.assertEqual(os.path.basename(p1), "0001-work-directly-on-main.md")
        self.assertEqual(os.path.basename(p2), "0002-licencias-bsd-3-para-la-libreria.md")
        p3 = hub.new_decision(self.hub, "PRs again", supersedes=1, today="2026-03-09")
        self.assertEqual(os.path.basename(p3), "0003-prs-again.md")
        with open(p3) as f:
            text = f.read()
        self.assertTrue(text.startswith("# 0003 — PRs again\n"))
        self.assertIn("- **Date:** 2026-03-09", text)
        self.assertIn("- **Supersedes:** [0001](0001-work-directly-on-main.md)", text)
        with open(p1) as f:
            old = f.read()
        self.assertIn("- **Status:** Superseded by [0003](0003-prs-again.md)", old)
        self.assertIn("# 0001 — Work directly on main", old)  # nothing else changes
        with self.assertRaises(SystemExit):
            hub.new_decision(self.hub, "x", supersedes=42)
        es = hub.init(os.path.join(self.d, "hq-es"), "hq", "yo", lang="es")
        hub.new_decision(es, "Trabajar en main", today="2026-03-01")
        p = hub.new_decision(es, "Volver a PRs", supersedes=1, today="2026-03-02")
        with open(os.path.join(es, "decisions", "0001-trabajar-en-main.md")) as f:
            self.assertIn("- **Estado:** Reemplazada por [0002](0002-volver-a-prs.md)", f.read())
        with open(p) as f:
            self.assertIn("- **Fecha:** 2026-03-02", f.read())

    def test_context_size_cap(self):
        with open(os.path.join(self.hub, "progress.md"), "w") as f:
            f.write("## Now\n" + "".join(f"- {'x' * 300} {i}\n" for i in range(55)))
        out = hub.context(self.hub, with_prs=False)
        self.assertLessEqual(len(out), hub.MAX_CONTEXT_CHARS + 100)
        self.assertIn("truncated", out)

    def test_context_of_a_fresh_hub_has_no_placeholders(self):
        out = hub.context(self.hub, with_prs=False, with_ci=False)
        self.assertIn("(Now and Blocked are empty)", out)
        self.assertNotIn("<", out)
        self.assertNotIn("YYYY", out)

    def test_cli_context_silent_outside_hub(self):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.d}), mock.patch("os.getcwd", return_value=self.d), redirect_stdout(buf):
            self.assertEqual(hub.main(["context"]), 0)
        self.assertEqual(buf.getvalue(), "")


class PluginLayout(unittest.TestCase):
    """The plugin files that Claude Code loads are well formed."""

    def test_manifests(self):
        with open(os.path.join(ROOT, "plugin", ".claude-plugin", "plugin.json")) as f:
            plugin = json.load(f)
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as f:
            market = json.load(f)
        self.assertEqual(plugin["name"], "hub")
        self.assertEqual(market["plugins"][0]["name"], plugin["name"])
        self.assertEqual(market["plugins"][0]["source"], "./plugin")
        with open(os.path.join(ROOT, "plugin", "hooks", "hooks.json")) as f:
            hooks = json.load(f)
        cmd = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/hub.py", cmd)

    def test_commands_and_agents_have_frontmatter(self):
        for sub in ("commands", "agents"):
            d = os.path.join(ROOT, "plugin", sub)
            for fn in os.listdir(d):
                with open(os.path.join(d, fn)) as f:
                    text = f.read()
                self.assertTrue(text.startswith("---\n"), fn)
                head = text.split("---\n")[1]
                self.assertIn("description:", head, fn)
        for name in ("feature", "e2e", "status", "close", "merge", "init", "add-repo", "dora", "decision"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "plugin", "commands", f"{name}.md")), name)


class Portfolio(unittest.TestCase):
    PROGRESS = """# Progress

Last updated: 2026-03-02

## Now

### Resume here (2026-03-02)

- **orders-api** — saved carts endpoints in review — next: merge #41 (`features/saved-carts.md`)
- checkout latency — p95 regression, seen from storefront and
  orders-api; nothing confirmed yet.
  - notifier is a nested bullet and does not count

## Next

- notifier — retry policy for failed emails
- `storefront`: dark mode — Next: pick the tokens. Then ask design.

## Blocked

- search-indexer — waiting on the data team for the catalog export, since 2026-02-27

## Paused

- invoices — paused on 2026-02-20 for saved carts

## Done

### Week of 2026-02-23

- 2026-02-26: warehouse shipped
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hub = self.tmp.name

    def write(self, progress=None, aliases=("orders-api",)):
        with open(os.path.join(self.hub, "progress.md"), "w", encoding="utf-8") as f:
            f.write(self.PROGRESS if progress is None else progress)
        rows = "".join(f"| {a} | `../{a}` | main | github |\n" for a in aliases)
        with open(os.path.join(self.hub, "repos.md"), "w", encoding="utf-8") as f:
            f.write("| Alias | Path | Base | Forge |\n|---|---|---|---|\n" + rows)

    def rows(self, *aliases, progress=None):
        self.write(progress, aliases)
        rows, lang = hub.portfolio(self.hub)
        return {r["project"]: r for r in rows}, lang

    def test_bullet_that_starts_with_the_alias_wins_over_a_mention(self):
        rows, lang = self.rows("orders-api")
        self.assertEqual(lang, "en")
        self.assertEqual(rows["orders-api"]["state"], "saved carts endpoints in review")
        self.assertEqual(rows["orders-api"]["next"], "merge #41")
        self.assertEqual(rows["orders-api"]["section"], "now")

    def test_head_in_a_later_section_beats_a_mention_in_now(self):
        rows, _ = self.rows("storefront")
        self.assertEqual(rows["storefront"]["section"], "next")
        self.assertEqual(rows["storefront"]["state"], "queued")
        self.assertEqual(rows["storefront"]["next"], "pick the tokens")

    def test_only_a_mention(self):
        text = "## Now\n\n- saved carts: api #41 and the storefront page are up. Next: e2e on staging.\n"
        rows, _ = self.rows("storefront", progress=text)
        self.assertEqual(rows["storefront"]["state"], "saved carts: api #41 and the storefront page are up.")
        self.assertEqual(rows["storefront"]["next"], "e2e on staging")

    def test_next_section_without_marker(self):
        rows, _ = self.rows("notifier")
        self.assertEqual(rows["notifier"]["state"], "queued")
        self.assertEqual(rows["notifier"]["next"], "retry policy for failed emails")

    def test_next_step_comes_from_the_next_section(self):
        text = "## Now\n\n- api — rewriting auth\n\n## Next\n\n- api — rate limits\n"
        rows, _ = self.rows("api", progress=text)
        self.assertEqual(rows["api"]["state"], "rewriting auth")
        self.assertEqual(rows["api"]["next"], "rate limits")

    def test_blocked_and_paused(self):
        rows, _ = self.rows("search-indexer", "invoices")
        self.assertEqual(rows["search-indexer"]["state"],
                         "blocked: waiting on the data team for the catalog export, since 2026-02-27")
        self.assertEqual(rows["invoices"]["state"], "paused: paused on 2026-02-20 for saved carts")

    def test_only_a_next_step(self):
        rows, _ = self.rows("api", progress="## Now\n\n- api — next: ship it\n")
        self.assertEqual(rows["api"]["state"], "in progress")
        self.assertEqual(rows["api"]["next"], "ship it")

    def test_done_nested_bullets_and_placeholders_do_not_count(self):
        text = self.PROGRESS + "\n## Now\n\n- <feature or task> — <state> — next: <warehouse>\n"
        rows, _ = self.rows("warehouse", progress=text)
        self.assertEqual(rows["warehouse"]["state"], "")
        rows, _ = self.rows("notifier", progress="## Now\n\n- x\n  - notifier nested\n")
        self.assertEqual(rows["notifier"]["section"], "")

    def test_alias_is_a_whole_name(self):
        text = "## Now\n\n- orders-api is up; see `docs/api.md` and api-docs\n"
        rows, _ = self.rows("api", "orders", progress=text)
        self.assertEqual(rows["api"]["section"], "")
        self.assertEqual(rows["orders"]["section"], "")

    def test_nothing_about_the_repo(self):
        rows, lang = self.rows("ghost")
        self.assertEqual((rows["ghost"]["state"], rows["ghost"]["next"]), ("", ""))
        table = hub.portfolio_table(list(rows.values()), lang)
        self.assertIn("| ghost | `../ghost` | — | — |", table)

    def test_spanish_headings_give_a_spanish_table(self):
        text = ("## Ahora\n\n- **api** — en review — próximo paso: mergear\n\n"
                "## Próximo\n\n- web — tema oscuro\n\n## Bloqueado\n\n- jobs — espera datos\n")
        rows, lang = self.rows("api", "web", "jobs", progress=text)
        self.assertEqual(lang, "es")
        self.assertEqual((rows["api"]["state"], rows["api"]["next"]), ("en review", "mergear"))
        self.assertEqual(rows["web"]["state"], "en cola")
        self.assertEqual(rows["jobs"]["state"], "bloqueado: espera datos")
        table = hub.portfolio_table(list(rows.values()), lang)
        self.assertTrue(table.startswith("| Proyecto | Repo | Estado | Próximo paso |"))

    def test_table_stays_on_one_line_per_repo(self):
        rows = [{"project": "a|b", "repo": "acme/a", "state": "x | y " * 60, "next": "", "section": "now"}]
        table = hub.portfolio_table(rows, "en").splitlines()
        self.assertEqual(len(table), 3)
        self.assertIn("a\\|b", table[2])
        self.assertIn("…", table[2])
        self.assertLess(len(table[2]), 260)

    def test_repo_is_the_slug_when_there_is_a_checkout(self):
        git_repo(os.path.join(self.hub, "..", os.path.basename(self.hub) + "-orders"), "git@github.com:acme/orders-api.git")
        checkout = os.path.join(self.hub, "..", os.path.basename(self.hub) + "-orders")
        self.addCleanup(shutil.rmtree, checkout)
        self.write(aliases=())
        with open(os.path.join(self.hub, "repos.md"), "a", encoding="utf-8") as f:
            f.write(f"| orders-api | `{checkout}` | main | github |\n")
        rows, _ = hub.portfolio(self.hub)
        self.assertEqual(rows[0]["repo"], "acme/orders-api")

    def test_update_only_touches_the_marked_block_and_is_idempotent(self):
        path = os.path.join(self.hub, "README.md")
        original = "# Hub\n\n<!-- hub:portfolio -->\nold table\n<!-- /hub:portfolio -->\n\nCaf\u00e9 \\1 notes.\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(original)
        hub.update_portfolio_block(path, "| a \\| b |")
        with open(path, encoding="utf-8") as f:
            once = f.read()
        self.assertEqual(once, "# Hub\n\n<!-- hub:portfolio -->\n| a \\| b |\n<!-- /hub:portfolio -->\n\nCaf\u00e9 \\1 notes.\n")
        hub.update_portfolio_block(path, "| a \\| b |")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), once)

    def test_update_refuses_without_markers_and_leaves_the_file_alone(self):
        path = os.path.join(self.hub, "README.md")
        for text in ("# Hub\n", "<!-- /hub:portfolio -->\n<!-- hub:portfolio -->\n"):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            with self.assertRaises(SystemExit):
                hub.update_portfolio_block(path, "x")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), text)
        with self.assertRaises(SystemExit):
            hub.update_portfolio_block(os.path.join(self.hub, "missing.md"), "x")


if __name__ == "__main__":
    unittest.main()
