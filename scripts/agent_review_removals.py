"""Name what a large net deletion removed, and whether the diff kept it elsewhere.

Line counts alone cannot tell an extraction from a loss: a guide moved into its
owner and a runbook overwritten by a stale one-line copy both measure as
"net -99". The review already has the diff for the reviewed scope, so the
removed lines of each net-deletion path are compared with the lines the same
diff added to other paths. That comparison is review context, never a gate: it
changes no pass/fail decision and asks for no prose.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
import re
from typing import Any

from agent_command_runtime import run_command as review_runtime_command
from support.native_probe_transport import NativeProbe

CommandRunner = Callable[[list[str], Path], dict[str, Any]]

PER_FILE_BYTE_LIMIT = 200_000
TOTAL_BYTE_LIMIT = 1_000_000
NOTICE_BYTE_LIMIT = 1_500
SAMPLE_CHARS = 100
HEADING_SAMPLE_LIMIT = 5
FALLBACK_SAMPLE_LIMIT = 3
# Lines shorter than this ("}", "```", "- ") match anywhere, so they neither
# prove a move nor disprove one.
MEANINGFUL_LINE_CHARS = 4
SIGNATURE_PREFIXES = ("def ", "async def ", "class ", "function ")
SENSITIVE_SAMPLE = re.compile(
    r"(?i)(?:password|passphrase|secret|token|credential|authorization|bearer|"
    r"api[_-]?key|private[_-]?key|database[_-]?url|connection[_-]?string|"
    r"-----BEGIN|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]+|sk-[A-Za-z0-9]+|"
    r"://[^/@\s]+:[^/@\s]+@|[A-Za-z0-9+/=_-]{24,})"
)


def classify_net_deletions(
    findings: list[dict[str, Any]],
    *,
    project: Path,
    run_command: CommandRunner,
    review_paths: list[str] | None,
    review_commits: tuple[str, str] | None,
    path_metadata: dict[str, dict[str, Any]],
) -> None:
    """Add `classification` and sample lines to each finding in place."""

    if not findings:
        return
    revisions = list(review_commits) if review_commits is not None else ["HEAD"]
    pathspec = [path.strip() for path in (review_paths or []) if path.strip()]
    untracked = path_metadata if review_commits is None else {}
    native = None
    if run_command is review_runtime_command:
        native = _native_removal_analysis(findings, {"revisions": revisions, "paths": pathspec}, project, untracked)
    if native is None:
        diff = run_command(
            ["git", "diff", "-U0", "--no-color", "--no-ext-diff", "--diff-filter=ACDMRTUXB",
             *revisions, "--", *pathspec],
            project,
        )
        if diff.get("returncode") != 0:
            for item in findings:
                item["classification"] = "unavailable"
            return
        text = str(diff.get("stdout") or "")
        native = _native_removal_analysis(findings, {"diff": text}, project, untracked)
    if native is not None:
        for item, result in zip(findings, native):
            item.update(result)
        return
    budget = _Budget()
    removed, added = parse_diff_lines(text, budget)
    _add_untracked_lines(added, project, untracked, budget)
    if budget.truncated:
        for item in findings:
            item["classification"] = "unavailable"
        return
    index: dict[str, Counter[str]] = {}
    for path, lines in added.items():
        for line in lines:
            index.setdefault(line, Counter())[path] += 1
    for item in findings:
        item.update(classify_removal(item["path"], removed.get(item["path"]), index))


def _native_removal_analysis(
    findings: list[dict[str, Any]], patch: dict[str, Any], project: Path, path_metadata: dict[str, dict[str, Any]],
) -> list[dict[str, Any]] | None:
    if not NativeProbe.available():
        return None
    paths = [item["path"] for item in findings]
    native = NativeProbe.request("--completion-probe", "structure-removal-analysis", {
        **patch, "project": str(project), "findings": paths,
        "untracked": [path for path in sorted(path_metadata)
                      if (path_metadata[path] or {}).get("untracked") is True],
        "per_file": PER_FILE_BYTE_LIMIT, "total": TOTAL_BYTE_LIMIT,
        "summary": {"headings": HEADING_SAMPLE_LIMIT, "fallback": FALLBACK_SAMPLE_LIMIT},
    })
    if native is None:
        return None
    if set(native) == {"truncated"} and native["truncated"] is True:
        return [{"classification": "unavailable"} for _ in findings]
    rows = native.get("findings")
    if not isinstance(rows, list) or len(rows) != len(paths):
        return None
    results = []
    for path, row in zip(paths, rows):
        result = _native_removal_result(path, row)
        if result is None:
            return None
        results.append(result)
    return results


def _native_removal_result(path: str, row: Any) -> dict[str, Any] | None:
    if row == {"classification": "unavailable"}:
        return row
    if not isinstance(row, dict) or set(row) != {
        "classification", "line_count", "unmatched_count", "moved_to", "samples",
    }:
        return None
    classification, count, unmatched = row["classification"], row["line_count"], row["unmatched_count"]
    destinations, samples = row["moved_to"], row["samples"]
    if (classification not in ("moved", "removed")
            or type(count) is not int or count <= 0
            or type(unmatched) is not int or not 0 <= unmatched <= count
            or not isinstance(destinations, list) or len(destinations) > 3
            or not all(isinstance(target, str) and target != path for target in destinations)
            or not isinstance(samples, list) or len(samples) > max(HEADING_SAMPLE_LIMIT, FALLBACK_SAMPLE_LIMIT)
            or not all(isinstance(line, str) for line in samples)
            or (classification == "moved" and (unmatched or samples))):
        return None
    result = {
        "classification": classification,
        "moved_ratio": round((count - unmatched) / count, 2),
    }
    if classification == "removed":
        result["unmatched_lines"] = unmatched
    result["moved_to"] = destinations
    if classification == "removed":
        result["sample_lines"] = [_redact_sample(line) for line in samples]
    return result


class _Budget:
    def __init__(self) -> None:
        self.total = 0
        self.per_file: Counter[str] = Counter()
        self.truncated = False

    def take(self, path: str, size: int) -> bool:
        if self.total + size > TOTAL_BYTE_LIMIT or self.per_file[path] + size > PER_FILE_BYTE_LIMIT:
            self.truncated = True
            return False
        self.total += size
        self.per_file[path] += size
        return True


def parse_diff_lines(
    text: str, budget: _Budget
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return removed and added lines per destination path of a `-U0` diff."""

    removed: dict[str, list[str]] = {}
    added: dict[str, list[str]] = {}
    source = destination = None
    in_header = False
    for line in text.splitlines():
        if line.startswith("diff --git "):
            source = destination = None
            in_header = True
            continue
        if in_header:
            if line.startswith("--- "):
                source = _header_path(line[4:], "a/")
            elif line.startswith("+++ "):
                destination = _header_path(line[4:], "b/")
                in_header = False
            continue
        path = destination or source
        if path is None or line[:1] not in {"+", "-"}:
            continue
        if not budget.take(path, len(line)):
            continue
        (added if line[0] == "+" else removed).setdefault(path, []).append(line[1:])
    return removed, added


def _header_path(value: str, prefix: str) -> str | None:
    value = value.rstrip("\t")
    if value == "/dev/null":
        return None
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
        value = value.encode("latin-1", "ignore").decode("utf-8", "replace")
    return value[len(prefix):] if value.startswith(prefix) else value


def _add_untracked_lines(
    added: dict[str, list[str]],
    project: Path,
    path_metadata: dict[str, dict[str, Any]],
    budget: _Budget,
) -> None:
    """Untracked files are absent from `git diff HEAD` but are still where content moves."""

    for name in sorted(path_metadata):
        if (path_metadata[name] or {}).get("untracked") is not True:
            continue
        candidate = project / name
        if candidate.is_symlink():
            budget.truncated = True
            continue
        try:
            with candidate.open("rb") as handle:
                data = handle.read(PER_FILE_BYTE_LIMIT + 1)
        except OSError:
            budget.truncated = True
            continue
        if len(data) > PER_FILE_BYTE_LIMIT:
            budget.truncated = True
            continue
        if not budget.take(name, len(data)):
            continue
        added.setdefault(name, []).extend(data.decode("utf-8", "replace").splitlines())


def classify_removal(
    path: str, removed_lines: list[str] | None, index: dict[str, Counter[str]]
) -> dict[str, Any]:
    if not removed_lines:
        return {"classification": "unavailable"}
    destinations: Counter[str] = Counter()
    unmatched: list[str] = []
    for line in removed_lines:
        available = index.get(line, Counter())
        destination = next(
            (name for name in sorted(available) if name != path and available[name] > 0),
            None,
        )
        if destination is None:
            unmatched.append(line)
            continue
        available[destination] -= 1
        destinations[destination] += 1
    return _describe_removal(removed_lines, unmatched, [name for name, _count in destinations.most_common(3)])


def _describe_removal(removed_lines: list[str], unmatched: list[str], moved_to: list[str]) -> dict[str, Any]:
    if not removed_lines:
        return {"classification": "unavailable"}
    meaningful = any(len(line.strip()) >= MEANINGFUL_LINE_CHARS for line in removed_lines)
    matched = len(removed_lines) - len(unmatched)
    ratio = matched / len(removed_lines)
    if meaningful and not unmatched:
        return {
            "classification": "moved",
            "moved_ratio": round(ratio, 2),
            "moved_to": moved_to,
        }
    return {
        "classification": "removed",
        "moved_ratio": round(ratio, 2),
        "unmatched_lines": len(unmatched),
        "moved_to": moved_to,
        "sample_lines": removal_samples(unmatched or [line for line in removed_lines if line.strip()]),
    }


def removal_samples(lines: list[str]) -> list[str]:
    """Headings and signatures say what vanished; otherwise show where it began."""

    stripped = [line.strip() for line in lines if line.strip()]
    headings = [line for line in stripped if _heading_like(line)]
    chosen = headings[:HEADING_SAMPLE_LIMIT] if headings else stripped[:FALLBACK_SAMPLE_LIMIT]
    return [_redact_sample(line) for line in chosen]


def _redact_sample(line: str) -> str:
    return "[sensitive-looking content omitted]" if SENSITIVE_SAMPLE.search(line) else line[:SAMPLE_CHARS]


def _heading_like(line: str) -> bool:
    return line.startswith("#") or line.endswith(":") or line.startswith(SIGNATURE_PREFIXES)


def removal_notice(findings: list[dict[str, Any]]) -> list[str]:
    """The compact review-output lines for measured net removals."""

    if not findings:
        return []
    fields = ("path", "net", "classification", "moved_to", "unmatched_lines", "sample_lines", "deletions", "additions")
    native = NativeProbe.request("--completion-probe", "structure-report", {
        "mode": "removal", "char_limit": NOTICE_BYTE_LIMIT,
        "findings": [{key: item[key] for key in fields if key in item} for item in findings],
    })
    lines = native.get("lines") if native is not None else None
    if isinstance(lines, list) and lines and all(isinstance(line, str) for line in lines):
        return lines
    return _python_removal_notice(findings)


def _python_removal_notice(findings: list[dict[str, Any]]) -> list[str]:
    details = [
        "measured net removals (review context, not a failure; compared with lines "
        "this diff added elsewhere):"
    ]
    used = len(details[0])
    for position, item in enumerate(findings):
        entry = _notice_entry(item)
        size = sum(len(line) for line in entry)
        if used + size > NOTICE_BYTE_LIMIT:
            details.append(
                f"  ... (+{len(findings) - position} more; all paths in structure_review.net_deletions)"
            )
            break
        details.extend(entry)
        used += size
    return details


def _notice_entry(item: dict[str, Any]) -> list[str]:
    head = f"  {item['path']}: net -{item['net']}"
    classification = item.get("classification")
    if classification == "moved":
        return [f"{head}, moved to {', '.join(item.get('moved_to') or [])}"]
    if classification == "removed":
        destinations = item.get("moved_to") or []
        explanation = (
            f"{item.get('unmatched_lines', 0)} unmatched lines; other lines match at {', '.join(destinations)}"
            if destinations else "not found elsewhere in this diff"
        )
        return [
            f"{head}, content removed ({explanation})",
            *(f"    removed: {line}" for line in item.get("sample_lines") or []),
        ]
    return [f"{head} (-{item['deletions']} +{item['additions']}); review the diff for what was removed"]
