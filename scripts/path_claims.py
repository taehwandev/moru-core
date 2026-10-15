"""Claim project paths before editing them, and record which session edited what.

Owner: the per-project path claim store under ``<project>/.moru/claims/`` and
the live-web edit log ``<project>/.moru/live-web/edits.jsonl``. The ``check``
subcommand delegates to ``live_web_checks``.
Allowed imports: the standard library and the sibling ``live_web_checks``
only, so any agent runtime or hook can run it without the Moru lifecycle.
Forbidden imports: the workflow route, the agent lifecycle and hook installers;
a claim is a courtesy lock between agents, never an authority decision.
Callers/tests: agents following the ``live-web`` card, and an optional Claude
Code PostToolUse hook running ``record --from-hook``; coverage lives in
``tests/test_path_claims.py``.
Verification: run that module, then ``claim``/``status``/``release`` by hand
against a scratch project.

A claim file is ``<sha1(project-relative path)>.json`` holding ``path``,
``holder``, ``since`` and ``expires``. A claim on a directory covers everything
below it, so a claim overlapping another holder's ancestor or descendant is a
conflict. Expired claims are removed whenever the store is read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import live_web_checks

CONFLICT_EXIT = 3
DEFAULT_TTL_SECONDS = 1800
WAIT_INTERVAL_SECONDS = 1.0
HOOK_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})


class PathError(ValueError):
    """A path that does not name something inside the project."""


def _now() -> float:
    return time.time()


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def _epoch(text: str) -> float:
    return datetime.fromisoformat(text).timestamp()


def default_holder() -> str:
    return os.environ.get("MORU_SESSION_ID") or f"pid:{os.getppid()}"


def claims_dir(project: Path) -> Path:
    return project / ".moru" / "claims"


def edits_log(project: Path) -> Path:
    return project / ".moru" / "live-web" / "edits.jsonl"


def normalize(project: Path, raw: str) -> str:
    """Return ``raw`` as a project-relative POSIX path; ``.`` is the whole project."""
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = project / candidate
    resolved = Path(os.path.normpath(str(candidate.resolve())))
    try:
        relative = resolved.relative_to(project)
    except ValueError:
        raise PathError(f"outside the project: {raw}") from None
    return relative.as_posix() or "."


def overlaps(first: str, second: str) -> bool:
    if first == "." or second == "." or first == second:
        return True
    return second.startswith(first + "/") or first.startswith(second + "/")


def _claim_file(project: Path, path: str) -> Path:
    return claims_dir(project) / (hashlib.sha1(path.encode("utf-8")).hexdigest() + ".json")


def active_claims(project: Path) -> list[dict]:
    """Read every unexpired claim, removing expired or unreadable ones."""
    directory = claims_dir(project)
    if not directory.is_dir():
        return []
    claims = []
    for entry in sorted(directory.glob("*.json")):
        try:
            claim = json.loads(entry.read_text(encoding="utf-8"))
            expired = _epoch(claim["expires"]) <= _now()
        except (OSError, ValueError, KeyError, TypeError):
            expired = True
        if expired:
            entry.unlink(missing_ok=True)
            continue
        claims.append(claim)
    return claims


def conflicts(project: Path, paths: Iterable[str], holder: str) -> list[dict]:
    wanted = list(paths)
    return [
        claim
        for claim in active_claims(project)
        if claim.get("holder") != holder and any(overlaps(claim["path"], p) for p in wanted)
    ]


def _write_claim(project: Path, path: str, holder: str, ttl: int) -> bool:
    """Create or renew ``path`` for ``holder``; False when another holder owns it."""
    target = _claim_file(project, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    body = {"path": path, "holder": holder, "since": _iso(now), "expires": _iso(now + ttl)}
    try:
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if current.get("holder") != holder:
            return False
        body["since"] = current.get("since", body["since"])
        temporary = target.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(body), encoding="utf-8")
        os.replace(temporary, target)
        return True
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(body, handle)
    return True


def try_claim(project: Path, paths: list[str], holder: str, ttl: int) -> list[dict]:
    """Claim all ``paths`` or none; return the blocking claims on failure."""
    blocking = conflicts(project, paths, holder)
    if blocking:
        return blocking
    started = _iso(_now())
    written = []
    for path in paths:
        if not _write_claim(project, path, holder, ttl):
            release(project, written, holder)
            return conflicts(project, [path], holder) or [{"path": path, "holder": "?", "since": "?"}]
        written.append(path)
    # A concurrent claimer may have taken an overlapping path between the scan
    # and the create. The later (since, holder) backs off, so one side keeps it.
    lost = [
        claim
        for claim in conflicts(project, paths, holder)
        if (claim.get("since", ""), claim.get("holder", "")) < (started, holder)
    ]
    if lost:
        release(project, written, holder)
    return lost


def release(project: Path, paths: Optional[list[str]], holder: str) -> list[dict]:
    """Remove ``holder``'s claims (all of them when ``paths`` is None)."""
    refused = []
    for claim in active_claims(project):
        if paths is not None and claim["path"] not in paths:
            continue
        if claim.get("holder") != holder:
            if paths is not None:
                refused.append(claim)
            continue
        _claim_file(project, claim["path"]).unlink(missing_ok=True)
    return refused


def record(project: Path, files: Iterable[str], holder: str) -> dict:
    entry = {"session": holder, "files": list(files), "time": _iso(_now())}
    log = edits_log(project)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry


def record_from_hook(stream, project: Optional[Path], holder: str) -> None:
    """Record one Claude Code PostToolUse edit; never raise, so a hook never blocks."""
    try:
        payload = json.loads(stream.read() or "{}")
        if not isinstance(payload, dict) or payload.get("tool_name") not in HOOK_EDIT_TOOLS:
            return
        tool_input = payload.get("tool_input") or {}
        raw = tool_input.get("file_path") or tool_input.get("notebook_path")
        root = project or Path(payload.get("cwd") or os.getcwd())
        if not raw:
            return
        root = root.resolve()
        record(root, [normalize(root, raw)], holder)
    except Exception:  # noqa: BLE001 -- the hook must stay non-blocking
        return


def _describe(claim: dict) -> str:
    return f"held by {claim.get('holder')} since {claim.get('since')}: {claim.get('path')}"


def _cmd_claim(project: Path, args: argparse.Namespace) -> int:
    paths = sorted({normalize(project, raw) for raw in args.path})
    deadline = _now() + max(args.wait, 0)
    while True:
        blocking = try_claim(project, paths, args.holder, args.ttl)
        if not blocking:
            for path in paths:
                print(f"claimed by {args.holder}: {path}")
            return 0
        if _now() >= deadline:
            for claim in blocking:
                print(_describe(claim))
            return CONFLICT_EXIT
        time.sleep(min(WAIT_INTERVAL_SECONDS, max(deadline - _now(), 0.05)))


def _cmd_release(project: Path, args: argparse.Namespace) -> int:
    paths = None if args.all else sorted({normalize(project, raw) for raw in args.path or []})
    if paths == []:
        print("release needs --path or --all", file=sys.stderr)
        return 2
    refused = release(project, paths, args.holder)
    for claim in refused:
        print(_describe(claim))
    return CONFLICT_EXIT if refused else 0


def _cmd_status(project: Path, args: argparse.Namespace) -> int:
    claims = sorted(active_claims(project), key=lambda claim: claim["path"])
    if args.json:
        print(json.dumps(claims, indent=2))
    elif not claims:
        print("no active claims")
    else:
        for claim in claims:
            print(f"{_describe(claim)} (expires {claim.get('expires')})")
    return 0


def _cmd_record(project: Optional[Path], args: argparse.Namespace) -> int:
    if args.from_hook:
        record_from_hook(sys.stdin, project, args.holder)
        return 0
    if project is None or not args.files:
        print("record needs --project and --files, or --from-hook", file=sys.stderr)
        return 2
    print(json.dumps(record(project, [normalize(project, raw) for raw in args.files], args.holder)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("claim", "release", "status", "record", "check"):
        sub = commands.add_parser(name)
        sub.add_argument("--project", type=Path, required=name != "record")
        sub.add_argument("--holder", default=None)
    claim, release_cmd, status, record_cmd = (commands.choices[n] for n in ("claim", "release", "status", "record"))
    claim.add_argument("--path", action="append", required=True)
    claim.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS)
    claim.add_argument("--wait", type=float, default=0.0)
    targets = release_cmd.add_mutually_exclusive_group(required=True)
    targets.add_argument("--path", action="append")
    targets.add_argument("--all", action="store_true")
    status.add_argument("--json", action="store_true")
    record_cmd.add_argument("--files", nargs="+")
    record_cmd.add_argument("--from-hook", action="store_true")
    live_web_checks.add_arguments(commands.choices["check"])
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    args.holder = args.holder or default_holder()
    project = args.project.expanduser().resolve() if args.project else None
    handlers = {"claim": _cmd_claim, "release": _cmd_release, "status": _cmd_status, "record": _cmd_record}
    handlers["check"] = live_web_checks.run
    try:
        return handlers[args.command](project, args)
    except PathError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
