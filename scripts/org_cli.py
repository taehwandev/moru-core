"""`workflow org add|sync|status`: register and update organization guide checkouts.

Registration writes the user-local `~/.moru/orgs.json` that `org_binding.py`
reads. Cloning and fetching use the user's existing Git access; nothing here
stores credentials, and nothing runs on its own -- `start` never syncs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from org_binding import (
    ORG_ID,
    OrgBindingError,
    exclude_local_index,
    head_commit,
    is_clean,
    load_orgs,
    orgs_file,
    resolve_binding,
    validate_manifest,
)


def add_org_parser(subparsers: Any) -> None:
    org = subparsers.add_parser("org", help="Register, update or inspect organization guides.")
    actions = org.add_subparsers(dest="org_action", required=True)
    add = actions.add_parser("add", help="Clone or register a guide and map remotes to it.")
    add.add_argument("--id", required=True)
    add.add_argument("--remote", help="Guide repository to clone; omit to register an existing checkout.")
    add.add_argument("--root", type=Path, help="Checkout path (default ~/.moru/orgs/<id>).")
    add.add_argument("--match", action="append", default=[], help="Remote pattern such as github.com/acme/*.")
    sync = actions.add_parser("sync", help="Fast-forward guide checkouts from their remote.")
    sync.add_argument("--id", help="Only this guide (default: every registered guide).")
    status = actions.add_parser("status", help="Show registered guides and a project's binding.")
    status.add_argument("--project", type=Path)


def run_org(args: argparse.Namespace) -> int:
    try:
        if args.org_action == "add":
            return _add(args)
        if args.org_action == "sync":
            return _sync(args.id)
        return _status(args.project)
    except OrgBindingError as error:
        print(f"FAIL: {error}")
        return 2


def _add(args: argparse.Namespace) -> int:
    if not ORG_ID.match(args.id):
        print(f"FAIL: org id `{args.id}` must match {ORG_ID.pattern}")
        return 2
    root = (args.root or Path("~/.moru/orgs") / args.id).expanduser().resolve()
    if not root.exists():
        if not args.remote:
            print(f"FAIL: {root} does not exist; pass --remote to clone it")
            return 2
        cloned = _git(None, "clone", "--quiet", args.remote, str(root))
        if cloned.returncode != 0:
            print(f"FAIL: could not clone {args.remote}: {cloned.stderr.strip()}")
            return 2
    validate_manifest(root, args.id)
    exclude_local_index(root)
    orgs = [org for org in load_orgs() if org["id"] != args.id]
    orgs.append({"id": args.id, "root": str(root), "match": args.match})
    _write_orgs(orgs)
    print(f"Registered org `{args.id}` at {root} (commit {head_commit(root)[:12]}), match: {args.match or 'pin only'}")
    return 0


def _sync(org_id: str | None) -> int:
    orgs = [org for org in load_orgs() if org_id in (None, org["id"])]
    if not orgs:
        print(f"FAIL: no registered org{f' `{org_id}`' if org_id else 's'} in {orgs_file()}")
        return 2
    status = 0
    for org in orgs:
        root = Path(org["root"]).expanduser()
        before = head_commit(root)
        if not is_clean(root):
            print(f"FAIL: `{org['id']}` has uncommitted changes at {root}; not updated")
            status = 2
            continue
        fetched = _git(root, "fetch", "--quiet")
        if fetched.returncode != 0:
            # Offline or unreachable: the checkout is left exactly as it was.
            print(f"FAIL: `{org['id']}` could not be updated ({fetched.stderr.strip() or 'fetch failed'}); "
                  f"still at {before[:12]}")
            status = 2
            continue
        merged = _git(root, "merge", "--ff-only", "--quiet", "@{upstream}")
        if merged.returncode != 0:
            print(f"FAIL: `{org['id']}` cannot fast-forward: {merged.stderr.strip()}; still at {before[:12]}")
            status = 2
            continue
        after = head_commit(root)
        change = "unchanged" if after == before else f"{before[:12]} -> {after[:12]}"
        print(f"Synced `{org['id']}`: {change}")
    return status


def _status(project: Path | None) -> int:
    orgs = load_orgs()
    if not orgs:
        print(f"No organization guides registered ({orgs_file()}).")
    for org in orgs:
        root = Path(org["root"]).expanduser()
        state = "clean" if is_clean(root) else "uncommitted changes"
        print(f"- {org['id']}: {root} commit {head_commit(root)[:12] or 'unreadable'} ({state}); "
              f"match {org.get('match') or 'pin only'}")
    if project is not None:
        binding = resolve_binding(project.resolve())
        print(f"Project {project}: "
              + (f"bound to `{binding['id']}` by {binding['binding']}" if binding else "no organization guide"))
    return 0


def _write_orgs(orgs: list[dict[str, Any]]) -> None:
    path = orgs_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"orgs": orgs}, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _git(root: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    command = ["git", *(["-C", str(root)] if root else []), *args]
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return subprocess.CompletedProcess(command, 1, "", str(error))
