"""Move local Moru records to .moru while keeping old paths usable.

This migrates runtime records, not Git-tracked guidance that may live below
``.tao/skills``. It never removes the old directory: each moved entry gains a
relative compatibility symlink at its former path.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

MARKER = "state-ready"
IGNORED_STATE = "# Moru Core local runtime records\n/*\n"
PRUNE = {".git", "node_modules", ".gradle", "build", "dist", "Pods", ".next"}


def project_state_dirs(workspace: Path, max_depth: int = 6) -> list[Path]:
    """Find checkout/module state, including state in linked worktrees."""
    result: list[Path] = []
    for root, names, _ in os.walk(workspace, followlinks=False):
        path = Path(root)
        depth = len(path.relative_to(workspace).parts)
        if depth >= max_depth:
            names[:] = []
            continue
        names[:] = [name for name in names if name not in PRUNE]
        if path == workspace:
            # The workspace router is not a project, even if an old task left
            # a state directory beside its AGENTS.md.
            names[:] = [name for name in names if name != ".tao"]
        if path.name == ".tao":
            result.append(path)
            names[:] = [name for name in names if name == "worktrees"]
    return sorted(result, key=lambda path: (-len(path.parts), str(path)))


def tracked_top_level(parent: Path) -> set[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(parent), "ls-files", "-z", "--", ".tao"],
            check=True, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return set()
    names: set[str] = set()
    for item in result.stdout.decode("utf-8", errors="surrogateescape").split("\0"):
        parts = Path(item).parts
        if len(parts) > 1 and parts[0] == ".tao":
            names.add(parts[1])
    return names


def items_to_move(old: Path, new: Path, protected: set[str]) -> list[tuple[Path, Path]]:
    entries: list[tuple[Path, Path]] = []
    for source in old.iterdir():
        if source.name in protected or source.name == MARKER:
            continue
        target = new / source.name
        if source.is_symlink():
            if target.exists() and source.resolve() == target.resolve():
                continue
            raise RuntimeError(f"unexpected symlink: {source}")
        if target.exists() or target.is_symlink():
            raise RuntimeError(f"target collision: {target}")
        entries.append((source, target))
    return entries


def migrate_dir(old: Path, new: Path, *, protected: set[str], apply: bool,
                is_global: bool = False) -> int:
    entries = items_to_move(old, new, protected)
    if not apply:
        return len(entries)
    new.mkdir(exist_ok=True)
    for source, target in entries:
        source.rename(target)
        source.symlink_to(os.path.relpath(target, source.parent), target_is_directory=target.is_dir())
        if source.resolve() != target.resolve():
            raise RuntimeError(f"compatibility link failed: {source}")
    if not is_global:
        ignore = new / ".gitignore"
        if not ignore.exists():
            ignore.write_text(IGNORED_STATE, encoding="utf-8")
    (new / MARKER).touch(exist_ok=True)
    return len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--project", type=Path, help="Migrate one project state root")
    target.add_argument("--global-state", action="store_true", help="Migrate the user-local install state")
    parser.add_argument("--workspace", type=Path, default=Path.home() / "git",
                        help="Read-only workspace inventory when no target is selected")
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    if args.apply and not (args.project or args.global_state):
        parser.error("--apply requires one exact --project or --global-state target")
    if args.project:
        project = args.project.expanduser().resolve()
        old = project / ".tao"
        if not old.is_dir() or old.is_symlink():
            parser.error(f"project state directory is absent or already linked: {old}")
        pairs = [(old, project / ".moru", tracked_top_level(project))]
    elif args.global_state:
        old = home / ".tao"
        if not old.is_dir() or old.is_symlink():
            parser.error(f"global state directory is absent or already linked: {old}")
        pairs = [(old, home / ".moru", set())]
    else:
        workspace = args.workspace.expanduser().resolve()
        projects = project_state_dirs(workspace)
        pairs = [(old, old.parent / ".moru", tracked_top_level(old.parent)) for old in projects]
    # Find every collision before the first mutation. A rerun skips existing
    # compatibility links and migrates only entries created since the last run.
    counts = [len(items_to_move(old, new, protected)) for old, new, protected in pairs]
    if args.apply:
        for old, new, protected in pairs:
            migrate_dir(old, new, protected=protected, apply=True,
                        is_global=args.global_state)
    print(f"{'migrated' if args.apply else 'ready'}: {len(pairs)} state roots, "
          f"{sum(counts)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
