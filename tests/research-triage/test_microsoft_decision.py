"""Exercise the optional adapter through its CLI entrypoint, without paid calls."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import shlex
import tempfile
import time
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

try:
    from native_launcher_support import NATIVE, install
except ModuleNotFoundError as error:
    if error.name != "native_launcher_support":
        raise
    NATIVE = None
else:
    from native_pretool_support import environment

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "research-triage" / "microsoft_decision.py"
SPEC = importlib.util.spec_from_file_location("microsoft_decision", SCRIPT)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def response(relevance=0.9, kind="review", cost=0.0001):
    return {
        "model": "inception/mercury-decide-test-snapshot", "provider": "Inception",
        "answers": {
            "relevant": {"type": "noul", "noul": relevance},
            "source_kind": {
                "type": "choice", "choice": kind,
                "probabilities": {option: float(option == kind) for option in (
                    "official", "paper", "review", "marketing", "other",
                )},
            },
        },
        "usage": {"cost": cost},
    }


def source(identifier="a", text="Users cannot find saved notes."):
    return {"id": identifier, "url": "https://example.org/notes", "title": "Interviews", "text": text}


class OpenRouterDecisionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.input = self.root / "input.json"
        self.cache = self.root / "cache"
        self.payload = {"query": "What problems should a note-taking product solve?", "sources": [source()]}
        self.environment = patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.key_file = self.root / "research.env"
        key_files = patch.object(adapter, "KEY_FILES", (self.key_file,))
        key_files.start()
        self.addCleanup(key_files.stop)
        network = patch.object(adapter, "open_provider_request", side_effect=AssertionError("unmocked network"))
        network.start()
        self.addCleanup(network.stop)

    def run_cli(self, *flags):
        self.input.write_text(json.dumps(self.payload), encoding="utf-8")
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = adapter.main([
                "--input", str(self.input), "--cache-dir", str(self.cache), *flags,
            ])
        return status, json.loads(output.getvalue()) if output.getvalue() else None, errors.getvalue()

    def test_default_has_no_network_or_writes_even_with_a_key(self):
        with patch.object(adapter, "send_request", side_effect=AssertionError("paid call")), \
                patch.object(adapter, "openrouter_api_key", side_effect=AssertionError("unneeded credential read")):
            status, result, _ = self.run_cli()
        self.assertEqual(0, status)
        self.assertEqual(0, result["network_calls"])
        self.assertEqual("unscored", result["results"][0]["status"])
        self.assertFalse(self.cache.exists())

    def test_native_cache_plan_reuses_existing_hash_and_scrubs_child_credentials(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        native = home / ".moru/bin/moru-hook-native"
        binary = native.with_name("native-fixture")
        native.rename(binary)
        observed = self.root / "decision-calls"
        native.write_text(
            "#!/bin/sh\n"
            'if [ "${2-}" = --decision-cache-probe ]; then\n'
            '    [ -z "${OPENROUTER_API_KEY+x}" ] || exit 80\n'
            f"    printf '%s\\n' \"$3\" >> {shlex.quote(str(observed))}\n"
            "fi\n"
            f'exec {shlex.quote(str(binary))} "$@"\n',
            encoding="utf-8",
        )
        native.chmod(0o755)
        self.payload = {"query": '검색 "질문" 😀', "sources": [
            {**source("one", "한글\n짝수\t😀"), "published_at": "2026-01-01", "required": True},
            source("two", "另一个"),
        ]}
        requests = [adapter.request_for(self.payload["query"], row, adapter.MODEL)
                    for row in self.payload["sources"]]
        expected = [[adapter.cache_key(request), len(json.dumps(
            request, ensure_ascii=False, sort_keys=True, allow_nan=False,
        ).encode())] for request in requests]
        saved = {**adapter.validate_response(response()), "evaluated_at": time.time()}
        adapter.save_cached(self.cache / (expected[0][0] + ".json"), expected[0][0], saved)
        env = {**environment(self.root, ROOT), "OPENROUTER_API_KEY": "fixture-only"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(adapter, "openrouter_api_key", side_effect=AssertionError("credential read")), \
                patch.object(adapter, "cache_key", side_effect=AssertionError("Python hashing")):
            self.assertEqual(expected, adapter._cache_plan(self.payload, adapter.MODEL))
            status, result, _ = self.run_cli()
        self.assertEqual(0, status)
        self.assertEqual(0, result["network_calls"])
        self.assertEqual(["cached", "unscored"], [row["status"] for row in result["results"]])
        self.assertEqual(["prepare", "read-prepare-input", "read-only-report"],
                         observed.read_text().splitlines())

    def test_native_read_only_report_matches_legacy_without_python_evaluation(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        env = environment(self.root, ROOT)
        python = {**env, "MORU_LAUNCHER_BACKEND": "python"}
        repeated = source("one", "한글 😀")
        self.payload["sources"] = [repeated, source("missing", "Different"),
                                   {**repeated, "id": "required", "required": True}]
        with patch.dict(os.environ, python, clear=True):
            missing = self.run_cli()
        with patch.dict(os.environ, env, clear=True), \
                patch.object(adapter, "evaluate", side_effect=AssertionError("Python evaluation")), \
                patch.object(adapter, "openrouter_api_key", side_effect=AssertionError("credential read")):
            self.assertEqual(self.run_cli(), missing)
        self.assertFalse(self.cache.exists())
        request = adapter.request_for(self.payload["query"], repeated, adapter.MODEL)
        key = adapter.cache_key(request)
        entry = adapter.validate_response({**response(-0.0), "usage": {"cost": 2**64 + 1}})
        with patch.dict(os.environ, python, clear=True):
            adapter.save_cached(self.cache / f"{key}.json", key, {**entry, "evaluated_at": time.time()})
            cached = self.run_cli()
            refreshed = self.run_cli("--refresh")
        with patch.dict(os.environ, env, clear=True), \
                patch.object(adapter, "evaluate", side_effect=AssertionError("Python evaluation")), \
                patch.object(adapter, "openrouter_api_key", side_effect=AssertionError("credential read")):
            self.assertEqual(json.dumps(self.run_cli(), ensure_ascii=False),
                             json.dumps(cached, ensure_ascii=False))
            # A regular cache directory is unnecessary when refresh ignores it.
            previous_cache = self.cache.with_name("previous-cache")
            self.cache.rename(previous_cache)
            self.cache.symlink_to(previous_cache, target_is_directory=True)
            self.assertEqual(self.run_cli("--refresh"), refreshed)
        self.assertEqual(cached[1]["cache_hits"], 2)
        self.assertEqual(cached[1]["ranked_ids"], ["missing", "required", "one"])
        with patch.dict(os.environ, env, clear=True), patch.object(adapter, "evaluate", wraps=adapter.evaluate) as fallback:
            self.assertEqual(self.run_cli(), cached)
        fallback.assert_called_once()

    def test_native_read_only_report_restarts_in_python_if_cache_payload_exceeds_cap(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        env = environment(self.root, ROOT)
        repeated = source("one", "Same evidence")
        self.payload["sources"] = [{**repeated, "id": str(index)} for index in range(5)]
        key = adapter.cache_key(adapter.request_for(self.payload["query"], repeated, adapter.MODEL))
        with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            path = self.cache / f"{key}.json"
            entry = {**adapter.validate_response(response()), "evaluated_at": time.time()}
            adapter.save_cached(path, key, {**entry, "unused": "x" * (220 * 1024)})
            expected = self.run_cli()
        with patch.dict(os.environ, env, clear=True), \
                patch.object(adapter, "evaluate", wraps=adapter.evaluate) as fallback, \
                patch.object(adapter, "send_request", side_effect=AssertionError("provider call")):
            self.assertEqual(self.run_cli(), expected)
        self.assertEqual(expected[1]["cache_hits"], 5)
        fallback.assert_called_once()

    def test_native_cli_reads_input_without_python_and_preserves_source_order(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        self.payload["query"] = '검색 "질문" 😀'
        self.payload["sources"] = [
            {**source("one", "한글\n😀"), "published_at": "", "ignored": {"content": "unused"}},
            {**source("two", "두 번째"), "required": True},
        ]
        env = environment(self.root, ROOT)
        with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = self.run_cli()
        read_text = Path.read_text

        def forbid_input_read(path, *args, **kwargs):
            self.assertNotEqual(path, self.input, "Python input read")
            return read_text(path, *args, **kwargs)

        with patch.dict(os.environ, env, clear=True), \
                patch.object(Path, "read_text", forbid_input_read), \
                patch.object(adapter, "validate_input", side_effect=AssertionError("Python validation")), \
                patch.object(adapter, "cache_key", side_effect=AssertionError("Python hashing")), \
                patch.object(adapter, "openrouter_api_key", side_effect=AssertionError("credential read")):
            self.assertEqual(self.run_cli(), expected)
            ordinary = adapter._read_input_native(self.input, adapter.MODEL)
            encoded = json.dumps(self.payload, ensure_ascii=False, indent=2)
            self.input.write_bytes(('{\r\n  "query": null,' + encoded[1:].replace("\n", "\r\n")).encode())
            self.assertIsNotNone(ordinary)
            self.assertEqual(adapter._read_input_native(self.input, adapter.MODEL), ordinary)
        self.assertEqual([row["id"] for row in expected[1]["results"]], ["one", "two"])
        self.assertFalse(self.cache.exists())

    def test_native_cli_uses_legacy_reader_for_symlink_and_oversized_input(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        env = environment(self.root, ROOT)
        target = self.root / "target.json"
        self.input.symlink_to(target)
        for oversized in (False, True):
            with self.subTest(oversized=oversized):
                if oversized:
                    self.input.unlink()
                    self.payload["ignored"] = "x" * (1024 * 1024)
                self.input.write_text(json.dumps(self.payload), encoding="utf-8")
                with patch.dict(os.environ, env, clear=True):
                    self.assertIsNone(adapter._read_input_native(self.input, adapter.MODEL))
                    actual = self.run_cli()
                with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                    self.assertEqual(actual, self.run_cli())
                self.assertEqual(actual[0], 0)
        self.assertFalse(self.cache.exists())

    def test_native_decision_order_is_stable_and_fallback_never_replays_provider(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        env = {**environment(self.root, ROOT), "OPENROUTER_API_KEY": "fixture-only"}
        self.payload["sources"] = [
            source("optional-high", "Optional high"),
            source("unscored-first", "Unavailable first"),
            {**source("required-zero", "Required zero"), "required": True},
            {**source("required-high", "Required high"), "required": True},
            source("unscored-last", "Unavailable last"),
            source("optional-tie", "Optional tie"),
        ]
        scenarios = [response(.9), ValueError("offline"), response(-0.0),
                     response(.2), ValueError("offline"), response(.9)]
        decisions = ["required-high", "unscored-first", "required-zero", "unscored-last",
                     "optional-high", "optional-tie"]
        original = adapter.NativeProbe.request
        for reject in (False, True):
            observed = []
            def observe(protocol, action, payload):
                result = original(protocol, action, payload)
                observed.append((action, result is not None))
                return {"order": [0, 0], "unscored": 1} if reject and action == "summarize" else result
            with self.subTest(reject=reject), patch.dict(os.environ, env, clear=True), \
                    patch.object(adapter.NativeProbe, "request", side_effect=observe), \
                    patch.object(adapter, "send_request", side_effect=scenarios) as provider:
                status, result, _ = self.run_cli("--execute", "--refresh")
            self.assertEqual(status, 0)
            self.assertEqual(provider.call_count, len(scenarios))
            self.assertEqual(observed, [("read-prepare-input", True)]
                             + [("validate-response", True), ("cache-write-support", True),
                                ("write-cached-file", True)] * 4
                             + [("summarize", True)])
            self.assertEqual(result["ranked_ids"], decisions)
            self.assertEqual(result["unscored"], 2)
            self.assertEqual([row["id"] for row in result["results"]],
                             [row["id"] for row in self.payload["sources"]])

    def test_native_input_preserves_first_error_before_any_effect(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        env = environment(self.root, ROOT)
        cases = [
            ([], "Input needs a query and sources"),
            ({"query": " \x1c\u2003", "sources": [0]}, "Input needs a nonempty query and a sources array"),
            ({"query": "Notes", "sources": {}}, "Input needs a nonempty query and a sources array"),
            ({"query": "Notes", "sources": [False]}, "Each source must be an object"),
            ({"query": "Notes", "sources": [source(), {**source(), "text": "\x1c", "required": 1}]},
             "Each source needs id, url, title, and text"),
            ({"query": "Notes", "sources": [source(), {**source(), "required": 1}]},
             "Source ids must be unique"),
            ({"query": "Notes", "sources": [{**source(), "required": 1, "published_at": False}]},
             "required must be a boolean"),
            ({"query": "Notes", "sources": [{**source(), "published_at": None}]},
             "published_at must be a string"),
        ]
        for payload, message in cases:
            with self.subTest(message=message), patch.dict(os.environ, env, clear=True), \
                    patch.object(adapter, "openrouter_api_key", side_effect=AssertionError("credential read")), \
                    patch.object(adapter, "read_cached", side_effect=AssertionError("cache read")):
                with self.assertRaises(ValueError) as baseline:
                    adapter.validate_input(payload)
                with self.assertRaises(ValueError) as native:
                    adapter._cache_plan(payload, adapter.MODEL, validate=True)
                self.assertEqual(str(baseline.exception), message)
                self.assertEqual(str(native.exception), message)
                self.payload = payload
                result = self.run_cli("--execute")
                with patch.object(adapter.NativeProbe, "request", return_value=None):
                    self.assertEqual(self.run_cli("--execute"), result)
                self.assertEqual(result, (2, None, "Invalid or unreadable research input\n"))
        self.assertFalse(self.cache.exists())

    def test_native_request_size_preserves_inclusive_utf8_boundary(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        base = source("exact", "한😀")
        request = adapter.request_for(self.payload["query"], base, adapter.MODEL)
        size = len(json.dumps(request, ensure_ascii=False, sort_keys=True, allow_nan=False).encode())
        base["text"] += "x" * (adapter.MAX_REQUEST_BYTES - size)
        self.payload["sources"] = [base, source("over", base["text"] + "한")]
        env = {**environment(self.root, ROOT), "OPENROUTER_API_KEY": "fixture-only"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(adapter, "cache_key", side_effect=AssertionError("Python hashing")), \
                patch.object(adapter, "send_request", return_value=response()) as call:
            status, result, _ = self.run_cli("--execute")
        self.assertEqual(0, status)
        self.assertEqual(1, call.call_count)
        self.assertEqual("scored", result["results"][0]["status"])
        self.assertEqual("request_too_large", result["results"][1]["reason"])

    def test_execute_without_key_preserves_sources_without_calls(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            with patch.object(adapter, "send_request") as call:
                status, result, _ = self.run_cli("--execute")
        self.assertEqual(0, status)
        call.assert_not_called()
        self.assertEqual("missing_key", result["results"][0]["reason"])
        self.assertFalse(self.cache.exists())

    def test_unset_variable_falls_back_to_the_user_env_file(self):
        self.key_file.write_text("# OpenRouter\nexport OPENROUTER_API_KEY='file-key'\n", encoding="utf-8")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            self.assertEqual("file-key", adapter.openrouter_api_key())
            with patch.object(adapter, "send_request", return_value=response()) as call:
                status, result, errors = self.run_cli("--execute")
        self.assertEqual(0, status)
        self.assertEqual("file-key", call.call_args.args[1])
        self.assertEqual("scored", result["results"][0]["status"])
        self.assertNotIn("file-key", json.dumps(result) + errors)

    def test_environment_wins_and_an_empty_file_value_is_no_key(self):
        self.key_file.write_text("OPENROUTER_API_KEY=file-key\n", encoding="utf-8")
        self.assertEqual("test-key", adapter.openrouter_api_key())
        self.key_file.write_text("export OPENROUTER_API_KEY=\n", encoding="utf-8")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            self.assertEqual("", adapter.openrouter_api_key())

    def test_http_contract_and_persistent_reuse_via_cli(self):
        with patch.object(adapter, "open_provider_request", return_value=io.BytesIO(
            json.dumps(response()).encode(),
        )) as http:
            status, first, _ = self.run_cli("--execute")
        self.assertEqual(0, status)
        request = http.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual("POST", request.get_method())
        self.assertEqual("https://openrouter.ai/api/alpha/decisions", request.full_url)
        self.assertEqual("Bearer test-key", request.get_header("Authorization"))
        self.assertEqual("inception/mercury-decide:free", body["model"])
        self.assertEqual({"allow_fallbacks": False}, body["provider"])
        self.assertEqual(self.payload["query"], body["state"]["query"])
        self.assertEqual(self.payload["sources"][0]["text"], body["state"]["source"]["text"])
        self.assertEqual({"relevant", "source_kind"}, set(body["questions"]))
        with patch.object(adapter, "send_request", side_effect=AssertionError("repeated call")):
            _, second, _ = self.run_cli("--execute")
        self.assertEqual(1, first["network_calls"])
        self.assertEqual(0, second["network_calls"])
        self.assertEqual(1, second["cache_hits"])
        self.assertIsNone(second["new_reported_cost_usd"])
        self.assertEqual(first["results"][0]["answers"], second["results"][0]["answers"])
        self.assertEqual("inception/mercury-decide-test-snapshot", second["results"][0]["response_model"])
        stored = next(self.cache.glob("*.json")).read_text()
        self.assertNotIn("test-key", stored)
        self.assertNotIn("Users cannot find saved notes.", stored)
        self.assertEqual(0o600, next(self.cache.glob("*.json")).stat().st_mode & 0o777)

    def test_changed_decision_inputs_invalidate_only_the_affected_source(self):
        for field in ("query", "text", "url", "title", "published_at"):
            with self.subTest(field=field):
                self.cache = self.root / field
                self.payload = {"query": "Notes", "sources": [source("a"), source("b", "Cannot sync.")]}
                with patch.object(adapter, "send_request", return_value=response()) as call:
                    self.run_cli("--execute")
                    if field == "query":
                        self.payload["query"] = "Search"
                    else:
                        self.payload["sources"][0][field] = "Changed"
                    _, result, _ = self.run_cli("--execute")
                expected = 2 if field == "query" else 1
                self.assertEqual(expected, result["network_calls"])
                self.assertEqual(2 - expected, result["cache_hits"])
                self.assertEqual(2 + expected, call.call_count)

    def test_ids_required_flags_and_retrieval_time_do_not_repeat_inference(self):
        with patch.object(adapter, "send_request", return_value=response()) as call:
            self.run_cli("--execute")
            self.payload["sources"][0].update(id="renamed", required=True, retrieved_at="later")
            _, result, _ = self.run_cli("--execute")
        self.assertEqual(1, call.call_count)
        self.assertEqual("renamed", result["results"][0]["id"])
        self.assertTrue(result["results"][0]["required"])
        self.assertEqual("cached", result["results"][0]["status"])

    def test_known_model_rubric_and_schema_changes_invalidate_decisions(self):
        for setting, replacement in (
            ("MODEL", adapter.MODEL + "-next"), ("CACHE_SCHEMA", 2),
            ("QUESTIONS", {**adapter.QUESTIONS, "relevant": {
                **adapter.QUESTIONS["relevant"], "instructions": "A different research criterion",
            }}),
        ):
            with self.subTest(setting=setting):
                self.cache = self.root / setting
                with patch.object(adapter, "send_request", return_value=response()) as call:
                    self.run_cli("--execute")
                    with patch.object(adapter, setting, replacement):
                        _, result, _ = self.run_cli("--execute")
                self.assertEqual(2, call.call_count)
                self.assertEqual(1, result["network_calls"])

    def test_paid_model_is_explicit_and_has_a_separate_cache_key(self):
        with patch.object(adapter, "send_request", return_value=response()) as call:
            _, free, _ = self.run_cli("--execute")
            _, paid, _ = self.run_cli("--execute", "--model", adapter.PAID_MODEL)
            _, cached, _ = self.run_cli("--execute", "--model", adapter.PAID_MODEL)
        self.assertEqual(2, call.call_count)
        self.assertEqual(adapter.MODEL, free["model"])
        self.assertEqual(adapter.PAID_MODEL, paid["model"])
        self.assertEqual(adapter.PAID_MODEL, call.call_args.args[0]["model"])
        self.assertEqual(1, cached["cache_hits"])
        self.assertEqual(2, len(list(self.cache.glob("*.json"))))

    def test_refresh_deduplicates_identical_sources_within_a_batch(self):
        self.payload["sources"] = [source("a"), source("b")]
        with patch.object(adapter, "send_request", return_value=response()) as call:
            _, result, _ = self.run_cli("--execute", "--refresh")
        self.assertEqual(1, call.call_count)
        self.assertEqual(1, result["cache_hits"])
        self.assertEqual(["a", "b"], [item["id"] for item in result["results"]])

    def test_expired_and_future_dated_entries_are_not_reused(self):
        with patch.object(adapter.time, "time", return_value=1_000_000):
            with patch.object(adapter, "send_request", return_value=response()):
                self.run_cli("--execute")
        for current_time in (1_086_400, 999_999):
            with self.subTest(now=current_time):
                with patch.object(adapter.time, "time", return_value=current_time):
                    _, result, _ = self.run_cli()
                self.assertEqual(0, result["cache_hits"])
                self.assertEqual("unscored", result["results"][0]["status"])

    def test_corrupt_cache_is_a_miss_without_paid_recovery_by_default(self):
        with patch.object(adapter, "send_request", return_value=response()):
            self.run_cli("--execute")
        path = next(self.cache.glob("*.json"))
        for contents in ("{", "[]", '{"schema":1}', '{"schema":2,"key":"wrong"}'):
            path.write_text(contents)
            with patch.object(adapter, "send_request", side_effect=AssertionError("paid recovery")):
                _, result, _ = self.run_cli()
            self.assertEqual(1, result["unscored"])

    def test_limit_and_ranking_preserve_required_and_unscored_items(self):
        self.payload["sources"] = [source("low"), source("required", "Primary evidence."), source("unknown", "More.")]
        self.payload["sources"][1]["required"] = True
        with patch.object(adapter, "send_request", return_value=response(0.01)) as call:
            _, result, _ = self.run_cli("--execute", "--max-calls", "1")
        self.assertEqual(1, call.call_count)
        self.assertEqual(["low", "required", "unknown"], [item["id"] for item in result["results"]])
        self.assertEqual(["required", "unknown", "low"], result["ranked_ids"])
        self.assertEqual("call_limit", result["results"][2]["reason"])

    def test_partial_failure_resumes_without_repeating_successes(self):
        self.payload["sources"] = [source("a"), source("b", "Sync issues.")]
        failure = urllib.error.HTTPError(adapter.ENDPOINT, 429, "rate limit", {}, None)
        with patch.object(adapter, "send_request", side_effect=[response(), failure]) as call:
            _, first, _ = self.run_cli("--execute")
        self.assertEqual(2, call.call_count)
        self.assertEqual(1, first["unscored"])
        with patch.object(adapter, "send_request", return_value=response()) as call:
            _, resumed, _ = self.run_cli("--execute")
        self.assertEqual(1, call.call_count)
        self.assertEqual(1, resumed["cache_hits"])
        self.assertEqual(0, resumed["unscored"])

    def test_provider_failure_stops_new_calls_but_still_reads_cache(self):
        with patch.object(adapter, "send_request", return_value=response()):
            self.run_cli("--execute")
        self.payload["sources"] = [source("bad", "New source"), source("cached"), source("later", "Another source")]
        with patch.object(adapter, "send_request", side_effect=urllib.error.URLError("offline")) as call:
            _, result, _ = self.run_cli("--execute")
        self.assertEqual(1, call.call_count)
        self.assertEqual(["unscored", "cached", "unscored"], [item["status"] for item in result["results"]])

    def test_source_rejection_skips_only_that_item(self):
        self.payload["sources"] = [source("bad"), source("next", "Another source")]
        for code in (400, 413):
            with self.subTest(code=code):
                self.cache = self.root / str(code)
                error = urllib.error.HTTPError(adapter.ENDPOINT, code, "rejected", {}, None)
                with patch.object(adapter, "send_request", side_effect=[error, response()]) as call:
                    _, result, _ = self.run_cli("--execute")
                self.assertEqual(2, call.call_count)
                self.assertEqual(["unscored", "scored"], [item["status"] for item in result["results"]])
                self.assertEqual("source_rejected", result["results"][0]["reason"])
                self.assertEqual(code, result["results"][0]["http_status"])

    def test_systemic_http_errors_stop_further_calls(self):
        self.payload["sources"] = [source("bad"), source("next", "Another source")]
        for code in (401, 402, 403, 404, 429, 500, 503):
            with self.subTest(code=code):
                error = urllib.error.HTTPError(adapter.ENDPOINT, code, "unavailable", {}, None)
                with patch.object(adapter, "send_request", side_effect=error) as call:
                    _, result, _ = self.run_cli("--execute")
                self.assertEqual(1, call.call_count)
                self.assertEqual("provider_unavailable", result["results"][1]["reason"])

    def test_rounded_probabilities_are_preserved_and_cached(self):
        candidate = response()
        distribution = {"official": 0.33, "paper": 0.33, "review": 0.33, "marketing": 0, "other": 0}
        candidate["answers"]["source_kind"]["probabilities"] = distribution
        with patch.object(adapter, "send_request", return_value=candidate) as call:
            _, first, _ = self.run_cli("--execute")
            _, cached, _ = self.run_cli("--execute")
        self.assertEqual(1, call.call_count)
        self.assertEqual("scored", first["results"][0]["status"])
        self.assertEqual(distribution, cached["results"][0]["answers"]["source_kind"]["probabilities"])

    def test_invalid_response_does_not_stop_the_next_item(self):
        self.payload["sources"] = [source("bad"), source("next", "Another source")]
        candidate = response()
        candidate["answers"]["source_kind"]["probabilities"] = dict.fromkeys(
            candidate["answers"]["source_kind"]["probabilities"], 0.1,
        )
        with patch.object(adapter, "send_request", side_effect=[candidate, response()]) as call:
            _, result, _ = self.run_cli("--execute")
        self.assertEqual(2, call.call_count)
        self.assertEqual("invalid_response", result["results"][0]["reason"])
        self.assertEqual("scored", result["results"][1]["status"])

    def test_oversized_request_skips_without_spending_call_limit(self):
        self.payload["sources"] = [source("large", "가" * 10_000), source("next", "Short source")]
        with patch.object(adapter, "send_request", return_value=response()) as call:
            _, result, _ = self.run_cli("--execute", "--max-calls", "1")
        self.assertEqual(1, call.call_count)
        self.assertEqual("request_too_large", result["results"][0]["reason"])
        self.assertEqual("Short source", call.call_args.args[0]["state"]["source"]["text"])
        self.assertEqual("scored", result["results"][1]["status"])
        self.assertEqual(["large", "next"], result["ranked_ids"])

    def test_invalid_answers_do_not_become_cached_decisions(self):
        invalid = []
        for value in (float("nan"), 2, True):
            invalid.append(response(value))
        for field, value in (("choice", []), ("probabilities", {"review": 1})):
            candidate = response()
            candidate["answers"]["source_kind"][field] = value
            invalid.append(candidate)
        zero_distribution = response()
        zero_distribution["answers"]["source_kind"]["probabilities"] = {
            option: 0 for option in zero_distribution["answers"]["source_kind"]["probabilities"]
        }
        invalid.append(zero_distribution)
        invalid.extend([{}, {**response(), "model": ""}])
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with patch.object(adapter, "send_request", return_value=candidate):
                    status, result, _ = self.run_cli("--execute")
                self.assertEqual(0, status)
                self.assertEqual("invalid_response", result["results"][0]["reason"])
                self.assertFalse(self.cache.exists())

    def test_cache_write_failure_keeps_answer_and_stops_further_calls(self):
        self.payload["sources"].append(source("b", "Another source"))
        with patch.object(adapter, "send_request", return_value=response()) as call:
            with patch.object(adapter, "save_cached", side_effect=PermissionError()):
                _, result, _ = self.run_cli("--execute")
        self.assertEqual(1, call.call_count)
        self.assertEqual("scored", result["results"][0]["status"])
        self.assertEqual(["cache_write_failed"], result["warnings"])

    def test_invalid_input_fails_before_any_network_request(self):
        for change in ("duplicate", "empty_text", "required_type"):
            self.payload = {"query": "Notes", "sources": [source()]}
            if change == "duplicate":
                self.payload["sources"].append(copy.deepcopy(self.payload["sources"][0]))
            elif change == "empty_text":
                self.payload["sources"][0]["text"] = ""
            else:
                self.payload["sources"][0]["required"] = "yes"
            with patch.object(adapter, "send_request") as call:
                status, result, errors = self.run_cli("--execute")
            self.assertEqual(2, status)
            self.assertIsNone(result)
            self.assertIn("Invalid", errors)
            call.assert_not_called()

    def test_native_response_verdict_preserves_original_numbers_and_threshold(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        env = environment(self.root, ROOT)
        accepted = response(relevance=-0.0, cost=0)
        distribution = accepted["answers"]["source_kind"]["probabilities"]
        distribution["review"] = 1
        rejected = response(relevance=True)
        near = response()
        near["answers"]["source_kind"]["probabilities"]["review"] = 0.975
        nonfinite = response(cost=float("inf"))
        for item, available in ((accepted, True), (rejected, True), (near, False), (nonfinite, False)):
            def normalize():
                try:
                    return json.dumps(adapter.validate_response(item), allow_nan=False)
                except ValueError as error:
                    return str(error)
            with self.subTest(available=available):
                with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                    expected = normalize()
                with patch.dict(os.environ, env, clear=True), \
                        patch.object(adapter, "_response_verdict", wraps=adapter._response_verdict) as check, \
                        patch.object(adapter.NativeProbe, "request", wraps=adapter.NativeProbe.request) as probe:
                    actual = normalize()
                self.assertEqual(actual, expected)
                self.assertEqual(check.call_count, 1)
                self.assertEqual(probe.call_args.args[1], "validate-response")
                with patch.dict(os.environ, env, clear=True):
                    result = adapter.NativeProbe.request(*probe.call_args.args)
                self.assertEqual(result is not None, available)

    def test_unknown_cost_is_reported_without_an_estimate(self):
        with patch.object(adapter, "send_request", return_value=response(cost=None)):
            _, result, _ = self.run_cli("--execute")
        self.assertIsNone(result["new_reported_cost_usd"])
        self.assertFalse(result["cost_complete"])

    def test_native_cache_reuse_matches_schema_and_expiry_boundaries(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        env = environment(self.root, ROOT)
        original = adapter.NativeProbe.request
        entry = {"schema": adapter.CACHE_SCHEMA, "key": "sample", "evaluated_at": 90,
                 "result": {"response_model": "fixture", "reported_cost_usd": 0,
                            "answers": response(relevance=-0.0)["answers"]}}
        path = self.root / "cache-fixture.json"
        cases = (
            ({}, 100, 11, True, True),
            ({}, 90, 1, True, True),
            ({}, 100, 10, False, True),
            ({}, 89.9, 11, False, True),
            ({"key": "different"}, 100, 11, False, True),
            ({"schema": 2}, 100, 11, False, True),
            ({"schema": True}, 100, 11, True, True),
            ({"schema": 1.0}, 100, 11, True, True),
            ({"evaluated_at": True}, 100, 11, False, True),
            ({"result": {}}, 100, 11, False, True),
            ({"evaluated_at": 2**53}, 2**53 + 1, 2, True, False),
        )
        for updates, now, ttl, hit, supported in cases:
            with self.subTest(updates=updates, now=now, ttl=ttl):
                raw = json.dumps({**entry, **updates})
                path.write_text(raw, encoding="utf-8")
                modified = path.stat().st_mtime_ns
                observed = []
                def observe(protocol, action, payload):
                    verdict = original(protocol, action, payload)
                    observed.append((action, verdict is not None))
                    return verdict
                with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                    expected = adapter.read_cached(path, "sample", now, ttl)
                with patch.dict(os.environ, env, clear=True), \
                        patch.object(adapter.NativeProbe, "request", side_effect=observe):
                    actual = adapter.read_cached(path, "sample", now, ttl)
                self.assertEqual(actual is not None, hit)
                self.assertEqual(json.dumps(actual), json.dumps(expected))
                self.assertEqual(observed[0], ("validate-cached", supported))
                if supported:
                    self.assertEqual(len(observed), 1)
                self.assertEqual(path.read_text(encoding="utf-8"), raw)
                self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_native_cache_file_reads_are_bounded_and_preserve_python_fallback(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        env = environment(self.root, ROOT)
        self.cache.mkdir()
        key = "a" * 64
        path = self.cache / f"{key}.json"
        saved = {"response_model": "fixture", "reported_cost_usd": 0,
                 "answers": response(relevance=-0.0)["answers"]}
        content = json.dumps({"schema": adapter.CACHE_SCHEMA, "key": key, "evaluated_at": 90, "result": saved})
        path.write_text(content, encoding="utf-8")
        with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = adapter.read_cached(path, key, 100, 20)
        original_read = Path.read_text
        def forbid_cache_read(target, *args, **kwargs):
            if target == path:
                raise AssertionError("unexpected Python cache file read")
            return original_read(target, *args, **kwargs)
        with patch.dict(os.environ, env, clear=True), patch.object(Path, "read_text", forbid_cache_read):
            self.assertEqual(json.dumps(adapter.read_cached(path, key, 100, 20)), json.dumps(expected))
            self.assertIsNone(adapter.read_cached(path, key, 100, 10))
            path.unlink()
            self.assertIsNone(adapter.read_cached(path, key, 100, 20))

        target = self.cache / "legacy-content.json"
        target.write_text(content, encoding="utf-8")
        path.symlink_to(target)
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(adapter._read_cache_file_native(path, key, 100, 20))
            self.assertEqual(adapter.read_cached(path, key, 100, 20), expected)
        self.assertTrue(path.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), content)
        path.unlink()
        large = content + " " * (256 * 1024)
        path.write_text(large, encoding="utf-8")
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(adapter._read_cache_file_native(path, key, 100, 20))
            self.assertEqual(adapter.read_cached(path, key, 100, 20), expected)
        self.assertEqual(path.read_text(encoding="utf-8"), large)

    def test_native_cache_replace_matches_bytes_mode_and_failed_cleanup(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        env = environment(self.root, ROOT)
        key = "a" * 64
        path = self.cache / f"{key}.json"
        item = {"response_model": "한글😀", "evaluated_at": 12, "reported_cost_usd": -0.0}
        with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            adapter.save_cached(path, key, item)
        expected = path.read_bytes()
        path.write_text("previous", encoding="utf-8")
        path.chmod(0o644)
        with patch.dict(os.environ, env, clear=True), \
                patch.object(adapter.tempfile, "mkstemp", side_effect=AssertionError("Python write replay")):
            adapter.save_cached(path, key, item)
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.unlink()
            path.mkdir()
            with self.assertRaises(OSError):
                adapter.save_cached(path, key, item)
            self.assertTrue(path.is_dir())
        self.assertEqual(list(self.cache.glob(".decision-*")), [])

    def test_legacy_launcher_without_cache_write_uses_python(self):
        native = self.root / "home/.moru/bin/moru-hook-native"
        native.parent.mkdir(parents=True)
        observed = self.root / "legacy-probes"
        native.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$3\" >> {shlex.quote(str(observed))}\n"
            "printf '%s\\n' 'unsupported alias' >&2\n"
            "exit 1\n",
            encoding="utf-8",
        )
        native.chmod(0o755)
        key = "c" * 64
        path = self.cache / f"{key}.json"
        with patch.dict(os.environ, environment(self.root, ROOT), clear=True):
            adapter.save_cached(path, key, {"evaluated_at": 12, "response_model": "fixture"})
        self.assertEqual(observed.read_text().splitlines(), ["cache-write-support"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["key"], key)

    def test_native_cache_unknown_write_result_never_replays(self):
        if NATIVE is None or not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.root / "home"
        home.mkdir()
        install(home, ROOT)
        native = home / ".moru/bin/moru-hook-native"
        binary = native.with_name("native-fixture")
        native.rename(binary)
        native.write_text(
            "#!/bin/sh\n"
            'if [ "${3-}" = write-cached-file ]; then\n'
            f'    {shlex.quote(str(binary))} "$@" >/dev/null\n'
            "    exit 1\n"
            "fi\n"
            f'exec {shlex.quote(str(binary))} "$@"\n',
            encoding="utf-8",
        )
        native.chmod(0o755)
        env = environment(self.root, ROOT)
        key = "b" * 64
        path = self.cache / f"{key}.json"
        with patch.dict(os.environ, env, clear=True), \
                patch.object(adapter.tempfile, "mkstemp", side_effect=AssertionError("Python write replay")):
            with self.assertRaisesRegex(OSError, "write outcome could not be determined"):
                adapter.save_cached(path, key, {"evaluated_at": 12, "response_model": "fixture"})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["key"], key)
        self.assertEqual(list(self.cache.glob(".decision-*")), [])


if __name__ == "__main__":
    unittest.main()
