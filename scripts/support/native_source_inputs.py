"""Shared source receipt for native artifacts and their pretool contract."""
from __future__ import annotations

import hashlib
from pathlib import Path


def source_inputs(root: Path) -> list[Path]:
    package = root / "native/checkout-identity"
    generator = package / "pretool_contract.py"
    files = [package / "Cargo.toml", package / "Cargo.lock", *sorted((package / "src").rglob("*.rs"))]
    if not generator.is_file():
        return files  # Older artifacts retain their original receipt schema.
    sources, _directories = pretool_contract(root)
    return sorted({*files, generator, package / "build.rs",
                   root / "scripts/support/native_source_inputs.py",
                   *(root / relative for relative in sources)})


def pretool_contract(root):
    """Bind all runtime Python sources without executing candidate code.

    A full bounded code snapshot also covers lazy imports called at module
    initialization, and avoids treating an incomplete import graph as proof.
    Runtime state under .moru and developer tests are outside this contract.
    """
    scripts = root / "scripts"
    sources, directories = {}, {"scripts"}
    for path in scripts.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in path.relative_to(scripts).parts:
            continue
        if path.is_dir():
            directories.add(relative)
            continue
        if path.suffix != ".py":
            continue
        raw = path.read_bytes()
        sources[relative] = (hashlib.sha256(raw).digest(), len(raw))
    return dict(sorted(sources.items())), sorted(directories)
