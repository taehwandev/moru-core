"""Read which project a Moru closeout command (review, finish, gate-batch) works on.

Owner: shell-word parsing of a Bash command into its closeout project.
Allowed imports: the standard library only.
Callers/tests: `claude_pretool_gate._queue_unread_required_docs`;
`tests/test_agent_required_doc_delivery.py`.
Verification: that module's closeout parsing cases.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

_CLOSEOUT_VERBS = {"review", "finish", "gate-batch"}
_LAUNCHERS = {"moru-hook", "agent-hook.py"}
_SEPARATORS = {"&&", "||", ";", "|", "&", ";;"}
_GROUPING = {"(", ")", "{", "}"}


def closeout_project(payload: dict) -> Path | None:
    """The project a Moru closeout command (review, finish, gate-batch) works on, else None.

    The command is read as shell words, so a mention inside a quoted string, a
    search pattern or a commit message is not a closeout. A `cd` earlier in the
    chain moves the directory a relative `--project` is read against, and the
    command's own `--project` wins over the shell's cwd. Never raises: this
    runs ahead of the gate's policy decision, which an error must not skip.
    """

    try:
        return _closeout_project(payload)
    except Exception:  # noqa: BLE001 - an unreadable command is simply not a closeout
        return None


def _closeout_project(payload: dict) -> Path | None:
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not any(verb in command for verb in _CLOSEOUT_VERBS):
        return None
    cwd = Path(str(payload.get("cwd") or "."))
    segment: list[str] = []
    for line in command.replace("\\\n", " ").splitlines():
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            words = list(lexer)  # `#` starts a comment, so its text is never a command
        except ValueError:
            continue  # a line inside a multi-line quote (message, heredoc) holds no command
        for word in [*words, ";"]:
            if word not in _SEPARATORS:
                if word not in _GROUPING:
                    segment.append(word)
                continue
            found, moved = _segment_closeout(segment, cwd)
            if found is not None:
                return found
            # `cd x || cmd` runs cmd only when the cd failed, so the move did not happen.
            cwd = cwd if word == "||" else moved
            segment = []
    return None


def _home_path(text: str) -> Path | None:
    try:
        return Path(text).expanduser()
    except (RuntimeError, OSError):
        return None


def _segment_closeout(words: list[str], cwd: Path) -> tuple[Path | None, Path]:
    """(project, cwd after this segment) for one simple command."""

    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words = words[1:]
    if words and words[0] == "env":
        words = words[1:]
        while words and (words[0].startswith("-") or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0])):
            words = words[1:]
    if words and Path(words[0]).name.startswith("python"):
        words = words[1:]
        while words and words[0].startswith("-"):
            words = words[1:]
    if not words:
        return None, cwd
    if words[0] == "cd":
        args = [word for word in words[1:] if not word.startswith("-") or word == "-"]
        target = _home_path(args[0]) if args else None
        if target is None or args[0] == "-":
            return None, cwd
        return None, target if target.is_absolute() else cwd / target
    if Path(words[0]).name not in _LAUNCHERS or len(words) < 2 or words[1] not in _CLOSEOUT_VERBS:
        return None, cwd
    for index, word in enumerate(words):
        value = word[len("--project="):] if word.startswith("--project=") else (
            words[index + 1] if word == "--project" and index + 1 < len(words) else None)
        if value:
            project = None if "$" in value or "`" in value else _home_path(value)
            if project is None:
                return cwd, cwd  # an expansion only the shell can resolve: the shell's directory
            return (project if project.is_absolute() else cwd / project), cwd
    return cwd, cwd
