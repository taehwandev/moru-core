#!/usr/bin/env python3
"""Offline grader for normalized agent behavior traces and filesystem artifacts.
Grades supplied evidence only; synthetic fixture results are not live-provider scores.
owner: offline behavior grading; allowed imports: stdlib and verified launcher selection;
forbidden imports: provider SDKs, network, lifecycle mutators;
callers/tests: CLI and tests/test_agent_behavior_eval.py; verification: unittest."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Iterable, Sequence, TextIO

SCHEMA_VERSION = 1
SUPPORTED_PROVIDERS = ("codex", "claude", "agy")
VALID_STATUSES = frozenset(("ok", "blocked", "needs_inspection"))
MAX_ARTIFACT_BYTES = 65536
MAX_JSON_BYTES = 4 * 1024 * 1024
_CASE_KEYS = frozenset(("id", "expected_status", "max_prompts", "required_events", "forbidden_events", "ordered_pairs", "artifacts"))


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_str_id(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip()) and "\x00" not in v


def _validate_envelope(doc: Any, list_key: str) -> list[Any]:
    if not isinstance(doc, dict) or set(doc.keys()) != {"schema_version", list_key}:
        raise ValueError(f"malformed {list_key} document schema")
    if not _is_int(doc["schema_version"]) or doc["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported {list_key} schema_version")
    items = doc[list_key]
    if not isinstance(items, list) or not items:
        raise ValueError(f"{list_key} must be a non-empty list")
    return items


def _validate_providers(providers: Iterable[str]) -> tuple[str, ...]:
    if isinstance(providers, (str, bytes)) or not isinstance(providers, Iterable):
        raise ValueError("providers must be an iterable of provider names")
    out: list[str] = []
    for item in providers:
        if not isinstance(item, str) or item not in SUPPORTED_PROVIDERS or item in out:
            raise ValueError(f"invalid or duplicate provider: {item!r}")
        out.append(item)
    if not out:
        raise ValueError("providers must not be empty")
    return tuple(out)


def _str_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(_is_str_id(v) for v in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return list(value)


def _validate_cases(cases_doc: Any) -> list[dict[str, Any]]:
    cases, seen_ids = [], set()
    for raw in _validate_envelope(cases_doc, "cases"):
        if not isinstance(raw, dict) or not set(raw.keys()).issubset(_CASE_KEYS):
            raise ValueError("malformed case entry")
        if not {"id", "expected_status", "max_prompts"}.issubset(raw.keys()):
            raise ValueError("case missing required keys")
        cid, status, max_prompts = raw["id"], raw["expected_status"], raw["max_prompts"]
        if not _is_str_id(cid) or "/" in cid or "\\" in cid or cid in (".", "..") or cid in seen_ids:
            raise ValueError(f"invalid or duplicate case id: {cid!r}")
        seen_ids.add(cid)
        if not isinstance(status, str) or status not in VALID_STATUSES or not _is_int(max_prompts) or max_prompts < 0:
            raise ValueError("invalid expected_status or max_prompts")
        raw_pairs, artifacts = raw.get("ordered_pairs", []), raw.get("artifacts", {})
        if not isinstance(raw_pairs, list) or not all(isinstance(p, (list, tuple)) and len(p) == 2 and _is_str_id(p[0]) and _is_str_id(p[1]) for p in raw_pairs):
            raise ValueError("invalid ordered_pairs")
        if not isinstance(artifacts, dict) or not all(isinstance(k, str) and bool(k) and "\x00" not in k and isinstance(v, str) for k, v in artifacts.items()):
            raise ValueError("artifacts must map relative paths to literal strings")
        cases.append({
            "id": cid, "expected_status": status, "max_prompts": max_prompts,
            "required_events": _str_list(raw.get("required_events", []), "required_events"),
            "forbidden_events": _str_list(raw.get("forbidden_events", []), "forbidden_events"),
            "ordered_pairs": [(p[0], p[1]) for p in raw_pairs], "artifacts": dict(artifacts),
        })
    return cases


def _validate_traces(traces_doc: Any, case_ids: set[str]) -> dict[tuple[str, str], list[dict[str, str]]]:
    runs: dict[tuple[str, str], list[dict[str, str]]] = {}
    for raw in _validate_envelope(traces_doc, "runs"):
        if not isinstance(raw, dict) or set(raw.keys()) != {"provider", "case_id", "events"}:
            raise ValueError("malformed run entry")
        provider, cid, raw_events = raw["provider"], raw["case_id"], raw["events"]
        if not isinstance(provider, str) or provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"unknown provider: {provider!r}")
        if not isinstance(cid, str) or cid not in case_ids or (provider, cid) in runs:
            raise ValueError(f"unknown or duplicate run: {provider}/{cid!r}")
        if not isinstance(raw_events, list):
            raise ValueError("events must be a list")
        events: list[dict[str, str]] = []
        for ev in raw_events:
            if not isinstance(ev, dict) or not _is_str_id(ev.get("kind")):
                raise ValueError("malformed event entry")
            kind, keys = ev["kind"], set(ev.keys())
            if kind == "final":
                if keys != {"kind", "status"} or not isinstance(ev["status"], str) or ev["status"] not in VALID_STATUSES:
                    raise ValueError("invalid final event")
                events.append({"kind": kind, "status": ev["status"]})
            elif keys != {"kind"}:
                raise ValueError("status is only valid on final events")
            else:
                events.append({"kind": kind})
        runs[(provider, cid)] = events
    return runs


def _check_artifact(base: Path, root: Path, provider: str, cid: str, rel_path: str, expected: str) -> str | None:
    has_drive = len(rel_path) >= 2 and rel_path[1] == ":" and rel_path[0].isalpha()
    parts = rel_path.split("/")
    if os.path.isabs(rel_path) or has_drive or "\\" in rel_path or any(p in ("", ".", "..") for p in parts):
        return f"artifact_path_escape:{rel_path}"
    cur, walk = base, (provider, cid, *parts)
    for idx, seg in enumerate(walk):
        cur = cur / seg
        try:
            st = os.lstat(cur)
        except (FileNotFoundError, NotADirectoryError):
            return f"artifact_missing:{rel_path}"
        except OSError:
            return f"artifact_unreadable:{rel_path}"
        if stat.S_ISLNK(st.st_mode):
            return f"artifact_symlink_escape:{rel_path}"
        expect_dir = idx < len(walk) - 1
        if (expect_dir and not stat.S_ISDIR(st.st_mode)) or (not expect_dir and not stat.S_ISREG(st.st_mode)):
            return f"artifact_missing:{rel_path}" if expect_dir else f"artifact_unreadable:{rel_path}"
    try:
        cur.resolve().relative_to(root)
    except (OSError, ValueError):
        return f"artifact_symlink_escape:{rel_path}"
    try:
        with os.fdopen(os.open(cur, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return f"artifact_unreadable:{rel_path}"
            raw = fh.read(MAX_ARTIFACT_BYTES + 1)
        if len(raw) > MAX_ARTIFACT_BYTES:
            return f"artifact_unreadable:{rel_path}"
        actual = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return f"artifact_unreadable:{rel_path}"
    return None if actual == expected else f"artifact_mismatch:{rel_path}"


def _grade_run(case: dict[str, Any], events: list[dict[str, str]] | None, base: Path, root: Path, provider: str) -> dict[str, Any]:
    cid = case["id"]
    if events is None:
        return {"provider": provider, "case_id": cid, "passed": False, "failures": ["missing_run"]}
    failures: list[str] = []
    finals = [ev for ev in events if ev["kind"] == "final"]
    if len(finals) != 1:
        failures.append(f"final_event_count:{len(finals)}")
    else:
        if finals[0]["status"] != case["expected_status"]:
            failures.append(f"final_status:{finals[0]['status']}!=expected:{case['expected_status']}")
        if events[-1]["kind"] != "final":
            failures.append("events_after_final")
    prompts = sum(1 for ev in events if ev["kind"] == "prompt_submitted")
    if prompts > case["max_prompts"]:
        failures.append(f"max_prompts_exceeded:{prompts}>{case['max_prompts']}")
    first_idx: dict[str, int] = {}
    counts: dict[str, int] = {}
    for idx, ev in enumerate(events):
        counts[ev["kind"]] = counts.get(ev["kind"], 0) + 1
        first_idx.setdefault(ev["kind"], idx)
    failures.extend(f"missing_required_event:{r}" for r in case["required_events"] if r not in first_idx)
    failures.extend(f"forbidden_event:{f}" for f in case["forbidden_events"] if f in first_idx)
    for a, b in case["ordered_pairs"]:
        if a not in first_idx or b not in first_idx or (a == b and counts[a] < 2):
            failures.append(f"ordered_pair_missing:{a}->{b}")
        elif a != b and first_idx[a] >= first_idx[b]:
            failures.append(f"ordered_pair_out_of_order:{a}->{b}")
    for rel_path, expected in case["artifacts"].items():
        err = _check_artifact(base, root, provider, cid, rel_path, expected)
        if err is not None:
            failures.append(err)
    return {"provider": provider, "case_id": cid, "passed": not failures, "failures": failures}


def evaluate(
    cases_doc: Any, traces_doc: Any, artifact_root: str | os.PathLike[str], providers: Iterable[str] = SUPPORTED_PROVIDERS
) -> dict[str, Any]:
    """Grade supplied offline traces and <artifact_root>/<provider>/<case_id>/ artifacts."""
    active, cases = _validate_providers(providers), _validate_cases(cases_doc)
    runs = _validate_traces(traces_doc, {c["id"] for c in cases})
    root_str = os.fspath(artifact_root) if isinstance(artifact_root, (str, os.PathLike)) else None
    if not isinstance(root_str, str) or not root_str or "\x00" in root_str:
        raise ValueError("invalid artifact_root")
    base = Path(root_str)
    try:
        st = os.lstat(base)
    except OSError as exc:
        raise ValueError(f"inaccessible artifact_root: {root_str}") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise ValueError("artifact_root must be a non-symlink directory")
    resolved = base.resolve()
    results = [_grade_run(c, runs.get((p, c["id"])), base, resolved, p) for p in active for c in cases]
    passed = sum(1 for r in results if r["passed"])
    return {"total": len(results), "passed": passed, "failed": len(results) - passed, "results": results}


class _CliParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _read_json(path_str: str) -> Any:
    try:
        with open(path_str, "rb") as fh:
            raw = fh.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError(f"input too large: {path_str}")
        return json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON input {path_str}: {exc}") from exc


def _native_json_trailing_comma() -> str | None:
    """Identify the caller's decoder wording and positions using fixed probes."""
    if sys.implementation.name != "cpython":
        return None
    errors = []
    for probe in ("[1,]", '{"a":1,}'):
        try:
            json.loads(probe)
        except json.JSONDecodeError as error:
            errors.append((error.msg, error.pos))
        else:
            return None
    if errors == [("Expecting value", 3),
                  ("Expecting property name enclosed in double quotes", 7)]:
        return "legacy"
    if errors == [("Illegal trailing comma before end of array", 2),
                  ("Illegal trailing comma before end of object", 6)]:
        return "modern"
    return None


def _native_json_integer_error(limit: int) -> str | None:
    """Bind the caller's error wording without passing any evidence to Python."""
    if not 0 < limit <= 10_000:
        return None
    messages = []
    for digits in (limit + 1, limit + 2):
        try:
            json.loads("9" * digits)
        except json.JSONDecodeError:
            return None
        except ValueError as error:
            messages.append(str(error))
        else:
            return None
    template = messages[0].replace(str(limit + 1), "{digits}").replace(str(limit), "{limit}")
    if len(template) > 512 or not template.isascii() or not template.isprintable():
        return None
    if template.count("{limit}") != 1 or template.count("{digits}") != 1:
        return None
    if template.replace("{limit}", str(limit)).replace("{digits}", str(limit + 2)) != messages[1]:
        return None
    return template


def _native_help_layout() -> str | None:
    import gettext
    import shutil

    if (sys.implementation.name != "cpython" or sys.stdout.isatty()
            or any(key in os.environ for key in ("FORCE_COLOR", "PYTHON_COLORS"))
            or os.path.basename(sys.argv[0]) != "agent_behavior_eval.py"
            or getattr(sys.modules.get("__main__"), "__spec__", None) is not None):
        return None
    if any(gettext.gettext(text) != text for text in ("usage: ", "show this help message and exit")):
        return None
    group = getattr(argparse.ArgumentParser(add_help=False), "_optionals", None)
    title = {"optional arguments": "legacy", "options": "modern"}.get(getattr(group, "title", None))
    if hasattr(argparse.HelpFormatter, "_get_actions_usage_parts"):
        title = "grouped" if title == "modern" else None
    width = shutil.get_terminal_size().columns - 2
    return f"{title},{width}" if title is not None and 32 <= width <= 512 else None


def _native_report(argv: Sequence[str]) -> tuple[int, str] | None:
    """Use the verified candidate for reports and stable input diagnostics."""
    if os.environ.get("MORU_LAUNCHER_BACKEND", "auto") not in ("auto", "rust"):
        return None
    if any(name in sys.modules for name in ("sitecustomize", "usercustomize")):
        return None
    help_flags = ("-h", "--h", "--he", "--hel", "--help")
    help_layout = None
    if any(flag in help_flags for flag in argv):
        if len(argv) != 1 or (help_layout := _native_help_layout()) is None:
            return None

    import subprocess

    try:
        import unicodedata

        from support.native_launcher_install import artifact_plan

        if any(os.fsencode(value) != value.encode("utf-8") for value in argv):
            return None
        entry = Path(__file__).resolve()
        plan = artifact_plan(entry.parent.parent, entry)
        if plan is None:
            return None
        command = [str(plan["source"]), str(entry), "--behavior-eval"]
        if help_layout is not None:
            command.append(f"--help-layout={help_layout}")
        else:
            digit_limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
            command.extend(["--stable-errors-only", f"--unicode-version={unicodedata.unidata_version}",
                            f"--int-max-str-digits={digit_limit}"])
            if (integer_error := _native_json_integer_error(digit_limit)) is not None:
                command.append(f"--json-integer-error={integer_error}")
            if (trailing_comma := _native_json_trailing_comma()) is not None:
                command.append(f"--json-trailing-comma={trailing_comma}")
        command.extend(["--public-args", *argv])
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True)
        if result.returncode in (0, 1) and result.stdout and not result.stderr:
            return result.returncode, result.stdout.decode("ascii")
        if result.returncode == 2 and result.stderr and not result.stdout:
            return 2, result.stderr.decode("utf-8")
    except (OSError, ValueError, ImportError, RuntimeError):
        pass
    return None


def main(argv: Sequence[str] | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    out, err = stdout or sys.stdout, stderr or sys.stderr
    if __name__ == "__main__" and argv is stdout is stderr is None:
        if (native := _native_report(sys.argv[1:])) is not None:
            code, output = native
            (err if code == 2 else out).write(output)
            return code
    p = _CliParser(description="Offline agent behavior grader (supplied evidence only, not live scores).")
    for flag, h in (("--cases", "Cases JSON"), ("--traces", "Traces JSON"), ("--artifact-root", "Root holding <provider>/<case_id>/ artifacts")):
        p.add_argument(flag, required=True, help=h)
    p.add_argument("--providers", nargs="+", help="Optional provider subset.")
    try:
        ns = p.parse_args(argv)
        toks = None if ns.providers is None else [x.strip() for a in ns.providers for x in a.split(",")]
        if toks is not None and any(not x for x in toks):
            raise ValueError("empty provider token in --providers")
        report = evaluate(_read_json(ns.cases), _read_json(ns.traces), ns.artifact_root, SUPPORTED_PROVIDERS if toks is None else toks)
    except ValueError as exc:
        err.write(f"error: {exc}\n")
        return 2
    out.write(json.dumps(report, indent=2) + "\n")
    return 0 if report["failed"] == 0 and report["total"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
