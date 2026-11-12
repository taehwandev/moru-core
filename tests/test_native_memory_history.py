"""Native replacement chains match original history and preserve store admission."""
import copy
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import agent_project_memory as source
from native_pretool_support import environment, prepare
from support.native_memory_history import NativeMemoryHistory


class NativeMemoryHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-memory-history-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        empty = self.base / "empty"
        empty.mkdir()
        self.env = {**environment(self.base), "PATH": str(empty)}

    def record(self, id, **fields):
        return {"id":id,"body":"body " + id,"source":"checked source","status":"active",**fields}

    def caller(self, id, records, backend="auto", native_required=False):
        with patch.dict(os.environ, {**self.env,"MORU_LAUNCHER_BACKEND":backend}, clear=True), \
             patch.object(source, "_existing"), patch.object(source, "scan_records", return_value=(records, 0)):
            if native_required:
                with patch.object(source, "_history_reference", side_effect=AssertionError("Python traversal replay")):
                    return source._history(self.project, id)
            return source._history(self.project, id)

    def parity(self, records, id):
        before = copy.deepcopy(records)
        expected = self.caller(id, records, "python")
        actual = self.caller(id, records, native_required=True)
        self.assertEqual(expected, actual)
        self.assertEqual(records, before)
        return actual

    def test_whole_chain_from_any_member_and_missing_predecessor(self):
        records = [self.record("a"), self.record("b", replaces="a"), self.record("c", replaces="b")]
        for id in ("a", "b", "c"):
            self.assertEqual(["c", "b", "a"], [r["id"] for r in self.parity(records, id)])
        self.assertEqual(["c", "b"], [r["id"] for r in self.parity(records[1:], "b")])

    def test_explicit_next_wins_even_when_dangling_and_forks_keep_input_order(self):
        records = [self.record("a", replaced_by="missing"), self.record("b", replaces="a")]
        self.assertEqual(["a"], [r["id"] for r in self.parity(records, "a")])
        records[0]["replaced_by"] = ""
        records.append(self.record("c", replaces="a"))
        self.assertEqual(["c", "a"], [r["id"] for r in self.parity(records, "a")])

    def test_duplicate_ids_use_last_row_but_first_dictionary_position(self):
        records = [self.record("a"), self.record("b", replaces="missing"),
                   self.record("c", replaces="a"), self.record("b", replaces="a")]
        self.assertEqual(["c", "a"], [r["id"] for r in self.parity(records, "a")])
        self.assertEqual("body b", self.parity(records, "b")[0]["body"])

    def test_cycles_terminate_and_chain_is_capped_at_twenty(self):
        self.parity([self.record("a", replaces="b", replaced_by="b"),
                     self.record("b", replaces="a", replaced_by="a")], "a")
        records = [self.record(str(i), replaces=str(i-1) if i else None) for i in range(30)]
        self.assertEqual([str(i) for i in range(29, 9, -1)], [r["id"] for r in self.parity(records, "0")])

    def test_seeded_link_graphs_match_the_original_walk(self):
        rng = random.Random(920611)
        for _ in range(40):
            records = [self.record(str(i), replaces=rng.choice([None, "", "missing", *map(str, range(8))]),
                                   replaced_by=rng.choice([None, "", "missing", *map(str, range(8))]))
                       for i in range(8)]
            if rng.randrange(2):
                records.append({**rng.choice(records), "body":"final duplicate"})
            self.parity(records, str(rng.randrange(8)))

    def test_indices_preserve_record_objects_and_unserialized_projection_metadata(self):
        marker = object()
        body = ["legacy field", 2**100]
        records = [self.record("a", created_at=marker, body=body, retired_at=float("inf"),
                               unused="\ud800"), self.record("b", replaces="a")]
        with patch.dict(os.environ, self.env, clear=True):
            selected = NativeMemoryHistory.select("a", records)
        self.assertIs(selected[0], records[1])
        self.assertIs(selected[1], records[0])
        result = self.caller("a", records, native_required=True)
        self.assertIs(result[1]["created_at"], marker)
        self.assertIs(result[1]["body"], body)
        self.assertNotIn("unused", result[1])

    def test_projection_matches_the_original_baseline_field_values_and_order(self):
        # Captured from the original _history before extracting its projection.
        records = [self.record("A", status="retired", body="old", source="source-A",
                               created_at="old-time", retired_at=None, replaces=None,
                               applies_when="old condition", not_when="old exception", scope="task", unused=True),
                   self.record("B", body="new", source="source-B", created_at="new-time", replaces="A",
                               applies_when="new condition", not_when="")]
        expected = [{"id":"B","status":"active","body":"new","source":"source-B",
                     "created_at":"new-time","replaces":"A","applies_when":"new condition","not_when":""},
                    {"id":"A","status":"retired","body":"old","source":"source-A","created_at":"old-time",
                     "retired_at":None,"replaces":None,"applies_when":"old condition","not_when":"old exception"}]
        for backend in ("python", "auto"):
            result = self.caller("A", records, backend, native_required=backend == "auto")
            self.assertEqual(expected, result)
            self.assertEqual([list(row) for row in expected], [list(row) for row in result])

    def test_actual_caller_wiring_has_a_negative_control(self):
        records = [self.record("a")]
        self.assertEqual([{"id":"a","status":"active","body":"body a","source":"checked source"}],
                         self.caller("a", records, native_required=True))
        with patch.object(NativeMemoryHistory, "select", return_value=None):
            with self.assertRaisesRegex(AssertionError, "Python traversal replay"):
                self.caller("a", records, native_required=True)

    def test_existing_record_failure_and_scan_race_keep_original_errors(self):
        with patch.object(source, "_existing", side_effect=ValueError("memory record is missing or invalid")), \
             patch.object(source, "scan_records", side_effect=AssertionError("scan")):
            with self.assertRaisesRegex(ValueError, "missing or invalid"):
                source._history(self.project, "a")
        for records in ([], [self.record("other")]):
            with self.assertRaises(KeyError) as expected:
                self.caller("a", records, "python")
            with self.assertRaises(KeyError) as actual:
                self.caller("a", records)
            self.assertEqual(expected.exception.args, actual.exception.args)

    def test_empty_scan_preserves_key_error_without_native_transport(self):
        with patch("support.native_memory_history.NativeProbe.request", side_effect=AssertionError("empty scan RPC")):
            with self.assertRaises(KeyError) as error:
                self.caller("a", [])
        self.assertEqual(("a",), error.exception.args)

    def test_custom_link_types_defer_and_keep_source_exceptions(self):
        for fields in ({"replaces":[]}, {"replaces":False}, {"replaced_by":{}},
                       {"replaces":["a"]}, {"replaced_by":["a"]}):
            records = [self.record("a", **fields)]
            with patch.dict(os.environ, self.env, clear=True):
                self.assertIsNone(NativeMemoryHistory.select("a", records))
            try:
                expected = self.caller("a", records, "python")
            except Exception as error:
                with self.assertRaises(type(error)):
                    self.caller("a", records)
            else:
                self.assertEqual(expected, self.caller("a", records))

    def test_malformed_packets_and_unavailable_transport_defer(self):
        records = [self.record("a")]
        for value in (None, {}, {"indices":[]}, {"indices":[True]}, {"indices":[-1]},
                      {"indices":[1]}, {"indices":[0,0]}, {"indices":[0],"extra":1}):
            with patch("support.native_memory_history.NativeProbe.request", return_value=value):
                self.assertIsNone(NativeMemoryHistory.select("a", records))
        for error in (OSError("transport"), ValueError("transport"), RuntimeError("transport")):
            with patch("support.native_memory_history.NativeProbe.request", side_effect=error):
                self.assertIsNone(NativeMemoryHistory.select("a", records))
        with patch("support.native_memory_history.NativeProbe.request", return_value={"indices":[0,1]}):
            self.assertIsNone(NativeMemoryHistory.select("a", [self.record("a"), self.record("a")]))

    def test_real_store_cli_history_is_read_only_and_uses_native_traversal(self):
        directory = self.base / "records"
        directory.mkdir()
        records = [self.record(char*16, schema_version=1, scope="task", review_on="2099-01-01",
                               replaces=previous*16 if previous else None)
                   for char, previous in (("a", ""), ("b", "a"), ("c", "b"))]
        for record in records:
            record["digest"] = source._digest(record)
            (directory/(record["id"]+".json")).write_text(json.dumps(record), encoding="utf-8")
        before = {p.name:p.read_bytes() for p in directory.iterdir()}
        with patch.dict(os.environ, self.env, clear=True), patch.object(source, "store_dir", return_value=directory), \
             patch.object(source, "_history_reference", side_effect=AssertionError("Python traversal replay")):
            for record in records:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(0, source._main(["--project", str(self.project), "history", record["id"]]))
                self.assertEqual(["c"*16,"b"*16,"a"*16], [r["id"] for r in json.loads(output.getvalue())])
        self.assertEqual(before, {p.name:p.read_bytes() for p in directory.iterdir()})
