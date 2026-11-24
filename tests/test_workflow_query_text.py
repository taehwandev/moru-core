"""Process parity for native workflow query output and Python rollback."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from native_launcher_support import NATIVE, PROJECT, install
from native_pretool_support import environment


class WorkflowQueryTextTests(unittest.TestCase):
    def test_reports_match_python_and_decline_unsupported_shapes(self):
        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            (base / "home").mkdir()
            install(base / "home", PROJECT)
            entry = base / "home/.moru/bin/moru-hook"
            env = environment(base, PROJECT)
            native = [str(entry.with_name("moru-hook-native")), str(entry),
                      "--workflow-query-probe", "render-text"]
            oracle = (
                "import json,sys; sys.path.insert(0, sys.argv[1]); "
                "from workflow_search import print_query_results; "
                "print_query_results(**json.load(sys.stdin))"
            )
            cases = (
                ([], True),
                ([{"path": "plain.md"}], True),
                ([
                    {"path": "가이드.md", "description": "설명 [link](doc.md) | *note*", "title": "Guide", "line": 7,
                     "search_backend": "wikimap", "heading": "절", "matched_facets": ["triage", "요청"],
                     "graph_reasons": ["first", "second", "omitted"]},
                    {"path": "다음.md", "description": "", "title": "다음", "line": 0, "heading": None},
                ], True),
                ([{"path": "first.md"}, {"path": "compat.md", "line": True, "matched_facets": [3]}], False),
            )
            for rows, supported in cases:
                with self.subTest(rows=rows):
                    message = json.dumps({"query": '검색 "triage"', "results": rows}).encode("utf-8")
                    expected = subprocess.run([sys.executable, "-c", oracle, str(PROJECT / "scripts")],
                                              input=message, env={**env, "MORU_LAUNCHER_BACKEND": "python"},
                                              capture_output=True, timeout=10, check=True)
                    result = subprocess.run(native, input=message, env=env,
                                            capture_output=True, timeout=10)
                    if supported:
                        self.assertEqual((result.returncode, result.stderr), (0, b""))
                        self.assertEqual(json.loads(result.stdout),
                                         {"schema_version": 1, "result": {"text": expected.stdout.decode("utf-8")}})
                    else:
                        self.assertEqual((result.returncode, result.stdout, result.stderr), (125, b"", b""))
                    actual = subprocess.run([sys.executable, "-c", oracle, str(PROJECT / "scripts")],
                                            input=message, env=env, capture_output=True, timeout=10)
                    self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                     (0, expected.stdout, b""))
            for message in (b'{"query":', b" " * (1024 * 1024 + 1)):
                result = subprocess.run(native, input=message, env=env, capture_output=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (125, b"", b""))

    def test_workflow_cli_uses_native_report_with_unchanged_output(self):
        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            (base / "home").mkdir()
            install(base / "home", PROJECT)
            native = base / "home/.moru/bin/moru-hook-native"
            binary = native.with_name("native-fixture")
            native.rename(binary)
            trace = base / "query-text-calls"
            native.write_text(
                "#!/bin/sh\n"
                'if [ "${2-}" = --workflow-query-probe ]; then\n'
                f'    {shlex.quote(str(binary))} "$@"\n'
                "    status=$?\n"
                f"    printf '%s %s\\n' \"$3\" \"$status\" >> {shlex.quote(str(trace))}\n"
                '    exit "$status"\n'
                "fi\n"
                f'exec {shlex.quote(str(binary))} "$@"\n',
                encoding="utf-8",
            )
            native.chmod(0o755)
            env = environment(base, PROJECT)
            args = [sys.executable, str(PROJECT / "scripts/workflow.py"), "query", "triage"]
            expected = subprocess.run(args, env={**env, "MORU_LAUNCHER_BACKEND": "python"},
                                      capture_output=True, timeout=15, check=True)
            self.assertFalse(trace.exists())
            actual = subprocess.run(args, env=env, capture_output=True, timeout=15, check=True)
            self.assertEqual((actual.stdout, actual.stderr), (expected.stdout, expected.stderr))
            self.assertEqual(trace.read_text().splitlines(), ["rank-wikimap 0", "render-text 0"])

    def test_rank_preserves_first_match_positions_and_policy_ties(self):
        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            (base / "home").mkdir()
            install(base / "home", PROJECT)
            corpus = base / "corpus"
            corpus.mkdir()
            for path in ("a.md", "b.md", "가.md", "z.md"):
                (corpus / path).write_text(f"# {path}\n", encoding="utf-8")
            (corpus / "scripts").mkdir()
            (corpus / "scripts/hidden.md").write_text("# Hidden\n", encoding="utf-8")
            env = environment(base, PROJECT)
            process = (
                "import json,sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                "import workflow_search as search; payload=json.load(sys.stdin); "
                "probe=search.NativeProbe.request\n"
                "def observe(*args, **kwargs):\n"
                "    result=probe(*args, **kwargs)\n"
                "    print(args[1], bool(result), file=sys.stderr)\n"
                "    return result\n"
                "search.NativeProbe.request=observe\n"
                "print(json.dumps(search._wikimap_results(Path(sys.argv[2]), **payload)))"
            )
            command = [sys.executable, "-c", process, str(PROJECT / "scripts"), str(corpus)]
            matches = [
                {"path": "missing.md", "line": 99},
                {"path": "b.md", "line": 7, "heading": "First", "matched": ["text"], "sources": "original"},
                {"path": "b.md", "line": 8, "heading": "Ignored"},
                {"path": "scripts/hidden.md", "line": 19},
                {"path": "z.md", "line": 4},
            ]
            boosts = {"가.md": 40, "missing.md": 10000, "a.md": 40, "b.md": -1000, "scripts/hidden.md": 500}
            cases = ((8, False, False), (2, False, False), (0, False, False),
                     (-1, False, False), (8, True, False), (8, False, True))
            for limit, unsupported, negative_rank in cases:
                with self.subTest(limit=limit, unsupported=unsupported, negative_rank=negative_rank):
                    hits = [*matches, {"path": "a.md", "line": "11"}] if unsupported else matches
                    if negative_rank:
                        hits = [*matches[:-1], *([matches[1]] * 500), matches[-1]]
                    data = json.dumps({"matches": hits, "doc_boosts": boosts,
                                       "matched_facets": [], "max_results": limit}).encode()
                    expected = subprocess.run(command, input=data, env={**env, "MORU_LAUNCHER_BACKEND": "python"},
                                              capture_output=True, timeout=10, check=True)
                    actual = subprocess.run(command, input=data, env=env, capture_output=True, timeout=10, check=True)
                    self.assertEqual(actual.stdout, expected.stdout)
                    self.assertEqual(actual.stderr, f"rank-wikimap {not unsupported}\n".encode())
                    if limit == 8 and not unsupported:
                        rows = json.loads(actual.stdout)
                        self.assertEqual([(row["path"], row["score"]) for row in rows],
                                         [("a.md", 1040), ("가.md", 1040), ("b.md", 499),
                                          ("z.md", -4 if negative_rank else 496)])
                        self.assertEqual((rows[2]["heading"], rows[2]["line"]), ("First", 7))

    def test_offline_score_preserves_weights_unicode_cutoff_and_batch_fallback(self):
        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            (base / "home").mkdir()
            install(base / "home", PROJECT)
            corpus = base / "corpus"
            corpus.mkdir()
            files = {
                "index.md": "- `positive.md` Repeat\n",
                "positive.md": "# REPEAT\n## Repeat\n한 repeat repeat\n",
                "cutoff.md": "가" * 1999 + "한",
                "beyond.md": "가" * 2000 + "한",
                "negative.md": "# Repeat\n",
            }
            for path, content in files.items():
                (corpus / path).write_text(content, encoding="utf-8")
            env = environment(base, PROJECT)
            process = (
                "import json,os,sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]);\n"
                "import workflow_search as search\n"
                "search._OFFLINE_BATCH_CHARS = 2048\n"
                "probe=search.NativeProbe.request\n"
                "def observe(*args, **kwargs):\n"
                "    result=probe(*args, **kwargs)\n"
                "    body=args[2]['rows']\n"
                "    if os.environ.get('REJECT_BATCH') and any('한' in row[1][3] for row in body):\n"
                "        result={'scores': []}\n"
                "    print(args[1], len(body), len(result['scores']) if result else -1, file=sys.stderr)\n"
                "    return result\n"
                "search.NativeProbe.request=observe\n"
                "search.search_wikimap=lambda *a: type('Unavailable', (), {'available': False, 'error': 'offline'})()\n"
                "search.query_terms=lambda query: (['한', 'repeat'], ['repeat'], [], {'positive.md': 7, 'negative.md': -50})\n"
                "search.infer_concerns_from_request=lambda query: []\n"
                "print(json.dumps(search.search_docs_outcome(Path(sys.argv[2]), 'offline').results))\n"
            )
            command = [sys.executable, "-c", process, str(PROJECT / "scripts"), str(corpus)]
            expected = subprocess.run(command, env={**env, "MORU_LAUNCHER_BACKEND": "python"},
                                      capture_output=True, timeout=10, check=True)
            rows = {row["path"]: row["score"] for row in json.loads(expected.stdout)}
            self.assertEqual(rows, {"positive.md": 39, "index.md": 3, "cutoff.md": 2})
            for override in ({}, {"REJECT_BATCH": "1"}):
                actual = subprocess.run(command, env={**env, **override},
                                        capture_output=True, timeout=10, check=True)
                self.assertEqual(actual.stdout, expected.stdout)
                batches = [line.split() for line in actual.stderr.decode().splitlines()]
                self.assertGreater(len(batches), 1)
                self.assertTrue(all(operation == "score-offline" for operation, _, _ in batches))
                self.assertTrue(any(count == scored for _, count, scored in batches))
                self.assertEqual(any(scored == "0" for _, _, scored in batches), bool(override))
