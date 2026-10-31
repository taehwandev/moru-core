"""Canonicalization reuse without weakening raw-input or error contracts."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

import agent_project_discovery as discovery
import agent_project_search as search
from agent_project_types import ProjectCandidate


class DiscoveryRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="discovery-repair-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / "project-004"
        self.project.mkdir()
        (self.project / "AGENTS.md").touch()
        self.link = self.base / "linked-project"
        self.link.symlink_to(self.project, target_is_directory=True)
        self.empty = self.base / "empty-registry.json"
        self.empty.write_text('{"projects":[],"search_roots":[]}')

    def test_built_candidate_resolves_once_but_raw_api_still_resolves(self):
        results = {}
        with patch.object(search, "safe_resolve", wraps=search.safe_resolve) as resolve:
            search.build_and_add_candidate(results, self.link, 35, "scan", "search_root")
        self.assertEqual(1, resolve.call_count)
        self.assertEqual([self.project], list(results))
        raw = ProjectCandidate(Path(os.path.relpath(self.link)), 45, aliases=["raw"])
        with patch.object(search, "safe_resolve", wraps=search.safe_resolve) as resolve:
            search.add_candidate(results, raw)
        self.assertEqual(1, resolve.call_count)
        self.assertEqual(self.project, raw.path)
        self.assertEqual([self.project], list(results))
        self.assertEqual(55, results[self.project].confidence)

    def test_aliases_are_copied_before_existing_candidate_is_merged(self):
        results = {}
        aliases = ["old", "new"]
        search.build_and_add_candidate(results, self.project, 35, "first", "scan", aliases=["old"])
        first = results[self.project]
        search.build_and_add_candidate(results, self.link, 120, "second", "registry", aliases=aliases)
        aliases.append("later mutation")
        self.assertIs(first, results[self.project])
        self.assertEqual(["old", "new"], first.aliases)
        self.assertEqual(["first", "second"], first.reasons)
        self.assertEqual(["scan", "registry"], first.sources)
        self.assertEqual(140, first.confidence)
        self.assertEqual(["AGENTS.md"], first.instruction_files)

    def test_built_and_legacy_producer_collector_results_match(self):
        legacy, repaired = {}, {}
        for path, score, reason, source, aliases in [
            (self.project, 35, "first", "scan", ["p"]),
            (self.link, 120, "second", "registry", ["p", "alias"]),
        ]:
            candidate = search.build_candidate(path, score, reason, source)
            candidate.aliases = aliases
            search.add_candidate(legacy, candidate)
            search.build_and_add_candidate(repaired, path, score, reason, source, aliases=aliases)
        self.assertEqual([c.to_dict() for c in legacy.values()], [c.to_dict() for c in repaired.values()])

    def test_entry_uses_one_resolved_cwd_observation(self):
        with patch.object(discovery, "safe_resolve", wraps=discovery.safe_resolve) as resolve:
            with patch.dict(os.environ, MORU_PROJECT_SEARCH_ROOTS=""):
                manifest = discovery.build_entry_manifest("fix this", self.link, runtime="generic",
                                                           registry_path=self.empty)
        self.assertEqual(1, resolve.call_count)
        self.assertEqual(str(self.project), manifest["cwd"])
        self.assertEqual(str(self.project), manifest["selected_project"]["path"])

    def test_presence_probe_keeps_later_instruction_errors(self):
        original = Path.exists
        def exists(path):
            if path == self.project / "CLAUDE.md":
                raise PermissionError("later instruction probe")
            return original(path)
        with patch.object(Path, "exists", exists):
            with self.assertRaises(PermissionError):
                search.find_project_root(self.project)
            with self.assertRaises(PermissionError):
                list(search.scan_project_roots(self.project, max_depth=0))

    def test_next_build_observes_a_retargeted_symlink(self):
        second = self.base / "second"
        second.mkdir()
        (second / "AGENTS.md").touch()
        results = {}
        search.build_and_add_candidate(results, self.link, 35, "first", "scan")
        self.link.unlink()
        self.link.symlink_to(second, target_is_directory=True)
        search.build_and_add_candidate(results, self.link, 35, "second", "scan")
        self.assertEqual([self.project, second], list(results))

    def test_resolver_fallback_is_shared_without_a_second_attempt(self):
        legacy, repaired = {}, {}
        with patch.object(Path, "resolve", side_effect=OSError("unavailable")):
            candidate = search.build_candidate(self.link, 35, "scan", "search_root")
            search.add_candidate(legacy, candidate)
            search.build_and_add_candidate(repaired, self.link, 35, "scan", "search_root")
        self.assertEqual([self.link], list(repaired))
        self.assertEqual([c.to_dict() for c in legacy.values()], [c.to_dict() for c in repaired.values()])

    @unittest.skipUnless(os.name == "posix", "child CPU measurement is a POSIX developer tool")
    def test_measurement_preserves_stdin_eof_bytes_and_nonzero_exit(self):
        from discovery_process_measure import run_measured
        code = "import sys; assert sys.stdin.buffer.read()==b''; sys.stdout.buffer.write(b'out'); sys.stderr.buffer.write(b'err'); sys.exit(3)"
        done, metrics = run_measured([sys.executable, "-c", code], env=dict(os.environ), cwd=self.base)
        self.assertEqual((3, b"out", b"err"), (done.returncode, done.stdout, done.stderr))
        self.assertGreater(metrics["wall_ms"], 0)
        self.assertGreaterEqual(metrics["cpu_ms"], 0)
        self.assertAlmostEqual(metrics["cpu_ms"], metrics["user_ms"] + metrics["system_ms"])
        with self.assertRaises(FileNotFoundError):
            run_measured([str(self.base / "missing-executable")], env={}, cwd=self.base)


if __name__ == "__main__":
    unittest.main()
