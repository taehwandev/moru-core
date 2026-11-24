#!/usr/bin/env python3
"""Stateless preview of the final review's structural checks.

Owner: changed-source structural preview CLI.
Allowed imports: standard library, agent_review_structure and the local native probe.
Forbidden imports: lifecycle writers, gates, provider runtimes.
Callers/tests: refactor workflow; test_agent_structure_check.py.
Verification: CLI tests against temporary Git projects.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True

from agent_review_structure import (
    REVIEW_FUNCTION_LINE_LIMIT,
    REVIEW_SOURCE_FILE_LINE_LIMIT,
    structure_review,
)
from support.native_probe_transport import NativeProbe

_REPORT_FIELDS = ("checked_paths", "failures", "warnings", "boundary_note_requirements", "net_deletions")


def _run(command: list[str], cwd: Path) -> dict:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--review-path", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        report = structure_review(
            args.project.resolve(), REVIEW_SOURCE_FILE_LINE_LIMIT,
            REVIEW_FUNCTION_LINE_LIMIT, _run, args.review_path or None,
        )
    except (OSError, RuntimeError, ValueError) as error:
        text = str(error)
        return _print_report({"mode": "error", "error": text}, 1, {"status": "FAIL", "error": text})
    fields = {key: report[key] for key in _REPORT_FIELDS}
    return _print_report({"mode": "cli", "fields": fields}, int(bool(fields["failures"])), fields)


def _print_report(payload: dict, status: int, fields: dict) -> int:
    native = NativeProbe.request("--completion-probe", "structure-report", payload)
    if (native is not None and isinstance(native.get("text"), str)
            and type(native.get("exit_code")) is int and native["exit_code"] == status):
        print(native["text"])
        return status
    if payload["mode"] == "error":
        print(json.dumps(fields))
        return status
    print(json.dumps({
        "status": "FAIL" if status else "SUCCESS",
        "scope": "Structural preview only; not behavior verification or review approval",
        **fields,
    }, indent=2, ensure_ascii=False))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
