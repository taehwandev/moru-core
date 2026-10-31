#!/usr/bin/env python3
"""Pack or install an explicitly selected offline native runtime bundle.

Owner: portable artifact CLI. Allowed: stdlib and support.native_bundle.
Forbidden: network, compiler and global setup. Tests: test_native_bundle.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from support.native_bundle import install_bundle, pack_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pack", "install"))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = (pack_bundle if args.command == "pack" else install_bundle)(args.root, args.bundle)
    except (OSError, ValueError) as error:
        print(f"native bundle failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
