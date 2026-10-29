"""Deterministic decision-source attribution and open-choice Grill-Me gating."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

DECISION_SOURCE_KINDS = ("request", "conversation", "repo", "assumed")
MAX_DECISION_VALUE_CHARS = 240
_FORBIDDEN_REPO_PARTS = frozenset({".git", ".moru"})
_REPO_CITATION_RE = re.compile(
    r"^(?P<path>[^:#]+?)(?:(?::|#L)(?P<start>\d+)(?:-(?:L)?(?P<end>\d+))?)?$"
)


def add_decision_attribution_arguments(group: argparse._ArgumentGroup) -> None:
    """Register decision-source attribution and open-choice CLI flags on start."""
    group.add_argument(
        "--decision-source", action="append", default=[],
        help="attribute a decision to request:<quote>, conversation:<quote>, repo:<path[:line]>, or assumed:<choice>",
    )
    group.add_argument(
        "--open-choice", action="append", default=[],
        help="declare an unresolved user-visible choice that requires Grill-Me alignment before writable work",
    )
    group.add_argument(
        "--ambiguity", choices=("", "resolved", "blocking"), default="",
        help="explicit ambiguity state for compact start; defaults to blocking when open choices exist, else resolved",
    )


def _verbatim_contains(haystack: str, needle: str) -> bool:
    text, target = str(haystack or ""), str(needle or "").strip()
    return bool(target and target in text)


def parse_decision_source_entry(raw: str) -> tuple[dict[str, str] | None, str]:
    """Parse ``<kind>:<value>`` into a verbatim attribution record."""
    text = str(raw or "").strip()
    if ":" not in text:
        return None, (
            f"--decision-source `{text}` must use `<kind>:<value>` where <kind> is "
            f"one of: {', '.join(DECISION_SOURCE_KINDS)}"
        )
    kind_raw, value_raw = text.split(":", 1)
    kind, value = kind_raw.strip().lower(), value_raw.strip()
    if kind not in DECISION_SOURCE_KINDS:
        return None, f"--decision-source kind `{kind}` is invalid; choose one of: {', '.join(DECISION_SOURCE_KINDS)}"
    if not value:
        return None, f"--decision-source `{kind}:` requires a non-empty citation or choice"
    if len(value) > MAX_DECISION_VALUE_CHARS or "\n" in value_raw or "\x00" in value_raw:
        return None, f"--decision-source `{kind}:...` must be a single line of at most {MAX_DECISION_VALUE_CHARS} characters"
    return {"kind": kind, "value": value}, ""


def _verify_repo_citation(project: Path | None, citation: str) -> str:
    if project is None:
        return ""
    match = _REPO_CITATION_RE.match(citation.strip())
    if not match:
        return f"--decision-source `repo:{citation}` is not a valid `<path[:line]>` citation"
    rel_path = match.group("path").strip()
    rel_parts = Path(rel_path).parts
    if not rel_path or Path(rel_path).is_absolute():
        return f"--decision-source `repo:{citation}` must be a project-relative file path"
    if any(part in _FORBIDDEN_REPO_PARTS for part in rel_parts):
        return f"--decision-source `repo:{citation}` cannot cite internal `.git` or `.moru` state files"
    try:
        project_root = project.expanduser().resolve()
        resolved = (project_root / rel_path).resolve()
        resolved.relative_to(project_root)
    except (OSError, RuntimeError, ValueError):
        return f"--decision-source `repo:{citation}` resolves outside the project root"
    if not resolved.is_file():
        return f"--decision-source `repo:{citation}` does not match an existing file in {project_root}"
    start_str, end_str = match.group("start"), match.group("end")
    if start_str is not None:
        start_line = int(start_str)
        end_line = int(end_str) if end_str is not None else start_line
        try:
            line_count = len(resolved.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            return f"--decision-source `repo:{citation}` could not be read"
        if start_line < 1 or end_line < start_line or end_line > max(line_count, 1):
            return f"--decision-source `repo:{citation}` line range is out of bounds (file has {line_count} lines)"
    return ""


def verify_decision_source(
    entry: dict[str, str], *, project: Path | None, request_text: str, continuation_scope: str
) -> str:
    """Verify a parsed decision source against request, continuation scope, or repo."""
    kind, value = entry["kind"], entry["value"]
    if kind == "request":
        if not _verbatim_contains(request_text, value):
            return (
                f"--decision-source `request:{value}` is not a verbatim substring of --request; "
                "do not attribute agent inferences to the user's request. Use "
                "`conversation:<quote>` if settled in --continuation-scope, `repo:<path[:line]>` "
                "if fixed by repository code, or `--open-choice` / `assumed:<choice>` if open"
            )
        return ""
    if kind == "conversation":
        if not _verbatim_contains(continuation_scope, value):
            return (
                f"--decision-source `conversation:{value}` is not a verbatim substring of "
                "--continuation-scope; pass the user's confirmed answer in "
                "--continuation-scope before claiming conversation attribution"
            )
        return ""
    return _verify_repo_citation(project, value) if kind == "repo" else ""


def evaluate_decision_attribution(
    *,
    project: Path | None,
    request_text: str,
    continuation_scope: str,
    raw_sources: list[str] | None = None,
    raw_open_choices: list[str] | None = None,
    declared_ambiguity: str = "",
) -> dict[str, Any]:
    """Validate decision sources and open choices and derive ambiguity state."""
    sources: list[dict[str, str]] = []
    open_choices: list[str] = []
    problems: list[str] = []
    for raw in raw_sources or []:
        entry, parse_error = parse_decision_source_entry(raw)
        if parse_error or entry is None:
            problems.append(parse_error)
            continue
        verify_error = verify_decision_source(
            entry, project=project, request_text=request_text, continuation_scope=continuation_scope
        )
        if verify_error:
            problems.append(verify_error)
            continue
        sources.append(entry)
        if entry["kind"] == "assumed" and entry["value"] not in open_choices:
            open_choices.append(entry["value"])
    for raw_choice in raw_open_choices or []:
        cleaned = str(raw_choice or "").strip()
        if not cleaned:
            problems.append("--open-choice requires a non-empty description of the open decision")
        elif len(cleaned) > MAX_DECISION_VALUE_CHARS or "\n" in str(raw_choice) or "\x00" in str(raw_choice):
            problems.append(f"--open-choice must be a single line of at most {MAX_DECISION_VALUE_CHARS} characters")
        elif cleaned not in open_choices:
            open_choices.append(cleaned)
    ambiguity = declared_ambiguity.strip() if declared_ambiguity else ""
    if open_choices:
        if ambiguity == "resolved":
            problems.append(
                "--ambiguity resolved cannot be combined with --open-choice or "
                "`--decision-source assumed:...`; open choices remain blocking until the user answers"
            )
        ambiguity = "blocking"
    elif ambiguity not in ("resolved", "blocking"):
        ambiguity = "resolved"
    return {"ambiguity": ambiguity, "decision_sources": sources, "open_choices": open_choices, "problems": problems}


def format_open_choice_grill_me_refusal(command: str, open_choices: list[str]) -> str:
    """Format the Grill-Me / Co-Design ping-pong refusal for blocking work starts."""
    summary = "; ".join(open_choices) if open_choices else "blocking ambiguity declared"
    return (
        f"compact `{command}` start blocked by unresolved open choice(s) ({summary}); "
        "do not auto-fill user-visible design, UX flow, or prose/thesis choices. "
        "Align with the user first (or start `--command triage` / `--command ambiguity`): "
        "(1) share bounded repo findings and any coupled adjacent/sibling surfaces, "
        "(2) show a concrete 2-3 line copy sample or design sketch, and "
        "(3) ask the focused decision question(s), then re-run start with the user's "
        "answer in `--continuation-scope` and `--decision-source conversation:<quote>`"
    )


def validate_envelope_decision_fields(envelope: dict[str, Any]) -> list[str]:
    """Validate optional ``decision_sources`` and ``open_choices`` on an envelope."""
    failures: list[str] = []
    has_open = False
    if "open_choices" in envelope:
        choices = envelope["open_choices"]
        if not isinstance(choices, list) or not all(
            isinstance(item, str) and 1 <= len(item.strip()) <= MAX_DECISION_VALUE_CHARS and "\n" not in item and "\x00" not in item
            for item in choices
        ):
            failures.append("intent envelope `open_choices` must be a list of bounded single-line strings")
        elif choices:
            has_open = True
    if "decision_sources" in envelope:
        sources = envelope["decision_sources"]
        if not isinstance(sources, list):
            failures.append("intent envelope `decision_sources` must be a list")
        else:
            for item in sources:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"kind", "value"}
                    or item.get("kind") not in DECISION_SOURCE_KINDS
                    or not isinstance(item.get("value"), str)
                    or not (1 <= len(item["value"].strip()) <= MAX_DECISION_VALUE_CHARS)
                    or "\n" in item["value"]
                    or "\x00" in item["value"]
                ):
                    failures.append(
                        "intent envelope `decision_sources` entries must be "
                        "`{\"kind\": <request|conversation|repo|assumed>, \"value\": <text>}`"
                    )
                    break
                if item.get("kind") == "assumed":
                    has_open = True
    if has_open and envelope.get("ambiguity") == "resolved":
        failures.append(
            "intent envelope cannot claim ambiguity `resolved` when `open_choices` "
            "or `assumed` decision sources are present"
        )
    return failures


def verify_envelope_decision_sources(
    envelope: dict[str, Any], *, project: Path | None = None, request_text: str = "", continuation_scope: str = ""
) -> list[str]:
    """Verify ``decision_sources`` in any envelope against request/continuation/repo."""
    sources = envelope.get("decision_sources")
    if not isinstance(sources, list) or not sources:
        return []
    failures: list[str] = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        kind, value = str(item.get("kind") or ""), str(item.get("value") or "").strip()
        if kind in ("request", "conversation") and not (request_text or continuation_scope):
            continue
        error = verify_decision_source(
            {"kind": kind, "value": value}, project=project, request_text=request_text, continuation_scope=continuation_scope
        )
        if error:
            failures.append(error)
    return failures


def build_compact_envelope_and_approval(
    *, command: str, fingerprint: str, session_id: str, intent: str, target: str,
    requested_effect: str, approved: str, prohibited: list[str], attribution: dict[str, Any], schema_version: int = 1,
) -> tuple[str, str]:
    """Serialize the compact-start intent envelope and optional approval JSON."""
    envelope: dict[str, Any] = {
        "schema_version": schema_version, "request_fingerprint": fingerprint, "runtime_session_id": session_id,
        "mode": "work", "intent": intent, "target_summary": target,
        "requested_effects": [requested_effect], "ambiguity": attribution["ambiguity"],
    }
    if prohibited:
        envelope["prohibited_effects"] = prohibited
    if attribution.get("decision_sources"):
        envelope["decision_sources"] = attribution["decision_sources"]
    if attribution.get("open_choices"):
        envelope["open_choices"] = attribution["open_choices"]
    envelope_json = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    approval_json = (
        json.dumps(
            {"request_fingerprint": fingerprint, "target_summary": target, "effect": approved, "command": command},
            ensure_ascii=False, separators=(",", ":"),
        )
        if approved else ""
    )
    return envelope_json, approval_json
