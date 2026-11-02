"""Tests for plugin/scripts/radar-md.py."""
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("radar_md", os.path.join(ROOT, "plugin", "scripts", "radar-md.py"))
radar_md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(radar_md)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


class RadarMd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.dump = self.tmp.name
        write(f"{d}/items/a.json", {"title": "Bulk export", "state": "Priority", "order": 2, "area": "Data",
                                    "requestedBy": "support", "createdAt": "2026-02-01T10:00:00Z", "createdBy": "opaque-1"})
        write(f"{d}/items/b.json", {"title": "SSO login", "state": "Priority", "order": 1, "area": "Platform",
                                    "waitingOn": ["security review"], "kind": "Tech task"})
        write(f"{d}/items/c.json", {"title": "Saved carts | v1", "state": "Shipped", "shippedAt": "2026-02-10T23:30:00Z",
                                    "area": "Product", "links": [{"label": "PR", "url": "https://example.com/pr/1"},
                                                                 {"label": "bad", "url": "javascript:alert(1)"}]})
        write(f"{d}/items/d.json", {"title": "Old idea", "state": "Dropped"})
        write(f"{d}/requests/opaque-2.json", {"items": {"r1": {"title": "Dark mode", "area": "Product",
                                                                "createdAt": "2026-02-11T00:00:00Z"},
                                                         "a": {"title": "duplicate of a triaged item"}}})

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, tz=timezone.utc):
        items = radar_md.load(self.dump)
        return radar_md.render(items, "Team Radar", "https://claude.ai/artifact/example", tz,
                               now=datetime(2026, 2, 12, tzinfo=timezone.utc))

    def test_sections_and_order(self):
        md = self.render()
        self.assertIn("# Team Radar (mirror)", md)
        self.assertIn("Summary: Priority 2 · In progress 0 · In review 0 · Inbox 1 · Later 0 · Shipped 1 · Dropped 1", md)
        self.assertLess(md.index("**#1** **SSO login**"), md.index("**#2** **Bulk export**"))
        self.assertIn("**waiting on security review**", md)
        self.assertIn("tech task", md)
        self.assertIn("**Dark mode** — new, untriaged · filed 2026-02-11", md)
        self.assertNotIn("duplicate of a triaged item", md)

    def test_shipped_table_escapes_and_filters_links(self):
        md = self.render()
        self.assertIn("| 2026-02-10 | Saved carts \\| v1 | Product |  | [PR](https://example.com/pr/1) |", md)
        self.assertNotIn("javascript:", md)

    def test_timezone(self):
        md = self.render(radar_md.tz_from("-03:00"))
        self.assertIn("| 2026-02-10 |", md)
        md = self.render(radar_md.tz_from("+02:00"))
        self.assertIn("| 2026-02-11 |", md)

    def test_never_names_creators(self):
        md = self.render()
        self.assertNotIn("opaque-1", md)
        self.assertNotIn("opaque-2", md)

    def test_cli(self):
        out = os.path.join(self.tmp.name, "radar.md")
        self.assertEqual(radar_md.main(["--dump", self.dump, "--out", out, "--title", "Team Radar"]), 0)
        with open(out) as f:
            self.assertIn("## Shipped", f.read())


if __name__ == "__main__":
    unittest.main()
