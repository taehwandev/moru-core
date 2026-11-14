"""Observe exact consolidation groups, source normalization and report authority."""
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from unittest.mock import patch

import agent_project_memory as memory
import agent_project_memory_consolidate as source
from native_pretool_support import environment, prepare
from support.native_memory_consolidation import NativeMemoryConsolidation


class NativeMemoryConsolidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-memory-consolidation-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        empty = self.base / "empty"
        empty.mkdir()
        self.env = {**environment(self.base), "PATH": str(empty)}

    def record(self, id, body="a b c d", scope="task", source="docs/Guide.md", **fields):
        return {"id": id, "body": body, "scope": scope, "source": source,
                "status": "active", "review_on": "2099-01-01", **fields}

    def groups(self, records, operation="duplicate", backend="auto", required=False):
        name = "_duplicate_groups" if operation == "duplicate" else "_shared_source_groups"
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": backend}, clear=True):
            if required:
                with patch.object(source, name + "_reference", side_effect=AssertionError("Python grouping replay")):
                    return getattr(source, name)(records)
            return getattr(source, name)(records)

    def parity(self, records, operation="duplicate"):
        expected = self.groups(records, operation, "python")
        actual = self.groups(records, operation, required=True)
        self.assertEqual(expected, actual)
        return actual

    def test_exact_threshold_and_below_are_not_greedy_similarity(self):
        records = [self.record("a"), self.record("b", "a b c d e"), self.record("c", "a b c x y")]
        self.assertEqual([["a", "b"]], [g["ids"] for g in self.parity(records)])

    def test_pre_edit_projection_values_reasons_and_key_order(self):
        # Captured from the unchanged source before extracting the references.
        records = [self.record(name, source="Docs!") for name in ("b", "a")]
        projected = [{"id":name,"scope":"task","body":"a b c d","source":"Docs!",
                      "review_on":"2099-01-01"} for name in ("a", "b")]
        reasons = {"duplicate":"bodies share at least 80% of their words in overlapping scopes; "
                                "merge with `capture --replaces <one>`, then retire the others",
                   "source":"records cite the same source; open it and keep, merge or retire the ones that disagree"}
        for mode, reason in reasons.items():
            expected = [{"ids":["a","b"],"reason":reason,"records":projected}]
            actual = self.groups(records, mode, required=True)
            self.assertEqual(expected, actual)
            self.assertEqual(list(expected[0]), list(actual[0]))
            self.assertEqual([list(row) for row in projected], [list(row) for row in actual[0]["records"]])

    def test_reordered_groups_and_equal_id_ties_defer(self):
        records = [self.record("a"), self.record("b"), self.record("c"), self.record("d")]
        for groups in ([[1,0]], [[2,3],[0,1]]):
            with patch("support.native_memory_consolidation.NativeProbe.request", return_value={"groups":groups}):
                self.assertIsNone(NativeMemoryConsolidation.groups("duplicate-groups", records, source._tokens))
        tied = [self.record("x") for _ in range(4)]
        for groups in ([[1,0]], [[2,3],[0,1]]):
            with patch("support.native_memory_consolidation.NativeProbe.request", return_value={"groups":groups}):
                self.assertIsNone(NativeMemoryConsolidation.groups("duplicate-groups", tied, source._tokens))
        with patch("support.native_memory_consolidation.NativeProbe.request", return_value={"groups":[[0,2],[1,3]]}):
            selected = NativeMemoryConsolidation.groups("duplicate-groups", tied, source._tokens)
        self.assertIs(tied[2], selected[0][1])

    def test_transitive_chain_and_all_scope_bridge_connect_endpoints(self):
        records = [self.record("c", "a b c d e f", "review"), self.record("a", "a b c d", "task"),
                   self.record("b", "a b c d e", "all")]
        self.assertLess(source._jaccard(source._tokens(records[0]["body"]), source._tokens(records[1]["body"])), 0.8)
        self.assertEqual([["a", "b", "c"]], [g["ids"] for g in self.parity(records)])
        records[2]["scope"] = "task"
        self.assertEqual([["a", "b"]], [g["ids"] for g in self.parity(records)])

    def test_empty_repeated_tokens_and_distinct_scopes_keep_original_decisions(self):
        self.assertEqual([], self.parity([self.record("a", "!!!"), self.record("b", "???")]))
        self.assertEqual([], self.parity([self.record("a", scope="task"), self.record("b", scope="review")]))
        self.assertEqual([["a", "b"]], [g["ids"] for g in self.parity([
            self.record("b", "a b a b c d"), self.record("a")])])

    def test_original_unicode_lower_punctuation_and_whitespace_are_preserved(self):
        for left, right in (("ABC_DEF, 한글\u00a0é", "abc_def 한글 é"), ("ΟΣ", "ος"),
                            ("Straße", "STRASSE"), ("é", "é"), ("İ", "i"), ("\x1ca\tb", "a b")):
            self.parity([self.record("a", left), self.record("b", right)])
            self.parity([self.record("a", source=left), self.record("b", source=right)], "source")

    def test_seeded_unsorted_components_match_original_algorithm(self):
        rng = random.Random(261112)
        for _ in range(24):
            records = [self.record(str(rng.randrange(5)),
                " ".join(rng.sample(list("abcdef"), rng.randrange(7))),
                rng.choice(["task", "review", "all"]), source=rng.choice(["a", "B!", "b", ""]))
                for _ in range(rng.randrange(9))]
            self.parity(records)
            self.parity(records, "source")

    def test_duplicate_id_ties_and_groups_retain_stable_original_values(self):
        marker = object()
        records = [self.record("x", "one", source="z", applies_when=marker),
                   self.record("x", "two", source="a", applies_when="\ud800"),
                   self.record("x", "one", source="z", applies_when=2**100),
                   self.record("x", "two", source="a", not_when=marker)]
        for mode in ("duplicate", "source"):
            groups = self.parity(records, mode)
            self.assertIs(marker, groups[0]["records"][0]["applies_when"])
            self.assertIs(marker, groups[1]["records"][1]["not_when"])

    def test_empty_sources_group_across_scopes_and_output_is_id_sorted(self):
        records = [self.record("z", source=""), self.record("b", scope="review", source="!!!"),
                   self.record("a", source="DOCS/guide.md "), self.record("c", source="docs/Guide.md")]
        self.assertEqual([["a", "c"], ["b", "z"]], [g["ids"] for g in self.parity(records, "source")])

    def test_empty_helpers_keep_no_probe_fast_path(self):
        with patch("support.native_memory_consolidation.NativeProbe.request", side_effect=AssertionError("transport")):
            self.assertEqual([], source._duplicate_groups([]))
            self.assertEqual([], source._shared_source_groups([]))

    def test_actual_grouping_wiring_has_negative_controls(self):
        records = [self.record("a"), self.record("b")]
        with patch.object(source, "_jaccard", side_effect=AssertionError("Python pair replay")), \
             patch.object(source, "_scopes_overlap", side_effect=AssertionError("Python scope replay")):
            self.groups(records, required=True)
        for mode in ("duplicate", "source"):
            with patch.object(NativeMemoryConsolidation, "groups", return_value=None):
                with self.assertRaisesRegex(AssertionError, "Python grouping replay"):
                    self.groups(records, mode, required=True)

    def test_malformed_and_custom_profiles_preserve_original_errors(self):
        class Custom(str):
            def lower(self):
                raise RuntimeError("custom lower")
        for records, mode in (([{}], "duplicate"), ([self.record("a", body=None)], "duplicate"),
                              ([self.record("a", body=Custom("a"))], "duplicate"),
                              ([self.record("a", source=Custom("a"))], "source")):
            with patch("support.native_memory_consolidation.NativeProbe.request", side_effect=AssertionError("transport")):
                try:
                    expected = self.groups(records, mode, "python")
                except Exception as error:
                    with self.assertRaises(type(error)) as actual:
                        self.groups(records, mode)
                    self.assertEqual(error.args, actual.exception.args)
                else:
                    self.assertEqual(expected, self.groups(records, mode))
        with patch.object(source, "DUPLICATE_JACCARD", 0.5), \
             patch("support.native_memory_consolidation.NativeProbe.request", side_effect=AssertionError("transport")):
            self.assertEqual(self.groups([self.record("a"), self.record("b", "a b")], backend="python"),
                             self.groups([self.record("a"), self.record("b", "a b")]))

    def test_malformed_packets_and_unavailable_transport_defer(self):
        records = [self.record("a"), self.record("b")]
        for result in (None, {}, {"groups": None}, {"groups": [[True, 1]]}, {"groups": [[0]]},
                       {"groups": [[-1, 1]]}, {"groups": [[0, 2]]}, {"groups": [[0, 0]]},
                       {"groups": [[0, 1], [0, 1]]}, {"groups": [], "extra": 1}):
            with patch("support.native_memory_consolidation.NativeProbe.request", return_value=result):
                self.assertIsNone(NativeMemoryConsolidation.groups("duplicate-groups", records, source._tokens))
        for error in (OSError("transport"), ValueError("transport"), RuntimeError("transport")):
            with patch("support.native_memory_consolidation.NativeProbe.request", side_effect=error):
                self.assertIsNone(NativeMemoryConsolidation.groups("shared-source-groups", records, source.normalize))

    def test_findings_preserves_dates_reasons_and_retired_record_exclusion(self):
        records = [self.record("a", review_on="2026-11-12"), self.record("b", status="pending"),
                   self.record("c", status="approved", review_on="2026-11-26", replaces="a"),
                   self.record("d", status="retired", review_on="2020-01-01")]
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = source.findings(records, 2, today=date(2026, 11, 12))
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(source, "_duplicate_groups_reference", side_effect=AssertionError("Python grouping replay")), \
             patch.object(source, "_shared_source_groups_reference", side_effect=AssertionError("Python grouping replay")):
            self.assertEqual(expected, source.findings(records, 2, today=date(2026, 11, 12)))
        self.assertEqual(["a"], [r["id"] for r in expected["expired"]])
        self.assertEqual(["c"], [r["id"] for r in expected["expiring"]])
        self.assertEqual(["c"], expected["unfinished_replacements"][0]["replaced_by"])

    def test_real_store_cli_is_read_only_and_requires_native_grouping(self):
        directory = self.base / "records"
        directory.mkdir()
        records = [self.record("a" * 16, schema_version=1), self.record("b" * 16, schema_version=1)]
        for record in records:
            record["digest"] = memory._digest(record)
            path = directory / (record["id"] + ".json")
            path.write_text(json.dumps(record), encoding="utf-8")
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            for path in directory.iterdir():
                self.assertIsNotNone(memory.read_record(path), "fixture must satisfy original record schema")
            expected = source.findings(records, 0, today=date.today())
        with patch.dict(os.environ, self.env, clear=True), patch.object(memory, "store_dir", return_value=directory), \
             patch.object(source, "_duplicate_groups_reference", side_effect=AssertionError("Python grouping replay")), \
             patch.object(source, "_shared_source_groups_reference", side_effect=AssertionError("Python grouping replay")):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, memory._main(["--project", str(self.project), "consolidate"]))
            self.assertEqual(expected, json.loads(output.getvalue()))
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})
