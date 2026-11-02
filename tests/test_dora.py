"""Tests for plugin/scripts/dora.py on a git fixture with controlled dates."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugin", "scripts"))
import dora  # noqa: E402
import hub  # noqa: E402

AUTHOR = "Pat Example"
EMAIL = "pat@example.com"


def t(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


class Fixture:
    def __init__(self, path):
        self.path = path
        subprocess.run(["git", "init", "-q", "-b", "main", path], check=True)

    def commit(self, msg, authored, committed=None, body=""):
        env = dict(os.environ, GIT_AUTHOR_NAME=AUTHOR, GIT_AUTHOR_EMAIL=EMAIL, GIT_COMMITTER_NAME=AUTHOR,
                   GIT_COMMITTER_EMAIL=EMAIL, GIT_AUTHOR_DATE=authored + " +0000",
                   GIT_COMMITTER_DATE=(committed or authored) + " +0000")
        with open(os.path.join(self.path, "f.txt"), "a") as f:
            f.write(msg + "\n")
        subprocess.run(["git", "-C", self.path, "add", "."], check=True)
        args = ["git", "-C", self.path, "commit", "-q", "-m", msg] + (["-m", body] if body else [])
        subprocess.run(args, check=True, env=env)
        return subprocess.run(["git", "-C", self.path, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

    def tag(self, name, when):
        env = dict(os.environ, GIT_COMMITTER_NAME=AUTHOR, GIT_COMMITTER_EMAIL=EMAIL, GIT_COMMITTER_DATE=when + " +0000")
        subprocess.run(["git", "-C", self.path, "tag", "-a", name, "-m", name], check=True, env=env)


class Quantile(unittest.TestCase):
    def test_quantile(self):
        self.assertIsNone(dora.quantile([], 0.5))
        self.assertEqual(dora.quantile([3], 0.9), 3)
        self.assertEqual(dora.quantile([1, 2, 3, 4, 5], 0.5), 3)
        self.assertEqual(dora.quantile([5, 1, 4, 2, 3], 0.9), 5)

    def test_json_pages(self):
        # gh/glab --paginate print one array per page back to back
        self.assertEqual(dora._json([sys.executable, "-c", "print('[1,2]\\n[3]')"]), [1, 2, 3])


class BranchDeploys(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Fixture(os.path.join(self.tmp.name, "app"))
        r = self.repo
        r.commit("initial", "2025-12-20T00:00:00")
        r.commit("add carts", "2026-01-02T00:00:00", "2026-01-02T10:00:00")          # lead 10 h
        self.bad = r.commit("add saved carts", "2026-01-03T00:00:00", "2026-01-03T02:00:00")  # lead 2 h, reverted
        r.commit(f'Revert "add saved carts"', "2026-01-03T05:00:00",
                 body=f"This reverts commit {self.bad}.")                             # restores after 3 h
        r.commit("fix: tidy", "2026-01-20T00:00:00", "2026-01-20T04:00:00")          # lead 4 h

    def tearDown(self):
        self.tmp.cleanup()

    def run_branch(self, overrides=None):
        deploys = dora.list_deploys({"abspath": self.repo.path, "base": "main"}, "branch", t("2026-01-01T00:00:00"))
        dora.analyze(self.repo.path, deploys)
        if overrides:
            dora.apply_overrides(deploys, overrides)
        return deploys, dora.metrics(deploys, t("2026-01-01T00:00:00"), t("2026-01-31T00:00:00"))

    def test_metrics(self):
        deploys, m = self.run_branch()
        self.assertEqual(len(deploys), 5)
        self.assertTrue(deploys[0].get("first"))
        self.assertEqual(m["deploys"], 4)
        self.assertEqual(m["failures"], 1)
        self.assertEqual(m["changeFailureRate"], 0.25)
        self.assertEqual(m["timeToRestoreHours"]["median"], 3.0)
        self.assertEqual(sorted(x for d in deploys for x in d["leads"]), [0.0, 2.0, 4.0, 10.0])
        failed = [d for d in deploys if d.get("failure")]
        self.assertEqual(failed[0]["sha"], self.bad)
        self.assertEqual(failed[0]["failure"]["kind"], "revert")

    def test_override_clears_failure(self):
        _, m = self.run_branch({self.bad[:8]: {"failure": False, "reason": "staging only"}})
        self.assertEqual(m["failures"], 0)
        self.assertEqual(m["changeFailureRate"], 0.0)

    def test_old_history_is_not_analyzed(self):
        deploys = dora.list_deploys({"abspath": self.repo.path, "base": "main"}, "branch", t("2026-01-10T00:00:00"))
        self.assertEqual([d["t"] for d in deploys], [t("2026-01-03T05:00:00"), t("2026-01-20T04:00:00")])

    def test_cli_output_has_no_author_data(self):
        hq = hub.init(os.path.join(self.tmp.name, "hq"), "hq", "team")
        with open(os.path.join(hq, "repos.md"), "w") as f:
            f.write("| Alias | Path | Base | Deploys |\n|---|---|---|---|\n| app | `../app` | main | branch |\n")
        out = os.path.join(self.tmp.name, "out")
        rc = dora.main(["--hub", hq, "--out", out, "--days", "30", "--now", "2026-01-31T00:00:00Z", "--no-fetch"])
        self.assertEqual(rc, 0)
        blob = ""
        for fn in os.listdir(out):
            with open(os.path.join(out, fn)) as f:
                blob += f.read()
        self.assertNotIn(AUTHOR, blob)
        self.assertNotIn(EMAIL, blob)
        self.assertNotIn("saved carts", blob)  # commit subjects are not stored either
        with open(os.path.join(out, "index.json")) as f:
            idx = json.load(f)
        self.assertEqual(idx["repos"][0]["metrics"]["deploys"], 4)
        with open(os.path.join(out, "report.md")) as f:
            self.assertIn("| app | 4 |", f.read())


class TagDeploys(unittest.TestCase):
    def test_tags_and_hotfix(self):
        with tempfile.TemporaryDirectory() as d:
            r = Fixture(os.path.join(d, "api"))
            r.commit("base", "2026-01-01T00:00:00")
            r.tag("v1", "2026-01-01T12:00:00")
            r.commit("feature a", "2026-01-05T00:00:00")
            r.commit("feature b", "2026-01-05T06:00:00")
            r.tag("v2", "2026-01-06T00:00:00")
            r.commit("hotfix: null cart", "2026-01-06T08:00:00")
            r.tag("v3", "2026-01-06T09:00:00")
            r.tag("not-a-release", "2026-01-07T00:00:00")
            deploys = dora.list_deploys({"abspath": r.path}, "tag:v*", t("2025-12-01T00:00:00"))
            self.assertEqual([x["ref"] for x in deploys], ["v1", "v2", "v3"])
            dora.analyze(r.path, deploys)
            self.assertEqual(deploys[1]["commits"], 2)
            self.assertEqual(sorted(deploys[1]["leads"]), [18.0, 24.0])
            self.assertEqual(deploys[1]["failure"]["kind"], "hotfix")
            self.assertEqual(deploys[1]["failure"]["restoredBy"], "v3")
            self.assertEqual(deploys[1]["failure"]["restoreHours"], 9.0)

    def test_unknown_spec(self):
        with self.assertRaises(RuntimeError):
            dora.list_deploys({"abspath": "."}, "weekly", t("2026-01-01T00:00:00"))


if __name__ == "__main__":
    unittest.main()
