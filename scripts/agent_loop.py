#!/usr/bin/env python3
"""Opt into bounded attempts under an existing Moru writable run."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from agent_loop_state import LoopRun


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "status", "begin", "reserve", "check", "accept", "reject", "pause", "resume", "cancel"):
        command = commands.add_parser(name)
        command.add_argument("--project", type=Path, default=Path.cwd())
        command.add_argument("--run-id", help="exact existing run; never transfers ownership")
        if name == "start":
            command.add_argument("--objective", required=True)
            command.add_argument("--path", dest="owned", action="append", required=True)
            command.add_argument("--verifier-path", dest="verifiers", action="append", required=True)
            command.add_argument("--test-directory", default="tests")
            command.add_argument("--goal-pattern", required=True)
            command.add_argument("--regression-pattern", required=True)
            command.add_argument("--max-iterations", type=int, required=True)
            command.add_argument("--max-seconds", type=int, required=True)
            command.add_argument("--max-model-calls", type=int, required=True)
            command.add_argument("--direction", choices=("min", "max"))
            command.add_argument("--min-delta", type=float)
        elif name == "begin":
            command.add_argument("--hypothesis", required=True)
            command.add_argument("--calls", type=int, default=1)
        elif name == "reserve":
            command.add_argument("--calls", type=int, required=True)
    return parser


def _dispatch(loop: LoopRun, args) -> dict:
    if args.command == "start":
        if (args.direction is None) != (args.min_delta is None):
            raise ValueError("direction and min-delta must be declared together")
        config = {key: getattr(args, key) for key in
                  ("objective", "owned", "verifiers", "goal_pattern", "regression_pattern",
                   "max_iterations", "max_seconds", "max_model_calls")}
        config["directory"] = args.test_directory
        config["metric"] = ({"direction": args.direction, "min_delta": args.min_delta}
                            if args.direction else None)
        return loop.start(config)
    if args.command == "begin":
        return loop.begin(args.hypothesis, args.calls)
    if args.command == "reserve":
        return loop.reserve(args.calls)
    if args.command == "check":
        return loop.evaluate()
    if args.command in {"accept", "reject"}:
        return loop.resolve(args.command == "accept")
    return getattr(loop, args.command)()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        loop = LoopRun(args.project, args.run_id)
        with contextlib.redirect_stdout(sys.stderr):
            result = _dispatch(loop, args)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 4 if result["status"] == "exhausted" else 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"FAIL loop: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
