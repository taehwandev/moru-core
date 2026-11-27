#!/usr/bin/env python3
"""CLI entrypoint for network-free Figma handoff validation."""

from __future__ import annotations

import json
import sys

from figma_coverage import coverage_report
from figma_summary_validate import _probe, _validate_summary_reference, validate_summary
from figma_validation_report import format_report


def _native_report(path: str) -> dict | None:
    if _probe is None:
        return None
    result = _probe("figma-validate-cli", path, __file__)
    if (type(result) is not dict or set(result) != {"code", "stdout", "stderr"}
            or type(result["code"]) is not int or result["code"] not in (0, 1, 2)
            or type(result["stdout"]) is not str or type(result["stderr"]) is not str):
        return None
    return result


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 figma_validate.py <design-summary.json>", file=sys.stderr)
        return 2
    result = _native_report(argv[1]) if type(argv[1]) is str else None
    if result is not None:
        sys.stdout.write(result["stdout"])
        sys.stderr.write(result["stderr"])
        return result["code"]
    try:
        with open(argv[1], encoding="utf-8") as handle:
            summary = json.load(handle)
    except (OSError, ValueError) as error:
        print(f"ERROR: cannot read summary: {error}", file=sys.stderr)
        return 2
    problems = _validate_summary_reference(summary)
    print(format_report(problems, coverage_report(summary)))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
