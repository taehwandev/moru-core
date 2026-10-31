"""Generic filesystem facts probe for a project directory.

Owner: ProjectFacts is the single public owner of probing which requested
instruction and marker names exist directly under a directory.

Import boundary: only stdlib dataclasses, pathlib.Path and typing are used.
Only supplied paths' filesystem metadata is read; no repository content,
registry, account, network or process access.

Forbidden: authority, scoring, ranking, recursion, traversal, registry
policy, caching or persistent storage, name normalization, path resolution,
case folding, scandir substitution, and exception suppression. Existence is
decided solely by Path.exists, so symlink, case-insensitive filesystem and
OSError semantics are inherited unchanged.

Callers: any generic adapter (discovery scanning, candidate construction)
that needs the facts for one directory. A caller may reuse one returned
object instead of probing the same names twice; ProjectFacts itself never
reuses results, so every probe() reads the filesystem afresh.

Tests: exercise through probe() against temporary directories, covering
order, duplicates, missing names, symlinks, change between probes, and
propagation of OSError from Path.exists.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Tuple


@dataclass(frozen=True)
class ProjectFacts:
    instruction_files: Tuple[str, ...] = ()
    markers: Tuple[str, ...] = ()

    @property
    def present(self) -> bool:
        return bool(self.instruction_files or self.markers)

    @classmethod
    def probe(
        cls,
        path: Path,
        instruction_names: Sequence[str],
        marker_names: Sequence[str],
    ) -> "ProjectFacts":
        instructions = tuple(n for n in instruction_names if (path / n).exists())
        markers = tuple(n for n in marker_names if (path / n).exists())
        return cls(instruction_files=instructions, markers=markers)
