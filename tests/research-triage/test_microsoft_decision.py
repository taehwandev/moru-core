"""Exercise the optional adapter through its CLI entrypoint, without paid calls."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "research-triage" / "microsoft_decision.py"
SPEC = importlib.util.spec_from_file_location("microsoft_decision", SCRIPT)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def response(relevance=0.9, kind="review", cost=0.0001):
    return {
        "model": "microsoft/microsoft-decision-1-test-snapshot", "provider": "Azure",
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


class MicrosoftDecisionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.input = self.root / "input.json"
        self.cache = self.root / "cache"
        self.payload = {"query": "What problems should a note-taking product solve?", "sources": [source()]}
        self.environment = patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        network = patch.object(adapter.urllib.request, "urlopen", side_effect=AssertionError("unmocked network"))
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
        with patch.object(adapter, "send_request", side_effect=AssertionError("paid call")):
            status, result, _ = self.run_cli()
        self.assertEqual(0, status)
        self.assertEqual(0, result["network_calls"])
        self.assertEqual("unscored", result["results"][0]["status"])
        self.assertFalse(self.cache.exists())

    def test_execute_without_key_preserves_sources_without_calls(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            with patch.object(adapter, "send_request") as call:
                status, result, _ = self.run_cli("--execute")
        self.assertEqual(0, status)
        call.assert_not_called()
        self.assertEqual("missing_key", result["results"][0]["reason"])
        self.assertFalse(self.cache.exists())

    def test_http_contract_and_persistent_reuse_via_cli(self):
        with patch.object(adapter.urllib.request, "urlopen", return_value=io.BytesIO(
            json.dumps(response()).encode(),
        )) as http:
            status, first, _ = self.run_cli("--execute")
        self.assertEqual(0, status)
        request = http.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual("POST", request.get_method())
        self.assertEqual("https://openrouter.ai/api/alpha/decisions", request.full_url)
        self.assertEqual("Bearer test-key", request.get_header("Authorization"))
        self.assertEqual("microsoft/microsoft-decision-1", body["model"])
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
        self.assertEqual("microsoft/microsoft-decision-1-test-snapshot", second["results"][0]["response_model"])
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

    def test_unknown_cost_is_reported_without_an_estimate(self):
        with patch.object(adapter, "send_request", return_value=response(cost=None)):
            _, result, _ = self.run_cli("--execute")
        self.assertIsNone(result["new_reported_cost_usd"])
        self.assertFalse(result["cost_complete"])


if __name__ == "__main__":
    unittest.main()
