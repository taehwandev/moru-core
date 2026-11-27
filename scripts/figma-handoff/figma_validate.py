#!/usr/bin/env python3
"""CLI entrypoint for network-free Figma handoff validation."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

from figma_coverage import coverage_report
from figma_summary_validate import validate_summary
from figma_validation_report import format_report


def _native_report(path: str) -> dict | None:
    if os.environ.get("MORU_LAUNCHER_BACKEND") == "python":
        return None
    root = Path(__file__).resolve().parent.parent.parent
    # This tool can also be copied on its own. Never import a similarly named
    # transport from site-packages or a different Moru checkout on sys.path.
    transport = root / "scripts/support/native_probe_transport.py"
    if not transport.is_file() or transport.resolve() != transport:
        return None
    spec = importlib.util.spec_from_file_location("_moru_figma_probe_transport", transport)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except OSError:
        return None
    digits = sys.get_int_max_str_digits() if hasattr(sys, "get_int_max_str_digits") else -1
    result = module.NativeProbe.request("--completion-probe", "figma-validate-cli", {
        "path": path, "source_root": str(root),
        "python_profile": f"{sys.implementation.name}:{sys.hexversion}:{sys.getrecursionlimit()}:{digits}",
    })
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
    problems = validate_summary(summary)
    print(format_report(problems, coverage_report(summary)))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
