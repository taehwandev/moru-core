"""Prompt and argv construction for a bounded Codex handoff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping

from agent_execution_capsule import capsule_path_for_evidence
from agent_gate_evidence import gate_evidence_path_for_preflight
from agent_worker_evidence import create_worker_reservation, worker_reservation_matches

WORKER_RESULT_SCHEMA = "worker_result_v1"
MAX_WORKER_RESULT_BYTES = 4096
MAX_WORKER_SUMMARY_BYTES = 600
MAX_WORKER_FINDINGS = 10
MAX_STREAM_TAIL_BYTES = 8192
MIN_COMPACT_BLOCKER_BYTES = 120
MAX_WORKER_BLOCKERS = 10
WORKER_RESULT_STATUSES = ("ok", "findings", "blocked", "needs_inspection")
READ_ONLY_NATIVE_AGENT_TYPE = "moru_explorer"


def _check_no_symlink(path: Path) -> None:
    if path.is_symlink():
        raise OSError(f"Symbolic link detected in worker output path: {path}")


def _utf8_truncate(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[: max(0, max_bytes)].decode("utf-8", errors="ignore")


def _json_string_truncate(value: str, max_bytes: int) -> str:
    """Truncate so the JSON-escaped string body, not only the raw text, fits ``max_bytes``."""

    truncated = _utf8_truncate(value, max_bytes)
    while truncated and len(json.dumps(truncated, ensure_ascii=False).encode("utf-8")) - 2 > max_bytes:
        truncated = truncated[:-1]
    return truncated


def worker_output_paths(handoff_state: Mapping[str, object]) -> dict[str, str]:
    """Return per-worker run-local paths for spooled logs and the bounded return packet."""

    parent_preflight = (
        Path(str(handoff_state.get("preflight_evidence") or ".moru/preflight.json"))
        .expanduser()
        .absolute()
    )
    worker_preflight = handoff_state.get("worker_preflight_evidence")
    raw_slot = (
        Path(str(worker_preflight)).parent.name if worker_preflight else "default"
    )
    slot = "".join(ch for ch in raw_slot if ch.isalnum() or ch in "-_") or "default"
    output_dir = parent_preflight.parent / "worker-outputs" / slot
    return {
        "last_message_path": str(output_dir / "worker-last-message.txt"),
        "result_path": str(output_dir / "worker-result.json"),
        "stream_log_path": str(output_dir / "worker-stream.log"),
        "details_path": str(output_dir / "worker-details.md"),
    }


def prepare_worker_output_dir(
    handoff_state: Mapping[str, object], *, clear_stale: bool = False
) -> dict[str, str]:
    """Ensure the worker output directory is symlink-free and optionally clear stale outputs."""

    paths = worker_output_paths(handoff_state)
    output_dir = Path(paths["result_path"]).parent
    _check_no_symlink(output_dir.parent.parent)
    _check_no_symlink(output_dir.parent)
    output_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _check_no_symlink(output_dir)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    for file_path in paths.values():
        candidate = Path(file_path)
        _check_no_symlink(candidate)
    if clear_stale:
        for key in ("last_message_path", "details_path"):
            stale = Path(paths[key])
            if stale.is_file():
                stale.unlink()
    return paths


def codex_argv(
    project: Path,
    profile: Mapping[str, object],
    sandbox_mode: str,
    handoff_prompt: str,
    working_dir: Path | None = None,
    *,
    trusted_worktree: Path | None = None,
    output_last_message: Path | None = None,
) -> list[str]:
    # ``--cd`` binds the worker's working directory. For an isolated worker that
    # is its dedicated git worktree; otherwise it is the shared project checkout.
    cd = working_dir if working_dir is not None else project
    config_args = [
        "--config",
        f'model_reasoning_effort="{profile["reasoning_effort"]}"',
    ]
    if trusted_worktree is not None:
        trusted = Path(trusted_worktree).expanduser().resolve()
        bound = Path(cd).expanduser().resolve()
        if working_dir is None or trusted != bound:
            raise ValueError(
                "Codex worktree trust must target the exact verified --cd path"
            )
        quoted_path = json.dumps(str(trusted), ensure_ascii=False)
        config_args.extend(
            [
                "--config",
                f'projects={{ {quoted_path} = {{ trust_level = "trusted" }} }}',
            ]
        )
    output_args = (
        ["-o", str(Path(output_last_message).expanduser())]
        if output_last_message is not None
        else []
    )
    return [
        "codex",
        "exec",
        "--model",
        str(profile["codex_model"]),
        *config_args,
        "--sandbox",
        sandbox_mode,
        "--cd",
        str(cd),
        *output_args,
        handoff_prompt,
    ]


def native_worker_dispatch(
    mode: str,
    profile: Mapping[str, object],
    prompt: str,
    handoff: Mapping[str, object],
    *,
    sandbox_mode: str,
    parent_sandbox_mode: str,
) -> tuple[str, dict[str, str] | None]:
    if mode != "native":
        return mode, None
    if not _has_reusable_capsule(handoff):
        return "inline", None
    # A native spawn inherits the parent sandbox: narrow it through the read-only
    # role, and never widen it from a read-only parent.
    if parent_sandbox_mode == "read-only" and sandbox_mode != "read-only":
        return "inline", None
    worker = {
        "fork_turns": "none",
        "model": str(profile["codex_model"]),
        "reasoning_effort": "low",
        "message": prompt + (
            "\nExecute only the parent's resolved steps. Return failures or new decisions to the parent; "
            "do not redesign, retry with broader effects, or change parent settings."
        ),
    }
    if sandbox_mode == "read-only" and parent_sandbox_mode != "read-only":
        worker["agent_type"] = READ_ONLY_NATIVE_AGENT_TYPE
    return "native", worker


def execution_policy(execution_mode: str) -> str:
    if execution_mode == "native":
        return (
            "Use the runtime's native spawn tool with native_worker arguments and a scoped task name. "
            "Keep the parent's selected model and effort unchanged. --execute must not start another Codex process. "
            "If native model/effort selection is unavailable, retain the parent session; never claim a low worker ran."
        )
    if execution_mode == "inline":
        return "Continue inline in the parent; dispatch --execute must not start another Codex process."
    return (
        "Inspect-only manifest intentionally withholds the raw worker command. "
        "Use --execute to revalidate the capsule and reserve isolated worker "
        "evidence immediately before launch."
    )


def build_handoff_state(
    *,
    command: str,
    project: Path,
    lexical_project: Path,
    rules: Path,
    route: Mapping[str, object] | None,
    parent_evidence: Path,
    parent_context_reusable: bool,
    worker_evidence_path: Path | None,
    execution_mode: str,
    reserve_worker_evidence: bool,
    worker_reservation_token: str,
    defer_capsule_validation: bool,
    execution_capsule_state: Callable[..., dict[str, object]],
    isolated_worker_evidence: Callable[..., Path],
) -> dict[str, object]:
    """Create the parent evidence and fallback worker boundary for a manifest."""

    if defer_capsule_validation:
        # ``dispatch --execute`` immediately transfers control to the launch
        # boundary. Hashing the full worktree here and again at launch doubles
        # its cost without increasing safety.
        capsule_state: dict[str, object] = {
            "path": str(capsule_path_for_evidence(parent_evidence)),
            "reusable": False,
            "invalidation_reasons": ["execution capsule validation deferred to launch"],
            "phase": "pending",
        }
    else:
        capsule_state = execution_capsule_state(
            project,
            rules,
            parent_evidence,
            route,
            parent_context_reusable=parent_context_reusable,
        )
    worker_evidence = isolated_worker_evidence(
        project,
        parent_evidence,
        worker_evidence_path,
        lexical_project=lexical_project,
        reserve=False,
    )
    token = worker_reservation_token or None
    pre_reserved = bool(token) and worker_reservation_matches(
        worker_evidence.parent, str(token)
    )
    if token and not pre_reserved:
        raise ValueError(
            "Fallback worker reservation token does not match the requested evidence path."
        )
    should_reserve = (
        reserve_worker_evidence
        and not defer_capsule_validation
        and execution_mode == "child"
        and not bool(capsule_state.get("reusable"))
        and not pre_reserved
    )
    if should_reserve:
        worker_evidence = isolated_worker_evidence(
            project, parent_evidence, worker_evidence, reserve=True
        )
        token = create_worker_reservation(worker_evidence.parent)
    required_docs_list = list(route.get("required_docs", [])) if route else []
    gates_list = list(route.get("gates", [])) if route else []
    verification_plan = "run the nearest verification required by the parent route"
    output_paths = worker_output_paths(
        {
            "preflight_evidence": str(parent_evidence),
            "worker_preflight_evidence": str(worker_evidence),
            "worker_evidence_reserved": pre_reserved or should_reserve,
        }
    )
    return {
        "route_command": command,
        "route_manifest": dict(route or {}),
        "required_docs": required_docs_list,
        "gates": gates_list,
        "rules": str(rules),
        "preflight_evidence": str(parent_evidence),
        "gate_ledger": str(gate_evidence_path_for_preflight(parent_evidence)),
        "worker_preflight_evidence": str(worker_evidence),
        "worker_gate_ledger": str(gate_evidence_path_for_preflight(worker_evidence)),
        "worker_evidence_reserved": pre_reserved or should_reserve,
        "worker_reservation_token": token,
        "parent_context_reusable": parent_context_reusable,
        "capsule_validation_deferred": defer_capsule_validation,
        "execution_capsule": capsule_state,
        "verification_plan": verification_plan,
        "worker_output_paths": output_paths,
        "worker_view": {
            "route_command": command,
            "required_docs": required_docs_list,
            "gates": gates_list,
            "verification_plan": verification_plan,
            "return_schema": WORKER_RESULT_SCHEMA,
            "max_return_bytes": MAX_WORKER_RESULT_BYTES,
            "output_paths": output_paths,
        },
    }


def build_handoff_prompt(
    command: str,
    request: str,
    work_kind: str,
    handoff_state: Mapping[str, object],
    *,
    non_authoring: bool,
    continuation_scope: str = "",
) -> str:
    required_docs = ", ".join(str(doc) for doc in handoff_state["required_docs"])
    gates = ", ".join(str(gate) for gate in handoff_state["gates"])
    instructions = [
        "You are a delegated Codex worker for one bounded task stage.",
        "Do not delegate another Codex child from this worker.",
        "Follow the scoped handoff and preserve existing user changes.",
    ]
    if non_authoring:
        instructions.append(
            "This is a read-only non-authoring stage. Do not modify files, write code, generate patches, or create tests."
        )
    _add_capsule_instructions(instructions, handoff_state)
    reusable_capsule = _has_reusable_capsule(handoff_state)
    evidence_instruction = (
        "Do not read parent preflight.json, gate-evidence.json, AGENTS.md, or required_docs; use this bounded handoff view and do not overwrite parent gate-ledger entries."
        if reusable_capsule
        else "Read existing parent evidence when present. Do not overwrite parent gate-ledger entries."
    )
    instructions.extend(
        [
            f"Workflow command: {command}",
            f"Work kind: {work_kind}",
            f"Moru Core rules root: {handoff_state['rules']}",
            f"Parent route gates: {gates or 'resolve from the route'}",
            f"Parent preflight evidence: {handoff_state['preflight_evidence']}",
            f"Parent gate ledger: {handoff_state['gate_ledger']}",
            f"Verification plan: {handoff_state['verification_plan']}",
            evidence_instruction,
            f"Return contract: emit {WORKER_RESULT_SCHEMA} (<= {MAX_WORKER_RESULT_BYTES} bytes) with status (one of {', '.join(WORKER_RESULT_STATUSES)}), summary, changed_paths, findings, checks, blockers, next_action, and artifacts; keep raw diffs and command logs in run-local files.",
            "User request:",
            request,
        ]
    )
    if continuation_scope:
        instructions.extend(
            [
                "Continuation target (target identity only; not current intent or authorization):",
                continuation_scope,
            ]
        )
    if reusable_capsule:
        instructions.insert(
            instructions.index(f"Parent route gates: {gates or 'resolve from the route'}"),
            f"Required docs already read by the parent: {required_docs or 'none'}",
        )
    else:
        instructions.insert(
            instructions.index(f"Parent route gates: {gates or 'resolve from the route'}"),
            "Open and read every required doc from the parent route manifest before editing, reviewing, or running project-specific work.",
        )
        instructions.insert(
            instructions.index("Open and read every required doc from the parent route manifest before editing, reviewing, or running project-specific work."),
            f"Required docs from the parent route: {required_docs or 'resolve from the route'}",
        )
    return "\n".join(instructions)


def _add_capsule_instructions(
    instructions: list[str], handoff_state: Mapping[str, object]
) -> None:
    capsule_state = handoff_state.get("execution_capsule") or {}
    if isinstance(capsule_state, Mapping) and capsule_state.get("reusable"):
        instructions.extend(
            [
                f"Validated parent execution capsule: {capsule_state['path']}",
                "The parent already completed route, preflight, required-doc reading, VibeGuard, and review preparation.",
                "Reuse that route, preflight, and document-read evidence. Do not reread required docs or rerun route, startup, preflight, VibeGuard, review, finish, or other lifecycle work.",
                "Return only scoped implementation and verification evidence to the parent for its single integration, workflow validation, and final review.",
                "The parent remains the only owner of the gate ledger; child runtime guards make parent evidence read-only.",
            ]
        )
        return
    reasons = "; ".join(
        str(reason) for reason in capsule_state.get("invalidation_reasons", [])
    ) if isinstance(capsule_state, Mapping) else ""
    token = handoff_state.get("worker_reservation_token")
    instructions.extend(
        [
            "No reusable execution capsule is available. Follow the normal project lifecycle before work"
            + (f" ({reasons})." if reasons else "."),
            f"Use isolated worker preflight evidence: {handoff_state['worker_preflight_evidence']}",
            f"Use isolated worker gate ledger: {handoff_state['worker_gate_ledger']}",
            "Never write the parent evidence files.",
        ]
    )
    if token:
        instructions.append(
            f"Pass the worker preflight path with --evidence and --worker-reservation-token {token} to the worker start command; the token is single-use."
        )
    else:
        instructions.append(
            "The launcher must reserve the worker evidence directory and mint its single-use token before this worker starts."
        )


def _has_reusable_capsule(handoff_state: Mapping[str, object]) -> bool:
    capsule_state = handoff_state.get("execution_capsule")
    return isinstance(capsule_state, Mapping) and bool(capsule_state.get("reusable"))


def _read_bounded_tail(path: Path, max_bytes: int = MAX_STREAM_TAIL_BYTES) -> str:
    _check_no_symlink(path)
    if not path.is_file():
        return ""
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes), 0)
        return handle.read(max_bytes).decode("utf-8", errors="replace").strip()


def _parse_worker_json(text: str) -> Mapping[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end > start:
            stripped = stripped[start : end + 1]
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            candidate = json.loads(stripped)
            if isinstance(candidate, Mapping):
                return candidate
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_findings(raw_findings: object, *, claim_bytes: int = 240) -> list[dict[str, object]]:
    if not isinstance(raw_findings, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in raw_findings[:MAX_WORKER_FINDINGS]:
        if isinstance(item, Mapping):
            line_val = item.get("line", 0)
            line_num = int(line_val) if isinstance(line_val, int) else 0
            normalized.append(
                {
                    "file": _utf8_truncate(str(item.get("file") or ""), 160),
                    "line": line_num,
                    "severity": _utf8_truncate(str(item.get("severity") or "info"), 32),
                    "claim": _utf8_truncate(str(item.get("claim") or ""), claim_bytes),
                }
            )
        elif str(item).strip():
            normalized.append(
                {
                    "file": "",
                    "line": 0,
                    "severity": "info",
                    "claim": _utf8_truncate(str(item).strip(), claim_bytes),
                }
            )
    return normalized


def _normalize_checks(raw_checks: object, *, returncode: int) -> list[dict[str, object]]:
    default_check = {
        "cmd": "codex exec",
        "exit_code": int(returncode),
        "outcome": "pass" if returncode == 0 else "fail",
    }
    if not isinstance(raw_checks, list) or not raw_checks:
        return [default_check]
    normalized: list[dict[str, object]] = []
    for item in raw_checks[:10]:
        if isinstance(item, Mapping):
            raw_code = item.get("exit_code", returncode)
            exit_code = int(raw_code) if isinstance(raw_code, int) else int(returncode)
            normalized.append(
                {
                    "cmd": _utf8_truncate(str(item.get("cmd") or "check"), 160),
                    "exit_code": exit_code,
                    "outcome": _utf8_truncate(
                        str(item.get("outcome") or ("pass" if exit_code == 0 else "fail")), 32
                    ),
                }
            )
        elif str(item).strip():
            normalized.append(
                {
                    "cmd": _utf8_truncate(str(item).strip(), 160),
                    "exit_code": int(returncode),
                    "outcome": "pass" if returncode == 0 else "fail",
                }
            )
    if returncode != 0 and all(check.get("exit_code", 0) == 0 for check in normalized):
        normalized.insert(0, default_check)
    return normalized[:10]


def _compact_packet_to_budget(packet: dict[str, object]) -> str:
    serialized = json.dumps(packet, ensure_ascii=False)
    if len((serialized + "\n").encode("utf-8")) <= MAX_WORKER_RESULT_BYTES:
        return serialized
    for max_findings, max_paths, max_checks, str_budget in (
        (3, 10, 4, 200),
        (2, 5, 2, 120),
        (1, 3, 1, 80),
        (0, 0, 1, 48),
    ):
        packet["findings"] = [
            {
                **item,
                "file": _utf8_truncate(str(item.get("file") or ""), str_budget),
                "claim": _utf8_truncate(str(item.get("claim") or ""), str_budget),
            }
            for item in list(packet.get("findings") or [])[:max_findings]
            if isinstance(item, Mapping)
        ]
        packet["changed_paths"] = [
            _utf8_truncate(str(p), str_budget)
            for p in list(packet.get("changed_paths") or [])[:max_paths]
        ]
        packet["checks"] = [
            {
                **item,
                "cmd": _utf8_truncate(str(item.get("cmd") or "check"), str_budget),
            }
            for item in list(packet.get("checks") or [])[:max_checks]
            if isinstance(item, Mapping)
        ]
        packet["summary"] = _utf8_truncate(str(packet.get("summary") or ""), str_budget)
        packet["next_action"] = _utf8_truncate(str(packet.get("next_action") or ""), str_budget)
        packet["blockers"] = [
            _json_string_truncate(str(b), max(str_budget, MIN_COMPACT_BLOCKER_BYTES))
            for b in list(packet.get("blockers") or [])
        ]
        serialized = json.dumps(packet, ensure_ascii=False)
        if len((serialized + "\n").encode("utf-8")) <= MAX_WORKER_RESULT_BYTES:
            return serialized
    return serialized


def build_worker_result_packet(
    handoff_state: Mapping[str, object],
    *,
    returncode: int,
    raw_output: str = "",
) -> dict[str, object]:
    """Build and persist a bounded ``worker_result_v1`` packet (<= 4096 bytes)."""

    paths = prepare_worker_output_dir(handoff_state)
    last_message_path = Path(paths["last_message_path"])
    stream_log_path = Path(paths["stream_log_path"])
    details_path = Path(paths["details_path"])
    result_path = Path(paths["result_path"])

    text = raw_output.strip()
    from_stream_log = False
    if not text and last_message_path.is_file():
        _check_no_symlink(last_message_path)
        text = last_message_path.read_text(encoding="utf-8", errors="replace").strip()
    if not text and stream_log_path.is_file():
        text = _read_bounded_tail(stream_log_path)
        from_stream_log = True

    parsed = _parse_worker_json(text)
    raw_status = str(parsed.get("status") or "")
    if returncode != 0:
        status = "blocked"
    elif raw_status in WORKER_RESULT_STATUSES:
        status = raw_status
    else:
        status = "needs_inspection"

    raw_summary = str(parsed.get("summary") or text or f"worker exited with code {returncode}").strip()
    spilled = len(text.encode("utf-8")) > MAX_WORKER_SUMMARY_BYTES or len(raw_summary.encode("utf-8")) > MAX_WORKER_SUMMARY_BYTES
    if spilled and text and not from_stream_log:
        _check_no_symlink(details_path)
        details_path.write_text(text + "\n", encoding="utf-8")

    blockers_raw = parsed.get("blockers")
    blockers = (
        [_json_string_truncate(str(item).strip(), 240) for item in blockers_raw if str(item).strip()]
        if isinstance(blockers_raw, list)
        else []
    )
    if len(blockers) > MAX_WORKER_BLOCKERS:
        # Never drop a blocker silently: name the remainder and keep the full text locally.
        hidden = len(blockers) - (MAX_WORKER_BLOCKERS - 1)
        blockers = blockers[: MAX_WORKER_BLOCKERS - 1] + [
            f"{hidden} more blockers in {'the worker stream log' if from_stream_log else details_path.name}"
        ]
        if text and not from_stream_log and not details_path.is_file():
            _check_no_symlink(details_path)
            details_path.write_text(text + "\n", encoding="utf-8")
    if returncode != 0 and not blockers:
        blockers = [f"worker exited with code {returncode}"]
    if status == "needs_inspection" and not blockers:
        blockers = [
            f"worker status {raw_status!r} is not a {WORKER_RESULT_SCHEMA} status"
            if raw_status
            else f"worker returned no {WORKER_RESULT_SCHEMA} status"
        ]
    if status == "ok" and blockers:
        status = "blocked"
    changed_raw = parsed.get("changed_paths")
    changed_paths = (
        [_utf8_truncate(str(item), 160) for item in changed_raw[:25]]
        if isinstance(changed_raw, list)
        else []
    )
    packet: dict[str, object] = {
        "schema_version": WORKER_RESULT_SCHEMA,
        "status": status,
        "summary": _utf8_truncate(raw_summary, MAX_WORKER_SUMMARY_BYTES),
        "changed_paths": changed_paths,
        "findings": _normalize_findings(parsed.get("findings")),
        "checks": _normalize_checks(parsed.get("checks"), returncode=returncode),
        "blockers": blockers,
        "next_action": _utf8_truncate(
            str(
                parsed.get("next_action")
                or ("integrate worker result" if status in {"ok", "findings"} else "inspect worker stream log and blockers")
            ),
            300,
        ),
        "artifacts": {
            "result_path": str(result_path),
            "log_path": str(stream_log_path),
            "details_path": str(details_path) if details_path.is_file() else "",
        },
    }
    serialized = json.dumps(packet, ensure_ascii=False)
    if len((serialized + "\n").encode("utf-8")) > MAX_WORKER_RESULT_BYTES:
        if text and not from_stream_log and not details_path.is_file():
            _check_no_symlink(details_path)
            details_path.write_text(text + "\n", encoding="utf-8")
            packet["artifacts"] = {
                "result_path": str(result_path),
                "log_path": str(stream_log_path),
                "details_path": str(details_path),
            }
        serialized = _compact_packet_to_budget(packet)
    _check_no_symlink(result_path)
    result_path.write_text(serialized + "\n", encoding="utf-8")
    return packet
