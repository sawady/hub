"""Tests for plugin/scripts/hub.py. Run: python3 -m unittest discover -s tests"""
import io
import json
import os
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
                  "research/README.md", ".claude/settings.json", ".gitignore"):
            self.assertTrue(os.path.isfile(os.path.join(self.hub, f)), f)
        with open(os.path.join(self.hub, "CLAUDE.md")) as f:
            text = f.read()
        self.assertIn("hq — engineering hub of the web team", text)
        self.assertNotIn("{{", text)
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

    def test_context_size_cap(self):
        with open(os.path.join(self.hub, "progress.md"), "w") as f:
            f.write("## Now\n" + "".join(f"- {'x' * 300} {i}\n" for i in range(55)))
        out = hub.context(self.hub, with_prs=False)
        self.assertLessEqual(len(out), hub.MAX_CONTEXT_CHARS + 100)
        self.assertIn("truncated", out)

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
        for name in ("feature", "e2e", "status", "close", "merge", "init", "add-repo", "dora"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "plugin", "commands", f"{name}.md")), name)


if __name__ == "__main__":
    unittest.main()
