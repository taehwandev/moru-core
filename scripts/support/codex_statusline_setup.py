"""Install Codex's native remaining-quota status items without owning the line."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


DEFAULT_STATUS_ITEMS = ("model-with-reasoning", "current-dir")
QUOTA_STATUS_ITEMS = ("five-hour-limit", "weekly-limit")

_TABLE_HEADER = re.compile(r"(?m)^[ \t]*\[([^\]\n]+)\][ \t]*(?:#.*)?$")


def merge_codex_status_line(target: Path, dry_run: bool) -> str:
    """Add the native quota items while preserving the user's status selection.

    Codex owns both the data and the rendering. Moru only makes the two built-in
    items visible. An unset status line first receives Codex's documented
    defaults so enabling quota does not make the model and directory disappear.

    The merge is deliberately narrower than a TOML rewrite: it changes one
    array literal in place and leaves every other byte alone. Config shapes it
    cannot prove safe to edit are reported as missing instead of being replaced.
    """

    original = target.read_text(encoding="utf-8") if target.exists() else ""
    result = _native_merge(original)
    status, updated = result if result is not None else _merge_text_reference(original)
    if status != "changed":
        return status
    if dry_run:
        return "would_update"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(updated, encoding="utf-8")
    return "installed"


def setup_codex_status_line(target: Path, dry_run: bool) -> str:
    """Delegate file I/O only when the caller and native child share HOME."""
    from support.native_probe_transport import NativeProbe

    home = Path(os.environ.get("HOME", ""))
    if home.is_absolute() and target == home / ".codex" / "config.toml":
        operation = "codex-status-line-plan" if dry_run else "codex-status-line-apply"
        result = NativeProbe.request("--setup-probe", operation, {})
        if result is not None:
            status = result.get("status")
            changed = "would_update" if dry_run else "installed"
            if set(result) == {"status"} and type(status) is str and status in ("ok", "missing", changed):
                return status
            if not dry_run:
                raise OSError("native Codex statusline apply outcome could not be determined")
    return merge_codex_status_line(target, dry_run)


def _merge_text_reference(original: str) -> tuple[str, str]:
    assignment = _status_line_assignment(original)
    if assignment is _CONFLICT:
        return "missing", original

    if assignment is None:
        desired = (*DEFAULT_STATUS_ITEMS, *QUOTA_STATUS_ITEMS)
        updated = _insert_status_line(original, desired)
        if updated is None:
            return "missing", original
    else:
        opening, closing = assignment
        configured = _quoted_items(original[opening + 1 : closing])
        if configured is None:
            return "missing", original
        missing = [item for item in QUOTA_STATUS_ITEMS if item not in configured]
        if not missing:
            return "ok", original
        updated = _append_array_items(original, opening, closing, missing)

    return ("ok" if updated == original else "changed"), updated


_CONFLICT = object()


def _status_line_assignment(text: str) -> tuple[int, int] | object | None:
    headers = list(_TABLE_HEADER.finditer(text))
    tui_headers = [header for header in headers if header.group(1).strip() == "tui"]
    if len(tui_headers) > 1:
        return _CONFLICT

    candidates: list[re.Match[str]] = []
    if tui_headers:
        header = tui_headers[0]
        following = next(
            (other.start() for other in headers if other.start() > header.start()),
            len(text),
        )
        candidates.extend(
            re.finditer(
                r"(?m)^[ \t]*status_line[ \t]*=",
                text[header.end() : following],
            )
        )
        offset = header.end()
    else:
        first_table = headers[0].start() if headers else len(text)
        candidates.extend(
            re.finditer(
                r"(?m)^[ \t]*tui\.status_line[ \t]*=",
                text[:first_table],
            )
        )
        offset = 0

    if len(candidates) > 1:
        return _CONFLICT
    if not candidates:
        return None

    equals = offset + candidates[0].end() - 1
    opening = equals + 1
    while opening < len(text) and text[opening].isspace():
        opening += 1
    if opening >= len(text) or text[opening] != "[":
        return _CONFLICT
    closing = _matching_array_end(text, opening)
    if closing is None:
        return _CONFLICT
    return opening, closing


def _matching_array_end(text: str, opening: int) -> int | None:
    quote = ""
    escaped = False
    comment = False
    depth = 0
    for index in range(opening, len(text)):
        character = text[index]
        if comment:
            if character == "\n":
                comment = False
            continue
        if quote:
            if quote == '"' and escaped:
                escaped = False
            elif quote == '"' and character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character == "#":
            comment = True
        elif text.startswith(('"""', "'''"), index):
            return None
        elif character in {'"', "'"}:
            quote = character
        elif character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return index
    return None


def _quoted_items(body: str) -> set[str] | None:
    items: set[str] = set()
    index = 0
    expect_item = True
    saw_item = False
    while index < len(body):
        character = body[index]
        if character.isspace():
            index += 1
            continue
        if character == "#":
            newline = body.find("\n", index)
            index = len(body) if newline < 0 else newline + 1
            continue
        if not expect_item:
            if character != ",":
                return None
            expect_item = True
            index += 1
            continue
        if character not in {'"', "'"} or body.startswith(
            ('"""', "'''"), index
        ):
            return None

        quote = character
        start = index + 1
        index += 1
        escaped = False
        while index < len(body):
            character = body[index]
            if quote == '"' and escaped:
                escaped = False
            elif quote == '"' and character == "\\":
                escaped = True
            elif character == quote:
                items.add(body[start:index])
                index += 1
                expect_item = False
                saw_item = True
                break
            index += 1
        else:
            return None

    if expect_item and saw_item:
        return items
    return items


def _append_array_items(
    text: str,
    opening: int,
    closing: int,
    items: list[str],
) -> str:
    body = text[opening + 1 : closing]
    last_syntax = _last_syntax_index(body)
    if last_syntax is not None and body[last_syntax] != ",":
        body = f"{body[: last_syntax + 1]},{body[last_syntax + 1 :]}"

    rendered = ", ".join(json.dumps(item) for item in items)
    trailing_line = body.rsplit("\n", 1)
    if len(trailing_line) == 2 and not trailing_line[1].strip():
        core, closing_indent = trailing_line
        item_indent = _item_indent(core, closing_indent)
        separator = "" if core.endswith("\n") else "\n"
        body = f"{core}{separator}{item_indent}{rendered}\n{closing_indent}"
    else:
        spacer = "" if last_syntax is None else " "
        body = f"{body}{spacer}{rendered}"
    return f"{text[: opening + 1]}{body}{text[closing:]}"


def _last_syntax_index(body: str) -> int | None:
    quote = ""
    escaped = False
    comment = False
    last: int | None = None
    for index, character in enumerate(body):
        if comment:
            if character == "\n":
                comment = False
            continue
        if quote:
            last = index
            if quote == '"' and escaped:
                escaped = False
            elif quote == '"' and character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character == "#":
            comment = True
        elif character in {'"', "'"}:
            quote = character
            last = index
        elif not character.isspace():
            last = index
    return last


def _item_indent(core: str, closing_indent: str) -> str:
    for line in reversed(core.splitlines()):
        if line.strip() and not line.lstrip().startswith("#"):
            return line[: len(line) - len(line.lstrip())]
    return f"{closing_indent}  "


def _insert_status_line(text: str, items: tuple[str, ...]) -> str | None:
    rendered = ", ".join(json.dumps(item) for item in items)
    headers = list(_TABLE_HEADER.finditer(text))

    tui = next((header for header in headers if header.group(1).strip() == "tui"), None)
    if tui is not None:
        line_end = text.find("\n", tui.end())
        insertion = len(text) if line_end < 0 else line_end + 1
        prefix = "\n" if line_end < 0 else ""
        return f"{text[:insertion]}{prefix}status_line = [{rendered}]\n{text[insertion:]}"

    first_table = headers[0].start() if headers else len(text)
    if re.search(r"(?m)^[ \t]*tui[ \t]*=", text[:first_table]):
        return None
    if any(header.group(1).strip().startswith("tui.") for header in headers):
        return (
            f'{text[:first_table]}tui.status_line = [{rendered}]\n'
            f"{text[first_table:]}"
        )
    separator = "" if not text else "\n" if text.endswith("\n") else "\n\n"
    return f"{text}{separator}[tui]\nstatus_line = [{rendered}]\n"


_NATIVE_PROFILE = {name: (globals()[name], globals()[name].__code__, globals()[name].__defaults__)
    for name in ("_merge_text_reference", "_status_line_assignment", "_matching_array_end",
                 "_quoted_items", "_append_array_items", "_last_syntax_index", "_item_indent", "_insert_status_line")}
_NATIVE_VALUES = {name: globals()[name] for name in
    ("DEFAULT_STATUS_ITEMS", "QUOTA_STATUS_ITEMS", "_TABLE_HEADER", "_CONFLICT")}
_NATIVE_JSON_DUMPS = (json.dumps, json.dumps.__code__, json.dumps.__kwdefaults__.copy())
_NATIVE_JSON_MODULE = json
_NATIVE_RE_MODULE = re
_NATIVE_RE = {name: (getattr(re, name), getattr(re, name).__code__, getattr(re, name).__defaults__)
    for name in ("finditer", "search")}


def _native_merge(text: str) -> tuple[str, str] | None:
    if (type(text) is not str
            or globals().get("json") is not _NATIVE_JSON_MODULE
            or getattr(json, "dumps", None) is not _NATIVE_JSON_DUMPS[0]
            or json.dumps.__code__ is not _NATIVE_JSON_DUMPS[1]
            or json.dumps.__kwdefaults__ != _NATIVE_JSON_DUMPS[2]
            or globals().get("re") is not _NATIVE_RE_MODULE
            or any(getattr(re, name, None) is not fn or fn.__code__ is not code or fn.__defaults__ is not defaults
                   for name, (fn, code, defaults) in _NATIVE_RE.items())
            or any(globals().get(name) is not value for name, value in _NATIVE_VALUES.items())
            or any(globals().get(name) is not fn or fn.__code__ is not code or fn.__defaults__ is not defaults
                   for name, (fn, code, defaults) in _NATIVE_PROFILE.items())):
        return None
    from support.native_probe_transport import NativeProbe
    try:
        result = NativeProbe.request("--setup-probe", "codex-status-line", {"text": text})
    except (OSError, ValueError, RuntimeError):
        return None
    if (type(result) is not dict or set(result) != {"status", "text"}
            or type(result["status"]) is not str or type(result["text"]) is not str
            or result["status"] not in {"ok", "missing", "changed"}
            or (result["status"] == "changed") != (result["text"] != text)):
        return None
    return result["status"], result["text"]


def _main() -> int:
    target = Path.home() / ".codex" / "config.toml"
    status = merge_codex_status_line(target, dry_run=False)
    print(f"Codex quota status line: {status} ({target})")
    return 0 if status in {"installed", "ok"} else 1


if __name__ == "__main__":
    raise SystemExit(_main())
