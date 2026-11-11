"""Read-only native work-card snapshots with exact SQLite cell reconstruction.

Owner: NativeCards. Allowed: stdlib, canonical repository-key reader, NativeProbe. Forbidden: SQL, filesystem
writes, schema changes or Python policy algorithms. Callers/tests: agent_work_cards;
test_native_card_snapshot verifies real ingress, types, order and atomic refusal.
"""
from __future__ import annotations

import math
from pathlib import Path

from agent_repository_key import repository_key
from support.native_probe_transport import NativeProbe


def _cell(cell):
    if type(cell) is not list or not cell or type(cell[0]) is not str:
        raise ValueError("invalid native cell")
    kind = cell[0]
    if kind == "null" and len(cell) == 1:
        return None
    if len(cell) != 2:
        raise ValueError("invalid native cell")
    value = cell[1]
    if kind == "integer" and type(value) is int and -(1 << 63) <= value < (1 << 63):
        return value
    if kind == "text" and type(value) is str:
        return value
    if kind == "real" and type(value) is str and len(value) <= 64:
        number = float(value)
        if not math.isnan(number):
            return number
    if (kind == "blob" and type(value) is str and not len(value) % 2
            and all(c in "0123456789abcdef" for c in value)):
        return bytes.fromhex(value)
    raise ValueError("invalid native cell")


def _rows(value):
    if type(value) is not dict or set(value) != {"rows"} or type(value["rows"]) is not list:
        return None
    result = []
    try:
        for row in value["rows"]:
            if type(row) is not list:
                return None
            card = {}
            for pair in row:
                if (type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str
                        or pair[0] == "repo" or pair[0] in card):
                    return None
                card[pair[0]] = _cell(pair[1])
            if not {"run_id", "runtime", "session_id"}.issubset(card):
                return None
            result.append(card)
    except (ValueError, OverflowError):
        return None
    return result


def _request(project, operation, fields):
    if type(project) is not type(Path()):
        return None
    try:
        if not NativeProbe.available():
            return None
        # Retain the canonical per-read-scope identity memo.
        repo = repository_key(project)
        return NativeProbe.request("--cards-probe", operation, {"repo": repo, **fields})
    except (OSError, ValueError, RuntimeError):
        return None


class NativeCards:
    @staticmethod
    def list(project, include_settled):
        if type(include_settled) is not bool:
            return None
        return _rows(_request(project, "list", {"include_settled": include_settled}))

    @staticmethod
    def context(project, current_work_id):
        if type(current_work_id) is not str:
            return None
        value = _request(project, "context", {"current_work_id": current_work_id})
        if (type(value) is not dict or set(value) != {"lines", "stale"}
                or type(value["lines"]) is not list or len(value["lines"]) > 5
                or any(type(line) is not str for line in value["lines"])
                or type(value["stale"]) is not list or len(value["stale"]) > 20):
            return None
        for pair in value["stale"]:
            if (type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str
                    or pair[0] == current_work_id or type(pair[1]) is not str
                    or pair[1] not in ("done", "cancelled")):
                return None
        return value
