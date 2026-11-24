"""Judge a mutation by the test run's exit code, never by reading its output.

Owner: the hand-run verification boundary -- proving a test can fail.
Allowed imports: the standard library only. A tool that decides whether a check
is trustworthy must not depend on the code it is checking.
Forbidden imports for the judge: the workflow route, the agent lifecycle, and
anything under ``scripts`` that a mutation could break. The direct CLI may
verify a source-bound Rust artifact before starting any mutation.
Callers/tests: run by hand; coverage lives in ``tests/test_mutation_check.py``.
Verification: run that module, then this script against a spec whose mutants are
known dead and known alive.

A green test proves something works, not that the thing it names works. The
separation is a mutant: break the code on purpose and watch the test fail. The
technique is only as good as the judgement, and judgement by reading output is
where it fails.

Counting ``FAIL:`` lines calls a dead mutant a survivor, because a mutant that
breaks the module -- a SyntaxError, a RecursionError, an import error -- prints
a traceback and no ``FAIL:`` line at all. Reading ``$?`` after any other command
does the same for a different reason. Both happened in one session, in both
directions.

The exit code answers it. Non-zero means the suite could not pass, whatever the
reason, which is exactly what "the test would have caught this" means.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

KILLED = "KILLED"
SURVIVED = "SURVIVED"
UNAPPLIED = "NOT APPLIED"


def load_spec(path: Path) -> list[dict[str, Any]]:
    """Read a mutant list, refusing anything that is not one."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("spec must be a list of mutants")
    for index, mutant in enumerate(payload):
        if not isinstance(mutant, dict):
            raise ValueError(f"mutant {index} is not an object")
        for field in ("label", "file", "old", "new"):
            if not isinstance(mutant.get(field), str) or not mutant[field]:
                raise ValueError(f"mutant {index} is missing {field}")
    return payload


def apply_mutant(path: Path, old: str, new: str) -> str | None:
    """Replace exactly one occurrence, or refuse and change nothing.

    A mutation that matched twice would test two things at once, and one that
    matched nothing would report SURVIVED for a mutant that never existed --
    the most expensive false negative this tool can produce.
    """

    original = path.read_text(encoding="utf-8")
    mutated = _replacement(original, old, new)
    if mutated is None:
        return None
    path.write_text(mutated, encoding="utf-8")
    return original


def _replacement(source: str, old: str, new: str) -> str | None:
    return source.replace(old, new) if source.count(old) == 1 else None


def run_check(command: list[str], cwd: Path) -> int:
    """Return the exit code. Nothing here reads stdout or stderr."""

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode


def judge(mutant: dict[str, Any], command: list[str], root: Path) -> str:
    path = root / mutant["file"]
    original = path.read_bytes()
    source = original.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    mutated = _replacement(source, mutant["old"], mutant["new"])
    if mutated is None:
        return UNAPPLIED
    path.write_text(mutated, encoding="utf-8")
    try:
        return KILLED if run_check(command, root) != 0 else SURVIVED
    finally:
        # Restoration is not optional. A mutant left in the tree is a defect
        # this tool introduced, so it is written back even when the run above
        # raised rather than returned.
        path.write_bytes(original)


def check_command(test: str) -> list[str]:
    return [sys.executable, "-m", "unittest", test]


def _exec_native(args) -> None:
    if os.environ.pop("MORU_MUTATION_REFERENCE_REPLAY", "") == "1":
        return
    if os.environ.get("MORU_LAUNCHER_BACKEND") == "python" or sys.stdout.encoding != "utf-8":
        return
    try:
        from support.native_launcher_install import artifact_plan

        script = Path(__file__).resolve()
        plan = artifact_plan(script.parent.parent, script)
        if plan is not None:
            launcher = str(plan["source"])
            os.execv(launcher, [
                launcher, str(script), "--mutation-check", sys.executable,
                str(args.spec), str(args.root), args.test, *sys.argv[1:],
            ])
    except (OSError, ImportError, ValueError):
        return


def main(argv: list[str] | None = None, *, display_python: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--test", required=True, help="unittest selector to run")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)

    if __name__ == "__main__" and argv is None:
        _exec_native(args)

    try:
        mutants = load_spec(args.spec)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"unusable spec: {error}")
        return 2

    command = check_command(args.test)
    shown = [display_python, *command[1:]] if display_python is not None else command
    print(f"check: {' '.join(shown)}")
    verdicts = []
    for mutant in mutants:
        verdict = judge(mutant, command, args.root)
        verdicts.append(verdict)
        print(f"{verdict:>11}  {mutant['label']}")

    survived = verdicts.count(SURVIVED)
    unapplied = verdicts.count(UNAPPLIED)
    print(f"{verdicts.count(KILLED)}/{len(verdicts)} killed")
    if unapplied:
        print(f"{unapplied} mutant(s) never applied: the `old` text was not found exactly once")
    return 1 if survived or unapplied else 0


if __name__ == "__main__":
    raise SystemExit(main())
