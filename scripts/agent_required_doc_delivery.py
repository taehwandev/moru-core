"""Hand an agent the required docs it has not read, at its run's first file edit.

Owner: delivery of a run's unread required docs to the model.
Allowed imports: the standard library and agent_required_doc_reuse.
Callers/tests: `claude_pretool_gate.decide` (Claude and Codex), `claude_continuation_hook`;
`tests/test_agent_required_doc_delivery.py`.
Verification: that module, which covers delivery, skipping read or reused
docs, the once-per-run marker, the size cap and every fail-quiet path.

`start` lists a route's required docs and nothing checked that they were read.
Measured on 2026-10-02: Claude sessions on c8c Android routes opened almost
none of them, while Codex read them in full. The gate already sees each file
edit, so at the first edit of a run it compares the required list with the
complete reads still in context (see `_read_in_context`). It then passes the unread docs to
the model as context, the way the hook already passes policy notes. It never
blocks: the edit gets the verdict it would have had anyway. It runs once per
run, plus at most `MAX_REDELIVERIES` more times, each after a compaction that
landed since the last delivery (the hash of an unchanged doc says nothing about
whether its text is still in context). A Moru closeout command (`review`,
`finish`, `gate-batch`) counts as an edit for this purpose and may spend one
redelivery more than the edits can, so a compaction late in the run is caught
at its last step. A delivery that cannot be computed is skipped silently, so the hook
fails towards the behaviour it had before.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from agent_required_doc_reuse import required_doc_reuse
from support.global_state import project_state_dir_target

MARKER = "required-docs-delivered.json"
# One small core contract is ~4-6 KB; the cap keeps a delivery to a few of them.
MAX_INLINE_DOC_BYTES = 8 * 1024
MAX_DELIVERY_BYTES = 24 * 1024
# A long run that compacts many times must not re-pay the delivery each time.
MAX_REDELIVERIES = 3
_LOCK_WAIT_SECONDS = 2.0
_COMPACTION_MARKS = (b'"compact_boundary"', b'"compacted"', b'"CHECKPOINT"')
# Cheap substring filters before a transcript line is parsed.
_TOOL_EVENT = ('"tool_use"', '"tool_result"', '"custom_tool_call', '"function_call',
               '"CommandExecution"')
_FRONTMATTER = re.compile(r"^---\n.*?\n---\n", re.S)
_PATCH_FILE = re.compile(r"\*\*\* (?:Update|Add|Delete) File: (\S[^\n]*)")


def edited_paths(payload: dict) -> list[Path]:
    """Files a file-edit tool call names, in either runtime's shape."""

    tool_input = payload.get("tool_input") or {}
    if isinstance(tool_input, str):
        # A patch body can arrive as the bare tool input.
        tool_input = {"input": tool_input}
    if not isinstance(tool_input, dict):
        return []
    paths = [tool_input.get(key) for key in ("file_path", "notebook_path", "path")]
    for value in tool_input.values():
        if isinstance(value, str):
            paths.extend(_PATCH_FILE.findall(value))
    cwd = Path(str(payload.get("cwd") or "."))
    return [Path(p) if Path(p).is_absolute() else cwd / p for p in paths if isinstance(p, str) and p]


def delivery_text(payload: dict, evidence_for, read_in_context=None, *, closeout: bool = False) -> str:
    """The unread required docs to show with this edit, or "" (also on any failure).

    `evidence_for(project)` returns this session's active run evidence for a
    project, or None; the gate passes its own resolver so binding stays exact.
    `read_in_context(transcript, rules, texts)` replaces the transcript reader
    for a runtime whose transcript has another shape (agy). `closeout` marks a
    Moru closeout command: it may spend one redelivery beyond the edits' budget,
    which an edit-heavy run would otherwise have used up before its last step.
    """

    try:
        evidence = _session_run(payload, evidence_for)
        if evidence is None:
            return ""
        with _serialized(evidence.parent / MARKER):
            return _deliver(payload, evidence, read_in_context, closeout)
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def compaction_text(payload: dict, evidence_for) -> str:
    """Every required doc of this session's run, right after its compaction.

    The runtime announces the compaction itself (Claude's SessionStart with
    source "compact"), so nothing is guessed from the transcript: a compaction
    drops all of the context, and every doc is owed again. The marker is moved
    to the current transcript size so the edit-time check does not deliver the
    same compaction a second time. Any failure returns "".
    """

    try:
        cwd = str(payload.get("cwd") or "")
        if not cwd:
            return ""
        evidence = _session_run({**payload, "tool_input": {"file_path": cwd}}, evidence_for)
        if evidence is None:
            return ""
        with _serialized(evidence.parent / MARKER):
            preflight = json.loads(evidence.read_text(encoding="utf-8"))
            rules = Path(preflight["rules"])
            docs = list(dict.fromkeys(preflight["route"].get("required_docs") or []))
            texts = {}
            for doc in docs:
                try:
                    texts[doc] = (rules / doc).read_text(encoding="utf-8")
                except OSError:
                    continue
            pending = [doc for doc in docs if doc in texts]
            transcript = Path(str(payload.get("transcript_path") or ""))
            _write_marker(evidence.parent / MARKER, pending, _aligned_size(transcript), 0)
            return _render(texts, pending, rules)
    except (OSError, ValueError, KeyError, TypeError):
        return ""


@contextlib.contextmanager
def _serialized(marker: Path):
    """Hold one lock over read-decide-write so two hooks cannot spend the same redelivery."""

    try:
        import fcntl

        handle = marker.with_name(marker.name + ".lock").open("a")
    except (ImportError, OSError):
        yield
        return
    with handle:
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break  # a stuck holder must not stall the turn; deliver unserialized
                time.sleep(0.02)
        yield


def _deliver(payload: dict, evidence: Path, read_in_context, closeout: bool) -> str:
    try:
        marker = evidence.parent / MARKER
        transcript = Path(str(payload.get("transcript_path") or ""))
        previous = _marker_state(marker)
        previous_offset = previous.get("transcript_bytes")
        if marker.exists():
            if type(previous_offset) is not int:
                if not _compacted_before(transcript):
                    delivered = previous.get("delivered")
                    _write_marker(marker, delivered if isinstance(delivered, list) else [],
                                  _aligned_size(transcript), 0)
                    return ""
                # Unknown when the old marker was written, so a compaction in the
                # transcript may be after it: deliver once and record the size.
            elif not _due_after_compaction(
                    previous, transcript, MAX_REDELIVERIES + (1 if closeout else 0)):
                return ""
        offset = _aligned_size(transcript, previous_offset if type(previous_offset) is int else 0)
        preflight = json.loads(evidence.read_text(encoding="utf-8"))
        rules = Path(preflight["rules"])
        docs = list(dict.fromkeys(preflight["route"].get("required_docs") or []))
        # A reuse proof says an earlier run took the doc in, not that its text is
        # in this context; a compaction since the proof was made voids it.
        reuse = {} if previous else required_doc_reuse(evidence)
        reused = set(reuse.get("reused") or [])
        if reused and _compacted_before(transcript):
            # The reuse proof carries no time, so any compaction may have evicted the
            # docs it covers; delivering again is cheap, a missing doc is not.
            reused = set()
        docs = [doc for doc in docs if doc not in reused]
        texts = {}
        for doc in docs:
            try:
                texts[doc] = (rules / doc).read_text(encoding="utf-8")
            except OSError:
                continue
        read = (read_in_context or _read_in_context)(transcript, rules, texts)
        pending = [doc for doc in docs if doc not in read]
        redeliveries = int(previous.get("redeliveries", 0)) + (1 if previous and pending else 0)
        _write_marker(marker, pending, offset, redeliveries)
        return _render(texts, pending, rules)
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def _write_marker(marker: Path, delivered: list, offset: int, redeliveries: int) -> None:
    staged = marker.with_name(f"{marker.name}.{os.getpid()}.tmp")
    staged.write_text(json.dumps({"delivered": delivered, "transcript_bytes": offset,
                                  "redeliveries": redeliveries}), encoding="utf-8")
    os.replace(staged, marker)


def _compacted_before(transcript: Path) -> bool:
    """Whether the transcript holds any compaction boundary."""

    from support.native_doc_transcript import NativeDocTranscript
    native = NativeDocTranscript.compacted(transcript)
    if native is not None:
        return native

    if not _size(transcript):
        return False
    with transcript.open("rb") as handle:
        for raw in handle:
            if any(mark in raw for mark in _COMPACTION_MARKS):
                try:
                    if is_compaction(json.loads(raw)):
                        return True
                except ValueError:
                    continue
    return False


def _marker_state(marker: Path) -> dict:
    """The last delivery's record; {} when absent or unreadable (the old marker shape too)."""

    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _size(transcript: Path) -> int:
    """File size, or 0 for no transcript (an empty path is `.`, a directory)."""

    try:
        return transcript.stat().st_size if transcript.is_file() else 0
    except OSError:
        return 0


def _aligned_size(transcript: Path, fallback: int = 0) -> int:
    """The size up to the last complete line, so a row still being written is scanned later."""

    from support.native_doc_transcript import NativeDocTranscript
    native = NativeDocTranscript.aligned(transcript, fallback)
    if native is not None:
        return native

    size = _size(transcript)
    if not size:
        return 0
    try:
        with transcript.open("rb") as handle:
            handle.seek(max(0, size - 1))
            if handle.read(1) == b"\n":
                return size
            start = max(0, size - 65536)
            handle.seek(start)
            tail = handle.read(size - start)
    except OSError:
        return size
    newline = tail.rfind(b"\n")
    if newline >= 0:
        return start + newline + 1
    return fallback if 0 <= fallback <= start else 0


def _due_after_compaction(state: dict, transcript: Path, limit: int = MAX_REDELIVERIES) -> bool:
    """Whether a compaction landed after the last delivery, so its docs may be gone.

    Compaction summarises tool results away, which is how a delivered or read
    doc leaves the context while its hash is unchanged. Only the transcript
    appended since the marker is scanned. A marker without a recorded size (the
    old shape), a replaced transcript or an exhausted redelivery budget keeps
    the once-per-run behaviour.
    """

    from support.native_doc_transcript import NativeDocTranscript
    native = NativeDocTranscript.due(state, transcript, limit)
    if native is not None:
        return native

    offset = state.get("transcript_bytes")
    if type(offset) is not int or int(state.get("redeliveries", 0)) >= limit:
        return False
    size = _size(transcript)
    if size == offset:
        return False
    if size < offset:
        offset = 0  # rewritten or replaced: scan it whole rather than skip its start
    with transcript.open("rb") as handle:
        handle.seek(offset)
        for raw in handle:
            if not raw.endswith(b"\n") or not any(mark in raw for mark in _COMPACTION_MARKS):
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if is_compaction(row):
                return True
    return False


def is_compaction(row: object) -> bool:
    """Whether a transcript row is a compaction boundary (Claude, Codex or agy)."""

    if not isinstance(row, dict):
        return False
    if row.get("type") == "compacted" or (
            row.get("type") == "system" and row.get("subtype") == "compact_boundary"):
        return True
    # agy writes the summary that replaces the history as a CHECKPOINT step.
    return row.get("type") == "CHECKPOINT" and str(row.get("content") or "").startswith(
        "# Resuming from a compaction")


def _session_run(payload: dict, evidence_for) -> Path | None:
    for edited in edited_paths(payload):
        for project in (edited, *edited.parents):
            if (project_state_dir_target(project) / "run-registry.json").is_file():
                evidence = evidence_for(project)
                if evidence is not None:
                    return evidence
                break
    return None


def _read_in_context(transcript: Path, rules: Path, texts: dict[str, str]) -> set[str]:
    """Docs whose full, current text a tool result put into the live context.

    Counting a tool call that merely named a doc credited searches, failed and
    partial reads; counting only calls since the run started re-delivered docs
    read just before `start` that were still in context. A doc counts when
    successful calls naming it returned exact, contiguous portions of the
    doc's current text that together cover it after the last compaction.
    Extra or reordered rules cannot prove a read of this version. File times
    are no guide: a fresh checkout restamps every unchanged doc.
    """

    if not texts or not transcript.is_file():
        return set()
    texts = {doc: [line.strip() for line in text.splitlines() if line.strip()]
             for doc, text in texts.items()}
    texts = {doc: lines for doc, lines in texts.items() if lines}
    calls: dict[str, list[str]] = {}
    covered: dict[str, set[int]] = {}
    with transcript.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not any(kind in line for kind in (*_TOOL_EVENT, '"compact_boundary"', '"compacted"')):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if row.get("type") == "compacted" or (
                row.get("type") == "system" and row.get("subtype") == "compact_boundary"
            ):
                calls.clear()
                covered.clear()
                continue
            if not any(doc in line for doc in texts) and not any(call in line for call in calls):
                continue
            for call_id, named, output, failed in _tool_events(row, texts):
                if output is None:
                    calls[call_id] = named
                    continue
                named = calls.pop(call_id, named)
                if not failed:
                    unchanged = {doc for doc in named if _modified(rules / doc) <= _stamp(row)}
                    for doc, span in _read_spans(named, texts, output, unchanged).items():
                        covered.setdefault(doc, set()).update(span)
    return {doc for doc, span in covered.items() if len(span) == len(texts[doc])}


def _read_spans(named: list[str], texts: dict[str, list[str]], output: str,
                unchanged: set[str] = frozenset()) -> dict[str, range]:
    """Credit only exact current text; ambiguous slices remain unconfirmed.

    `unchanged` names docs whose file was not modified after this output.
    """

    if output.startswith(("Chunk ID:", "Wall time:", "Process exited")):
        if re.search(r"Process exited with code [1-9]\d*", output):
            return {}
        output = re.split(r"\n(?:Final output|Output):\n", output, maxsplit=1)[-1]
    lines = [re.sub(r"^\s*\d+(?:\t|→)", "", line).strip() for line in output.splitlines()]
    lines = [line for line in lines if line]
    if not named or not lines:
        return {}
    # A compound read (`sed ...; cat doc`) prints other text around the doc.
    # The whole current doc, unbroken, inside that output is still a full
    # read -- unless the file changed since: an old version whose trailing
    # rule was later deleted contains the current text unbroken too, and
    # the text around it cannot tell that rule from another command's output.
    whole = {doc: range(len(texts[doc])) for doc in named
             if doc in unchanged and _contains_run(lines, texts[doc])}
    if whole:
        return whole
    if len(named) > 1:
        if lines == [line for doc in named for line in texts[doc]]:
            return {doc: range(len(texts[doc])) for doc in named}
        return {}
    doc = named[0]
    starts = _matching_starts(texts[doc], lines)
    first = next(starts, None)
    if first is None or next(starts, None) is not None:
        return {}
    return {doc: range(first, first + len(lines))}


def _modified(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return float("inf")


def _stamp(row: dict) -> float:
    """The row's timestamp; a row without one proves no ordering."""

    try:
        raw = row.get("timestamp") or row.get("created_at")
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("-inf")


def _contains_run(lines: list[str], doc: list[str]) -> bool:
    """Whether `doc` occurs in `lines` as one contiguous, exact block."""

    return next(_matching_starts(lines, doc), None) is not None


def _matching_starts(lines: list[str], fragment: list[str]):
    """Exact, overlapping spans; bound repeated-prefix work without a cache.

    Normal reads use native first-line search and list comparison.
    After eight candidates, a KMP failure table bounds the remaining
    comparisons to linear work. Callers stop at one match or proven ambiguity.
    """
    size = len(fragment)
    if not size or size > len(lines):
        return
    start = 0
    limit = len(lines) - size + 1
    for _ in range(8):
        try:
            start = lines.index(fragment[0], start, limit)
        except ValueError:
            return
        if lines[start:start + size] == fragment:
            yield start
        start += 1

    failure = [0] * size
    matched = 0
    for index in range(1, size):
        while matched and fragment[index] != fragment[matched]:
            matched = failure[matched - 1]
        if fragment[index] == fragment[matched]:
            matched += 1
        failure[index] = matched

    matched = 0
    for index in range(start, len(lines)):
        while matched and lines[index] != fragment[matched]:
            matched = failure[matched - 1]
        if lines[index] == fragment[matched]:
            matched += 1
        if matched == size:
            yield index - size + 1
            matched = failure[matched - 1]


def _tool_events(row: dict, texts: dict[str, list[str]]):
    """(call id, docs named, output or None for a call, failed) in either runtime's shape."""

    def named(value) -> list[str]:
        text = json.dumps(value, ensure_ascii=False)
        return sorted((doc for doc in texts if doc in text), key=text.index)

    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    if item.get("type") == "CommandExecution":
        # Codex reports a finished shell command with its output in one event.
        failed = item.get("status") != "completed" or item.get("exit_code") not in (None, 0)
        yield str(item.get("id")), named(item.get("command")), str(item.get("stdout") or ""), failed
        return
    kind = payload.get("type", "")
    if kind in ("function_call", "custom_tool_call"):
        yield str(payload.get("call_id")), named(payload.get("arguments") or payload.get("input")), None, False
    elif kind in ("function_call_output", "custom_tool_call_output"):
        yield str(payload.get("call_id")), [], _result_text(payload.get("output")), False
    content = (row.get("message") or {}).get("content") if isinstance(row.get("message"), dict) else None
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            yield str(block.get("id")), named(block.get("input")), None, False
        elif block.get("type") == "tool_result":
            yield (str(block.get("tool_use_id")), [], _result_text(block.get("content")),
                   bool(block.get("is_error")))


def _result_text(content) -> str:
    if isinstance(content, str):
        if content.startswith("Script running"):
            return ""
        if content.startswith("Script completed\n"):
            header = re.match(r"Script completed\nWall time [\d.]+ seconds\nOutput:\n", content)
            if header is None:
                return ""
            content = content[header.end():]
        try:
            decoded = json.loads(content)
        except ValueError:
            # functions.exec's text() items can be adjacent JSON values rather
            # than one array. Require the entire stream; never credit a valid
            # prefix of a truncated or otherwise malformed result.
            remaining, items = content.lstrip(), []
            if not remaining.startswith(("{", "[")):
                return content
            decoder = json.JSONDecoder()
            try:
                while remaining:
                    item, end = decoder.raw_decode(remaining)
                    if not isinstance(item, (dict, list)):
                        return ""
                    items.append(item)
                    remaining = remaining[end:].lstrip()
            except ValueError:
                return ""
            decoded = items
        if not isinstance(decoded, (dict, list)):
            return content
        content = decoded
    if isinstance(content, dict):
        if (content.get("exit_code") not in (None, 0) or content.get("is_error")
                or content.get("isError")
                or content.get("status") in ("rejected", "failed", "cancelled", "pending", "running", "in_progress")
                or ("session_id" in content and content.get("exit_code") is None)):
            return ""
        for key in ("stdout", "output", "text", "content", "result", "value"):
            if key in content:
                return _result_text(content[key])
        return ""
    if isinstance(content, list):
        return "\n".join(_result_text(part) for part in content)
    return ""


def _render(texts: dict[str, str], pending: list[str], rules: Path | None = None) -> str:
    if not pending:
        return ""
    inline, listed, used = [], [], 0
    for doc in pending:
        if doc not in texts:
            continue
        text = _FRONTMATTER.sub("", texts[doc]).strip()
        size = len(text.encode("utf-8"))
        if size <= MAX_INLINE_DOC_BYTES and used + size <= MAX_DELIVERY_BYTES:
            inline.append(f"=== {doc} ===\n{text}")
            used += size
        else:
            listed.append(f"{rules / doc if rules else doc} ({size} bytes)")
    if not inline and not listed:
        return ""
    parts = ["Moru required docs not yet read in this run, delivered once before its first edit. "
             "Apply them to this change; this does not block the edit."]
    if listed:
        parts.append("Read each of these whole, with no line range, before continuing "
                     "(too large to include; a ranged read does not count as read): " + "; ".join(listed))
    parts.extend(inline)
    return "\n\n".join(parts)
