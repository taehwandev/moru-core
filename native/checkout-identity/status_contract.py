"""Generate immutable native status snippets from the canonical Python API.

Owner: developer status-contract generation. Allowed: stdlib and status/API owners.
Forbidden: state reads, lifecycle actions and runtime installation.
Callers/tests: build.rs; native status parity and bundle tests.
Verification: generated snapshots match Python's contract and validation.
"""
import argparse
import json
from pathlib import Path
import sys


def emit(output):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from agent_observability import API_VERSION
    from agent_os_api import api_contract_manifest, runtime_adapter_catalog

    values = {"API": api_contract_manifest(), "ADAPTERS": runtime_adapter_catalog()}
    lines = [f"pub(super) const VERSION: u32 = {API_VERSION};"]
    for name, value in values.items():
        snippet = json.dumps(value, ensure_ascii=False, sort_keys=True)
        lines.append(f"pub(super) const {name}: &str = {json.dumps(snippet, ensure_ascii=False)};")
    output.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", type=Path, required=True)
    emit(parser.parse_args().emit)
