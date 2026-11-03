"""Explicit project paths through real generated discovery and entry manifests."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from native_pretool_support import environment, prepare, result


class NativeRequestPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-paths-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.current = prepare(self.base)
        self.env = environment(self.base)
        self.empty = self.base / "empty-path"
        self.empty.mkdir()
        self.workspace = self.base / "workspace"
        self.target = self.project_at("target-service")
        self.other = self.project_at("other-service")
        self.registry = self.base / "registry.json"
        self.registry.write_text("{}")

    def project_at(self, name):
        path = self.base / "workspace" / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "AGENTS.md").touch()
        return path

    def call(self, request, *, backend="auto", args=(), **overrides):
        return subprocess.run([str(self.entry), "project-discover", "--request", request,
            "--cwd", str(self.workspace), "--registry", str(self.registry), "--format", "json", *args],
            cwd=self.base, capture_output=True, timeout=10,
            env={**self.env, "MORU_LAUNCHER_BACKEND": backend, **overrides})

    def parity(self, request, *, args=(), **env):
        expected = self.call(request, backend="python", args=args, **env)
        self.assertIn(expected.returncode, (0, 2, 3), expected.stderr)
        self.assertFalse(expected.stderr)
        self.assertEqual(result(expected), result(self.call(request, args=args, **env)))
        self.assertEqual(result(expected), result(self.call(request, args=args, PATH=str(self.empty), **env)))
        return json.loads(expected.stdout) if "--format" not in args else expected.stdout

    def test_explicit_target_overrides_cwd_and_preserves_text_json_and_exit(self):
        for request in (str(self.target), f"수정해줘 {self.target}", f"수정\t{self.target}\n진행"):
            for format in ("text", "json"):
                with self.subTest(request=request, format=format):
                    self.parity(request, args=["--cwd", str(self.current), "--format", format])
        chosen = self.parity(str(self.target), args=["--cwd", str(self.current)])["selected_project"]
        self.assertEqual(str(self.target), chosen["path"])
        self.assertEqual(["request_path"], chosen["sources"])
        self.assertEqual(["explicit path in request", "candidate name appeared in request"], chosen["reasons"])

    def test_file_nested_and_symlink_paths_resolve_to_the_nearest_project(self):
        nested = self.target / "source/nested"
        nested.mkdir(parents=True)
        file = nested / "file.txt"
        file.touch()
        link = self.workspace / "target-link"
        link.symlink_to(self.target, target_is_directory=True)
        for path in (nested, file, link, self.target / "AGENTS.md"):
            with self.subTest(path=path):
                self.assertEqual(str(self.target), self.parity(f"작업 {path}")["selected_project"]["path"])

    def test_multiple_explicit_paths_keep_ambiguity_and_duplicates_merge_once(self):
        value = self.parity(f"{self.target} {self.other} {self.target}")
        self.assertEqual("ambiguous", value["status"])
        self.assertEqual(2, len(value["candidates"]))
        self.assertEqual(sorted([str(self.target), str(self.other)]), [v["path"] for v in value["candidates"]])
        for candidate in value["candidates"]:
            self.assertEqual(["request_path"], candidate["sources"])
            self.assertEqual(1, candidate["reasons"].count("explicit path in request"))

    def test_punctuation_embedded_paths_and_full_word_regex_union(self):
        for request in (f"진행({self.target})", f"{self.target},", f"{self.target};", f"{self.target}:line",
                        f"<{self.target}>", f"{self.target}...", f"{self.target}/./", f"./{self.target}"):
            with self.subTest(request=request):
                self.assertEqual(str(self.target), self.parity(request)["selected_project"]["path"])
        prefix = self.project_at("colon")
        whole = self.project_at("colon:tail")
        value = self.parity(str(whole))
        self.assertEqual({str(prefix), str(whole)}, {v["path"] for v in value["candidates"]})
        self.assertEqual("ambiguous", value["status"])

    def test_current_home_expansion_and_canonical_leading_dot_trimming(self):
        home_project = self.base / "home/home-target"
        home_project.mkdir()
        (home_project / "AGENTS.md").touch()
        self.assertEqual(str(home_project), self.parity("작업 ~/home-target")["selected_project"]["path"])
        (self.base / "home/AGENTS.md").touch()
        self.assertEqual(str(self.base / "home"), self.parity("~")["selected_project"]["path"])
        # Canonical strip removes initial dots before joining: keep that behavior.
        for request in ("./target-service", "../target-service", ".", "..", "source.txt"):
            self.parity(request)

    def test_missing_unmarked_and_unquoted_space_paths_do_not_gain_candidates(self):
        plain = self.workspace / "plain"
        plain.mkdir()
        spaced = self.project_at("with spaces")
        link = self.workspace / "broken"
        link.symlink_to(self.workspace / "missing")
        for path in (self.workspace / "missing", plain, link, spaced):
            with self.subTest(path=path):
                self.assertEqual("not_found", self.parity(str(path))["status"])

    def test_request_registry_cwd_group_scan_merge_order_is_unchanged(self):
        self.registry.write_text(json.dumps({"projects": [{"root": str(self.target), "aliases": ["launch", "launch"]}],
            "workspace_groups": [{"name": "suite", "members": [{"root": str(self.target), "role": "web"}]}]}))
        chosen = self.parity(f"{self.target} launch suite web", args=["--cwd", str(self.target),
            "--search-root", str(self.workspace)])["selected_project"]
        self.assertEqual(["request_path", "registry", "cwd", "workspace_group", "search_root"], chosen["sources"])
        self.assertEqual(["launch", "suite", "web", "target-service"], chosen["aliases"])
        self.assertEqual(["explicit path in request", "registry alias or project name matched request",
            "current working directory is inside a project", "workspace group member alias matched request",
            "project name matched request under configured search root", "candidate name appeared in request"], chosen["reasons"])

    def test_entry_manifest_reuses_native_path_candidates_and_python_scope(self):
        import agent_project_discovery as discovery
        self.registry.write_text(json.dumps({"workspace_groups": [{"name": "suite", "members": [
            {"root": str(self.target), "role": "web"}, {"root": str(self.other), "role": "app"}]}]}))
        args = dict(request=str(self.target), cwd=self.workspace, runtime="codex", registry_path=self.registry)
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = discovery.build_entry_manifest(**args)
        with patch.dict(os.environ, {**self.env, "PATH": str(self.empty)}, clear=True), \
             patch.object(discovery, "explicit_request_paths", side_effect=AssertionError("Python path lookup")), \
             patch.object(discovery, "_scan_roots", side_effect=AssertionError("Python scan")), \
             patch.object(discovery, "load_registry", wraps=discovery.load_registry) as load:
            actual = discovery.build_entry_manifest(**args)
            self.assertEqual(expected, actual)
            self.assertEqual("primary_selected_checkpoint_before_expansion", actual["workspace_scope"]["scope_mode"])
            self.assertTrue(actual["workspace_scope"]["scope_checkpoint"]["required_before_secondary_write"])
            load.assert_called_once()

    def test_complex_request_grammar_and_environment_keep_python_replay(self):
        spaced = self.project_at("with spaces")
        requests = [f"'{spaced}'", f'"{spaced}"', str(spaced).replace(" ", "\\ "),
            "$MORU_NATIVE_PATH_TEST", f"`{self.target}`", f"x\u00a0{self.target}",
            f"x\x1c{self.target}", "~definitely_missing_moru_native_path_user"]
        for request in requests:
            with self.subTest(request=request):
                self.assertEqual(result(self.call(request, backend="python")), result(self.call(request)))
                self.assertEqual(127, self.call(request, PATH=str(self.empty)).returncode)
        expected = self.call(str(self.target), backend="python", PYTHONVERBOSE="1")
        actual = self.call(str(self.target), PYTHONVERBOSE="1")
        # Verbose import diagnostics contain process-specific memory addresses.
        self.assertEqual((expected.returncode, expected.stdout), (actual.returncode, actual.stdout))
        self.assertIn(b"# code object from", actual.stderr)
        self.assertEqual(127, self.call(str(self.target), PATH=str(self.empty), PYTHONVERBOSE="1").returncode)


if __name__ == "__main__":
    unittest.main()
