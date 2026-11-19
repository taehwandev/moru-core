"""Native completion policy through the actual private binary protocol."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_execution_capsule_state import atomic_write_json
from agent_local_delivery import LocalDeliveryProof, _capture_identities
from agent_pending_publication import (
    _git, _legacy_local_head, _legacy_local_head_python, _load, _load_python, _new_record, _observe, _observed_record, _store,
    _remote_head, outstanding, pending_reason, record_pending, split_remaining,
)
from agent_publication_status import _observe_pull_request_python, observe_pull_request, observe_upstream
from native_pretool_support import environment, prepare
from support.completion_native import completion_native
from support.native_probe_transport import NativeProbe
from test_agent_run_interruption import Run


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

    def test_pending_publication_encoder_preserves_atomic_write_and_exact_bytes(self):
        path = self.base / "pending-publication.json"
        payload = {"z": [{"b": "한글🐈", "a": []}], "A": {}, "가": None,
                   "escape": '\x00\b\t\n\f\r\x1f\x7f"\\/', "count": 2**64 - 1}
        expected = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
        result = self.raw("pending-publication-encode", payload)
        self.assertEqual((0, expected, b""), (result.returncode, result.stdout, result.stderr))

        path.write_bytes(b"previous\n")
        with patch.dict(os.environ, self.env, clear=True), patch(
                "agent_execution_capsule_state._encoded_json", side_effect=AssertionError("Python fallback")):
            atomic_write_json(path, payload, write_payload=NativeProbe.encode_publication_receipt)
        self.assertEqual(expected, path.read_bytes())
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        with patch.dict(os.environ, self.env, clear=True), path.open("rb") as read_only:
            self.assertFalse(NativeProbe.encode_publication_receipt(payload, read_only))
        self.assertEqual(expected, path.read_bytes())

        def partial(_, stream):
            self.assertEqual(expected, path.read_bytes())
            stream.write(b"old oversized output" * 100)
            return False

        atomic_write_json(path, payload, write_payload=partial)
        self.assertEqual(expected, path.read_bytes())

        def failed(_, stream):
            stream.write(b"partial")
            raise OSError("write failed")

        with self.assertRaisesRegex(OSError, "write failed"):
            atomic_write_json(path, payload, write_payload=failed)
        self.assertEqual(expected, path.read_bytes())
        self.assertFalse(list(path.parent.glob(path.name + ".*.tmp")))
        collision = path.with_name(path.name + ".existing.tmp")
        collision.write_bytes(b"another writer's temporary file")
        with patch("agent_execution_capsule_state.uuid.uuid4") as uuid:
            uuid.return_value.hex = "existing"
            with self.assertRaises(FileExistsError):
                atomic_write_json(path, payload, write_payload=partial)
        self.assertEqual(b"another writer's temporary file", collision.read_bytes())
        self.assertEqual(expected, path.read_bytes())

        unusual = {**payload, "decimal": 1e-5, "large": 2**100}
        result = self.raw("pending-publication-encode", unusual)
        self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
        with patch.dict(os.environ, self.env, clear=True):
            atomic_write_json(path, unusual, write_payload=NativeProbe.encode_publication_receipt)
        self.assertEqual((json.dumps(unusual, sort_keys=True, indent=2) + "\n").encode(), path.read_bytes())

    def test_native_receipt_replacement_is_bound_and_atomic(self):
        run, nonce = "a" * 32, "b" * 32
        directory = self.project / ".moru" / "runs" / run
        directory.mkdir(parents=True)
        evidence = directory / "preflight.json"
        evidence.write_bytes(b"{}\n")
        target = directory / "pending-publication.json"
        record = {
            "schema_version": 1, "run_id": run, "base_head": "c" * 40,
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "items": [{"checkpoint": "publication.commit", "state": "pending", "observation": "한글"}],
        }
        request = {"evidence": str(evidence), "temporary": nonce, "record": record}
        target.write_bytes(b"old\n")
        temporary = target.with_name(f"{target.name}.{nonce}.tmp")
        temporary.write_bytes(b"another writer")
        self.assertEqual({"error": "FileExistsError"}, self.check("pending-publication-replace", request))
        self.assertEqual(b"another writer", temporary.read_bytes())
        self.assertEqual(b"old\n", target.read_bytes())
        temporary.unlink()
        for changes in ({"run_id": "d" * 32}, {"evidence_sha256": "0" * 64},
                        {"opaque": "project_local_never_sync"},
                        {f".moru/runs/{run}/continuation.json?query": "rejected"}):
            refused = self.raw("pending-publication-replace", {**request, "record": {**record, **changes}})
            self.assertEqual((125, b"", b""), (refused.returncode, refused.stdout, refused.stderr))
            self.assertEqual(b"old\n", target.read_bytes())
            self.assertFalse(temporary.exists())
        with patch.dict(os.environ, self.env, clear=True), patch(
                "agent_pending_publication.atomic_write_json", side_effect=AssertionError("Python fallback")):
            _store(evidence, record)
        self.assertEqual((json.dumps(record, sort_keys=True, indent=2) + "\n").encode(), target.read_bytes())
        self.assertEqual(0o600, target.stat().st_mode & 0o777)
        self.assertFalse(list(directory.glob("*.tmp")))
        alias = directory.with_name("e" * 32)
        alias.symlink_to(directory, target_is_directory=True)
        aliased = self.raw("pending-publication-replace", {
            **request, "evidence": str(alias / evidence.name), "record": {**record, "run_id": alias.name},
        })
        self.assertEqual((125, b"", b""), (aliased.returncode, aliased.stdout, aliased.stderr))
        with patch.dict(os.environ, self.env, clear=True), self.assertRaises(OSError):
            _store(alias / evidence.name, {**record, "run_id": alias.name})
        self.assertEqual((json.dumps(record, sort_keys=True, indent=2) + "\n").encode(), target.read_bytes())
        old_target = directory / "external-object"
        old_target.write_bytes(b"linked content")
        target.unlink()
        target.symlink_to(old_target)
        self.assertEqual({"error": None}, self.check("pending-publication-replace", request))
        self.assertFalse(target.is_symlink())
        self.assertEqual(b"linked content", old_target.read_bytes())
        target.unlink()
        target.mkdir()
        with self.assertRaises(OSError) as failure:
            atomic_write_json(target, record)
        self.assertEqual({"error": type(failure.exception).__name__},
                         self.check("pending-publication-replace", request))
        self.assertFalse(list(directory.glob("*.tmp")))
        self.assertTrue(target.is_dir())

    def test_receipt_write_transport_does_not_retry_unknown_outcomes(self):
        evidence = self.project / "preflight.json"
        record = {"data": True}
        with patch.dict(os.environ, self.env, clear=True), patch(
                "agent_pending_publication.atomic_write_json") as legacy, patch(
                "support.native_probe_transport.subprocess.run") as native:
            for status, stdout in ((1, b""), (0, b""), (-9, b"")):
                native.return_value = subprocess.CompletedProcess([], status, stdout, b"")
                with self.assertRaisesRegex(OSError, "outcome could not be determined"):
                    _store(evidence, record)
            native.side_effect = subprocess.TimeoutExpired([], 10)
            with self.assertRaisesRegex(OSError, "outcome could not be determined"):
                _store(evidence, record)
            legacy.assert_not_called()
            native.side_effect = None
            native.return_value = subprocess.CompletedProcess([], 125, b"", b"")
            _store(evidence, record)
            legacy.assert_called_once_with(evidence.with_name("pending-publication.json"), record,
                                           write_payload=NativeProbe.encode_publication_receipt)

    def test_pending_publication_transitions_preserve_receipt_order_and_metadata(self):
        fields = {"run_id": "test-run", "evidence_sha256": "1" * 64, "base_head": "2" * 40,
                  "source_branch": "reviewed"}
        checkpoints = ["publication.integrate/main", "publication.commit", "publication.integrate/main",
                       "publication.push"]
        local = {"targets": {"main": "2" * 40}, "extension": [None, True, 2**63]}
        baseline = {**self.env, "MORU_LAUNCHER_BACKEND": "python"}
        observed_at = "2026-05-28T00:00:00+00:00"
        oid = "3" * 40
        for proof in (None, local):
            with patch.dict(os.environ, baseline, clear=True):
                record = _new_record(fields, checkpoints, proof)
            result = self.check("pending-publication-prepare", {
                **fields, "checkpoints": checkpoints, "local_delivery": proof,
            })
            self.assertEqual({"record": record}, result)
            with patch.dict(os.environ, self.env, clear=True):
                self.assertEqual(record, _new_record(fields, checkpoints, proof))
            self.assertEqual(list(dict.fromkeys(checkpoints)), [item["checkpoint"] for item in record["items"]])

            record["extension"] = [None, {"漢字": "🎉"}]
            commit = record["items"][1]
            record["items"].insert(0, {**commit, "state": "observed", "observation": "prior"})
            record["items"].append({**commit, "historical": True})
            for checkpoint, observation in (("publication.commit", f"committed as {oid}"),
                                            ("publication.push", f"pushed {oid}"),
                                            ("publication.integrate/main", f"integrated {oid} ")):
                with self.subTest(version=record["schema_version"], checkpoint=checkpoint):
                    reference = json.loads(json.dumps(record))
                    item = next(i for i in reference["items"]
                                if i["checkpoint"] == checkpoint and i["state"] == "pending")
                    with patch.dict(os.environ, baseline, clear=True):
                        expected = _observed_record(reference, item, observation, observed_at)
                    result = self.check("pending-publication-observe", {
                        "record": record, "checkpoint": checkpoint, "observation": observation,
                        "observed_at": observed_at,
                    })
                    self.assertEqual({"record": expected}, result)
                    original = json.loads(json.dumps(record))
                    item = next(i for i in record["items"]
                                if i["checkpoint"] == checkpoint and i["state"] == "pending")
                    with patch.dict(os.environ, self.env, clear=True):
                        self.assertEqual(expected, _observed_record(record, item, observation, observed_at))
                    self.assertEqual(original, record)
                    if proof is None:
                        self.assertNotIn("local_delivery", expected)
                    else:
                        cache = oid if checkpoint == "publication.commit" else None
                        self.assertEqual(cache, expected["local_delivery"].get("reviewed_commit"))

    def test_pending_publication_launcher_uses_native_status_without_losing_bound_debt(self):
        folder = self.base / "bound"
        folder.mkdir()
        with patch.dict(os.environ, self.env, clear=True):
            run = Run(str(folder), packet=True, writable=True, command="commit",
                      effect="git_write", authority="envelope")
        status = [str(self.entry), "pending-publication", "status",
                  "--evidence", str(run.evidence), "--project", str(run.project)]

        def invoke(backend="auto", empty=False, args=status):
            env = {**self.env, "MORU_LAUNCHER_BACKEND": backend}
            if empty:
                env["PATH"] = str(self.empty)
            done = subprocess.run(args, cwd=run.project, env=env, capture_output=True, timeout=15)
            return done.returncode, done.stdout, done.stderr

        self.assertEqual((0, b"no pending publication\n", b""), invoke(empty=True))
        items = [{"checkpoint": "publication.commit", "action": "Commit the reviewed files"}]
        with patch.dict(os.environ, self.env, clear=True):
            write_continuation_checkpoint(
                project=run.project, rules=run.project, run_id=run.run["run_id"], kind="initial",
                phase="acting", binding_path=run.evidence,
                work={"objective": "Finish the reviewed local commit", "remaining_work": items},
            )
        owed = invoke("python")
        self.assertEqual(0, owed[0])
        self.assertIn(b"(publication.commit)", owed[1])
        self.assertEqual(owed, invoke())
        self.assertEqual(127, invoke(empty=True)[0])

        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual("", record_pending(run.project, run.evidence, items))
        self.assertEqual(owed, invoke(empty=True))
        trailing_slash = [value + "/" if value == str(run.evidence) else value for value in status]
        self.assertEqual(owed, invoke(empty=True, args=trailing_slash))
        receipt = run.evidence.with_name("pending-publication.json")
        record = json.loads(receipt.read_text())
        record["items"][0]["state"] = "observed"
        receipt.write_text(json.dumps(record))
        self.assertEqual((0, b"no pending publication\n", b""), invoke(empty=True))
        self.assertEqual(invoke("python"), invoke(empty=True))
        run.evidence.with_name("continuation.json").write_text("{")
        self.assertEqual(invoke("python"), invoke())
        self.assertEqual(127, invoke(empty=True)[0])

    def test_legacy_local_settlement_launcher_needs_git_but_no_python_or_registry(self):
        def git(*args):
            return subprocess.run(["git", "-C", str(self.project), *args], check=True,
                                  capture_output=True, text=True, env=self.env, timeout=5).stdout.strip()

        def commit(message):
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", message)
            return git("rev-parse", "HEAD")

        file = self.project / "tracked.txt"
        file.write_text("base\n")
        git("add", file.name)
        base = commit("base")
        run = self.project / ".moru" / "runs" / ("a" * 32)
        run.mkdir(parents=True)
        evidence = run / "preflight.json"
        evidence.write_bytes(b"{}\n")
        receipt = run / "pending-publication.json"
        checkpoint = "publication.commit"
        integration = "publication.integrate/main"
        receipt.write_text(json.dumps({
            "schema_version": 1, "run_id": run.name, "base_head": base, "source_branch": "main",
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "items": [{"checkpoint": item, "state": "pending"} for item in (checkpoint, integration)],
        }))
        before = receipt.read_bytes()
        (self.empty / "git").symlink_to(shutil.which("git"))

        def launcher(action=checkpoint, *, legacy=False):
            env = ({**self.env, "MORU_LAUNCHER_BACKEND": "python"} if legacy else
                   {**self.env, "PATH": str(self.empty)})
            args = [str(self.entry), "pending-publication", "settle", "--checkpoint", action,
                    "--evidence", str(evidence), "--project", str(self.project)]
            result = subprocess.run(args, env=env, capture_output=True, timeout=15)
            return result.returncode, result.stdout, result.stderr

        def refused(reason, action=checkpoint):
            expected = (2, f"FAIL publication settle: {reason}\n".encode(), b"")
            self.assertEqual(expected, launcher(action, legacy=True))
            self.assertEqual(expected, launcher(action))
            self.assertEqual(before, receipt.read_bytes())

        refused("local integration requires a bound staged-content proof", integration)
        refused("HEAD has not advanced from the finished commit base")
        file.write_text("reviewed\n")
        git("add", file.name)
        head = commit("reviewed")
        git("checkout", "--detach")
        refused("source branch differs from the finished publication")
        git("checkout", "main")
        file.write_text("dirty\n")
        refused("tracked changes remain uncommitted")
        file.write_text("reviewed\n")
        (self.project / "untracked.txt").write_text("ignored by legacy proof")
        self.assertEqual((0, b"publication observation recorded\n", b""), launcher())
        record = json.loads(receipt.read_bytes())
        self.assertNotIn("local_delivery", record)
        self.assertEqual(f"HEAD {head} descends from {base}", record["items"][0]["observation"])
        self.assertEqual("pending", record["items"][1]["state"])
        self.assertFalse((self.project / ".moru" / "run-registry.json").exists())

    def test_pending_publication_partition_preserves_admitted_effect_and_original_items(self):
        opaque = object()
        commit = {"checkpoint": "publication.commit", "action": opaque}
        integrate = {"checkpoint": "publication.integrate/main"}
        push = {"checkpoint": "publication.push"}
        pr = {"checkpoint": "publication.pull-request/develop"}
        invalid = {"checkpoint": "publication.pull-request/-invalid"}
        remaining = [pr, commit, invalid, None, integrate, push, commit, {"checkpoint": "publication.integrate"}]
        fallback = {**self.env, "MORU_LAUNCHER_BACKEND": "python"}
        original_request = NativeProbe.request
        for command, effect, local, authority, schema, failures, positions in (
            ("commit", "git_write", False, "envelope", True, [], [1, 6]),
            ("commit", "external_write", False, "envelope", True, [], [0, 1, 5, 6]),
            ("commit", "external_write", True, "envelope", True, [], [0, 1, 4, 5, 6]),
            ("task", "git_write", True, "envelope", True, [], [1, 4, 6]),
            ("task", "external_write", True, "envelope", True, [], [1, 4, 6]),
            ("task", "local_write", True, "envelope", True, [], []),
            ("task", "external_write", True, "assumed", True, [], []),
            ("task", "external_write", True, "envelope", False, [], []),
            ("task", "external_write", True, "envelope", True, ["invalid"], []),
            ("review", "external_write", True, "envelope", True, [], []),
        ):
            with self.subTest(command=command, effect=effect, local=local, authority=authority, schema=schema,
                              failures=failures):
                envelope = {"effective_effect": effect, "authority": authority,
                            "schema_valid": schema, "failures": failures}
                route = {"command": command, "request_classification": {"intent_envelope": envelope}}
                if local:
                    route["local_delivery_contract"] = LocalDeliveryProof.CONTRACT
                with patch.dict(os.environ, fallback, clear=True):
                    expected = split_remaining({"route": route}, remaining)
                seen = []

                def request(*args):
                    result = original_request(*args)
                    seen.append(result)
                    return result

                with patch.dict(os.environ, self.env, clear=True), patch(
                        "agent_pending_publication.NativeProbe.request", side_effect=request):
                    actual = split_remaining({"route": route}, remaining)
                self.assertEqual(expected, actual)
                self.assertEqual([remaining[index] for index in positions], actual[1])
                self.assertTrue(all(item is remaining[index] for item, index in zip(actual[1], positions)))
                mask = [index in positions for index in range(len(remaining))]
                self.assertEqual([] if command == "review" else [{"deferred": mask}], seen)

    def test_pending_publication_status_preserves_debt_and_order_from_bound_receipts(self):
        run = self.base / "status-run"
        run.mkdir()
        evidence = run / "preflight.json"
        receipt = run / "pending-publication.json"
        evidence.write_bytes(b"fixture")
        names = ["publication.commit", "publication.push", "publication.integrate/main", "publication.push",
                 "publication.pull-request/main"]
        declared = [{"checkpoint": name} for name in names] + [{"checkpoint": "ignored"}, None]
        fallback = {**self.env, "MORU_LAUNCHER_BACKEND": "python"}

        def compare(wanted):
            checkpoints = declared if wanted else []
            with patch.dict(os.environ, fallback, clear=True), patch(
                    "agent_pending_publication.declared_deferrable", return_value=checkpoints):
                expected = outstanding(self.project, evidence, checkpoints), pending_reason(self.project, evidence)
            self.assertEqual({"owed": expected[0], "reason": expected[1]},
                             self.check("pending-publication-status", {
                                 "evidence": str(evidence), "declared": names if wanted else [],
                             }))
            with patch.dict(os.environ, self.env, clear=True), patch(
                    "agent_pending_publication._outstanding_python", side_effect=AssertionError("Python fallback")
            ), patch("agent_pending_publication.declared_deferrable", return_value=checkpoints):
                self.assertEqual(expected, (outstanding(self.project, evidence, checkpoints),
                                            pending_reason(self.project, evidence)))
            return expected[0]

        self.assertEqual([], compare(False))
        self.assertEqual(list(dict.fromkeys(names)), compare(True))
        receipt.write_bytes(b"\xff")
        self.assertEqual(["receipt (unreadable)"], compare(False))
        self.assertEqual(list(dict.fromkeys(names)), compare(True))
        receipt.write_bytes(b"")
        result = self.raw("pending-publication-status", {"evidence": str(evidence), "declared": []})
        self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(["receipt (unreadable)"], outstanding(self.project, evidence))
        record = {"schema_version": 2, "run_id": run.name, "base_head": "base",
                  "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                  "items": [{"checkpoint": "publication.integrate/main", "state": "pending"},
                            {"checkpoint": "publication.commit", "state": "observed"},
                            {"checkpoint": "publication.integrate/main", "state": "pending"}]}
        receipt.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(["publication.integrate/main", "publication.integrate/main",
                          "publication.push", "publication.pull-request/main"], compare(True))
        evidence.write_bytes(b"changed")
        self.assertEqual(["receipt (foreign or malformed)"], compare(False))
        self.assertEqual(list(dict.fromkeys(names)), compare(True))

    def test_pending_publication_reads_verify_raw_evidence_and_keep_reference_fallback(self):
        run = self.base / "run-fixture"
        run.mkdir()
        evidence = run / "preflight.json"
        receipt = run / "pending-publication.json"
        payload = {"evidence": str(evidence)}
        raw_evidence = b'{\r\n"source": "fixture"\r\n}\r\n'
        evidence.write_bytes(raw_evidence)
        record = {"schema_version": 2, "run_id": run.name,
                  "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(), "base_head": "base",
                  "items": [{"checkpoint": "publication.commit", "state": "observed"},
                            {"checkpoint": "publication.integrate/" + "x" * 200, "state": "pending"}],
                  "opaque": {"label": "한글🐈", "count": 2**64 - 1, "optional": None}}

        def compare_native():
            expected = _load_python(evidence)
            self.assertEqual({"record": expected[0], "problem": expected[1]},
                             self.check("pending-publication-read", payload))
            with patch.dict(os.environ, self.env, clear=True), patch(
                    "agent_pending_publication._load_python", side_effect=AssertionError("Python fallback")):
                self.assertEqual(expected, _load(evidence))

        compare_native()
        for changes in ({}, {"schema_version": 1}, {"schema_version": True}, {"run_id": "foreign"},
                        {"items": [{"checkpoint": "publication.integrate/" + "x" * 201, "state": "pending"}]},
                        {"items": [{"checkpoint": "publication.push", "state": "unknown"}]}):
            with self.subTest(changes=changes):
                receipt.write_text(json.dumps({**record, **changes}), encoding="utf-8")
                compare_native()
        receipt.write_bytes(b"[]")
        compare_native()
        duplicate = json.dumps(record).replace('"schema_version": 2', '"schema_version": 3, "schema_version": 2')
        receipt.write_text(duplicate, encoding="utf-8")
        compare_native()
        receipt.write_text(json.dumps(record), encoding="utf-8")
        evidence.write_bytes(evidence.read_bytes().replace(b"\r\n", b"\n"))
        compare_native()
        evidence.unlink()
        compare_native()
        receipt.write_bytes(b"\xff")
        compare_native()
        evidence.write_bytes(raw_evidence)
        for body in (b"{", json.dumps({**record, "schema_version": 1.0}).encode(),
                     json.dumps({**record, "opaque": 2**100}).encode(),
                     json.dumps({**record, "opaque": "\ud800"}).encode()):
            receipt.write_bytes(body)
            result = self.raw("pending-publication-read", payload)
            self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
            with patch.dict(os.environ, self.env, clear=True):
                self.assertEqual(_load_python(evidence), _load(evidence))
        receipt.unlink()
        os.mkfifo(receipt)
        result = self.raw("pending-publication-read", payload)
        self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))

    def test_local_delivery_prepares_exact_receipt_from_linked_worktree(self):
        repo = self.project

        def git(project, *args):
            return subprocess.run(["git", "-C", str(project), *args], check=True,
                                  capture_output=True, text=True, env=self.env, timeout=5).stdout.strip()

        git(repo, "config", "user.email", "fixture@example.invalid")
        git(repo, "config", "user.name", "Fixture")
        (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-qm", "base")
        base = git(repo, "rev-parse", "HEAD")
        work = self.base / "linked"
        git(repo, "worktree", "add", "-qb", "delivery", str(work))
        git(work, "commit", "--allow-empty", "-qm", "new HEAD")
        head = git(work, "rev-parse", "HEAD")
        alias = self.base / "linked-alias"
        alias.symlink_to(work, target_is_directory=True)
        file = work / "tracked.txt"
        items = [{"checkpoint": "publication.commit"}, {"checkpoint": "publication.integrate/main"}]

        def unexpected_git(*args):
            self.fail("native preparation fell back to the Python Git reader")

        def compare(checkpoints=items, expected_head=head, reason=""):
            with patch.dict(os.environ, self.env, clear=True):
                if reason:
                    with self.assertRaisesRegex(ValueError, reason):
                        LocalDeliveryProof.capture(alias, expected_head, "delivery", checkpoints, _git)
                    with self.assertRaisesRegex(ValueError, reason):
                        LocalDeliveryProof.capture(alias, expected_head, "delivery", checkpoints,
                                                   unexpected_git, native=True)
                else:
                    reference = LocalDeliveryProof.capture(alias, expected_head, "delivery", checkpoints, _git)
                    actual = LocalDeliveryProof.capture(alias, expected_head, "delivery", checkpoints,
                                                        unexpected_git, native=True)
                    self.assertEqual(reference, actual)
                    self.assertEqual(str(work.resolve()), actual["project"])
                    self.assertEqual(str((repo / ".git").resolve()), actual["common"])

        (work / "untracked.txt").write_text("ignored by Git diff\n", encoding="utf-8")
        compare(checkpoints=items[1:])
        git(work, "branch", "other-target", head)
        checkpoint = "publication.integrate/other-target"
        with patch.dict(os.environ, self.env, clear=True):
            proof = LocalDeliveryProof.capture(alias, head, "delivery", [{"checkpoint": checkpoint}], _git)
            record = {"base_head": head, "source_branch": "delivery", "local_delivery": proof}
            self.assertEqual((f"target other-target contains reviewed commit {head}", ""),
                             LocalDeliveryProof.observe(alias, record, checkpoint, unexpected_git, native=True))
            self.assertEqual(("", "local delivery belongs to a different repository or checkout"),
                             LocalDeliveryProof.observe(repo, record, checkpoint, unexpected_git, native=True))
        compare(reason="stage the reviewed changes")
        file.write_text("unstaged\n", encoding="utf-8")
        compare(reason="tracked worktree content")
        git(work, "add", "tracked.txt")
        compare()
        compare(checkpoints=items[1:], reason="declare a local commit")
        compare(expected_head=base, reason="HEAD changed")
        compare(checkpoints=items[:1] + [{"checkpoint": "publication.integrate/delivery"}],
                reason="valid different target branch")
        git(repo, "tag", "tag-only")
        compare(checkpoints=items[:1] + [{"checkpoint": "publication.integrate/tag-only"}],
                reason="target must already exist")
        old_blob = git(work, "rev-parse", "HEAD:tracked.txt")
        subprocess.run(["git", "-C", str(work), "update-index", "--index-info"],
                       input=f"0 {'0' * len(old_blob)}\ttracked.txt\n100644 {old_blob} 2\ttracked.txt\n",
                       text=True, check=True, capture_output=True, env=self.env, timeout=5)
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaises(ValueError) as reference:
                LocalDeliveryProof.capture(alias, head, "delivery", items, _git)
            with self.assertRaises(ValueError) as actual:
                LocalDeliveryProof.capture(alias, head, "delivery", items, _git, native=True)
            self.assertEqual(str(reference.exception), str(actual.exception))

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
        payload = {"project": str(project), "recorded_project": str(project),
                   "recorded_common": str(project / ".git"), "base": base, "source": "source", "targets": ["integration"],
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
            with patch.object(LocalDeliveryProof, "_common", side_effect=AssertionError("Python fallback")):
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
                LocalDeliveryProof, "_common", side_effect=AssertionError("Python fallback")):
            self.assertEqual((integrated, ""), _observe(project, record, {"checkpoint": args["checkpoint"]}))
            record["local_delivery"]["common"] = str(project / "foreign.git")
            self.assertEqual(("", "local delivery belongs to a different repository or checkout"),
                             _observe(project, record, {"checkpoint": args["checkpoint"]}))

    def test_native_upstream_config_preserves_remote_query_boundary(self):
        project = self.project
        payload = {"project": str(project)}
        head = "1" * 40
        reference = "refs/heads/main"
        env = {**self.env, "GIT_ALLOW_PROTOCOL": ""}

        def git(*args):
            return subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True,
                                  text=True, env=env, timeout=5)

        def config():
            response = self.raw("publication-upstream-config", payload, PATH=os.environ["PATH"])
            self.assertEqual((0, b""), (response.returncode, response.stderr), response)
            return json.loads(response.stdout)["result"]

        def read_git(path, *args):
            if args[0] == "ls-remote":
                return f"{head}\t{reference}" if remote_succeeds else None
            return _git(path, *args)

        def remote_calls(expected, calls):
            with patch.dict(os.environ, env, clear=True), patch(
                    "agent_pending_publication._git", side_effect=read_git) as reader, patch(
                    "agent_pending_publication._LOCAL_DELIVERY_GIT", reader):
                self.assertEqual(expected, _remote_head(project, head))
                self.assertEqual(calls, [call.args[1:] for call in reader.call_args_list])

        remote_succeeds = True
        absent = ("", "the branch has no configured upstream to check")
        self.assertEqual({"remote": "", "merge": ""}, config())
        remote_calls(absent, [])
        git("config", "--add", "branch.main.remote", "first")
        git("config", "--add", "branch.main.remote", " final ")
        git("config", "--add", "branch.main.merge", "refs/tags/no")
        self.assertEqual({"remote": "", "merge": ""}, config())
        remote_calls(absent, [])
        git("config", "--add", "branch.main.merge", f" {reference}\n")
        self.assertEqual({"remote": "final", "merge": reference}, config())
        with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = observe_upstream(f"{head}\t{reference}", "final", reference, head)
            failed = observe_upstream(None, "final", reference, head)
        query = ("ls-remote", "--exit-code", "final", reference)
        remote_calls(expected, [query])
        remote_succeeds = False
        remote_calls(failed, [query])
        git("config", "--replace-all", "branch.main.remote", "--upload-pack=ignored")
        declined = self.raw("publication-upstream-config", payload, PATH=os.environ["PATH"])
        self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "--allow-empty", "-m", "base")
        git("checkout", "--detach")
        self.assertEqual({"remote": "", "merge": ""}, config())
        remote_calls(absent, [])

    def test_publication_evidence_matches_existing_provider_and_upstream_checks(self):
        path = self.base / "provider-proof.json"
        head, branch, target = "1" * 40, "feature", "main"
        record = {"exists": True, "source_branch": branch, "source_commit": head, "target_branch": target,
                  "state": "OPEN"}
        payload = {"path": str(path), "branch": branch, "head": head, "target": target}

        def compare():
            expected = _observe_pull_request_python(path, branch, head, target)
            self.assertEqual({"observation": expected[0], "reason": expected[1]},
                             self.check("publication-pr-proof", payload))
            with patch.dict(os.environ, self.env, clear=True), patch(
                    "agent_publication_status._observe_pull_request_python", side_effect=AssertionError("Python fallback")):
                self.assertEqual(expected, observe_pull_request(self.project, head, target, lambda *_: branch, path))

        for change in ({}, {"state": "MERGED"}, {"exists": 1}, {"target_branch": "develop"},
                       {"source_commit": head[:7]}, {"source_branch": "other"}, {"state": "CLOSED"},
                       {"state": "open"}):
            with self.subTest(change=change):
                path.write_text(json.dumps({**record, **change}), encoding="utf-8")
                compare()
        raw = json.dumps(record).encode()
        path.write_bytes(raw.ljust(65_536, b" "))
        compare()
        path.write_bytes(raw.ljust(65_537, b" "))
        compare()
        path.write_bytes(raw + b"{}")
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(("", "the provider observation could not be read as JSON"),
                             observe_pull_request(self.project, head, target, lambda *_: branch, path))

        reference = "refs/heads/main"
        wrong = "2" * 40
        for output in (f"{head}\t{reference}", f"{wrong}\t{reference}\n{head}\trefs/heads/other", "\u2003", None):
            with self.subTest(output=output):
                request = {"listed": output or "", "remote": "origin", "merge": reference, "head": head}
                with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                    expected = observe_upstream(output, "origin", reference, head)
                self.assertEqual({"observation": expected[0], "reason": expected[1]},
                                 self.check("publication-upstream-proof", request))
                with patch.dict(os.environ, self.env, clear=True):
                    self.assertEqual(expected, observe_upstream(output, "origin", reference, head))

    def test_legacy_publication_head_matches_python_without_remote_checks(self):
        project = self.project

        def git(*args):
            return subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True,
                                  text=True, env=self.env, timeout=5).stdout.strip()

        git("config", "user.email", "fixture@example.invalid")
        git("config", "user.name", "Fixture")
        file = project / "tracked.txt"
        file.write_text("first", encoding="utf-8")
        git("add", "tracked.txt")
        git("commit", "-qm", "base")
        base = git("rev-parse", "HEAD")
        record = {"schema_version": 1, "source_branch": "main", "base_head": base, "items": []}

        def compare(checkpoint, value=record):
            with patch.dict(os.environ, self.env, clear=True):
                expected = _legacy_local_head_python(project, value, checkpoint)
                with patch("agent_pending_publication._legacy_local_head_python",
                           side_effect=AssertionError("Python fallback")):
                    self.assertEqual(expected, _legacy_local_head(project, value, checkpoint))
            return expected

        self.assertEqual((base, ""), compare("publication.push"))
        self.assertEqual(("", "HEAD has not advanced from the finished commit base"), compare("publication.commit"))
        git("commit", "--allow-empty", "-qm", "descendant with the same tree")
        head = git("rev-parse", "HEAD")
        self.assertEqual((head, ""), compare("publication.commit"))
        self.assertEqual(("", "HEAD is not the reviewed finish commit and no declared commit covers it"),
                         compare("publication.push"))
        self.assertEqual((head, ""), compare("publication.push", {
            **record, "items": [{"checkpoint": "publication.commit"}],
        }))
        file.write_text("dirty", encoding="utf-8")
        self.assertEqual(("", "tracked changes remain uncommitted"), compare("publication.commit"))
        git("add", "tracked.txt")
        self.assertEqual(("", "tracked changes remain uncommitted"), compare("publication.commit"))
        git("checkout", "--detach", "-q", head)
        self.assertEqual(("", "source branch differs from the finished publication"), compare("publication.commit"))

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
