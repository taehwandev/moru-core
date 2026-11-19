"""Read-only changed-file test target discovery and bounded verify advice.

Owner: NextVerification; allowed imports: stdlib (pathlib, shlex, typing);
forbidden imports: subprocess execution, lifecycle/ledger writes, test imports;
callers/tests: agent_next_action; test_agent_next_verification, test_agent_next_action;
verification: directory-relative selectors, quoting, 64-selector batching, omissions.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

RUNNER_SELECTOR_LIMIT = 64
COMPILE_TARGET_LIMIT = 64
MAX_SELECTOR_LENGTH = 240

_FRAMEWORK_MARKERS: tuple[tuple[str, str], ...] = (
    ("package.json", "npm test"),
    ("Cargo.toml", "cargo test"),
    ("go.mod", "go test ./..."),
    ("Package.swift", "swift test"),
    ("gradlew", "./gradlew test"),
)


def shell_quote(value: str) -> str:
    """Quote a shell argument safely using POSIX single-quoting."""
    return shlex.quote(value)


def compile_arg_quote(rel_posix: str) -> str:
    """Quote a Python file path for py_compile, shielding leading dashes."""
    safe = f"./{rel_posix}" if rel_posix.startswith("-") else rel_posix
    return shlex.quote(safe)


def _check_selector_eligibility(
    tests_dir: Path, rel_under_tests: tuple[str, ...]
) -> tuple[str | None, str | None]:
    stem = Path(rel_under_tests[-1]).stem
    parts = (*rel_under_tests[:-1], stem)
    selector = ".".join(parts)
    if len(selector) > MAX_SELECTOR_LENGTH or not all(part.isidentifier() for part in parts):
        return None, "invalid_selector_identifier"
    if not tests_dir.is_dir():
        return None, "missing_or_deleted"
    resolved_tests = tests_dir.resolve()
    candidate = tests_dir.joinpath(*rel_under_tests)
    if not candidate.exists():
        return None, "missing_or_deleted"
    if not candidate.is_file() or not candidate.resolve().is_relative_to(resolved_tests):
        return None, "escapes_test_directory"
    for end in range(1, len(parts)):
        prefix = tests_dir.joinpath(*parts[:end])
        if prefix.exists() and not prefix.resolve().is_relative_to(resolved_tests):
            return None, "escapes_test_directory"
        if prefix.with_suffix(".py").exists():
            return None, "ambiguous_module_package"
    return selector, None


def discover_verification_targets(project: Path, paths: list[str]) -> dict[str, Any]:
    """Map changed paths to directory-relative selectors, commands, and explicit omissions."""
    resolved = project.expanduser().resolve()
    tests_dir = resolved / "tests"
    compile_targets: list[str] = []
    selectors: list[str] = []
    matched_modules: list[str] = []
    omissions: list[dict[str, Any]] = []
    seen_omissions: set[tuple[str, str, str]] = set()

    def add_omission(kind: str, path: str, reason: str, **extra: Any) -> None:
        key = (kind, path, reason)
        if key not in seen_omissions:
            seen_omissions.add(key)
            omissions.append({"kind": kind, "path": path, "reason": reason, **extra})

    for rel_str in paths:
        rel = Path(rel_str)
        if rel.suffix != ".py":
            continue
        is_file = (resolved / rel).is_file()
        if is_file:
            compile_targets.append(rel.as_posix())
        if rel.parts and rel.parts[0] == "tests" and rel.name.startswith("test_") and len(rel.parts) >= 2:
            selector, reason = _check_selector_eligibility(tests_dir, rel.parts[1:])
            if selector:
                selectors.append(selector)
                matched_modules.append(f"tests.{selector}")
            else:
                add_omission("unsupported_test_file", rel.as_posix(), reason or "unsupported_test_target")
            continue
        stem = rel.stem.replace("-", "_")
        matched_for_file = False
        for cand_name in (f"test_{stem}.py", f"test_support_{stem}.py"):
            cand = tests_dir / cand_name
            if cand.exists() or cand.is_symlink():
                selector, reason = _check_selector_eligibility(tests_dir, (cand_name,))
                if selector:
                    selectors.append(selector)
                    matched_modules.append(f"tests.{selector}")
                    matched_for_file = True
                else:
                    add_omission("unsupported_test_file", f"tests/{cand_name}", reason or "unsupported_test_target")
        if not matched_for_file and is_file and rel.name != "__init__.py":
            add_omission("unmatched_python_file", rel.as_posix(), "no_matching_test_file")

    compile_targets = sorted(dict.fromkeys(compile_targets))
    selectors = sorted(dict.fromkeys(selectors))
    matched_modules = sorted(dict.fromkeys(matched_modules))
    next_batch = selectors[:RUNNER_SELECTOR_LIMIT]
    remaining_selectors = selectors[RUNNER_SELECTOR_LIMIT:]
    if remaining_selectors:
        add_omission(
            "batch_limit",
            "",
            f"exceeds_runner_{RUNNER_SELECTOR_LIMIT}_selector_limit",
            count=len(remaining_selectors),
        )
    compile_batch = compile_targets[:COMPILE_TARGET_LIMIT]
    if len(compile_targets) > COMPILE_TARGET_LIMIT:
        add_omission(
            "compile_limit",
            "",
            f"exceeds_compile_{COMPILE_TARGET_LIMIT}_target_limit",
            count=len(compile_targets) - COMPILE_TARGET_LIMIT,
        )

    commands: list[str] = []
    if compile_batch:
        quoted = " ".join(compile_arg_quote(target) for target in compile_batch)
        commands.append(f"python3 -B -m py_compile {quoted}")
    if matched_modules:
        for idx in range(0, len(matched_modules), RUNNER_SELECTOR_LIMIT):
            chunk = matched_modules[idx : idx + RUNNER_SELECTOR_LIMIT]
            module_args = " ".join(shell_quote(mod) for mod in chunk)
            commands.append(f"PYTHONPATH=tests:scripts python3 -B -m unittest {module_args}")
    else:
        for marker, cmd in _FRAMEWORK_MARKERS:
            if (resolved / marker).is_file():
                commands.append(cmd)
                break

    if selectors:
        coverage_note = (
            "Selected tests cover only matched Python test targets; "
            "they do not prove full-suite or non-Python coverage."
        )
    elif compile_targets:
        coverage_note = (
            "Changed Python files have no verified full-suite coverage; "
            "inspect unmatched files explicitly."
        )
    else:
        coverage_note = ""

    return {
        "changed_paths": paths,
        "matched_test_modules": matched_modules,
        "test_selectors": selectors,
        "next_verify_batch": next_batch,
        "remaining_test_selectors": remaining_selectors,
        "omissions": omissions,
        "coverage_note": coverage_note,
        "suggested_commands": commands,
    }


def build_verify_command(
    launcher: str,
    project: Path,
    rules: Path | str,
    evidence_path: Path,
    selectors: list[str],
) -> str:
    """Build a shell-quoted `moru-hook verify` command for up to 64 selectors."""
    parts = [
        shell_quote(launcher),
        "verify",
        "--project",
        shell_quote(str(project)),
        "--rules",
        shell_quote(str(rules)),
        "--evidence",
        shell_quote(str(evidence_path)),
    ]
    for selector in selectors[:RUNNER_SELECTOR_LIMIT]:
        parts.extend(["--test-selector", shell_quote(selector)])
    return " ".join(parts)


def reconcile_verify_batches(verification, *, project, rules, evidence_path):
    """Advance large selections from actual current-run execution observations."""
    selectors = verification.get('test_selectors') or []
    if len(selectors) <= RUNNER_SELECTOR_LIMIT:
        return False
    from agent_verification_receipts import ExecutionReceipts
    reader = ExecutionReceipts(project, rules)
    tests_dir = str(Path(project).resolve() / 'tests')
    if not any(fact['test_directory'] == tests_dir for fact in reader.history(evidence_path, live=False)):
        return False  # Existing manually recorded checks retain their own scope.
    covered = set()
    for fact in reader.history(evidence_path):
        if fact['test_directory'] != tests_dir:
            continue
        prefix = 'passed' if fact['successful'] else 'failed'
        ids = fact[prefix + '_ids'] + fact[prefix + '_selectors']
        matched = {sel for sel in selectors if any(test_id == sel or test_id.startswith(sel + '.')
                   or test_id.endswith('_FailedTest.' + sel) for test_id in ids)}
        if fact['successful']:
            if fact['selectors']:
                matched = {sel for sel in matched if any(sel == name or sel.startswith(name + '.')
                           for name in fact['selectors'])}
            covered.update(matched)
        else:
            covered.difference_update(matched)
    pending = [sel for sel in selectors if sel not in covered]
    verification['verified_test_selectors'] = sorted(covered)
    verification['next_verify_batch'] = pending[:RUNNER_SELECTOR_LIMIT]
    verification['remaining_test_selectors'] = pending[RUNNER_SELECTOR_LIMIT:]
    verification['observed_selection_complete'] = not pending
    verification['omissions'] = [item for item in verification['omissions'] if item['kind'] != 'batch_limit']
    if len(pending) > RUNNER_SELECTOR_LIMIT:
        verification['omissions'].append({'kind': 'batch_limit', 'path': '',
            'reason': 'exceeds_runner_64_selector_limit', 'count': len(pending) - RUNNER_SELECTOR_LIMIT})
    verification['suggested_commands'] = [cmd for cmd in verification['suggested_commands']
        if not cmd.startswith('PYTHONPATH=tests:scripts python3 -B -m unittest ')]
    return True


def apply_active_verify_advice(
    verification: dict[str, Any],
    *,
    launcher: str,
    project: Path,
    rules: Path | str,
    evidence_path: Path,
) -> str | None:
    """Connect active tests-gate advice to `verify --test-selector` when eligible."""
    next_batch = list(verification.get("next_verify_batch") or [])
    if not next_batch:
        return None
    verify_cmd = build_verify_command(launcher, project, rules, evidence_path, next_batch)
    commands = [
        cmd
        for cmd in verification.get("suggested_commands") or []
        if not cmd.startswith("PYTHONPATH=tests:scripts python3 -B -m unittest ")
    ]
    commands.append(verify_cmd)
    verification["suggested_commands"] = commands
    verification["verify_command"] = verify_cmd
    remaining = list(verification.get("remaining_test_selectors") or [])
    if remaining:
        total = len(verification.get("test_selectors") or [])
        verification["batch_status"] = (
            f"bounded batch 1 ({len(next_batch)} of {total} selectors); "
            f"{len(remaining)} remaining selectors must also be verified before the tests gate is complete"
        )
    return verify_cmd
