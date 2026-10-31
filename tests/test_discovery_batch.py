"""Independent contracts for the three discovery/entry reductions."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import random
import re
import tempfile
import unittest
from unittest.mock import patch

import agent_project_discovery as discovery
import agent_project_search as search
from agent_project_types import INSTRUCTION_FILES, PROJECT_MARKERS
from support.literal_boundary import contains_literal
from support.project_facts import ProjectFacts


class LiteralBoundaryTests(unittest.TestCase):
    def test_reference_equivalence_corpus(self):
        fixed = [("", ""), ("a", ""), (" ", ""), ("x.y", "."), ("a-a", "a"),
                 ("aab ab", "ab"), ("ApPA", "p"), ("한app글", "app"), ("i̇", "i"),
                 ("a\x00b", "\x00"), ("a\nb", "\n"), ("[x]", "[x]"), ("aaaa", "aa")]
        rng = random.Random(1837)
        alphabet = "abcAZ09_- .[]()\\\n\x00한éİ😀"
        for _ in range(5000):
            text = "".join(rng.choices(alphabet, k=rng.randrange(24)))
            name = "".join(rng.choices(alphabet, k=rng.randrange(6)))
            fixed.append((text, name))
        for text, name in fixed:
            with self.subTest(text=text, name=name):
                expected = re.search(r"(?<![a-z0-9_-])" + re.escape(name) + r"(?![a-z0-9_-])", text) is not None
                self.assertEqual(expected, contains_literal(text, name))

    def test_project_name_normalization_policy_still_applies(self):
        self.assertFalse(search.request_name_matches("web", "update web"))
        self.assertTrue(search.request_name_matches("web", "update web", allow_generic=True))
        self.assertFalse(search.request_name_matches("spill", "spill-web 작업"))
        self.assertTrue(search.request_name_matches("spill-web", "spill web 작업"))

    def test_short_requests_avoid_regex_but_long_requests_keep_the_legacy_path(self):
        with patch.object(search.re, "search", side_effect=AssertionError("unexpected regex")):
            self.assertTrue(search.request_name_matches("repo-one", "work on repo-one"))
        with patch.object(search, "contains_literal", side_effect=AssertionError("slow repeated scan")):
            self.assertFalse(search.request_name_matches("a", "a" * 65536))
            self.assertTrue(search.request_name_matches("repo-one", "!" * 4096 + " repo-one"))
        for length in (4095, 4096, 4097):
            value = "a" * length
            expected = re.search(r"(?<![a-z0-9_-])a(?![a-z0-9_-])", value) is not None
            self.assertEqual(expected, search._contains_strict_name(value, "a"))


class DiscoveryBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="discovery-batch-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.tree = self.base / "tree"
        self.tree.mkdir()
        self.project = self.tree / "project-004"
        self.project.mkdir()
        (self.project / "AGENTS.md").touch()
        (self.project / ".git").mkdir()
        self.outside = self.base / "outside"
        self.outside.mkdir()
        self.registry = self.base / "registry.json"
        self.registry.write_text('{"projects":[],"search_roots":[]}')
        self.environment = patch.dict(os.environ, MORU_PROJECT_SEARCH_ROOTS="")
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def discover(self):
        return discovery.discover_projects("work on project-004", self.outside,
            registry_path=self.registry, search_roots=[self.tree], max_depth=2)

    def test_facts_keep_order_duplicates_and_do_not_cache_across_probes(self):
        facts = ProjectFacts.probe(self.project, ["missing", "AGENTS.md", "AGENTS.md"], [".git", "missing"])
        self.assertEqual(("AGENTS.md", "AGENTS.md"), facts.instruction_files)
        self.assertEqual((".git",), facts.markers)
        self.assertTrue(facts.present)
        (self.project / "AGENTS.md").unlink()
        self.assertEqual((), ProjectFacts.probe(self.project, ["AGENTS.md"], []).instruction_files)
        self.assertEqual(("AGENTS.md", "AGENTS.md"), facts.instruction_files)

    def test_facts_retain_exists_semantics_and_errors(self):
        (self.project / "instruction-link").symlink_to(self.project / "AGENTS.md")
        (self.project / "broken").symlink_to(self.project / "absent")
        facts = ProjectFacts.probe(self.project, ["instruction-link", "broken"], [])
        self.assertEqual(("instruction-link",), facts.instruction_files)
        with patch.object(Path, "exists", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                ProjectFacts.probe(self.project, ["AGENTS.md"], [])

    def test_scan_reuses_one_set_of_metadata_probes_per_candidate(self):
        original = Path.exists
        calls = []
        def tracked(path):
            if path.parent == self.project:
                calls.append(path.name)
            return original(path)
        with patch.object(Path, "exists", tracked):
            result = self.discover()
        self.assertEqual(self.project, result.selected.path)
        for name in (*INSTRUCTION_FILES, *PROJECT_MARKERS):
            # Nested .agents/README.md has a different immediate parent.
            if "/" not in name:
                self.assertEqual(1, calls.count(name), (name, calls))

    def test_scan_records_and_legacy_paths_keep_bfs_order_and_bounds(self):
        (self.project / "nested").mkdir()
        (self.project / "nested/CLAUDE.md").touch()
        for depth, limit in [(0, 1500), (1, 1500), (2, 1500), (2, 1), (2, 2)]:
            paths = list(search.scan_project_roots(self.tree, max_depth=depth, max_visited=limit))
            records = list(search.scan_project_records(self.tree, max_depth=depth, max_visited=limit))
            self.assertEqual(paths, [path for path, _ in records])
            for path, facts in records:
                old = search.build_candidate(path, 35, "scan", "search_root")
                new = search.build_candidate(path, 35, "scan", "search_root", facts=facts)
                self.assertEqual(old.to_dict(), new.to_dict())

    def test_legacy_path_scan_keeps_early_instruction_probe_behavior(self):
        with patch.object(search, "project_markers", side_effect=AssertionError("unneeded probe")):
            self.assertEqual([self.project], list(search.scan_project_roots(self.project, max_depth=0)))

    def test_two_discoveries_see_metadata_changes(self):
        self.assertIn("AGENTS.md", self.discover().selected.instruction_files)
        (self.project / "AGENTS.md").unlink()
        self.assertEqual([], self.discover().selected.instruction_files)

    def test_entry_reads_one_registry_snapshot_and_does_not_mutate_it(self):
        first = {"projects": [{"root": str(self.project), "aliases": ["target-alias"]}],
                 "search_roots": [], "workspace_groups": []}
        expected = copy.deepcopy(first)
        with patch.object(discovery, "load_registry", side_effect=[first, {"projects": []}]) as loader:
            manifest = discovery.build_entry_manifest("work on target-alias", self.outside, runtime="generic")
        self.assertEqual(1, loader.call_count)
        self.assertEqual("selected", manifest["status"])
        self.assertEqual(str(self.project), manifest["workspace_scope"]["primary_repo"])
        self.assertEqual(expected, first)

    def test_entry_reads_fresh_registry_on_the_next_call(self):
        self.registry.write_text(json.dumps({"projects": [{"root": str(self.project), "aliases": ["target-alias"]}]}))
        first = discovery.build_entry_manifest("target-alias", self.outside, runtime="generic", registry_path=self.registry)
        self.registry.write_text('{"projects":[]}')
        second = discovery.build_entry_manifest("target-alias", self.outside, runtime="generic", registry_path=self.registry)
        self.assertEqual("selected", first["status"])
        self.assertEqual("not_found", second["status"])


if __name__ == "__main__":
    unittest.main()
