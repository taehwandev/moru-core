"""Exact literal boundary matching without regular expression compilation.

Owner: scripts/support/literal_boundary.py
Allowed imports: none beyond Python's future annotations.
Forbidden: re module imports/compilation, case normalization/folding, global
    mutable caches, external dependencies, and filesystem/network/provider I/O.
Callers: agent_project_search._contains_strict_name; no selection policy here.
Tests: test_discovery_batch verifies equivalence with
    re.search(r'(?<![a-z0-9_-])' + re.escape(name) + r'(?![a-z0-9_-])', request).
"""

from __future__ import annotations

__all__ = ["contains_literal"]


def _is_forbidden_neighbor(ch: str) -> bool:
    """Return True if ch is in the ASCII class [a-z0-9_-]."""
    return ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "_" or ch == "-"


def contains_literal(request: str, name: str) -> bool:
    """Return True iff name occurs in request without [a-z0-9_-] neighbors.

    Matches the exact semantics of:
        re.search(r'(?<![a-z0-9_-])' + re.escape(name) + r'(?![a-z0-9_-])', request) is not None

    Inputs are inspected in their exact provided code points without case
    folding or Unicode normalization.
    """
    name_len = len(name)
    req_len = len(request)
    start = 0

    while True:
        pos = request.find(name, start)
        if pos == -1:
            return False

        end = pos + name_len
        left_ok = pos == 0 or not _is_forbidden_neighbor(request[pos - 1])
        right_ok = end == req_len or not _is_forbidden_neighbor(request[end])
        if left_ok and right_ok:
            return True

        start = pos + 1
