"""Judging acceptance items from screenshots, page text and source code."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path

from verify_backend import chat
from verify_checklist import parse_array

JUDGE_MODEL = os.environ.get("MORU_VERIFY_JUDGE_MODEL", "openai/gpt-5.4")
VERDICTS = {"pass", "fail", "unobserved"}

JUDGE_PROMPT = """You are an independent verifier. You did not build this page. Judge each acceptance item using
only the evidence below: the screenshots (in order, labelled), the visible page text captured at each step, and the
console errors. For each item answer one verdict:
- pass: the evidence shows it is true.
- fail: a specific step's screenshot or text shows it is false. Name that step in "contradicting_step"; for a number in the TIMELINE write timeline@<seconds>s. Missing
  evidence, a control that was never operated, a viewport that was never tried, or a view that legitimately cannot
  show the thing (for example a first-person view cannot show the subject itself) is never a fail.
- unobserved: the evidence cannot show it. Do not guess; say what is missing.
Steps named pointer-* are a real mouse drag over the scene and then a wheel scroll, each with a picture before and after.
Steps named mobile-* come from a 390x844 touch viewport after the main action; overflowX above 0 there means the page scrolls sideways.
The TIMELINE lists the page's own text every half second while it ran (only when it changed): use its numbers for continuity, jumps and smoothness.
Give a one-sentence reason that cites a step label. Answer with a JSON array of
{{"id": ..., "verdict": ..., "reason": ..., "contradicting_step": "<label or empty>"}} only, covering every item.

ITEMS:
{items}

CONSOLE ERRORS: {console}
FAILED REQUESTS (favicon requests are irrelevant): {failed}
PRIMARY ACTION FOUND: {primary}
STEPS (label, seconds after the action, visible text):
{steps}
"""


def image_part(b64: str) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def load_images(evidence_dir: Path, evidence: dict) -> dict[str, str]:
    return {step["screenshot"]: base64.b64encode((evidence_dir / step["screenshot"]).read_bytes()).decode()
            for step in evidence.get("steps", [])}


MAX_IMAGES = 16


LATE_IMAGES = 5


def spread(items: list, count: int) -> list:
    """``count`` items spread evenly over the list, always including the last one."""

    if len(items) <= count:
        return list(items)
    return [items[round(i * (len(items) - 1) / (count - 1))] for i in range(count)]


def select_steps(steps: list[dict], limit: int = MAX_IMAGES) -> list[dict]:
    """The screenshots worth sending: the start, the default-view run, a few controls, the end.

    Each image costs tokens at the judge; later controls and middle marks add the least.
    """

    if len(steps) <= limit:
        return steps
    keep = [s for s in steps
            if s["label"] == "initial" or s["label"].startswith(("default-view", "pointer-", "mobile-"))]
    controls = [s for s in steps if s["label"].startswith("control-")]
    late = []
    for step in steps:
        # A frame whose page text equals the one before it shows nothing new (an idle scene still shifts a few pixels).
        if step["label"].startswith("late-") and not (late and step.get("text") and step.get("text") == late[-1].get("text")):
            late.append(step)
    chosen = keep + controls[: max(0, limit - len(keep) - LATE_IMAGES)] + spread(late, LATE_IMAGES)
    chosen = [s for s in steps if s in chosen]
    return chosen[:limit] if len(chosen) > limit else chosen


def timeline_text(evidence: dict) -> str:
    """The page's text samples, keeping only the ones where it changed (digits included), capped."""

    lines, last = [], None
    for sample in evidence.get("timeline") or []:
        if sample.get("text") != last:
            lines.append(f"- {sample['t']}s: {sample['text'][:160]}")
            last = sample.get("text")
    return "\n".join(spread(lines, 70)) or "(none)"


def judge_loaded(items: list[dict], evidence: dict, images: dict[str, str], *, ask=chat) -> list[dict]:
    steps = evidence.get("steps", [])
    text = JUDGE_PROMPT.format(
        items=json.dumps([{k: i[k] for k in ("id", "claim", "phase", "evidence")} for i in items], indent=1),
        console=json.dumps(evidence.get("consoleErrors", [])),
        failed=json.dumps([r for r in evidence.get("failedRequests", []) if "favicon" not in r.get("url", "")]),
        primary=json.dumps(evidence.get("primaryAction")),
        steps="\n".join(f"- {s['label']} ({s['seconds']}s): {s.get('text', '')[:400]}"
                        + (f" [overflowX={s['overflowX']}]" if s['label'].startswith('mobile-') else "") for s in steps)
        + "\nTIMELINE:\n" + timeline_text(evidence))
    content: list[dict] = [{"type": "text", "text": text}]
    if any("screenshots" in i.get("evidence", []) for i in items):
        for step in select_steps(steps):
            content.append({"type": "text", "text": f"Screenshot: {step['label']}"})
            content.append(image_part(images[step["screenshot"]]))
    answers = {a.get("id"): a for a in parse_array(ask(JUDGE_MODEL, content, max_tokens=4000)) if isinstance(a, dict)}
    known = {step["label"] for step in steps}
    has_timeline = bool(evidence.get("timeline"))
    results = []
    for item in items:
        answer = answers.get(item["id"], {})
        verdict = answer.get("verdict") if answer.get("verdict") in VERDICTS else "unobserved"
        reason = str(answer.get("reason") or "the judge gave no answer for this item")[:400]
        cited = str(answer.get("contradicting_step") or "")
        if verdict == "fail" and not (cited in known or (has_timeline and cited.startswith("timeline"))):
            verdict = "unobserved"
            reason = f"downgraded: a fail needs a contradicting step; judge said: {reason}"[:400]
        if evidence.get("observerError"):
            verdict, reason = "unobserved", f"observer failed: {evidence['observerError']}"
        results.append({**item, "verdict": verdict, "reason": reason})
    return results


def judge(items: list[dict], evidence_dir: Path, *, ask=chat) -> list[dict]:
    evidence = json.loads((evidence_dir / "observations.json").read_text(encoding="utf-8"))
    return judge_loaded(items, evidence, load_images(evidence_dir, evidence), ask=ask)


CODE_JUDGE_PROMPT = """You are an independent code reviewer. Judge each item from the source code below ONLY.
For facing, find which local axis the model's front points along (geometry or comments), find how the per-frame
orientation is computed from the path direction, and work out whether the front ends up along the direction of
travel. Remember the engine's own conventions, for example in Three.js Object3D.lookAt aims a mesh's +Z at the
target (cameras and lights aim -Z) while Matrix4.lookAt(eye, target, up) builds the camera basis, whose Z axis
points from the target to the eye. For resting state, find what runs before the action starts. For attitude, find the pitch and roll applied during vertical rises and descents and judge whether the body stays level, except for a rocket or launch vehicle, which rises upright by design; heading follows the horizontal direction of travel, not a vertical one.
A direction that looks reversed may be intended: before failing it, find which end carries the heat shield, engine or landing legs. A capsule re-entering heat-shield first, or a booster landing tail-first, is correct; fail only when the code makes the wrong end lead against the stated intent.
Verdicts: pass (the code shows it holds), fail (the code shows it is false; cite file:line and quote the code),
unobserved (the code cannot decide it).
Answer with a JSON array of {{"id": ..., "verdict": ..., "reason": ..., "evidence": "file:line and quoted code"}} only.

ITEMS:
{items}

SOURCE (line numbered):
{source}
"""
SOURCE_SUFFIXES = {".js", ".jsx", ".mjs", ".ts", ".tsx", ".html", ".css"}
SOURCE_LIMIT = 150_000


SECRET_NAME = re.compile(r"(^\.env|secret|credential|password|token|\.pem$|\.key$)", re.IGNORECASE)


def source_candidates(project: Path) -> list[Path]:
    """Files git would track or could add (ignored files excluded); every file when not a git repo."""

    try:
        listed = subprocess.run(
            ["git", "-C", str(project), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=True, timeout=20).stdout
        return sorted(project / name for name in listed.decode(errors="ignore").split("\0") if name)
    except (OSError, subprocess.SubprocessError):
        return sorted(project.rglob("*"))


def collect_source(project: Path) -> str:
    """The project's own source, line numbered, without dependencies, builds, tests, secrets or links out of the project."""

    skip = {"node_modules", "dist", "build", "out", ".git", ".moru", "tests", "test", "coverage"}
    root = project.resolve()
    chunks, total = [], 0
    for path in source_candidates(project):
        relative = path.relative_to(project)
        if (path.suffix not in SOURCE_SUFFIXES or path.is_symlink() or not path.is_file() or skip & set(relative.parts)
                or ".test." in path.name or ".spec." in path.name or SECRET_NAME.search(path.name)
                or not path.resolve().is_relative_to(root)):
            continue
        body = "\n".join(f"{n + 1}: {line}" for n, line in enumerate(path.read_text(errors="ignore").splitlines()))
        if total + len(body) > SOURCE_LIMIT:
            continue
        total += len(body)
        chunks.append(f"=== {relative}\n{body}")
    return "\n".join(chunks)


def judge_code(items: list[dict], source: str, *, ask=chat) -> dict[str, dict]:
    """Verdicts for the items that name code as evidence, keyed by id."""

    chosen = [i for i in items if "code" in i.get("evidence", [])]
    if not chosen or not source.strip():
        return {}
    text = CODE_JUDGE_PROMPT.format(
        items=json.dumps([{"id": i["id"], "claim": i["claim"]} for i in chosen], indent=1), source=source)
    answers = {a.get("id"): a for a in parse_array(ask(JUDGE_MODEL, text, max_tokens=3000)) if isinstance(a, dict)}
    results = {}
    for item in chosen:
        answer = answers.get(item["id"], {})
        verdict = answer.get("verdict") if answer.get("verdict") in VERDICTS else "unobserved"
        cited = str(answer.get("evidence") or "")
        if verdict == "fail" and not re.search(r"\w[\w./-]*\.\w+:\d+", cited):
            verdict = "unobserved"
        results[item["id"]] = {"verdict": verdict, "reason": str(answer.get("reason") or "")[:300], "evidence": cited[:300]}
    return results


def combine(results: list[dict], code: dict[str, dict]) -> list[dict]:
    """Merge screenshot-based and code-based verdicts: a cited fail from either wins."""

    merged = []
    for result in results:
        verdict_code = code.get(result["id"])
        if verdict_code is None:
            merged.append(result)
            continue
        visual, by_code = result["verdict"], verdict_code["verdict"]
        if "fail" in (visual, by_code):
            final = "fail"
        elif "pass" in (visual, by_code):
            final = "pass"
        else:
            final = "unobserved"
        reasons = {"fail": [], "pass": [], "unobserved": []}
        reasons[visual].append(f"screens: {result['reason']}")
        reasons[by_code].append(f"code: {verdict_code['reason']} [{verdict_code['evidence']}]")
        merged.append({**result, "verdict": final, "reason": " | ".join(reasons[final] or reasons[visual])[:600]})
    return merged
