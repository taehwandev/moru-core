"""Claim project paths before editing them, and record which session edited what.

Owner: the per-project path claim store under ``<project>/.moru/claims/`` and
the live-web edit log ``<project>/.moru/live-web/edits.jsonl``. The ``check``
subcommand delegates to ``live_web_checks``.
Allowed imports: the standard library, ``live_web_checks`` and the bounded
native probe transport, so hooks can run without the Moru lifecycle.
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
from support.native_probe_transport import NativeProbe

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
    return _active_claims(directory, _scan_claims(project, directory))


def _scan_claims(
    project: Path, directory: Path, *, status_json: Optional[bool] = None,
    conflict: Optional[dict] = None, release: Optional[dict] = None,
) -> Optional[dict]:
    if not directory.is_dir():
        return None
    return NativeProbe.request("--completion-probe", "path-claim-scan", {
        "project": str(project), "digit_limit": getattr(sys, "get_int_max_str_digits", lambda: 0)(),
        "status_json": status_json, "conflict": conflict, "release": release,
    })


def _active_claims(directory: Path, result: Optional[dict]) -> list[dict]:
    rows = result.get("rows") if result is not None else None
    if isinstance(rows, list) and all(_valid_scan_row(row) for row in rows):
        claims = []
        for name, expiry, raw in rows:
            # Recheck deletion candidates in case a concurrent writer renewed
            # or replaced a claim after Rust read it.
            claim = json.loads(raw) if expiry is not None and expiry > _now() else _recheck_active(directory / name)
            if claim is not None:
                claims.append(claim)
        return claims
    if not directory.is_dir():
        return []
    return [claim for entry in sorted(directory.glob("*.json")) if (claim := _read_active(entry)) is not None]


def _valid_scan_row(row) -> bool:
    if not isinstance(row, list) or len(row) != 3:
        return False
    name, expiry, raw = row
    return (isinstance(name, str) and Path(name).name == name and name.endswith(".json")
            and ((expiry is None and raw is None) or (type(expiry) in (int, float) and isinstance(raw, str))))


def _read_active(entry: Path) -> Optional[dict]:
    try:
        claim = json.loads(entry.read_text(encoding="utf-8"))
        expired = _epoch(claim["expires"]) <= _now()
        if not expired:
            return claim
    except (OSError, ValueError, KeyError, TypeError):
        pass
    entry.unlink(missing_ok=True)
    return None


def _recheck_active(entry: Path) -> Optional[dict]:
    result = NativeProbe.request("--completion-probe", "path-claim-expire", {
        "project": str(entry.parents[2]), "name": entry.name, "now": _now(),
        "digit_limit": getattr(sys, "get_int_max_str_digits", lambda: 0)(),
    })
    if result is None:
        return _read_active(entry)
    if result.keys() == {"line"}:
        raw = result["line"]
        if raw is None:
            return None
        if isinstance(raw, str):
            return json.loads(raw)
    raise OSError("invalid native path claim expiry receipt")


def conflicts(project: Path, paths: Iterable[str], holder: str) -> list[dict]:
    return _find_conflicts(project, paths, holder)


def _find_conflicts(
    project: Path, paths: Iterable[str], holder: str, *, started: Optional[str] = None,
) -> list[dict]:
    wanted = list(paths)
    directory = claims_dir(project)
    query = None
    if type(holder) is str and all(type(path) is str for path in wanted):
        query = {"paths": wanted, "holder": holder, "started": started}
    result = _scan_claims(project, directory, conflict=query)
    key = "conflicts" if started is None else "arbitration"
    matches = _fresh_projection(result, key, "matches")
    if isinstance(matches, list) and all(isinstance(raw, str) for raw in matches):
        return [json.loads(raw) for raw in matches]
    blocking = [
        claim
        for claim in _active_claims(directory, result)
        if claim.get("holder") != holder and any(overlaps(claim["path"], p) for p in wanted)
    ]
    if started is None:
        return blocking
    return [claim for claim in blocking if (claim.get("since", ""), claim.get("holder", "")) < (started, holder)]


def _fresh_projection(result: Optional[dict], name: str, field: str):
    projection = result.get(name) if result is not None else None
    if not isinstance(projection, dict) or projection.keys() != {field, "earliest"}:
        return None
    earliest = projection["earliest"]
    if earliest is None or (type(earliest) in (int, float) and earliest > _now()):
        return projection[field]
    return None


def _write_claim(project: Path, path: str, holder: str, ttl: int) -> bool:
    """Create or renew ``path`` for ``holder``; False when another holder owns it."""
    now = _now()
    body = {"path": path, "holder": holder}
    result = NativeProbe.request("--completion-probe", "path-claim-write", {
        "project": str(project), "entry": body, "now": now, "ttl": ttl,
        "digit_limit": getattr(sys, "get_int_max_str_digits", lambda: 0)(),
    })
    if result is not None:
        if result.keys() == {"written"} and type(result["written"]) is bool:
            return result["written"]
        raise OSError("invalid native path claim write receipt")
    body.update(since=_iso(now), expires=_iso(now + ttl))
    target = _claim_file(project, path)
    target.parent.mkdir(parents=True, exist_ok=True)
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
    written, blocked = _write_claims(project, paths, holder, ttl)
    if blocked is not None:
        release(project, written, holder)
        return conflicts(project, [blocked], holder) or [{"path": blocked, "holder": "?", "since": "?"}]
    # A concurrent claimer may have taken an overlapping path between the scan
    # and the create. The later (since, holder) backs off, so one side keeps it.
    lost = _find_conflicts(project, paths, holder, started=started)
    if lost:
        release(project, written, holder)
    return lost


def _write_claims(project: Path, paths: list[str], holder: str, ttl: int) -> tuple[list[str], Optional[str]]:
    written = []
    remaining = paths
    if type(paths) is list and 2 <= len(paths) <= 128 and all(type(path) is str for path in paths):
        result = NativeProbe.request("--completion-probe", "path-claim-write-batch", {
            "project": str(project), "paths": paths, "holder": holder, "now": _now(), "ttl": ttl,
            "digit_limit": getattr(sys, "get_int_max_str_digits", lambda: 0)(),
        })
        if result is not None:
            count, blocked = result.get("written"), result.get("blocked")
            if (result.keys() != {"written", "blocked"} or type(count) is not int or type(blocked) is not bool
                    or not 0 <= count <= len(paths) or (blocked and count == len(paths))):
                raise OSError("invalid native path claim batch receipt")
            written = paths[:count]
            if blocked:
                return written, paths[count]
            remaining = paths[count:]
    for path in remaining:
        if not _write_claim(project, path, holder, ttl):
            return written, path
        written.append(path)
    return written, None


def release(project: Path, paths: Optional[list[str]], holder: str) -> list[dict]:
    """Remove ``holder``'s claims (all of them when ``paths`` is None)."""
    directory = claims_dir(project)
    ordinary_paths = paths is None or (type(paths) is list and all(type(path) is str for path in paths))
    query = {"paths": paths, "holder": holder} if type(holder) is str and ordinary_paths else None
    scan = _scan_claims(project, directory, release=query)
    plan = _fresh_projection(scan, "release", "plan")
    if isinstance(plan, dict) and plan.keys() == {"owned", "refused"} and all(
        isinstance(values, list) and all(isinstance(value, str) for value in values) for values in plan.values()
    ):
        refused = [json.loads(raw) for raw in plan["refused"]]
        owned = plan["owned"]
        if owned and not _native_release(project, owned, holder):
            for path in owned:
                _claim_file(project, path).unlink(missing_ok=True)
        return refused
    claims = _active_claims(directory, scan)
    if type(holder) is str and ordinary_paths and all(type(claim.get("path")) is str for claim in claims):
        selected = [claim for claim in claims if paths is None or claim["path"] in paths]
        owned = [claim["path"] for claim in selected if claim.get("holder") == holder]
        if owned and _native_release(project, owned, holder):
            return [claim for claim in selected if claim.get("holder") != holder] if paths is not None else []
    refused = []
    for claim in claims:
        if paths is not None and claim["path"] not in paths:
            continue
        if claim.get("holder") != holder:
            if paths is not None:
                refused.append(claim)
            continue
        _claim_file(project, claim["path"]).unlink(missing_ok=True)
    return refused


def _native_release(project: Path, paths: list[str], holder: str) -> bool:
    result = NativeProbe.request("--completion-probe", "path-claim-release", {
        "project": str(project), "paths": paths, "holder": holder,
        "digit_limit": getattr(sys, "get_int_max_str_digits", lambda: 0)(),
    })
    if result is None:
        return False
    if result.keys() == {"handled"} and result["handled"] is True:
        return True
    raise OSError("invalid native path claim release receipt")


def record(project: Path, files: Iterable[str], holder: str) -> dict:
    return _record(project, files, holder)[0]


def _record(project: Path, files: Iterable[str], holder: str, *, resolve_paths: bool = False) -> tuple[dict, str]:
    entry = {"session": holder, "files": list(files)}
    operation = "live-web-edit-record" if resolve_paths else "live-web-edit-append"
    result = NativeProbe.request("--completion-probe", operation, {
        "project": str(project), "entry": entry,
    })
    if resolve_paths:
        if result is None:
            return _record(project, [normalize(project, raw) for raw in entry["files"]], holder)
        if result.keys() == {"outside"} and isinstance(result["outside"], str):
            raise PathError(f"outside the project: {result['outside']}")
    if result is not None:
        if result.keys() == {"appended", "line"} and result["appended"] is True and isinstance(result["line"], str):
            return json.loads(result["line"]), result["line"]
        raise OSError("invalid native live-web edit append receipt")
    entry["time"] = _iso(_now())
    log = edits_log(project)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        line = json.dumps(entry)
        handle.write(line + "\n")
    return entry, line


def record_from_hook(stream, project: Optional[Path], holder: str) -> None:
    """Record one Claude Code PostToolUse edit; never raise, so a hook never blocks."""
    try:
        raw_payload = stream.read() or "{}"
        result = NativeProbe.request("--completion-probe", "live-web-edit-hook", {
            "payload": raw_payload, "project": str(project) if project else None, "holder": holder,
            "digit_limit": getattr(sys, "get_int_max_str_digits", lambda: 0)(),
        })
        if result is not None:
            return
        payload = json.loads(raw_payload)
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
    paths = _claim_paths(project, args.path)
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
    paths = None if args.all else _claim_paths(project, args.path or [])
    if paths == []:
        print("release needs --path or --all", file=sys.stderr)
        return 2
    refused = release(project, paths, args.holder)
    for claim in refused:
        print(_describe(claim))
    return CONFLICT_EXIT if refused else 0


def _claim_paths(project: Path, raw_paths: list[str]) -> list[str]:
    result = NativeProbe.request("--completion-probe", "path-claim-arguments", {
        "project": str(project), "paths": raw_paths,
    })
    if result is not None:
        if result.keys() == {"outside"} and isinstance(result["outside"], str):
            raise PathError(f"outside the project: {result['outside']}")
        paths = result.get("paths")
        if isinstance(paths, list) and all(isinstance(path, str) for path in paths):
            return paths
    return sorted({normalize(project, raw) for raw in raw_paths})


def _cmd_status(project: Path, args: argparse.Namespace) -> int:
    directory = claims_dir(project)
    result = _scan_claims(project, directory, status_json=args.json)
    output = _fresh_projection(result, "status", "output")
    if isinstance(output, str):
        print(output)
        return 0
    claims = sorted(_active_claims(directory, result), key=lambda claim: claim["path"])
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
    _, line = _record(project, args.files, args.holder, resolve_paths=True)
    print(line)
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
