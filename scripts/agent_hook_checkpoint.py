"""Strict provider-neutral continuation checkpoint command."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from agent_checkpoint_input import normalize_work, step_name
from agent_continuation_checkpoint import CHECKPOINT_KINDS, write_continuation_checkpoint
from agent_continuation_fields import MAX_SHORT_TEXT, MAX_TEXT
from agent_continuation_packet import (
    MAX_PACKET_BYTES,
    MUTATION_KINDS,
    PHASES,
    ContinuationPacketError,
)
from agent_hook_continuation import run_binding_path
from agent_hook_runtime import finish_with_result

# Mirrors agent_continuation_fields.CHECKPOINT_RE and its 64-character bound.
LAST_COMPLETED_RULE = "1-64 chars of a-z, A-Z, 0-9, space, '_', '.', '/', '-'"


def add_checkpoint_arguments(parser: argparse.ArgumentParser) -> None:
    checkpoint = parser.add_argument_group("continuation checkpoint")
    checkpoint.add_argument("--checkpoint-kind", "--checkpoint", choices=CHECKPOINT_KINDS)
    checkpoint.add_argument("--phase", choices=PHASES)
    checkpoint.add_argument(
        "--last-completed",
        help=f"short step name ({LAST_COMPLETED_RULE}); put prose in the work object",
    )
    checkpoint.add_argument("--mutation-kind", choices=MUTATION_KINDS)
    checkpoint.add_argument("--mutation-path", action="append", default=[])
    work_input = checkpoint.add_mutually_exclusive_group()
    work_input.add_argument("--work-json", help="one inline JSON work object")
    work_input.add_argument(
        "--work-stdin",
        action="store_true",
        help="read one schema-bounded partial work object from stdin",
    )
    work_input.add_argument(
        "--work-file",
        type=Path,
        metavar="PATH",
        help="read one schema-bounded UTF-8 JSON work object without stdin or a terminal",
    )
    checkpoint.add_argument(
        "--work-shape",
        action="store_true",
        help="print the work object's fields, limits and enums, and do nothing else",
    )
    checkpoint.add_argument(
        "--work-template", action="store_true",
        help="print a minimal JSON work object without reading stdin or writing state",
    )


def checkpoint_hook(args: argparse.Namespace) -> int:
    """Write one strict checkpoint; failures never permit a mutation to start."""

    if getattr(args, "work_template", False):
        print(json.dumps({"objective": "Describe the bounded task outcome"}, indent=2))
        return 0
    if getattr(args, "work_shape", False):
        # Asked for, rather than printed by every start in every session. The
        # schema is nine unchanging lines; a reader needs them once.
        from agent_hook_continuation import _work_shape_lines

        return _result(args, True, "\n".join(_work_shape_lines()))

    try:
        binding = run_binding_path(args)
    except PermissionError:
        # A sandboxed runtime cannot take the run-state lock; a traceback here
        # read as a Moru crash rather than a permission to request.
        return _result(args, False, "checkpoint unavailable: run state is not writable "
                       "from this sandbox; rerun the same command with write permission")
    if binding is None:
        return _result(args, False, "checkpoint requires exact run-local evidence")
    try:
        work_file = getattr(args, "work_file", None)
        work = _read_work_file(work_file) if work_file is not None else (
            _read_work_stdin() if args.work_stdin else None
        )
        if getattr(args, "work_json", None) is not None:
            work = _decode_work_input(args.work_json.encode("utf-8"))
        warnings = []
        if work is not None:
            work = normalize_work(work, args.project, warnings)
        mutation = None
        if args.checkpoint_kind == "pre_mutation":
            mutation = {
                "kind": str(args.mutation_kind or ""),
                "paths": list(args.mutation_path),
            }
        packet = write_continuation_checkpoint(
            project=args.project,
            rules=args.rules,
            run_id=binding.parent.name,
            kind=args.checkpoint_kind,
            binding_path=binding,
            work=work,
            phase=args.phase,
            last_completed=step_name(args.last_completed),
            mutation=mutation,
        )
    except ContinuationPacketError as error:
        rules = ", ".join(
            f"{item['rule']}@{item['pointer']}" for item in error.failures
        )
        prose_hint = ""
        if any(item["rule"] == "prose_too_long" for item in error.failures):
            prose_hint = (
                f"Shorten the rejected prose to at most {MAX_TEXT} Unicode characters "
                f"per field ({MAX_SHORT_TEXT} for each non_goals entry), not bytes. "
                "Eligible summary fields are truncated with a warning. Resubmit rejected fields within their limits.\n"
            )
        if any(item["pointer"] == "/checkpoint/last_completed" for item in error.failures):
            prose_hint += (
                f"--last-completed is a step name ({LAST_COMPLETED_RULE}), such as "
                "\"tests passed\"; put the sentence in the work object.\n"
            )
        return _result(
            args, False,
            f"checkpoint refused: {rules}\n"
            f"{prose_hint}"
            f"{_work_input_shape_hint(error.failures)}"
            "Use checkpoint --work-template for minimal JSON, or --work-shape "
            "for optional fields. Keep scope paths repository-relative; evidence "
            "hashes must be real SHA-256 values, not result labels. A post_mutation "
            "requires a recorded pre_mutation and must omit verification entirely. "
            "For a lost post hook or baseline use --checkpoint-kind reconcile "
            "in the exact owning session, with --phase acting (or blocked), "
            "objective, verification: [], and changed_scope acknowledging every "
            "pending and previously changed path. Re-read the worktree first; "
            "reconciliation grants no verification or publication authority. "
            "Do not fabricate past mutation or verification evidence.",
        )
    except ValueError as error:
        return _result(args, False, f"checkpoint refused: {error}")
    except (OSError, RuntimeError) as error:
        return _result(args, False, f"checkpoint unavailable: {type(error).__name__}")
    return finish_with_result(
        "checkpoint",
        True,
        [
            *dict.fromkeys(warnings),
            f"checkpoint kind: {args.checkpoint_kind}",
            f"packet generation: {packet['generation']}",
        ],
        args.output,
        {"checkpoint": {"kind": args.checkpoint_kind, "generation": packet["generation"]}},
        args.repair_cycle,
    )


def _work_input_shape_hint(failures: list[dict[str, str]]) -> str:
    """Show rejected fields' canonical shapes without echoing submitted values."""

    from agent_hook_continuation import _work_shape_lines

    fields = set()
    for item in failures:
        parts = item["pointer"].split("/")
        if len(parts) < 3 or parts[1] != "work" or not parts[2]:
            continue
        if item["rule"] != "unknown_field":
            fields.add(parts[2])
    shapes = [
        line for line in _work_shape_lines()
        if any(re.search(rf"\b{re.escape(field)}(?:\[|:)", line)
               for field in fields)
    ]
    examples = {
        "changed_scope": [{"path": "docs/guide.md", "role": "modified"}],
        "inspected_scope": [{"path": "docs/guide.md", "role": "inspected"}],
        "remaining_work": [{"checkpoint": "verify", "action": "Verify the remaining outcomes"}],
        "decisions": [{"id": "scope", "status": "accepted", "text": "Keep the agreed scope"}],
        "verification": [{"id": "unit", "kind": "unit", "result": "success",
                          "evidence_sha256": None, "completed_at": "2026-11-19T12:00:00Z"}],
        "objective": "Verify the requested outcome", "blockers": ["Record the outstanding dependency"],
        "non_goals": ["Unrequested changes"], "acceptance_criteria": ["Verify each outcome"],
        "requirements": {"revision": 1, "items": [{"id": "r1", "outcome": "Verify the requested outcome",
                         "owner": "lead", "gate": "tests", "artifacts": ["src/app.py"]}]},
        "evidence_refs": [{"id": "result", "path": "/absolute/path/result.txt", "sha256": "0" * 64,
                           "status": "unverified", "summary": "Replace the example path and digest with actual evidence"}],
    }
    shapes.extend(json.dumps({field: examples[field]}) for field in sorted(fields & examples.keys()))
    if not shapes:
        return 'Example work object: {"objective":"Verify the requested outcome"}\n'
    return (
        "Expected work input (schema shapes; entries in braces are objects):\n"
        + "\n".join(shapes) + "\n"
    )


def _read_work_stdin() -> dict[str, Any]:
    return _decode_work_input(sys.stdin.buffer.read(MAX_PACKET_BYTES + 1))


def _read_work_file(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        return _decode_work_input(source.read(MAX_PACKET_BYTES + 1))


def _decode_work_input(encoded: bytes) -> dict[str, Any]:
    if len(encoded) > MAX_PACKET_BYTES:
        raise ValueError("work input exceeds packet budget")
    try:
        decoded = encoded.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("work input must be UTF-8") from None
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        raise ValueError("work input must be valid JSON") from None
    if not isinstance(payload, dict):
        raise ValueError("work input must be an object")
    return payload


def _result(args: argparse.Namespace, success: bool, detail: str) -> int:
    return finish_with_result(
        "checkpoint",
        success,
        [detail],
        args.output,
        {},
        args.repair_cycle,
        invocation_error=not success,
    )
