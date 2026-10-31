"""Generic child-directory listing helper.

Owner: this module only provides `child_directories`; the parent owns the
adapter that calls it, the tests, the baseline/benchmark, docs and lifecycle.
Imports: standard library only (os, pathlib). No repository, config, account,
network or VCS access.
Forbidden: caches or persistent state, resolving paths, skipping symlinks,
pruning project roots, and any traversal policy (BFS order, max_depth,
max_visited, marker checks). Those stay in the callers.
Callers/tests: callers pass the parent path and the names to skip; behaviour
is pinned by the parent's tests in tests/test_project_directory_scan.py.
"""

from __future__ import annotations

import os
from pathlib import Path


def child_directories(path: Path, skip_names: set[str]) -> list[Path]:
    """Return child directories of `path`, sorted stably by `name.lower()`.

    Names starting with '.' or listed in `skip_names` are dropped. Directory
    symlinks are followed and kept; dangling links and file links are
    excluded. An OSError while opening or iterating the parent yields [] (any
    partial results are discarded); an OSError from one entry's is_dir only
    skips that entry. Returned paths keep the caller's spelling of `path`.
    """
    accepted: list[str] = []
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                name = entry.name
                if name.startswith(".") or name in skip_names:
                    continue
                try:
                    if entry.is_dir(follow_symlinks=True):
                        accepted.append(name)
                except OSError:
                    continue
    except OSError:
        return []
    accepted.sort(key=str.lower)
    return [path / name for name in accepted]
