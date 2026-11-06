"""Active next advice through the real launcher, with no interpreter available."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from native_next_support import invoke_next, prepare_next, seed
from native_pretool_support import result


class NativeNextActiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-next-active-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.launcher, self.project = prepare_next(self.base)
        self.evidence = seed(self.project, "running")
        self.git_only = self.base / "git-only"
        self.git_only.mkdir()
        (self.git_only / "git").symlink_to(shutil.which("git"))

    def call(self, output="json", backend="auto", no_python=False):
        return invoke_next(self.launcher, self.base, self.project,
            ["--project", str(self.project), "--evidence", str(self.evidence),
             "--format", output], backend=backend,
            **({"PATH": str(self.git_only)} if no_python else {}))

    def snapshot(self):
        return {str(p.relative_to(self.project)): p.read_bytes()
                for p in (self.project / ".moru").rglob("*") if p.is_file()}

    def test_initial_active_advice_all_decision_branches_without_python(self):
        cases = [
            (["tests", "review hook", "retrospective check"], "record_pre_review_gates"),
            (["review hook", "retrospective check"], "review"),
            (["tests", "retrospective check"], "record_closeout_gates"),
            (["retrospective check"], "record_closeout_gates"),
            (["commit readiness"], "finish"),
            (["custom 한글 gate"], "record_closeout_gates"),
            ([], "finish"),
        ]
        for gates, step in cases:
            preflight = json.loads(self.evidence.read_text())
            preflight["route"]["gates"] = gates
            self.evidence.write_text(json.dumps(preflight))
            before = self.snapshot()
            for output in ("json", "markdown"):
                with self.subTest(gates=gates, output=output):
                    reference = self.call(output, backend="python")
                    self.assertEqual(0, reference.returncode, reference.stderr)
                    if output == "json":
                        self.assertEqual(step, json.loads(reference.stdout)["next_step"])
                    self.assertEqual(result(reference), result(self.call(output, no_python=True)))
            self.assertEqual(before, self.snapshot(), "advice must not mutate run state")

    def test_present_ledger_is_not_ignored_even_when_empty_or_invalid(self):
        ledger = self.evidence.with_name("gate-evidence.json")
        for content in ("{}", "{", '{"entries":[]}'):
            with self.subTest(content=content):
                ledger.write_text(content)
                before = self.snapshot()
                self.assertEqual(result(self.call(backend="python")), result(self.call()))
                self.assertEqual(127, self.call(no_python=True).returncode)
                self.assertEqual(before, self.snapshot())

    def test_gate_templates_and_skill_aliases_match_canonical_owners(self):
        from agent_gate_evidence import FIELD_REQUIREMENTS
        preflight = json.loads(self.evidence.read_text())
        preflight["route"]["gates"] = list(FIELD_REQUIREMENTS)
        preflight["route"]["required_docs"] = [
            "common/skills/agent-operating-skill/SKILL.md",
            "workflows/skills/feature-implementation/references/current-guidance.md",
            "common/skills/testing/SKILL.md",
        ]
        self.evidence.write_text(json.dumps(preflight))
        for output in ("json", "markdown"):
            reference = self.call(output, backend="python")
            self.assertEqual(0, reference.returncode, reference.stderr)
            self.assertEqual(result(reference), result(self.call(output, no_python=True)))

    def test_invalid_preflight_does_not_invent_finish_advice(self):
        for content in ("{", "[]", "null", '{"route":{"gates":{}}}'):
            with self.subTest(content=content):
                self.evidence.write_text(content)
                self.assertEqual(result(self.call(backend="python")), result(self.call()))
                self.assertEqual(127, self.call(no_python=True).returncode)

    def test_dash_prefixed_separate_argument_keeps_argparse_error(self):
        (self.project / "-preflight.json").write_bytes(self.evidence.read_bytes())
        args = ["--project", str(self.project), "--evidence", "-preflight.json", "--format", "json"]
        reference = invoke_next(self.launcher, self.base, self.project, args, backend="python")
        self.assertEqual(2, reference.returncode)
        self.assertEqual(result(reference), result(invoke_next(self.launcher, self.base, self.project, args)))
        self.assertEqual(127, invoke_next(self.launcher, self.base, self.project, args,
                                         PATH=str(self.git_only)).returncode)

    def test_trailing_dot_evidence_keeps_python_ledger_naming(self):
        trailing = self.evidence.with_name("run.")
        trailing.write_bytes(self.evidence.read_bytes())
        self.evidence = trailing
        self.evidence.with_name(self.evidence.stem + "-gate-evidence.json").write_text("{}")
        self.assertEqual(result(self.call(backend="python")), result(self.call()))
        self.assertEqual(127, self.call(no_python=True).returncode)


if __name__ == "__main__":
    unittest.main()
