#!/usr/bin/env python3
"""Live smoke harness for a real Figma API handoff pipeline.

This is not an unittest target (the filename does not start with ``test``) and
requires network access plus a token. It returns SKIP (exit 0) when the token
environment variable is missing so offline CI remains independent.

Checks:
1. the tool exits successfully
2. design-summary.json passes figma_validate
3. frame downloads are valid PNGs at the requested scale
4. vectors export as SVG and image fills as PNG
5. image-fill recovery meets the configured threshold
6. the fidelity coverage report is produced

Usage: python3 live_smoke.py --url <frame-url> [--scale 3]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from figma_coverage import coverage_report  # noqa: E402
from figma_summary_validate import _probe, _validate_summary_reference  # noqa: E402
from figma_validation_report import format_report  # noqa: E402

TOOL = Path(__file__).parent / "figma-handoff.py"
IMAGE_FILL_MIN_PCT = 100  # Image fills must be fully recovered as PNG files.


def _png_size(path: Path) -> tuple[int, int] | None:
    with open(path, "rb") as handle:
        head = handle.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def _frame_scale_failures(summary: dict, bundle_root: Path, scale: float) -> list[str]:
    failures: list[str] = []
    for screen in summary.get("screens", []) or []:
        image_path = screen.get("imagePath")
        width = screen.get("width")
        height = screen.get("height")
        if not image_path or not str(image_path).endswith(".png"):
            continue
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            failures.append(f"screen dimensions unavailable for scale check: {screen.get('id')}")
            continue
        size = _png_size(bundle_root / str(image_path))
        expected = (round(width * scale), round(height * scale))
        if size is None or any(abs(actual - target) > 1 for actual, target in zip(size, expected)):
            failures.append(f"frame scale mismatch for {screen.get('id')}: actual={size} expected={expected}")
    return failures


def _frame_probe(summary, bundle_root, scale, selection):
    if _probe is None or type(summary) is not dict:
        return None
    try:
        root = str(bundle_root.resolve(strict=True))
    except (OSError, RuntimeError):
        return None
    receipt = _probe("figma-smoke-frames", {
        "bundle_root": root, "screens": summary.get("screens", []), "scale": scale, **selection,
    }, __file__)
    if (type(receipt) is not dict or type(receipt.get("failures")) is not list
            or any(type(item) is not str for item in receipt["failures"])):
        return None
    return receipt


def _discovered_frames(summary, root, scale):
    receipt = _frame_probe(summary, root, scale, {"discover": True})
    if (receipt is None or set(receipt) != {"frames", "failures", "svg_count", "png_count"}
            or type(receipt["frames"]) is not list or len(receipt["frames"]) > 32000
            or any(type(receipt[k]) is not int or not 0 <= receipt[k] <= 32000 for k in ("svg_count", "png_count"))):
        return None
    previous = ""
    for name in receipt["frames"]:
        if (type(name) is not str or name <= previous or not name.startswith("frames/")
                or name.count("/") != 1 or not name.endswith(".png") or "\0" in name):
            return None
        previous = name
    return receipt


def _frame_failures(summary, bundle_root, frames, scale):
    if len(frames) <= 32000:
        names = [str(path.relative_to(bundle_root)) for path in frames]
        receipt = _frame_probe(summary, bundle_root, scale, {"frames": names})
        if receipt is not None and set(receipt) == {"failures"}:
            return receipt["failures"]
    return _frame_failures_reference(summary, bundle_root, frames, scale)


def _frame_failures_reference(summary, bundle_root, frames, scale):
    failures = [] if frames else ["no frame PNG downloaded"]
    for frame in frames:
        size = _png_size(frame)
        if not size:
            failures.append(f"invalid PNG: {frame.name}")
        elif size[0] <= 0 or size[1] <= 0:
            failures.append(f"empty PNG dimensions: {frame.name} {size}")
    failures.extend(_frame_scale_failures(summary, bundle_root, scale))
    return failures


def _layout_coverage_failures(coverage: dict) -> list[str]:
    if coverage["screens"] and coverage["layoutNodes"]["total"] == 0:
        return ["layout coverage is empty for a non-empty handoff"]
    return []


def _native_analysis(summary):
    if _probe is None or type(summary) is not dict:
        return None
    result = _probe("figma-smoke-analysis", summary, __file__)
    counts = ("screens", "layout_total", "image_fill_total", "image_fill_with_path")
    if (type(result) is not dict or set(result) != {"problems", "report", *counts}
            or type(result["problems"]) is not list or any(type(item) is not str for item in result["problems"])
            or type(result["report"]) is not str or any(type(result[key]) is not int or result[key] < 0 for key in counts)
            or result["image_fill_with_path"] > result["image_fill_total"]):
        return None
    return result


def _native_verdict(summary, quick):
    if _probe is None or type(summary) is not dict:
        return None
    result = _probe("figma-smoke-verdict", {"summary": summary, "quick": quick}, __file__)
    if (type(result) is not dict or set(result) != {"problems", "report", "coverage_failures"}
            or type(result["report"]) is not str
            or any(type(result[key]) is not list or any(type(item) is not str for item in result[key])
                   for key in ("problems", "coverage_failures"))):
        return None
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="figma-handoff live smoke harness")
    parser.add_argument("--url", default=os.environ.get("FIGMA_SMOKE_URL"))
    parser.add_argument("--scale", type=float, default=3.0)
    parser.add_argument("--token-env", default="FIGMA_TOKEN")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Schema + frame PNG + layout coverage only; skip asset export (fast on large flows).",
    )
    args = parser.parse_args()

    if not os.environ.get(args.token_env):
        print(f"SKIP: {args.token_env} is not set — live smoke needs network + token.")
        return 0
    if not args.url:
        parser.error("--url or FIGMA_SMOKE_URL is required when a token is available")

    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="figma-smoke-"))
    try:
        command = [
            sys.executable, str(TOOL),
            "--url", args.url,
            "--name", "smoke",
            "--out", str(tmp),
            "--scale", str(args.scale),
            "--token-env", args.token_env,
        ]
        if not args.quick:
            command.append("--export-assets")
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
        print(result.stdout.strip()[-600:])
        if result.returncode != 0:
            print(result.stderr.strip()[-800:], file=sys.stderr)
            print("FAIL: tool exited non-zero")
            return 1

        out = tmp / "smoke"
        summary = json.loads((out / "summary" / "design-summary.json").read_text(encoding="utf-8"))

        verdict = _native_verdict(summary, args.quick)
        problems = _validate_summary_reference(summary) if verdict is None else verdict["problems"]
        if problems:
            failures.append(f"schema violations: {problems}")

        discovered = _discovered_frames(summary, out, args.scale)
        if discovered is None:
            frames = sorted((out / "frames").glob("*.png"))
            failures.extend(_frame_failures_reference(summary, out, frames, args.scale))
            assets = out / "assets"
            svg_count = sum(1 for _ in assets.glob("*.svg")) if assets.exists() else 0
            png_count = sum(1 for _ in assets.glob("*.png")) if assets.exists() else 0
        else:
            frames = [out / name for name in discovered["frames"]]
            failures.extend(discovered["failures"])
            svg_count, png_count = discovered["svg_count"], discovered["png_count"]
        if not args.quick and not svg_count:
            failures.append("no vector SVG assets exported (asset split broken?)")

        if verdict is None:
            cov = coverage_report(summary)
            failures.extend(_layout_coverage_failures(cov))
            asset = cov["assets"]
            if not args.quick and asset["imageFillTotal"]:
                pct = asset["imageFillWithPath"] * 100 // asset["imageFillTotal"]
                if pct < IMAGE_FILL_MIN_PCT:
                    failures.append(
                        f"image-fill recovery {asset['imageFillWithPath']}/{asset['imageFillTotal']} "
                        f"({pct}%) < {IMAGE_FILL_MIN_PCT}%"
                    )
            report = format_report(problems, cov)
        else:
            failures.extend(verdict["coverage_failures"])
            report = verdict["report"]
        print(report)
        print(f"frames={len(frames)} (for example: {_png_size(frames[0]) if frames else None}) "
              f"assets: svg={svg_count} png={png_count}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("LIVE SMOKE FAILURES:")
        for failure in failures:
            print(f" - {failure}")
        return 1
    print("LIVE SMOKE PASS ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
