"""Real Codex worker and exact-path trust tests for isolated dispatch."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_worktree_identity import new_worktree_path
from workflow_dispatch_handoff import codex_argv
from workflow_dispatch_launch import execute_dispatch_manifest as execute_launch


@unittest.skipUnless(
    os.environ.get("MORU_RUN_LIVE_CODEX_E2E") == "1" and shutil.which("codex"),
    "set MORU_RUN_LIVE_CODEX_E2E=1 with Codex installed to run the live worker proof",
)
class LiveCodexWorktreeEndToEndTests(unittest.TestCase):
    def test_real_codex_loads_local_policy_and_writes_only_in_verified_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
            (project / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            policy = project / ".codex" / "config.toml"
            policy.parent.mkdir()
            policy.write_text(
                'developer_instructions = """\n'
                "MORU_CODEX_PROJECT_POLICY_SENTINEL\n"
                "When asked to run the live isolation proof, create "
                "live-worker-output.txt containing exactly: isolated by codex\n"
                "Do not modify tracked files.\n"
                '"""\n',
                encoding="utf-8",
            )
            for args in (
                ("init", "-q"),
                ("config", "user.email", "tests@example.invalid"),
                ("config", "user.name", "Moru Core Tests"),
                ("add", "-A"),
                ("commit", "-qm", "initial"),
            ):
                subprocess.run(
                    ["git", *args],
                    cwd=project,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            baseline_worktrees = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=project,
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
            worktree = new_worktree_path(project)
            observed_argv: list[str] = []

            def production_argv(*args: object, **kwargs: object) -> list[str]:
                argv = codex_argv(*args, **kwargs)
                trusted = kwargs.get("trusted_worktree")
                if trusted is not None:
                    observed_argv.extend(argv)
                    self.assertNotIn("--skip-git-repo-check", argv)
                    trust_override = next(
                        argv[index + 1]
                        for index, item in enumerate(argv)
                        if item == "--config" and "trust_level" in argv[index + 1]
                    )
                    prompt_input = subprocess.run(
                        [
                            "codex",
                            "-C",
                            str(trusted),
                            "-c",
                            trust_override,
                            "debug",
                            "prompt-input",
                            "policy probe",
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(0, prompt_input.returncode, prompt_input.stderr)
                    self.assertIn(
                        "MORU_CODEX_PROJECT_POLICY_SENTINEL",
                        prompt_input.stdout,
                    )
                return argv

            reusable_capsule = {
                "path": str(project / ".tao" / "execution-capsule.json"),
                "reusable": True,
                "invalidation_reasons": [],
                "phase": "ready",
            }
            manifest = {
                "execution_mode": "child",
                "capability_profile": {"working_dir_kind": "worktree"},
                "isolation_required": True,
                "worktree_path": str(worktree),
                "project": str(project),
                "work_profile": {
                    "codex_model": "gpt-5.6-terra",
                    "reasoning_effort": "medium",
                },
                "sandbox_mode": "workspace-write",
                "command": "feature",
                "request": "Run the live isolation proof.",
                "work_kind": "implementation",
                "authoring_policy": "authoring allowed",
                "handoff_state": {
                    "rules": str(ROOT),
                    "preflight_evidence": str(project / ".tao" / "preflight.json"),
                    "route_manifest": {"required_docs": [], "gates": []},
                    "parent_context_reusable": True,
                    "execution_capsule": reusable_capsule,
                },
            }
            result = execute_launch(
                manifest,
                runner=None,
                execution_capsule_state=lambda *_args, **_kwargs: reusable_capsule,
                isolated_worker_evidence=lambda *_args, **_kwargs: (
                    project / ".tao" / "workers" / "unused" / "preflight.json"
                ),
                codex_argv=production_argv,
                build_handoff_prompt=lambda *_args, **_kwargs: (
                    "Run the live isolation proof defined by project policy."
                ),
            )

            self.assertEqual(0, result)
            self.assertTrue(observed_argv)
            verified = worktree.resolve()
            self.assertEqual(
                "isolated by codex\n",
                (verified / "live-worker-output.txt").read_text(encoding="utf-8"),
            )
            self.assertFalse((project / "live-worker-output.txt").exists())
            self.assertEqual(
                "",
                subprocess.run(
                    ["git", "status", "--porcelain", "--untracked-files=all"],
                    cwd=project,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
            )
            shutil.copy2(
                verified / "live-worker-output.txt",
                project / "live-worker-output.txt",
            )
            finalized = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "workflow.py"),
                    "dispatch-finalize",
                    "--project",
                    str(project),
                    "--worktree",
                    str(verified),
                    "--format",
                    "json",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, finalized.returncode, finalized.stderr)
            self.assertEqual("finalized", json.loads(finalized.stdout)["status"])
            self.assertFalse(verified.exists())
            self.assertEqual(
                baseline_worktrees,
                subprocess.run(
                    ["git", "worktree", "list", "--porcelain"],
                    cwd=project,
                    check=True,
                    stdout=subprocess.PIPE,
                ).stdout,
            )
            self.assertFalse((project / ".tao" / "worktrees").exists())
            self.assertEqual(
                "isolated by codex\n",
                (project / "live-worker-output.txt").read_text(encoding="utf-8"),
            )


class CodexArgvTrustBoundaryTests(unittest.TestCase):
    def test_trust_override_must_match_bound_worktree(self) -> None:
        profile = {"codex_model": "gpt-5.6-terra", "reasoning_effort": "medium"}

        with self.assertRaisesRegex(ValueError, "exact verified --cd path"):
            codex_argv(
                ROOT,
                profile,
                "workspace-write",
                "bounded worker prompt",
                ROOT / ".tao" / "worktrees" / ("a" * 16),
                trusted_worktree=ROOT / ".tao" / "worktrees" / ("b" * 16),
            )


if __name__ == "__main__":
    unittest.main()
