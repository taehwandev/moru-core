"""Build-only Unicode vocabulary for the native memory lexical owner.

Owner: memory term contract. Allowed: stdlib. Forbidden: runtime policy/store
imports. Caller: pretool_contract.py. Verification: source/native term corpus.
"""
import json
from pathlib import Path
import unicodedata


def emit(output):
    ranges, folds, lower, cased, ignored, spaces, start = [], [], [], [], [], [], None
    for point in range(0x110000):
        char = chr(point)
        enabled = char.isalnum() or char == "_"
        if enabled and start is None:
            start = point
        elif not enabled and start is not None:
            ranges.append((start, point - 1))
            start = None
        if char.casefold() != char:
            folds.append((point, char.casefold()))
        if char.lower() != char:
            lower.append((point, char.lower()))
        # Derive effective casing/ignorable context from the builder's lower
        # oracle, including characters with both Unicode properties.
        if (char + "Σ").lower().endswith("ς"):
            cased.append(point)
        elif ("A" + char + "Σ").lower().endswith("ς"):
            ignored.append(point)
        if char.isspace():
            spaces.append(point)
    if start is not None:
        ranges.append((start, 0x10ffff))
    rows = [f'const MEMORY_UNICODE: &str = "{unicodedata.unidata_version}";',
            f'const MEMORY_LEADING_DOT_SUFFIX: bool = {str(Path("..x").stem != "..x").lower()};',
            'const WORD_RANGES: &[(u32,u32)] = &[']
    rows.extend(f'({low},{high}),' for low, high in ranges)
    rows.extend(['];', 'const CASE_FOLDS: &[(u32,&str)] = &['])
    rows.extend(f'({point},{json.dumps(fold, ensure_ascii=False)}),' for point, fold in folds)
    rows.append('];')
    rows.append('const LOWER_MAP: &[(u32,&str)] = &[')
    rows.extend(f'({point},{json.dumps(value, ensure_ascii=False)}),' for point, value in lower)
    rows.append('];')
    for name, points in (("LOWER_CASED", cased), ("LOWER_IGNORED", ignored), ("PYTHON_SPACE", spaces)):
        rows.append(f'const {name}: &[u32] = &[')
        rows.extend(f'{point},' for point in points)
        rows.append('];')
    output.write_text("\n".join(rows) + "\n", encoding="utf-8")
