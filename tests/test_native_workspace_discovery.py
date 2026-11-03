"""Workspace groups through generated discovery and the Python entry builder."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from native_pretool_support import environment, prepare, result


class NativeWorkspaceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-groups-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.current = prepare(self.base)
        self.env = environment(self.base)
        self.empty = self.base / "empty-path"
        self.empty.mkdir()
        self.workspace = self.base / "workspace"
        self.app = self.project_at("sample-app")
        self.web = self.project_at("sample-web")
        self.registry = self.base / "registry.json"

    def project_at(self, name):
        path = self.base / "workspace" / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "AGENTS.md").touch()
        return path

    def write(self, groups, **fields):
        self.registry.write_text(json.dumps({"workspace_groups": groups, **fields}))

    def group(self, **fields):
        return {"name": "suite", "aliases": ["company", "한글 묶음"], "members": [
            {"role": "app", "root": str(self.app), "aliases": ["desktop"]},
            {"role": "web", "root": str(self.web), "aliases": ["browser"]}], **fields}

    def call(self, request="suite", *, backend="auto", args=(), **overrides):
        command = [str(self.entry), "project-discover", "--request", request,
            "--cwd", str(self.workspace), "--registry", str(self.registry), "--format", "json", *args]
        return subprocess.run(command, cwd=self.base, capture_output=True, timeout=10,
            env={**self.env, "MORU_LAUNCHER_BACKEND": backend, **overrides})

    def parity(self, request="suite", *, args=(), **env):
        expected = self.call(request, backend="python", args=args, **env)
        self.assertIn(expected.returncode, (0, 2, 3), expected.stderr)
        self.assertFalse(expected.stderr)
        self.assertEqual(result(expected), result(self.call(request, args=args, **env)))
        self.assertEqual(result(expected), result(self.call(request, args=args, PATH=str(self.empty), **env)))
        return json.loads(expected.stdout) if "--format" not in args else expected.stdout

    def test_group_alias_remains_ambiguous_and_member_alias_selects_exactly(self):
        self.write([self.group()])
        for request in ("suite", "company", "한글 묶음", "HANDFUL", "xsuite", "suite-extra"):
            for format in ("text", "json"):
                with self.subTest(request=request, format=format):
                    self.parity(request, args=["--format", format])
        value = self.parity()
        self.assertEqual("ambiguous", value["status"])
        self.assertIsNone(value["selected_project"])
        for request, target in (("suite web", self.web), ("APP", self.app), ("browser", self.web),
                                ("desktop", self.app), ("sample web", self.web), ("sample-app", self.app)):
            with self.subTest(request=request):
                self.assertEqual(str(target), self.parity(request)["selected_project"]["path"])
        self.assertEqual("not_found", self.parity("xsuite")["status"])

    def test_alias_normalization_name_id_fallback_and_member_role_precedence(self):
        cases = [({"name": "", "id": "idgroup"}, "idgroup"),
                 ({"name": None, "id": ""}, "workspace"),
                 ({"name": [], "id": "idgroup"}, "idgroup"),
                 ({"aliases": "ignored"}, "suite"),
                 ({"aliases": [None, 12, "suite", "suite"]}, "suite")]
        for fields, request in cases:
            with self.subTest(fields=fields):
                self.write([self.group(**fields)])
                self.assertEqual("ambiguous", self.parity(request)["status"])
        for fields, request in (({"role": "", "name": "named"}, "named"),
                                 ({"role": False, "name": "named"}, "named"),
                                 ({"role": 3, "name": "named"}, "sample-app"),
                                 ({"role": "app", "aliases": None}, "app"),
                                 ({"role": "app", "aliases": "ignored"}, "app")):
            self.write([self.group(members=[{"root": str(self.app), **fields}])])
            self.assertEqual(str(self.app), self.parity(request)["selected_project"]["path"])

    def test_malformed_and_disabled_groups_and_members_follow_exact_boolean_rule(self):
        for groups in (None, {}, "ignored", [None, 3, "ignored"], [self.group(members=None)],
                       [self.group(members={})], [self.group(disabled=True)]):
            with self.subTest(groups=groups):
                self.write(groups)
                self.assertEqual("not_found", self.parity()["status"])
        self.write([self.group(disabled=1)])
        self.assertEqual("ambiguous", self.parity()["status"])
        self.write([self.group(members=[None, 3, "ignored",
            {"root": str(self.app), "disabled": True}, {"root": str(self.web), "disabled": 1}])])
        self.assertEqual(str(self.web), self.parity()["selected_project"]["path"])

    def test_root_path_truthiness_missing_paths_and_unmarked_directories(self):
        plain = self.workspace / "plain"
        plain.mkdir()
        broken = self.workspace / "broken"
        broken.symlink_to(self.workspace / "absent")
        for raw in ("", False, 0, [], {}, None):
            self.write([self.group(members=[{"root": raw, "path": str(self.app)}])])
            self.assertEqual(str(self.app), self.parity()["selected_project"]["path"])
        self.write([self.group(members=[{"root": 123, "path": str(self.app)},
            {"path": str(plain)}, {"path": str(broken)}, {"root": str(self.workspace / "absent")}, {}])])
        self.assertEqual("not_found", self.parity()["status"])

    def test_group_merge_keeps_registry_cwd_group_scan_order_and_unique_aliases(self):
        link = self.workspace / "linked-app"
        link.symlink_to(self.app, target_is_directory=True)
        self.write([self.group(aliases=["launch", "suite", "launch"], members=[
            {"path": str(self.app), "role": "app", "aliases": ["launch", "app", "launch"]},
            {"path": str(link), "role": "desktop"}]),
            self.group(name="other", aliases=["launch"], members=[{"path": str(self.app)}])],
            projects=[{"root": str(self.app), "aliases": ["launch", "launch"]}])
        chosen = self.parity("launch", args=["--cwd", str(self.app), "--search-root", str(self.workspace)])["selected_project"]
        self.assertEqual(["registry", "cwd", "workspace_group", "search_root"], chosen["sources"])
        self.assertEqual(["launch", "suite", "app", "sample-app", "desktop", "other"], chosen["aliases"])
        self.assertEqual(["registry alias or project name matched request", "current working directory is inside a project",
            "workspace group member alias matched request", "workspace group alias matched request",
            "project marker found under configured search root", "candidate name appeared in request"], chosen["reasons"])

    def test_member_paths_expand_variables_home_relative_files_and_symlinks(self):
        home_project = self.base / "home/home-app"
        home_project.mkdir()
        (home_project / "AGENTS.md").touch()
        link = self.workspace / "linked-app"
        link.symlink_to(self.app, target_is_directory=True)
        nested = self.app / "nested"
        nested.mkdir()
        (nested / "source.txt").touch()
        cases = [("${GROUP ROOT}", self.app), ("$GROUP_ROOT", self.app),
                 ("~/home-app", home_project), ("workspace/sample-app/./", self.app),
                 (str(nested / "source.txt"), self.app), (str(link), self.app)]
        for raw, target in cases:
            with self.subTest(raw=raw):
                self.write([self.group(members=[{"root": raw}])])
                self.assertEqual(str(target), self.parity(GROUP_ROOT=str(self.app),
                    **{"GROUP ROOT": str(self.app)})["selected_project"]["path"])

    def test_registry_changes_are_observed_without_a_cache(self):
        for path in (self.app, self.web, self.app):
            self.write([self.group(members=[{"path": str(path)}])])
            self.assertEqual(str(path), self.parity()["selected_project"]["path"])

    def test_entry_manifest_uses_native_candidates_and_python_scope_with_one_snapshot(self):
        import agent_project_discovery as discovery
        for request, mode in (("suite", "needs_target_decision"),
                              ("suite web", "primary_selected_checkpoint_before_expansion")):
            self.write([self.group()])
            args = dict(request=request, cwd=self.workspace, runtime="codex", registry_path=self.registry)
            with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                expected = discovery.build_entry_manifest(**args)
            with patch.dict(os.environ, {**self.env, "PATH": str(self.empty)}, clear=True), \
                 patch.object(discovery, "add_workspace_group_candidates", side_effect=AssertionError("Python group lookup")), \
                 patch.object(discovery, "_scan_roots", side_effect=AssertionError("Python traversal")), \
                 patch.object(discovery, "load_registry", wraps=discovery.load_registry) as load:
                actual = discovery.build_entry_manifest(**args)
                self.assertEqual(expected, actual)
                self.assertEqual(mode, actual["workspace_scope"]["scope_mode"])
                self.assertTrue(actual["workspace_scope"]["scope_checkpoint"]["required_before_secondary_write"])
                load.assert_called_once()

    def test_unusual_names_homes_case_and_request_paths_replay_python(self):
        groups = [self.group(name=123), self.group(name=True), self.group(name={"value": "suite"}),
                  self.group(members=[{"root": "~definitely_missing_moru_native_group_user"}]),
                  self.group(name="other", aliases=["ΟΣ"])]
        for group in groups:
            with self.subTest(group=group):
                self.write([group])
                self.assertEqual(result(self.call(backend="python")), result(self.call()))
                self.assertEqual(127, self.call(PATH=str(self.empty)).returncode)
        # Python's any() does not lowercase unused aliases after an exact match.
        self.write([self.group(aliases=["ΟΣ"])])
        self.parity()
        self.write([self.group()])
        self.parity(str(self.web))
        for request in ("'suite'", "ΟΣ"):
            self.assertEqual(result(self.call(request, backend="python")), result(self.call(request)))
            self.assertEqual(127, self.call(request, PATH=str(self.empty)).returncode)


if __name__ == "__main__":
    unittest.main()
