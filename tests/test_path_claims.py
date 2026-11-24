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
from concurrent.futures import ThreadPoolExecutor
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

    def test_native_claim_arguments_sort_deduplicate_and_resolve_missing_paths(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        scope = self.project / "scope"
        (scope / "nested" / "child").mkdir(parents=True)
        (scope / "alias").symlink_to("nested/child")
        (scope / "escape").symlink_to(self.project / "absent")
        (scope / "loop").symlink_to("loop")
        raw = ["z", "alias/../한글.ts", "nested/한글.ts", "absent/../a", "absent/../alias/../한글.ts"]
        expected = sorted({path_claims.normalize(scope, path) for path in raw})
        self.assertEqual(expected, ["a", "nested/한글.ts", "z"])
        args = ("--project", str(scope), "--holder", "editor")
        options = [option for path in raw for option in ("--path", path)]
        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            self.assertIsNone(path_claims.NativeProbe.request("--completion-probe", "path-claim-arguments", {
                "project": str(scope), "paths": ["loop"],
            }))
            with mock.patch.object(path_claims, "normalize", side_effect=AssertionError("Python normalized a claim")):
                self.assertEqual(self.run_cli("claim", *args, *options),
                                 (0, "".join(f"claimed by editor: {path}\n" for path in expected)))
                directory = path_claims.claims_dir(scope)
                before = sorted(entry.name for entry in directory.iterdir())
                self.assertEqual(self.run_cli("release", *args, "--path", "z", "--path", "escape"), (1, ""))
                self.assertEqual(sorted(entry.name for entry in directory.iterdir()), before)
                self.assertEqual(self.run_cli("release", *args, *options), (0, ""))
                self.assertEqual(list(directory.iterdir()), [])

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

    def test_native_release_preserves_foreign_and_replaced_claims(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            self.assertEqual(self.claim("a", "mine", "replace", "uncertain")[0], 0)
            self.assertEqual(self.claim("b", "foreign")[0], 0)
            args = ("release", "--project", str(self.project), "--holder", "a")
            with mock.patch.object(Path, "unlink", side_effect=AssertionError("Python removed claim")):
                code, output = self.run_cli(*args, "--path", "mine", "--path", "foreign")
            self.assertEqual(code, path_claims.CONFLICT_EXIT)
            self.assertIn("held by b", output)
            self.assertEqual([claim["path"] for claim in self.status()], ["foreign", "replace", "uncertain"])

            target = path_claims._claim_file(self.project, "replace")
            request = path_claims.NativeProbe.request
            self.assertIsNone(request("--completion-probe", "path-claim-release", {
                "project": str(self.project), "holder": "a", "digit_limit": 0,
                "names": [target.name, "../outside.json"],
            }))
            self.assertTrue(target.is_file())

            def replace_before_release(protocol, operation, payload):
                if operation == "path-claim-release":
                    claim = json.loads(target.read_text())
                    claim["holder"] = "new owner"
                    replacement = target.with_suffix(".tmp")
                    replacement.write_text(json.dumps(claim), encoding="utf-8")
                    replacement.replace(target)
                return request(protocol, operation, payload)

            with mock.patch.object(path_claims.NativeProbe, "request", side_effect=replace_before_release):
                self.assertEqual(self.run_cli(*args, "--path", "replace"), (0, ""))
            self.assertEqual(json.loads(target.read_text())["holder"], "new owner")

            invoke = subprocess.run

            def lose_release_reply(command, **kwargs):
                result = invoke(command, **kwargs)
                if command[-1] == "path-claim-release":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    return subprocess.CompletedProcess(result.args, 0, stdout=b"", stderr=b"")
                return result

            with mock.patch.object(subprocess, "run", side_effect=lose_release_reply) as process, (
                mock.patch.object(Path, "unlink", side_effect=AssertionError("Python replayed release"))
            ):
                with self.assertRaisesRegex(OSError, "release outcome could not be determined"):
                    self.run_cli(*args, "--all")
                self.assertEqual(sum(call.args[0][-1] == "path-claim-release" for call in process.call_args_list), 1)
            self.assertEqual([claim["path"] for claim in self.status()], ["foreign", "replace"])

    def test_native_release_selection_matches_reference_and_rechecks_expiry(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        oracle = self.project / "oracle"
        oracle.mkdir()
        for project in (self.project, oracle):
            directory = path_claims.claims_dir(project)
            directory.mkdir(parents=True)
            for name, path, holder, ttl in (("00.json", "z", "한글", 1), ("01.json", "a", "other", 5)):
                (directory / name).write_text(json.dumps({
                    "path": path, "holder": holder, "expires": path_claims._iso(self.clock + ttl),
                }), encoding="utf-8")
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                self.assertTrue(path_claims._write_claim(project, "own", "me", 5))
        args = ("--holder", "me", "--path", "a", "--path", "own", "--path", "z")
        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = self.run_cli("release", "--project", str(oracle), *args)
            with mock.patch.object(path_claims, "_active_claims", side_effect=AssertionError("Python selected release")):
                self.assertEqual(self.run_cli("release", "--project", str(self.project), *args), expected)
                self.assertEqual(path_claims.release(self.project, None, "me"), [])
            self.assertEqual(expected[0], path_claims.CONFLICT_EXIT)
            self.assertEqual(expected[1].splitlines(), ["held by 한글 since None: z", "held by other since None: a"])

            request = path_claims.NativeProbe.request

            def expire_after_scan(*call):
                result = request(*call)
                if call[1] == "path-claim-scan":
                    self.assertIsNotNone(result["release"])
                    self.clock += 1
                return result

            with mock.patch.object(path_claims.NativeProbe, "request", side_effect=expire_after_scan):
                self.assertEqual(self.run_cli("release", "--project", str(self.project), *args),
                                 (path_claims.CONFLICT_EXIT, "held by other since None: a\n"))
            self.assertFalse((path_claims.claims_dir(self.project) / "00.json").exists())

    def test_expired_claim_is_cleaned_and_freed(self) -> None:
        self.claim("a", "src/x.tsx", extra=("--ttl", "60"))
        self.clock += 61
        self.assertEqual(self.status(), [])
        self.assertEqual(list(path_claims.claims_dir(self.project).glob("*.json")), [])
        code, _ = self.claim("b", "src/x.tsx")
        self.assertEqual(code, 0)

    def test_native_claim_scan_preserves_values_and_rechecks_cleanup_candidates(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        oracle = self.project / "oracle"
        expiry = path_claims._iso(self.clock)
        later = path_claims._iso(self.clock + 60)
        rows = {
            "a.json": json.dumps({"path": "z", "holder": "한글", "expires": later, "extra": 10 ** 40}),
            "b.json": json.dumps({"path": "a", "holder": "h", "expires": later}),
            "c.json": json.dumps({"path": "expired", "holder": "h", "expires": expiry}),
            "d.json": "{broken",
        }
        for project in (self.project, oracle):
            directory = path_claims.claims_dir(project)
            directory.mkdir(parents=True)
            for name, raw in rows.items():
                (directory / name).write_text(raw, encoding="utf-8")
        directory = path_claims.claims_dir(self.project)
        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = path_claims.active_claims(oracle)
            with mock.patch.object(path_claims, "_read_active", wraps=path_claims._read_active) as reread:
                self.assertEqual(expected, path_claims.active_claims(self.project))
                reread.assert_not_called()
            self.assertEqual(sorted(p.name for p in directory.iterdir()), ["a.json", "b.json"])
            self.assertEqual([row["path"] for row in self.status()], ["a", "z"])

            candidate = directory / "c.json"
            candidate.write_text(rows[candidate.name], encoding="utf-8")
            vanished = directory / "d.json"
            vanished.write_text(rows[vanished.name], encoding="utf-8")
            request = path_claims.NativeProbe.request

            def renew_after_scan(*args):
                result = request(*args)
                self.assertIsNotNone(result)
                if args[1] == "path-claim-scan":
                    replacement = candidate.with_suffix(".tmp")
                    replacement.write_text(json.dumps({"path": "renewed", "expires": later}), encoding="utf-8")
                    replacement.replace(candidate)
                    vanished.unlink()
                return result

            with mock.patch.object(path_claims.NativeProbe, "request", side_effect=renew_after_scan):
                self.assertEqual([row["path"] for row in path_claims.active_claims(self.project)], ["z", "a", "renewed"])
            self.assertTrue(candidate.exists())

            for exceptional in (
                {"path": "legacy", "expires": "2030-01-01T01:00:00"},
                {"path": "legacy", "expires": later, "extra": "x" * (64 * 1024)},
            ):
                candidate.write_text(json.dumps(exceptional), encoding="utf-8")
                with mock.patch.object(path_claims, "_read_active", wraps=path_claims._read_active) as reread:
                    self.assertEqual(path_claims.active_claims(self.project), expected + [exceptional])
                    self.assertEqual(reread.call_count, 3)

            candidate.write_text(rows["c.json"], encoding="utf-8")
            invoke = subprocess.run

            def lose_expiry_reply(command, **kwargs):
                result = invoke(command, **kwargs)
                if command[-1] == "path-claim-expire":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    return subprocess.CompletedProcess(result.args, 0, stdout=b"", stderr=b"")
                return result

            with mock.patch.object(subprocess, "run", side_effect=lose_expiry_reply), (
                mock.patch.object(path_claims, "_read_active", side_effect=AssertionError("Python replayed expiry"))
            ):
                with self.assertRaisesRegex(OSError, "expiry outcome could not be determined"):
                    path_claims.active_claims(self.project)
            self.assertFalse(candidate.exists())

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

    def test_native_claim_create_and_renew_match_python_and_do_not_replay(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        oracle = self.project / "oracle"
        oracle.mkdir()
        write = path_claims._write_claim
        path, holder = "src/한글.tsx", "세션"
        target = path_claims._claim_file(self.project, path)
        reference = path_claims._claim_file(oracle, path)
        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                self.assertTrue(write(oracle, path, holder, 60))
            with mock.patch.object(path_claims.os, "open", side_effect=AssertionError("Python opened claim")):
                self.assertTrue(write(self.project, path, holder, 60))
                self.assertFalse(write(self.project, path, "other", 60))
            self.assertEqual(reference.read_bytes(), target.read_bytes())
            self.assertEqual(reference.stat().st_mode, target.stat().st_mode)
            since = json.loads(target.read_text())["since"]

            self.clock += 30
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                self.assertTrue(write(self.project, path, holder, 90))
            with mock.patch.object(path_claims.os, "replace", side_effect=AssertionError("Python renewed claim")):
                self.assertTrue(write(oracle, path, holder, 90))
            self.assertEqual(reference.read_bytes(), target.read_bytes())
            self.assertEqual(reference.stat().st_mode, target.stat().st_mode)
            self.assertEqual(json.loads(target.read_text())["since"], since)

            with ThreadPoolExecutor(max_workers=2) as workers:
                winners = list(workers.map(lambda h: write(self.project, "race", h, 60), ["first", "second"]))
            self.assertEqual(winners.count(True), 1)
            self.assertEqual(json.loads(path_claims._claim_file(self.project, "race").read_text())["holder"],
                             ["first", "second"][winners.index(True)])

            invoke = subprocess.run

            def lose_reply(*command, **kwargs):
                result = invoke(*command, **kwargs)
                self.assertEqual(result.returncode, 0, result.stderr)
                return subprocess.CompletedProcess(result.args, 0, stdout=b"", stderr=b"")

            with mock.patch.object(subprocess, "run", side_effect=lose_reply) as process:
                with self.assertRaisesRegex(OSError, "outcome could not be determined"):
                    write(self.project, "uncertain", holder, 60)
                process.assert_called_once()
            self.assertEqual(json.loads(path_claims._claim_file(self.project, "uncertain").read_text())["holder"], holder)

            paths = [".", "é", "e\u0301", "nested/" + "한글" * 75]
            targets = [path_claims._claim_file(self.project, path) for path in paths]
            self.assertEqual(len(set(targets)), len(paths))
            with mock.patch.object(path_claims, "_claim_file", side_effect=AssertionError("Python hashed a path")):
                for item in paths:
                    self.assertTrue(write(self.project, item, holder, 60))
                self.assertEqual([json.loads(target.read_text())["path"] for target in targets], paths)
                self.assertEqual(path_claims.release(self.project, paths, holder), [])
            self.assertTrue(all(not target.exists() for target in targets))

    def test_native_claim_ttl_matches_python_at_timestamp_boundaries(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        vectors = [
            (-62135596800.0, 1), (-1.0000006, 1), (-0.9999995, 0),
            (-0.0000005, 0), (0.9999995, -1), (172800.99999949, 0),
            (1800000000.0000005, -60), (253402300799.0, -1),
        ]
        with mock.patch.dict(os.environ, {**environment(self.project, ROOT), "TZ": "Asia/Seoul"}, clear=True):
            for index, (self.clock, ttl) in enumerate(vectors):
                with self.subTest(now=self.clock, ttl=ttl):
                    path = f"clock/{index}"
                    expected = {
                        "path": path, "holder": "clock",
                        "since": path_claims._iso(self.clock), "expires": path_claims._iso(self.clock + ttl),
                    }
                    with mock.patch.object(path_claims, "_iso", side_effect=AssertionError("Python formatted time")):
                        self.assertTrue(path_claims._write_claim(self.project, path, "clock", ttl))
                    self.assertEqual(path_claims._claim_file(self.project, path).read_text(), json.dumps(expected))
            self.clock = 253402300799.0
            with self.assertRaises((OverflowError, OSError, ValueError)):
                path_claims._write_claim(self.project, "invalid", "clock", 1)
            self.assertFalse(path_claims._claim_file(self.project, "invalid").exists())

            old = {"path": "legacy", "holder": "clock", "since": "old-since", "expires": "old-expiry"}
            target = path_claims._claim_file(self.project, "legacy")
            receipt = path_claims.NativeProbe.request("--completion-probe", "path-claim-write", {
                "project": str(self.project), "name": target.name, "entry": old, "digit_limit": 0,
            })
            self.assertEqual(receipt, {"written": True})
            self.assertEqual(target.read_text(), json.dumps(old))

    def test_native_status_matches_python_and_refreshes_expiry_at_output(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        directory = path_claims.claims_dir(self.project)
        directory.mkdir(parents=True)
        expiry = path_claims._iso(self.clock + 1)
        for name, path, holder in (("a", "same", "첫째"), ("b", "same", "둘째"), ("c", "aaa", "third")):
            (directory / f"{name}.json").write_text(json.dumps({
                "path": path, "holder": holder, "expires": expiry, "large": 10 ** 40,
            }), encoding="utf-8")
        args = ("status", "--project", str(self.project))
        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = [self.run_cli(*args), self.run_cli(*args, "--json")]
            with mock.patch.object(path_claims, "_active_claims", side_effect=AssertionError("Python rendered status")):
                self.assertEqual(expected, [self.run_cli(*args), self.run_cli(*args, "--json")])
            self.assertEqual([entry["holder"] for entry in json.loads(expected[1][1])], ["third", "첫째", "둘째"])

            request = path_claims.NativeProbe.request

            def expire_after_scan(*args):
                result = request(*args)
                if args[1] == "path-claim-scan":
                    self.assertIsNotNone(result["status"])
                    self.clock += 1
                return result

            with mock.patch.object(path_claims.NativeProbe, "request", side_effect=expire_after_scan) as scan:
                self.assertEqual((0, "[]\n"), self.run_cli(*args, "--json"))
                self.assertEqual([call.args[1] for call in scan.call_args_list],
                                 ["path-claim-scan"] + ["path-claim-expire"] * 3)
            self.assertEqual(list(directory.iterdir()), [])
            with mock.patch.object(path_claims, "_active_claims", side_effect=AssertionError("Python rendered empty status")):
                self.assertEqual((0, "no active claims\n"), self.run_cli(*args))

    def test_native_conflict_selection_preserves_path_boundaries_and_expiry(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        directory = path_claims.claims_dir(self.project)
        directory.mkdir(parents=True)
        for name, path, holder in (
            ("a", "src/한글", "first"), ("b", "src", "owner"),
            ("c", "src-old", "second"), ("d", ".", "root"), ("e", None, "owner"),
        ):
            entry = {"holder": holder, "expires": path_claims._iso(self.clock + (1 if name == "e" else 2))}
            if path is not None:
                entry["path"] = path
            (directory / f"{name}.json").write_text(json.dumps(entry), encoding="utf-8")

        queries = [("src",), ("src/한글/file",), ("src-old",), (".",), ("srcsuffix",), ("src/",), ()]
        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = [path_claims.conflicts(self.project, iter(query), "owner") for query in queries]
            with mock.patch.object(path_claims, "overlaps", side_effect=AssertionError("Python compared paths")):
                self.assertEqual(expected, [path_claims.conflicts(self.project, iter(query), "owner") for query in queries])
            self.assertEqual([["first", "root"], ["first", "root"], ["second", "root"],
                              ["first", "second", "root"], ["root"], ["root"], []],
                             [[row["holder"] for row in result] for result in expected])
            self.assertEqual(path_claims.conflicts(self.project, [], "third"), [])
            with self.assertRaises(KeyError):
                path_claims.conflicts(self.project, ["src"], "third")

            request = path_claims.NativeProbe.request

            def expire_after_scan(*args):
                result = request(*args)
                if args[1] == "path-claim-scan":
                    self.assertIsNotNone(result["conflicts"])
                    self.clock += 1
                return result

            with mock.patch.object(path_claims.NativeProbe, "request", side_effect=expire_after_scan) as scan:
                self.assertEqual(path_claims.conflicts(self.project, ["src"], "owner"), expected[0])
                self.assertEqual([call.args[1] for call in scan.call_args_list],
                                 ["path-claim-scan", "path-claim-expire"])
            self.assertEqual(sorted(p.name for p in directory.iterdir()), ["a.json", "b.json", "c.json", "d.json"])

    def test_native_post_write_arbitration_rolls_back_only_owned_writes(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        paths = ["src", "lib"]
        holder = "middle"
        started = path_claims._iso(self.clock)
        expiry = path_claims._iso(self.clock + 60)
        earlier = {"path": "src/a", "holder": "older", "expires": expiry}
        tie = {"path": "lib/b", "holder": "alpha", "since": started, "expires": expiry}
        contenders = [
            earlier, tie, {"path": "lib/c", "holder": "zulu", "since": started, "expires": expiry},
            {"path": "src/d", "holder": "alpha", "since": path_claims._iso(self.clock + 1), "expires": expiry},
            {"path": "unrelated", "holder": "other", "expires": expiry},
        ]
        directory = path_claims.claims_dir(self.project)
        request = path_claims.NativeProbe.request

        def write_with_race(protocol, operation, payload):
            result = request(protocol, operation, payload)
            if operation == "path-claim-write-batch":
                self.assertEqual(result, {"written": len(paths), "blocked": False})
                for index, claim in enumerate(contenders):
                    (directory / f"race-{index}.json").write_text(json.dumps(claim), encoding="utf-8")
            return result

        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            with mock.patch.object(path_claims.NativeProbe, "request", side_effect=write_with_race), (
                mock.patch.object(path_claims, "overlaps", side_effect=AssertionError("Python arbitrated claims"))
            ):
                self.assertEqual(path_claims.try_claim(self.project, paths, holder, 60), [earlier, tie])
            self.assertEqual(sorted(entry.name for entry in directory.iterdir()),
                             [f"race-{index}.json" for index in range(len(contenders))])

            def old_launcher(protocol, operation, payload):
                if operation == "path-claim-scan":
                    payload = {**payload, "conflict": {**payload["conflict"], "started": None}}
                return request(protocol, operation, payload)

            with mock.patch.object(path_claims.NativeProbe, "request", side_effect=old_launcher):
                self.assertEqual(path_claims._find_conflicts(self.project, paths, holder, started=started), [earlier, tie])

    def test_native_batch_resumes_partial_prefix_and_does_not_replay_lost_reply(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        directory = path_claims.claims_dir(self.project)
        directory.mkdir(parents=True)
        paths = ["one", "broken", "untouched"]
        broken = path_claims._claim_file(self.project, "broken")
        broken.write_text("{broken", encoding="utf-8")
        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            with mock.patch.object(path_claims, "_write_claim", wraps=path_claims._write_claim) as write:
                self.assertEqual(path_claims._write_claims(self.project, paths, "editor", 60), (["one"], "broken"))
                write.assert_called_once_with(self.project, "broken", "editor", 60)
            self.assertTrue(path_claims._claim_file(self.project, "one").exists())
            self.assertFalse(path_claims._claim_file(self.project, "untouched").exists())
            self.assertEqual(broken.read_text(), "{broken")

            self.assertTrue(path_claims._write_claim(self.project, "foreign", "other", 60))
            with mock.patch.object(path_claims, "_write_claim", side_effect=AssertionError("Python retried contention")):
                self.assertEqual(path_claims._write_claims(
                    self.project, ["four", "foreign", "untouched"], "editor", 60
                ), (["four"], "foreign"))
            self.assertEqual(json.loads(path_claims._claim_file(self.project, "foreign").read_text())["holder"], "other")
            self.assertFalse(path_claims._claim_file(self.project, "untouched").exists())

            with mock.patch.object(path_claims.NativeProbe, "request", return_value={"written": 3, "blocked": False}), (
                mock.patch.object(path_claims, "_write_claim", side_effect=AssertionError("Python trusted invalid count"))
            ):
                with self.assertRaisesRegex(OSError, "invalid native path claim batch receipt"):
                    path_claims._write_claims(self.project, ["five", "six"], "editor", 60)

            invoke = subprocess.run

            def lose_batch_reply(command, **kwargs):
                result = invoke(command, **kwargs)
                self.assertEqual(command[-1], "path-claim-write-batch")
                self.assertEqual(result.returncode, 0, result.stderr)
                return subprocess.CompletedProcess(result.args, 0, stdout=b"", stderr=b"")

            with mock.patch.object(subprocess, "run", side_effect=lose_batch_reply) as process, (
                mock.patch.object(path_claims, "_write_claim", side_effect=AssertionError("Python replayed batch"))
            ):
                with self.assertRaisesRegex(OSError, "batch outcome could not be determined"):
                    path_claims._write_claims(self.project, ["two", "three"], "editor", 60)
                process.assert_called_once()
            for path in ("two", "three"):
                self.assertEqual(json.loads(path_claims._claim_file(self.project, path).read_text())["path"], path)

    def test_wait_gives_up_after_timeout(self) -> None:
        self.claim("a", "src/x.tsx")

        def advance(seconds: float) -> None:
            self.clock += seconds

        with mock.patch.object(path_claims.time, "sleep", side_effect=advance) as sleep:
            code, output = self.claim("b", "src/x.tsx", extra=("--wait", "3"))
        self.assertEqual(code, path_claims.CONFLICT_EXIT)
        self.assertIn("held by a", output)
        self.assertGreaterEqual(sleep.call_count, 3)

    def test_native_wait_polls_until_deadline_or_release(self) -> None:
        from threading import Timer

        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        request = path_claims.NativeProbe.request
        wait_results = []
        release = False
        claim_file = path_claims._claim_file(self.project, "src/x.tsx")

        def probe(flag, operation, payload):
            if operation != "path-claim-wait":
                return request(flag, operation, payload)
            timer = Timer(0.1, claim_file.unlink) if release else None
            if timer is not None:
                timer.start()
            try:
                result = request(flag, operation, payload)
                wait_results.append(result)
                return result
            finally:
                if timer is not None:
                    timer.cancel()
                    timer.join()

        with (
            mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True),
            mock.patch.object(path_claims, "_now", side_effect=path_claims.time.time),
            mock.patch.object(path_claims.NativeProbe, "request", side_effect=probe),
        ):
            self.assertEqual(self.claim("a", "src/x.tsx")[0], 0)
            with mock.patch.object(path_claims, "try_claim", wraps=path_claims.try_claim) as attempt:
                code, output = self.claim("b", "src/x.tsx", extra=("--wait", "1.2"))
            self.assertEqual(code, path_claims.CONFLICT_EXIT)
            self.assertIn("held by a", output)
            self.assertEqual(attempt.call_count, 2)
            self.assertEqual(wait_results, [{"waited": True}])
            self.assertTrue(claim_file.exists())

            release = True
            self.assertEqual(self.claim("b", "src/x.tsx", extra=("--wait", "3"))[0], 0)
            self.assertEqual(wait_results, [{"waited": True}, {"waited": True}])
            self.assertEqual(self.status()[0]["holder"], "b")

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

    def test_native_record_matches_python_and_does_not_replay_after_lost_reply(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        oracle = self.project / "oracle"
        oracle.mkdir()
        args = ("--holder", "세션😀", "--files", "src/편집.tsx")
        hook = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "src/편집.tsx"}})
        (self.project / "src/편집.tsx").touch()
        log = path_claims.edits_log(self.project)
        large_file = 'parallel"\n' * 800
        with mock.patch.dict(os.environ, {**environment(self.project, ROOT), "TZ": "Asia/Seoul"}, clear=True):
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = self.run_cli("record", "--project", str(oracle), *args)
            before = int(path_claims.time.time())
            with mock.patch.object(path_claims, "edits_log", side_effect=AssertionError("Python append")), (
                mock.patch.object(path_claims, "_now", side_effect=AssertionError("Python sampled the clock"))
            ):
                code, shown = self.run_cli("record", "--project", str(self.project), *args)
                self.assertEqual(code, expected[0])
                self.assertEqual((0, ""), self.run_cli(
                    "record", "--project", str(self.project), "--from-hook", "--holder", "세션😀", stdin=hook
                ))
                with ThreadPoolExecutor(max_workers=4) as workers:
                    list(workers.map(lambda i: path_claims.record(self.project, [large_file], f"s{i}"), range(12)))

            reference = json.loads(expected[1])

            def assert_record(line):
                entry = json.loads(line)
                moment = path_claims._epoch(entry["time"])
                self.assertGreaterEqual(moment, before)
                self.assertLessEqual(moment, int(path_claims.time.time()) + 1)
                self.assertEqual(entry["time"], path_claims._iso(moment))
                self.assertEqual(line, (json.dumps(reference | {"time": entry["time"]}) + "\n").encode())

            lines = log.read_bytes().splitlines(keepends=True)
            self.assertEqual(shown.encode(), lines[0])
            for line in lines[:2]:
                assert_record(line)
            parallel = [json.loads(line) for line in lines[2:]]
            self.assertCountEqual([entry["session"] for entry in parallel], [f"s{i}" for i in range(12)])
            self.assertTrue(all(entry["files"] == [large_file] for entry in parallel))

            invoke = subprocess.run

            def lose_reply(*command, **kwargs):
                result = invoke(*command, **kwargs)
                self.assertEqual(result.returncode, 0, result.stderr)
                return subprocess.CompletedProcess(result.args, 0, stdout=b"", stderr=b"")

            with mock.patch.object(subprocess, "run", side_effect=lose_reply) as process:
                with self.assertRaisesRegex(OSError, "outcome could not be determined"):
                    self.run_cli("record", "--project", str(self.project), *args)
                process.assert_called_once()
                self.assertEqual((0, ""), self.run_cli(
                    "record", "--project", str(self.project), "--from-hook", "--holder", "세션😀", stdin=hook
                ))
                self.assertEqual(process.call_count, 2)
            after = log.read_bytes().splitlines(keepends=True)
            self.assertEqual(after[:-2], lines)
            for line in after[-2:]:
                assert_record(line)

            oversized = "\\" * 270000
            with mock.patch.object(path_claims, "edits_log", wraps=path_claims.edits_log) as fallback:
                entry = path_claims.record(self.project, [oversized], "large")
                fallback.assert_called_once()
            self.assertEqual(entry["time"], path_claims._iso(self.clock))
            self.assertEqual(log.read_bytes(), b"".join(after) + (json.dumps(entry) + "\n").encode())

            receipt = path_claims.NativeProbe.request("--completion-probe", "live-web-edit-append", {
                "project": str(oracle), "entry": reference,
            })
            self.assertEqual(receipt, {"appended": True})
            self.assertEqual(path_claims.edits_log(oracle).read_bytes(), expected[1].encode() * 2)

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

    def test_native_direct_record_resolves_all_files_before_append(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        scope = self.project / "scope"
        scope.mkdir()
        actual = scope / "한글.ts"
        actual.touch()
        (scope / "alias.ts").symlink_to(actual)
        outside = self.project / "outside.ts"
        outside.touch()
        (scope / "escape.ts").symlink_to(outside)
        args = ("record", "--project", str(scope), "--holder", "editor", "--files")
        log = path_claims.edits_log(scope)
        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            with mock.patch.object(path_claims, "normalize", side_effect=AssertionError("Python normalized record")):
                code, output = self.run_cli(*args, "alias.ts", ".", str(actual), "alias.ts")
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output)["files"], ["한글.ts", ".", "한글.ts", "한글.ts"])
                stderr, stdout = io.StringIO(), io.StringIO()
                with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                    self.assertEqual(path_claims.main([*args, "alias.ts", "./escape.ts"]), 1)
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(stderr.getvalue(), "outside the project: ./escape.ts\n")
            self.assertEqual(log.read_bytes(), output.encode())

            request = path_claims.NativeProbe.request

            def old_launcher(protocol, operation, payload):
                if operation == "live-web-edit-record":
                    return None
                return request(protocol, operation, payload)

            with mock.patch.object(path_claims.NativeProbe, "request", side_effect=old_launcher) as probe:
                code, output = self.run_cli(*args, "alias.ts", "new.ts")
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output)["files"], ["한글.ts", "new.ts"])
                self.assertEqual([call.args[1] for call in probe.call_args_list],
                                 ["live-web-edit-record", "live-web-edit-append"])
            self.assertEqual(log.read_bytes().splitlines()[-1], output.strip().encode())

            dangling = scope / "dangling.ts"
            dangling.symlink_to(self.project / "missing.ts")
            before = log.read_bytes()
            with mock.patch.object(path_claims, "normalize", side_effect=AssertionError("Python resolved dangling path")):
                self.assertEqual(self.run_cli(*args, "alias.ts", "dangling.ts"), (1, ""))
            self.assertEqual(log.read_bytes(), before)

    def test_native_hook_binds_project_and_handles_missing_targets(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        scope = self.project / "scope"
        scope.mkdir()
        notebook = scope / "한글.ipynb"
        notebook.touch()
        (scope / "alias.ipynb").symlink_to(notebook)
        outside = self.project / "outside.ts"
        outside.touch()
        (scope / "escape.ts").symlink_to(outside)
        args = ("record", "--from-hook", "--holder", "editor")

        def payload(tool_name, **tool_input):
            return json.dumps({"tool_name": tool_name, "tool_input": tool_input, "cwd": str(scope)})

        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            with mock.patch.object(path_claims, "normalize", side_effect=AssertionError("Python normalized hook")) as normalize:
                self.assertEqual(self.run_cli(*args, stdin=payload(
                    "NotebookEdit", file_path="", notebook_path="alias.ipynb"
                )), (0, ""))
                override = json.loads(payload("MultiEdit", file_path="alias.ipynb"))
                override.update(cwd=str(self.project), ignored=float("nan"))
                self.assertEqual(self.run_cli(*args, "--project", str(scope), stdin=json.dumps(override)), (0, ""))
                self.assertEqual(self.run_cli(*args, stdin=payload("Edit", file_path="escape.ts")), (0, ""))
                self.assertEqual(self.run_cli(*args, stdin=payload("Bash", file_path="한글.ipynb")), (0, ""))
                self.assertEqual(self.run_cli(*args, stdin="{broken"), (0, ""))
                normalize.assert_not_called()
            with mock.patch.object(path_claims, "normalize", side_effect=AssertionError("Python resolved missing hook path")) as normalize:
                self.assertEqual(self.run_cli(*args, "--project", str(scope), stdin=payload(
                    "Write", file_path="not-yet-created.ts"
                )), (0, ""))
                normalize.assert_not_called()
        log = path_claims.edits_log(scope)
        self.assertEqual([json.loads(row)["files"] for row in log.read_text().splitlines()],
                         [["한글.ipynb"], ["한글.ipynb"], ["not-yet-created.ts"]])
        self.assertFalse(path_claims.edits_log(self.project).exists())

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

    def test_native_check_matches_python_tail_timestamp_and_path_selection(self) -> None:
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.project / "home"
        home.mkdir()
        install(home, ROOT)
        log = live_web_checks.checks_log(self.project)
        log.parent.mkdir(parents=True)
        old = b'{"files":["cut.tsx"],"time":"2026-10-15T09:16:12Z"}\n'
        recent = (b'{"files":["/src/ui/Header.tsx/"],"time":"2026-10-15T11:16:12+02:00",'
                  b'"errors":["bad \xff byte"],"extra":1e400}\n'
                  b'{"files":["Header.tsx"],"time":"2026-10-15T09:16:11.999999Z","errors":[]}\n'
                  b'{"files":["src/elsewhere.tsx"],"time":"2026-10-15T09:20:00Z"}\n'
                  b'["ignored"]\n{"partial":')
        padding = b"x" * (live_web_checks.CHECK_TAIL_BYTES - len(old) - len(recent) - 1)
        log.write_bytes(b"anchor\n" + old + padding + b"\n" + recent)
        source = self.project / "src" / "ui"
        source.mkdir(parents=True)
        (source / "Header.tsx").touch()
        alias = self.project / "alias.tsx"
        alias.symlink_to(source / "Header.tsx")
        (home / "alias.tsx").symlink_to(source / "Header.tsx")
        args = (
            ("--json", "--files", "Header.tsx", "--since", "2026-10-15T09:16:12Z"),
            ("--json", "--files", "web/src/ui/Header.tsx", "--since", "2026-10-15T09:16:12"),
            ("--json", "--files", "eader.tsx"),
            ("--json", "--files", "cut.tsx"),
            ("--json", "--files", "src//unused/../ui/./Header.tsx", "--since", "invalid"),
            ("--json", "--files", str(alias), "--since", "2026-10-15T09:16:12+00:00"),
            ("--json", "--files", "~//alias.tsx"),
        )
        with mock.patch.dict(os.environ, environment(self.project, ROOT), clear=True):
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = [self.check(*argv) for argv in args]
            with mock.patch.object(live_web_checks, "read_checks", side_effect=AssertionError("Python read the log")), (
                mock.patch.object(live_web_checks, "check_problems", side_effect=AssertionError("Python classified the check"))
            ), (
                mock.patch.object(live_web_checks, "_relative", side_effect=AssertionError("Python normalized the path"))
            ), (
                mock.patch.object(live_web_checks, "_since_epoch", side_effect=AssertionError("Python parsed the timestamp"))
            ):
                self.assertEqual(expected, [self.check(*argv) for argv in args])
            self.assertEqual([4, 4, 5, 5, 0, 4, 0], [code for code, _ in expected])
            payload = json.loads(expected[0][1])["check"]
            self.assertEqual(["bad � byte"], payload["errors"])
            self.assertEqual(float("inf"), payload["extra"])

            self.write_checks({
                "files": ["한.js"], "time": None, "reloadFailed": 1, "errors": [True, 7],
                "extra": [-0.0, float("inf"), float("-inf"), float("nan"), 10 ** 30],
                "views": [None, {"viewport": "", "elements": True, "boxes": [[0, 0, 2.5, 3.5]]},
                          {"viewport": "Wide", "elements": 1.0, "boxes": [[0, 0, -0.5, 4.5]]},
                          {"viewport": "Other", "elements": False, "boxes": [[0, 0, 10 ** 30, True]]}],
            })
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = [self.check(), self.check("--json")]
            with mock.patch.object(live_web_checks, "describe_check", side_effect=AssertionError("Python rendered text")), (
                mock.patch.object(live_web_checks, "read_checks", side_effect=AssertionError("Python read the log"))
            ):
                self.assertEqual(expected, [self.check(), self.check("--json")])
            self.assertIn("? True element (2x4), Wide 0 elements (0x4)", expected[0][1])
            self.assertTrue(expected[0][1].endswith("errors 2: True; reload ok"))
            self.assertIn("\\ud55c.js", expected[1][1])

            unsupported = ("--json", "--files", "Header.tsx", "--since", "20261015T091612")
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = self.check(*unsupported)
            with mock.patch.object(live_web_checks, "read_checks", wraps=live_web_checks.read_checks) as read:
                self.assertEqual(expected, self.check(*unsupported))
                read.assert_called_once()

            log.write_bytes(b'{"files":["Header.tsx"],"time":"20261015T091612"}\n')
            with mock.patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                expected = self.check(*args[0])
            with mock.patch.object(live_web_checks, "read_checks", wraps=live_web_checks.read_checks) as read:
                self.assertEqual(expected, self.check(*args[0]))
                read.assert_called_once()


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
