#!/usr/bin/env python3
"""Evaluate project-memory retrieval on synthetic fixtures, without store writes.

This developer tool measures selection and rendered context, not learning,
applicability judgments, model accuracy, token usage or production performance.
An alternate engine root may contain an unchanged historical memory module.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any


SCRIPTS = Path(__file__).resolve().parent
DEFAULT_FIXTURE = SCRIPTS.parent / "tests/fixtures/project-memory-experience-cases.json"
ID_RE = re.compile(r"[0-9a-f]{16}\Z")
SCOPE_RE = re.compile(r"[a-z][a-z0-9_-]{1,40}\Z")
RECORD_FIELDS = {"id", "body", "source", "scope", "status", "review_in_days",
                 "applies_when", "not_when", "replaces"}
CASE_FIELDS = {"id", "category", "scope", "request", "target_summary", "target_paths",
               "expected_relevant", "applicability_expectation"}


def _line(value: Any, maximum: int, label: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or not value.isprintable():
        raise ValueError(f"{label} must be one printable line of 1–{maximum} characters")
    return value


def _scope(value: Any) -> str:
    if not isinstance(value, str) or not SCOPE_RE.fullmatch(value):
        raise ValueError("scope must be a workflow slug")
    return value


def load_fixture(path: Path) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(fixture, dict) or type(fixture.get("schema_version")) is not int or fixture["schema_version"] != 1:
        raise ValueError("fixture schema_version must be 1")
    _line(fixture.get("description"), 1000, "description")
    records, cases = fixture.get("records"), fixture.get("cases")
    if not isinstance(records, list) or not records or not isinstance(cases, list) or not cases:
        raise ValueError("fixture needs nonempty records and cases lists")
    ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) - RECORD_FIELDS:
            raise ValueError("record contains unsupported fields")
        identifier = record.get("id")
        if not isinstance(identifier, str) or not ID_RE.fullmatch(identifier) or identifier in ids:
            raise ValueError("record ids must be unique 16-character lowercase hex strings")
        ids.add(identifier)
        _line(record.get("body"), 500, "body")
        _line(record.get("source"), 200, "source")
        _scope(record.get("scope", "task"))
        if not isinstance(record.get("status", "active"), str) or record.get("status", "active") not in {"active", "approved", "pending", "retired"}:
            raise ValueError("record status is invalid")
        days = record.get("review_in_days", 30)
        if isinstance(days, bool) or not isinstance(days, int) or not -365 <= days <= 365:
            raise ValueError("review_in_days must be an integer between -365 and 365")
        for field in ("applies_when", "not_when"):
            if field in record:
                _line(record[field], 160, field)
    for record in records:
        if "replaces" in record and (not isinstance(record["replaces"], str) or
                                    record["replaces"] not in ids or record["replaces"] == record["id"]):
            raise ValueError("replaces must reference another fixture record")
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) - CASE_FIELDS:
            raise ValueError("case contains unsupported fields")
        identifier = _line(case.get("id"), 80, "case id")
        if identifier in case_ids:
            raise ValueError("case ids must be unique")
        case_ids.add(identifier)
        _line(case.get("category"), 80, "category")
        _scope(case.get("scope", "task"))
        for field in ("request", "target_summary"):
            if field in case and (not isinstance(case[field], str) or
                                  (case[field] and not case[field].isprintable())):
                raise ValueError(f"{field} must be a printable string")
        paths = case.get("target_paths", [])
        if not isinstance(paths, list) or any(not isinstance(item, str) or not item or
                                            not item.isprintable() for item in paths):
            raise ValueError("target_paths must contain nonempty printable strings")
        expected = case.get("expected_relevant")
        if not isinstance(expected, list) or any(not isinstance(item, str) or item not in ids
                                                for item in expected) or len(set(expected)) != len(expected):
            raise ValueError("expected_relevant must contain unique fixture record ids")
        if "applicability_expectation" in case:
            _line(case["applicability_expectation"], 1000, "applicability_expectation")
    return fixture


def load_engine(root: Path) -> ModuleType:
    path = root.resolve() / "agent_project_memory.py"
    spec = importlib.util.spec_from_file_location("_moru_experience_engine", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load memory engine: {path}")
    # A historical module can reuse unchanged dependencies from this checkout.
    original_path = sys.path[:]
    try:
        sys.path[:0] = [str(root.resolve()), str(SCRIPTS)]
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
    return module


def evaluate(engine: ModuleType, fixture: dict[str, Any], project: Path) -> dict[str, Any]:
    today = date.today()
    records = []
    for item in fixture["records"]:
        record = {key: value for key, value in item.items() if key != "review_in_days"}
        record.update(schema_version=1, status=item.get("status", "active"),
                      scope=item.get("scope", "task"), created_at=f"{today}T00:00:00+00:00",
                      review_on=(today + timedelta(days=item.get("review_in_days", 30))).isoformat())
        record["digest"] = engine._digest(record)
        records.append(record)
    results = []
    totals = {"relevant_rendered": 0, "rendered": 0, "expected": 0,
              "irrelevant_selections": 0, "misses": 0, "payload_characters": 0}
    for case in fixture["cases"]:
        context = {"records": records, "request": case.get("request", ""),
                   "target_summary": case.get("target_summary", ""),
                   "target_paths": tuple(case.get("target_paths", []))}
        scope = case.get("scope", "task")
        ranked = engine._recall(project, scope, **context)
        lines = engine.recall_lines(project, scope, **context)
        payloads = [line[2:] for line in lines if line.startswith("- ")]
        rendered = [json.loads(payload)["id"] for payload in payloads]
        if len(rendered) != len(set(rendered)):
            raise ValueError("engine rendered duplicate ids")
        expected = set(case["expected_relevant"])
        selected = set(rendered)
        if not selected.issubset({record["id"] for record in records}):
            raise ValueError("engine rendered an unknown fixture id")
        counts = {"relevant_rendered": len(selected & expected), "rendered": len(rendered),
                  "expected": len(expected), "irrelevant_selections": len(selected - expected),
                  "misses": len(expected - selected),
                  "payload_characters": sum(map(len, payloads))}
        if case["category"] != "listing":
            for key, value in counts.items():
                totals[key] += value
        results.append({"id": case["id"], "category": case["category"],
                        "ranked_ids": [record["id"] for record in ranked],
                        "rendered_ids": rendered, "expected_relevant": case["expected_relevant"],
                        "false_inclusions": sorted(selected - expected),
                        "missed_ids": sorted(expected - selected), **counts,
                        **({"applicability_expectation": case["applicability_expectation"]}
                           if "applicability_expectation" in case else {})})
    totals.update(precision=(totals["relevant_rendered"] / totals["rendered"]
                             if totals["rendered"] else None),
                  recall=(totals["relevant_rendered"] / totals["expected"]
                          if totals["expected"] else None))
    return {"schema_version": 1, "synthetic": True, "evaluation_date": today.isoformat(),
            "measurement": "rendered retrieval only; listing cases and applicability judgments are excluded from retrieval metrics",
            "case_count": len(results),
            "retrieval_case_count": sum(item["category"] != "listing" for item in results),
            "total_payload_characters": sum(item["payload_characters"] for item in results),
            "metrics": totals, "cases": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", type=Path, default=SCRIPTS)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args(argv)
    try:
        fixture = load_fixture(args.fixture)
        engine = load_engine(args.engine_root)
        report = evaluate(engine, fixture, SCRIPTS.parent)
        report["inputs"] = {name: {"path": str(path.resolve()),
                                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                            for name, path in (("engine", args.engine_root / "agent_project_memory.py"),
                                               ("fixture", args.fixture))}
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, ValueError, ImportError, AttributeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
