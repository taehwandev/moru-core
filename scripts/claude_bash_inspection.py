"""Exact read-only grammars for inspection tools outside the core command list.

Owner: command-shape recognition consulted by claude_bash_readonly.simple_command_kind.
Allowed imports: standard library only.
Forbidden: execution, run state, project policy, interpreter-by-name allowances.
Callers/tests: claude_bash_readonly; test_claude_bash_inspection.
Verification: every grammar has an admitted case and a refused neighbour.

Each rule names one program and the exact argument shape under which that
program cannot write. Anything else returns None, and the caller keeps its
fail-closed default. An interpreter is admitted only for a mode that does not
run the program it is given -- a syntax check, a version probe, or the standard
library's JSON pretty-printer in isolated mode reading one file to stdout --
never for a script or a module shadowed by project files.
"""

from __future__ import annotations

from pathlib import Path
import re

# Programs that only report, whatever options they are given: none of them has
# an option that writes a file, runs a program, or signals a process.
INSPECTION_COMMANDS = frozenset({"cmp", "lsof", "md5", "pgrep", "readlink", "shasum"})
PYTHON_NAME_RE = re.compile(r"python(?:\d+(?:\.\d+)*)?")
# `json.tool [infile [outfile]]`: a second operand is a write target.
JSON_TOOL_FLAGS = frozenset({"--sort-keys", "--compact", "--no-ensure-ascii",
                             "--json-lines", "--tab", "--no-indent", "--ensure-ascii"})
# A `tar` listing: one leading mode cluster that contains `t` and only the
# decompression, verbosity and archive-file letters. Every other option --
# `--to-command`, `-I <program>`, `-x`, `-c` -- falls outside the cluster.
TAR_LIST_RE = re.compile(r"-?[vzjJf]*t[vzjJf]*")
FF_LOGLEVELS = frozenset({
    "quiet", "panic", "fatal", "error", "warning", "info", "verbose", "debug", "trace",
})
FFPROBE_SAFE_FLAGS = frozenset({
    "-hide_banner", "-show_format", "-show_streams", "-show_frames", "-show_packets",
    "-show_chapters", "-show_programs", "-show_error", "-show_data", "-count_frames",
    "-count_packets", "-pretty", "-unit", "-prefix", "-byte_binary_prefix",
    "-sexagesimal", "-bitexact", "-noprivate", "-show_private_data",
})
FFPROBE_FORMATS = frozenset({"default", "compact", "csv", "flat", "ini", "json", "xml"})
FFMPEG_PROBE_FLAGS = frozenset({"-hide_banner", "-nostats", "-nostdin", "-an", "-vn", "-sn", "-dn"})
FFMPEG_PROBE_VALUE_OPTIONS = frozenset({"-v", "-loglevel", "-t", "-ss", "-frames:v", "-map"})


def _operands_only(arguments: list[str]) -> bool:
    return all(not argument.startswith("-") for argument in arguments)


def interpreter_probe_kind(command: list[str]) -> str | None:
    """Read-only for a version probe, `node --check`, or `python -I -m json.tool`."""

    if command[0] != Path(command[0]).name:
        return None
    name = command[0]
    is_python = PYTHON_NAME_RE.fullmatch(name) is not None
    if name != "node" and not is_python:
        return None
    arguments = command[1:]
    version_flags = {"--version", "-V"} if is_python else {"--version", "-v"}
    if len(arguments) == 1 and arguments[0] in version_flags:
        return "read_only"
    if name == "node":
        # `--check` parses the file and exits; it never evaluates it.
        if len(arguments) >= 2 and arguments[0] in {"--check", "-c"} and _operands_only(arguments[1:]):
            return "read_only"
        return None
    # -I excludes the project directory and PYTHONPATH from module lookup.
    if arguments[:3] != ["-I", "-m", "json.tool"]:
        return None
    operands = 0
    index = 3
    while index < len(arguments):
        argument = arguments[index]
        flag, equal, value = argument.partition("=")
        if flag == "--indent":
            if not equal:
                index += 1
                value = arguments[index] if index < len(arguments) else ""
            if not value.isdigit():
                return None
        elif argument in JSON_TOOL_FLAGS:
            pass
        elif argument.startswith("-"):
            return None
        else:
            operands += 1
        index += 1
    return "read_only" if operands <= 1 else None


def _is_local_media_input(word: str) -> bool:
    return bool(word) and not word.startswith("-") and (word.startswith("/") or ":" not in word)


def _ffprobe_format_safe(value: str) -> bool:
    fmt = value.split("=", 1)[0]
    return fmt in FFPROBE_FORMATS and "/" not in value


def _ffprobe_metadata_kind(arguments: list[str]) -> str | None:
    """Local metadata to stdout, without output/report or format/protocol options."""
    inputs = 0
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if word in FFPROBE_SAFE_FLAGS:
            pass
        elif word in {"-v", "-loglevel", "-of", "-print_format", "-show_entries",
                      "-select_streams", "-read_intervals", "-probesize", "-analyzeduration", "-i"} and index + 1 < len(arguments):
            index += 1
            value = arguments[index]
            if word in {"-v", "-loglevel"}:
                if value not in FF_LOGLEVELS and not value.isdigit():
                    return None
            elif word in {"-of", "-print_format"}:
                if not _ffprobe_format_safe(value):
                    return None
            elif word == "-show_entries":
                if not re.fullmatch(r"[a-zA-Z0-9_=,:.\-]+", value):
                    return None
            elif word == "-select_streams":
                if not re.fullmatch(r"[a-zA-Z0-9_:]+", value):
                    return None
            elif word == "-i":
                if not _is_local_media_input(value):
                    return None
                inputs += 1
            elif not re.fullmatch(r"[a-zA-Z0-9_+%:,.\-]+", value):
                return None
        elif _is_local_media_input(word):
            inputs += 1
        else:
            return None
        index += 1
    return "read_only" if inputs == 1 else None


def _ffmpeg_probe_kind(arguments: list[str]) -> str | None:
    """Read-only `ffmpeg -i <local>` stream probe or `-f null -` decode check."""
    inputs = 0
    saw_null_muxer = False
    saw_null_sink = False
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if word in FFMPEG_PROBE_FLAGS:
            pass
        elif word == "-i" and index + 1 < len(arguments):
            index += 1
            if not _is_local_media_input(arguments[index]):
                return None
            inputs += 1
        elif word in FFMPEG_PROBE_VALUE_OPTIONS and index + 1 < len(arguments):
            index += 1
            value = arguments[index]
            if word in {"-v", "-loglevel"} and value not in FF_LOGLEVELS and not value.isdigit():
                return None
        elif word == "-f" and index + 1 < len(arguments):
            index += 1
            if arguments[index] != "null" or saw_null_muxer:
                return None
            saw_null_muxer = True
        elif word == "-" and saw_null_muxer and not saw_null_sink:
            saw_null_sink = True
        else:
            return None
        index += 1
    if inputs != 1:
        return None
    if saw_null_muxer and not saw_null_sink:
        return None
    return "read_only"


def inspection_command_kind(command: list[str]) -> str | None:
    """The read-only verdict for one exact inspection grammar, or None."""

    if not command:
        return None
    if command[0] != Path(command[0]).name:
        return None
    name = command[0]
    if name in INSPECTION_COMMANDS:
        return "read_only"
    if name == "command":
        arguments = command[1:]
        return "read_only" if (len(arguments) >= 2 and arguments[0] in {"-v", "-V"}
                               and _operands_only(arguments[1:])) else None
    if name == "ffprobe":
        return _ffprobe_metadata_kind(command[1:])
    if name == "ffmpeg":
        return _ffmpeg_probe_kind(command[1:])
    if name == "unzip":
        # -p streams archive members to stdout; default extraction, combined
        # switches and output-directory options must not inherit this contract.
        arguments = command[1:]
        return "read_only" if (len(arguments) >= 2 and arguments[0] == "-p"
                               and _operands_only(arguments[1:])) else None
    if name == "tar":
        arguments = command[1:]
        if arguments and TAR_LIST_RE.fullmatch(arguments[0]) and _operands_only(arguments[1:]):
            return "read_only"
        return None
    return interpreter_probe_kind(command)
