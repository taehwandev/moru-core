"""Path claims are a courtesy lock between agents editing one live web project.

The costly mistakes are two agents editing the same file, a folder claim that
fails to cover what is inside it, and an edit hook that blocks or crashes the
agent it runs in. Each rule is tested through the CLI entry point.
"""

from __future__ import annotations

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
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import live_web_checks  # noqa: E402
import path_claims  # noqa: E402


class PathClaimsTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name).resolve()
        (self.project / "src" / "components").mkdir(parents=True)
        self.clock = 1_800_000_000.0
        patcher = mock.patch.object(path_claims, "_now", side_effect=lambda: self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv: str, stdin: str = "") -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()), mock.patch.object(
            sys, "stdin", io.StringIO(stdin)
        ):
            code = path_claims.main(list(argv))
        return code, output.getvalue()

    def claim(self, holder: str, *paths: str, extra: tuple[str, ...] = ()) -> tuple[int, str]:
        args = ["claim", "--project", str(self.project), "--holder", holder]
        for path in paths:
            args += ["--path", path]
        return self.run_cli(*args, *extra)

    def status(self) -> list[dict]:
        code, output = self.run_cli("status", "--project", str(self.project), "--json")
        self.assertEqual(code, 0)
        return json.loads(output)

    def test_claim_writes_one_file_per_path(self) -> None:
        code, output = self.claim("a", "src/components/Header.tsx")
        self.assertEqual(code, 0, output)
        claims = self.status()
        self.assertEqual([c["path"] for c in claims], ["src/components/Header.tsx"])
        self.assertEqual(claims[0]["holder"], "a")
        files = list(path_claims.claims_dir(self.project).glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(set(json.loads(files[0].read_text())), {"path", "holder", "since", "expires"})

    def test_absolute_path_inside_project_is_stored_relative(self) -> None:
        code, _ = self.claim("a", str(self.project / "src" / "x.tsx"))
        self.assertEqual(code, 0)
        self.assertEqual(self.status()[0]["path"], "src/x.tsx")

    def test_other_holder_on_same_path_conflicts(self) -> None:
        self.claim("a", "src/x.tsx")
        code, output = self.claim("b", "src/x.tsx")
        self.assertEqual(code, path_claims.CONFLICT_EXIT)
        self.assertRegex(output, r"held by a since \S+: src/x\.tsx")

    def test_directory_claim_covers_children_both_ways(self) -> None:
        self.claim("a", "src/components")
        code, output = self.claim("b", "src/components/Header.tsx")
        self.assertEqual(code, path_claims.CONFLICT_EXIT)
        self.assertIn("held by a", output)
        self.claim("c", "lib/util.ts")
        code, _ = self.claim("d", "lib")
        self.assertEqual(code, path_claims.CONFLICT_EXIT)
        code, _ = self.claim("d", "src/componentsX.tsx")
        self.assertEqual(code, 0, "a sibling sharing a name prefix is not a child")

    def test_conflict_claims_nothing(self) -> None:
        self.claim("a", "src/x.tsx")
        code, _ = self.claim("b", "src/y.tsx", "src/x.tsx")
        self.assertEqual(code, path_claims.CONFLICT_EXIT)
        self.assertEqual([c["path"] for c in self.status()], ["src/x.tsx"])

    def test_path_outside_project_is_rejected(self) -> None:
        code, _ = self.claim("a", "../elsewhere.tsx")
        self.assertEqual(code, 1)
        self.assertEqual(self.status(), [])

    def test_release_path_and_refuses_other_holder(self) -> None:
        self.claim("a", "src/x.tsx", "src/y.tsx")
        code, output = self.run_cli("release", "--project", str(self.project), "--holder", "b", "--path", "src/x.tsx")
        self.assertEqual(code, path_claims.CONFLICT_EXIT)
        self.assertIn("held by a", output)
        code, _ = self.run_cli("release", "--project", str(self.project), "--holder", "a", "--path", "src/x.tsx")
        self.assertEqual(code, 0)
        self.assertEqual([c["path"] for c in self.status()], ["src/y.tsx"])

    def test_release_all_keeps_other_holders(self) -> None:
        self.claim("a", "src/x.tsx", "src/y.tsx")
        self.claim("b", "lib")
        code, _ = self.run_cli("release", "--project", str(self.project), "--holder", "a", "--all")
        self.assertEqual(code, 0)
        self.assertEqual([(c["path"], c["holder"]) for c in self.status()], [("lib", "b")])

    def test_expired_claim_is_cleaned_and_freed(self) -> None:
        self.claim("a", "src/x.tsx", extra=("--ttl", "60"))
        self.clock += 61
        self.assertEqual(self.status(), [])
        self.assertEqual(list(path_claims.claims_dir(self.project).glob("*.json")), [])
        code, _ = self.claim("b", "src/x.tsx")
        self.assertEqual(code, 0)

    def test_same_holder_reclaim_renews(self) -> None:
        self.claim("a", "src/x.tsx", extra=("--ttl", "60"))
        first = self.status()[0]
        self.clock += 50
        code, _ = self.claim("a", "src/x.tsx", extra=("--ttl", "60"))
        self.assertEqual(code, 0)
        renewed = self.status()[0]
        self.assertEqual(renewed["since"], first["since"])
        self.assertGreater(renewed["expires"], first["expires"])
        self.clock += 30
        self.assertEqual(len(self.status()), 1, "renewal must outlive the original expiry")

    def test_wait_gives_up_after_timeout(self) -> None:
        self.claim("a", "src/x.tsx")

        def advance(seconds: float) -> None:
            self.clock += seconds

        with mock.patch.object(path_claims.time, "sleep", side_effect=advance) as sleep:
            code, output = self.claim("b", "src/x.tsx", extra=("--wait", "3"))
        self.assertEqual(code, path_claims.CONFLICT_EXIT)
        self.assertIn("held by a", output)
        self.assertGreaterEqual(sleep.call_count, 3)

    def test_wait_succeeds_once_claim_expires(self) -> None:
        self.claim("a", "src/x.tsx", extra=("--ttl", "2"))

        def advance(seconds: float) -> None:
            self.clock += seconds

        with mock.patch.object(path_claims.time, "sleep", side_effect=advance):
            code, _ = self.claim("b", "src/x.tsx", extra=("--wait", "10"))
        self.assertEqual(code, 0)
        self.assertEqual(self.status()[0]["holder"], "b")

    def test_holder_defaults_to_session_env(self) -> None:
        with mock.patch.dict("os.environ", {"MORU_SESSION_ID": "session-7"}):
            self.run_cli("claim", "--project", str(self.project), "--path", "src/x.tsx")
        self.assertEqual(self.status()[0]["holder"], "session-7")
        with mock.patch.dict("os.environ", {"MORU_SESSION_ID": ""}):
            self.assertTrue(path_claims.default_holder().startswith("pid:"))

    def read_edits(self) -> list[dict]:
        log = path_claims.edits_log(self.project)
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def test_record_appends_session_files_time(self) -> None:
        code, _ = self.run_cli(
            "record", "--project", str(self.project), "--holder", "s1", "--files", "src/a.tsx", "src/b.tsx"
        )
        self.assertEqual(code, 0)
        self.run_cli("record", "--project", str(self.project), "--holder", "s2", "--files", "src/c.tsx")
        edits = self.read_edits()
        self.assertEqual([e["session"] for e in edits], ["s1", "s2"])
        self.assertEqual(edits[0]["files"], ["src/a.tsx", "src/b.tsx"])
        self.assertEqual(set(edits[0]), {"session", "files", "time"})

    def test_record_from_hook_records_project_relative_path(self) -> None:
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(self.project / "src" / "components" / "Header.tsx")},
            "cwd": str(self.project),
        }
        code, _ = self.run_cli("record", "--from-hook", "--holder", "s1", stdin=json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertEqual(self.read_edits()[0]["files"], ["src/components/Header.tsx"])
        notebook = {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "n.ipynb"}, "cwd": str(self.project)}
        self.run_cli("record", "--from-hook", "--holder", "s1", stdin=json.dumps(notebook))
        self.assertEqual(self.read_edits()[1]["files"], ["n.ipynb"])

    def test_record_from_hook_ignores_other_tools_and_bad_input(self) -> None:
        inputs = [
            "",
            "not json",
            "[1, 2]",
            json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(self.project)}),
            json.dumps({"tool_name": "Write", "tool_input": {}, "cwd": str(self.project)}),
            json.dumps({"tool_name": "Write", "tool_input": "oops", "cwd": str(self.project)}),
            json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/elsewhere/x.ts"}, "cwd": str(self.project)}),
        ]
        for stdin in inputs:
            with self.subTest(stdin=stdin):
                code, _ = self.run_cli("record", "--from-hook", stdin=stdin)
                self.assertEqual(code, 0)
        self.assertEqual(self.read_edits(), [])


class PathClaimsCheckTests(unittest.TestCase):
    """``check`` replaces a screenshot, so a wrong match or a wrong exit hides a broken save."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name).resolve()

    def write_checks(self, *lines) -> None:
        log = live_web_checks.checks_log(self.project)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("".join((line if isinstance(line, str) else json.dumps(line)) + "\n" for line in lines))

    @staticmethod
    def entry(time: str, files: list, errors: tuple = (), reload_failed: bool = False, views=None) -> dict:
        return {
            "time": time,
            "files": files,
            "views": views if views is not None else [{"viewport": "Phone", "elements": 1, "boxes": [[0, 0, 388, 47]]}],
            "errors": list(errors),
            "reloadFailed": reload_failed,
        }

    def check(self, *argv: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = path_claims.main(["check", "--project", str(self.project), *argv])
        return code, output.getvalue().strip()

    def test_latest_check_for_given_files_skips_newer_unrelated_ones(self) -> None:
        self.write_checks(
            self.entry("2026-10-15T09:10:00Z", ["src/components/Header.tsx"], errors=("old",)),
            self.entry("2026-10-15T09:16:12Z", ["src/components/Header.tsx"], views=[
                {"viewport": "Phone", "elements": 1, "boxes": [[0, 0, 388, 47]]},
                {"viewport": "Desktop", "elements": 1, "boxes": []},
            ]),
            self.entry("2026-10-15T09:20:00Z", ["src/App.tsx"], errors=("boom",)),
        )
        code, output = self.check("--files", "src/components/Header.tsx")
        self.assertEqual(code, 0)
        self.assertEqual(
            output,
            "check 2026-10-15T09:16:12Z src/components/Header.tsx: Phone 1 element (388x47), "
            "Desktop 1 element; errors 0; reload ok",
        )

    def test_without_files_prints_latest_overall(self) -> None:
        self.write_checks(
            self.entry("2026-10-15T09:16:12Z", ["src/components/Header.tsx"]),
            self.entry("2026-10-15T09:20:00Z", ["src/App.tsx"], errors=("boom", "second")),
        )
        code, output = self.check()
        self.assertEqual(code, live_web_checks.CHECK_PROBLEM_EXIT)
        self.assertTrue(output.startswith("check 2026-10-15T09:20:00Z src/App.tsx:"), output)
        self.assertIn("errors 2: boom", output)

    def test_suffix_matching_in_both_directions_but_not_partial_names(self) -> None:
        self.write_checks(self.entry("2026-10-15T09:16:12Z", ["src/components/Header.tsx"]))
        self.assertEqual(self.check("--files", "Header.tsx")[0], 0)
        self.assertEqual(self.check("--files", "components/Header.tsx")[0], 0)
        self.assertEqual(self.check("--files", str(self.project / "src/components/Header.tsx"))[0], 0)
        self.assertEqual(self.check("--files", "eader.tsx")[0], live_web_checks.CHECK_MISSING_EXIT)
        self.write_checks(self.entry("2026-10-15T09:16:12Z", ["Header.tsx"]))
        self.assertEqual(self.check("--files", "web/src/Header.tsx")[0], 0)

    def test_exit_codes(self) -> None:
        self.assertEqual(self.check(), (live_web_checks.CHECK_MISSING_EXIT, "no check yet"))
        self.write_checks(self.entry("2026-10-15T09:16:12Z", ["a.tsx"]))
        self.assertEqual(self.check()[0], 0)
        self.write_checks(self.entry("2026-10-15T09:16:12Z", ["a.tsx"], reload_failed=True))
        code, output = self.check()
        self.assertEqual(code, live_web_checks.CHECK_PROBLEM_EXIT)
        self.assertTrue(output.endswith("errors 0; reload FAILED"), output)
        self.write_checks(self.entry("2026-10-15T09:16:12Z", ["a.tsx"], errors=("TypeError: x",)))
        self.assertEqual(self.check()[0], live_web_checks.CHECK_PROBLEM_EXIT)
        self.assertEqual(self.check("--files", "b.tsx"), (live_web_checks.CHECK_MISSING_EXIT, "no check yet for b.tsx"))

    def test_malformed_lines_are_skipped(self) -> None:
        self.write_checks(
            self.entry("2026-10-15T09:16:12Z", ["a.tsx"]),
            "{broken",
            "[1, 2]",
            "",
            {"time": "2026-10-15T09:17:00Z", "files": "a.tsx", "views": "x", "errors": 3},
            {"time": "2026-10-15T09:18:00Z", "files": ["b.tsx"], "views": [None, {"viewport": "Phone", "boxes": [["x"]]}]},
        )
        self.assertEqual(self.check("--files", "a.tsx")[0], 0)
        code, output = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(output, "check 2026-10-15T09:18:00Z b.tsx: ?, Phone 0 elements; errors 0; reload ok")

    def test_reads_only_the_tail_of_a_large_log(self) -> None:
        old = self.entry("2026-10-15T08:00:00Z", ["old.tsx"])
        filler = [self.entry("2026-10-15T09:00:00Z", ["filler.tsx"]) for _ in range(800)]
        self.write_checks(old, *filler, self.entry("2026-10-15T09:30:00Z", ["new.tsx"]))
        self.assertGreater(live_web_checks.checks_log(self.project).stat().st_size, live_web_checks.CHECK_TAIL_BYTES)
        self.assertEqual(self.check("--files", "new.tsx")[0], 0)
        self.assertEqual(self.check("--files", "old.tsx")[0], live_web_checks.CHECK_MISSING_EXIT)
        self.assertTrue(all(isinstance(entry, dict) for entry in live_web_checks.read_checks(self.project)))

    def test_since_drops_older_checks(self) -> None:
        self.write_checks(self.entry("2026-10-15T09:16:12Z", ["a.tsx"]), {"time": "garbage", "files": ["a.tsx"]})
        self.assertEqual(self.check("--since", "2026-10-15T09:16:00Z")[0], 0)
        self.assertEqual(self.check("--since", "2026-10-15T09:17:00+00:00")[0], live_web_checks.CHECK_MISSING_EXIT)

    def test_json_shape(self) -> None:
        code, output = self.check("--json")
        self.assertEqual((code, json.loads(output)), (live_web_checks.CHECK_MISSING_EXIT, {"status": "none", "check": None}))
        problem = self.entry("2026-10-15T09:16:12Z", ["a.tsx"], errors=("boom",))
        self.write_checks(problem)
        code, output = self.check("--json", "--files", "a.tsx")
        self.assertEqual((code, json.loads(output)), (live_web_checks.CHECK_PROBLEM_EXIT, {"status": "problems", "check": problem}))
        clean = self.entry("2026-10-15T09:17:00Z", ["a.tsx"])
        self.write_checks(problem, clean)
        self.assertEqual(json.loads(self.check("--json")[1]), {"status": "ok", "check": clean})


class PathClaimsProcessTests(unittest.TestCase):
    """The hook and agents run the file as a script, not through ``main``."""

    def test_script_conflict_exit_and_hook_record(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        project = Path(directory.name).resolve()
        script = [sys.executable, str(SCRIPTS / "path_claims.py")]

        def run(holder: str, *argv: str, stdin: str = "") -> subprocess.CompletedProcess:
            env = dict(os.environ, MORU_SESSION_ID=holder)
            return subprocess.run([*script, *argv], input=stdin, capture_output=True, text=True, env=env)

        self.assertEqual(run("t1", "claim", "--project", str(project), "--path", "src").returncode, 0)
        blocked = run("t2", "claim", "--project", str(project), "--path", "src/a.tsx")
        self.assertEqual(blocked.returncode, path_claims.CONFLICT_EXIT)
        self.assertTrue(blocked.stdout.startswith("held by t1 since "), blocked.stdout)
        hook = {"tool_name": "Write", "tool_input": {"file_path": str(project / "src/a.tsx")}, "cwd": str(project)}
        self.assertEqual(run("t1", "record", "--from-hook", stdin=json.dumps(hook)).returncode, 0)
        self.assertEqual(run("t1", "record", "--from-hook", stdin="{broken").returncode, 0)
        edits = path_claims.edits_log(project).read_text().splitlines()
        self.assertEqual([json.loads(line)["session"] for line in edits], ["t1"])
        self.assertEqual(run("t1", "release", "--project", str(project), "--all").returncode, 0)
        self.assertEqual(run("t2", "status", "--project", str(project)).stdout.strip(), "no active claims")
        missing = run("t1", "check", "--project", str(project), "--files", "src/a.tsx")
        self.assertEqual((missing.returncode, missing.stdout.strip()), (live_web_checks.CHECK_MISSING_EXIT, "no check yet for src/a.tsx"))


if __name__ == "__main__":
    unittest.main()
