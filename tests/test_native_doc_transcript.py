"""Source parity for native doc-delivery file scans and read-only boundaries."""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

import agent_required_doc_delivery as reference
import agent_required_doc_reuse as reuse_reference
import agent_runtime_session
import agy_hook_adapter as adapter
import agy_required_docs_hook as agy
import test_agent_required_doc_delivery as delivery_fixtures
import test_agent_required_doc_reuse as reuse_fixtures
import test_agy_required_docs_hook as agy_fixtures
from native_pretool_support import environment, prepare, result
from support.agy_setup import _agy_hooks_spec
from support.native_doc_transcript import (
    NativeDocTranscript, agy_delivery_preparation, agy_delivery_request, agy_delivery_stdout, agy_redelivery,
    agy_skill_read_note,
    nearest_registry_project, read_delivery_manifest,
    reuse_credit,
    discover_reuse_roots, rank_reuse_roots, reuse_current, reuse_matches, reuse_run_ids,
)


class NativeDocTranscriptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-doc-transcript-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.empty = self.base / "empty-path"
        self.empty.mkdir()
        self.env = {**environment(self.base), "PATH": str(self.empty)}
        self.path = self.base / "synthetic-transcript.jsonl"

    def raw(self, operation, payload=None, **env):
        return subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry),
            "--doc-transcript-probe", operation], input=json.dumps(payload or {"path":str(self.path)}).encode(),
            capture_output=True, cwd=self.project, env={**self.env, **env}, timeout=8)

    def native(self, name, *args):
        with patch.dict(os.environ, self.env, clear=True):
            return getattr(NativeDocTranscript, name)(*args)

    def original(self, name, *args):
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND":"python"}, clear=True):
            return getattr(reference, "_" + name)(*args)

    def parity(self, raw, fallback=0, offset=0, count=0, limit=3):
        self.path.write_bytes(raw)
        state = {"transcript_bytes":offset, "redeliveries":count}
        before = self.path.read_bytes()
        calls = (("compacted", "compacted_before", (self.path,)),
                 ("aligned", "aligned_size", (self.path,fallback)),
                 ("due", "due_after_compaction", (state,self.path,limit)))
        for native, source, args in calls:
            with self.subTest(operation=native, raw=raw[:60], offset=offset):
                expected = self.original(source, *args)
                actual = self.native(native, *args)
                self.assertIsNotNone(actual)
                self.assertEqual(expected,actual)
                self.assertIs(type(expected),type(actual))
        self.assertEqual(before,self.path.read_bytes())

    def test_agy_prompt_compaction_count_preserves_python_filter_and_fallback(self):
        checkpoint = b'{"type":"CHECKPOINT","content":"# Resuming from a compaction summary"}'
        escaped = checkpoint.replace(b'CHECKPOINT', br'\u0043HECKPOINT')
        duplicate = checkpoint.replace(b'"type":', b'"type":"old","type":')
        other_runtime = b'{"type":"compacted","tag":"CHECKPOINT","ignored": NaN}'
        malformed = b'{"type":"CHECKPOINT","content":'
        rows = [b'\xef\xbb\xbf' + checkpoint, escaped, duplicate, other_runtime,
                malformed, b'["CHECKPOINT"]', checkpoint]
        self.path.write_bytes(b'\r\n'.join(rows[:3]) + b'\r' + b'\n'.join(rows[3:]))
        payload = {"transcriptPath": str(self.path)}
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            self.assertEqual(3, adapter._compaction_count(payload))
        with patch.dict(os.environ, self.env, clear=True), patch.object(adapter, "parse_json") as parse:
            self.assertEqual(3, adapter._compaction_count(payload))
            parse.assert_not_called()

        digits = checkpoint[:-1] + b',"ignored":' + b'1' * 641 + b'}'
        self.path.write_bytes(digits)
        for limit, expected in ((0, 1), (640, 0)):
            with self.subTest(limit=limit):
                probe = self.raw("agy-compaction-count", {"path": str(self.path), "digit_limit": limit})
                self.assertEqual(0, probe.returncode, probe.stderr)
                self.assertEqual(expected, json.loads(probe.stdout)["result"]["value"])

        self.path.write_bytes(checkpoint.replace(b'summary', b'\xffsummary'))
        self.assertIsNone(self.native("agy_compaction_count", self.path))
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(1, adapter._compaction_count(payload))
        with self.path.open("wb") as stream:
            stream.write(checkpoint + b'\n')
            stream.truncate(16 * 1024 * 1024 + 1)
        self.assertIsNone(self.native("agy_compaction_count", self.path))
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(1, adapter._compaction_count(payload))

    def test_agy_native_request_preserves_defaults_order_and_legacy_fallback(self):
        with patch.dict(os.environ, self.env, clear=True):
            for raw, expected in (
                ("", ("", [], "")),
                ("[]", ("", [], "")),
                ('{"conversationId":null,"workspacePaths":null}', ("", [], "")),
                ('{"conversationId":"old","conversationId":"새","workspacePaths":["둘","첫","둘"]}',
                 ("새", ["둘", "첫", "둘"], "")),
                ('{"workspacePaths":["path"],"transcriptPath":1}', ("", ["path"], "")),
            ):
                with self.subTest(raw=raw):
                    self.assertEqual(expected, agy_delivery_request(raw=raw))
            for raw in ('{', '{"conversationId":1}', '{"workspacePaths":"ab"}',
                        '{"unused":NaN}', '{"unused":"\\ud800"}', "{}" + " " * (128 * 1024)):
                with self.subTest(raw=raw[:60]):
                    self.assertIsNone(agy_delivery_request(raw=raw))
            self.assertIsNone(agy_delivery_request(payload={"workspacePaths": ("a", "b")}))
            at_limit = "{}" + " " * (128 * 1024 - 2)
            self.assertEqual(("", [], ""), agy_delivery_request(raw=at_limit))
            self.assertIsNone(agy_delivery_request(raw=at_limit + " "))
            self.assertEqual(("session", ["a", "a"], "trace"), agy_delivery_request(
                payload={"conversationId": "session", "workspacePaths": ["a", "a"],
                         "transcriptPath": "trace", "unrelated": object()}))

    def test_native_agy_stdout_matches_python_byte_for_byte(self):
        with patch.dict(os.environ, self.env, clear=True):
            for text in ("", "literal", "한글 😀 \u007f \n\r\t\b\f\u0000 \\ \" ", "a" * (128 * 1024)):
                with self.subTest(length=len(text)):
                    expected = json.dumps(agy._injection(text))
                    self.assertEqual(expected, agy_delivery_stdout(text))
                    self.assertFalse(expected.endswith("\n"))
            self.assertIsNone(agy_delivery_stdout("a" * (128 * 1024 + 1)))
            self.assertIsNone(agy_delivery_stdout("\ud800"))

    def test_native_agy_ingress_preserves_public_noop_output_and_exact_replay(self):
        def invoke(event, raw, path, *extra, **overrides):
            argv = [str(self.entry)]
            if event != "pre-tool":
                argv.insert(0, str(self.entry.with_name("moru-hook-native")))
            return subprocess.run(
                [*argv, "agy-hook", event, *extra],
                input=raw, cwd=self.project, env={**self.env, "PATH": str(path), **overrides},
                capture_output=True, timeout=8,
            )

        allow = b'{"decision": "allow"}\n'
        command = _agy_hooks_spec(self.entry)["PreToolUse"][0]["hooks"][0]["command"]
        raw = b'{"toolCall":{"name":"read_file","args":{"Path":"src/ordinary.py"}}}'
        shell_env = {key: value for key, value in self.env.items() if key != "MORU_LAUNCHER_BACKEND"}
        configured = subprocess.run(["/bin/sh", "-c", command], input=raw, cwd=self.project,
                                    env=shell_env, capture_output=True, timeout=8)
        self.assertEqual((0, allow, b""), result(configured))
        limit = 128 * 1024
        for event, raw, expected in (
            ("pre-tool", b'{"toolCall":{"name":"unknown"}}', allow),
            ("pre-tool", b'{"toolCall":{"name":"read_file","args":{"Path":"src/ordinary.py"}}}', allow),
            ("pre-tool", b'{"toolCall":{"name":"read_file","args":{"Path":"skill.md"}}}', allow),
            ("pre-tool", b'{"toolCall":{"name":"read_file","args":{"Path":"","AbsolutePath":"src/a.py"}}}', allow),
            ("pre-tool", b" " * (limit - 2) + b"{}", allow),
            ("pre-tool", b'{"toolCall":{"name":"edit_file","name":"unknown"}}', allow),
            ("pre-tool", b'{broken', allow),
            ("pre-invocation", b'{broken', b'{}\n'),
            ("stop", b'{broken', b'{}\n'),
        ):
            with self.subTest(event=event, raw=raw):
                self.assertEqual((0, expected, b""), result(invoke(event, raw, self.empty)))

        replay = self.base / "replay-bin"
        replay.mkdir()
        python = replay / "python3"
        python.write_text("#!/bin/sh\nexec /bin/cat\n", encoding="utf-8")
        python.chmod(0o755)
        for event, raw in (
            ("pre-tool", b'{"toolCall":{"name":"run_command"}}'),
            ("pre-tool", b'{"toolCall":{"name":"unknown","name":"write_file"}}'),
            ("pre-tool", b'{"toolCall":{"name":"edit_file"}}'),
            ("pre-tool", b'{"toolCall":{"name":"read_file","args":{"Path":"","AbsolutePath":"docs/SKILL.md/."}}}'),
            ("pre-tool", b'{"toolCall":{"name":"read_file","args":{"Path":"docs/SKILL.md"}}}'),
            ("pre-invocation", b'{"conversationId":"current"}'),
            ("stop", b'{}'),
            ("pre-tool", b" " * (limit - 1) + b"{}"),
            ("pre-tool", b'{"tail":"' + b" " * (limit - 11) + "한글".encode() + b'"}\r\n'),
            ("pre-tool", b'{"raw":"\xff"}'),
        ):
            with self.subTest(event=event, length=len(raw), suffix=raw[-88:]):
                self.assertEqual((0, raw, b""), result(invoke(event, raw, replay)))
        raw = b'{"toolCall":{"name":"unknown"}}'
        self.assertEqual((0, raw, b""), result(invoke("pre-tool", raw, replay, PYTHONIOENCODING="latin-1")))
        self.assertEqual((0, raw, b""), result(invoke("pre-tool", raw, replay, "extra")))
        self.assertEqual((0, raw, b""), result(invoke("pre-tool", raw, replay, MORU_LAUNCHER_BACKEND="python")))
        self.assertEqual((0, raw, b""), result(invoke("pre-tool", raw, replay, MORU_HOME=str(self.project))))
        for event in ("pre-invocation", "stop"):
            public = subprocess.run([str(self.entry), "agy-hook", event], input=b"{broken", cwd=self.project,
                                    env={**self.env, "PATH": str(replay)}, capture_output=True, timeout=8)
            self.assertEqual((0, b"{broken", b""), result(public))
        python.write_text("#!/bin/sh\n/bin/cat >/dev/null\nprintf '{\"decision\": \"deny\"}\\n'\nexit 7\n",
                          encoding="utf-8")
        self.assertEqual((7, b'{"decision": "deny"}\n', b""), result(invoke(
            "pre-tool", b'{"toolCall":{"name":"edit_file"}}', replay, MORU_AGY_GATE="strict",
        )))
        self.entry.with_name("moru-hook-native").chmod(0o644)
        self.assertEqual((7, b'{"decision": "deny"}\n', b""), result(invoke("pre-tool", raw, replay)))

    def test_native_agy_skill_notice_matches_ranges_and_keeps_deduplication(self):
        skill = self.project / "한글" / "SKILL.md"
        skill.parent.mkdir()
        marker_directory = self.base / "marker-state"
        with patch.dict(os.environ, self.env, clear=True):
            for source in ("", "\n", "a\r\nb\r\nc\rd\u0085e\u2028f\u2029g\x1ch\x1di\x1ej\v\fk\n"):
                skill.write_bytes(source.encode())
                total = len(source.splitlines())
                for start, end in ((None, None), (0, 0), (1, total), (0, total - 1), (2, -1), (2, 100)):
                    with self.subTest(source=source, start=start, end=end):
                        expected = adapter._partial_read_note_python(skill, {"StartLine": start, "EndLine": end})
                        self.assertEqual(expected, agy_skill_read_note(skill, start, end))
            span = {"Path": str(skill), "StartLine": "1", "EndLine": "1"}
            alias = self.project / "lexical"
            alias.symlink_to(skill.parent, target_is_directory=True)
            aliased_skill = alias / skill.name
            self.assertEqual(adapter._partial_read_note_python(aliased_skill, span),
                             agy_skill_read_note(aliased_skill, 1, 1))
            self.assertIsNone(agy_skill_read_note(skill, "1", "1"))
            with patch("agy_hook_state.MARKER_DIR", marker_directory):
                self.assertEqual(
                    adapter._partial_read_note_python(skill, span), adapter.partial_read_note(span, "legacy"),
                )
                span.update(StartLine=1, EndLine=1)
                expected = adapter._partial_read_note_python(skill, span)
                with patch.object(adapter, "_partial_read_note_python", side_effect=AssertionError("Python notice")):
                    self.assertEqual(expected, adapter.partial_read_note(span, "native"))
                    self.assertEqual("", adapter.partial_read_note(span, "native"))
                self.assertEqual("", adapter.partial_read_note({**span, "EndLine": "1"}, "native"))
            self.assertTrue((marker_directory / "native.partial-read.digest").is_file())

        payload = {"conversationId": "fresh", "toolCall": {"name": "read_file", "args": {
            "Path": str(skill), "StartLine": 1, "EndLine": total,
        }}}
        completed = subprocess.run(
            [str(self.entry.with_name("moru-hook-native")), str(self.entry), "agy-hook", "pre-tool"],
            input=json.dumps(payload).encode(), cwd=self.project, env=self.env,
            capture_output=True, timeout=8,
        )
        self.assertEqual((0, b'{"decision": "allow"}\n', b""), result(completed))
        self.assertFalse((self.base / "home/.moru/agy-hook/fresh.partial-read.digest").exists())
        skill.write_bytes(b"\xff")
        with patch.dict(os.environ, self.env, clear=True):
            self.assertIsNone(agy_skill_read_note(skill, 1, 1))
            self.assertEqual("", adapter.partial_read_note(span, "invalid-utf8"))

    def test_native_reuse_credit_matches_latest_entry_normalization_and_cap(self):
        current = reuse_fixtures.RequiredDocReuseTests()._fixture(self.project, takeaway="")
        prior = current.parent.parent / ("a" * 32) / "preflight.json"
        ledger = prior.with_name("gate-evidence.json")
        review = prior.with_name("doc-takeaway.json")
        good = {"gate": "source docs", "status": "SUCCESS",
                "fields": {"takeaway": " first\u001c  근거 "}}
        failed = {"gate": "source docs", "status": "FAIL"}
        cases = (
            ([good, failed], None, [], False, None),
            ([good, failed], " reviewed\r\n again ", [], True, "reviewed again"),
            ([failed, good], "first 근거", [], True, "first 근거"),
            ([good], "  reviewed ", [], True, "first 근거 | reviewed"),
            ([good], "  reviewed ", ["other", "unrelated", "prefix first 근거 | reviewed suffix"], True, None),
            ([good], "  reviewed ", ["one", "two", "three"], False, None),
            ([], "😀" * 401, [], True, "😀" * 400),
        )
        with patch.dict(os.environ, self.env, clear=True):
            for entries, prior_review, previous, credited, added in cases:
                with self.subTest(previous=previous, entries=len(entries), credited=credited):
                    ledger.write_text(json.dumps({"entries": entries}), encoding="utf-8")
                    review.unlink(missing_ok=True)
                    if prior_review is not None:
                        review.write_text(json.dumps({"takeaway": prior_review}, ensure_ascii=False),
                                          encoding="utf-8")
                    expected = list(previous)
                    self.assertEqual(credited, reuse_reference._credit_takeaway_python(prior, expected))
                    self.assertEqual((credited, added), reuse_credit(prior, previous, 3, 400))
                    self.assertEqual(expected, previous + ([added] if added is not None else []))
            ledger.write_text("{}", encoding="utf-8")
            review.write_text('{"takeaway":23}', encoding="utf-8")
            self.assertIsNone(reuse_credit(prior, [], 3, 400))
            self.assertEqual(["23"], reuse_reference.required_doc_reuse(current)["takeaways"])

    def test_both_native_reuse_callers_keep_session_and_snapshot_admission(self):
        current = reuse_fixtures.RequiredDocReuseTests()._fixture(self.project)
        prior = current.parent.parent / ("a" * 32) / "preflight.json"
        for path in (current, prior):
            manifest = json.loads(path.read_bytes())
            manifest["project_route_docs"] = manifest["execution_snapshot"]["required_docs"]
            path.write_text(json.dumps(manifest), encoding="utf-8")
        callers = (reuse_reference.required_doc_reuse, reuse_reference.project_route_doc_reuse)
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = [caller(current) for caller in callers]
        original = json.loads(prior.read_bytes())
        read = reuse_reference._read

        def read_current(path, limit):
            self.assertEqual(current, path, "prior evidence should be read in Rust")
            return read(path, limit)

        with patch.dict(os.environ, self.env, clear=True):
            with patch.object(reuse_reference, "_read", side_effect=read_current):
                self.assertEqual(expected, [caller(current) for caller in callers])
                for field, value in (
                    ("runtime_session", {"runtime": "codex", "session_id": "foreign"}),
                    ("runtime_session", {"runtime": "claude", "session_id": "session-one"}),
                    ("agent_run_id", "f" * 32),
                ):
                    with self.subTest(field=field, value=value):
                        prior.write_text(json.dumps({**original, field: value}), encoding="utf-8")
                        for caller in callers:
                            self.assertEqual([], caller(current)["reused"])

            alias = self.base / "alias"
            alias.symlink_to(self.project, target_is_directory=True)
            prior.write_text(json.dumps({**original, "project": str(alias)}), encoding="utf-8")
            self.assertEqual(expected, [caller(current) for caller in callers])
            for size in (True, 120.0, -1):
                with self.subTest(size=size):
                    records = [{**record, "size_bytes": size} for record in original["project_route_docs"]]
                    prior.write_text(json.dumps({**original, "project_route_docs": records}), encoding="utf-8")
                    self.assertEqual([], reuse_reference.project_route_doc_reuse(current)["reused"])

            records = original["project_route_docs"]
            stale = [{**record, "sha256": "0" * 64} for record in records]
            with patch.object(reuse_reference, "_read", side_effect=read_current):
                for duplicate, result in ((stale + records, expected[1]["reused"]), (records + stale, [])):
                    prior.write_text(json.dumps({**original, "project_route_docs": duplicate}), encoding="utf-8")
                    self.assertEqual(result, reuse_reference.project_route_doc_reuse(current)["reused"])

    def test_native_current_reuse_preserves_order_and_legacy_admission(self):
        current = reuse_fixtures.RequiredDocReuseTests()._fixture(self.project)
        prior = current.parent.parent / ("a" * 32) / "preflight.json"
        data = json.loads(current.read_bytes())
        first, second = data["execution_snapshot"]["required_docs"]
        a, b = first["path"], second["path"]
        required = [b, "missing-one.md", a, "missing-two.md", b]
        data["route"]["required_docs"] = required
        rows = [{**first, "sha256": "0" * 64}, second, first]
        data["project_route_docs"] = data["execution_snapshot"]["required_docs"] = rows
        current.write_text(json.dumps(data), encoding="utf-8")
        history = json.loads(prior.read_bytes())
        history["project_route_docs"] = history["execution_snapshot"]["required_docs"] = [first, second]
        prior.write_text(json.dumps(history), encoding="utf-8")
        required_reuse = reuse_reference.required_doc_reuse
        project_reuse = reuse_reference.project_route_doc_reuse
        with patch.dict(os.environ, self.env, clear=True):
            with patch.object(reuse_reference, "_read", side_effect=AssertionError("Python read")):
                self.assertEqual([b, a], required_reuse(current)["reused"])
                self.assertEqual(["missing-one.md", "missing-two.md"], required_reuse(current)["unread"])
                self.assertEqual([a, b], project_reuse(current)["reused"])

            alias = self.base / "alias.json"
            alias.symlink_to(current)
            self.assertIsNone(reuse_current(alias, project_docs=False))
            self.assertEqual(required_reuse(current), required_reuse(alias))

            foreign = self.project.with_name(self.project.name + "-other") / current.relative_to(self.project)
            foreign.parent.mkdir(parents=True)
            foreign.write_bytes(current.read_bytes())
            self.assertIsNone(reuse_current(foreign, project_docs=False))
            self.assertEqual({"reused": [], "unread": required[:-1]}, required_reuse(foreign))

            unused = {"path": "unused.md", "sha256": "a" * 64, "size_bytes": True}
            data["execution_snapshot"]["required_docs"] = rows + [unused]
            current.write_text(json.dumps(data), encoding="utf-8")
            self.assertIsNone(reuse_current(current, project_docs=False))
            self.assertEqual({"reused": [], "unread": required[:-1]}, required_reuse(current))

    def test_native_reuse_registry_window_preserves_ids_and_lazy_evidence_reads(self):
        current = reuse_fixtures.RequiredDocReuseTests()._fixture(self.project)
        registry = self.project / ".moru" / "run-registry.json"
        prior_id = "a" * 32
        current_id = current.parent.name
        registry.write_text(json.dumps({"runs": [
            {"run_id": "0" * 32, "state": "completed"},
            *([None] * 96),
            {"run_id": prior_id, "state": "completed"},
            {"run_id": "c" * 32, "state": "completed", "evidence_name": "worker.json"},
            {"run_id": current_id, "state": "completed"},
            {"run_id": prior_id, "state": "completed", "evidence_name": "preflight.json"},
        ]}), encoding="utf-8")
        older_id = "d" * 32
        older = current.parent.parent / older_id / "preflight.json"
        older.parent.mkdir()
        older.write_text("{", encoding="utf-8")
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual([prior_id, prior_id], reuse_run_ids(self.project, current_id, 100))
            self.assertEqual([prior_id], reuse_run_ids(self.project, current_id, 3))
            self.assertIsNone(reuse_run_ids(self.project, current_id, 101))
            with patch.object(reuse_reference, "_completed_run_ids_python",
                              side_effect=AssertionError("Python registry scan")), patch.object(
                                  reuse_reference, "_read", wraps=reuse_reference._read) as reads:
                prior_path = current.parent.parent / prior_id / "preflight.json"
                records = reuse_reference._doc_records(json.loads(prior_path.read_bytes()))
                wanted = set(records.values())
                lookup = reuse_reference._completed_matches(
                    self.project, current_id, ("codex", "session-one"), wanted, project_docs=False
                )
                prior, matches = next(lookup)
                lookup.close()
                self.assertEqual(prior_id, prior.parent.name)
                self.assertEqual(wanted, matches)
                reads.assert_not_called()
            # A malformed older candidate would decline the entire native
            # request if it were read eagerly after the first match.
            self.assertEqual((1, wanted), reuse_matches(
                self.project, [prior_id, older_id], ("codex", "session-one"), list(wanted),
                project_docs=False,
            ))

    def test_native_reuse_plan_preserves_order_cap_and_fallback(self):
        fixture = reuse_fixtures.ReuseAcrossRunsTests()
        docs = [f"docs/{name}.md" for name in "abcdef"]
        current = fixture._run(self.project, "f" * 32, docs)
        ids = [f"{index:032x}" for index in range(1, 8)]
        rows = [(0, "first note"), (0, "unused"), (1, ""), (3, "third"),
                (4, "fourth"), (5, "over the cap"), (2, "note")]
        priors = [fixture._run(self.project, run_id, [docs[doc]], takeaway)
                  for run_id, (doc, takeaway) in zip(ids, rows)]
        fixture._registry(self.project, list(reversed(ids)))
        for path in (current, *priors):
            manifest = json.loads(path.read_bytes())
            manifest["project_route_docs"] = manifest["execution_snapshot"]["required_docs"]
            path.write_text(json.dumps(manifest), encoding="utf-8")
        # The second run can add no coverage, so this legacy takeaway
        # must be left unread even though the manifest matches.
        priors[1].with_name("doc-takeaway.json").write_text('{"takeaway":23}', encoding="utf-8")
        callers = (reuse_reference.required_doc_reuse, reuse_reference.project_route_doc_reuse)
        strict = {"reused": [docs[i] for i in (0, 2, 3, 4)],
                  "unread": [docs[1], docs[5]], "takeaways": ["first note", "third", "fourth"]}
        relaxed = {**strict, "reused": docs, "unread": []}
        with patch.dict(os.environ, self.env, clear=True), patch.object(
                reuse_reference, "_completed_matches", side_effect=AssertionError("plan fell back")):
            self.assertEqual([strict, strict], [caller(current) for caller in callers])
            self.assertEqual(relaxed, reuse_reference.required_doc_reuse(current, require_takeaway=False))

        # The declined native attempt has already found some coverage. The
        # compatibility path must carry over none of that partial result.
        priors[4].with_name("doc-takeaway.json").write_text('{"takeaway":23}', encoding="utf-8")
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = [caller(current) for caller in callers]
        with patch.dict(os.environ, self.env, clear=True), patch.object(
                reuse_reference, "_completed_matches", wraps=reuse_reference._completed_matches) as fallback:
            self.assertEqual(expected, [caller(current) for caller in callers])
            self.assertGreaterEqual(fallback.call_count, len(callers))

    def test_native_reuse_plan_carries_coverage_and_slots_between_roots(self):
        fixture = reuse_fixtures.ReuseAcrossRunsTests()
        docs = ["a.md", "b.md", "c.md", "d.md"]
        current = fixture._run(self.project, "f" * 32, docs)
        first, second = (self.base / name for name in ("first", "second"))
        for root, rows in ((self.project, [(docs[0], "first note"), (docs[1], "second")]),
                           (first, [(docs[0], "must not use a slot"), (docs[2], "third")]),
                           (second, [(docs[3], "note")])):
            ids = [f"{index:032x}" for index in range(1, len(rows) + 1)]
            for run_id, (doc, takeaway) in zip(ids, rows):
                fixture._run(root, run_id, [doc], takeaway)
            fixture._registry(root, list(reversed(ids)))
        older = fixture._run(second, "e" * 32, [docs[0]])
        older.write_text("{", encoding="utf-8")
        fixture._registry(second, [older.parent.name, f"{1:032x}"])

        def roots(*args, **kwargs):
            yield from (self.project, first, second)
            self.fail("read another root after full coverage")

        with patch.dict(os.environ, self.env, clear=True), patch.object(
                reuse_reference, "_repository_roots", side_effect=roots), patch.object(
                reuse_reference, "_completed_matches", side_effect=AssertionError("plan fell back")):
            self.assertEqual(
                {"reused": docs, "unread": [], "takeaways": ["first note", "second", "third"]},
                reuse_reference.required_doc_reuse(current),
            )

    def test_native_root_discovery_preserves_lazy_worktree_and_sibling_phases(self):
        fixture = reuse_fixtures.ReuseAcrossRunsTests()
        workspace = self.base / "workspace"
        main, linked, sibling = (workspace / name for name in ("main", "linked", "sibling"))
        admin = main / ".git" / "worktrees" / "linked"
        admin.mkdir(parents=True)
        linked.mkdir()
        (sibling / ".git").mkdir(parents=True)
        (linked / ".git").write_text("gitdir: ../main/.git/worktrees/linked\r\n", encoding="utf-8")
        (admin / "commondir").write_text("../../\r\n", encoding="utf-8")
        (admin / "gitdir").write_text(f"{linked}/.git\r\n", encoding="utf-8")
        doc_a, doc_b = fixture.DOC_A, fixture.DOC_B
        current = fixture._run(linked, "f" * 32, [doc_a, doc_b])
        fixture._run(main, "a" * 32, [doc_a], "main proof")
        fixture._run(sibling, "b" * 32, [doc_b], "sibling proof")
        fixture._registry(main, ["a" * 32])
        fixture._registry(sibling, ["b" * 32])

        with patch.dict(os.environ, self.env, clear=True), patch.object(
                reuse_reference, "_worktree_roots_python", side_effect=AssertionError("Python discovery")), patch(
                "support.native_doc_transcript.discover_reuse_roots", wraps=discover_reuse_roots) as discovery:
            self.assertEqual([doc_a, doc_b], reuse_reference.required_doc_reuse(current)["reused"])
            self.assertEqual(["worktrees", "siblings"], [c.kwargs["phase"] for c in discovery.call_args_list])
            discovery.reset_mock()
            self.assertEqual([linked, main], list(reuse_reference._repository_roots(linked)))
            self.assertEqual(["worktrees"], [c.kwargs["phase"] for c in discovery.call_args_list])
            discovery.reset_mock()
            fixture._run(linked, "c" * 32, [doc_a, doc_b], "current checkout proof")
            fixture._registry(linked, ["c" * 32])
            self.assertEqual([doc_a, doc_b], reuse_reference.required_doc_reuse(current)["reused"])
            discovery.assert_not_called()

        stale = main / ".git" / "worktrees" / "removed"
        stale.mkdir()
        (stale / "gitdir").write_text(f"{workspace}/missing/.git", encoding="utf-8")
        with patch.dict(os.environ, self.env, clear=True), patch.object(
                reuse_reference, "_worktree_roots_python", wraps=reuse_reference._worktree_roots_python) as fallback:
            self.assertEqual([linked, main, sibling],
                             list(reuse_reference._repository_roots(linked, include_sibling_repos=True)))
            fallback.assert_called_once_with(linked)

    def test_native_reuse_root_ranking_preserves_float_ties_exclusions_and_cap(self):
        root = self.base / "roots"
        epoch = 1_700_000_000_000_000_000
        candidates = [root / f"project-{index}" for index in range(10)]
        prefix = root / "a" / "child"
        punctuation = root / "a.x"
        for index, project in enumerate([*candidates, prefix, punctuation]):
            state = project / ".moru"
            state.mkdir(parents=True)
            registry = state / "run-registry.json"
            registry.write_text("{}", encoding="utf-8")
            stamp = epoch + index if project in (prefix, punctuation) else epoch + index * 1_000_000
            os.utime(registry, ns=(stamp, stamp))
        alias = root / "alias"
        alias.symlink_to(candidates[-1], target_is_directory=True)
        directory = root / "not-registered" / ".moru" / "run-registry.json"
        directory.mkdir(parents=True)
        inputs = [prefix, punctuation, alias, *candidates, directory.parents[1], root / "missing"]
        excluded = [candidates[7]]
        expected = reuse_reference._recent_registered_roots_python(inputs, excluded)
        with patch.dict(os.environ, self.env, clear=True), patch.object(
                reuse_reference, "_recent_registered_roots_python", side_effect=AssertionError("Python ranking")):
            self.assertEqual(expected, reuse_reference._recent_registered_roots(inputs, excluded))
            self.assertEqual([punctuation, prefix], rank_reuse_roots([prefix, punctuation], [], 8))
            self.assertEqual((125, b"", b""), result(self.raw("rank-reuse-roots", {
                "candidates": [str(prefix / "..")], "excluded": [], "limit": 8,
            })))
        self.assertEqual(8, len(expected))
        self.assertEqual([candidates[-1], candidates[-1]], expected[:2])

    def test_agy_native_request_runs_through_stdin_and_adapter_callers(self):
        fixture = agy_fixtures.AgyHookTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        payload = {"conversationId": "한글", "workspacePaths": [str(fixture.rules), str(fixture.project)],
                   "transcriptPath": str(fixture.transcript)}
        raw = json.dumps(payload, ensure_ascii=False)
        marker = fixture.evidence.parent / reference.MARKER

        def run_stdin(text):
            out = io.StringIO()
            with patch.object(sys, "stdin", io.StringIO(text)), patch.object(sys, "stdout", out):
                self.assertEqual(0, agy.main())
            return out.getvalue()

        def resolve(project, identity):
            self.assertEqual({"runtime": "antigravity", "session_id": "한글"}, identity)
            return fixture.evidence if project == fixture.project else None

        with patch.object(agent_runtime_session, "resolve_runtime_evidence", side_effect=resolve):
            with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                expected = run_stdin(raw)
                expected_marker = marker.read_bytes()
            marker.unlink()
            with patch.dict(os.environ, self.env, clear=True), patch.object(
                    agy, "_python_payload", side_effect=AssertionError("standalone Python parser")), patch.object(
                    agy, "_injection", side_effect=AssertionError("standalone Python encoder")):
                self.assertEqual(expected, run_stdin(raw))
                self.assertEqual("{}", run_stdin(raw))
            self.assertEqual(expected_marker, marker.read_bytes())
            marker.unlink()
            run = subprocess.run

            def lose_stdout_encoding(argv, *args, **kwargs):
                completed = run(argv, *args, **kwargs)
                if argv[-1] == "agy-delivery-stdout":
                    self.assertEqual(expected_marker, marker.read_bytes())
                    self.assertEqual(0, completed.returncode)
                    raise subprocess.TimeoutExpired(argv, 10)
                return completed

            with patch.dict(os.environ, self.env, clear=True), patch(
                    "support.native_probe_transport.subprocess.run", side_effect=lose_stdout_encoding), patch.object(
                    agy, "_delivered_text", wraps=agy._delivered_text) as deliver:
                self.assertEqual(expected, run_stdin(raw))
                deliver.assert_called_once()
            self.assertEqual(expected_marker, marker.read_bytes())
            marker.unlink()
            with patch.dict(os.environ, self.env, clear=True), patch.object(
                    adapter, "_prompt_guidance_steps", return_value=[]), patch.object(
                    agy, "_respond", wraps=agy._respond) as respond:
                self.assertEqual(json.loads(expected), adapter.pre_invocation(payload))
                self.assertEqual(("한글", payload["workspacePaths"], str(fixture.transcript)),
                                 respond.call_args.args[2])
            self.assertEqual(raw, json.dumps(payload, ensure_ascii=False))
            self.assertEqual(expected_marker, marker.read_bytes())
            marker.unlink()
            legacy = {**payload, "workspacePaths": tuple(payload["workspacePaths"]),
                      "transcriptPath": fixture.transcript}
            with patch.dict(os.environ, self.env, clear=True), patch.object(
                    adapter, "_prompt_guidance_steps", return_value=[]):
                self.assertEqual(json.loads(expected), adapter.pre_invocation(legacy))
            self.assertEqual(expected_marker, marker.read_bytes())
            with patch.dict(os.environ, self.env, clear=True):
                for invalid in ("{malformed", "{}{}", " \n", "\ufeff{}"):
                    self.assertEqual("{}", run_stdin(invalid))

    def test_agy_whole_file_coverage_preserves_compaction_and_modification_time(self):
        docs = {"한글 guide.md": "test", "second.md": "test"}
        for doc in docs:
            path = self.base / doc
            path.write_text("fixture")
            os.utime(path, (1577836800, 1577836800))
        alias = self.base / "alias.md"
        alias.symlink_to(self.base / "second.md")

        def read(path, stamp=None, tool="read_file", **extra):
            return {"created_at": stamp, "tool_calls": [{"name": tool,
                    "args": {"Path": json.dumps(str(path)), **extra}}]}

        rows = [read(self.base / "한글 guide.md"),
                {"type": "CHECKPOINT", "content": "# Resuming from a compaction"},
                read(self.base / "한글 guide.md", "2999-01-01T00:00:00Z", StartLine=1),
                read(self.base / "한글 guide.md", "2000-01-01T00:00:00Z"),
                read(alias, "2021-01-01T01:00:00+01:00", tool="view_file")]
        self.path.write_bytes(b'{invalid "tool_calls"}\r' + "\r".join(map(json.dumps, rows)).encode())
        before = self.path.read_bytes()
        expected = agy._read_in_context_python(self.path, self.base, docs)
        self.assertEqual({"second.md"}, expected)
        with patch.dict(os.environ, self.env, clear=True), patch.object(
                agy, "_read_in_context_python", side_effect=AssertionError("Python fallback")):
            self.assertEqual(expected, agy.read_in_context(self.path, self.base, docs))
        self.assertEqual(before, self.path.read_bytes())

        for stamp in ("2021-01-01T00:00:00", "2020-01-01T00:00:00Z"):
            with self.subTest(stamp=stamp), patch.dict(os.environ, self.env, clear=True):
                self.path.write_text(json.dumps(read(alias, stamp)))
                self.assertIsNone(NativeDocTranscript.agy_covered(self.path, self.base, list(docs)))
                self.assertEqual(agy._read_in_context_python(self.path, self.base, docs),
                                 agy.read_in_context(self.path, self.base, docs))

    def test_native_delivery_text_matches_python_byte_limits_and_order(self):
        texts = {
            "first.md": "---\nmeta: yes\n---\n\x1c한글\u3000",
            "large.md": "가" * 20,
            "next.md": "123",
            "later.md": "z",
            "unclosed.md": "---\nmetadata: open",
            "empty.md": "\x1f",
        }
        pending = ["first.md", "missing.md", "large.md", "next.md", "later.md",
                   "unclosed.md", "empty.md", "next.md"]
        for inline_limit, total_limit in ((6, 9), (0, 0), (64, 200)):
            with self.subTest(inline=inline_limit, total=total_limit), patch.multiple(
                    reference, MAX_INLINE_DOC_BYTES=inline_limit, MAX_DELIVERY_BYTES=total_limit):
                expected = reference._render_python(texts, pending, self.base)
                with patch.dict(os.environ, self.env, clear=True), patch.object(
                        reference, "_render_python", side_effect=AssertionError("Python fallback")):
                    self.assertEqual(expected, reference._render(texts, pending, self.base))
                    self.assertEqual("", reference._render(texts, ["missing.md"]))
        self.assertEqual((125, b"", b""), result(self.raw("render", {
            "docs": [{"name": "missing-text.md"}], "inline_limit": 6, "total_limit": 9,
        })))

    def test_native_document_batch_preserves_python_file_reads(self):
        names = ["missing.md", "한글.md", "folder", "./second.md/", "한글.md", "empty.md"]
        (self.base / "한글.md").write_bytes("\ufefffirst\r\n한글\rlast\n".encode())
        (self.base / "folder").mkdir()
        (self.base / "second.md").write_text("second")
        (self.base / "empty.md").touch()
        expected = reference._read_docs_python(self.base, names)
        self.assertEqual(["한글.md", "./second.md/", "empty.md"], list(expected))
        self.assertEqual("\ufefffirst\n한글\nlast\n", expected["한글.md"])
        with patch.dict(os.environ, self.env, clear=True), patch.object(
                reference, "_read_docs_python", side_effect=AssertionError("Python fallback")):
            self.assertEqual(list(expected.items()), list(reference._read_docs(self.base, names).items()))
        self.assertEqual("\ufefffirst\r\n한글\rlast\n".encode(), (self.base / "한글.md").read_bytes())

        (self.base / "alias.md").symlink_to(self.base / "second.md")
        (self.base / "large.md").write_bytes(b"x" * (128 * 1024 + 1))
        (self.base / "limit.md").write_bytes(b"x" * (128 * 1024))
        (self.base / "invalid.md").write_bytes(b"\xff")
        os.mkfifo(self.base / "stream.md")
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual({"limit.md": "x" * (128 * 1024)},
                             NativeDocTranscript.read_docs(self.base, ["limit.md"]))
            for name in ("alias.md", "large.md", "invalid.md", "stream.md", "../outside.md"):
                self.assertIsNone(NativeDocTranscript.read_docs(self.base, ["second.md", name]))
            self.assertEqual({"alias.md": "second"}, reference._read_docs(self.base, ["alias.md"]))
            with self.assertRaises(UnicodeDecodeError):
                reference._read_docs(self.base, ["second.md", "invalid.md"])

    def test_native_delivery_plan_matches_marker_upgrade_and_compaction_cadence(self):
        marker = self.base / reference.MARKER
        compact = b'{"type":"compacted"}\n'
        cases = [
            (None, b"", 3, "deliver"),
            (b'{"delivered":["a.md"]}', b"unfinished", 3, "upgrade"),
            (b"{broken", b"", 3, "upgrade"),
            (b'{"delivered":["a.md"]}', compact, 3, "deliver"),
            (b'{"transcript_bytes":0}', compact[:-1], 3, "skip"),
            (json.dumps({"transcript_bytes": len(compact)}).encode(), compact, 3, "skip"),
            (b'{"transcript_bytes":999,"redeliveries":2}', compact, 3, "deliver"),
            (b'{"transcript_bytes":0,"redeliveries":3}', compact, 3, "skip"),
            (b'{"transcript_bytes":0,"redeliveries":3}', compact, 4, "deliver"),
        ]
        for record, transcript, limit, action in cases:
            with self.subTest(record=record, transcript=transcript, limit=limit):
                marker.unlink(missing_ok=True)
                if record is not None:
                    marker.write_bytes(record)
                self.path.write_bytes(transcript)
                expected = self.original("delivery_plan_python", marker, self.path, limit)
                self.assertEqual(action, expected["action"])
                with patch.dict(os.environ, self.env, clear=True), patch.object(
                        reference, "_delivery_plan_python", side_effect=AssertionError("Python fallback")):
                    self.assertEqual(expected, reference._delivery_plan(marker, self.path, limit))
                self.assertEqual(record, marker.read_bytes() if marker.exists() else None)
                self.assertEqual(transcript, self.path.read_bytes())
        marker.write_bytes(b'{"transcript_bytes":0,"redeliveries":"3"}')
        self.assertIsNone(self.native("delivery_plan", marker, self.path, 4))
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(self.original("delivery_plan_python", marker, self.path, 4),
                             reference._delivery_plan(marker, self.path, 4))

    def test_native_registry_discovery_follows_stat_but_preserves_lexical_path(self):
        outer = self.base / "outer"
        inner = outer / "nested"
        alias = self.base / "alias"
        state = inner / ".moru"
        state.mkdir(parents=True)
        alias.symlink_to(inner, target_is_directory=True)
        (outer / ".moru").mkdir()
        (outer / ".moru" / "run-registry.json").touch()
        registry = state / "run-registry.json"
        registry.symlink_to(outer / ".moru" / "run-registry.json")
        file = inner / "existing"
        file.touch()
        with patch.dict(os.environ, self.env, clear=True):
            for edited, expected in (
                (file, (inner,)),
                (inner, (inner,)),
                (alias / "missing" / "file", (alias,)),
                (self.empty, ()),
            ):
                with self.subTest(edited=edited):
                    self.assertEqual(expected, reference._nearest_registry_project_python(edited))
                    self.assertEqual(expected, nearest_registry_project(edited))
            registry.unlink()
            registry.symlink_to(self.base / "missing-registry")
            self.assertEqual((outer,), nearest_registry_project(file))
            registry.unlink()
            registry.mkdir()
            self.assertEqual((outer,), nearest_registry_project(file))
            for unsupported in (Path("relative"), inner / ".." / "existing", Path("//volume")):
                self.assertIsNone(nearest_registry_project(unsupported))

    def test_session_binding_uses_nearest_root_once_per_edit_in_order(self):
        outer = self.base / "outer"
        inner = outer / "nested"
        later = self.base / "later"
        for root in (outer, inner, later):
            (root / ".moru").mkdir(parents=True)
        for root in (outer, inner):
            (root / ".moru" / "run-registry.json").touch()
        expected = later / "preflight.json"
        payload = {"tool_input": {"file_path": str(inner / "one"),
                                  "notebook_path": str(inner / "two"),
                                  "path": str(later / "three"),
                                  "patch": "*** Add File: /unvisited\n"}}
        queries = []

        def evidence_for(project):
            queries.append(project)
            if queries == [inner, inner]:
                (later / ".moru" / "run-registry.json").touch()
            return expected if project == later else None

        with patch.dict(os.environ, self.env, clear=True), patch.object(
                reference, "_nearest_registry_project_python", side_effect=AssertionError("Python fallback")), patch(
                "support.native_doc_transcript.nearest_registry_project", wraps=nearest_registry_project) as probe:
            self.assertEqual(expected, reference._session_run(payload, evidence_for))
        self.assertEqual([(inner / "one",), (inner / "two",), (later / "three",)],
                         [entry.args for entry in probe.call_args_list])
        self.assertEqual([inner, inner, later], queries)

    def test_native_delivery_manifest_projection_and_fallback(self):
        evidence = self.base / "preflight.json"
        ordinary = (
            b'{"rules":"obsolete","rules":"./rules","route":{"required_docs":'
            b'["z.md","a.md","z.md","\\ud55c\\uae00.md","a.md"]}}',
            b'{"rules":"rules","route":{}}',
            b'{"rules":"rules","route":{"required_docs":null}}',
            b'{"rules":"rules","route":{"required_docs":[]}}',
        )
        evidence.touch()
        evidence.chmod(0o444)
        with patch.dict(os.environ, self.env, clear=True):
            for raw in ordinary:
                with self.subTest(raw=raw):
                    evidence.chmod(0o644)
                    evidence.write_bytes(raw)
                    evidence.chmod(0o444)
                    expected = reference._delivery_manifest_python(evidence)
                    self.assertEqual(expected, read_delivery_manifest(evidence))
                    self.assertEqual(raw, evidence.read_bytes())
                    self.assertEqual(0o444, evidence.stat().st_mode & 0o777)

            for raw in (
                b'{"rules":"rules","route":{"required_docs":"ab"}}',
                b'{"rules":"rules","route":{"required_docs":[1]}}',
                b'{"rules":"rules","route":{},"unrelated":NaN}',
                b'{"rules":"rules","route":{}}' + b' ' * (128 * 1024),
            ):
                with self.subTest(prefix=raw[:64]):
                    evidence.chmod(0o644)
                    evidence.write_bytes(raw)
                    self.assertIsNone(read_delivery_manifest(evidence))
                    self.assertEqual(reference._delivery_manifest_python(evidence),
                                     reference._delivery_manifest(evidence))
            for raw in (b'{', b'{"rules":"rules","route":{},"unrelated":"\xff"}'):
                evidence.write_bytes(raw)
                self.assertIsNone(read_delivery_manifest(evidence))
                with self.assertRaises(ValueError):
                    reference._delivery_manifest(evidence)
            self.assertEqual((125, b"", b""), result(self.raw(
                "read-delivery-manifest", {"path": str(evidence.parent)})))

    def test_both_delivery_callers_use_native_manifest_after_admission(self):
        action_cases = ("_deliver", "_compaction")
        for name in action_cases:
            with self.subTest(caller=name):
                fixture = delivery_fixtures.DeliveryTests()
                fixture.setUp()
                try:
                    fixture._preflight([delivery_fixtures.OTHER, delivery_fixtures.CORE,
                                        delivery_fixtures.OTHER])
                    action = getattr(fixture, name)
                    marker = fixture.evidence.parent / reference.MARKER
                    with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                        expected = action()
                        expected_marker = marker.read_bytes()
                    marker.unlink()
                    with patch.dict(os.environ, self.env, clear=True), patch.object(
                            reference, "_delivery_manifest_python", side_effect=AssertionError("Python fallback")):
                        self.assertEqual(expected, action())
                    self.assertEqual(expected_marker, marker.read_bytes())
                    with patch.object(reference, "_delivery_manifest",
                                      side_effect=AssertionError("manifest read after delivery was skipped")):
                        self.assertEqual("", fixture._deliver())
                finally:
                    fixture.doCleanups()

    def test_native_marker_writer_matches_python_and_keeps_write_failures_terminal(self):
        directory = self.project / ".moru" / "runs" / ("a" * 32)
        directory.mkdir(parents=True)
        (directory / "preflight.json").write_text("{}")
        marker = directory / reference.MARKER
        legacy = self.base / reference.MARKER
        docs = ["한글.md", "escaped\n\x7f😀.md"]
        payload = {"marker": str(marker), "delivered": docs, "offset": 41,
                   "redeliveries": 3, "temporary": "b" * 32}
        previous_umask = os.umask(0o077)
        try:
            reference._write_marker_python(legacy, docs, 41, 3)
            with patch.dict(os.environ, self.env, clear=True), patch.object(
                    reference, "_write_marker_python", side_effect=AssertionError("Python fallback")):
                reference._write_marker(marker, docs, 41, 3)
                with patch("support.native_probe_transport.subprocess.run", side_effect=subprocess.TimeoutExpired([], 10)):
                    with self.assertRaisesRegex(OSError, "outcome could not be determined"):
                        reference._write_marker(marker, [], 0, 0)
        finally:
            os.umask(previous_umask)
        self.assertEqual(legacy.read_bytes(), marker.read_bytes())
        self.assertEqual(0o600, legacy.stat().st_mode & 0o777)
        self.assertEqual(legacy.stat().st_mode & 0o777, marker.stat().st_mode & 0o777)

        def probe():
            done = self.raw("write-marker", payload)
            self.assertEqual((0, b""), (done.returncode, done.stderr), done)
            return json.loads(done.stdout)["result"]["value"]

        temporary = directory / f"{reference.MARKER}.{payload['temporary']}.tmp"
        temporary.write_bytes(b"another writer")
        self.assertEqual({"stored": False}, probe())
        self.assertEqual(b"another writer", temporary.read_bytes())
        self.assertEqual(legacy.read_bytes(), marker.read_bytes())
        temporary.unlink()
        marker.unlink()
        marker.mkdir()
        self.assertEqual({"stored": False}, probe())
        self.assertFalse(temporary.exists())
        self.assertTrue(marker.is_dir())
        self.assertEqual((125, b"", b""), result(self.raw("write-marker", {**payload, "marker": str(legacy)})))
        alias = directory.with_name("c" * 32)
        alias.symlink_to(directory, target_is_directory=True)
        self.assertEqual((125, b"", b""), result(self.raw(
            "write-marker", {**payload, "marker": str(alias / reference.MARKER)})))

    def test_three_runtime_boundaries_and_partial_rows(self):
        for row in ({"type":"compacted"}, {"type":"system","subtype":"compact_boundary"},
                    {"type":"CHECKPOINT","content":"# Resuming from a compaction\nsummary"}):
            encoded=json.dumps(row).encode()
            self.parity(encoded)
            self.parity(encoded+b"\n")
            self.parity(b"ordinary row\n"+encoded+b"\n")

    def test_raw_prefilter_invalid_rows_bom_and_unused_nonfinite_values(self):
        for raw in (b"", b"\xff\n", b"{bad \"compacted\"}\n", b"[\"compacted\"]\n",
                    b'{"type":"comp\\u0061cted"}\n',
                    b'{"type":"comp\\u0061cted","unused":"compacted"}\n',
                    b'{"type":"compacted","unused":[NaN,Infinity,-Infinity,900719925474099312345678901]}\n',
                    b'{"type":"compacted","type":"assistant"}\n',
                    b'{"type":"assistant","type":"compacted"}\n',
                    b'\xef\xbb\xbf{"type":"compacted"}\n',
                    b'\xff\n{"type":"compacted"}\n',
                    b'{"type":"compacted","unused":"\xff"}\n',
                    b'{"type":"CHECKPOINT","content":123}\n'):
            self.parity(raw)

    def test_alignment_tail_window_fallback_and_unfinished_long_line(self):
        for length in (65535,65536,65537,70000):
            raw=b"header\n"+b"x"*length
            for fallback in (-1,0,7,8): self.parity(raw,fallback=fallback)
        self.parity(b"x"*70000+b"\n")
        self.parity(b"x"*70000+b"\npartial",fallback=4)

    def test_due_rewrite_equal_size_limit_and_offset_boundaries(self):
        row=b'{"type":"compacted"}\n'
        for offset in (0,1,len(row),len(row)+100):
            for count,limit in ((0,3),(3,3),(4,3),(0,0),(-1,0)):
                self.parity(row,offset=offset,count=count,limit=limit)
        self.path.write_bytes(row)
        self.assertIsNone(self.native("due",{"transcript_bytes":-1},self.path,3))
        with self.assertRaises((OSError,ValueError)) as expected:
            self.original("due_after_compaction",{"transcript_bytes":-1},self.path,3)
        with patch.dict(os.environ,self.env,clear=True), self.assertRaises(type(expected.exception)) as actual:
            reference._due_after_compaction({"transcript_bytes":-1},self.path,3)
        self.assertEqual(str(expected.exception),str(actual.exception))
        self.assertFalse(self.native("due",{"transcript_bytes":-1},self.path,0))

    def test_supported_bridge_executes_no_original_size_or_line_scan(self):
        self.path.write_bytes(b'{"type":"compacted"}\n')
        with patch.dict(os.environ,self.env,clear=True), \
             patch.object(reference,"_size",side_effect=AssertionError("Python file scan")):
            self.assertTrue(reference._compacted_before(self.path))
            self.assertEqual(self.path.stat().st_size,reference._aligned_size(self.path))
            self.assertTrue(reference._due_after_compaction({"transcript_bytes":0},self.path))

    def test_missing_directory_and_regular_symlink_match_original(self):
        for path in (self.path,self.base):
            self.assertEqual(self.original("compacted_before",path),self.native("compacted",path))
            self.assertEqual(self.original("aligned_size",path),self.native("aligned",path,0))
            self.assertFalse(self.native("due",{"transcript_bytes":0},path,3))
        self.path.write_bytes(b'{"type":"compacted"}\n')
        link=self.base/"regular-link"; link.symlink_to(self.path)
        self.assertTrue(self.native("compacted",link))
        self.assertEqual(self.path.stat().st_size,self.native("aligned",link,0))

    def test_source_or_environment_refusal_is_quiet_and_read_only(self):
        self.path.write_bytes(b'{"type":"compacted"}\n')
        before=self.path.read_bytes()
        for env in ({"PYTHONVERBOSE":"1"},{"MORU_HOME":str(self.project)}):
            self.assertEqual((125,b"",b""),result(self.raw("compacted",**env)))
        for operation,payload in (("unknown",{}),("aligned",{"path":str(self.path),"fallback":True}),
                                  ("due",{"path":str(self.path),"offset":0,"redeliveries":0,"limit":3,"extra":1})):
            self.assertEqual((125,b"",b""),result(self.raw(operation,payload)))
        self.assertEqual(before,self.path.read_bytes())

    def test_unsupported_byte_encoding_and_surrogate_use_original_fallback(self):
        special = b'"compacted"x'.decode("utf-16-be")
        raw=(json.dumps({"type":"compacted","content":special},ensure_ascii=False)+"\n").encode("utf-16-be")
        self.assertIn(b'"compacted"',raw)
        for data in (raw,b'{"type":"compacted","unused":"\\ud800"}\n',
                     b'{"type":"compacted","unused":"\xed\xa0\x80"}\n',
                     b'{"type":"compacted","unused":"\xed\xbf\xbf"}\n'):
            self.path.write_bytes(data)
            before=self.path.read_bytes()
            self.assertEqual((125,b"",b""),result(self.raw("compacted")))
            self.assertEqual((125,b"",b""),result(self.raw("due",{"path":str(self.path),
                "offset":0,"redeliveries":0,"limit":3})))
            with patch.dict(os.environ,self.env,clear=True):
                self.assertTrue(reference._compacted_before(self.path))
                self.assertTrue(reference._due_after_compaction({"transcript_bytes":0},self.path))
            self.assertEqual(before,self.path.read_bytes())

    def test_stream_refusal_does_not_consume_owned_pipe_or_inherited_file(self):
        fifo=self.base/"fifo"; os.mkfifo(fifo)
        for operation,fields in (("compacted",{}),("aligned",{"fallback":0}),
                                 ("due",{"offset":1,"redeliveries":0,"limit":3})):
            done=self.raw(operation,{"path":str(fifo),**fields})
            if operation=="due": self.assertEqual((125,b"",b""),result(done))
            else:
                # Source size0 can answer without opening a special file.
                if done.returncode==0:
                    self.assertEqual(b"",done.stderr)
                    value=json.loads(done.stdout)["result"]["value"]
                    self.assertIs(type(value),bool if operation=="compacted" else int)
                    self.assertEqual(False if operation=="compacted" else 0,value)
                else: self.assertEqual((125,b"",b""),result(done))
        self.path.write_bytes(b'{"type":"compacted"}\n')
        with self.path.open("rb",buffering=0) as handle:
            handle.read(3)
            for prefix in ("/dev/fd","/proc/self/fd"):
                if not Path(prefix).exists(): continue
                payload={"path":f"{prefix}/{handle.fileno()}"}
                done=subprocess.run([str(self.entry.with_name("moru-hook-native")),str(self.entry),
                    "--doc-transcript-probe","compacted"], input=json.dumps(payload).encode(),
                    env=self.env,cwd=self.project,capture_output=True,pass_fds=(handle.fileno(),),timeout=8)
                self.assertEqual((125,b"",b""),result(done))
                self.assertEqual(3,os.lseek(handle.fileno(),0,os.SEEK_CUR))

    def test_bridge_rejects_malformed_packets_and_preserves_noninteger_profiles(self):
        self.path.write_bytes(b"a\n"+b"x"*70000)
        for value in (None,{}, {"value":1,"extra":0},{"value":True},{"value":-1}):
            with patch("support.native_doc_transcript.NativeProbe.request",return_value=value):
                self.assertIsNone(NativeDocTranscript.aligned(self.path,0))
        for fallback in (True,1.0,10**100):
            expected=self.original("aligned_size",self.path,fallback)
            with patch.dict(os.environ,self.env,clear=True):
                actual=reference._aligned_size(self.path,fallback)
            self.assertEqual(expected,actual); self.assertIs(type(expected),type(actual))

    def test_optional_availability_failures_preserve_original_results_and_order(self):
        for error in (PermissionError("unsearchable home"),RuntimeError("no home"),ValueError("bad home")):
            with patch("support.native_doc_transcript.NativeProbe.available",side_effect=error):
                self.assertFalse(reference._compacted_before(self.path))
                self.assertEqual(0,reference._aligned_size(self.path))
                self.assertFalse(reference._due_after_compaction({"transcript_bytes":0},self.path))
                # An invalid offset suppresses even invalid redelivery coercion.
                self.assertFalse(reference._due_after_compaction({"transcript_bytes":None,"redeliveries":"bad"},self.path))
        self.path.write_bytes(b'{"type":"compacted"}\n')
        with patch("support.native_doc_transcript.NativeProbe.available",side_effect=PermissionError("home")):
            self.assertTrue(reference._compacted_before(self.path))
            with self.assertRaises(ValueError):
                reference._due_after_compaction({"transcript_bytes":0,"redeliveries":"bad"},self.path)

    def test_search_only_ancestor_does_not_advance_partial_line_offset(self):
        directory=self.base/"search-only"; directory.mkdir()
        path=directory/"partial.jsonl"; path.write_bytes(b'partial compaction row')
        try:
            directory.chmod(0o111)
            expected=self.original("aligned_size",path,0)
            self.assertEqual(0,expected)
            with patch.dict(os.environ,self.env,clear=True):
                self.assertEqual(expected,reference._aligned_size(path,0))
            try: list(directory.iterdir())
            except PermissionError:
                self.assertIsNone(self.native("aligned",path,0))
            else:
                self.assertEqual(expected,self.native("aligned",path,0))
        finally: directory.chmod(0o700)

    def test_actual_native_scan_preserves_shared_delivery_markers_and_budgets(self):
        outcomes=[]
        for native in (False,True):
            fixture=delivery_fixtures.DeliveryTests(); fixture.setUp()
            try:
                env={**self.env,"MORU_LAUNCHER_BACKEND":"auto" if native else "python"}
                with patch.dict(os.environ,env,clear=True):
                    texts=[fixture._deliver(),fixture._deliver()]
                    for _ in range(reference.MAX_REDELIVERIES+1):
                        fixture._append({"type":"system","subtype":"compact_boundary"})
                        texts.extend((fixture._deliver(),fixture._deliver()))
                    marker=json.loads((fixture.evidence.parent/reference.MARKER).read_text())
                self.assertEqual(reference.MAX_REDELIVERIES,marker["redeliveries"])
                self.assertTrue(texts[0]); self.assertFalse(texts[1]); self.assertFalse(texts[-1])
                outcomes.append((texts,marker))
            finally: fixture.doCleanups()
        self.assertEqual(outcomes[0],outcomes[1])

    def test_actual_native_scan_preserves_agy_checkpoint_delivery(self):
        outcomes=[]
        for native in (False,True):
            fixture=agy_fixtures.AgyHookTests(); fixture.setUp()
            try:
                env={**self.env,"MORU_LAUNCHER_BACKEND":"auto" if native else "python"}
                with patch.dict(os.environ,env,clear=True):
                    first=fixture._hook(); self.assertTrue(first)
                    self.assertEqual({},fixture._hook())
                    fixture._append(agy_fixtures.CHECKPOINT,fixture._read_call(agy_fixtures.CORE))
                    if native:
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            results = [future.result(timeout=8) for future in
                                       (pool.submit(fixture._hook), pool.submit(fixture._hook))]
                        self.assertEqual(1, sum(bool(answer) for answer in results))
                        after = next(answer for answer in results if answer)
                    else:
                        after = fixture._hook()
                    self.assertTrue(after)
                    self.assertEqual({},fixture._hook())
                    marker=(fixture.evidence.parent/reference.MARKER).read_bytes()
                    outcomes.append((first,after,marker))
            finally: fixture.doCleanups()
        self.assertEqual(outcomes[0],outcomes[1])

    def test_agy_native_redelivery_declines_initial_and_upgrades_legacy_marker(self):
        fixture = agy_fixtures.AgyHookTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        marker = fixture.evidence.parent / reference.MARKER
        raw = {"evidence": str(fixture.evidence), "transcript": str(fixture.transcript),
               "limit": 3, "inline_limit": 8192, "total_limit": 24576, "temporary": "d" * 32}

        def probe():
            return self.raw("agy-redelivery", raw)

        self.assertEqual((125, b"", b""), result(probe()))
        self.assertFalse(marker.exists())
        lock = marker.with_name(marker.name + ".lock")
        self.assertFalse(lock.exists())
        old = json.dumps({"delivered": [agy_fixtures.CORE]}).encode()
        marker.write_bytes(old)
        foreign_lock = self.base / "foreign.lock"
        foreign_lock.write_bytes(b"external")
        lock.symlink_to(foreign_lock)
        self.assertEqual((125, b"", b""), result(probe()))
        self.assertEqual(b"external", foreign_lock.read_bytes())
        self.assertEqual(old, marker.read_bytes())
        lock.unlink()
        temporary = marker.with_name(f"{marker.name}.{raw['temporary']}.tmp")
        temporary.write_bytes(b"another writer")
        previous_umask = os.umask(0o027)
        try:
            failed = probe()
        finally:
            os.umask(previous_umask)
        self.assertEqual(0o640, lock.stat().st_mode & 0o777)
        self.assertEqual((0, b""), (failed.returncode, failed.stderr))
        self.assertEqual({"write_failed": True}, json.loads(failed.stdout)["result"]["value"])
        self.assertEqual(old, marker.read_bytes())
        self.assertEqual(b"another writer", temporary.read_bytes())
        temporary.unlink()

        with patch.dict(os.environ, self.env, clear=True), patch.object(
                reference, "_deliver", side_effect=AssertionError("legacy delivery")):
            self.assertEqual({}, fixture._hook())
        self.assertEqual({"delivered": [agy_fixtures.CORE], "transcript_bytes": 0, "redeliveries": 0},
                         json.loads(marker.read_bytes()))
        with fixture.transcript.open("wb") as handle:
            handle.truncate(4 * 1024 * 1024 + 1)
        before = marker.read_bytes()
        self.assertEqual((125, b"", b""), result(probe()))
        self.assertEqual(before, marker.read_bytes())

    def test_agy_contended_native_lock_falls_back_and_rereads_after_python_writer(self):
        fixture = agy_fixtures.AgyHookTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        marker = fixture.evidence.parent / reference.MARKER
        lock = marker.with_name(marker.name + ".lock")
        declined = Event()

        def observe_decline(*args):
            value = agy_redelivery(*args)
            self.assertIsNone(value)
            declined.set()
            return value

        with patch.dict(os.environ, self.env, clear=True), ThreadPoolExecutor(max_workers=1) as pool:
            self.assertTrue(fixture._hook())
            fixture._append(agy_fixtures.CHECKPOINT)
            before = marker.read_bytes()
            with patch("support.native_doc_transcript.agy_redelivery", side_effect=observe_decline), patch.object(
                    reference, "_deliver", wraps=reference._deliver) as fallback:
                with lock.open("a") as handle:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    follower = pool.submit(fixture._hook)
                    self.assertTrue(declined.wait(5))
                    self.assertEqual(before, marker.read_bytes())
                    reference._write_marker_python(marker, [], fixture.transcript.stat().st_size, 1)
                    after = marker.read_bytes()
                self.assertEqual({}, follower.result(timeout=8))
                fallback.assert_called_once()
            self.assertEqual(after, marker.read_bytes())

    def test_agy_preparation_does_not_need_manifest_for_skip_or_upgrade(self):
        fixture = agy_fixtures.AgyHookTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        evidence, transcript = fixture.evidence, fixture.transcript
        marker = evidence.with_name(reference.MARKER)
        evidence.write_text("{", encoding="utf-8")
        with patch.dict(os.environ, self.env, clear=True):
            self.assertIsNone(agy_delivery_preparation(evidence, transcript, 3))
            self.assertFalse(marker.exists())
            for original, action in (({"delivered": [], "transcript_bytes": 0}, "skip"),
                                     ({"delivered": [agy_fixtures.CORE]}, "upgrade")):
                with self.subTest(action=action):
                    marker.write_text(json.dumps(original), encoding="utf-8")
                    before = marker.read_bytes()
                    expected = reference._delivery_plan_python(marker, transcript, 3)
                    self.assertEqual(action, expected["action"])
                    self.assertEqual((expected, None), agy_delivery_preparation(evidence, transcript, 3))
                    self.assertEqual(before, marker.read_bytes())

    def test_agy_prepared_first_delivery_respects_reuse_and_compaction(self):
        for reused, compacted, expected_docs in (
            ([agy_fixtures.CORE], False, [agy_fixtures.OTHER]),
            ([agy_fixtures.CORE], True, [agy_fixtures.CORE, agy_fixtures.OTHER]),
            ([agy_fixtures.CORE, agy_fixtures.OTHER], False, []),
        ):
            with self.subTest(reused=reused, compacted=compacted):
                fixture = agy_fixtures.AgyHookTests()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                marker = fixture.evidence.parent / reference.MARKER
                if compacted:
                    fixture._append(agy_fixtures.CHECKPOINT)
                else:
                    # A proven reused document must not be read at all.
                    (fixture.rules / agy_fixtures.CORE).write_bytes(b"\xff")
                with patch.object(reference, "required_doc_reuse", return_value={"reused": reused}) as reuse:
                    with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                        expected = fixture._hook()
                        expected_marker = marker.read_bytes()
                    marker.unlink()
                    with patch.dict(os.environ, self.env, clear=True), patch.multiple(
                            reference, _read_docs=unittest.mock.DEFAULT, _delivery_plan=unittest.mock.DEFAULT,
                            _delivery_manifest=unittest.mock.DEFAULT, _compacted_before=unittest.mock.DEFAULT) as old:
                        for call in old.values():
                            call.side_effect = AssertionError("legacy preparation or delivery")
                        self.assertEqual(expected, fixture._hook())
                        for call in old.values():
                            call.assert_not_called()
                    self.assertEqual([fixture.evidence, fixture.evidence],
                                     [call.args[0] for call in reuse.call_args_list])
                self.assertEqual(expected_marker, marker.read_bytes())
                stored = json.loads(expected_marker)
                self.assertEqual(expected_docs, stored["delivered"])
                self.assertEqual(0, stored["redeliveries"])

    def test_agy_prepared_first_delivery_does_not_repeat_uncertain_write(self):
        fixture = agy_fixtures.AgyHookTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = subprocess.run

        def lose_reply(argv, *args, **kwargs):
            completed = original(argv, *args, **kwargs)
            if argv[-1] == "agy-prepared-delivery":
                self.assertEqual(0, completed.returncode)
                self.assertTrue(json.loads(completed.stdout)["result"]["value"]["text"])
                raise subprocess.TimeoutExpired(argv, 10)
            return completed

        with patch.dict(os.environ, self.env, clear=True), patch(
                "support.native_probe_transport.subprocess.run", side_effect=lose_reply), patch.object(
                reference, "_read_docs", side_effect=AssertionError("unsafe compatibility retry")) as fallback:
            self.assertEqual({}, fixture._hook())
            fallback.assert_not_called()
        marker = fixture.evidence.parent / reference.MARKER
        self.assertEqual([agy_fixtures.CORE, agy_fixtures.OTHER], json.loads(marker.read_bytes())["delivered"])

    def test_agy_redelivery_acknowledgement_loss_never_retries_and_releases_lock(self):
        fixture = agy_fixtures.AgyHookTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with patch.dict(os.environ, self.env, clear=True):
            self.assertTrue(fixture._hook())
            fixture._append(agy_fixtures.CHECKPOINT)
            run = subprocess.run

            def lose_acknowledgement(argv, *args, **kwargs):
                completed = run(argv, *args, **kwargs)
                if argv[-1] == "agy-redelivery":
                    self.assertEqual(0, completed.returncode)
                    self.assertTrue(json.loads(completed.stdout)["result"]["value"]["text"])
                    raise subprocess.TimeoutExpired(argv, 10)
                return completed

            with patch("support.native_probe_transport.subprocess.run", side_effect=lose_acknowledgement), patch.object(
                    reference, "_deliver", side_effect=AssertionError("unsafe compatibility retry")) as fallback:
                self.assertEqual({}, fixture._hook())
            fallback.assert_not_called()
            marker = fixture.evidence.parent / reference.MARKER
            self.assertEqual(1, json.loads(marker.read_bytes())["redeliveries"])
            with marker.with_name(marker.name + ".lock").open("a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual({}, fixture._hook())


if __name__=="__main__": unittest.main()
