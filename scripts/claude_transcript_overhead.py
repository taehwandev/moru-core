"""Count Moru workflow overhead in one Claude Code session transcript.

Owner: per-session parsing for the overhead report. Allowed imports: the
standard library. Forbidden: Moru state, gate records, provider calls and any
write. Callers/tests: moru_overhead_report.py,
tests/test_claude_transcript_overhead.py.

Only aggregates leave this module: counts, token sums, hook durations and
normalized hook messages with paths and ids removed. Prompt text and full
commands are never returned; a launcher call is reduced to its subcommand.
Transcripts written before the Tao-to-Moru rename are still recognized.
"""

from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
from typing import Any

LAUNCHER_RE = re.compile(
    r"(?:moru-hook|agent-hook|tao-hook)['\"]?\s+([A-Za-z][\w-]*)(?:\s+([A-Za-z][\w-]*))?"
)
LAUNCHER_COMMAND_RE = re.compile(r"moru-hook|tao-hook|agent-hook")
MORU_MARK_RE = re.compile(r"\b(Moru|Tao)\b|moru-hook|tao-hook|agent-hook|Agent OS")
NOTE_RE = re.compile(r"policy note|worktree gate", re.I)
SEARCH_ONLY_RE = re.compile(r"\s*(?:grep|rg|git\s+(?:log|grep|diff)|echo)\b")
GUIDANCE_TOP = {"common", "workflows", "docs", "platforms", "AGENTS.md", "CLAUDE.md", "index.md", "README.md"}
GUIDANCE_BASH_RE = re.compile(
    r"\b(?:cat|sed|head|tail|less|awk)\b[^|;&]*moru-core[^\s'\"]*/(?:common|workflows|docs|platforms)/[^\s'\"]+\.md"
)
WORKTREE_RE = re.compile(r"^(?:\.moru/worktrees|\.claude/worktrees)/[^/]+/(.*)$")
KNOWN_SUBCOMMANDS = {
    "start", "gate-batch", "gate", "review", "finish", "checkpoint", "next", "cancel",
    "fingerprint", "handoff", "resume", "agent-mailbox", "project-memory", "repair-verify",
    "setup-agent-hooks", "work-cards", "skill-feedback", "status", "doctor", "approval-record",
    "continuation", "skill-review", "claude-pretool-gate", "claude-stop-gate", "workflow",
}
COUNTERS = (
    "assistant_turns", "user_prompts", "tool_calls", "lifecycle_total", "policy_notes",
    "hook_denials", "moru_hook_denials", "stop_hook_blocks", "guidance_reads", "guidance_bash_reads",
    "tok_input", "tok_cache_read", "tok_cache_create", "tok_output",
    "moru_injected_chars", "moru_injected_events",
)


def normalize_message(text: Any) -> str:
    """Group a hook message without paths, ids or the pre-rename brand."""

    normalized = " ".join(str(text).split())
    normalized = normalized.replace("Tao Agent OS", "Moru Core").replace("Tao ", "Moru ")
    normalized = re.sub(r"(?:/private)?/(?:Users|home|tmp|var|private)[^\s`'\",;)]*", "<path>", normalized)
    normalized = re.sub(r"\b[0-9a-f]{16,}\b", "<id>", normalized)
    normalized = re.sub(r"toolu_\w+", "<toolu>", normalized)
    return normalized[:120]


def text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(text_of(item.get("text") if "text" in item else item.get("content")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return "" if content is None else str(content)


def parse_timestamp(value: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def guidance_relative_path(path: Any, moru_roots: list[str]) -> str | None:
    """The Moru guidance path a Read targeted, in a checkout or worktree, if any."""

    if not isinstance(path, str):
        return None
    for root in [candidate for base in moru_roots for candidate in (base, base + "-worktrees")]:
        if not path.startswith(root + "/"):
            continue
        relative = path[len(root) + 1:]
        if root.endswith("-worktrees"):
            relative = relative.split("/", 1)[1] if "/" in relative else ""
        nested = WORKTREE_RE.match(relative)
        if nested:
            relative = nested.group(1)
        return relative if relative.split("/", 1)[0] in GUIDANCE_TOP else None
    return None


def launcher_subcommand(command: str, *, known_only: bool = True) -> str | None:
    """The launcher subcommand; hook latency keys keep unknown names (known_only=False)."""

    match = LAUNCHER_RE.search(command)
    if not match:
        return None
    sub = match.group(1)
    if sub == "workflow" and match.group(2):
        return f"workflow {match.group(2)}"
    return sub if sub in KNOWN_SUBCOMMANDS or not known_only else "other"


class _HookEventTally:
    """Hook-produced transcript entries: injected context, notes and latency."""

    row: dict[str, Any]
    shared: dict[str, Any]

    def _attachment(self, attachment: dict[str, Any]) -> None:
        kind = attachment.get("type")
        if kind == "hook_additional_context":
            text = text_of(attachment.get("content"))
            if MORU_MARK_RE.search(text) or "continuation guidance" in text:
                self._injected(text)
            items = attachment.get("content") if isinstance(attachment.get("content"), list) else [text]
            for item in map(str, items):
                if NOTE_RE.search(item[:200]):
                    self.row["policy_notes"] += 1
                    self.shared["notes"][normalize_message(item)] += 1
            return
        command = str(attachment.get("command") or "")
        if kind not in ("hook_success", "hook_blocking_error", "hook_non_blocking_error"):
            return
        if not LAUNCHER_COMMAND_RE.search(command):
            return
        key = f"{attachment.get('hookEvent') or '?'}:{launcher_subcommand(command, known_only=False) or '?'}"
        self._latency(key, attachment.get("durationMs"))
        output = str(attachment.get("stdout") or attachment.get("content") or "")
        # Plain-text stdout is injected verbatim; JSON stdout arrives as additionalContext.
        if output.strip() and not output.lstrip().startswith("{"):
            self._injected(output)
        if kind == "hook_blocking_error":
            self.row["moru_injected_chars"] += len(str(attachment.get("blockingError") or attachment.get("stderr") or ""))

    def _stop_summary(self, entry: dict[str, Any]) -> None:
        for info in entry.get("hookInfos") or []:
            command = str(info.get("command")) if isinstance(info, dict) else ""
            if LAUNCHER_COMMAND_RE.search(command):
                self._latency(f"Stop:{launcher_subcommand(command, known_only=False) or '?'}", info.get("durationMs"))
        if entry.get("preventedContinuation"):
            self.row["stop_hook_blocks"] += 1

    def _injected(self, text: str) -> None:
        self.row["moru_injected_chars"] += len(text)
        self.row["moru_injected_events"] += 1

    def _latency(self, key: str, value: Any) -> None:
        try:
            self.shared["hook_latency"][key].append(float(value))
        except (TypeError, ValueError):
            pass


class SessionTally(_HookEventTally):
    """Accumulates one transcript; shared message counters span all sessions."""

    def __init__(self, path: str, moru_roots: list[str], shared: dict[str, Any],
                 window: tuple[dt.datetime | None, dt.datetime | None] = (None, None)) -> None:
        self.moru_roots = moru_roots
        self.shared = shared
        self.window = window
        self.row: dict[str, Any] = {name: 0 for name in COUNTERS}
        self.row.update({
            "file": os.path.basename(path), "project_dir": os.path.basename(os.path.dirname(path)),
            "cwd": None, "first_ts": None, "last_ts": None,
            "tools": collections.Counter(), "lifecycle_calls": collections.Counter(),
        })
        self._seen_messages: set[Any] = set()
        self._seen_tools: set[Any] = set()

    def add(self, entry: dict[str, Any]) -> None:
        if not self.row["cwd"] and isinstance(entry.get("cwd"), str):
            self.row["cwd"] = entry["cwd"]
        stamp = parse_timestamp(entry["timestamp"]) if entry.get("timestamp") else None
        since, until = self.window
        # A session that straddles the window contributes only its in-window entries,
        # so a before/after run right after a change does not mix in older behavior.
        if stamp and ((since and stamp < since) or (until and stamp > until)):
            return
        if stamp:
            self.row["first_ts"] = min(self.row["first_ts"] or stamp, stamp)
            self.row["last_ts"] = max(self.row["last_ts"] or stamp, stamp)
        kind = entry.get("type")
        if kind == "assistant":
            self._assistant(entry.get("message") or {}, entry.get("uuid"))
        elif kind == "user":
            self._user(entry)
        elif kind == "attachment":
            self._attachment(entry.get("attachment") or {})
        elif kind == "system" and entry.get("subtype") == "stop_hook_summary":
            self._stop_summary(entry)

    def _assistant(self, message: dict[str, Any], fallback_id: Any) -> None:
        message_id = message.get("id") or fallback_id
        if message_id not in self._seen_messages:
            self._seen_messages.add(message_id)
            self.row["assistant_turns"] += 1
            usage = message.get("usage") or {}
            for field, key in (("input_tokens", "tok_input"), ("cache_read_input_tokens", "tok_cache_read"),
                               ("cache_creation_input_tokens", "tok_cache_create"), ("output_tokens", "tok_output")):
                self.row[key] += int(usage.get(field) or 0)
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") not in self._seen_tools:
                self._seen_tools.add(block.get("id"))
                self._tool_use(block.get("name") or "?", block.get("input") or {})

    def _tool_use(self, name: str, tool_input: dict[str, Any]) -> None:
        self.row["tool_calls"] += 1
        self.row["tools"][name] += 1
        if name == "Read" and guidance_relative_path(tool_input.get("file_path"), self.moru_roots):
            self.row["guidance_reads"] += 1
        if name != "Bash":
            return
        command = str(tool_input.get("command") or "")
        sub = launcher_subcommand(command)
        if sub and not SEARCH_ONLY_RE.match(command):
            self.row["lifecycle_calls"][sub] += 1
            self.row["lifecycle_total"] += 1
        if GUIDANCE_BASH_RE.search(command):
            self.row["guidance_bash_reads"] += 1

    def _user(self, entry: dict[str, Any]) -> None:
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str) and not entry.get("isMeta"):
            self.row["user_prompts"] += 1
        if not isinstance(content, list):
            return
        decision = entry.get("permissionDecision") or {}
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_result":
                continue
            text = text_of(item.get("content"))
            from_hook = (isinstance(decision, dict) and decision.get("source") == "hook") or (
                text.startswith("PreToolUse:") and "hook error" in text[:80])
            if not (from_hook and (entry.get("toolDenialKind") or item.get("is_error"))):
                continue
            self.row["hook_denials"] += 1
            if MORU_MARK_RE.search(text[:400]):
                self.row["moru_hook_denials"] += 1
                self._injected(text)
            self.shared["denials"][normalize_message(re.sub(r"^PreToolUse:\w+ hook error:\s*", "", text))] += 1

    def finish(self) -> dict[str, Any]:
        row = self.row
        row["tok_total"] = row["tok_input"] + row["tok_cache_read"] + row["tok_cache_create"] + row["tok_output"]
        row["moru_injected_tokens_est"] = row["moru_injected_chars"] // 4
        row["moru_core"] = bool(row["cwd"] and any(row["cwd"].startswith(root) for root in self.moru_roots))
        return row


def measure_session(path: str, moru_roots: list[str], shared: dict[str, Any],
                    window: tuple[dt.datetime | None, dt.datetime | None] = (None, None)) -> dict[str, Any]:
    """Read one transcript's entries inside the window; malformed lines are skipped."""

    tally = SessionTally(path, moru_roots, shared, window)
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                try:
                    tally.add(entry)
                except (AttributeError, TypeError, ValueError):
                    continue
    return tally.finish()


def new_shared_counters() -> dict[str, Any]:
    return {
        "notes": collections.Counter(),
        "denials": collections.Counter(),
        "hook_latency": collections.defaultdict(list),
    }
