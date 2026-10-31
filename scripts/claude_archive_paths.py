"""Read/write operands of narrowly modelled, trusted local backup commands.

Owner: archive operand roles; allowed imports: stdlib and executable trust check.
Forbidden: execution, authorization, network and filesystem changes.
Callers/tests: shell path/effect admission; test_claude_archive_paths.
Verification: backup sources remain reads; destinations and unknown forms stay protected.
"""

from __future__ import annotations

from pathlib import Path
import os

from claude_bash_paths import _resolves_to_trusted, _copy_segment_token_is_uncertain


def archive_operands(tokens: list[str]) -> tuple[frozenset[int], int] | None:
    """Return exact read token positions and the destination token, or unknown."""
    if not tokens or any(_copy_segment_token_is_uncertain(t) for t in tokens[1:]):
        return None
    name = Path(tokens[0]).name
    if name not in {"tar", "ditto"} or not _resolves_to_trusted(
        tokens[0], name, (Path("/usr/bin") / name, Path("/bin") / name)
    ):
        return None
    if name == "ditto":
        if len(tokens) == 3 and all(t and not t.startswith("-") for t in tokens[1:]):
            return frozenset({1}), 2
        return None
    return _tar_create(tokens)


def _tar_create(tokens: list[str]) -> tuple[frozenset[int], int] | None:
    if os.environ.get("TAR_OPTIONS"):
        return None  # GNU tar can inherit source-deleting or command-executing options.
    reads: set[int] = set()
    destination = None
    create = False
    members = False
    options = True
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if options and token == "--":
            options = False
        elif options and token == "-C":
            index += 1
            if index >= len(tokens) or not tokens[index] or tokens[index].startswith("-"):
                return None
            reads.add(index)
        elif options and token.startswith("-"):
            flags = token[1:]
            if not flags or set(flags) - set("cfzjJv") or flags.count("f") > 1:
                return None
            if "c" in flags:
                if create:
                    return None
                create = True
            if "f" in flags:
                if destination is not None or not flags.endswith("f"):
                    return None
                index += 1
                if index >= len(tokens) or not tokens[index] or tokens[index].startswith("-"):
                    return None
                destination = index
        else:
            if not token:
                return None
            reads.add(index)
            members = True
        index += 1
    if (not create or destination is None or not members
            or not Path(tokens[destination]).expanduser().is_absolute()):
        return None
    return frozenset(reads), destination
