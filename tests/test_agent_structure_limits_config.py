"""Tests for C3/I5 repo-level structure limits, base-only config safety, and opt-in exclusions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_hook import (  # noqa: E402
    _countable_changed_path_count,
    raised_addition_limit_failures,
    review_success_details,
    structure_evidence_failures,
)
from agent_review_structure import (  # noqa: E402
    REVIEW_ADDED_LINE_LIMIT,
    REVIEW_FUNCTION_LINE_LIMIT,
    REVIEW_SOURCE_EXTENSIONS,
    REVIEW_SOURCE_FILE_LINE_LIMIT,
    is_creative_source_path,
    is_excluded_asset_or_build_script,
    net_deletion_findings,
    review_source_path,
    structure_review,
)
from agent_structure_rule_config import (  # noqa: E402
    STRUCTURE_CODE_EXTENSIONS,
    load_structure_limits_config,
)


def _git_run(command: list[str], cwd: Path) -> dict[str, object]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _git_commit_all(root: Path, message: str = "commit") -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c", "user.name=Test",
            "-c", "user.email=test@example.invalid",
            "commit", "-qm", message,
        ],
        cwd=root,
        check=True,
    )


def _init_repo(root: Path, structure_rules: dict | None = None) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    (root / "README.md").write_text("# Fixture\n", encoding="utf-8")
    if structure_rules is not None:
        rules = root / ".agents" / "structure-rules.json"
        rules.parent.mkdir(parents=True, exist_ok=True)
        rules.write_text(json.dumps(structure_rules), encoding="utf-8")
    _git_commit_all(root, "init")


def _js_function(name: str, body_lines: int) -> str:
    body = "\n".join(f"  const v{i} = {i};" for i in range(body_lines))
    return f"export function {name}() {{\n{body}\n  return 0;\n}}\n"


class RepoStructureLimitsConfigTests(unittest.TestCase):
    def test_committed_base_config_raises_limits_within_2x_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            _init_repo(
                project,
                {
                    "schema_version": 1,
                    "limits": {
                        "max_function_lines": 150,
                        "max_added_lines": 420,
                        "max_source_file_lines": 600,
                        "max_changed_paths": 45,
                        "max_public_owners": 2,
                    },
                },
            )
            # Ordinary path with 2 exports, 380 lines, 135-line function -> passes under committed base limits.
            target = project / "src" / "engine" / "camera.js"
            target.parent.mkdir(parents=True)
            target.write_text(
                _js_function("buildCamera", 135)
                + _js_function("updateCamera", 135)
                + "\n".join(f"// pad {i}" for i in range(100))
                + "\n",
                encoding="utf-8",
            )
            report = structure_review(
                project,
                REVIEW_SOURCE_FILE_LINE_LIMIT,
                REVIEW_FUNCTION_LINE_LIMIT,
                _git_run,
            )
            self.assertEqual([], report["failures"], report["failures"])
            self.assertEqual(420, report["max_added_lines"])
            self.assertEqual(150, report["max_block_lines"])
            self.assertEqual(600, report["max_file_lines"])
            # N2: no waiver — effective config differing from defaults emits a visible
            # warning listing relaxed keys, reports HEAD fallback, and requires structure evidence.
            joined_warnings = "\n".join(report["warnings"])
            self.assertIn("HEAD fallback", joined_warnings)
            self.assertIn("limits.max_added_lines=420", joined_warnings)
            self.assertIn("limits.max_function_lines=150", joined_warnings)
            self.assertTrue(raised_addition_limit_failures(report, ""))
            self.assertTrue(structure_evidence_failures(report, ""))
            valid_evidence = (
                "owner: engine camera; allowed imports: math; forbidden imports: ui; "
                "callers/tests: scene and camera tests; verification: camera unit tests; "
                "addition limit raised to 420 for standalone single-file module"
            )
            self.assertEqual([], raised_addition_limit_failures(report, valid_evidence))
            self.assertEqual([], structure_evidence_failures(report, valid_evidence))
            success_lines = "\n".join(review_success_details(report, "working-tree", "Ready"))
            self.assertIn("warning: structure rules:", success_lines)

    def test_n2_branch_committed_config_relaxation_fails_against_default_branch_merge_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            _init_repo(project)
            subprocess.run(["git", "checkout", "-qb", "feat"], cwd=project, check=True)
            # Attacker commits relaxing .agents/structure-rules.json on feature branch first.
            rules = project / ".agents" / "structure-rules.json"
            rules.parent.mkdir(parents=True)
            rules.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "limits": {"max_added_lines": 600, "max_function_lines": 240},
                    }
                ),
                encoding="utf-8",
            )
            _git_commit_all(project, "relax rules on branch")
            big = project / "src" / "core" / "main.js"
            big.parent.mkdir(parents=True)
            big.write_text(
                _js_function("hugeFn", 150) + "\n".join(f"const x{i} = {i};" for i in range(260)) + "\n",
                encoding="utf-8",
            )
            report = structure_review(
                project,
                REVIEW_SOURCE_FILE_LINE_LIMIT,
                REVIEW_FUNCTION_LINE_LIMIT,
                _git_run,
            )
            joined = "\n".join(report["failures"])
            self.assertIn("changed relative to base (main)", joined)
            self.assertIn("per-file addition limit", joined)
            self.assertIn("hugeFn", joined)
            self.assertEqual(REVIEW_ADDED_LINE_LIMIT, report["max_added_lines"])
            self.assertFalse(report["config_base_fallback"])

    def test_n2_creative_paths_rejects_catchall_and_code_wide_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            _init_repo(
                project,
                {
                    "schema_version": 1,
                    "creative_paths": ["**", "**/*", "*", "**/*.js", "src/**", "lib/**/*.py"],
                },
            )
            cfg, failures = load_structure_limits_config(project)
            self.assertEqual([], cfg["creative_paths"])
            self.assertEqual(6, len(failures), failures)
            # Defense-in-depth at evaluation layer too:
            for bad in ("**", "**/*", "*", "**/*.js", "src/**", "src/**/*.ts"):
                with self.subTest(pattern=bad):
                    self.assertFalse(is_creative_source_path("src/app.js", [bad]))
            self.assertTrue(is_creative_source_path("src/scenes/alley.js", ["src/scenes/**"]))

    def test_n6_review_source_and_structure_code_extensions_come_from_one_source(self) -> None:
        self.assertIs(REVIEW_SOURCE_EXTENSIONS, STRUCTURE_CODE_EXTENSIONS)

    def test_i5_uncommitted_config_change_in_same_review_fails_and_is_not_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            _init_repo(project)
            # Attacker adds .agents/structure-rules.json in the same change to disable all limits!
            rules = project / ".agents" / "structure-rules.json"
            rules.parent.mkdir(parents=True)
            rules.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "exclude_paths": ["**"],
                        "limits": {"max_added_lines": 99999, "max_function_lines": 99999},
                    }
                ),
                encoding="utf-8",
            )
            big = project / "src" / "core" / "main.js"
            big.parent.mkdir(parents=True)
            big.write_text(
                _js_function("hugeFn", 150) + "\n".join(f"const x{i} = {i};" for i in range(400)) + "\n",
                encoding="utf-8",
            )
            report = structure_review(
                project,
                REVIEW_SOURCE_FILE_LINE_LIMIT,
                REVIEW_FUNCTION_LINE_LIMIT,
                _git_run,
            )
            joined = "\n".join(report["failures"])
            self.assertIn("changed relative to base", joined)
            self.assertIn("new-file hard limit", joined)
            self.assertIn("per-file addition limit", joined)
            self.assertIn("hugeFn", joined)
            self.assertEqual(REVIEW_ADDED_LINE_LIMIT, report["max_added_lines"])

    def test_i5_over_cap_limits_catchall_excludes_moru_local_and_env_override_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            _init_repo(
                project,
                {
                    "schema_version": 1,
                    "exclude_paths": ["**", "**/*.py"],
                    "limits": {
                        "max_function_lines": 999,
                        "max_added_lines": 900,
                        "max_changed_paths": 100,
                        "bogus_key": 10,
                    },
                },
            )
            cfg, failures = load_structure_limits_config(project)
            joined = "\n".join(failures)
            self.assertIn("exceeds maximum allowed cap", joined)
            self.assertIn("unknown limits key", joined)
            self.assertIn("catch-all pattern", joined)
            self.assertIn("cannot exclude code extension", joined)
            # None of the over-cap limits or forbidden excludes were applied.
            self.assertEqual({}, cfg["limits"])
            self.assertEqual([], cfg["exclude_paths"])

            # Untracked .moru/structure-rules.json cannot grant limits.
            moru_cfg = project / ".moru" / "structure-rules.json"
            moru_cfg.parent.mkdir(parents=True)
            moru_cfg.write_text(json.dumps({"limits": {"max_added_lines": 500}}), encoding="utf-8")
            _, moru_failures = load_structure_limits_config(project)
            self.assertTrue(any(".moru/structure-rules.json" in f for f in moru_failures))

            # MORU_STRUCTURE_RULES env var cannot relax beyond committed base config.
            env_file = Path(tmp) / "env-rules.json"
            env_file.write_text(json.dumps({"limits": {"max_added_lines": 500}}), encoding="utf-8")
            with patch.dict(os.environ, {"MORU_STRUCTURE_RULES": str(env_file)}):
                _, env_failures = load_structure_limits_config(project)
            self.assertTrue(any("MORU_STRUCTURE_RULES" in f for f in env_failures))


class AssetAndOptInExclusionTests(unittest.TestCase):
    def test_i5_no_hardcoded_creative_or_blender_exclusions_and_code_exts_never_excluded(self) -> None:
        # Without opt-in config, creative dir names and blender scripts are NOT excluded/relaxed.
        for path in (
            "assets/app.js",
            "scripts/blender/run.py",
            "blender/main.py",
            "tools/blender/build_alley.py",
            "src/geometry/parser.ts",
            "src/scene/app.tsx",
            "app/three/index.ts",
            "src/stages/checkout.ts",
            "lib/materials/api.py",
        ):
            with self.subTest(path=path):
                self.assertFalse(is_excluded_asset_or_build_script(path, []))
                self.assertFalse(is_creative_source_path(path, []))
        # Binary/3D assets ARE excluded.
        self.assertTrue(is_excluded_asset_or_build_script("a.svg", []))
        self.assertTrue(is_excluded_asset_or_build_script("x.gltf", []))
        # exclude_paths can NEVER exclude code extensions (even with "**" or "assets/**").
        self.assertFalse(is_excluded_asset_or_build_script("src/core/main.py", ["**"]))
        self.assertFalse(is_excluded_asset_or_build_script("assets/app.js", ["assets/**"]))

    def test_opted_in_blender_exclusion_and_binary_assets_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            _init_repo(project, {"schema_version": 1, "exclude_blender_scripts": True})
            status_lines = [f"?? assets/frame_{i:03d}.png" for i in range(200)]
            status_lines += [f" M assets/model_{i:02d}.glb" for i in range(50)]
            status_lines += [f" M assets/scene_{i:02d}.gltf" for i in range(44)]
            status_lines += [" M tools/blender/build_alley.py"]
            status_lines += [" M src/app.js", " M src/camera.js"]
            countable, excluded, _ = _countable_changed_path_count(project, status_lines)
            self.assertEqual(2, countable)
            self.assertEqual(295, excluded)

            blender_script = project / "tools" / "blender" / "build_alley.py"
            blender_script.parent.mkdir(parents=True)
            blender_script.write_text("\n".join(f"x_{i} = {i}" for i in range(894)), encoding="utf-8")
            self.assertTrue(review_source_path(project, Path("tools/blender/build_alley.py")))
            self.assertFalse(
                review_source_path(
                    project, Path("tools/blender/build_alley.py"), exclude_blender_scripts=True
                )
            )
            findings = net_deletion_findings(
                {
                    "assets/alley.gltf": {"additions": 10, "deletions": 800},
                    "tools/blender/build_alley.py": {"additions": 50, "deletions": 894},
                    "docs/architecture.md": {"additions": 5, "deletions": 120},
                },
                exclude_blender_scripts=True,
            )
            self.assertEqual(["docs/architecture.md"], [item["path"] for item in findings])

    def test_negative_control_ordinary_code_files_still_count_against_path_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            _init_repo(project)
            status_lines = [f" M src/mod_{i:02d}.py" for i in range(30)]
            countable, excluded, _ = _countable_changed_path_count(project, status_lines)
            self.assertEqual(30, countable)
            self.assertEqual(0, excluded)


class CreativeOptInFileAndFunctionGrowthTests(unittest.TestCase):
    def test_opted_in_creative_file_warns_while_growing_existing_function_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            _init_repo(project, {"schema_version": 1, "creative_paths": ["src/scenes/**"]})
            scene = project / "src" / "scenes" / "alley.js"
            scene.parent.mkdir(parents=True)
            scene.write_text(
                _js_function("buildAlleyScene", 140)
                + "\n".join(f"const prop{i} = {i};" for i in range(420))
                + "\n",
                encoding="utf-8",
            )
            new_report = structure_review(
                project,
                REVIEW_SOURCE_FILE_LINE_LIMIT,
                REVIEW_FUNCTION_LINE_LIMIT,
                _git_run,
            )
            self.assertEqual([], new_report["failures"], new_report["failures"])
            self.assertTrue(new_report["warnings"])

            _git_commit_all(project, "add scene")
            scene.write_text(
                _js_function("buildAlleyScene", 150)
                + "\n".join(f"const prop{i} = {i};" for i in range(420))
                + "\n",
                encoding="utf-8",
            )
            grown_report = structure_review(
                project,
                REVIEW_SOURCE_FILE_LINE_LIMIT,
                REVIEW_FUNCTION_LINE_LIMIT,
                _git_run,
            )
            self.assertTrue(
                any("buildAlleyScene" in f for f in grown_report["failures"]),
                grown_report["failures"],
            )

    def test_negative_control_unopted_stages_or_billing_code_still_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            _init_repo(project)
            for rel in ("src/stages/checkout.ts", "src/billing/invoice.js"):
                target = project / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    _js_function("computeInvoice", 140)
                    + _js_function("formatInvoice", 20)
                    + "\n".join(f"const row{i} = {i};" for i in range(380))
                    + "\n",
                    encoding="utf-8",
                )
            report = structure_review(
                project,
                REVIEW_SOURCE_FILE_LINE_LIMIT,
                REVIEW_FUNCTION_LINE_LIMIT,
                _git_run,
            )
            joined = "\n".join(report["failures"])
            self.assertIn("src/stages/checkout.ts", joined)
            self.assertIn("new-file hard limit", joined)
            self.assertIn("per-file addition limit", joined)
            self.assertIn("computeInvoice", joined)
            self.assertIn("public/exported top-level owners", joined)


if __name__ == "__main__":
    unittest.main()
