from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_evidence_references as subject


def reference(path="/outside/project/evidence.json", content=b"proof", **changes):
    return dict(id="proof-1", path=str(path), sha256=hashlib.sha256(content).hexdigest(),
                status="unverified", summary="Focused verification result.", **changes)


def failures(value):
    result = []
    subject.validate_evidence_refs(value, "/evidence_refs", result)
    return result


class EvidenceValidationTests(unittest.TestCase):
    def test_valid_external_absolute_path_and_unicode(self):
        record = reference()
        record["path"] = "/외부/검증.json"
        with patch.object(subject.os, "open", side_effect=AssertionError("file I/O")):
            self.assertEqual([], failures([record]))
            self.assertEqual([], failures([]))

    def test_closed_record_shape_and_duplicate_ids(self):
        record = reference()
        self.assertIn({"rule": "duplicate_id", "pointer": "/evidence_refs/1/id"},
                      failures([record, record]))
        record["secret-key-name"] = "hidden"
        del record["summary"]
        errors = failures([record])
        self.assertIn({"rule": "unknown_field", "pointer": "/evidence_refs/0"}, errors)
        self.assertIn({"rule": "missing_field", "pointer": "/evidence_refs/0/summary"}, errors)
        self.assertNotIn("secret-key-name", str(errors))

    def test_list_cap_and_types(self):
        self.assertEqual("invalid_type", failures({})[0]["rule"])
        self.assertEqual("too_many_items", failures([reference()] * 5)[0]["rule"])
        self.assertEqual("invalid_type", failures([None])[0]["rule"])

    def test_paths_reject_nonlocal_unnormalized_and_secret_shapes(self):
        paths = ["relative", "/", "//host/path", "/a//b", "/a/./b", "/a/../b",
                 "/a/", "https://host/file", "/a\\b", "/a:b", "/a\x00b", "/a\u2028b",
                 "/a\u200bb", "/e\u0301", "/" + "x" * 512,
                 "/sk-" + "x" * 24, "/ghp_" + "x" * 24]
        for path in paths:
            with self.subTest(path=repr(path)):
                record = reference()
                record["path"] = path
                self.assertIn("invalid_path", [error["rule"] for error in failures([record])])
        record = reference()
        record["path"] = "/\ud800"
        self.assertIn("invalid_unicode", [error["rule"] for error in failures([record])])
        record["path"] = "/" + "x" * 511
        self.assertEqual([], failures([record]))

    def test_existing_scalar_rules_and_boundaries(self):
        cases = [("id", "x" * 41, "invalid_slug"), ("id", "bad/id", "invalid_slug"),
                 ("id", "proof\n", "invalid_slug"),
                 ("sha256", "f" * 63, "invalid_sha256"),
                 ("status", "authorized", "invalid_enum"),
                 ("summary", "x" * 161, "prose_too_long"),
                 ("summary", "sk-" + "x" * 24, "prose_secret_shaped"),
                 ("summary", "\ud800", "invalid_unicode")]
        for field, value, rule in cases:
            with self.subTest(field=field, rule=rule):
                record = reference()
                record[field] = value
                self.assertIn({"rule": rule, "pointer": "/evidence_refs/0/" + field},
                              failures([record]))
        for status in subject.EVIDENCE_REF_STATUSES:
            record = reference()
            record.update(id="x" * 40, summary="x" * 160, status=status)
            self.assertEqual([], failures([record]))


class EvidenceInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.path = self.directory / "proof.json"
        self.path.write_bytes(b"proof")

    def inspect(self, path=None, **changes):
        record = reference(path or self.path)
        record.update(changes)
        return subject.inspect_evidence_refs([record], check_files=True)[0]["freshness"]

    def test_default_has_no_file_io_and_preserves_record(self):
        record = reference(self.path)
        record["status"] = "verified"
        with patch.object(subject.os, "open", side_effect=AssertionError("open")), \
             patch.object(subject.os, "stat", side_effect=AssertionError("stat")), \
             patch.object(subject.os, "read", side_effect=AssertionError("read")):
            self.assertEqual([dict(record, freshness="unchecked")],
                             subject.inspect_evidence_refs([record]))
        self.assertNotIn("freshness", record)

    def test_match_changed_missing_and_permission_failure(self):
        self.assertEqual("match", self.inspect())
        self.assertEqual("changed", self.inspect(sha256="a" * 64))
        self.path.write_bytes(b"changed")
        self.assertEqual("changed", self.inspect())
        self.path.unlink()
        self.assertEqual("missing", self.inspect())
        with patch.object(subject, "_open_file", side_effect=PermissionError(13, "denied")):
            self.assertEqual("unreadable", self.inspect())

    def test_symlinked_final_and_parent_and_directory_refused(self):
        alias = self.directory / "alias"
        alias.symlink_to(self.path)
        self.assertEqual("unsafe", self.inspect(alias))
        parent_alias = self.directory / "alias-parent"
        parent_alias.symlink_to(self.directory, target_is_directory=True)
        self.assertEqual("unsafe", self.inspect(parent_alias / self.path.name))
        self.assertEqual("unsafe", self.inspect(self.directory))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO required")
    def test_fifo_is_nonblocking_and_never_read(self):
        fifo = self.directory / "fifo"
        os.mkfifo(fifo)
        with patch.object(subject.os, "read", side_effect=AssertionError("FIFO read")):
            self.assertEqual("unsafe", self.inspect(fifo))

    def test_oversized_file_is_not_read(self):
        with self.path.open("wb") as stream:
            stream.truncate(subject.MAX_EVIDENCE_FILE_BYTES + 1)
        with patch.object(subject.os, "read", side_effect=AssertionError("oversized read")):
            self.assertEqual("oversized", self.inspect())

    def test_change_during_hash_and_registered_path_replacement(self):
        original_read = os.read
        mutated = False

        def mutate(descriptor, count):
            nonlocal mutated
            chunk = original_read(descriptor, count)
            if not mutated:
                mutated = True
                self.path.write_bytes(b"changed while reading")
            return chunk

        with patch.object(subject.os, "read", side_effect=mutate):
            self.assertEqual("changed", self.inspect())
        self.path.write_bytes(b"proof")
        original_open = subject._open_file
        opens = 0

        def replace_path(path):
            nonlocal opens
            opens += 1
            if opens == 2:
                self.path.unlink()
                self.path.write_bytes(b"proof")
            return original_open(path)

        with patch.object(subject, "_open_file", side_effect=replace_path):
            self.assertEqual("changed", self.inspect())

    def test_invalid_path_and_unsupported_platform_fail_closed(self):
        with patch.object(subject.os, "open", side_effect=AssertionError("unsafe open")):
            self.assertEqual("unsafe", self.inspect("/a/../b"))
        with patch.object(subject.os, "name", "unsupported"):
            self.assertEqual("unsafe", self.inspect())


if __name__ == "__main__":
    unittest.main()
