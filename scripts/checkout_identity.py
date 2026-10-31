#!/usr/bin/env python3
"""Compatibility process adapter for checkout metadata.

Owner: NDJSON compatibility protocol. Allowed: stdlib and existing lookup owner.
Forbidden: policy/state writes, networking, shell execution, result caching.
Callers/tests: moru-checkout-identity and test_checkout_identity_runtime.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from claude_worktree_gate import current_branch, git_common_dir

MAX_LINE_BYTES = 1024 * 1024


def failure(code: str) -> dict:
    return {"schema_version": 1, "ok": False, "error": code}


def answer(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        return failure("invalid_json")
    if (not isinstance(value, dict) or set(value) != {"schema_version", "root"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["root"], str) or not value["root"]
            or "\0" in value["root"] or not os.path.isabs(value["root"])):
        return failure("invalid_request")
    try:
        root = Path(value["root"])
        common = git_common_dir(root)
        branch = current_branch(root)
        return {"schema_version": 1, "ok": True,
                "common_dir": str(common) if common is not None else None,
                "branch": branch}
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return failure("io_error")


def main() -> int:
    if len(sys.argv) != 1:
        print("checkout_identity.py accepts NDJSON on stdin, no arguments", file=sys.stderr)
        return 2
    stream = sys.stdin.buffer
    while True:
        raw = stream.readline(MAX_LINE_BYTES + 1)
        if not raw:
            return 0
        if len(raw) > MAX_LINE_BYTES:
            while not raw.endswith(b"\n"):
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
            response = failure("input_too_large")
        else:
            response = answer(raw)
        print(json.dumps(response, ensure_ascii=True, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
