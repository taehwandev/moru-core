"""Real discovery CLI/entry parity, native-only execution and safe deferral."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from native_launcher_support import copied_build_root, install
from native_pretool_support import PROJECT, environment, prepare, result
from support.native_source_inputs import pretool_contract


class NativeProjectDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-discovery-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        self.empty = self.base / "empty-path"
        self.empty.mkdir()
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()

    def call(self, *args, backend="auto", source=PROJECT, entry=None, **overrides):
        env = {**self.env, "MORU_HOME": str(source), "MORU_LAUNCHER_BACKEND": backend, **overrides}
        return subprocess.run([str(entry or self.entry), "project-discover", *args],
            cwd=self.base, capture_output=True, env=env, timeout=10)

    def parity(self, args, **env):
        expected = self.call(*args, backend="python", **env)
        self.assertIn(expected.returncode, (0, 2, 3), expected.stderr)
        self.assertFalse(expected.stderr)
        self.assertEqual(result(expected), result(self.call(*args, **env)))
        self.assertEqual(result(expected), result(self.call(*args, **env, PATH=str(self.empty))))
        return expected

    def project_at(self, name, marker="AGENTS.md"):
        root = self.workspace / name
        root.mkdir(parents=True)
        (root / marker).parent.mkdir(parents=True, exist_ok=True)
        (root / marker).touch()
        return root

    def test_parent_lookup_and_exact_text_json_unicode_match_without_python(self):
        nested = self.project / "한글😀" / "nested"
        nested.mkdir(parents=True)
        for cwd in (self.project, nested, self.project / "AGENTS.md"):
            for format in ("text", "json"):
                with self.subTest(cwd=cwd, format=format):
                    self.parity(["--request", "이어서 진행", "--cwd", str(cwd), "--format", format])
        # Preserve the generated launcher's existing soft-fail convention.
        self.parity(["--request", "진행", "--cwd", str(self.workspace)], MORU_HOOK_SOFT_FAIL="1")

    def test_scan_markers_ranking_ambiguity_and_generic_names(self):
        for name, marker in (("alpha-proj", ".git"), ("beta", "package.json"),
                             ("한글😀", ".agents/README.md"), ("web", "Cargo.toml")):
            self.project_at(name, marker)
        args = ["--cwd", str(self.workspace), "--search-root", str(self.workspace)]
        for request in ("진행", "alpha-proj", "alpha proj", "beta", "한글😀", "web", "xalpha-proj"):
            for format in ("text", "json"):
                with self.subTest(request=request, format=format):
                    self.parity(["--request", request, *args, "--format", format])
        self.parity(["--request", "진행", *args], MORU_HOOK_SOFT_FAIL="1")

    def test_depth_hidden_skip_symlinks_and_bounded_cycles(self):
        real = self.project_at("real")
        self.project_at("node_modules/ignored")
        self.project_at(".hidden/ignored")
        self.project_at("Build/kept")
        (self.workspace / "alias").symlink_to(real, target_is_directory=True)
        (self.workspace / "broken").symlink_to(self.workspace / "missing")
        (self.workspace / "self-loop").symlink_to(self.workspace / "self-loop")
        (real / "cycle").symlink_to(self.workspace, target_is_directory=True)
        for depth in (-1, 0, 1, 2, 8):
            with self.subTest(depth=depth):
                self.parity(["--request", "진행", "--cwd", str(self.workspace),
                    "--search-root", str(self.workspace), "--max-depth", str(depth), "--format", "json"])

    def test_registry_env_defaults_and_duplicate_roots(self):
        self.project_at("alpha")
        registry = self.base / "registry.json"
        registry.write_text(json.dumps({"projects": [], "search_roots": [str(self.workspace)]}))
        args = ["--request", "alpha", "--cwd", str(self.workspace), "--registry", str(registry),
                "--search-root", str(self.workspace), "--search-root", str(self.workspace), "--format", "json"]
        self.parity(args, MORU_PROJECT_SEARCH_ROOTS=str(self.workspace))
        self.parity(["--request", "alpha", "--cwd", str(self.workspace), "--format", "json"],
                    MORU_PROJECT_REGISTRY=str(registry))
        home_git = self.base / "home/git"
        home_git.mkdir()
        (home_git / "AGENTS.md").touch()
        for flags in (["--include-default-search-roots"],
                      ["--include-default-search-roots", "--no-default-search-roots"]):
            self.parity(["--request", "진행", "--cwd", str(self.workspace), *flags, "--format", "json"])

    def test_python_whitespace_and_case_insensitive_path_spelling(self):
        root = self.project_at("\x1cMixedCase\x1f")
        args = ["--request", "mixedcase", "--cwd", str(self.workspace),
                "--search-root", str(self.workspace), "--format", "json"]
        self.parity(args)
        alternate = root.with_name(root.name.lower())
        if alternate.is_dir():
            self.parity(["--request", "진행", "--cwd", str(alternate), "--format", "json"])
        state = self.base / "custom-state"
        state.mkdir()
        (state / "projects.json").write_text(json.dumps({"search_roots": [str(self.workspace)]}))
        self.parity(["--request", "mixedcase", "--cwd", str(self.workspace), "--format", "json"],
                    MORU_STATE_HOME="\x1c" + str(state) + "\x1f")

    def test_unsupported_request_registry_case_and_cli_preserve_python(self):
        registry = self.base / "registry.json"
        registry.write_text(json.dumps({"projects": [{"path": str(self.project), "aliases": ["target"]}]}))
        cases = [["--request", str(self.project)], ["--request", "'경로'"],
                 ["--request", "진행", "--cwd", str(self.base / "missing")],
                 ["--help"], ["--request", "진행", "--format", "unknown"],
                 ["--request", "진행", "--max-depth", "2147483648"]]
        self.project_at("ΟΣ")
        cases.append(["--request", "진행", "--search-root", str(self.workspace)])
        for args in cases:
            with self.subTest(args=args):
                self.assertEqual(result(self.call(*args, backend="python")), result(self.call(*args)))
                self.assertEqual(127, self.call(*args, PATH=str(self.empty)).returncode)
        registry.write_text('{"workspace_groups": [{"name": "group"}]}')
        args = ["--request", "진행", "--registry", str(registry)]
        self.assertEqual(result(self.call(*args, backend="python")), result(self.call(*args)))
        self.assertEqual(127, self.call(*args, PATH=str(self.empty)).returncode)

    def test_entry_manifest_reuses_native_with_one_registry_snapshot(self):
        from agent_project_discovery import build_entry_manifest
        from support.project_discovery_native import native_discovery
        common = dict(request="이어서 진행", cwd=self.project, runtime="codex")
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = build_entry_manifest(**common)
        with patch.dict(os.environ, {**self.env, "PATH": str(self.empty)}, clear=True):
            # A fresh file read must not replace the snapshot Python supplied.
            state = Path(self.env["MORU_STATE_HOME"])
            state.mkdir(parents=True, exist_ok=True)
            (state / "projects.json").write_text('{"projects": [{"path": "/different"}]}')
            found = native_discovery("이어서 진행", self.project, registry_snapshot={},
                search_roots=(), max_depth=2, include_default_search_roots=False)
            self.assertEqual(str(self.project), str(found.selected.path))
            with patch("agent_project_discovery.load_registry", return_value={}) as load, \
                 patch("agent_project_discovery.find_project_root", side_effect=AssertionError("Python FS used")), \
                 patch("agent_project_discovery._scan_roots", side_effect=AssertionError("Python scan used")):
                self.assertEqual(expected, build_entry_manifest(**common))
                load.assert_called_once()

    def test_stale_source_and_nonstandard_environment_keep_python(self):
        root = copied_build_root(self.base / "copy")
        for relative in pretool_contract(PROJECT)[1]:
            (root / relative).mkdir(parents=True, exist_ok=True)
        for name in ("AGENTS.md", "index.md"):
            (root / name).write_text("synthetic\n")
        home = self.base / "other-home"
        install(home, root)
        entry = home / ".moru/bin/moru-hook"
        args = ["--request", "진행", "--cwd", str(self.project), "--format", "json"]
        self.assertEqual(0, self.call(*args, source=root, entry=entry, HOME=str(home), PATH=str(self.empty)).returncode)
        changed = root / "scripts/agent_project_discovery.py"
        changed.write_text(changed.read_text() + "\n# synthetic stale-source change\n")
        self.assertEqual(result(self.call(*args, backend="python", source=root, entry=entry, HOME=str(home))),
                         result(self.call(*args, source=root, entry=entry, HOME=str(home))))
        self.assertEqual(127, self.call(*args, source=root, entry=entry, HOME=str(home), PATH=str(self.empty)).returncode)
        self.assertEqual(127, self.call(*args, PYTHONVERBOSE="1", PATH=str(self.empty)).returncode)

    def test_bfs_visit_limit(self):
        for index in range(1502):
            self.project_at(f"p{index:04}", "Cargo.toml")
        args = ["--request", "진행", "--cwd", str(self.workspace), "--search-root", str(self.workspace), "--format", "json"]
        done = self.parity(args)
        self.assertEqual(1499, len(json.loads(done.stdout)["candidates"]))
        self.assertNotIn("p1499", done.stdout.decode())


if __name__ == "__main__":
    unittest.main()
