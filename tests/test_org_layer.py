"""Organization guide selection, budget share and drift (docs/org-guide-layer/prd.md P1)."""

from __future__ import annotations

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

import workflow_route  # noqa: E402
from agent_route_state import route_fingerprint  # noqa: E402
from org_binding import ORGS_FILE_ENV, PROJECT_PIN_FILE  # noqa: E402
from org_layer import organization_drift_failures, summary_lines  # noqa: E402

UI_REQUEST = "fix the checkout button on the settings screen"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_guide(root: Path, org_id: str = "acme") -> str:
    root.mkdir(parents=True)
    git(root, "init", "-q")
    write(root, "org.json", json.dumps({
        "schema_version": 1,
        "id": org_id,
        "enforce": [{"concern": "security", "doc": "skills/security/SKILL.md"}],
    }))
    write(root, "AGENTS.md", f"# {org_id} guide\n")
    write(root, "skills/security/SKILL.md", "# Security baseline\n")
    write(root, "skills/design-system/SKILL.md", "# Design system\n" + "token rules\n" * 20)
    write(root, "workflow-doc-surfaces.json", json.dumps({
        "schema_version": 1,
        "request_intents": [{
            "name": f"{org_id}_ui",
            "request_any": ["\\b(button|screen)\\b"],
            "docs": ["skills/design-system/SKILL.md"],
            "required_priority": 10,
        }],
        "path_surfaces": [],
    }))
    git(root, "add", "-A")
    git(root, "commit", "-qm", "guide")
    return git(root, "rev-parse", "HEAD")


def make_project(root: Path, remote: str) -> None:
    root.mkdir(parents=True)
    git(root, "init", "-q")
    git(root, "remote", "add", "origin", remote)
    write(root, "README.md", "app\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")


class OrgLayerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)], check=False)
        self.guide = self.tmp / "guides" / "acme"
        self.commit = make_guide(self.guide)
        self.project = self.tmp / "web"
        make_project(self.project, "git@github.com:acme/web.git")
        self.orgs = self.tmp / "orgs.json"
        self.register({"id": "acme", "root": str(self.guide), "match": ["github.com/acme/*"]})
        patcher = mock.patch.dict(os.environ, {ORGS_FILE_ENV: str(self.orgs)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def register(self, *orgs: dict) -> None:
        self.orgs.write_text(json.dumps({"orgs": list(orgs)}), encoding="utf-8")

    def route(self, project: Path | None = None, request: str = UI_REQUEST) -> dict:
        return workflow_route.resolve_docs(
            "feature", None, [], request_classified=True,
            request_text=request, project_root=project or self.project,
        )


class BindingTests(OrgLayerTestCase):
    def test_matching_remote_selects_entry_enforced_and_request_docs(self) -> None:
        route = self.route()
        organization = route["organization"]
        self.assertEqual("acme", organization["id"])
        self.assertEqual(self.commit, organization["commit"])
        self.assertEqual("pattern", organization["binding"])
        self.assertEqual(
            ["AGENTS.md", "skills/security/SKILL.md", "skills/design-system/SKILL.md"],
            [doc["path"] for doc in organization["required_docs"]],
        )
        self.assertEqual([], route["missing"])
        self.assertTrue(all(not doc.startswith("org:") for doc in route["required_docs"]))

    def test_request_without_an_org_surface_keeps_only_mandatory_docs(self) -> None:
        organization = self.route(request="rename a database column")["organization"]
        self.assertEqual(
            ["AGENTS.md", "skills/security/SKILL.md"],
            [doc["path"] for doc in organization["required_docs"]],
        )

    def test_unbound_project_route_is_unchanged(self) -> None:
        other = self.tmp / "side"
        make_project(other, "https://github.com/me/side.git")
        bound_elsewhere = self.route(other)
        self.orgs.unlink()
        unregistered = self.route(other)
        self.assertNotIn("organization", bound_elsewhere)
        self.assertEqual(json.dumps(unregistered, sort_keys=True), json.dumps(bound_elsewhere, sort_keys=True))
        self.assertEqual(route_fingerprint(unregistered), route_fingerprint(bound_elsewhere))

    def test_pin_to_another_commit_stops(self) -> None:
        write(self.project, PROJECT_PIN_FILE, json.dumps({"id": "acme", "commit": "0" * 40}))
        route = self.route()
        self.assertNotIn("organization", route)
        self.assertTrue(any("pinned commit" in item for item in route["missing"]))

    def test_pin_at_head_binds_without_a_matching_remote(self) -> None:
        other = self.tmp / "side"
        make_project(other, "https://github.com/me/side.git")
        write(other, PROJECT_PIN_FILE, json.dumps({"id": "acme", "commit": self.commit}))
        self.assertEqual("pin", self.route(other)["organization"]["binding"])

    def test_several_matching_orgs_stop(self) -> None:
        second = self.tmp / "guides" / "acme2"
        make_guide(second, "acme2")
        self.register(
            {"id": "acme", "root": str(self.guide), "match": ["github.com/acme/*"]},
            {"id": "acme2", "root": str(second), "match": ["github.com/acme/web"]},
        )
        route = self.route()
        self.assertTrue(any("several orgs" in item for item in route["missing"]))

    def test_uncommitted_guide_changes_stop(self) -> None:
        write(self.guide, "skills/security/SKILL.md", "# edited\n")
        self.assertTrue(any("uncommitted" in item for item in self.route()["missing"]))

    def test_invalid_guide_surfaces_stop_instead_of_crashing(self) -> None:
        write(self.guide, "workflow-doc-surfaces.json", json.dumps({"schema_version": 9}))
        git(self.guide, "commit", "-qam", "bad surfaces")
        self.assertTrue(any("schema_version" in item for item in self.route()["missing"]))

    def test_malformed_guide_config_stops_instead_of_crashing(self) -> None:
        for name, payload in (
            ("org.json", {"schema_version": 1, "id": "acme", "enforce": None}),
            ("workflow-doc-surfaces.json", {"schema_version": 1, "request_intents": [
                {"name": "bad", "request_any": ["(unclosed"], "docs": ["AGENTS.md"]}]}),
        ):
            with self.subTest(name=name):
                original = (self.guide / name).read_text()
                write(self.guide, name, json.dumps(payload))
                git(self.guide, "commit", "-qam", f"bad {name}")
                self.assertTrue(self.route()["missing"])
                write(self.guide, name, original)
                git(self.guide, "commit", "-qam", f"restore {name}")

    def test_ignored_enforced_doc_is_not_read_as_committed(self) -> None:
        write(self.guide, ".gitignore", "skills/secret/\n")
        write(self.guide, "org.json", json.dumps({
            "schema_version": 1, "id": "acme",
            "enforce": [{"concern": "security", "doc": "skills/secret/SKILL.md"}],
        }))
        git(self.guide, "add", "-A")
        git(self.guide, "commit", "-qm", "ignored enforce")
        write(self.guide, "skills/secret/SKILL.md", "# local only\n")
        self.assertTrue(any("is not committed" in item for item in self.route()["missing"]))

    def test_mixed_case_pattern_matches_the_remote(self) -> None:
        self.register({"id": "acme", "root": str(self.guide), "match": ["GitHub.com/Acme/*"]})
        self.assertEqual("acme", self.route()["organization"]["id"])

    def test_local_index_does_not_make_an_unexcluded_guide_dirty(self) -> None:
        write(self.guide, ".wikimap/index.db", "index")
        self.assertEqual([], self.route()["missing"])

    def test_missing_enforced_doc_stops(self) -> None:
        git(self.guide, "rm", "-q", "skills/security/SKILL.md")
        git(self.guide, "commit", "-qm", "drop")
        self.assertTrue(any("does not exist" in item for item in self.route()["missing"]))


class DriftTests(OrgLayerTestCase):
    def test_unchanged_guide_has_no_drift(self) -> None:
        self.assertEqual([], organization_drift_failures(self.route()["organization"]))

    def test_new_guide_commit_is_drift(self) -> None:
        organization = self.route()["organization"]
        write(self.guide, "skills/design-system/SKILL.md", "# Design system v2\n")
        git(self.guide, "commit", "-qam", "v2")
        failures = organization_drift_failures(organization)
        self.assertTrue(any("HEAD" in failure for failure in failures))
        self.assertTrue(any("org:acme/skills/design-system/SKILL.md" in failure for failure in failures))

    def test_uncommitted_edit_is_drift(self) -> None:
        organization = self.route()["organization"]
        write(self.guide, "org.json", "{}")
        self.assertTrue(organization_drift_failures(organization))

    def test_unreadable_doc_is_drift_not_a_crash(self) -> None:
        organization = self.route()["organization"]
        target = self.guide / "skills/design-system/SKILL.md"
        target.chmod(0)
        self.addCleanup(target.chmod, 0o644)
        self.assertTrue(any("design-system" in item for item in organization_drift_failures(organization)))

    def test_fingerprint_binds_the_guide_commit(self) -> None:
        route = self.route()
        changed = json.loads(json.dumps(route))
        changed["organization"]["commit"] = "f" * 40
        self.assertNotEqual(route_fingerprint(route), route_fingerprint(changed))

    def test_start_summary_shows_guide_docs_after_project_docs(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("agent_hook_for_org", ROOT / "scripts" / "agent-hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        payload = {"route": {"organization": self.route()["organization"]}}
        lines = hook._project_route_doc_lines(Path("unused.json"), payload, [])
        self.assertTrue(lines[0].startswith("Organization guide `acme`"))
        self.assertIn("org:acme/skills/design-system/SKILL.md", "\n".join(lines))

    def test_summary_names_absolute_paths_and_enforce_rule(self) -> None:
        text = "\n".join(summary_lines(self.route()["organization"]))
        self.assertIn(str(self.guide / "skills/design-system/SKILL.md"), text)
        self.assertIn("Organization enforce (security)", text)


class SearchTests(OrgLayerTestCase):
    """P2: the bound guide is searched like Moru's library, as candidates only."""

    def test_lookup_route_searches_the_guide_without_dirtying_it(self) -> None:
        route = workflow_route.resolve_docs(
            "analysis", None, [], request_classified=True,
            request_text="design system token rules", project_root=self.project,
        )
        self.assertIn(
            "org:acme/skills/design-system/SKILL.md",
            route["organization"]["search_candidates"],
        )
        self.assertNotIn("org:acme/skills/design-system/SKILL.md", route["required_docs"])
        self.assertEqual([], organization_drift_failures(route["organization"]))

    def test_workflow_query_labels_guide_results(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "workflow.py"), "query", "design", "system",
             "--project", str(self.project), "--format", "json"],
            capture_output=True, text=True, check=True, env={**os.environ, ORGS_FILE_ENV: str(self.orgs)},
        )
        results = json.loads(completed.stdout)["organization_results"]
        self.assertTrue(results)
        self.assertTrue(all(item["path"].startswith("org:acme/") for item in results))


class BudgetShareTests(unittest.TestCase):
    TIERS = [["common/skills/testing/SKILL.md"]]

    def select(self, prespent: tuple[int, int]) -> list[str]:
        token = workflow_route._ORGANIZATION_PRESPENT.set(prespent)
        try:
            return workflow_route._select_within_budget("feature", self.TIERS, [])
        finally:
            workflow_route._ORGANIZATION_PRESPENT.reset(token)

    def test_without_an_organization_the_tier_is_selected(self) -> None:
        self.assertEqual(["common/skills/testing/SKILL.md"], self.select((0, 0)))

    def test_organization_slots_count_against_the_document_cap(self) -> None:
        self.assertEqual([], self.select((0, workflow_route.MAX_REQUIRED_DOCS)))

    def test_organization_bytes_count_against_the_byte_budget(self) -> None:
        self.assertEqual([], self.select((workflow_route.REQUIRED_DOC_BUDGET_BYTES, 0)))


if __name__ == "__main__":
    unittest.main()
