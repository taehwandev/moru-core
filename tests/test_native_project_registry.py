"""Registered discovery parity through real generated and Python entry paths."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from native_pretool_support import environment, prepare, result


class NativeProjectRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-registry-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.current = prepare(self.base)
        self.env = environment(self.base)
        self.empty = self.base / "empty-path"
        self.empty.mkdir()
        self.workspace = self.base / "workspace"
        self.target = self.project_at("target-service")
        self.registry = self.base / "registry.json"

    def project_at(self, name):
        path = self.base / "workspace" / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "AGENTS.md").touch()
        return path

    def write(self, value):
        self.registry.write_text(json.dumps(value))

    def call(self, request="launch", *, backend="auto", args=(), **overrides):
        command = [str(self.entry), "project-discover", "--request", request,
            "--cwd", str(self.current), "--registry", str(self.registry), "--format", "json", *args]
        return subprocess.run(command, cwd=self.base, capture_output=True, timeout=10,
            env={**self.env, "MORU_LAUNCHER_BACKEND": backend, **overrides})

    def parity(self, request="launch", *, args=(), **env):
        expected = self.call(request, backend="python", args=args, **env)
        self.assertIn(expected.returncode, (0, 2, 3), expected.stderr)
        self.assertFalse(expected.stderr)
        self.assertEqual(result(expected), result(self.call(request, args=args, **env)))
        self.assertEqual(result(expected), result(self.call(request, args=args, PATH=str(self.empty), **env)))
        return json.loads(expected.stdout) if "--format" not in args else expected.stdout

    def test_aliases_names_generic_terms_and_exact_boundaries(self):
        self.write({"projects": [{"root": str(self.target), "aliases": ["launch", "target app", "web", "한글"]}]})
        for request in ("launch", "target-service", "target-app", "TARGET APP", "web", "한글", "xtarget-app", "target-appx"):
            for format in ("json", "text"):
                with self.subTest(request=request, format=format):
                    self.parity(request, args=["--format", format])
        self.assertEqual(str(self.target), self.parity()["selected_project"]["path"])

    def test_disabled_identity_and_root_path_precedence(self):
        cases = [({"disabled": True}, self.current), ({"disabled": 1}, self.target),
                 ({"root": ""}, self.target), ({"root": False}, self.target),
                 ({"root": 0}, self.target), ({"root": []}, self.target),
                 ({"root": {}}, self.target), ({"root": 123}, self.current)]
        for overrides, target in cases:
            self.write({"projects": [None, 42, "ignored", {"root": str(self.target), "path": str(self.target),
                "aliases": [None, "launch", 3], **overrides}]})
            with self.subTest(overrides=overrides):
                self.assertEqual(str(target), self.parity()["selected_project"]["path"])
        for raw in (str(self.target / "AGENTS.md") + "/.", str(self.target) + "/./"):
            self.write({"projects": [{"path": raw, "aliases": ["launch"]}]})
            self.assertEqual(str(self.target), self.parity()["selected_project"]["path"])

    def test_ordered_merges_duplicates_and_alias_boost(self):
        link = self.workspace / "target-link"
        link.symlink_to(self.target, target_is_directory=True)
        self.write({"projects": [{"path": str(self.target), "aliases": ["launch", "launch"]}]})
        self.assertEqual(["launch", "launch"], self.parity()["selected_project"]["aliases"])
        self.write({"projects": [{"path": str(self.target), "aliases": ["launch", "launch"]},
                                 {"path": str(link), "aliases": ["other", "launch"]}]})
        value = self.parity(args=["--cwd", str(self.target), "--search-root", str(self.workspace)])
        chosen = value["selected_project"]
        self.assertEqual(["launch", "other"], chosen["aliases"])
        self.assertEqual(["registry", "cwd", "search_root"], chosen["sources"])
        self.assertEqual(["registry alias or project name matched request", "current working directory is inside a project",
            "project marker found under configured search root", "candidate name appeared in request"], chosen["reasons"])

    def test_top_level_array_ambiguity_and_fresh_registry(self):
        second = self.project_at("second-service")
        self.write([{"root": str(self.target), "aliases": ["launch"]},
                    {"path": str(second), "aliases": ["launch"]}])
        self.assertEqual("ambiguous", self.parity()["status"])
        self.write({"projects": [{"root": str(self.target), "aliases": ["launch"]}]})
        self.assertEqual(str(self.target), self.parity()["selected_project"]["path"])
        self.write({"projects": [{"root": str(second), "aliases": ["launch"]}]})
        self.assertEqual(str(second), self.parity()["selected_project"]["path"])
        self.parity(args=["--registry", str(self.registry) + "/."])

    def test_environment_home_and_nonrecursive_path_expansion(self):
        home_project = self.base / "home/registered-home"
        home_project.mkdir()
        (home_project / "AGENTS.md").touch()
        literal = self.project_at("$LATE")
        brace = self.project_at("${}")
        unterminated = self.project_at("${UNCLOSED")
        missing = self.project_at("$MORU_REGISTRY_MISSING_TEST")
        env = {"REGISTRY_TARGET": str(self.target), "REGISTRY_BRACE": str(brace),
               "ROOT WITH SPACE": str(self.target), "한글변수": str(self.target), "1ROOT": str(self.target),
               "ONCE": "workspace/$LATE", "LATE": str(self.target)}
        cases = [("$REGISTRY_TARGET", self.target), ("${REGISTRY_TARGET}", self.target),
                 ("${ROOT WITH SPACE}", self.target), ("${한글변수}", self.target),
                 ("$1ROOT", self.target), ("~/registered-home", home_project),
                 ("$ONCE", literal), ("workspace/${}", brace),
                 ("workspace/${UNCLOSED", unterminated), ("workspace/$MORU_REGISTRY_MISSING_TEST", missing)]
        for raw, target in cases:
            with self.subTest(raw=raw):
                self.write({"projects": [{"root": raw, "aliases": ["launch"]}]})
                self.assertEqual(str(target), self.parity(**env)["selected_project"]["path"])
        # An empty expansion becomes Path('.'), not an absent empty OS path.
        (self.base / "AGENTS.md").touch()
        self.write({"projects": [{"root": "$EMPTY_ROOT", "aliases": ["launch"]}]})
        self.assertEqual(str(self.base), self.parity(EMPTY_ROOT="")["selected_project"]["path"])

    def test_environment_registry_and_search_roots_share_expansion(self):
        self.write({"projects": [{"root": "$REGISTRY_TARGET", "aliases": ["launch"]}],
                    "search_roots": ["${REGISTRY_WORKSPACE}"]})
        env = {"REGISTRY_TARGET": str(self.target), "REGISTRY_WORKSPACE": str(self.workspace)}
        self.parity(**env, MORU_PROJECT_SEARCH_ROOTS="${REGISTRY_WORKSPACE}")
        # Use a separate default file so --registry is not needed for this path.
        state = self.base / "state"
        state.mkdir(exist_ok=True)
        (state / "projects.json").write_bytes(self.registry.read_bytes())
        for backend, path in (("python", None), ("auto", None), ("auto", str(self.empty))):
            command = [str(self.entry), "project-discover", "--request", "launch", "--cwd", str(self.current), "--format", "json"]
            done = subprocess.run(command, cwd=self.base, capture_output=True, timeout=10,
                env={**self.env, **env, "REGISTRY_STATE": str(state),
                     "MORU_PROJECT_REGISTRY": "${REGISTRY_STATE}/projects.json", "MORU_LAUNCHER_BACKEND": backend,
                     **({"PATH": path} if path else {})})
            self.assertEqual(0, done.returncode, done.stderr)
            if backend == "python": expected = result(done)
            else: self.assertEqual(expected, result(done))

    def test_registered_entry_manifest_uses_the_same_snapshot_without_python_child(self):
        import agent_project_discovery as discovery
        self.write({"projects": [{"root": str(self.target), "aliases": ["launch"]}]})
        args = dict(request="launch", cwd=self.current, runtime="codex", registry_path=self.registry)
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = discovery.build_entry_manifest(**args)
        with patch.dict(os.environ, {**self.env, "PATH": str(self.empty)}, clear=True), \
             patch.object(discovery, "find_project_root", side_effect=AssertionError("Python project lookup")), \
             patch.object(discovery, "_scan_roots", side_effect=AssertionError("Python roots")), \
             patch.object(discovery, "load_registry", wraps=discovery.load_registry) as load:
            self.assertEqual(expected, discovery.build_entry_manifest(**args))
            load.assert_called_once()

    def test_unusual_aliases_named_homes_and_groups_preserve_python_fallback(self):
        entries = [{"root": str(self.target), "aliases": "launch"},
                   {"root": str(self.target), "aliases": None},
                   {"root": "~definitely_missing_moru_native_registry_user", "aliases": ["launch"]},
                   {"root": str(self.target), "aliases": ["ΟΣ"]}]
        for entry in entries:
            with self.subTest(entry=entry):
                self.write({"projects": [entry]})
                self.assertEqual(result(self.call(backend="python")), result(self.call()))
                self.assertEqual(127, self.call(PATH=str(self.empty)).returncode)
        self.write({"projects": [{"root": str(self.target), "aliases": ["launch"]}], "workspace_groups": [{"name": "group"}]})
        self.assertEqual(result(self.call(backend="python")), result(self.call()))
        self.assertEqual(127, self.call(PATH=str(self.empty)).returncode)
