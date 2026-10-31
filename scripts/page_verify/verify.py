#!/usr/bin/env python3
"""Independent page verification: derive a checklist from the request, observe, judge.

The model that built a page is the worst witness that the page works: its tests
repeat its own assumptions and a green build proves nothing about motion, state
or framing. This module turns the user's request into observable acceptance
items, has ``observe.mjs`` watch the built page in a real browser, and has a
separate judge rule on each item from that evidence alone.

Verdicts are ``pass``, ``fail`` or ``unobserved``. Evidence that cannot show a
property yields ``unobserved``, never a guess. The exit status is 1 when any item
failed, 0 otherwise, so a hook can gate on it.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from support.provider_http import open_provider_request  # noqa: E402

DERIVE_MODEL = os.environ.get("MORU_VERIFY_DERIVE_MODEL", "openai/gpt-5.4")
JUDGE_MODEL = os.environ.get("MORU_VERIFY_JUDGE_MODEL", "openai/gpt-5.4")
VERDICTS = {"pass", "fail", "unobserved"}
GENERIC_ITEMS = [
    {"id": "loads-clean", "claim": "The page loads and runs without uncaught errors or failed script requests.",
     "phase": "any", "evidence": ["console"], "source": "generic"},
    {"id": "action-responds", "claim": "Using the page's main action visibly changes its state.",
     "phase": "during_action", "evidence": ["text", "screenshots"], "source": "generic"},
]

DERIVE_PROMPT = """You turn a user's request for a web page into acceptance items that a third party can
check by watching the running page: screenshots over time, the page's visible text, and console errors.

Rules:
- Every item states one observable fact that must be true for the request to be satisfied.
- Include conditions the request implies even when unstated: a "ready" or "before" state must differ from the
  running state; a subject said to stay visible must be in frame in every state; motion must look coherent with
  the subject (no reversed, mirrored or teleporting movement); things said to return must end where they began.
- Before answering, consider each of these generic implied conditions and include the ones that apply to this
  request (skip those that do not): (1) resting state before the action differs from the active state, with
  nothing that belongs to the active state already running; (2) a moving subject faces its direction of travel and
  never moves backwards, sideways or teleports unless asked; (3) the subject stays in frame in every camera or view
  mode the page offers, while it moves; (4) motion looks continuous, with plausible acceleration and deceleration
  rather than a constant-speed jump; (5) things said to return end where they began; (6) the offered controls
  actually change what they claim to change; (7) a vehicle that rises or descends vertically keeps its body level
  (pitch near zero) and does not stand on its tail, dive nose-first or fall like a rocket unless the request asks
  for that, and its pitch and roll stay plausible through every phase.
- Add nothing the request does not imply. No visual taste judgements such as "beautiful".
- At most 10 items. Each item: id (short kebab-case), claim, phase (initial | during_action | after_action | any),
  evidence (a non-empty subset of: screenshots, text, console, code). Use code for anything a screenshot cannot
  show: which way a subject's front points versus its travel direction, coordinate conventions, and whether
  things that belong to the active state are already running in the resting state.
Answer with a JSON array only.

REQUEST:
{request}
"""

JUDGE_PROMPT = """You are an independent verifier. You did not build this page. Judge each acceptance item using
only the evidence below: the screenshots (in order, labelled), the visible page text captured at each step, and the
console errors. For each item answer one verdict:
- pass: the evidence shows it is true.
- fail: a specific step's screenshot or text shows it is false. Name that step in "contradicting_step". Missing
  evidence, a control that was never operated, a viewport that was never tried, or a view that legitimately cannot
  show the thing (for example a first-person view cannot show the subject itself) is never a fail.
- unobserved: the evidence cannot show it. Do not guess; say what is missing.
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


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        env = Path.home() / ".moru" / "research.env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                match = re.match(r"\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.+)", line)
                if match:
                    key = match.group(1).strip().strip("\"'")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set and ~/.moru/research.env has none")
    return key


def chat(model: str, content: object, *, max_tokens: int = 3000) -> str:
    body = json.dumps({"model": model, "temperature": 0, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": content}]}).encode()
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json",
                 "User-Agent": "moru-page-verify"})
    with open_provider_request(request, timeout=240) as response:
        return json.load(response)["choices"][0]["message"].get("content") or ""


def parse_array(text: str) -> list:
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise ValueError("no JSON array in the model answer")
    value = json.loads(match.group(0))
    if not isinstance(value, list):
        raise ValueError("answer is not an array")
    return value


def clean_items(raw: list) -> list[dict]:
    items = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("claim"):
            continue
        evidence = [e for e in entry.get("evidence", []) if e in {"screenshots", "text", "console", "code"}]
        items.append({"id": re.sub(r"[^a-z0-9-]+", "-", str(entry["id"]).lower()).strip("-")[:48],
                      "claim": str(entry["claim"])[:300], "phase": str(entry.get("phase") or "any"),
                      "evidence": evidence or ["screenshots"], "source": "derived"})
    return items[:10]


MENU_ITEMS = [{
    "id": "body-level-in-vertical-phases",
    "claim": ("When the vehicle rises or descends vertically (takeoff, landing, hover), its body stays level (pitch near "
              "zero); it does not stand on its tail, dive nose-first or fall like a rocket unless the request asks for that."),
    "phase": "during_action", "evidence": ["code", "screenshots"], "source": "menu",
    "applies": r"take.?off|landing|\bland\b|lift.?off|hover|ascen|descen|vtol|rocket|\bfl(?:y|ies|ight)\b|aircraft|spaceship|drone",
    "covered": r"level|pitch|nose|attitude|tail",
}]


def ensure_menu_items(request: str, items: list[dict]) -> list[dict]:
    """Add a standard item when the request calls for it and the derivation left it out.

    The derivation prompt lists generic implied conditions but the model decides which to
    include, and it omitted vehicle attitude on a request about takeoff and landing.
    """

    have = " ".join(f"{i['id']} {i['claim']}" for i in items).lower()
    extra = [{k: m[k] for k in ("id", "claim", "phase", "evidence", "source")} for m in MENU_ITEMS
             if re.search(m["applies"], request, re.I) and not re.search(m["covered"], have)]
    return [*items, *extra]


def derive_checklist(request: str, *, ask=chat) -> list[dict]:
    derived = clean_items(parse_array(ask(DERIVE_MODEL, DERIVE_PROMPT.format(request=request))))
    seen = {item["id"] for item in derived}
    return ensure_menu_items(request, [*(item for item in GENERIC_ITEMS if item["id"] not in seen), *derived])


def image_part(b64: str) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def load_images(evidence_dir: Path, evidence: dict) -> dict[str, str]:
    return {step["screenshot"]: base64.b64encode((evidence_dir / step["screenshot"]).read_bytes()).decode()
            for step in evidence.get("steps", [])}


MAX_IMAGES = 10


def select_steps(steps: list[dict], limit: int = MAX_IMAGES) -> list[dict]:
    """The screenshots worth sending: the start, the default-view run, a few controls, the end.

    Each image costs tokens at the judge; later controls and middle marks add the least.
    """

    if len(steps) <= limit:
        return steps
    keep = [s for s in steps if s["label"] == "initial" or s["label"].startswith("default-view")]
    controls = [s for s in steps if s["label"].startswith("control-")]
    late = [s for s in steps if s["label"].startswith("late-")]
    chosen = keep + controls[: max(0, limit - len(keep) - 2)] + late[-2:]
    chosen = [s for s in steps if s in chosen]
    return chosen[:limit] if len(chosen) > limit else chosen


def judge_loaded(items: list[dict], evidence: dict, images: dict[str, str], *, ask=chat) -> list[dict]:
    steps = evidence.get("steps", [])
    text = JUDGE_PROMPT.format(
        items=json.dumps([{k: i[k] for k in ("id", "claim", "phase", "evidence")} for i in items], indent=1),
        console=json.dumps(evidence.get("consoleErrors", [])),
        failed=json.dumps([r for r in evidence.get("failedRequests", []) if "favicon" not in r.get("url", "")]),
        primary=json.dumps(evidence.get("primaryAction")),
        steps="\n".join(f"- {s['label']} ({s['seconds']}s): {s.get('text', '')[:400]}" for s in steps))
    content: list[dict] = [{"type": "text", "text": text}]
    if any("screenshots" in i.get("evidence", []) for i in items):
        for step in select_steps(steps):
            content.append({"type": "text", "text": f"Screenshot: {step['label']}"})
            content.append(image_part(images[step["screenshot"]]))
    answers = {a.get("id"): a for a in parse_array(ask(JUDGE_MODEL, content, max_tokens=4000)) if isinstance(a, dict)}
    known = {step["label"] for step in steps}
    results = []
    for item in items:
        answer = answers.get(item["id"], {})
        verdict = answer.get("verdict") if answer.get("verdict") in VERDICTS else "unobserved"
        reason = str(answer.get("reason") or "the judge gave no answer for this item")[:400]
        if verdict == "fail" and answer.get("contradicting_step") not in known:
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
points from the target to the eye. For resting state, find what runs before the action starts. For attitude, find the pitch and roll applied during vertical rises and descents and judge whether the body stays level; heading follows the horizontal direction of travel, not a vertical one.
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


def collect_source(project: Path) -> str:
    """The project's own source, line numbered, without dependencies, builds or tests."""

    skip = {"node_modules", "dist", "build", "out", ".git", ".moru", "tests", "test", "coverage"}
    chunks, total = [], 0
    for path in sorted(project.rglob("*")):
        relative = path.relative_to(project)
        if (path.suffix not in SOURCE_SUFFIXES or not path.is_file() or skip & set(relative.parts)
                or ".test." in path.name or ".spec." in path.name):
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


def remote_call(path: str, payload: dict) -> dict:
    """Ask a judge service instead of calling a model here, so the key never enters this process."""

    base = os.environ["MORU_VERIFY_JUDGE_URL"].rstrip("/")
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


def can_observe() -> bool:
    """Whether a browser and node are here for the observer, so a stop-time check can really run."""

    import shutil

    candidates = (os.environ.get("CHROME_PATH", ""), "/usr/bin/google-chrome", "/usr/bin/chromium",
                  "/usr/bin/chromium-browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return bool(shutil.which("node")) and any(path and Path(path).exists() for path in candidates)


def can_judge() -> bool:
    """Whether a derive-and-judge backend is reachable from this process."""

    if os.environ.get("MORU_VERIFY_JUDGE_URL"):
        return True
    try:
        api_key()
    except RuntimeError:
        return False
    return True


def feedback_text(results: list[dict]) -> str:
    """The message that sends failed items back to the model that built the page, or "" when none failed."""

    failed = [r for r in results if r["verdict"] == "fail"]
    if not failed:
        return ""
    lines = [f"- {r['id']}: {r['claim']} Observed: {r['reason']}" for r in failed]
    unobserved = [r["id"] for r in results if r["verdict"] == "unobserved"]
    tail = (f"\nNot observed, so unchecked: {', '.join(unobserved)}." if unobserved else "")
    return ("An independent check of the finished page in a real browser, against criteria derived from the original "
            "request, found these items failing:\n" + "\n".join(lines) + tail +
            "\nFix the cause of each failing item in the project, rebuild so the built output reflects the fix, and "
            "say in your final report what you changed and what you could not verify.")


def remaining_text(results: list[dict]) -> str:
    """The message for the last check: failures that remain are to be reported, not hidden.

    No further fix is asked for. The aim is an honest final report, so the reader is not told the
    page is complete when the independent check still found it failing.
    """

    failed = [r for r in results if r["verdict"] == "fail"]
    if not failed:
        return ""
    lines = [f"- {r['id']}: {r['claim']} Observed: {r['reason']}" for r in failed]
    return ("The independent check run after your fix still reports these items failing:\n" + "\n".join(lines) +
            "\nDo not call the page complete. State these plainly in your final report as not fixed, with what you "
            "tried and what you could not verify.")


def observe(url: str, out: Path, viewport: str, seconds: int) -> None:
    import signal

    # Own session, so a timeout can end the observer and every browser process it started.
    process = subprocess.Popen(["node", str(HERE / "observe.mjs"), url, str(out), "--viewport", viewport,
                                "--seconds", str(seconds)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        _, stderr = process.communicate(timeout=seconds + 150)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        _, stderr = process.communicate()
    if not (out / "observations.json").is_file():
        raise RuntimeError(f"observer produced no evidence: {stderr.strip()[:300]}")


def project_fingerprint(project: Path) -> str:
    """A hash of the built page and the source it came from, to tell whether anything changed."""

    import hashlib

    digest = hashlib.sha256()
    dist = find_dist(project)
    roots = [dist] if dist else []
    roots.append(project / "src")
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.stat().st_size < 4_000_000:
                digest.update(str(path.relative_to(project)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def floor_results(items: list[dict], evidence: dict) -> list[dict]:
    """Verdicts for the basic checks that need no model: errors on load and an unresponsive main action.

    Returns the failing items only. When any basic check fails there is nothing for a judge to add yet,
    so the model calls are skipped and the agent is sent back to fix those first.
    """

    steps = evidence.get("steps", [])
    failing = []
    errors = evidence.get("consoleErrors", [])
    if errors and steps:
        for item in items:
            if item["id"] in {"loads-clean", "no-console-errors"}:
                failing.append({**item, "verdict": "fail", "reason": f"{steps[-1]['label']}: console error {errors[0][:160]}"})
    if evidence.get("primaryAction") and len(steps) > 1 and evidence.get("secondaryControls") is not None:
        first = steps[0].get("text")
        first_shot = steps[0].get("shotHash")
        # A canvas-only change leaves the text alone, so the picture must also be unchanged.
        if all(step.get("text") == first and step.get("shotHash") == first_shot for step in steps[1:]):
            for item in items:
                if item["id"] == "action-responds":
                    failing.append({**item, "verdict": "fail",
                                    "reason": f"{steps[-1]['label']}: neither the page text nor the picture changed after the main action was used twice"})
    return failing


def find_dist(project: Path) -> Path | None:
    for candidate in (project / "dist", project / "build", project / "out", project):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def verify_project(project: Path, request: str, out: Path, *, viewport: str = "desktop", seconds: int = 75,
                   checklist: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Serve the built page, observe it, and judge it. Returns (items, results)."""

    import socket
    import time

    dist = find_dist(project)
    if dist is None:
        raise RuntimeError("no built page (index.html) found in the project")
    out.mkdir(parents=True, exist_ok=True)
    items = checklist if checklist is not None else derive_any(request)
    (out / "checklist.json").write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                               "--directory", str(dist)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        observe(f"http://127.0.0.1:{port}/", out / "evidence", viewport, seconds)
    finally:
        server.terminate()
    evidence = json.loads((out / "evidence" / "observations.json").read_text(encoding="utf-8"))
    failing = floor_results(items, evidence)
    if failing:
        by_id = {r["id"]: r for r in failing}
        results = [by_id.get(i["id"]) or {**i, "verdict": "unobserved", "reason": "skipped: a basic check failed, fix that first"}
                   for i in items]
    else:
        results = judge_any(items, out / "evidence", collect_source(project))
    (out / "report.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(render(results), encoding="utf-8")
    return items, results


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
    observe(args.url, args.out / "evidence", args.viewport, args.seconds)
    results = judge_any(items, args.out / "evidence")
    (args.out / "report.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / "report.md").write_text(render(results), encoding="utf-8")
    print(render(results))
    return 1 if any(r["verdict"] == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
