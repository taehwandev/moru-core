"""Watching the built page in a browser and the checks that need no model."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def can_observe() -> bool:
    """Whether a browser and node are here for the observer, so a stop-time check can really run."""

    import shutil

    candidates = (os.environ.get("CHROME_PATH", ""), "/usr/bin/google-chrome", "/usr/bin/chromium",
                  "/usr/bin/chromium-browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return bool(shutil.which("node")) and any(path and Path(path).exists() for path in candidates)


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
        try:  # the browser has its own process group, which the kill above does not reach
            os.killpg(int((out / "chrome.pid").read_text().strip()), signal.SIGKILL)
        except (OSError, ValueError):
            pass
    if not (out / "observations.json").is_file():
        raise RuntimeError(f"observer produced no evidence: {stderr.strip()[:300]}")


def observe_mobile(url: str, out: Path, evidence: dict) -> None:
    """A short touch-viewport look, merged into the desktop evidence as mobile-* steps."""

    mobile_dir = out / "mobile"
    try:
        observe(url, mobile_dir, "mobile", 12)
        mobile = json.loads((mobile_dir / "observations.json").read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - a missing mobile look is reported as unverified, not a crash
        evidence["mobileError"] = f"{type(error).__name__}: {str(error)[:200]}"
        return
    for step in mobile.get("steps", []):
        name = f"m-{step['screenshot']}"
        shutil.copyfile(mobile_dir / step["screenshot"], out / name)
        evidence["steps"].append({**step, "label": f"mobile-{step['label']}", "screenshot": name})
    evidence["mobileInputProbes"] = mobile.get("inputProbes") or {}
    evidence["consoleErrors"] = [*evidence.get("consoleErrors", []), *mobile.get("consoleErrors", [])][:20]
    if mobile.get("observerError"):
        evidence["mobileError"] = str(mobile["observerError"])[:200]


def observe_with_mobile(url: str, out: Path, viewport: str, seconds: int) -> dict:
    """The requested observation, plus the short touch-viewport look after a desktop run; returns the evidence."""

    observe(url, out, viewport, seconds)
    evidence = json.loads((out / "observations.json").read_text(encoding="utf-8"))
    if viewport == "desktop":
        observe_mobile(url, out, evidence)
        (out / "observations.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence


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
    blockers = invisible_blockers(evidence)
    if blockers:
        failing.extend({**item, "verdict": "fail", "reason": "; ".join(blockers)[:400]}
                       for item in items if item["id"] == "input-reaches-controls")
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


def invisible_blockers(evidence: dict) -> list[str]:
    """Where pointer input lands on something invisible (transparent or hidden) instead of the control or scene."""

    found = []
    for viewport, probes in (("desktop", evidence.get("inputProbes") or {}),
                             ("mobile", evidence.get("mobileInputProbes") or {})):
        for name in ("primary", "canvasInitial", "canvasRunning"):
            entries = probes.get(name) or []
            for point in [entries] if isinstance(entries, dict) else entries:
                if not point.get("reaches", True) and point.get("invisible"):
                    target = "the main action" if name == "primary" else "the scene"
                    found.append(f"{viewport} {name}: input at ({point['x']},{point['y']}) for {target} lands on "
                                 f"invisible <{point.get('by')}> {point.get('text', '')!r}")
    return found


def settle_input_items(results: list[dict], evidence: dict) -> list[dict]:
    """The input-reach item is decided from the probes alone; no model reads it."""

    blockers = invisible_blockers(evidence)
    probed = bool(evidence.get("inputProbes"))
    settled = []
    for result in results:
        if result["id"] == "input-reaches-controls":
            if blockers:
                result = {**result, "verdict": "fail", "reason": "; ".join(blockers)[:400]}
            elif probed:
                result = {**result, "verdict": "pass", "reason": "no invisible element sat over the probed controls or scene"}
            else:
                result = {**result, "verdict": "unobserved", "reason": "input was not probed"}
        settled.append(result)
    return settled


def find_dist(project: Path) -> Path | None:
    for candidate in (project / "dist", project / "build", project / "out", project):
        if (candidate / "index.html").is_file():
            return candidate
    return None
