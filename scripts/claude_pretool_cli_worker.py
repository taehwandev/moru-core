"""Whether a Claude Bash call runs a provider CLI worker in the foreground.

Owner: the foreground CLI worker hold -- a `codex exec` or `claude -p` worker
started through Claude's Bash tool without `run_in_background` is cut off by
the tool's default timeout, although a cross-runtime comparison may run long.
The reader looks through wrappers, `sh -c` bodies and command substitutions,
and skips heredoc bodies and quoted words, which never run as commands.
Allowed imports: the standard library and claude_bash_raw_lines.
Forbidden imports: claude_pretool_gate and run evidence; the hold is decided
from the call alone.
Callers/tests: claude_pretool_gate; tests/test_claude_pretool_cli_worker.py.
Verification: that module.
"""

from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath

from claude_bash_raw_lines import substitution_end

MAX_NESTING = 4
SEGMENT_PUNCTUATION = ";&|(){}"
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC_RE = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
SHELL_PROGRAMS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
# Wrapper -> its options that take a separate value; other `-x` options take none.
WRAPPER_VALUE_OPTIONS: dict[str, frozenset[str]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "nohup": frozenset(),
    "time": frozenset(),
    "command": frozenset(),
    "exec": frozenset({"-a"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "gtimeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "sudo": frozenset({"-u", "--user", "-g", "--group", "-C", "-D", "-h", "-p", "-r", "-t", "-U"}),
    "npx": frozenset({"-p", "--package", "-c", "--call"}),
    "bunx": frozenset(),
    "caffeinate": frozenset({"-t", "-w"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
}
# Wrappers whose first operand is a value (a duration) before the program.
WRAPPERS_WITH_LEADING_OPERAND = frozenset({"timeout", "gtimeout"})
CODEX_VALUE_OPTIONS = frozenset({
    "-c", "--config", "-p", "--profile", "-m", "--model", "-C", "--cd", "-s", "--sandbox",
    "-a", "--ask-for-approval", "-i", "--image", "--add-dir", "--enable", "--disable",
    "--local-provider",
})
CODEX_EXEC_SUBCOMMANDS = frozenset({"exec", "e"})
CLAUDE_SUBCOMMANDS = frozenset({
    "mcp", "config", "doctor", "update", "install", "migrate-installer", "setup-token",
    "plugin", "agents", "auth",
})
CLAUDE_PRINT_FLAGS = frozenset({"-p", "--print"})
INFO_FLAGS = frozenset({"-h", "--help", "-V", "-v", "--version"})


def foreground_cli_worker_denial(payload: dict) -> str:
    """A denial reason for a foreground provider CLI worker, else an empty string."""

    tool_input = payload.get("tool_input") or {}
    if tool_input.get("run_in_background") is True:
        return ""
    worker = _worker_in(str(tool_input.get("command") or ""), 0)
    if not worker:
        return ""
    return (
        f"`{worker}` runs a provider CLI worker in the foreground, where the Bash tool's "
        "default timeout cuts off a long comparison. Rerun the same call with "
        "`run_in_background: true` and no `timeout`; spool output to run-local files "
        "and read the result when the completion notice arrives."
    )


def _worker_in(command: str, depth: int) -> str:
    if depth > MAX_NESTING:
        return ""
    command = _without_heredoc_bodies(command)
    for body in _substitution_bodies(command):
        worker = _worker_in(body, depth + 1)
        if worker:
            return worker
    try:
        lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=SEGMENT_PUNCTUATION)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return ""
    segment: list[str] = []
    for token in [*tokens, ";"]:
        # Adjacent operators such as `);` arrive as one punctuation token.
        if not set(token) <= set(SEGMENT_PUNCTUATION):
            segment.append(token)
            continue
        worker = _segment_worker(segment, depth)
        if worker:
            return worker
        segment = []
    return ""


def _without_heredoc_bodies(command: str) -> str:
    lines = command.split("\n")
    kept: list[str] = []
    pending: list[tuple[str, bool]] = []
    for line in lines:
        if pending:
            delimiter, strip_tabs = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                pending.pop(0)
            continue
        kept.append(line)
        pending.extend((match.group(3), match.group(1) == "-") for match in HEREDOC_RE.finditer(line))
    return "\n".join(kept)


def _substitution_bodies(command: str) -> list[str]:
    bodies: list[str] = []
    index = 0
    quote = ""
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if quote == "'":
            if character == "'":
                quote = ""
        elif character == "'" and not quote:
            quote = "'"
        elif character == '"':
            quote = "" if quote == '"' else '"'
        elif command.startswith("$(", index):
            end = substitution_end(command, index + 2)
            if end is None:
                return bodies
            bodies.append(command[index + 2 : end])
            index = end
        elif character == "`":
            end = command.find("`", index + 1)
            if end == -1:
                return bodies
            bodies.append(command[index + 1 : end])
            index = end
        index += 1
    return bodies


def _segment_worker(tokens: list[str], depth: int) -> str:
    tokens = _behind_wrappers(tokens)
    if not tokens:
        return ""
    program = PurePosixPath(tokens[0]).name
    if program in SHELL_PROGRAMS:
        body = _shell_command_body(tokens[1:])
        return _worker_in(body, depth + 1) if body else ""
    if program == "codex":
        return _codex_worker(tokens[1:])
    if program == "claude":
        return _claude_worker(tokens[1:])
    return ""


def _behind_wrappers(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if ASSIGNMENT_RE.match(token):
            index += 1
            continue
        name = PurePosixPath(token).name
        if name not in WRAPPER_VALUE_OPTIONS:
            return tokens[index:]
        index += 1
        value_options = WRAPPER_VALUE_OPTIONS[name]
        while index < len(tokens) and tokens[index].startswith("-") and tokens[index] != "-":
            option = tokens[index]
            index += 2 if option in value_options else 1
            if option == "--":
                break
        if name in WRAPPERS_WITH_LEADING_OPERAND:
            index += 1
    return []


def _shell_command_body(arguments: list[str]) -> str:
    for index, argument in enumerate(arguments):
        if argument == "--" or not argument.startswith("-"):
            return ""
        if "c" in argument.lstrip("-") and not argument.startswith("--"):
            return arguments[index + 1] if index + 1 < len(arguments) else ""
    return ""


def _options_before_end(arguments: list[str]) -> list[str]:
    return arguments[: arguments.index("--")] if "--" in arguments else arguments


def _codex_worker(arguments: list[str]) -> str:
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--" or not argument.startswith("-"):
            break
        if argument in INFO_FLAGS:
            return ""
        index += 2 if argument in CODEX_VALUE_OPTIONS else 1
    if index >= len(arguments) or arguments[index] not in CODEX_EXEC_SUBCOMMANDS:
        return ""
    exec_arguments = arguments[index + 1 :]
    if INFO_FLAGS.intersection(_options_before_end(exec_arguments)):
        return ""
    positionals = [argument for argument in _options_before_end(exec_arguments) if not argument.startswith("-")]
    if positionals[:1] == ["help"]:
        return ""
    return "codex exec"


def _claude_worker(arguments: list[str]) -> str:
    options = _options_before_end(arguments)
    positionals = [argument for argument in options if not argument.startswith("-")]
    if positionals[:1] and positionals[0] in CLAUDE_SUBCOMMANDS:
        return ""
    if INFO_FLAGS.intersection(options) or not CLAUDE_PRINT_FLAGS.intersection(options):
        return ""
    return "claude -p"
