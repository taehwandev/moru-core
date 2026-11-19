"""Native completion policy through the actual private binary protocol."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_local_delivery import LocalDeliveryProof, _capture_identities
from agent_pending_publication import _git, _observe
from native_pretool_support import environment, prepare
from support.completion_native import completion_native


def contract(revision=1, **overrides):
    return {"revision": revision, "items": [{"id": "r1", "outcome": "Deliver the plan", "owner": "lead",
        "gate": "tests", "artifacts": ["plan.md"], **overrides}]}


class NativeCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-completion-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        self.empty = self.base / "empty"
        self.empty.mkdir()

    def raw(self, op, value, **overrides):
        return subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry), "--completion-probe", op],
            input=json.dumps(value).encode() if not isinstance(value, bytes) else value,
            env={**self.env, "PATH": str(self.empty), **overrides}, cwd=self.project, capture_output=True, timeout=10)

    def check(self, op, value):
        result = self.raw(op, value)
        self.assertEqual((0, b""), (result.returncode, result.stderr), result)
        envelope = json.loads(result.stdout)
        self.assertEqual(1, envelope["schema_version"])
        return envelope["result"]

    def test_staged_receipt_hash_matches_python_for_index_and_tree(self):
        index = '100755 ef 0\tz"\\악\x7f\U0001f408\0\0' + '100644 ab 0\ta\tb\n\0'
        tree = '100644 blob ab\ta\tb\n\0' + '100755 blob ef\tz"\\악\x7f\U0001f408\0'
        index += "160000 0123 0\te\u0301\0" + "120000 4567 0\té\0" * 2
        tree += "120000 blob 4567\té\0" * 2 + "160000 commit 0123\te\u0301\0"
        for staged, base in ((index, tree), ("", ""), ("", tree)):
            with self.subTest(empty=not staged):
                expected = (LocalDeliveryProof._identity(staged, index=True),
                            LocalDeliveryProof._identity(base))
                result = self.check("staged-v1", {"index": staged, "base": base})
                self.assertEqual(result, dict(zip(("staged", "base"), expected)))
                with patch.dict(os.environ, self.env, clear=True), patch.object(
                        LocalDeliveryProof, "_identity", side_effect=AssertionError("Python fallback")):
                    self.assertEqual(expected, _capture_identities(staged, base))

        for bad in ("100644 ab 2\tx\0", "missing tab", "100644 ab 0 extra\tx"):
            result = self.raw("staged-v1", {"index": bad, "base": tree})
            self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
            with patch.dict(os.environ, self.env, clear=True), self.assertRaises(ValueError):
                _capture_identities(bad, tree)

    def test_local_delivery_search_keeps_cache_order_and_scan_limit(self):
        project = self.project

        def git(*args):
            return subprocess.run(["git", "-C", str(project), *args], check=True,
                                  capture_output=True, text=True, env=self.env, timeout=5).stdout.strip()

        def commit(label, content=None):
            if content is not None:
                (project / "receipt.txt").write_text(content, encoding="utf-8")
                git("add", "receipt.txt")
            git("commit", "--allow-empty", "-qm", label)
            return git("rev-parse", "HEAD")

        def digest(oid):
            return LocalDeliveryProof._identity(git("ls-tree", "-r", "-z", oid))

        git("config", "user.email", "fixture@example.invalid")
        git("config", "user.name", "Fixture")
        base = commit("base")
        first = commit("first match", "proof")
        different = commit("different", "other")
        second = commit("second match", "proof")
        for _ in range(60):
            commit("same tree")
        boundary = commit("64th commit", "inside limit")
        head = commit("65th commit", "outside limit")
        git("branch", "source", head)
        git("branch", "integration", base)
        payload = {"project": str(project), "base": base, "source": "source", "targets": ["integration"],
                   "checkpoint": "publication.commit", "commit_declared": True}

        def observe(**overrides):
            result = self.raw("staged-v1-observe", {**payload, **overrides}, PATH=os.defpath)
            self.assertEqual((0, b""), (result.returncode, result.stderr))
            return json.loads(result.stdout)["result"]

        for target, cached, expected in (
            (first, "", first), (first, second, second), (first, different, first),
            (boundary, "", boundary), (head, "", ""),
        ):
            with self.subTest(target=target, cached=cached):
                result = observe(cached=cached, expected=digest(target))
                if expected:
                    self.assertEqual({"observation": f"reviewed staged content committed as {expected}",
                                      "reason": ""}, result)
                else:
                    self.assertEqual({"observation": "",
                                      "reason": "the reviewed staged content has not been observed in a commit"}, result)

        request = {**payload, "cached": "", "expected": digest(first)}
        result = self.raw("staged-v1-observe", request)
        self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))

        record = {"schema_version": 2, "base_head": base, "source_branch": "main",
                  "local_delivery": {"project": str(project), "common": str(project / ".git"),
                                     "commit_declared": True, "staged_sha256": digest(first), "targets": {}}}
        with patch.dict(os.environ, self.env, clear=True):
            with patch.object(LocalDeliveryProof, "_committed", side_effect=AssertionError("Python fallback")):
                self.assertEqual((f"reviewed staged content committed as {first}", ""),
                                 _observe(project, record, {"checkpoint": "publication.commit"}))
            with patch("agent_pending_publication._git", wraps=_git) as reader:
                self.assertEqual((f"reviewed staged content committed as {first}", ""),
                                 _observe(project, record, {"checkpoint": "publication.commit"}))
                self.assertIn(("ls-tree", "-r", "-z", first), [call.args[1:] for call in reader.call_args_list])

        args = {"checkpoint": "publication.integrate/integration", "cached": "", "expected": digest(first)}
        self.assertEqual("target branch does not contain the reviewed commit", observe(**args)["reason"])
        self.assertEqual("local integration target was not prepared", observe(**{**args, "targets": []})["reason"])
        git("branch", "-f", "integration", head)
        integrated = f"target integration contains reviewed commit {first}"
        self.assertEqual(integrated, observe(**args)["observation"])
        git("branch", "-f", "source", base)
        self.assertEqual("local delivery proof cannot be verified", observe(**{**args, "base": first})["reason"])
        git("branch", "-D", "source")
        self.assertEqual(integrated, observe(**args)["observation"])
        self.assertEqual(f"target integration contains reviewed commit {base}",
                         observe(**{**args, "commit_declared": False})["observation"])
        record["source_branch"] = "source"
        record["local_delivery"]["targets"] = {"integration": base}
        with patch.dict(os.environ, self.env, clear=True), patch.object(
                LocalDeliveryProof, "_committed", side_effect=AssertionError("Python fallback")):
            self.assertEqual((integrated, ""), _observe(project, record, {"checkpoint": args["checkpoint"]}))
            record["local_delivery"]["common"] = str(project / "foreign.git")
            with patch("agent_local_delivery.NativeProbe.request") as native:
                self.assertEqual(("", "local delivery belongs to a different repository or checkout"),
                                 _observe(project, record, {"checkpoint": args["checkpoint"]}))
                native.assert_not_called()

    def test_quality_warns_without_executing_commands_or_printing_command_content(self):
        marker = self.project / "never-created"
        records = [{"gate": "tests", "status": "SUCCESS", "fields": {"check": cmd, "result": "1 test passed"}}
                   for cmd in ("echo success", "printf 'done'", "true", ":", "exit 0",
                               f"echo ok && touch {marker}", "pytest -q", "echo $OBSERVED")]
        warnings = self.check("quality", {"records": records})["warnings"]
        self.assertEqual(5, len(warnings))
        self.assertTrue(all(row == {"gate": "tests", "rule": "fixed_output_check"} for row in warnings))
        self.assertFalse(marker.exists())
        records[0]["fields"] = {"check": "pytest", "result": "0 tests; exit 0"}
        records[1]["fields"]["result"] = "5 tests; 0 failures"
        rules = [v["rule"] for v in self.check("quality", {"records": records})["warnings"]]
        self.assertEqual(1, rules.count("zero_test_count"))

    def test_requirements_revision_duplicates_and_removal_are_checked(self):
        original = contract()
        self.assertEqual([], self.check("requirements", {"current": original, "previous": None})["failures"])
        changed = contract(owner="other")
        self.assertIn("requirements_revision_must_advance", self.check("requirements", {"current": changed, "previous": original})["failures"])
        changed["revision"] = 2
        self.assertEqual([], self.check("requirements", {"current": changed, "previous": original})["failures"])
        changed["items"][0]["id"] = "r2"
        self.assertIn("requirements_cannot_disappear", self.check("requirements", {"current": changed, "previous": original})["failures"])
        for value in ({"revision": True, "items": []}, {"revision": 1, "items": []},
                      {"revision": 1, "items": original["items"] * 2}, contract(artifacts=["../outside"]),
                      contract(artifacts=[".moru/hidden"]), contract(artifacts=["plan.md", "plan.md"])):
            with self.subTest(value=value):
                self.assertTrue(self.check("requirements", {"current": value})["failures"])

    def test_coverage_observes_gate_and_actual_artifact_and_rejects_symlinks(self):
        value = {"current": contract(), "project": str(self.project), "allowed_gates": ["tests"],
                 "gates": [{"gate": "tests", "status": "SUCCESS"}]}
        self.assertTrue(self.check("coverage", value)["failures"])
        (self.project / "plan.md").write_text("Delivered plan\n")
        output = self.check("coverage", value)
        self.assertEqual([], output["failures"])
        self.assertEqual(64, len(output["observations"][0]["artifacts"]["plan.md"]))
        value["gates"].append({"gate": "tests", "status": "FAIL"})
        self.assertTrue(self.check("coverage", value)["failures"])
        value["gates"] = [{"gate": "tests", "status": "SUCCESS"}]
        value["allowed_gates"] = ["other"]
        self.assertTrue(self.check("coverage", value)["failures"])
        value["allowed_gates"] = ["tests"]
        target = self.project / "actual.md"
        (self.project / "plan.md").rename(target)
        (self.project / "plan.md").symlink_to(target)
        self.assertTrue(self.check("coverage", value)["failures"])

    def test_progress_ignores_metadata_and_order_but_resets_for_acceptance_changes(self):
        work = {"remaining_work": [{"checkpoint": "tests", "action": "Check plan"},
            {"checkpoint": "review", "action": "Review plan"}], "blockers": ["second", "first"], "requirements": contract()}
        value = {"work": work, "gates": [{"gate": "tests", "status": "FAIL", "updated_at": "one"},
                                           {"gate": "review", "status": "SUCCESS"}]}
        first = self.check("progress", value)
        for index in range(2):
            value["previous"] = first
            value["updated_at"] = str(index)
            value["work"]["generation"] = index
            value["work"]["requirements"]["revision"] += 1
            value["work"]["remaining_work"].reverse()
            value["work"]["blockers"].reverse()
            value["gates"].reverse()
            value["gates"][0]["updated_at"] = str(index)
            first = self.check("progress", value)
        self.assertTrue(first["stalled"])
        self.assertEqual(2, first["repeats"])
        value["previous"] = first
        value["gates"][0]["status"] = "SUCCESS"
        final = self.check("progress", value)
        self.assertEqual(0, final["repeats"])
        self.assertFalse(final["stalled"])

    def test_long_gate_history_preserves_latest_failure(self):
        (self.project / "plan.md").write_text("Delivered\n")
        value = {"current": contract(), "project": str(self.project), "allowed_gates": ["tests"],
                 "gates": [{"gate": "tests", "status": "SUCCESS"}] * 1024}
        self.assertEqual([], self.check("coverage", value)["failures"])
        value["gates"].append({"gate": "tests", "status": "FAIL"})
        self.assertIn("observing gate", self.check("coverage", value)["failures"][0])
        value["gates"].append({"gate": "tests", "status": "SUCCESS"})
        self.assertEqual([], self.check("coverage", value)["failures"])

    def test_artifact_limits_return_specific_failures_at_exact_boundaries(self):
        for name in ("one.bin", "two.bin"):
            with (self.project / name).open("wb") as stream:
                stream.truncate(16 * 1024 * 1024)
        value = {"current": contract(artifacts=["one.bin", "two.bin"]), "project": str(self.project),
                 "allowed_gates": ["tests"], "gates": [{"gate": "tests", "status": "SUCCESS"}]}
        self.assertEqual([], self.check("coverage", value)["failures"])
        (self.project / "three.bin").write_bytes(b"x")
        value["current"]["items"][0]["artifacts"].append("three.bin")
        self.assertIn("32 MiB total limit", self.check("coverage", value)["failures"][0])
        with (self.project / "one.bin").open("ab") as stream:
            stream.write(b"x")
        self.assertTrue(any("16 MiB file limit" in failure for failure in self.check("coverage", value)["failures"]))
        (self.project / "one.bin").unlink()
        os.mkfifo(self.project / "one.bin")
        self.assertIn("unsafe", self.check("coverage", value)["failures"][0])

    def test_protocol_source_environment_and_python_rollback_boundaries(self):
        for op, payload in (("unknown", {}), ("quality", b"{broken"), ("quality", b" " * (1024 * 1024 + 1))):
            result = self.raw(op, payload, MORU_HOOK_SOFT_FAIL="1")
            self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
        self.assertEqual(125, self.raw("quality", {"records": []}, PYTHONVERBOSE="1").returncode)
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual({"warnings": []}, completion_native("quality", {"records": []}))
            with patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                self.assertIsNone(completion_native("quality", {"records": []}))


if __name__ == "__main__":
    unittest.main()
