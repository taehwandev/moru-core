"""Real Python/native next parity, lifecycle boundaries and no-Python proof."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from native_launcher_support import copied_build_root
from native_next_support import invoke_next, prepare_next, seed
from native_pretool_support import PROJECT, result


class NativeNextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-next-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.launcher, self.project = prepare_next(self.base)
        self.git_only = self.base / "git-only"
        self.git_only.mkdir()
        (self.git_only / "git").symlink_to(shutil.which("git"))

    def call(self, args=None, **overrides):
        return invoke_next(self.launcher, self.base, self.project, args, **overrides)

    def test_clean_cli_formats_and_framework_markers_match_without_python(self):
        forms = [[], ["--format", "json"], ["--project", str(self.project)],
                 ["--project", str(self.project), "--format", "markdown"],
                 ["--project", str(self.project), "--format", "json"]]
        for args in forms:
            baseline = self.call(args, backend="python")
            self.assertEqual(0, baseline.returncode, baseline.stderr)
            self.assertEqual(result(baseline), result(self.call(args)))
            self.assertEqual(result(baseline), result(self.call(args, PATH=str(self.git_only))))
        # Ignored marker fixtures stay clean; only these synthetic paths are excluded.
        with (self.project / ".git/info/exclude").open("a") as stream:
            stream.write("\npackage.json\nCargo.toml\ngo.mod\nPackage.swift\ngradlew\n")
        for marker in ("package.json", "Cargo.toml", "go.mod", "Package.swift", "gradlew"):
            path = self.project / marker
            path.write_text("synthetic\n")
            try:
                baseline = self.call(backend="python")
                self.assertTrue(json.loads(baseline.stdout)["verification"]["suggested_commands"])
                self.assertEqual(result(baseline), result(self.call(PATH=str(self.git_only))))
            finally:
                path.unlink()

    def test_terminal_history_preserves_output_and_state_for_all_runtime_sessions(self):
        seed(self.project)
        before = {str(p.relative_to(self.project)): p.read_bytes()
                  for p in (self.project / ".moru").rglob("*") if p.is_file()}
        for key in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "ANTIGRAVITY_CONVERSATION_ID"):
            overrides = {key: "synthetic-next"}
            baseline = self.call(backend="python", **overrides)
            self.assertEqual("no_active_run", json.loads(baseline.stdout)["status"])
            self.assertEqual(result(baseline), result(self.call(PATH=str(self.git_only), **overrides)))
        after = {str(p.relative_to(self.project)): p.read_bytes()
                 for p in (self.project / ".moru").rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_active_and_unknown_state_never_gain_native_completion_advice(self):
        for state in ("running", "paused", "resuming", "claiming", "blocked", "interrupted", "reconcile_required", "unknown"):
            seed(self.project, state)
            baseline = self.call(backend="python", CODEX_THREAD_ID="synthetic-next")
            if state in ("running", "paused", "resuming"):
                self.assertEqual("active_run", json.loads(baseline.stdout)["status"])
            self.assertEqual(result(baseline), result(self.call(CODEX_THREAD_ID="synthetic-next")))
            self.assertEqual(127, self.call(CODEX_THREAD_ID="synthetic-next", PATH=str(self.git_only)).returncode)

    def test_cli_fallbacks_and_unicode_paths_preserve_parity(self):
        evidence = seed(self.project, "running")
        forms = [["--help"], ["--project"], ["--format", "yaml"],
                 ["--project", ".", "--format", "json"],
                 ["--format", "json", "--project", str(self.project)]]
        for args in forms:
            self.assertEqual(result(self.call(args, backend="python")), result(self.call(args)))
            self.assertEqual(127, self.call(args, PATH=str(self.git_only)).returncode)
        (self.project / "한글 dirty.py").write_text("synthetic = 1\n")
        baseline = self.call(backend="python")
        self.assertTrue(json.loads(baseline.stdout)["verification"]["changed_paths"])
        self.assertEqual(result(baseline), result(self.call(PATH=str(self.git_only))))
        (self.project / "-uncertain.py").write_text("synthetic = 1\n")
        self.assertEqual(result(self.call(backend="python")), result(self.call()))
        self.assertEqual(127, self.call(PATH=str(self.git_only)).returncode)

    def test_missing_busy_and_symlink_locks_do_not_skip_python_effects(self):
        self.assertEqual(127, self.call(CODEX_THREAD_ID="synthetic-next", PATH=str(self.git_only)).returncode)
        self.call(backend="python", CODEX_THREAD_ID="synthetic-next")
        for name in (".state.lock.lock", ".run-registry.json.lock"):
            with (self.project / ".moru" / name).open("rb") as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(127, self.call(CODEX_THREAD_ID="synthetic-next", PATH=str(self.git_only)).returncode)
            path = self.project / ".moru" / name
            path.unlink()
            path.symlink_to(self.base / "absent")
            self.assertEqual(127, self.call(CODEX_THREAD_ID="synthetic-next", PATH=str(self.git_only)).returncode)
            path.unlink()
            path.touch()

    def test_environment_overrides_missing_git_and_noncanonical_home_select_python(self):
        overrides = [{"PYTHONPATH": "synthetic"}, {"MORU_WORKER_EVIDENCE": "synthetic"},
                     {"HOME": str(self.base / "home") + "/."}]
        for values in overrides:
            self.assertEqual(result(self.call(backend="python", **values)), result(self.call(**values)))
            self.assertEqual(127, self.call(PATH=str(self.git_only), **values).returncode)
        empty = self.base / "empty"
        empty.mkdir()
        self.assertEqual(127, self.call(PATH=str(empty)).returncode)

    def test_changed_source_forces_python_after_verified_install(self):
        source = copied_build_root(self.base / "source")
        shutil.copytree(PROJECT / "scripts", source / "scripts", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("AGENTS.md", "index.md"):
            shutil.copy2(PROJECT / name, source / name)
        isolated = self.base / "isolated"
        isolated.mkdir()
        launcher, project = prepare_next(isolated, source)
        expected = invoke_next(launcher, isolated, project, backend="python", source=source)
        self.assertEqual(result(expected), result(invoke_next(launcher, isolated, project,
            PATH=str(self.git_only), source=source)))
        path = source / "scripts/agent_next_action.py"
        path.write_bytes(path.read_bytes() + b"\n# synthetic source change\n")
        self.assertEqual(result(expected), result(invoke_next(launcher, isolated, project, source=source)))
        self.assertEqual(127, invoke_next(launcher, isolated, project, PATH=str(self.git_only), source=source).returncode)

    def test_git_argv_cwd_exit_and_decode_errors_preserve_python_behavior(self):
        spy_dir = self.base / "spy"
        spy_dir.mkdir()
        spy = spy_dir / "git"
        record = self.base / "git-record.json"
        prefix = ("#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\n"
                  + "Path(" + repr(str(record)) + ").write_text(json.dumps([os.getcwd(),sys.argv[1:]]))\n")
        for body in ("", "sys.exit(3)\n", "sys.stderr.buffer.write(bytes([255]))\n"):
            spy.write_text(prefix + body)
            spy.chmod(0o755)
            path = str(spy_dir) + os.pathsep + os.environ["PATH"]
            baseline = self.call(backend="python", PATH=path)
            self.assertEqual(result(baseline), result(self.call(PATH=path)))
            self.assertEqual([str(self.project), ["status", "--porcelain", "--untracked-files=all"]],
                             json.loads(record.read_text()))

    def test_registry_locks_are_released_before_git_status(self):
        seed(self.project)
        spy_dir = self.base / "lock-spy"
        spy_dir.mkdir()
        spy = spy_dir / "git"
        locks = [str(self.project / ".moru" / name)
                 for name in (".state.lock.lock", ".run-registry.json.lock")]
        spy.write_text("#!" + sys.executable + "\nimport fcntl\n"
            + "for path in " + repr(locks) + ":\n"
            + "    with open(path, 'rb') as stream:\n"
            + "        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n")
        spy.chmod(0o755)
        baseline = self.call(backend="python", CODEX_THREAD_ID="synthetic-next",
                             PATH=str(spy_dir) + os.pathsep + os.environ["PATH"])
        self.assertEqual(0, baseline.returncode, baseline.stderr)
        self.assertEqual(result(baseline), result(self.call(
            CODEX_THREAD_ID="synthetic-next", PATH=str(spy_dir))))

    def test_changed_files_test_targets_limits_and_renames_match_without_python(self):
        (self.project / "src").mkdir()
        (self.project / "tests").mkdir()
        (self.project / "src/foo-bar.py").write_text("synthetic = 1\n")
        for name in ["test_foo_bar", "test_support_foo_bar", *["test_case_%02d" % i for i in range(12)]]:
            (self.project / "tests" / (name + ".py")).write_text("synthetic = 1\n")
        for args in (["--project", str(self.project), "--format", "json"],
                     ["--project", str(self.project), "--format", "markdown"]):
            baseline = self.call(args, backend="python")
            self.assertEqual(0, baseline.returncode, baseline.stderr)
            self.assertEqual(result(baseline), result(self.call(args, PATH=str(self.git_only))))
        from native_pretool_support import environment
        env = environment(self.base)
        for args in (["add", "."], ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                                   "commit", "-qm", "synthetic"],
                     ["mv", "src/foo-bar.py", "src/renamed.py"]):
            subprocess.run(["git", *args], cwd=self.project, env=env, check=True, capture_output=True)
        (self.project / "tests/test_case_00.py").unlink()
        baseline = self.call(backend="python")
        self.assertEqual(result(baseline), result(self.call(PATH=str(self.git_only))))

    def test_symlink_changed_paths_keep_python_resolution(self):
        external = self.base / "external.py"
        external.write_text("synthetic = 1\n")
        (self.project / "linked.py").symlink_to(external)
        (self.project / "chain.py").symlink_to("linked.py")
        (self.project / "broken.py").symlink_to("absent.py")
        (self.project / "loop.py").symlink_to("loop.py")
        directory = self.base / "external-directory"
        directory.mkdir()
        (self.project / "directory.py").symlink_to(directory, target_is_directory=True)
        baseline = self.call(backend="python")
        self.assertEqual(result(baseline), result(self.call()))
        self.assertEqual(result(baseline), result(self.call(PATH=str(self.git_only))))

    def test_symlinked_test_directories_and_framework_markers_match(self):
        external = self.base / "external-tests"
        external.mkdir()
        (external / "test_code.py").write_text("synthetic = 1\n")
        (self.project / "tests").symlink_to(external, target_is_directory=True)
        (self.project / "code.py").write_text("synthetic = 1\n")
        baseline = self.call(backend="python")
        self.assertIn("tests.test_code", json.loads(baseline.stdout)["verification"]["matched_test_modules"])
        self.assertEqual(result(baseline), result(self.call(PATH=str(self.git_only))))
        (self.project / "code.py").unlink()
        (self.project / "tests").unlink()
        for marker in ("Cargo.toml", "package.json"):
            (external / marker).write_text("synthetic\n")
            (self.project / marker).symlink_to(external / marker)
            baseline = self.call(backend="python")
            self.assertEqual(result(baseline), result(self.call(PATH=str(self.git_only))))

    def test_uncertain_metadata_errors_keep_exact_python_result(self):
        spy_dir = self.base / "long-path-spy"
        spy_dir.mkdir()
        spy = spy_dir / "git"
        spy.write_text("#!" + sys.executable + "\nimport sys\nsys.stdout.write('?? ' + 'x' * 5000 + '.py\\n')\n")
        spy.chmod(0o755)
        path = str(spy_dir) + os.pathsep + os.environ["PATH"]
        baseline = self.call(backend="python", PATH=path)
        self.assertEqual(result(baseline), result(self.call(PATH=path)))
        self.assertEqual(127, self.call(PATH=str(spy_dir)).returncode)

    def test_transported_bundle_resolves_linked_verification_targets(self):
        from support.native_bundle import install_bundle, pack_bundle
        archive = self.base / "native-links.tar.gz"
        pack_bundle(PROJECT, archive)
        source = copied_build_root(self.base / "transported source")
        shutil.copytree(PROJECT / "scripts", source / "scripts", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("AGENTS.md", "index.md"):
            shutil.copy2(PROJECT / name, source / name)
        install_bundle(source, archive)
        isolated = self.base / "transported-consumer"
        isolated.mkdir()
        launcher, project = prepare_next(isolated, source)
        external = self.base / "transported-target.py"
        external.write_text("synthetic = 1\n")
        (project / "linked.py").symlink_to(external)
        for format in ("json", "markdown"):
            args = ["--project", str(project), "--format", format]
            baseline = invoke_next(launcher, isolated, project, args, backend="python", source=source)
            self.assertEqual(0, baseline.returncode, baseline.stderr)
            self.assertEqual(result(baseline), result(invoke_next(launcher, isolated, project, args,
                PATH=str(self.git_only), source=source)))

    def test_unicode_and_space_paths_match_with_both_git_quote_modes(self):
        from native_pretool_support import environment
        (self.project / "한글 file.py").write_text("synthetic = 1\n")
        (self.project / "space name.py").write_text("synthetic = 1\n")
        for mode in ("true", "false"):
            subprocess.run(["git", "config", "core.quotePath", mode], cwd=self.project,
                           env=environment(self.base), capture_output=True, check=True)
            baseline = self.call(backend="python")
            self.assertEqual(0, baseline.returncode, baseline.stderr)
            self.assertEqual(result(baseline), result(self.call(PATH=str(self.git_only))))
