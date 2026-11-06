from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_publication_admission import PublicationAdmission
from agent_publication_review_union import review_scope_for_receipt
from agent_review_attestation import ReviewAttestation, _attestation_id
import agent_publication_review_union as review_union
from tests import test_agent_review_attestation as attestation_tests


class PublicationReviewUnionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = attestation_tests.ReviewAttestationTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.project = self.fixture.project
        self.rules = self.project / ".moru" / "review-rules"
        self.rules.mkdir()
        attestation_tests.initialize_repository(self.rules)
        self.fixture.route = {
            "command": "commit",
            "gates": ["review hook"],
            "request_classification": {"intent_envelope": {
                "authority": "envelope", "schema_valid": True, "failures": [],
                "effective_effect": "external_write",
            }},
        }
        self.new_evidence("a" * 32)

    def git(self, *args):
        return self.fixture._git(*args)

    def new_evidence(self, run_id):
        self.evidence = self.fixture._write_preflight(run_id)
        payload = json.loads(self.evidence.read_text())
        payload["rules"] = str(self.rules)
        self.evidence.write_text(json.dumps(payload))

    def stage(self, files):
        for name, content in files.items():
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content if isinstance(content, bytes) else content.encode())
        self.git("add", "--", *files)

    def review(self, paths):
        changed = self.git("diff", "--cached", "--name-only", "--no-renames", "--", *paths).splitlines()
        return ReviewAttestation.record(
            project=self.project, rules=self.rules, evidence_path=self.evidence,
            preflight=json.loads(self.evidence.read_text()),
            review_scope="pathspec: " + ", ".join(paths), review_paths=paths,
            changed_path_count=len(changed),
            checks={
                "review_outcome": "pass", "workflow_validate": {"returncode": 0},
                "diff_check": {"returncode": 0},
                "vibeguard": {"returncode": 0, "overall": "Ready"},
            },
        )

    def union(self):
        return review_scope_for_receipt(
            self.project, self.evidence, hashlib.sha256(self.evidence.read_bytes()).hexdigest(),
        )

    def finish(self):
        return PublicationAdmission.record_finish(self.project, self.evidence)

    def assert_incomplete(self):
        with self.assertRaisesRegex(ValueError, "^scoped review coverage is incomplete$"):
            self.union()
        self.assertFalse(self.finish())
        self.assertFalse(PublicationAdmission.allows(self.project, self.evidence, "git_write"))

    def two_reviews(self):
        self.stage({"first.kt": "first\n", "second.kt": "second\n"})
        return self.review(["first.kt"]), self.review(["second.kt"])

    def replace_archive(self, record, field, value, *, resign=True):
        archive = ReviewAttestation.archive_dir(self.evidence)
        path = archive / (record["attestation_id"] + ".json")
        payload = json.loads(path.read_text())
        payload[field] = value
        if resign:
            payload["attestation_id"] = _attestation_id(payload)
        path.unlink()
        (archive / (payload["attestation_id"] + ".json")).write_text(json.dumps(payload))

    def assert_capture_race_rejected(self, *, during_union):
        capture = review_union.scoped_review_binding
        for entrypoint in ("union", "finish"):
            self.new_evidence(hashlib.sha256(f"{during_union}:{entrypoint}".encode()).hexdigest()[:32])
            self.two_reviews()
            injected = False

            def raced(project, paths, **kwargs):
                nonlocal injected
                if not injected and not during_union and paths == ["first.kt"]:
                    injected = True
                    self.stage({"first.kt": "changed after canonical freshness\n"})
                result = capture(project, paths, **kwargs)
                if not injected and during_union and set(paths) == {"first.kt", "second.kt"}:
                    injected = True
                    self.stage({"first.kt": "changed during union capture\n"})
                return result

            with patch.object(review_union, "scoped_review_binding", side_effect=raced):
                if entrypoint == "union":
                    with self.assertRaises(ValueError):
                        self.union()
                else:
                    self.assertFalse(self.finish())
            self.assertTrue(injected)
            self.assertFalse(PublicationAdmission.allows(self.project, self.evidence, "git_write"))

    def test_component_binding_race_after_canonical_freshness_is_rejected(self):
        self.assert_capture_race_rejected(during_union=False)

    def test_mutation_while_capturing_union_is_rejected(self):
        self.assert_capture_race_rejected(during_union=True)

    def test_review_required_without_any_review_evidence_cannot_finish(self):
        self.stage({"first.kt": "first\n", "second.kt": "second\n"})
        self.assert_incomplete()

    def test_two_through_many_bounded_reviews_cover_one_staged_unit(self):
        self.stage({f"source/{index}.kt": f"source {index}\n" for index in range(6)})
        for count in (2, 3, 6):
            with self.subTest(scopes=count):
                self.new_evidence(f"{count:032x}")
                records = [self.review([f"source/{index}.kt" for index in range(part, 6, count)])
                           for part in range(count)]
                scope = self.union()
                self.assertEqual(self.git("diff", "--cached", "--name-only").splitlines(),
                                 scope["inputs"]["changed_paths"])
                self.assertEqual({record["attestation_id"] for record in records},
                                 set(scope["attestation_ids"]))
                self.assertEqual(count, len(list(ReviewAttestation.archive_dir(self.evidence).glob("*.json"))))
                self.assertTrue(self.finish())
                self.assertTrue(PublicationAdmission.allows(self.project, self.evidence, "git_write"))

    def test_doc_and_schema_need_explicit_coverage_beyond_all_code_scopes(self):
        self.two_reviews()
        self.stage({"Doc/contract.md": "contract\n", "schema/receipt.json": '{"version":1}\n'})
        self.assert_incomplete()
        artifact = self.review(["Doc/contract.md", "schema/receipt.json"])
        self.assertIn(artifact["attestation_id"], self.union()["attestation_ids"])
        self.assertTrue(self.finish())
        receipt = json.loads(self.evidence.with_name("publication.json").read_text())
        self.assertEqual(self.git("diff", "--cached", "--name-only").splitlines(),
                         receipt["project_scope"]["inputs"]["changed_paths"])

    def test_final_two_path_review_does_not_erase_the_other_138_reviewed_paths(self):
        self.stage({f"source/{index:03d}.kt": f"source {index}\n" for index in range(140)})
        for start in range(0, 138, 23):
            self.review([f"source/{index:03d}.kt" for index in range(start, start + 23)])
        final = self.review(["source/138.kt", "source/139.kt"])
        self.assertEqual(2, final["changed_path_count"])
        self.assertEqual(140, len(self.union()["inputs"]["changed_paths"]))
        self.assertEqual(7, len(self.union()["attestation_ids"]))
        self.assertTrue(self.finish())
        self.assertTrue(PublicationAdmission.allows(self.project, self.evidence, "git_write"))

    def test_mutated_staged_scope_requires_a_fresh_review_of_that_scope(self):
        old, unchanged = self.two_reviews()
        self.stage({"first.kt": "new first\n"})
        self.assert_incomplete()
        fresh = self.review(["first.kt"])
        ids = self.union()["attestation_ids"]
        self.assertIn(fresh["attestation_id"], ids)
        self.assertIn(unchanged["attestation_id"], ids)
        self.assertNotIn(old["attestation_id"], ids)
        self.assertTrue(self.finish())

    def test_source_drift_with_unchanged_index_is_not_review_coverage(self):
        self.two_reviews()
        (self.project / "first.kt").write_text("unstaged edit\n")
        self.assert_incomplete()

    def test_index_drift_with_restored_reviewed_worktree_is_not_coverage(self):
        self.two_reviews()
        self.stage({"first.kt": "different staged bytes\n"})
        (self.project / "first.kt").write_text("first\n")
        self.assert_incomplete()

    def test_tampered_archive_cannot_complete_the_union(self):
        first, _ = self.two_reviews()
        self.replace_archive(first, "changed_path_count", 123, resign=False)
        with self.assertRaises(ValueError):
            self.union()
        self.assertFalse(self.finish())

    def test_empty_and_non_object_latest_records_never_fall_back_to_whole_tree(self):
        for payload in ({}, [], None, "not an attestation"):
            with self.subTest(payload=payload):
                self.new_evidence(hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:32])
                self.two_reviews()
                ReviewAttestation.path(self.evidence).write_text(json.dumps(payload))
                self.assertFalse(self.finish())
                self.assertFalse(PublicationAdmission.allows(self.project, self.evidence, "git_write"))

    def test_pathspec_without_scoped_input_proof_is_not_a_whole_tree_review(self):
        archive = ReviewAttestation.archive_dir(self.evidence)
        for record in self.two_reviews():
            original = archive / (record["attestation_id"] + ".json")
            payload = json.loads(original.read_text())
            payload.pop("project_inputs")
            payload["attestation_id"] = _attestation_id(payload)
            original.unlink()
            (archive / (payload["attestation_id"] + ".json")).write_text(json.dumps(payload))
            ReviewAttestation.path(self.evidence).write_text(json.dumps(payload))
        self.assertFalse(self.finish())
        self.assertFalse(PublicationAdmission.allows(self.project, self.evidence, "git_write"))

    def test_well_formed_foreign_run_route_and_preflight_records_are_not_coverage(self):
        for field, value in (("agent_run_id", "foreign-run"),
                             ("route_fingerprint", "0" * 64),
                             ("preflight_evidence", {"path": "runs/foreign/preflight.json", "sha256": "0" * 64})):
            with self.subTest(field=field):
                self.new_evidence(hashlib.sha256(field.encode()).hexdigest()[:32])
                first, _ = self.two_reviews()
                self.replace_archive(first, field, value)
                self.assert_incomplete()

    def test_preflight_changed_after_review_does_not_rebind_old_archives(self):
        self.two_reviews()
        payload = json.loads(self.evidence.read_text())
        payload["request_fingerprint"] = "new request"
        self.evidence.write_text(json.dumps(payload))
        self.assert_incomplete()

    def test_rules_changes_invalidate_every_scope_until_rereview(self):
        self.two_reviews()
        (self.rules / "tracked.txt").write_text("new acceptance rules\n")
        self.assert_incomplete()
        self.review(["first.kt"])
        self.assert_incomplete()
        self.review(["second.kt"])
        self.assertTrue(self.finish())

    def test_overlapping_directory_scopes_use_expanded_changed_paths(self):
        self.stage({"feature/first.kt": "first\n", "feature/second.kt": "second\n",
                    "Doc/contract.md": "contract\n"})
        directory = self.review(["feature"])
        overlap = self.review(["feature/first.kt", "Doc/contract.md"])
        scope = self.union()
        self.assertEqual({directory["attestation_id"], overlap["attestation_id"]}, set(scope["attestation_ids"]))
        self.assertEqual(["Doc/contract.md", "feature/first.kt", "feature/second.kt"],
                         scope["inputs"]["changed_paths"])
        self.assertTrue(self.finish())

    def test_deletion_rename_and_binary_bytes_are_all_attested(self):
        self.stage({"old.kt": "rename me\n", "deleted.kt": "delete me\n", "blob.bin": b"\x00before\xff"})
        self.git("commit", "-qm", "base fixtures")
        (self.project / "old.kt").rename(self.project / "renamed.kt")
        (self.project / "deleted.kt").unlink()
        (self.project / "blob.bin").write_bytes(b"\x00after\xff")
        self.git("add", "-A")
        self.review(["old.kt", "renamed.kt"])
        self.review(["deleted.kt", "blob.bin"])
        self.assertEqual(["blob.bin", "deleted.kt", "old.kt", "renamed.kt"],
                         self.union()["inputs"]["changed_paths"])
        self.assertTrue(self.finish())
        (self.project / "blob.bin").write_bytes(b"\x00changed again\xff")
        self.assertFalse(PublicationAdmission.allows(self.project, self.evidence, "git_write"))

    def test_exact_committed_union_keeps_local_continuation_but_push_stays_whole_tree(self):
        self.two_reviews()
        self.assertTrue(self.finish())
        self.git("commit", "-qm", "reviewed union")
        self.assertTrue(PublicationAdmission.allows(self.project, self.evidence, "git_write"))
        self.assertTrue(PublicationAdmission.allows(self.project, self.evidence, "external_write"))
        (self.project / "unrelated.kt").write_text("another task\n")
        self.assertTrue(PublicationAdmission.allows(self.project, self.evidence, "git_write"))
        self.assertFalse(PublicationAdmission.allows(self.project, self.evidence, "external_write"))
        self.git("add", "unrelated.kt")
        self.assertFalse(PublicationAdmission.allows(self.project, self.evidence, "git_write"))


if __name__ == "__main__":
    unittest.main()
