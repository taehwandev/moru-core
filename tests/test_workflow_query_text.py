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
            self.assertEqual(trace.read_text().splitlines(), ["render-text 0"])
