"""Builder-owned CPython JSON diagnostic vocabulary; no runtime Python or writes except output.

Owner: JSON error contract. Imports: stdlib. Callers: build.rs.
Verification: exact decoder messages/positions and integer conversion diagnostics.
"""
import argparse
import json
from pathlib import Path
import sys


def _error(text):
    try:
        json.loads(text)
    except ValueError as error:
        return error
    raise RuntimeError("expected invalid JSON probe")


def emit(output):
    flags = []
    for text, kind, legacy, old_pos, new_pos in [
        ("[1,]", "array", "Expecting value", 3, 2),
        ('{"a":1,}', "object", "Expecting property name enclosed in double quotes", 7, 6),
    ]:
        error = _error(text)
        new = f"Illegal trailing comma before end of {kind}"
        if (error.msg, error.pos) not in ((legacy, old_pos), (new, new_pos)):
            raise RuntimeError("unsupported JSON trailing-comma diagnostics")
        flags.append(f"const JSON_{kind.upper()}_TRAILING: bool = {str(error.msg == new).lower()};\n")
    for text, message, position in [
        ("", "Expecting value", 0), ("1.", "Extra data", 1),
        ('"a\\q"', "Invalid \\escape", 2), ('"a\\u12z4"', "Invalid \\uXXXX escape", 3),
        ('"a\n"', "Invalid control character at", 2),
        ('"a', "Unterminated string starting at", 0),
        ('{"a" 1}', "Expecting ':' delimiter", 5),
        ('[1 2]', "Expecting ',' delimiter", 3),
        ('\ufeff{}', "Unexpected UTF-8 BOM (decode using utf-8-sig)", 0),
    ]:
        error = _error(text)
        if (error.msg, error.pos) != (message, position):
            raise RuntimeError("unsupported JSON syntax diagnostics")
    limit = sys.get_int_max_str_digits() if hasattr(sys, "get_int_max_str_digits") else 0
    template = None
    if limit:
        template = str(_error("1" * (limit + 1))).replace(str(limit + 1), "{digits}").replace(str(limit), "{limit}")
        if template.format(limit=limit, digits=limit + 2) != str(_error("1" * (limit + 2))):
            raise RuntimeError("unsupported integer digit-limit diagnostic")
    literal = "None" if template is None else "Some(" + json.dumps(template) + ")"
    flags.append(f"const JSON_DIGIT_ERROR: Option<&str> = {literal};\n")
    output.write_text("".join(flags))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", type=Path, required=True)
    emit(parser.parse_args().emit)
