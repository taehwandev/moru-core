"""Folding a candidate inbox must be invisible to the store that reads it.

The writer already keeps one record per lesson, but only for lessons that
recur; a lesson that stopped happening keeps whatever files it had. On the
reference machine that left 824 legacy files beside 80 canonical ones -- 904
records for 296 lessons, read in full by every preflight.

The danger is that a lesson's occurrence count is the *sum* across its
records, so a plain delete would quietly reduce it. These tests hold the fold
to the store's own arithmetic: after folding, the next upsert must count what
it would have counted before.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_lesson_store import upsert_retrospective_candidate
from agent_state_lock import state_lock

_spec = importlib.util.spec_from_file_location("lessons_compact", SCRIPTS / "lessons-compact.py")
compact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compact)


def _candidate(lesson_id: str, created_at: str, **overrides) -> dict:
    record = {
        "schema_version": 1,
        "lesson_id": lesson_id,
        "created_at": created_at,
        "first_seen_at": created_at,
        "last_seen_at": created_at,
        "occurrence_count": 1,
        "occurrence_keys": [f"key-{created_at}"],
        "failure_type": "finish_gate_failure",
        "root_cause": "finish_failed_before_completion",
        "promotion_status": "candidate",
        "status": "candidate",
    }
    record.update(overrides)
    return record


class CompactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        self.inbox = compact.inbox_path(self.state)
        self.inbox.mkdir(parents=True)

    def _write(self, name: str, record: dict) -> Path:
        path = self.inbox / name
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def _files(self) -> set[str]:
        return {path.name for path in self.inbox.glob("*.json")}

    def test_installed_alias_uses_native_for_supported_read_only_arguments(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        self.state = self.state.resolve()
        self.inbox = compact.inbox_path(self.state)
        home = self.state / "home"
        home.mkdir()
        install(home, ROOT)
        entry = home / ".moru/bin/moru-hook"
        self._write("legacy.json", _candidate("lesson", "2026-01-01T00:00:00Z"))
        before = {path.name: path.read_bytes() for path in self.inbox.iterdir()}
        env = {**environment(self.state, ROOT), "MORU_STATE_HOME": str(self.state)}
        shim = self.state / "shim"
        shim.mkdir()
        python = shim / "python3"
        python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 37\n', encoding="utf-8")
        python.chmod(0o755)

        def run(args, **overrides):
            return subprocess.run([str(entry), "lessons-compact", *args], env={**env, **overrides},
                                  capture_output=True, timeout=10)

        for args in ([], ["--state-home", str(self.state)], [f"--state-home={self.state}"]):
            with self.subTest(args=args):
                oracle = run(args, MORU_LAUNCHER_BACKEND="python")
                actual = run(args, PATH=str(shim))
                self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                 (oracle.returncode, oracle.stdout, oracle.stderr))
                self.assertEqual(actual.returncode, 0)
                self.assertIn(b"nothing written", actual.stdout)
        for args in (["--state-home", "--apply", str(self.state)], ["--apply=false"],
                     ["--help"], ["--state-home", "."]):
            with self.subTest(args=args):
                result = run(args, PATH=str(shim))
                self.assertEqual(result.returncode, 37)
                self.assertEqual(result.stdout.decode().splitlines(), [str(entry), "lessons-compact", *args])
        self.assertEqual({path.name: path.read_bytes() for path in self.inbox.iterdir()}, before)
        (self.inbox / "linked.json").symlink_to(self.inbox / "legacy.json")
        declined = run([], PATH=str(shim))
        self.assertEqual(declined.returncode, 37)
        self.assertEqual(declined.stdout.decode().splitlines(), [str(entry), "lessons-compact"])

    def test_installed_apply_runs_natively_and_hands_off_only_untouched_folds(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        root = self.state.resolve()
        home = root / "home"
        home.mkdir()
        install(home, ROOT)
        entry = home / ".moru/bin/moru-hook"
        shim = root / "shim"
        shim.mkdir()
        trace = root / "continuation.json"
        python = shim / "python3"
        python.write_text(
            f"#!{sys.executable}\nimport pathlib, subprocess, sys\n"
            f"data = sys.stdin.buffer.read()\npathlib.Path({str(trace)!r}).write_bytes(data)\n"
            f"raise SystemExit(subprocess.run([{sys.executable!r}, *sys.argv[1:]], input=data).returncode)\n",
            encoding="utf-8",
        )
        python.chmod(0o755)
        stamp = "2026-01-01T00:00:00Z"
        for state_name in ("native", "mixed", "reference"):
            inbox = compact.inbox_path(root / state_name)
            inbox.mkdir(parents=True)
            for lesson in ("a", "b"):
                (inbox / f"old-{lesson}.json").write_text(json.dumps(_candidate(lesson, stamp)), encoding="utf-8")
            if state_name == "mixed":
                (inbox / "b.compact.tmp").write_text("legacy scratch", encoding="utf-8")

        def run(state, env):
            result = subprocess.run(
                [str(entry), "lessons-compact", "--apply", "--state-home", str(root / state)],
                env=env, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, b"")
            return result.stdout.splitlines()[1:]

        env = environment(root, ROOT)
        expected = run("reference", {**env, "MORU_LAUNCHER_BACKEND": "python"})
        self.assertEqual(run("native", {**env, "PATH": str(shim)}), expected)
        self.assertFalse(trace.exists(), "native apply unexpectedly started Python")
        self.assertEqual(run("mixed", {**env, "PATH": str(shim)}), expected)
        continued = json.loads(trace.read_bytes())
        self.assertEqual(continued["folds"], [["b", ["old-b.json"]]])
        self.assertEqual(continued["written"], 1)
        for state in ("native", "mixed"):
            inbox = compact.inbox_path(root / state)
            self.assertEqual(sorted(path.name for path in inbox.glob("*.json")), ["a.json", "b.json"])
            for path in inbox.glob("*.json"):
                self.assertEqual(path.read_bytes(), (compact.inbox_path(root / "reference") / path.name).read_bytes())
                lock = path.with_name(f".{path.name}.lock")
                self.assertEqual(lock.read_bytes(), b"")
                inode = lock.stat().st_ino
                with state_lock(path):
                    self.assertEqual(lock.stat().st_ino, inode)

        trace.unlink()
        inbox = compact.inbox_path(root / "contended")
        inbox.mkdir(parents=True)
        (inbox / "old-a.json").write_text(json.dumps(_candidate("a", stamp)), encoding="utf-8")
        target = inbox / "a.json"
        lock = inbox / ".a.json.lock"
        child = None
        try:
            with state_lock(target):
                inode = lock.stat().st_ino
                child = subprocess.Popen(
                    [str(entry), "lessons-compact", "--apply", "--state-home", str(root / "contended")],
                    env={**env, "PATH": str(shim)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                )
                self.assertTrue(select.select([child.stdout], [], [], 5)[0], "missing native plan")
                self.assertTrue(child.stdout.readline().startswith(b"inbox: "))
                self.assertFalse(target.exists())
                self.assertIsNone(child.poll())
                (inbox / "late-a.json").write_text(json.dumps(_candidate("a", stamp)), encoding="utf-8")
            _, errors = child.communicate(timeout=10)
        finally:
            if child is not None and child.poll() is None:
                child.kill()
                child.communicate()
        self.assertEqual(child.returncode, 0, errors)
        self.assertFalse(trace.exists(), "lock contention invoked Python")
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(json.loads(target.read_bytes())["occurrence_count"], 2)

        if os.geteuid() != 0:
            inbox = compact.inbox_path(root / "denied")
            inbox.mkdir(parents=True)
            legacy = inbox / "old-a.json"
            legacy.write_text(json.dumps(_candidate("a", stamp)), encoding="utf-8")
            with state_lock(inbox / "a.json"):
                pass
            inbox.chmod(0o555)
            try:
                failed = subprocess.run(
                    [str(entry), "lessons-compact", "--apply", "--state-home", str(root / "denied")],
                    env={**env, "PATH": str(shim)}, capture_output=True, timeout=10,
                )
            finally:
                inbox.chmod(0o755)
            self.assertEqual(failed.returncode, 1)
            self.assertIn(b"Permission denied", failed.stderr)
            self.assertFalse(trace.exists(), "native write error invoked the continuation")
            self.assertEqual(list(inbox.glob("*.json")), [legacy])

    def test_native_inbox_matches_plan_and_leaves_files_untouched(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        self.state = self.state.resolve()
        self.inbox = compact.inbox_path(self.state)
        home = self.state / "home"
        home.mkdir()
        install(home, ROOT)
        date = "2026-01-01T00:00:00Z"
        self._write("a-legacy.json", _candidate("한글", date, extra=10 ** 40))
        self._write("b-numeric.json", _candidate(12, date))
        self._write("c-legacy.json", _candidate("한글", date))
        self._write("ignored.txt", _candidate("ignored", date))
        self._write("empty-id.json", _candidate(False, date))
        (self.inbox / "broken.json").write_text("{broken", encoding="utf-8")
        (self.inbox / "list.json").write_text("[]", encoding="utf-8")
        before = {path.name: path.read_bytes() for path in self.inbox.iterdir()}

        def dry_run():
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(compact.main(["--state-home", str(self.state)]), 0)
            return out.getvalue()

        with mock.patch.dict(os.environ, environment(self.state, ROOT), clear=True):
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = compact.read_records(self.inbox)
                report = dry_run()
            with mock.patch.object(Path, "read_text", side_effect=AssertionError("Python read the candidate")):
                actual = compact.read_records(self.inbox)
                self.assertEqual(dry_run(), report)
            self.assertEqual(actual, expected)
            self.assertEqual(list(actual[0]), ["한글", "12"])
            self.assertEqual([path.name for path in actual[1]], ["broken.json", "empty-id.json", "list.json"])
            self.assertEqual({path.name: path.read_bytes() for path in self.inbox.iterdir()}, before)

            link = self.inbox / "z-link.json"
            link.symlink_to(self.inbox / "a-legacy.json")
            self.assertIsNone(compact.NativeProbe.request("--completion-probe", "lesson-compaction-inbox", {
                "inbox": str(self.inbox), "digit_limit": 0,
            }))
            self.assertEqual(compact.read_records(self.inbox)[0]["한글"][-1][0], link)

    def test_native_dry_run_keeps_report_caps_and_tie_order(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        self.state = self.state.resolve()
        self.inbox = compact.inbox_path(self.state)
        home = self.state / "home"
        home.mkdir()
        install(home, ROOT)
        for index in reversed(range(7)):
            lesson = f"lesson-{index}"
            for part in range(3 if index == 6 else 2):
                self._write(f"{part}-{lesson}.json", _candidate(lesson, "2026-01-01T00:00:00Z"))
            (self.inbox / f"broken-{index}.json").write_text("{broken", encoding="utf-8")

        def run(*args):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(compact.main(["--state-home", str(self.state), *args]), 0)
            return out.getvalue()

        with mock.patch.dict(os.environ, environment(self.state, ROOT), clear=True):
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = run()
            with mock.patch.object(compact, "plan", side_effect=AssertionError("Python assembled dry-run plan")):
                self.assertEqual(run(), expected)
            lines = expected.splitlines()
            self.assertEqual(lines[5:10], [f"    broken-{index}.json" for index in range(5)])
            self.assertEqual([line.split(":")[0].strip() for line in lines[10:15]],
                             ["lesson-6", "lesson-0", "lesson-1", "lesson-2", "lesson-3"])
            with (
                mock.patch.object(compact.NativeProbe, "request", wraps=compact.NativeProbe.request) as request,
                mock.patch.object(compact, "apply_plan", return_value=0),
                mock.patch.object(compact, "mark_stale", return_value=0),
            ):
                self.assertIn("folded 0 lessons", run("--apply"))
                self.assertNotIn("lesson-compaction-preview", [call.args[1] for call in request.call_args_list])

    def test_native_apply_report_matches_python_and_keeps_guarded_writes(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        self.state = self.state.resolve()
        self.inbox = compact.inbox_path(self.state)
        home = self.state / "home"
        home.mkdir()
        install(home, ROOT)
        reference = self.state / "reference"
        for root in (self.state, reference):
            inbox = compact.inbox_path(root)
            inbox.mkdir(parents=True, exist_ok=True)
            for index in (1, 2):
                record = _candidate("lesson", f"2026-01-0{index}T00:00:00Z", occurrence_count=index)
                (inbox / f"{index}-lesson.json").write_text(json.dumps(record), encoding="utf-8")
            (inbox / "broken.json").write_text("{broken", encoding="utf-8")
            with state_lock(inbox / "lesson.json"):
                pass

        def run(root):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(compact.main(["--state-home", str(root), "--apply"]), 0)
            return out.getvalue().splitlines()[1:]

        with mock.patch.dict(os.environ, environment(self.state, ROOT), clear=True):
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = run(reference)
            with mock.patch.object(compact, "plan", side_effect=AssertionError("Python assembled apply report")):
                self.assertEqual(run(self.state), expected)
            request = compact.NativeProbe.request

            def malformed(protocol, operation, payload):
                if operation == "lesson-compaction-apply-report":
                    return {"output": "unexpected\n", "folds": [["lesson", ["../outside.json"]]],
                            "stale": [], "removed": 0}
                return request(protocol, operation, payload)

            with (
                mock.patch.object(compact.NativeProbe, "request", side_effect=malformed),
                mock.patch.object(compact, "plan", wraps=compact.plan) as fallback,
            ):
                self.assertEqual(run(self.state)[-2:], ["folded 0 lessons; 0 files removed", "marked 0 lessons stale"])
                fallback.assert_called_once()
        self.assertEqual(expected[-2:], ["folded 1 lessons; 1 files removed", "marked 1 lessons stale"])
        self.assertEqual(self._files(), {"lesson.json", "broken.json"})
        self.assertEqual((self.inbox / "lesson.json").read_bytes(),
                         (compact.inbox_path(reference) / "lesson.json").read_bytes())

    def test_native_plan_preserves_keys_calendar_and_strict_staleness(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        self.state = self.state.resolve()
        self.inbox = compact.inbox_path(self.state)
        home = self.state / "home"
        home.mkdir()
        install(home, ROOT)
        created = "2026-03-01T00:00:00Z"
        now = datetime(2026, 3, 15, tzinfo=timezone.utc)
        keys = [f"key-{index}" for index in range(22)]
        self._write("a-legacy.json", _candidate(
            "boundary", created, occurrence_count=-2, occurrence_keys=keys,
            recent_occurrences={"2026-03-01": 7, "2026-03-02": 2, "2026-03-15": 1},
            marker="first",
        ))
        self._write("b-legacy.json", _candidate(
            "boundary", created, occurrence_count=True, occurrence_keys=[keys[0], "fresh"],
            recent_occurrences={"2026-03-02": 3, "2026-03-15": True},
            marker="last",
        ))
        self._write("stale.json", _candidate("stale", "2026-02-28T23:59:59.999999Z"))
        self._write("already.json", _candidate("already", "2026-02-01T00:00:00Z", status="stale"))
        with mock.patch.dict(os.environ, environment(self.state, ROOT), clear=True):
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = compact.plan(self.inbox, now)
            with (
                mock.patch.object(compact, "merge_group", side_effect=AssertionError("Python merged the plan")),
                mock.patch.object(compact, "is_stale", side_effect=AssertionError("Python classified the plan")),
            ):
                self.assertEqual(compact.plan(self.inbox, now), expected)
            self.assertEqual(expected["stale"], ["stale"])
            merged = expected["folds"][0]["merged"]
            self.assertEqual(merged["marker"], "last")
            self.assertEqual(merged["occurrence_count"], 1)
            self.assertEqual(merged["occurrence_keys"], keys[3:] + ["fresh"])
            self.assertEqual(merged["recent_occurrences"], {"2026-03-02": 5, "2026-03-15": 1})

            self._write("a-legacy.json", _candidate("boundary", created, occurrence_count=10 ** 40))
            with mock.patch.object(compact, "merge_group", wraps=compact.merge_group) as fallback:
                self.assertEqual(compact.plan(self.inbox, now)["folds"][0]["merged"]["occurrence_count"], 10 ** 40)
                self.assertTrue(fallback.called)

    def test_the_merged_count_is_the_sum_the_store_reads(self) -> None:
        for day in ("01", "02", "03"):
            self._write(
                f"20260101-0{day}-abc.json", _candidate("abc", f"2026-01-{day}T00:00:00Z")
            )

        merged = compact.merge_group(
            [json.loads(path.read_text(encoding="utf-8")) for path in sorted(self.inbox.glob("*.json"))]
        )

        self.assertEqual(3, merged["occurrence_count"])
        self.assertEqual("2026-01-01T00:00:00Z", merged["first_seen_at"])
        self.assertEqual("2026-01-03T00:00:00Z", merged["last_seen_at"])
        self.assertEqual(3, len(merged["occurrence_keys"]))

    def test_the_next_upsert_counts_what_it_would_have_counted(self) -> None:
        """The fold has to be invisible to the store, not merely tidy."""

        for day in ("01", "02", "03"):
            self._write(
                f"20260101-0{day}-abc.json", _candidate("abc", f"2026-01-{day}T00:00:00Z")
            )
        before = upsert_retrospective_candidate(
            self.state,
            _candidate("abc", "2026-02-01T00:00:00Z"),
            occurrence_id="fresh-one",
        )["occurrence_count"]

        self.setUp()
        for day in ("01", "02", "03"):
            self._write(
                f"20260101-0{day}-abc.json", _candidate("abc", f"2026-01-{day}T00:00:00Z")
            )
        compact.apply_plan(self.inbox, compact.plan(self.inbox)["folds"])
        after = upsert_retrospective_candidate(
            self.state,
            _candidate("abc", "2026-02-01T00:00:00Z"),
            occurrence_id="fresh-one",
        )["occurrence_count"]

        self.assertEqual(before, after)

    def test_folding_leaves_one_canonical_file(self) -> None:
        for day in ("01", "02"):
            self._write(f"2026010{day}-abc.json", _candidate("abc", f"2026-01-0{day}T00:00:00Z"))
        self._write("20260101-def.json", _candidate("def", "2026-01-01T00:00:00Z"))

        compact.apply_plan(self.inbox, compact.plan(self.inbox)["folds"])

        self.assertEqual({"abc.json", "def.json"}, self._files())

    def test_a_write_landing_after_the_plan_is_not_deleted_unread(self) -> None:
        """The plan reads; the apply deletes. A write in between was lost.

        `plan` computed the merge from what it read, and `apply_plan` unlinked
        every path that read had named. A candidate written in between -- the
        writer holds this lesson's lock, the compactor held none -- was deleted
        without ever being merged, and its occurrences went with it.
        """

        for day in ("01", "02"):
            self._write(
                f"2026-01-{day}T00-00-00-lesson.json",
                _candidate("lesson", f"2026-01-{day}T00:00:00+00:00"),
            )
        folds = compact.plan(self.inbox)["folds"]

        # The window: a real writer creates this between the two calls.
        self._write(
            "2026-01-09T00-00-00-lesson.json",
            _candidate("lesson", "2026-01-09T00:00:00+00:00"),
        )

        with mock.patch.object(compact, "_native_merges", return_value=None) as native:
            compact.apply_plan(self.inbox, folds)
            self.assertEqual(len(native.call_args.args[0][0]), 3)

        merged = json.loads((self.inbox / "lesson.json").read_text(encoding="utf-8"))
        self.assertEqual(3, merged["occurrence_count"])
        self.assertIn("key-2026-01-09T00:00:00+00:00", merged["occurrence_keys"])
        self.assertEqual("2026-01-09T00:00:00+00:00", merged["last_seen_at"])

    def test_native_apply_merges_records_arriving_under_the_writer_lock(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        self.state = self.state.resolve()
        self.inbox = compact.inbox_path(self.state)
        home = self.state / "home"
        home.mkdir()
        install(home, ROOT)
        for day in ("01", "02"):
            self._write(
                f"2026-01-{day}T00-00-00-lesson.json",
                _candidate("lesson", f"2026-01-{day}T00:00:00Z"),
            )
        canonical = self.inbox / "lesson.json"
        entered = threading.Event()
        merging = threading.Event()
        request = compact.NativeProbe.request

        def apply(folds):
            entered.set()
            return compact.apply_plan(self.inbox, folds)

        def probe(protocol, operation, payload):
            if operation == "lesson-compaction-merge":
                self.assertIsNone(payload["now"])
                self.assertEqual(len(json.loads(payload["groups_json"])[0]), 3)
                merging.set()
            return request(protocol, operation, payload)

        with mock.patch.dict(os.environ, environment(self.state, ROOT), clear=True):
            folds = compact.plan(self.inbox)["folds"]
            with (
                ThreadPoolExecutor(max_workers=1) as worker,
                mock.patch.object(compact.NativeProbe, "request", side_effect=probe),
                mock.patch.object(compact, "merge_group", side_effect=AssertionError("Python merged the locked records")),
            ):
                with state_lock(canonical):
                    future = worker.submit(apply, folds)
                    self.assertTrue(entered.wait(5))
                    self.assertFalse(merging.wait(0.2))
                    self._write("2026-01-09T00-00-00-lesson.json", _candidate("lesson", "2026-01-09T00:00:00Z"))
                    self.assertFalse(canonical.exists())
                self.assertEqual(future.result(timeout=5), 1)
            self.assertTrue(merging.is_set())
            merged = json.loads(canonical.read_text(encoding="utf-8"))
            self.assertEqual(merged["occurrence_count"], 3)
            self.assertIn("key-2026-01-09T00:00:00Z", merged["occurrence_keys"])
            self.assertEqual(self._files(), {"lesson.json"})

    def test_native_apply_persists_exact_bytes_and_does_not_replay_unknown_write(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        self.state = self.state.resolve()
        self.inbox = compact.inbox_path(self.state)
        home = self.state / "home"
        home.mkdir()
        install(home, ROOT)
        canonical = self.inbox / "lesson.json"
        with state_lock(canonical):
            pass
        first = _candidate("lesson", "2026-01-01T00:00:00Z")
        second = _candidate("lesson", "2026-01-02T00:00:00Z", extra={"z": [True, "한글"], "a": -0.0})
        self._write("a-lesson.json", first)
        foreign = self._write("b-lesson.json", _candidate("other", "2026-01-02T00:00:00Z"))
        self._write("legacy.json", second)
        expected = json.dumps(compact.merge_group([first, second]), indent=1, sort_keys=True)
        invoke = subprocess.run

        def lose_reply(command, **kwargs):
            result = invoke(command, **kwargs)
            if command[-1] == "lesson-compaction-apply":
                self.assertEqual(result.returncode, 0, result.stderr)
                return subprocess.CompletedProcess(result.args, 0, stdout=b"", stderr=b"")
            return result

        with mock.patch.dict(os.environ, environment(self.state, ROOT), clear=True):
            folds = compact.plan(self.inbox)["folds"]
            fold = next(fold for fold in folds if fold["lesson_id"] == "lesson")
            with (
                mock.patch.object(subprocess, "run", side_effect=lose_reply),
                mock.patch.object(compact, "state_lock", side_effect=AssertionError("Python replayed the write")),
            ):
                with self.assertRaisesRegex(OSError, "lesson compaction outcome could not be determined"):
                    compact.apply_plan(self.inbox, [fold])
            self.assertEqual(canonical.read_text(encoding="utf-8"), expected)
            self.assertTrue(foreign.is_file())
            self.assertEqual(self._files(), {"lesson.json", "b-lesson.json"})
            self.assertTrue((self.inbox / ".lesson.json.lock").is_file())

    def test_native_write_batch_counts_noops_and_resumes_only_untouched_suffix(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        self.state = self.state.resolve()
        self.inbox = compact.inbox_path(self.state)
        home = self.state / "home"
        home.mkdir()
        install(home, ROOT)
        date = "2026-01-01T00:00:00Z"
        for lesson in ("a", "b", "c", "d"):
            self._write(f"first-{lesson}.json", _candidate(lesson, date))
        (self.inbox / "c.compact.tmp").write_text("legacy scratch", encoding="utf-8")
        request = compact.NativeProbe.request
        batches = []
        singles = []

        def probe(protocol, operation, payload):
            result = request(protocol, operation, payload)
            if operation == "lesson-compaction-write-batch":
                batches.append(result)
            if operation == "lesson-compaction-apply":
                singles.append(payload["lesson_id"])
            return result

        with mock.patch.dict(os.environ, environment(self.state, ROOT), clear=True):
            folds = compact.plan(self.inbox)["folds"]
            (self.inbox / "first-b.json").unlink()
            with mock.patch.object(compact.NativeProbe, "request", side_effect=probe):
                self.assertEqual(compact.apply_plan(self.inbox, folds), 3)
            self.assertEqual(batches, [{"processed": 2, "changed": 1}])
            self.assertEqual(singles, ["c", "d"])
            self.assertEqual(self._files(), {"a.json", "c.json", "d.json"})

            for lesson in ("a", "d"):
                self._write(f"again-{lesson}.json", _candidate(lesson, date))
            folds = compact.plan(self.inbox)["folds"]
            invoke = subprocess.run

            def lose_reply(command, **kwargs):
                result = invoke(command, **kwargs)
                if command[-1] == "lesson-compaction-write-batch":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    return subprocess.CompletedProcess(result.args, 0, stdout=b"", stderr=b"")
                self.assertNotEqual(command[-1], "lesson-compaction-apply")
                return result

            with mock.patch.object(subprocess, "run", side_effect=lose_reply):
                with self.assertRaisesRegex(OSError, "lesson compaction batch outcome could not be determined"):
                    compact.apply_plan(self.inbox, folds)
            self.assertEqual(self._files(), {"a.json", "c.json", "d.json"})
            self.assertEqual(json.loads((self.inbox / "a.json").read_text())["occurrence_count"], 2)

    def test_native_stale_mark_rechecks_snapshot_and_never_replays_write(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        self.state = self.state.resolve()
        self.inbox = compact.inbox_path(self.state)
        home = self.state / "home"
        home.mkdir()
        install(home, ROOT)
        now = datetime(2026, 3, 15, tzinfo=timezone.utc)
        old = "2026-02-28T23:59:59.999999Z"
        stale = _candidate("old", old, occurrence_count=7, extra={"z": "한글", "a": -0.0})
        old_path = self._write("old.json", stale)
        refreshed = self._write("refreshed.json", _candidate("refreshed", old))
        missing = self._write("missing.json", _candidate("missing", old))
        for path in (old_path, refreshed, missing):
            with state_lock(path):
                pass
        with mock.patch.dict(os.environ, environment(self.state, ROOT), clear=True):
            stale_ids = compact.plan(self.inbox, now)["stale"]
            self.assertEqual(stale_ids, ["missing", "old", "refreshed"])
            with state_lock(refreshed):
                self.assertIsNone(compact.NativeProbe.request("--completion-probe", "lesson-compaction-mark-stale", {
                    "inbox": str(self.inbox), "lesson_id": "refreshed", "now": now.isoformat(),
                    "stale_days": 14, "digit_limit": 0,
                }))
                self._write("refreshed.json", _candidate("refreshed", "2026-03-01T00:00:00Z"))
            missing.unlink()
            before = refreshed.read_bytes()
            expected = json.dumps({**stale, "status": "stale"}, indent=1, sort_keys=True)
            with mock.patch.object(compact, "state_lock", side_effect=AssertionError("Python acquired the lock")):
                self.assertEqual(compact.mark_stale(self.inbox, stale_ids, now), 1)
                self.assertEqual(compact.mark_stale(self.inbox, stale_ids, now), 0)
            self.assertEqual(old_path.read_text(encoding="utf-8"), expected)
            self.assertEqual(refreshed.read_bytes(), before)
            self.assertFalse(missing.exists())

            self._write("old.json", stale)
            invoke = subprocess.run

            def lose_reply(command, **kwargs):
                result = invoke(command, **kwargs)
                if command[-1] == "lesson-compaction-mark-stale":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    return subprocess.CompletedProcess(result.args, 0, stdout=b"", stderr=b"")
                return result

            with (
                mock.patch.object(subprocess, "run", side_effect=lose_reply),
                mock.patch.object(compact, "state_lock", side_effect=AssertionError("Python replayed the write")),
            ):
                with self.assertRaisesRegex(OSError, "lesson stale marking outcome could not be determined"):
                    compact.mark_stale(self.inbox, ["old"], now)
            self.assertEqual(old_path.read_text(encoding="utf-8"), expected)

    def test_a_legacy_name_the_store_cannot_find_is_still_merged(self) -> None:
        """The two readers disagree by design, so the apply reads both.

        The store finds a lesson by filename, which is what the writer creates.
        This script groups by the `lesson_id` inside the record, which is how it
        finds legacy files named by no convention. Reading under the lock
        through the store's reader alone would orphan those: not merged, so
        their occurrences are missing from the canonical record, and not
        removed, so every later report keeps offering the same fold. The
        reference store holds one such record today.
        """

        self._write("legacy-name.json", _candidate("lesson", "2026-01-01T00:00:00+00:00"))
        self._write(
            "2026-01-02T00-00-00-lesson.json",
            _candidate("lesson", "2026-01-02T00:00:00+00:00"),
        )

        compact.apply_plan(self.inbox, compact.plan(self.inbox)["folds"])

        merged = json.loads((self.inbox / "lesson.json").read_text(encoding="utf-8"))
        self.assertEqual(2, merged["occurrence_count"])
        self.assertIn("key-2026-01-01T00:00:00+00:00", merged["occurrence_keys"])
        self.assertEqual({"lesson.json"}, self._files())

    def test_the_apply_waits_on_the_lock_the_writer_holds(self) -> None:
        """The apply must take the writer's lock, not merely take a lock.

        Written first as a test that held `state_lock` itself and watched an
        upsert wait. That proved the writer and `state_lock` agree on the path
        and said nothing about `apply_plan`: pointing the apply at a private
        lock file left it green. So the writer's lock is held here and the
        apply is the one that has to wait.
        """

        for day in ("01", "02"):
            self._write(
                f"2026-01-{day}T00-00-00-lesson.json",
                _candidate("lesson", f"2026-01-{day}T00:00:00+00:00"),
            )
        folds = compact.plan(self.inbox)["folds"]
        entered = threading.Event()
        finished = threading.Event()

        def apply() -> None:
            entered.set()
            compact.apply_plan(self.inbox, folds)
            finished.set()

        # The writer's own transaction boundary for this lesson.
        with state_lock(self.inbox / "lesson.json"):
            worker = threading.Thread(target=apply)
            worker.start()
            self.assertTrue(entered.wait(5))
            self.assertFalse(finished.wait(0.5), "the apply did not wait for the lock")
        worker.join(10)
        self.assertTrue(finished.is_set())

    def test_a_lesson_already_canonical_and_alone_is_left_alone(self) -> None:
        self._write("abc.json", _candidate("abc", "2026-01-01T00:00:00Z"))

        self.assertEqual([], compact.plan(self.inbox)["folds"])

    def test_a_report_writes_nothing(self) -> None:
        for day in ("01", "02"):
            self._write(f"2026010{day}-abc.json", _candidate("abc", f"2026-01-0{day}T00:00:00Z"))
        before = self._files()

        compact.plan(self.inbox)

        self.assertEqual(before, self._files())

    def test_an_unreadable_record_is_reported_and_untouched(self) -> None:
        (self.inbox / "broken.json").write_text("{not json", encoding="utf-8")
        self._write("20260101-abc.json", _candidate("abc", "2026-01-01T00:00:00Z"))

        report = compact.plan(self.inbox)
        compact.apply_plan(self.inbox, report["folds"])

        self.assertEqual([self.inbox / "broken.json"], report["unreadable"])
        self.assertIn("broken.json", self._files())

    def test_a_record_without_a_lesson_id_is_never_merged_into_another(self) -> None:
        self._write("nameless.json", _candidate("", "2026-01-01T00:00:00Z"))
        self._write("20260101-abc.json", _candidate("abc", "2026-01-01T00:00:00Z"))

        report = compact.plan(self.inbox)
        compact.apply_plan(self.inbox, report["folds"])

        self.assertIn("nameless.json", self._files())
        self.assertIn("abc.json", self._files())


    def test_the_command_without_apply_changes_nothing(self) -> None:
        """The dry run is the safety property, so it is tested through main."""

        import io
        from contextlib import redirect_stdout

        for day in ("01", "02"):
            self._write(f"2026010{day}-abc.json", _candidate("abc", f"2026-01-0{day}T00:00:00Z"))
        before = {path.name: path.read_text(encoding="utf-8") for path in self.inbox.glob("*.json")}

        output = io.StringIO()
        with redirect_stdout(output):
            code = compact.main_with_arguments(["--state-home", str(self.state)])

        after = {path.name: path.read_text(encoding="utf-8") for path in self.inbox.glob("*.json")}
        self.assertEqual(0, code)
        self.assertEqual(before, after)
        self.assertIn("nothing written", output.getvalue())

    def test_the_command_with_apply_folds(self) -> None:
        import io
        from contextlib import redirect_stdout

        for day in ("01", "02"):
            self._write(f"2026010{day}-abc.json", _candidate("abc", f"2026-01-0{day}T00:00:00Z"))

        with redirect_stdout(io.StringIO()):
            compact.main_with_arguments(["--state-home", str(self.state), "--apply"])

        self.assertEqual({"abc.json"}, self._files())

    def test_the_apply_never_deletes_lock_files(self) -> None:
        """Unlinking a lock lets an old-inode holder and a new-file holder both hold it."""

        import io
        import os
        from contextlib import redirect_stdout

        self._write("20260101-abc.json", _candidate("abc", "2026-01-01T00:00:00Z"))
        old_lock = self.inbox / "old.json.lock"
        old_lock.write_text("", encoding="utf-8")
        os.utime(old_lock, (0, 0))
        with state_lock(self.inbox / "abc.json"):
            pass
        locks_before = {path.name for path in self.inbox.glob("*.lock")}

        output = io.StringIO()
        with redirect_stdout(output):
            compact.main_with_arguments(["--state-home", str(self.state), "--apply"])

        self.assertEqual(locks_before, {path.name for path in self.inbox.glob("*.lock")})
        self.assertNotIn("lock files", output.getvalue())

    def test_a_record_that_is_not_an_object_is_left_alone(self) -> None:
        """Valid JSON is not the same as a lesson."""

        (self.inbox / "list.json").write_text("[]", encoding="utf-8")
        self._write("20260101-abc.json", _candidate("abc", "2026-01-01T00:00:00Z"))

        report = compact.plan(self.inbox)
        compact.apply_plan(self.inbox, report["folds"])

        self.assertIn(self.inbox / "list.json", report["unreadable"])
        self.assertIn("list.json", self._files())

    def test_nothing_outside_the_inbox_is_read_or_written(self) -> None:
        promoted = self.state / "lessons" / "promoted"
        promoted.mkdir(parents=True)
        (promoted / "abc.json").write_text(
            json.dumps(_candidate("abc", "2026-01-01T00:00:00Z")), encoding="utf-8"
        )
        self._write("20260101-abc.json", _candidate("abc", "2026-01-02T00:00:00Z"))

        compact.apply_plan(self.inbox, compact.plan(self.inbox)["folds"])

        self.assertEqual({"abc.json"}, {path.name for path in promoted.glob("*.json")})
        self.assertEqual(
            1,
            json.loads((promoted / "abc.json").read_text(encoding="utf-8"))["occurrence_count"],
        )


if __name__ == "__main__":
    unittest.main()
