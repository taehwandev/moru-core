#!/usr/bin/env python3
"""Report Moru workflow overhead across local Claude Code sessions.

Owner: the before/after overhead measurement for maintenance audit H10.
Allowed imports: the standard library and claude_transcript_overhead.
Forbidden: Moru state, gate records, provider calls and writes other than the
requested --out/--md files. Callers/tests: docs/maintenance-audit.md,
tests/test_moru_overhead_report.py.

Usage:
  python3 -I scripts/moru_overhead_report.py [--days 30] [--since ISO] [--until ISO]
      [--projects-dir ~/.claude/projects] [--timings ~/.moru/timings.jsonl]
      [--moru-root <checkout>] [--alias-root <old checkout>] [--exclude-session ID]
      [--include-subagents] [--out report.json] [--md report.md]

It reads only local transcripts and timing records and prints aggregates. Rerun
with the same window flags after a change to compare before and after.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude_transcript_overhead import measure_session, new_shared_counters, parse_timestamp  # noqa: E402

NUMERIC = (
    "assistant_turns", "user_prompts", "tool_calls", "lifecycle_total", "policy_notes",
    "hook_denials", "moru_hook_denials", "stop_hook_blocks", "guidance_reads", "guidance_bash_reads",
    "tok_total", "tok_output", "tok_cache_read", "tok_cache_create",
    "moru_injected_tokens_est", "moru_injected_events",
)
MARKDOWN_ROWS = (
    ("assistant turns", "assistant_turns"), ("tool calls", "tool_calls"),
    ("lifecycle (launcher) Bash calls", "lifecycle_total"), ("policy notes", "policy_notes"),
    ("hook denials (all)", "hook_denials"), ("Moru hook denials", "moru_hook_denials"),
    ("guidance doc Reads", "guidance_reads"), ("guidance doc Bash reads", "guidance_bash_reads"),
    ("total tokens", "tok_total"), ("output tokens", "tok_output"),
    ("Moru-injected tokens (chars/4)", "moru_injected_tokens_est"),
)


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 2)


def summarize(values: list[float]) -> dict[str, Any]:
    values = [value for value in values if value is not None]
    if not values:
        return {"n": 0}
    return {"n": len(values), "median": percentile(values, 0.5), "p90": percentile(values, 0.9),
            "mean": round(statistics.mean(values), 2), "sum": round(sum(values), 2)}


def _share(numerator: float, denominator: float) -> float:
    return round(100 * numerator / (denominator or 1), 2)


def aggregate(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"sessions": len(sessions)}
    result.update({key: summarize([session[key] for session in sessions]) for key in NUMERIC})
    tools: collections.Counter = collections.Counter()
    lifecycle: collections.Counter = collections.Counter()
    for session in sessions:
        tools.update(session["tools"])
        lifecycle.update(session["lifecycle_calls"])
    result["tool_calls_by_name_total"] = dict(tools.most_common(25))
    result["lifecycle_calls_by_subcommand_total"] = dict(lifecycle.most_common())
    result["sessions_with_lifecycle_calls"] = sum(1 for session in sessions if session["lifecycle_total"])
    if sessions:
        def total(key: str) -> float:
            return sum(session[key] for session in sessions)

        result["lifecycle_share_of_tool_calls_pct"] = _share(total("lifecycle_total"), total("tool_calls"))
        result["guidance_read_share_of_reads_pct"] = _share(total("guidance_reads"), tools.get("Read", 0))
        result["injected_tokens_vs_new_input_pct"] = _share(
            total("moru_injected_tokens_est"), total("tok_input") + total("tok_cache_create"))
    return result


def read_timings(path: str) -> dict[str, Any]:
    per_hook: dict[str, list[float]] = collections.defaultdict(list)
    status: collections.Counter = collections.Counter()
    records = 0
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                    timings = record.get("timings") or {}
                    value = timings.get("hook_total")
                    if value is None and timings:
                        value = sum(v for v in timings.values() if isinstance(v, (int, float)))
                    per_hook[str(record.get("hook"))].append(float(value))
                except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
                    continue
                status[f"{record.get('hook')}:{record.get('status')}"] += 1
                records += 1
    return {"records": records, "per_hook_ms": {k: summarize(v) for k, v in per_hook.items()},
            "status": dict(status)}


def collect_sessions(args: argparse.Namespace, roots: list[str], since: dt.datetime, until: dt.datetime,
                     shared: dict[str, Any]) -> list[dict[str, Any]]:
    files = glob.glob(os.path.join(args.projects_dir, "*", "*.jsonl"))
    if args.include_subagents:
        files += glob.glob(os.path.join(args.projects_dir, "*", "*", "subagents", "*.jsonl"))
    sessions = []
    for path in files:
        try:
            modified = dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)
        except OSError:
            continue
        if modified < since or any(skip in os.path.basename(path) for skip in args.exclude_session):
            continue
        session = measure_session(path, roots, shared)
        if session["assistant_turns"] < args.min_turns:
            continue
        first, last = session["first_ts"], session["last_ts"]
        if first and (first > until or (last and last < since)):
            continue
        sessions.append(session)
    return sessions


def build_report(args: argparse.Namespace, now: dt.datetime) -> dict[str, Any]:
    roots = [root.rstrip("/") for root in [args.moru_root, *args.alias_root] if root]
    until = parse_timestamp(args.until) if args.until else now
    since = parse_timestamp(args.since) if args.since else until - dt.timedelta(days=args.days)
    if until is None or since is None:
        raise SystemExit("--since/--until must be ISO timestamps")
    shared = new_shared_counters()
    sessions = collect_sessions(args, roots, since, until, shared)
    return {
        "generated_at": now.isoformat(),
        "window": {"since": since.isoformat(), "until": until.isoformat()},
        "sources": {"transcript_files_in_window": len(sessions), "include_subagents": args.include_subagents},
        "notes": "tokens sum input, cache read, cache creation and output per unique assistant message; "
                 "moru_injected_tokens_est is chars/4 of Moru hook context, plain-text hook stdout and "
                 "Moru PreToolUse denial reasons, an approximation rather than a tokenizer count.",
        "all": aggregate(sessions),
        "moru_core": aggregate([session for session in sessions if session["moru_core"]]),
        "other_projects": aggregate([session for session in sessions if not session["moru_core"]]),
        "moru_hook_latency_ms_from_transcripts": {
            key: summarize(values) for key, values in sorted(shared["hook_latency"].items())},
        "timings_jsonl": read_timings(args.timings),
        "top_policy_notes": [{"count": c, "message": m} for m, c in shared["notes"].most_common(5)],
        "top_hook_denials": [{"count": c, "message": m} for m, c in shared["denials"].most_common(5)],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Moru workflow overhead", "", f"Generated: {report['generated_at']}  ",
             f"Window: {report['window']['since']} .. {report['window']['until']}", "",
             "Sessions: all={}, moru-core={}, other={}".format(
                 report["all"]["sessions"], report["moru_core"]["sessions"], report["other_projects"]["sessions"]),
             ""]
    for group in ("all", "moru_core", "other_projects"):
        data = report[group]
        lines += [f"## {group} (median / p90 per session)", "", "| metric | median | p90 | n |", "|---|---|---|---|"]
        for label, key in MARKDOWN_ROWS:
            value = data.get(key) or {}
            lines.append(f"| {label} | {value.get('median')} | {value.get('p90')} | {value.get('n', 0)} |")
        lines += ["", f"- lifecycle share of tool calls: {data.get('lifecycle_share_of_tool_calls_pct')}%",
                  f"- injected tokens vs new input: {data.get('injected_tokens_vs_new_input_pct')}%",
                  f"- lifecycle subcommands: {json.dumps(data.get('lifecycle_calls_by_subcommand_total'))}", ""]
    lines += ["## Moru hook latency from transcripts (ms)", "", "| hook | n | median | p90 |", "|---|---|---|---|"]
    for key, value in report["moru_hook_latency_ms_from_transcripts"].items():
        lines.append(f"| {key} | {value.get('n')} | {value.get('median')} | {value.get('p90')} |")
    for title, key in (("Top policy notes", "top_policy_notes"), ("Top hook denials", "top_hook_denials")):
        lines += ["", f"## {title}", ""]
        lines += [f"{i}. ({item['count']}) {item['message']}" for i, item in enumerate(report[key], 1)]
    return "\n".join(lines) + "\n"


def default_moru_root() -> Path:
    """This checkout, or its main checkout when it is a sibling `<name>-worktrees` worktree."""

    checkout = Path(__file__).resolve().parents[1]
    container = checkout.parent
    if container.name.endswith("-worktrees"):
        return container.with_name(container.name[: -len("-worktrees")])
    return checkout


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--projects-dir", default=str(home / ".claude" / "projects"))
    parser.add_argument("--timings", default=str(home / ".moru" / "timings.jsonl"))
    parser.add_argument("--moru-root", default=str(default_moru_root()))
    parser.add_argument("--alias-root", action="append", default=[],
                        help="another checkout path counted as moru-core, such as a pre-rename path")
    parser.add_argument("--exclude-session", action="append", default=[])
    parser.add_argument("--include-subagents", action="store_true")
    parser.add_argument("--min-turns", type=int, default=1)
    parser.add_argument("--out")
    parser.add_argument("--md")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args, dt.datetime.now(dt.timezone.utc))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.md:
        Path(args.md).write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
