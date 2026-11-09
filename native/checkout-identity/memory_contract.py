"""Build-only Unicode vocabulary for the native memory lexical owner.

Owner: memory term contract. Allowed: stdlib. Forbidden: runtime policy/store
imports. Caller: pretool_contract.py. Verification: source/native term corpus.
"""
import json
import unicodedata


def emit(output):
    ranges, folds, start = [], [], None
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
    if start is not None:
        ranges.append((start, 0x10ffff))
    rows = [f'const MEMORY_UNICODE: &str = "{unicodedata.unidata_version}";',
            'const WORD_RANGES: &[(u32,u32)] = &[']
    rows.extend(f'({low},{high}),' for low, high in ranges)
    rows.extend(['];', 'const CASE_FOLDS: &[(u32,&str)] = &['])
    rows.extend(f'({point},{json.dumps(fold, ensure_ascii=False)}),' for point, fold in folds)
    rows.append('];')
    output.write_text("\n".join(rows) + "\n", encoding="utf-8")
