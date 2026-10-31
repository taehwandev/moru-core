"""Embed a bounded runtime source snapshot; never import policy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def emit(output):
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "scripts"))
    from support.native_source_inputs import pretool_contract
    sources, directories = pretool_contract(root)
    rows = ["pub(super) const SOURCES: &[(&str, &[u8], u64)] = &["]
    rows.extend(f"({json.dumps(path, ensure_ascii=False)}, &{list(digest)}, {size})," for path, (digest, size) in sources.items())
    rows.append("];")
    rows.append("pub(super) const DIRECTORIES: &[&str] = &[")
    rows.extend(json.dumps(path, ensure_ascii=False) + "," for path in directories)
    rows.append("];")
    output.write_text("\n".join(rows) + "\n")
    print("cargo:rerun-if-changed=" + str(root / "scripts/support/native_source_inputs.py"))
    for path in (*sources, *directories):
        print("cargo:rerun-if-changed=" + str(root / path))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", type=Path, required=True)
    emit(parser.parse_args().emit)
