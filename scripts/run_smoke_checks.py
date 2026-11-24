#!/usr/bin/env python3
"""Run automated smoke checks to verify Moru Core hooks and search library E2E."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support.global_state import project_state_dir_target  # noqa: E402
from support.native_probe_transport import NativeProbe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GATE_FIXTURE = ROOT / "native/checkout-identity/smoke-gate-records.json"


def run_command(cmd: List[str], cwd: Union[Path, str] = ROOT) -> subprocess.CompletedProcess:
    print(f"Running command: {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _preflight(temp_dir: str) -> Path:
    state = project_state_dir_target(Path(temp_dir))
    candidates = [state / "preflight.json", *sorted(state.glob("runs/*/preflight.json"))]
    found = next((path for path in candidates if path.is_file()), None)
    assert found is not None, "preflight.json was not created!"
    return found


def test_start_hook(temp_dir: str) -> None:
    print("\n--- Test 1: Start hook (triage command) ---")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "agent-hook.py"),
        "start",
        "--project",
        temp_dir,
        "--rules",
        str(ROOT),
        "--command",
        "triage",
        "--request",
        "재검증해줘 이제 코덱스가 마무리했네",
    ]
    result = run_command(cmd)
    assert result.returncode == 0, (
        f"Start hook failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    print("SUCCESS: Start hook completed successfully.")

    # Start now claims a run-scoped evidence path; the legacy flat path remains
    # valid for direct preflight callers, so accept either location.
    _preflight(temp_dir)
    print("SUCCESS: preflight.json exists.")


def test_gate_validation_failures(temp_dir: str) -> None:
    print("\n--- Test 2: Gate validation failures (checking constraints) ---")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "agent-hook.py"),
        "gate",
        "--project",
        temp_dir,
        "--rules",
        str(ROOT),
        "--evidence",
        str(_preflight(temp_dir)),
        "--gate-name",
        "alignment brief",
        "--status",
        "SUCCESS",
        "--gate-evidence",
        "invalid brief without shared understanding phrase",
    ]
    result = run_command(cmd)
    assert result.returncode != 0, (
        "Gate should have failed validation due to missing required phrases!"
    )
    print("SUCCESS: Gate validation correctly rejected weak alignment brief.")


def test_gate_validation_success(temp_dir: str) -> None:
    print("\n--- Test 3: Gate validation success ---")
    data = GATE_FIXTURE.read_bytes()
    records = json.loads(data)
    batch = project_state_dir_target(Path(temp_dir)) / "smoke-gates.json"
    batch.write_bytes(data)
    result = run_command(
        [
            sys.executable,
            str(ROOT / "scripts" / "agent-hook.py"),
            "gate-batch",
            "--project",
            temp_dir,
            "--rules",
            str(ROOT),
            "--evidence",
            str(_preflight(temp_dir)),
            "--gate-json",
            str(batch),
        ]
    )
    assert result.returncode == 0, (
        f"Failed to record the gate batch:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    for data in records:
        assert data["gate"] in result.stdout or "truncated" in result.stdout, (
            f"Gate {data['gate']} is missing from the batch result:\n{result.stdout}"
        )
    print("SUCCESS: All gates populated with valid evidence.")


def test_finish_hook(temp_dir: str) -> None:
    print("\n--- Test 4: Finish hook check ---")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "agent-hook.py"),
        "finish",
        "--project",
        temp_dir,
        "--rules",
        str(ROOT),
        "--evidence",
        str(_preflight(temp_dir)),
        "--allow-vibeguard-review",
        "E2E testing in temporary directory",
    ]
    result = run_command(cmd)
    assert result.returncode == 0, f"Finish hook failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    print("SUCCESS: Finish hook approved completed triage workflow.")


def test_workflow_query() -> None:
    print("\n--- Test 5: Workflow search query check ---")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "workflow.py"),
        "query",
        "triage",
    ]
    result = run_command(cmd)
    assert result.returncode == 0, f"Workflow query failed: {result.stderr}"
    assert "triage" in result.stdout.lower(), "Expected search results not found!"
    print("SUCCESS: Search query returned results correctly.")


def _native_suite() -> int | None:
    if not NativeProbe.available():
        return None
    launcher = Path.home() / ".moru/bin/moru-hook"
    # Only a decline before scratch setup permits replay through Python.
    sys.stdout.flush()
    try:
        result = subprocess.run(
            [str(launcher.with_name("moru-hook-native")), str(launcher), "--smoke-hook-suite",
             sys.executable],
            stdin=subprocess.DEVNULL,
            env={**os.environ, "MORU_HOME": str(ROOT)},
        )
    except FileNotFoundError:
        return None
    return None if result.returncode == 125 else result.returncode


def main() -> int:
    native = _native_suite()
    if native is not None:
        return native if native >= 0 else 1

    print("==================================================")
    print("Starting E2E Hook Smoke Checks")
    print("==================================================")
    with tempfile.TemporaryDirectory() as temp_dir:
        run_command(["git", "init"], cwd=temp_dir)
        run_command(["git", "config", "user.name", "Test User"], cwd=temp_dir)
        run_command(["git", "config", "user.email", "test@example.com"], cwd=temp_dir)

        dummy_file = Path(temp_dir) / "README.md"
        dummy_file.write_text("Dummy project", encoding="utf-8")
        run_command(["git", "add", "README.md"], cwd=temp_dir)
        run_command(["git", "commit", "-m", "Initial commit"], cwd=temp_dir)

        shutil.copy(
            str(ROOT / ".vibeguard.json"),
            str(Path(temp_dir) / ".vibeguard.json"),
        )

        try:
            test_start_hook(temp_dir)
            test_gate_validation_failures(temp_dir)
            test_gate_validation_success(temp_dir)
            test_finish_hook(temp_dir)
            test_workflow_query()
            print("\n==================================================")
            print("✅ All E2E smoke checks passed successfully!")
            print("==================================================")
            return 0
        except AssertionError as err:
            print(f"\n❌ Smoke check failed: {err}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
