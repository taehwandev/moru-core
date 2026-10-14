"""Move pre-rename local runtime records from ``.tao`` into ``.moru``.

Runtime records move; Git-tracked files below the old directory (an older
project-local skill copy, for instance) are left in place and reported,
because removing them is a change to that repository. Links an earlier
migration left at the old paths are removed, and the old directory itself is
removed once nothing but those links and empty directories remain.

When both trees hold the same file, the newer copy is kept. Directories merge.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from support import legacy_names

STATE_DIR = ".moru"
IGNORED_STATE = "# Moru Core local runtime records\n/*\n"
PRUNE = {".git", "node_modules", ".gradle", "build", "dist", "Pods", ".next"}
# Written by the previous migration tool; it selects nothing any more.
READY_MARKER = "state-ready"


def legacy_state_dirs(workspace: Path, max_depth: int = 6) -> list[Path]:
    """Find old state trees, including those in linked worktrees, deepest first."""
    result: list[Path] = []
    for root, names, _ in os.walk(workspace, followlinks=False):
        path = Path(root)
        depth = len(path.relative_to(workspace).parts)
        if depth >= max_depth:
            names[:] = []
            continue
        names[:] = [name for name in names if name not in PRUNE]
        if path.name == legacy_names.STATE_DIR:
            result.append(path)
            names[:] = [name for name in names if name == "worktrees"]
    return sorted(result, key=lambda path: (-len(path.parts), str(path)))


def tracked_paths(old: Path) -> set[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(old.parent), "ls-files", "-z", "--", old.name],
            check=True, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {
        old.parent / item
        for item in result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
        if item
    }


def _holds_tracked(path: Path, tracked: set[Path]) -> bool:
    return any(item == path or path in item.parents for item in tracked)


def plan(old: Path, new: Path, tracked: set[Path]) -> list[tuple[str, Path, Path | None]]:
    """Ordered actions: ("move"|"replace"|"drop"|"unlink"|"keep", source, target)."""
    actions: list[tuple[str, Path, Path | None]] = []
    for source in sorted(old.iterdir()):
        target = new / source.name
        if source.is_symlink():
            actions.append(("unlink", source, None))
        elif _holds_tracked(source, tracked):
            if source.is_dir() and not (source in tracked):
                # Merge the untracked part of a directory that also holds tracked files.
                actions += plan(source, target, tracked)
            else:
                actions.append(("keep", source, None))
        elif source.name == READY_MARKER:
            actions.append(("drop", source, None))
        elif not (target.exists() or target.is_symlink()):
            actions.append(("move", source, target))
        elif source.is_dir() and target.is_dir() and not target.is_symlink():
            actions += plan(source, target, tracked)
        elif source.is_file() and target.is_file():
            newer = source.stat().st_mtime > target.stat().st_mtime
            actions.append(("replace" if newer else "drop", source, target))
        else:
            raise RuntimeError(f"cannot merge {source} into {target}")
    return actions


def apply_plan(old: Path, new: Path, actions, *, is_global: bool) -> list[Path]:
    new.mkdir(exist_ok=True)
    if not is_global and not (new / ".gitignore").exists():
        (new / ".gitignore").write_text(IGNORED_STATE, encoding="utf-8")
    kept: list[Path] = []
    for action, source, target in actions:
        if action == "unlink":
            source.unlink()
        elif action == "keep":
            kept.append(source)
        elif action == "move":
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
        elif action == "replace":
            source.replace(target)
        elif action == "drop":
            if source.is_dir() and not source.is_symlink():
                shutil.rmtree(source)
            else:
                source.unlink()
    _remove_empty_tree(old)
    return kept


def _remove_empty_tree(path: Path) -> None:
    if not path.is_dir() or path.is_symlink():
        return
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            _remove_empty_tree(child)
    # An untracked ignore file or Finder metadata is all a drained tree keeps.
    for name in (".gitignore", ".DS_Store"):
        leftover = path / name
        if leftover.is_file() and len(list(path.iterdir())) == 1:
            leftover.unlink()
    if not any(path.iterdir()):
        path.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--project", type=Path, help="Migrate one project or workspace state root")
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
        roots = [args.project.expanduser().resolve() / legacy_names.STATE_DIR]
    elif args.global_state:
        roots = [home / legacy_names.STATE_DIR]
    else:
        roots = legacy_state_dirs(args.workspace.expanduser().resolve())
    roots = [old for old in roots if old.exists() or old.is_symlink()]
    if args.project and not roots:
        parser.error("project has no pre-rename state directory")
    if args.global_state and not roots:
        parser.error("no pre-rename global state directory")
    # Plan everything before the first mutation, so a collision stops the run.
    plans = []
    for old in roots:
        if old.is_symlink():
            plans.append((old, None, [("unlink", old, None)]))
            continue
        new = old.parent / STATE_DIR
        plans.append((old, new, plan(old, new, set() if args.global_state else tracked_paths(old))))
    if not args.apply:
        for old, _new, actions in plans:
            counts: dict[str, int] = {}
            for action, *_ in actions:
                counts[action] = counts.get(action, 0) + 1
            print(f"{old}: " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "empty"))
        return 0
    for old, new, actions in plans:
        if new is None:
            old.unlink()
            print(f"{old}: removed link")
            continue
        kept = apply_plan(old, new, actions, is_global=args.global_state)
        state = "kept tracked files: " + ", ".join(str(p.relative_to(old.parent)) for p in kept) if kept else (
            "removed" if not old.exists() else "left non-empty")
        print(f"{old}: migrated; {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
