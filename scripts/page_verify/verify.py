#!/usr/bin/env python3
"""Independent page verification: derive a checklist from the request, observe, judge.

The model that built a page is the worst witness that the page works: its tests
repeat its own assumptions and a green build proves nothing about motion, state
or framing. This module turns the user's request into observable acceptance
items, has ``observe.mjs`` watch the built page in a real browser, and has a
separate judge rule on each item from that evidence alone.

Verdicts are ``pass`` or ``fail``. An item that could not be confirmed is a ``fail``
with ``basis`` ``unverified``, so that someone looks for the cause; a ``fail`` that a
step or a line of code contradicts has ``basis`` ``contradicted``. (The judges
themselves may still answer ``unobserved``; ``finalize`` turns that into a fail.)
The exit status is 1 when any item failed, 0 otherwise, so a hook can gate on it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

# The names below are re-exported: the stop-time hook, the judge service and the tests reach them through `verify`.
from verify_backend import (  # noqa: E402,F401
    api_key, backend, can_judge, chat, codex_available, judge_configured, judge_settings, paid_calls_allowed,
    require_backend, require_paid_calls)
from verify_checklist import GENERIC_ITEMS, DERIVE_PROMPT, derive_checklist, ensure_menu_items  # noqa: E402,F401
from verify_evidence import (  # noqa: E402,F401
    can_observe, find_dist, floor_results, invisible_blockers, observe, observe_mobile, observe_with_mobile,
    project_fingerprint, settle_input_items)
from verify_judging import (  # noqa: E402,F401
    CODE_JUDGE_PROMPT, collect_source, combine, judge, judge_code, judge_loaded, load_images, select_steps,
    timeline_text)


# host.docker.internal is how a container reaches a service its host keeps on loopback.
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}


def remote_call(path: str, payload: dict) -> dict:
    """Ask a judge service instead of calling a model here, so the key never enters this process."""

    base = os.environ["MORU_VERIFY_JUDGE_URL"].rstrip("/")
    parts = urllib.parse.urlsplit(base)
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS):
        raise RuntimeError("MORU_VERIFY_JUDGE_URL must be https, or http on a loopback or container-host name")
    request = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + os.environ.get("MORU_VERIFY_JUDGE_TOKEN", "")})
    with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310 - operator-configured URL
        return json.load(response)


def derive_any(request: str) -> list[dict]:
    if os.environ.get("MORU_VERIFY_JUDGE_URL"):
        return remote_call("/derive", {"request": request})["items"]
    return derive_checklist(request)


def judge_any(items: list[dict], evidence_dir: Path, source: str = "") -> list[dict]:
    if not os.environ.get("MORU_VERIFY_JUDGE_URL"):
        return combine(judge(items, evidence_dir), judge_code(items, source))
    evidence = json.loads((evidence_dir / "observations.json").read_text(encoding="utf-8"))
    return remote_call("/judge", {"items": items, "evidence": evidence, "source": source,
                                  "images": load_images(evidence_dir, evidence)})["results"]


def failing_lines(results: list[dict]) -> tuple[list[str], list[str]]:
    """Failing items as fix lines, and the ids that were never checked because a basic check failed."""

    lines, unchecked = [], []
    for r in results:
        if r["verdict"] != "fail":
            continue
        if r.get("basis") == "unchecked":
            unchecked.append(r["id"])
        elif r.get("basis") == "unverified":
            lines.append(f"- {r['id']}: {r['claim']} Could not be confirmed ({r['reason']}); an item that cannot be "
                         "confirmed counts as failing, so fix the cause or make the behavior observable.")
        else:
            lines.append(f"- {r['id']}: {r['claim']} Observed: {r['reason']}")
    return lines, unchecked


def feedback_text(results: list[dict]) -> str:
    """The message that sends failed items back to the model that built the page, or "" when none failed."""

    lines, unchecked = failing_lines(results)
    if not lines and not unchecked:
        return ""
    tail = f"\nNot checked yet because a basic check failed: {', '.join(unchecked)}." if unchecked else ""
    return ("An independent check of the finished page in a real browser, against criteria derived from the original "
            "request, found these items failing:\n" + "\n".join(lines) + tail +
            "\nFix the cause of each failing item in the project, rebuild so the built output reflects the fix, and "
            "say in your final report what you changed and what you could not verify.")


def remaining_text(results: list[dict]) -> str:
    """The message for the last check: failures that remain are to be reported, not hidden.

    No further fix is asked for. The aim is an honest final report, so the reader is not told the
    page is complete when the independent check still found it failing.
    """

    lines, unchecked = failing_lines(results)
    if not lines and not unchecked:
        return ""
    tail = f"\nNot checked because a basic check was still failing: {', '.join(unchecked)}." if unchecked else ""
    return ("The independent check run after your fix still reports these items failing:\n" + "\n".join(lines) + tail +
            "\nDo not call the page complete. State these plainly in your final report as not fixed, with what you "
            "tried and what you could not verify.")


def verify_project(project: Path, request: str, out: Path, *, viewport: str = "desktop", seconds: int = 75,
                   checklist: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Serve the built page, observe it, and judge it. Returns (items, results)."""

    import socket
    import time

    dist = find_dist(project)
    if dist is None:
        raise RuntimeError("no built page (index.html) found in the project")
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    judged = judge_configured()
    # Without a judge there is nothing to derive a request-specific checklist with: the basic checks still run.
    items = checklist if checklist is not None else (derive_any(request) if judged else [dict(i) for i in GENERIC_ITEMS])
    (out / "checklist.json").write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                               "--directory", str(dist)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        evidence = observe_with_mobile(f"http://127.0.0.1:{port}/", out / "evidence", viewport, seconds)
    finally:
        server.terminate()
    failing = floor_results(items, evidence)
    if not judged:
        results = finalize(basic_results(items, evidence, failing), evidence)
    elif failing:
        by_id = {r["id"]: r for r in failing}
        results = finalize([by_id.get(i["id"]) or {**i, "verdict": "fail", "basis": "unchecked",
                                                   "reason": "not checked yet: a basic check failed, fix that first"}
                            for i in items], evidence)
    else:
        results = finalize(judge_any(items, out / "evidence", collect_source(project)), evidence)
    log_round(items, results, judged, time.time() - started)
    (out / "report.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(render(results), encoding="utf-8")
    return items, results


def basic_results(items: list[dict], evidence: dict, failing: list[dict]) -> list[dict]:
    """Verdicts for the checks that need no model, used when no judge is configured."""

    by_id = {r["id"]: r for r in failing}
    results = []
    for item in items:
        if item["id"] in by_id:
            results.append(by_id[item["id"]])
        elif item["id"] == "action-responds" and not evidence.get("primaryAction"):
            results.append({**item, "verdict": "unobserved", "reason": "no main action was found to use"})
        else:
            results.append({**item, "verdict": "pass", "reason": "no basic problem observed"})
    return results


def log_round(items: list[dict], results: list[dict], judged: bool, seconds: float) -> None:
    """One local line per check, so the person can see what a judge found and what it cost, and decide to keep it."""

    import time

    settings = judge_settings()
    counts = {"pass": 0, "contradicted": 0, "unverified": 0, "unchecked": 0}
    for r in results:
        counts["pass" if r["verdict"] == "pass" else r.get("basis", "contradicted")] += 1
    line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "judged": judged, "backend": settings["backend"] if judged else "none",
            "model": settings["model"], "seconds": round(seconds), "counts": counts,
            "failing": [r["id"] for r in results if r["verdict"] == "fail"]}
    path = Path(os.environ.get("MORU_VERIFY_EFFECT_LOG") or Path.home() / ".moru" / "verify-effect.jsonl")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
    except OSError:
        pass


def finalize(results: list[dict], evidence: dict) -> list[dict]:
    """The only two outcomes a caller sees: pass, or fail with the reason it could not be passed."""

    final = []
    for result in settle_input_items(results, evidence):
        if result["verdict"] == "unobserved":
            result = {**result, "verdict": "fail", "basis": "unverified", "reason": f"unverified: {result['reason']}"[:400]}
        elif result["verdict"] == "fail":
            result = {"basis": "contradicted", **result}
        final.append(result)
    return final


def render(results: list[dict]) -> str:
    lines = ["| item | verdict | reason |", "| --- | --- | --- |"]
    lines += [f"| {r['id']} | {r['verdict']} | {r['reason']} |" for r in results]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--request", required=True, help="The user's request text.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--viewport", choices=("desktop", "mobile"), default="desktop")
    parser.add_argument("--seconds", type=int, default=75)
    parser.add_argument("--checklist", type=Path, help="Reuse a saved checklist instead of deriving one.")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    items = (json.loads(args.checklist.read_text(encoding="utf-8")) if args.checklist
             else derive_any(args.request))
    (args.out / "checklist.json").write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    observe_with_mobile(args.url, args.out / "evidence", args.viewport, args.seconds)
    results = finalize(judge_any(items, args.out / "evidence"),
                       json.loads((args.out / "evidence" / "observations.json").read_text(encoding="utf-8")))
    (args.out / "report.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / "report.md").write_text(render(results), encoding="utf-8")
    print(render(results))
    return 1 if any(r["verdict"] == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
