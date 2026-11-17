"""agy hands a run's unread required docs to the model, again after a compaction."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agy_required_docs_hook import respond

CORE = "platforms/android/skills/sample/SKILL.md"
OTHER = "common/skills/testing/references/final-check.md"
CHECKPOINT = {"step_index": 9, "source": "SYSTEM", "type": "CHECKPOINT",
              "content": "# Resuming from a compaction\n\nsummary"}


class AgyHookTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name).resolve()
        self.rules, self.project = base / "rules", base / "project"
        for doc, body in ((CORE, "- Keep state immutable."), (OTHER, "- Run the tests.")):
            (self.rules / doc).parent.mkdir(parents=True, exist_ok=True)
            (self.rules / doc).write_text(f"---\nkeyflow_id: k\n---\n{body}\n", encoding="utf-8")
        run = self.project / ".moru" / "runs" / ("b" * 32)
        run.mkdir(parents=True)
        (self.project / ".moru" / "run-registry.json").write_text("{}", encoding="utf-8")
        self.evidence = run / "preflight.json"
        self.evidence.write_text(json.dumps({
            "project": str(self.project), "rules": str(self.rules),
            "timestamp": "2026-11-05T00:00:00+00:00",
            "route": {"required_docs": [CORE, OTHER]}}), encoding="utf-8")
        self.transcript = base / "transcript.jsonl"
        self.transcript.write_text("", encoding="utf-8")

    def _append(self, *rows: dict) -> None:
        with self.transcript.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def _read_call(self, doc: str, **extra) -> dict:
        return {"step_index": 1, "type": "PLANNER_RESPONSE", "tool_calls": [
            {"name": "read_file", "args": {"Path": str(self.rules / doc), **extra}}]}

    def _hook(self, project: Path | None = None) -> dict:
        payload = {"conversationId": "c-1", "workspacePaths": [str(project or self.project)],
                   "transcriptPath": str(self.transcript)}
        return respond(payload, lambda path: self.evidence if path == self.project else None)

    @staticmethod
    def _text(answer: dict) -> str:
        return answer["injectSteps"][0]["systemMessage"]["systemMessage"] if answer else ""

    def test_unread_docs_are_injected_once_in_the_shape_agy_accepts(self) -> None:
        answer = self._hook()
        self.assertEqual({"injectSteps"}, set(answer))
        self.assertEqual({"systemMessage"}, set(answer["injectSteps"][0]))
        self.assertEqual({"systemMessage"}, set(answer["injectSteps"][0]["systemMessage"]))
        text = self._text(answer)
        self.assertIn("Keep state immutable.", text)
        self.assertIn("Run the tests.", text)
        self.assertEqual({}, self._hook())

    def test_a_whole_file_read_call_counts_but_a_ranged_read_does_not(self) -> None:
        self._append(self._read_call(CORE), self._read_call(OTHER, StartLine=1, EndLine=3))
        text = self._text(self._hook())
        self.assertNotIn("Keep state immutable.", text)
        self.assertIn("Run the tests.", text)

    def test_the_compact_transcript_stores_arguments_json_encoded(self) -> None:
        quoted = {"step_index": 1, "type": "PLANNER_RESPONSE", "tool_calls": [
            {"name": "read_file", "args": {"Path": json.dumps(str(self.rules / CORE))}}]}
        self._append(quoted)
        text = self._text(self._hook())
        self.assertNotIn("Keep state immutable.", text)
        self.assertIn("Run the tests.", text)

    def test_a_read_older_than_the_doc_s_last_change_does_not_count(self) -> None:
        self._append({**self._read_call(CORE), "created_at": "2000-01-01T00:00:00Z"},
                     {**self._read_call(OTHER), "created_at": "2999-01-01T00:00:00Z"})
        text = self._text(self._hook())
        self.assertIn("Keep state immutable.", text)
        self.assertNotIn("Run the tests.", text)

    def test_any_workspace_of_the_conversation_can_hold_the_run(self) -> None:
        payload = {"conversationId": "c-1", "workspacePaths": [str(self.rules), str(self.project)],
                   "transcriptPath": str(self.transcript)}
        answer = respond(payload, lambda path: self.evidence if path == self.project else None)
        self.assertIn("Keep state immutable.", self._text(answer))

    def test_a_compaction_checkpoint_delivers_the_docs_again(self) -> None:
        self.assertNotEqual({}, self._hook())
        self._append(self._read_call(CORE), CHECKPOINT)
        text = self._text(self._hook())
        self.assertIn("Keep state immutable.", text)
        self.assertIn("Run the tests.", text)
        self.assertEqual({}, self._hook())

    def test_a_read_after_the_checkpoint_is_still_in_context(self) -> None:
        self.assertNotEqual({}, self._hook())
        self._append(CHECKPOINT, self._read_call(CORE))
        text = self._text(self._hook())
        self.assertNotIn("Keep state immutable.", text)
        self.assertIn("Run the tests.", text)

    def test_no_run_or_missing_conversation_answers_nothing(self) -> None:
        self.assertEqual({}, self._hook(project=self.rules))
        self.assertNotEqual({}, self._hook(project=self.project / "subdir"))
        self.assertEqual({}, respond({"workspacePaths": [str(self.project)]}, lambda path: self.evidence))
        self.assertEqual({}, respond({"conversationId": "c-1"}, lambda path: self.evidence))

    def test_the_script_fails_open_on_bad_input(self) -> None:
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "agy_required_docs_hook.py")],
                                input="not json", capture_output=True, text=True, check=False)
        self.assertEqual((0, "{}"), (result.returncode, result.stdout))


class AgyHookRegistrationTests(unittest.TestCase):
    def test_managed_standalone_docs_group_is_retired_from_durable_root_preserving_other_hooks(self) -> None:
        from support.agy_setup import AGY_HOOK_GROUP, _retire_agy_docs_hook

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            durable = base / "moru"
            (durable / "scripts").mkdir(parents=True)
            (durable / ".git").mkdir()
            target = base / "config" / "hooks.json"
            target.parent.mkdir()
            other = {"auto-approve": {"PreToolUse": [{"matcher": "*", "hooks": []}]}}
            managed = {
                **other,
                AGY_HOOK_GROUP: {
                    "PreInvocation": [{
                        "type": "command",
                        "command": f"python3 '{durable}/scripts/agy_required_docs_hook.py'",
                        "timeout": 10,
                    }]
                },
            }
            target.write_text(json.dumps(managed), encoding="utf-8")
            self.assertEqual("would_remove", _retire_agy_docs_hook(target, True, root=durable))
            self.assertIn(AGY_HOOK_GROUP, json.loads(target.read_text(encoding="utf-8")))
            self.assertEqual("removed", _retire_agy_docs_hook(target, False, root=durable))
            written = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(other, written)
            self.assertEqual("ok", _retire_agy_docs_hook(target, False, root=durable))

            # A non-Moru group that happens to share the name is left untouched.
            foreign = {**other, AGY_HOOK_GROUP: {"PreInvocation": [{"type": "command", "command": "python3 custom.py"}]}}
            target.write_text(json.dumps(foreign), encoding="utf-8")
            self.assertEqual("ok", _retire_agy_docs_hook(target, False, root=durable))
            self.assertEqual(foreign, json.loads(target.read_text(encoding="utf-8")))

    def test_a_task_worktree_keeps_a_working_durable_docs_hook_until_durable_setup_runs(self) -> None:
        from support.agy_setup import AGY_HOOK_GROUP, _retire_agy_docs_hook

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            durable, linked, tagged = base / "moru", base / "elsewhere" / "wt", base / "x" / ".moru" / "worktrees" / "t"
            for root in (durable, linked, tagged):
                (root / "scripts").mkdir(parents=True)
            (durable / "scripts" / "agy_required_docs_hook.py").write_text("", encoding="utf-8")
            (linked / ".git").write_text("gitdir: /somewhere", encoding="utf-8")  # linked worktree marker
            (durable / ".git").mkdir()

            def command(root: Path) -> str:
                return f"python3 {root}/scripts/agy_required_docs_hook.py"

            target = base / "hooks.json"
            target.write_text(json.dumps({AGY_HOOK_GROUP: {"PreInvocation": [
                {"type": "command", "command": command(durable), "timeout": 10}]}}), encoding="utf-8")
            for task in (linked, tagged):
                self.assertTrue(_retire_agy_docs_hook(target, False, root=task).startswith("ok (kept"))
                self.assertIn(str(durable), target.read_text(encoding="utf-8"))
            # A hook whose script is gone is dangling and safe to remove even from a task worktree.
            (durable / "scripts" / "agy_required_docs_hook.py").unlink()
            self.assertEqual("removed", _retire_agy_docs_hook(target, False, root=linked))
            self.assertEqual({}, json.loads(target.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
