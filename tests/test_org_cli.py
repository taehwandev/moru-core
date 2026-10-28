"""`workflow org add|sync|status` (docs/org-guide-layer/prd.md P3)."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from org_binding import ORGS_FILE_ENV, head_commit, resolve_binding  # noqa: E402
from org_cli import add_org_parser, run_org  # noqa: E402
from test_org_layer import git, make_guide, make_project, write  # noqa: E402


def org(*argv: str) -> tuple[int, str]:
    parser = argparse.ArgumentParser()
    add_org_parser(parser.add_subparsers(dest="action"))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        status = run_org(parser.parse_args(["org", *argv]))
    return status, output.getvalue()


class OrgCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)], check=False)
        self.upstream = self.tmp / "upstream"
        make_guide(self.upstream)
        self.remote = self.tmp / "acme-guides.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.upstream), str(self.remote)], check=True)
        self.checkout = self.tmp / "orgs" / "acme"
        self.orgs = self.tmp / "orgs.json"
        patcher = mock.patch.dict(os.environ, {ORGS_FILE_ENV: str(self.orgs)})
        patcher.start()
        self.addCleanup(patcher.stop)
        status, _ = org("add", "--id", "acme", "--remote", str(self.remote),
                        "--root", str(self.checkout), "--match", "github.com/acme/*")
        self.assertEqual(0, status)

    def push_upstream_change(self) -> str:
        work = self.tmp / "work"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(work)], check=True)
        write(work, "skills/design-system/SKILL.md", "# Design system v2\n")
        git(work, "commit", "-qam", "v2")
        git(work, "push", "-q")
        return git(work, "rev-parse", "HEAD")

    def test_add_clones_and_registers_a_matching_binding(self) -> None:
        registered = json.loads(self.orgs.read_text())["orgs"]
        self.assertEqual([{"id": "acme", "root": str(self.checkout), "match": ["github.com/acme/*"]}], registered)
        project = self.tmp / "web"
        make_project(project, "https://github.com/acme/web.git")
        self.assertEqual("acme", resolve_binding(project)["id"])

    def test_indexing_the_guide_never_dirties_it(self) -> None:
        (self.checkout / ".wikimap").mkdir()
        (self.checkout / ".wikimap" / "index.db").write_bytes(b"index")
        self.assertEqual("", git(self.checkout, "status", "--porcelain"))

    def test_sync_fast_forwards_to_the_remote(self) -> None:
        latest = self.push_upstream_change()
        status, output = org("sync", "--id", "acme")
        self.assertEqual(0, status)
        self.assertEqual(latest, head_commit(self.checkout))
        self.assertIn("->", output)

    def test_sync_offline_leaves_the_checkout_unchanged(self) -> None:
        before = head_commit(self.checkout)
        git(self.checkout, "remote", "set-url", "origin", str(self.tmp / "missing.git"))
        status, output = org("sync", "--id", "acme")
        self.assertEqual(2, status)
        self.assertIn("could not be updated", output)
        self.assertEqual(before, head_commit(self.checkout))

    def test_sync_refuses_a_modified_checkout(self) -> None:
        self.push_upstream_change()
        write(self.checkout, "AGENTS.md", "# local edit\n")
        status, output = org("sync")
        self.assertEqual(2, status)
        self.assertIn("uncommitted", output)

    def test_add_rejects_a_guide_whose_manifest_names_another_id(self) -> None:
        status, output = org("add", "--id", "other", "--root", str(self.checkout))
        self.assertEqual(2, status)
        self.assertIn("declares id `acme`", output)

    def test_add_rejects_an_invalid_id_before_registering(self) -> None:
        status, output = org("add", "--id", "Acme", "--root", str(self.checkout))
        self.assertEqual(2, status)
        self.assertIn("must match", output)
        self.assertEqual(["acme"], [item["id"] for item in json.loads(self.orgs.read_text())["orgs"]])

    def test_status_reports_the_project_binding(self) -> None:
        project = self.tmp / "web"
        make_project(project, "git@github.com:acme/web.git")
        status, output = org("status", "--project", str(project))
        self.assertEqual(0, status)
        self.assertIn("bound to `acme` by pattern", output)


if __name__ == "__main__":
    unittest.main()
