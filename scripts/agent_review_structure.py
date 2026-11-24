"""Read-only structure checks for the Moru Core review hook."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from agent_review_boundary import boundary_note_requirements
from agent_review_generated_attrs import _declares_generated, linguist_generated_path
from agent_android_action_boundary import AndroidActionBoundary
from agent_review_purpose import (
    GENERIC_PACKAGE_PARTS,
    MAX_PUBLIC_TOP_LEVEL_OWNERS,
    MAX_TOP_LEVEL_OWNERS,
    MIXED_ROLE_BLOCKS,
    _owner_findings,
    _owner_review_facts,
    previous_top_level_type_declarations,
    purpose_failures,
    top_level_type_declarations,
)
from agent_review_removals import classify_net_deletions
from agent_review_merge_baseline import inherited_merge_paths
from agent_structure_rules import structure_rule_review
from agent_workspace_policy import is_non_git_workspace, is_writing_workspace
from support.native_probe_transport import NativeProbe


CommandRunner = Callable[[list[str], Path], dict[str, Any]]

REVIEW_SOURCE_FILE_LINE_LIMIT = 500
REVIEW_FILE_REVIEW_WARNING_LIMIT = 300
REVIEW_ADDED_LINE_LIMIT = 300
REVIEW_FUNCTION_LINE_LIMIT = 120
# The file/block gates above catch a unit that grew too large. They do nothing
# about the opposite failure: a small task spread across many new files, layers,
# and abstractions ("dozens of files for a few lines of behavior"). Count new
# development source files and require structure-review evidence past this limit
# so sprawl has to be justified per file/abstraction against a present risk. See
# llm-coding-discipline/references/current-guidance.md#match-structure-to-the-problem-hard-stop.
REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT = 20
# Test files legitimately run longer than production files (setup, fixtures,
# one scenario per case), so they get a wider budget instead of the source
# limit -- but an unbounded exemption is how a single test file grows to
# thousands of lines with no gate ever flagging it. See
# common/skills/testing/references/current-guidance.md#test-file-organization.
REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER = 3
REVIEW_TEST_FILE_LINE_LIMIT = REVIEW_SOURCE_FILE_LINE_LIMIT * REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER
REVIEW_TEST_FILE_REVIEW_WARNING_LIMIT = (
    REVIEW_FILE_REVIEW_WARNING_LIMIT * REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER
)
REVIEW_TEST_ADDED_LINE_LIMIT = REVIEW_ADDED_LINE_LIMIT * REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER
# Every structural check below inspects development source files only, so a
# rewrite that dropped a documented procedure out of a markdown file produced no
# signal from any gate: the result still parsed, still validated, and still
# passed review. Net line loss is therefore measured for every changed path
# regardless of extension, because losing content is a reviewable outcome of the
# diff rather than a property of the language it was written in.
REVIEW_NET_DELETION_LIMIT = 50
REVIEW_SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".cjs",
    ".dart",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".m",
    ".mjs",
    ".mm",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sass",
    ".scss",
    ".svelte",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}
REVIEW_STYLE_EXTENSIONS = {".css", ".scss", ".sass"}
STRUCTURE_REVIEW_SCOPE_NOTE = (
    "changed development source/style only; tests/fixtures/mocks/specs use wider file "
    "limits (REVIEW_TEST_FILE_LINE_LIMIT), not exemption; tests alone skip oversized-block "
    "checks. Generated/pinned third-party, config/build, Markdown/MDX/prose excluded"
)
REVIEW_SKIP_PARTS = {
    ".git",
    ".next",
    "DerivedData",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
}
REVIEW_GENERATED_PARTS = {"__generated__", "generated", "gen"}
REVIEW_CONFIG_FILE_NAMES = {
    "package.swift",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "setup.py",
}
REVIEW_CONFIG_SUFFIXES = (
    ".config.cjs", ".config.js", ".config.mjs", ".config.mts", ".config.py",
    ".config.ts", ".conf.js", ".conf.ts", ".gradle", ".gradle.kts",
)
TEST_PATH_PARTS = {
    "__fixtures__",
    "__mocks__",
    "__tests__",
    "fixture",
    "fixtures",
    "mock",
    "mocks",
    "spec",
    "specs",
    "test",
    "tests",
}
PYTHON_BLOCK_RE = re.compile(r"^(\s*)(?:async\s+def|def|class)\s+([A-Za-z_]\w*)\b")
BRACE_BLOCK_RE = re.compile(
    r"^\s*(?:"
    r"(?:export\s+)?(?:async\s+)?function\s+\w+"
    r"|(?:export\s+)?(?:default\s+)?class\s+\w+"
    r"|(?:export\s+)?(?:const|let|var)\s+\w+(?:\s*:[^=]+)?\s*=\s*(?:async\s*)?(?:<[^>({]+>\s*)?(?:\((?:[^()]|\([^()]*\))*\)|\w+)(?:\s*:[^=]+)?\s*=>"
    r"|(?:public|private|protected|internal|static|final|open|override|async|func|fun|def|fn|"
    r"function|method|class|struct|enum|interface|type)\b.*"
    r")"
)
BRACE_TYPE_BLOCK_RE = re.compile(
    r"^\s*(?:(?:export|default|public|private|protected|internal|static|final|open|abstract|"
    r"sealed|data|value|annotation|enum)\s+)*(?:class|struct|enum|interface|object|record|"
    r"actor|protocol|type)\b"
)
STYLE_BLOCK_RE = re.compile(r"^\s*[^@{}][^{}]*\{\s*$")


def android_action_delta_failures(project, path, lines, metadata, run_command):
    """Block new violations; report violations on unchanged baseline lines."""
    current = AndroidActionBoundary.failures(path, "\n".join(lines))
    if not current or metadata.get("status") == "A":
        return current, []
    previous_path = str(metadata.get("previous_path") or path.as_posix())
    previous = run_command(["git", "show", f"HEAD:{previous_path}"], project)
    if previous.get("returncode") != 0:
        return current, []
    previous_lines = previous.get("stdout", "").splitlines()
    prior = AndroidActionBoundary.failures(path, "\n".join(previous_lines))
    prior_keys = [_action_key(finding) for finding in prior]
    current_keys = [_action_key(finding) for finding in current]
    native = NativeProbe.request("--completion-probe", "structure-action-delta", {
        "previous": previous_lines, "current": lines,
        "prior_keys": prior_keys, "current_keys": current_keys,
    })
    flags = native.get("inherited") if native is not None else None
    if (not isinstance(flags, list) or len(flags) != len(current)
            or not all(type(flag) is bool for flag in flags)):
        flags = _inherited_action_findings(previous_lines, lines, prior_keys, current_keys)
    failures, warnings = [], []
    for finding, inherited in zip(current, flags):
        if inherited:
            warnings.append("unchanged baseline violation: " + finding)
        else:
            failures.append(finding)
    return failures, warnings


def _action_key(finding: str) -> tuple[int, str] | None:
    match = re.match(r"^.*?:(\d+): (.*)$", finding)
    return (int(match[1]), match[2]) if match else None


def _inherited_action_findings(
    previous: list[str], current: list[str],
    prior_keys: list[tuple[int, str] | None], current_keys: list[tuple[int, str] | None],
) -> list[bool]:
    unchanged = {}
    for block in SequenceMatcher(None, previous, current, autojunk=False).get_matching_blocks():
        unchanged.update((block.a + offset + 1, block.b + offset + 1)
                         for offset in range(block.size))
    inherited = {(unchanged[key[0]], key[1]) for key in prior_keys if key and key[0] in unchanged}
    return [key in inherited for key in current_keys]


def structure_review(
    project: Path,
    max_file_lines: int,
    max_block_lines: int,
    run_command: CommandRunner,
    review_paths: list[str] | None = None,
    max_added_lines: int = REVIEW_ADDED_LINE_LIMIT,
    source_project: Path | None = None,
    review_commits: tuple[str, str] | None = None,
) -> dict[str, Any]:
    source_root = source_project or project
    discovery, paths = changed_source_paths(
        project,
        run_command,
        review_paths,
        review_commits=review_commits,
        source_project=source_root,
        include_net_deletions=True,
    )
    subject_run_command = _subject_run_command(project, run_command, review_commits)
    result = _structure_result(
        discovery,
        paths,
        max_file_lines=max_file_lines,
        max_block_lines=max_block_lines,
        max_added_lines=max_added_lines,
    )
    classify_net_deletions(
        result["net_deletions"],
        project=project,
        run_command=run_command,
        review_paths=review_paths,
        review_commits=review_commits,
        path_metadata=discovery["path_metadata"],
    )

    inherited = inherited_merge_paths(project, paths, run_command) if review_commits is None else {}
    result["inherited_merge_paths"] = inherited
    active_paths = [path for path in paths if str(path) not in inherited]
    if inherited:
        result["warnings"].append(
            f"{len(inherited)} merge paths retain exact parent/index content and mode; "
            "structural baseline only, with full review/publication scope unchanged"
        )

    file_checks = []
    owner_checks = []
    for relative in active_paths:
        is_test_path = test_exempt_path(relative)
        if is_test_path:
            result["test_exempt_paths"].append(str(relative))
        else:
            result["strict_checked_paths"].append(str(relative))

        absolute = source_root / relative
        try:
            lines = absolute.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            result["warnings"].append(f"{relative} is not valid UTF-8; manual structure review required")
            continue

        metadata = discovery["path_metadata"].get(str(relative), {})
        file_review = {
            "path": str(relative),
            "line_count": len(lines),
            "metadata": metadata,
            "max_file_lines": REVIEW_TEST_FILE_LINE_LIMIT if is_test_path else max_file_lines,
            "max_added_lines": max_added_lines * REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER if is_test_path
            else max_added_lines,
            "review_warning_file_lines": REVIEW_TEST_FILE_REVIEW_WARNING_LIMIT if is_test_path
            else REVIEW_FILE_REVIEW_WARNING_LIMIT,
        }
        if not is_test_path:
            owner_checks.append(_owner_review_facts(
                relative,
                top_level_type_declarations(relative, lines),
                previous_top_level_type_declarations(source_root, relative, discovery["path_metadata"], subject_run_command),
            ))
            file_review["actions"] = android_action_delta_failures(
                project, relative, lines, metadata, subject_run_command,
            )
            if len(lines) > max_block_lines:
                prepared = _block_span_input(relative, lines)
                if "lines" in prepared or prepared["starts"]:
                    file_review["block_spans"] = {
                        **prepared, "limit": max_block_lines, "initial": bool(metadata.get("initial_full_build")),
                    }
        file_checks.append((len(result["failures"]), len(result["warnings"]), file_review))

    files = [row for _, _, row in file_checks]
    _attach_block_baselines(source_root, files, subject_run_command)
    path_metadata = discovery["path_metadata"]
    file_findings, source_layout = _file_findings(files, source_layout={
        "limit": REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT,
        "generic_parts": sorted(GENERIC_PACKAGE_PARTS),
        "paths": [[path, path_metadata.get(path, {}).get("status")] for path in result["strict_checked_paths"]],
        "owners": {
            "files": owner_checks,
            "public_limit": MAX_PUBLIC_TOP_LEVEL_OWNERS,
            "visible_limit": MAX_TOP_LEVEL_OWNERS,
            "role_pairs": MIXED_ROLE_BLOCKS,
        },
    })
    owner_findings = source_layout.get("owner_failures") if source_layout is not None else None
    if owner_findings is None:
        owner_findings = [finding for check in owner_checks for finding in _owner_findings(check)]
    # Preserve each file's position relative to encoding warnings.
    for kind, index in (("failures", 0), ("warnings", 1)):
        other_findings = result[kind]
        combined = []
        start = 0
        for check, messages in zip(file_checks, file_findings):
            end = check[index]
            combined.extend(other_findings[start:end])
            combined.extend(messages[index])
            start = end
        combined.extend(other_findings[start:])
        result[kind] = combined

    _add_cross_path_findings(
        result,
        source_root=source_root,
        paths=active_paths,
        discovery={**discovery, "path_metadata": {
            path: metadata for path, metadata in discovery["path_metadata"].items()
            if path not in inherited
        }},
        subject_run_command=subject_run_command,
        source_layout=source_layout,
        owner_findings=owner_findings,
    )
    return result


def _structure_result(
    discovery: dict[str, Any],
    paths: list[Path],
    *,
    max_file_lines: int,
    max_block_lines: int,
    max_added_lines: int,
) -> dict[str, Any]:
    """The review's answer sheet, with every limit it will be judged against.

    The limits are recorded rather than only applied, because a reader who is
    told a file is too long has to be able to see what "too long" was for that
    file: the test budget and the source budget differ, and which one applied is
    not recoverable from the failure text alone.
    """

    net_deletions = discovery.pop("_net_deletions", None)
    if net_deletions is None:
        net_deletions = net_deletion_findings(discovery["path_metadata"])
    return {
        "checked_paths": [str(path) for path in paths],
        "checked_path_count": len(paths),
        "development_extensions": sorted(REVIEW_SOURCE_EXTENSIONS),
        "strict_checked_paths": [],
        "test_exempt_paths": [],
        "max_file_lines": max_file_lines,
        "max_block_lines": max_block_lines,
        "max_added_lines": max_added_lines,
        "review_warning_file_lines": REVIEW_FILE_REVIEW_WARNING_LIMIT,
        "test_max_file_lines": REVIEW_TEST_FILE_LINE_LIMIT,
        "test_max_added_lines": max_added_lines * REVIEW_TEST_FILE_LINE_LIMIT_MULTIPLIER,
        "test_review_warning_file_lines": REVIEW_TEST_FILE_REVIEW_WARNING_LIMIT,
        "scope": STRUCTURE_REVIEW_SCOPE_NOTE,
        "warnings": [],
        "failures": list(discovery["command_errors"]),
        "boundary_note_requirements": [],
        "net_deletion_limit": REVIEW_NET_DELETION_LIMIT,
        "net_deletions": net_deletions,
        "discovery": discovery,
    }


def _add_cross_path_findings(
    result: dict[str, Any],
    *,
    source_root: Path,
    paths: list[Path],
    discovery: dict[str, Any],
    subject_run_command: CommandRunner,
    source_layout: dict[str, Any] | None,
    owner_findings: list[str],
) -> None:
    """Everything that can only be seen with the whole changed set in view.

    Sprawl, content-preserving copies, purpose overlap and boundary notes are
    all statements about how the changed files relate to each other, so none of
    them can be decided inside the per-file loop above.
    """

    if source_layout is None:
        flag_new_source_file_sprawl(result, discovery["path_metadata"])
        flag_content_preserving_source_copies(result, discovery["path_metadata"])
    else:
        result["new_source_file_count"] = source_layout["added"]
        result["new_source_file_pressure_limit"] = REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT
        result["content_preserving_source_copy_count"] = source_layout["copied"]
        result["warnings"].extend(source_layout["warnings"])
    result["failures"].extend(
        purpose_failures(
            source_root,
            paths,
            discovery["path_metadata"],
            review_source_path,
            test_exempt_path,
            subject_run_command,
            package_findings=source_layout.get("package_failures") if source_layout is not None else None,
            owner_findings=owner_findings,
        )
    )
    structure_rules = structure_rule_review(
        source_root,
        paths,
        discovery["path_metadata"],
        review_source_path,
        test_exempt_path,
    )
    result["structure_rules"] = structure_rules
    result["failures"].extend(structure_rules["failures"])
    result["warnings"].extend(structure_rules["warnings"])
    result["boundary_note_requirements"] = boundary_note_requirements(
        source_root,
        paths,
        discovery["path_metadata"],
        subject_run_command,
        review_source_path,
        test_exempt_path,
    )


def flag_new_source_file_sprawl(
    result: dict[str, Any],
    path_metadata: dict[str, dict[str, Any]],
) -> None:
    """Require justification when a change spawns many new source files.

    Test, config, generated, and pinned third-party files are already excluded
    from strict_checked_paths, so this counts only new development source files.
    """
    added = [
        path
        for path in result["strict_checked_paths"]
        if path_metadata.get(path, {}).get("status") == "A"
    ]
    result["new_source_file_count"] = len(added)
    result["new_source_file_pressure_limit"] = REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT
    if len(added) <= REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT:
        return

    shown = ", ".join(added[:8])
    if len(added) > 8:
        shown += "; ..."
    result["warnings"].append(
        f"change adds {len(added)} new development source files ({shown}); "
        f"new-file review-pressure limit is {REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT}; "
        "structure-review evidence must justify each new file or abstraction against a "
        "concrete present risk (see Match Structure To The Problem), or the change should "
        "be collapsed into fewer files"
    )


def flag_content_preserving_source_copies(
    result: dict[str, Any],
    path_metadata: dict[str, dict[str, Any]],
) -> None:
    """Keep copy-first migrations visible without treating retained debt as new work."""
    copied = [
        path
        for path in result["strict_checked_paths"]
        if path_metadata.get(path, {}).get("status") == "C"
    ]
    result["content_preserving_source_copy_count"] = len(copied)
    if not copied:
        return

    shown = ", ".join(copied[:8])
    if len(copied) > 8:
        shown += "; ..."
    result["warnings"].append(
        f"change adds {len(copied)} content-preserving source copy/copies ({shown}); "
        "structure-review evidence must name the copy-first source and target, the "
        "behavior-parity verification, and the caller-cutover or legacy-removal condition"
    )


# The object ids of git's empty tree, SHA-1 and SHA-256 repositories.
EMPTY_TREE_IDS = frozenset({
    "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321",
})


def _head_tree_is_empty(project: Path, run_command: CommandRunner) -> bool:
    """Whether HEAD is a root commit with git's empty tree (compared by id, never inferred from empty output).

    A later commit that deleted everything also has an empty tree, but it is not a fresh start: only a
    parentless HEAD gives an initial full build.
    """

    tree = run_command(["git", "rev-parse", "--verify", "HEAD^{tree}"], project)
    if tree["returncode"] != 0 or tree["stdout"].strip() not in EMPTY_TREE_IDS:
        return False
    parent = run_command(["git", "rev-parse", "--verify", "--quiet", "HEAD^"], project)
    return parent["returncode"] != 0


def changed_source_paths(
    project: Path,
    run_command: CommandRunner,
    review_paths: list[str] | None = None,
    *,
    review_commits: tuple[str, str] | None = None,
    source_project: Path | None = None,
    include_net_deletions: bool = False,
) -> tuple[dict[str, Any], list[Path]]:
    commands: dict[str, Any] = {}
    names: set[str] = set()
    path_metadata: dict[str, dict[str, Any]] = {}
    command_errors: list[str] = []

    if review_commits is not None:
        base_sha, head_sha = review_commits
        collect_commit_diff(
            project,
            run_command,
            commands,
            names,
            path_metadata,
            command_errors,
            base_sha,
            head_sha,
            review_paths,
        )
        paths = [Path(name) for name in sorted(names)]
        source_root = source_project or project
        discovery = {
            "commands": commands,
            "command_errors": command_errors,
            "path_metadata": path_metadata,
            "review_commits": {"base_sha": base_sha, "head_sha": head_sha},
        }
        return discovery, _review_sources(source_root, paths, discovery if include_net_deletions else None)

    head = run_command(["git", "rev-parse", "--verify", "HEAD"], project)
    commands["rev_parse_head"] = head
    if head["returncode"] == 0 and _head_tree_is_empty(project, run_command):
        # A commit with an empty tree gives nothing to diff against, so it is no baseline: the work
        # is still an initial full build, exactly as if HEAD did not exist yet.
        head = {**head, "returncode": 1, "stderr": "HEAD has an empty tree"}
    if head["returncode"] != 0 and (
        is_writing_workspace(project) or is_non_git_workspace(project)
    ):
        return {
            "commands": commands,
            "command_errors": [],
            "path_metadata": path_metadata,
            "review_only": "non_git_workspace",
        }, []
    if head["returncode"] == 0:
        collect_head_diff(project, run_command, commands, names, path_metadata, command_errors, review_paths,
                          include_untracked=True)
    else:
        listings = _read_listings(project, run_command, commands, command_errors, review_paths, initial=True)
        empty_diff = {"returncode": 0, "stdout": ""}
        _record_diff(
            empty_diff, empty_diff, names, path_metadata, command_errors, "git diff", listings=listings,
        )

    if head["returncode"] == 0:
        reclassify_untracked_moves(
            project,
            run_command,
            commands,
            path_metadata,
            command_errors,
            review_paths,
        )
        reclassify_untracked_copies(
            project,
            run_command,
            commands,
            path_metadata,
            command_errors,
        )

    paths = [Path(name) for name in sorted(names)]
    discovery = {
        "commands": commands,
        "command_errors": command_errors,
        "path_metadata": path_metadata,
    }
    return discovery, _review_sources(project, paths, discovery if include_net_deletions else None)


def collect_commit_diff(
    project: Path,
    run_command: CommandRunner,
    commands: dict[str, Any],
    names: set[str],
    path_metadata: dict[str, dict[str, Any]],
    command_errors: list[str],
    base_sha: str,
    head_sha: str,
    review_paths: list[str] | None = None,
) -> None:
    pathspec = _pathspec_args(review_paths)
    status = run_command(
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            "--diff-filter=ACDMRTUXB",
            base_sha,
            head_sha,
            *pathspec,
        ],
        project,
    )
    commands["commit_diff_name_status"] = status

    numstat = run_command(
        [
            "git",
            "diff",
            "--numstat",
            "-z",
            "--diff-filter=ACDMRTUXB",
            base_sha,
            head_sha,
            *pathspec,
        ],
        project,
    )
    commands["commit_diff_numstat"] = numstat
    _record_diff(status, numstat, names, path_metadata, command_errors, "git commit-range")


def _subject_run_command(
    git_project: Path,
    run_command: CommandRunner,
    review_commits: tuple[str, str] | None,
) -> CommandRunner:
    if review_commits is None:
        return run_command
    base_sha, _head_sha = review_commits

    def subject_command(command: list[str], _cwd: Path) -> dict[str, Any]:
        rewritten = [
            base_sha if argument == "HEAD" else f"{base_sha}:{argument[5:]}"
            if argument.startswith("HEAD:")
            else argument
            for argument in command
        ]
        return run_command(rewritten, git_project)

    return subject_command


def collect_head_diff(
    project: Path,
    run_command: CommandRunner,
    commands: dict[str, Any],
    names: set[str],
    path_metadata: dict[str, dict[str, Any]],
    command_errors: list[str],
    review_paths: list[str] | None = None,
    *,
    include_untracked: bool = False,
) -> None:
    pathspec = _pathspec_args(review_paths)
    status = run_command(
        ["git", "diff", "--name-status", "-z", "--diff-filter=ACDMRTUXB", "--relative", "HEAD", *pathspec],
        project,
    )
    commands["diff_name_status"] = status

    numstat = run_command(
        ["git", "diff", "--numstat", "-z", "--diff-filter=ACDMRTUXB", "--relative", "HEAD", *pathspec],
        project,
    )
    commands["diff_numstat"] = numstat
    listing_errors = []
    listings = (_read_listings(project, run_command, commands, listing_errors, review_paths, initial=False)
                if include_untracked else None)
    _record_diff(status, numstat, names, path_metadata, command_errors, "git diff", listings=listings)
    command_errors.extend(listing_errors)


def _read_listings(project, run_command, commands, errors, review_paths, *, initial: bool):
    initial_text = None
    pathspec = _pathspec_args(review_paths)
    if initial:
        tracked = run_command(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", *pathspec], project)
        commands["ls_files_initial"] = tracked
        initial_text = tracked["stdout"] if tracked["returncode"] == 0 else ""
        if tracked["returncode"] != 0:
            errors.append("git ls-files changed source discovery failed")
    untracked = run_command(["git", "ls-files", "-z", "--others", "--exclude-standard", *pathspec], project)
    commands["ls_files_untracked"] = untracked
    if untracked["returncode"] != 0:
        errors.append("git ls-files untracked source discovery failed")
        return initial_text, ""
    return initial_text, untracked["stdout"]


def _record_diff(status, numstat, names, path_metadata, command_errors, label, *, listings=None):
    status_ok = status["returncode"] == 0
    counts_ok = numstat["returncode"] == 0
    status_text = status["stdout"] if status_ok else ""
    counts_text = numstat["stdout"] if counts_ok else ""
    if not status_ok:
        command_errors.append(f"{label} changed source discovery failed")
    if not counts_ok:
        command_errors.append(f"{label} line-count discovery failed")
    decoded = None
    if any("\0" in text for text in (status_text, counts_text, *(listings or ())) if text is not None):
        payload = {"status": status_text, "numstat": counts_text, "metadata": True}
        if listings is not None:
            payload["listings"] = listings
        decoded = NativeProbe.request("--completion-probe", "structure-diff", payload)
    metadata = decoded.get("metadata") if decoded is not None else None
    listings_applied = listings is not None and decoded is not None and decoded.get("listings_applied") is True
    if isinstance(metadata, dict) and metadata and all(
        _valid_diff_metadata(path, row, listings_applied) for path, row in metadata.items()
    ):
        for path, row in metadata.items():
            record_path(names, path_metadata, path, **row)
        if listings is not None and not listings_applied:
            _record_listings(names, path_metadata, listings)
        return
    parsed = _validated_diff_records(decoded)
    if parsed is None:
        parsed = _parse_name_status(status_text), _parse_numstat(counts_text)
    statuses, counts = parsed
    for destination, code, previous in statuses:
        updates = {"status": code}
        if previous:
            updates["previous_path"] = previous
        record_path(names, path_metadata, destination, **updates)
    for destination, additions, deletions in counts:
        record_path(names, path_metadata, destination, additions=additions, deletions=deletions)
    if listings is not None:
        _record_listings(names, path_metadata, listings)


def _record_listings(names, path_metadata, listings):
    initial, untracked = listings
    if initial is not None:
        for path in _listed_paths(initial):
            record_path(names, path_metadata, path, status="A", initial_full_build=True)
    for path in _listed_paths(untracked):
        record_path(names, path_metadata, path, status="A", untracked=True, initial_full_build=initial is not None)


def _valid_diff_metadata(path: str, row, listings_applied: bool) -> bool:
    if not path or not isinstance(row, dict) or not row or row.keys() - {
        "status", "previous_path", "additions", "deletions", "untracked", "initial_full_build",
    }:
        return False
    status = row.get("status", "")
    if "status" in row and (not isinstance(status, str) or len(status) != 1 or status not in "ACDMRTUXB"):
        return False
    if "previous_path" in row:
        previous = row["previous_path"]
        if not status or not isinstance(previous, str) or not previous:
            return False
    counts = {"additions", "deletions"} & row.keys()
    if "initial_full_build" in row and (
        not listings_applied or status != "A" or type(row["initial_full_build"]) is not bool
    ):
        return False
    if "untracked" in row and (row["untracked"] is not True or "initial_full_build" not in row):
        return False
    return len(counts) != 1 and all(type(row[key]) is int and row[key] >= 0 for key in counts)


def _validated_diff_records(decoded):
    if decoded is None or set(decoded) != {"status", "numstat"}:
        return None
    statuses, counts = decoded["status"], decoded["numstat"]
    if not isinstance(statuses, list) or not isinstance(counts, list):
        return None
    if not all(isinstance(row, list) and len(row) == 3 and all(isinstance(v, str) for v in row)
               and row[0] and row[1] in "ACDMRTUXB" and len(row[1]) == 1 for row in statuses):
        return None
    if not all(isinstance(row, list) and len(row) == 3 and isinstance(row[0], str) and row[0]
               and all(type(v) is int and v >= 0 for v in row[1:]) for row in counts):
        return None
    return statuses, counts


def _listed_paths(stdout: str) -> list[str]:
    """Return the paths of a one-path-per-record ``-z`` git listing.

    Without ``-z`` git quotes any path holding a special character, so a file
    named ``we<newline>ird.py`` arrives as the literal 11-character text
    ``"we\\nird.py"``. Discovery then recorded that quoted string as a filename
    and dropped the real file from review entirely -- a silent miss in a gate
    whose whole job is to see every changed file. NUL is the one byte a path
    cannot contain, and ``-z`` output is never quoted, so the fields are the
    paths verbatim and must not be stripped.
    """

    if "\0" not in stdout:
        # Injected command runners in tests still provide the line-oriented
        # form; keep reading it for paths that carry no separator character.
        return [line.strip() for line in stdout.splitlines() if line.strip()]
    return [field for field in stdout.split("\0") if field]


def _parse_name_status(stdout: str) -> list[tuple[str, str, str]]:
    """Return (destination, status, previous) from ``git diff --name-status -z``.

    Splitting the human-readable form on tabs silently corrupts any path that
    contains one: the parser kept the fragment after the last tab and recorded a
    file that does not exist, while ``--numstat`` recorded the real path, so the
    two discovery passes disagreed and invented a phantom entry. A newline in a
    path breaks the line split the same way. NUL is the only separator no path
    can contain.
    """

    if "\0" not in stdout:
        # Injected command runners in tests still provide the line-oriented
        # form; keep reading it for paths that carry no separator character.
        records: list[tuple[str, str, str]] = []
        for line in stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                code = parts[0][:1]
                previous = parts[-2] if code in {"R", "C"} and len(parts) >= 3 else ""
                records.append((parts[-1], code, previous))
        return records

    fields = stdout.split("\0")
    records = []
    index = 0
    while index + 1 < len(fields):
        code = fields[index][:1]
        index += 1
        if not code:
            continue
        source = fields[index]
        index += 1
        if code in {"R", "C"}:
            if index >= len(fields):
                break
            records.append((fields[index], code, source))
            index += 1
        else:
            records.append((source, code, ""))
    return records


def _parse_numstat(stdout: str) -> list[tuple[str, int, int]]:
    """Return destination-path line counts from ``git diff --numstat -z``.

    A rename or copy has an empty path in its header followed by separate source
    and destination NUL fields. Human-readable numstat instead renders
    ``{old => new}``, which is not a filesystem path and cannot join the counts
    to the destination discovered by ``--name-status``.
    """

    if "\0" not in stdout:
        # Preserve compatibility with injected command runners that still
        # provide the traditional line-oriented form for ordinary paths.
        records: list[tuple[str, int, int]] = []
        for line in stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3 and parts[2]:
                records.append(
                    (parts[2], _numstat_count(parts[0]), _numstat_count(parts[1]))
                )
        return records

    fields = stdout.split("\0")
    records = []
    index = 0
    while index < len(fields):
        header = fields[index]
        index += 1
        if not header:
            continue
        parts = header.split("\t", 2)
        if len(parts) != 3:
            continue
        additions, deletions, destination = parts
        if not destination:
            if index + 1 >= len(fields):
                break
            index += 1  # source path
            destination = fields[index]
            index += 1
        if destination:
            records.append((destination, _numstat_count(additions), _numstat_count(deletions)))
    return records


def _numstat_count(value: str) -> int:
    return int(value) if value.isdigit() else 0


def reclassify_untracked_moves(
    project: Path,
    run_command: CommandRunner,
    commands: dict[str, Any],
    path_metadata: dict[str, dict[str, Any]],
    command_errors: list[str],
    review_paths: list[str] | None = None,
) -> None:
    """Recognize unstaged content-preserving moves before applying new-file gates.

    Git does not report a filesystem move as a rename until it is staged. The
    review hook still has to distinguish a moved legacy owner from hundreds of
    newly added lines without mutating the caller's index. Limit matching to
    deleted files with the same filename and require high line similarity.
    """

    deleted = run_command(
        ["git", "diff", "--name-only", "-z", "--diff-filter=D", "HEAD", *_pathspec_args(review_paths)],
        project,
    )
    commands["diff_deleted_paths"] = deleted
    if deleted["returncode"] != 0:
        command_errors.append("git diff deleted source discovery failed")
        return

    deleted_by_filename: dict[str, list[str]] = {}
    for previous_path in _listed_paths(deleted["stdout"]):
        deleted_by_filename.setdefault(Path(previous_path).name, []).append(previous_path)

    matches: list[dict[str, Any]] = []
    for current_path, metadata in path_metadata.items():
        if metadata.get("status") != "A" or metadata.get("untracked") is not True:
            continue
        candidates = deleted_by_filename.get(Path(current_path).name, [])
        match = _unstaged_source_match(project, current_path, candidates, run_command)
        if match is None:
            continue
        previous_path, similarity, additions, deletions = match
        metadata.update(
            status="R",
            previous_path=previous_path,
            additions=additions,
            deletions=deletions,
            similarity=round(similarity, 4),
        )
        matches.append(
            {
                "current_path": current_path,
                "previous_path": previous_path,
                "similarity": round(similarity, 4),
            }
        )

    commands["unstaged_move_detection"] = {
        "similarity_threshold": 0.8,
        "matches": matches,
    }


def reclassify_untracked_copies(
    project: Path,
    run_command: CommandRunner,
    commands: dict[str, Any],
    path_metadata: dict[str, dict[str, Any]],
    command_errors: list[str],
) -> None:
    """Recognize copy-first migrations while the tracked source remains in place.

    Copy-first work intentionally keeps the current runtime owner until parity is
    proven. Git therefore reports the destination as an untracked addition rather
    than a copy. Compare only remaining untracked additions against tracked HEAD
    files with the same filename and require high line similarity.
    """

    tracked = run_command(["git", "ls-files", "-z", "--cached", "--"], project)
    commands["ls_files_copy_candidates"] = tracked
    if tracked["returncode"] != 0:
        command_errors.append("git ls-files copy candidate discovery failed")
        return

    tracked_by_filename: dict[str, list[str]] = {}
    for previous_path in _listed_paths(tracked["stdout"]):
        tracked_by_filename.setdefault(Path(previous_path).name, []).append(previous_path)

    matches: list[dict[str, Any]] = []
    for current_path, metadata in path_metadata.items():
        if metadata.get("status") != "A" or metadata.get("untracked") is not True:
            continue
        candidates = [
            previous_path
            for previous_path in tracked_by_filename.get(Path(current_path).name, [])
            if previous_path != current_path
        ]
        match = _unstaged_source_match(project, current_path, candidates, run_command)
        if match is None:
            continue
        previous_path, similarity, additions, deletions = match
        metadata.update(
            status="C",
            previous_path=previous_path,
            additions=additions,
            deletions=deletions,
            similarity=round(similarity, 4),
        )
        matches.append(
            {
                "current_path": current_path,
                "previous_path": previous_path,
                "similarity": round(similarity, 4),
            }
        )

    commands["unstaged_copy_detection"] = {
        "similarity_threshold": 0.8,
        "matches": matches,
    }


def _unstaged_source_match(
    project: Path, current_path: str, candidates: list[str], run_command: CommandRunner,
) -> tuple[str, float, int, int] | None:
    if not candidates:
        return None
    try:
        current = (project / current_path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    paths, sources = [], []
    for path in candidates:
        previous = run_command(["git", "show", f"HEAD:{path}"], project)
        if previous["returncode"] == 0:
            paths.append(path)
            sources.append(previous["stdout"].splitlines())
    if not sources:
        return None
    index, matched = _best_source_match(current, sources)
    additions, deletions = len(current) - matched, len(sources[index]) - matched
    total = len(current) + len(sources[index])
    similarity = 2.0 * matched / total if total else 1.0
    if similarity < 0.8:
        return None
    return paths[index], similarity, additions, deletions


def _best_source_match(current: list[str], sources: list[list[str]]) -> tuple[int, int]:
    native = NativeProbe.request("--completion-probe", "structure-move-matching", {
        "current": current, "candidates": sources,
    })
    best = native.get("best") if native is not None else None
    if isinstance(best, list) and len(best) == 2:
        index, matched = best
        if (type(index) is int and 0 <= index < len(sources) and type(matched) is int
                and 0 <= matched <= min(len(current), len(sources[index]))):
            return index, matched
    matcher = SequenceMatcher(None, [], current, autojunk=False)
    best_index, best_matched, best_ratio = 0, 0, -1.0
    for index, source in enumerate(sources):
        matcher.set_seq1(source)
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_index, best_ratio = index, ratio
            best_matched = sum(block.size for block in matcher.get_matching_blocks())
    return best_index, best_matched


def record_path(
    names: set[str],
    path_metadata: dict[str, dict[str, Any]],
    name: str,
    **updates: Any,
) -> None:
    names.add(name)
    path_metadata.setdefault(name, {}).update(updates)


def net_deletion_findings(path_metadata: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return changed paths whose measured net line loss needs review attention.

    ``path_metadata`` carries the numstat counts for every changed path, not just
    the development sources the structural checks read, so this is the one place
    a large removal in documentation, configuration, or fixtures is observable.
    """

    findings: list[dict[str, Any]] = []
    for name in sorted(path_metadata):
        metadata = path_metadata[name]
        additions = metadata.get("additions")
        deletions = metadata.get("deletions")
        if not isinstance(additions, int) or not isinstance(deletions, int):
            continue
        net = deletions - additions
        if net >= REVIEW_NET_DELETION_LIMIT:
            findings.append(
                {"path": name, "additions": additions, "deletions": deletions, "net": net}
            )
    return findings


def _pathspec_args(review_paths: list[str] | None) -> list[str]:
    paths = [path.strip() for path in (review_paths or []) if path.strip()]
    return ["--", *paths] if paths else ["--"]


def _review_sources(
    project: Path, paths: list[Path], discovery: dict[str, Any] | None = None,
) -> list[Path]:
    if paths and NativeProbe.available() and not _declares_generated(project):
        payload = {
            "project": str(project),
            "paths": [{"path": str(path), "suffix": path.suffix.lower()} for path in paths],
            "policy": {
                "extensions": sorted(REVIEW_SOURCE_EXTENSIONS),
                "skipped": sorted(REVIEW_SKIP_PARTS),
                "generated": sorted(REVIEW_GENERATED_PARTS),
                "config_names": sorted(REVIEW_CONFIG_FILE_NAMES),
                "config_suffixes": REVIEW_CONFIG_SUFFIXES,
            },
        }
        if discovery is not None:
            counts = []
            for path, metadata in discovery["path_metadata"].items():
                additions, deletions = metadata.get("additions"), metadata.get("deletions")
                if isinstance(additions, int) and isinstance(deletions, int):
                    counts.append([path, additions, deletions])
            payload["net_deletions"] = {"limit": REVIEW_NET_DELETION_LIMIT, "counts": counts}
        native = NativeProbe.request("--completion-probe", "structure-source-paths", payload)
        if native is not None and "selected" in native:
            selected = native["selected"]
            if (isinstance(selected, list) and len(selected) == len(paths)
                    and all(value is None or type(value) is bool for value in selected)):
                deletions = native.get("net_deletions")
                if discovery is not None and isinstance(deletions, list) and all(
                    isinstance(row, dict) and set(row) == {"path", "additions", "deletions", "net"}
                    and isinstance(row["path"], str) and row["path"] in discovery["path_metadata"]
                    and all(type(row[key]) is int for key in ("additions", "deletions", "net"))
                    for row in deletions
                ):
                    discovery["_net_deletions"] = deletions
                return [
                    path for path, keep in zip(paths, selected)
                    if (review_source_path(project, path) if keep is None else keep)
                ]
    return [path for path in paths if review_source_path(project, path)]


def review_source_path(project: Path, path: Path) -> bool:
    absolute = project / path
    return (
        path.suffix.lower() in REVIEW_SOURCE_EXTENSIONS
        and not any(part in REVIEW_SKIP_PARTS for part in path.parts)
        and not config_or_generated_path(path)
        and not pinned_third_party_source(project, path)
        and not linguist_generated_path(project, path)
        and absolute.exists()
        and absolute.is_file()
    )


def config_or_generated_path(path: Path) -> bool:
    lower_parts = {part.lower() for part in path.parts}
    if lower_parts.intersection(REVIEW_GENERATED_PARTS):
        return True

    name = path.name.lower()
    # Pigeon code-generator schemas: one input file must declare every API type.
    if name.endswith(".dart") and path.parent.name == "pigeons":
        return True
    return name in REVIEW_CONFIG_FILE_NAMES or name.endswith(REVIEW_CONFIG_SUFFIXES)


def pinned_third_party_source(project: Path, path: Path) -> bool:
    """Recognize an isolated vendor package only when provenance is present."""
    lower_parts = [part.lower() for part in path.parts]
    try:
        boundary = lower_parts.index("third_party")
    except ValueError:
        return False
    if boundary + 1 >= len(path.parts):
        return False

    package = project.joinpath(*path.parts[: boundary + 2])
    readme = package / "README.md"
    license_file = package / "LICENSE"
    if not readme.is_file() or not license_file.is_file():
        return False
    try:
        provenance = readme.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return all(marker in provenance for marker in ("upstream", "commit", "sha-256", "license"))


def test_exempt_path(path: Path) -> bool:
    lower_parts = {part.lower() for part in path.parts}
    if lower_parts.intersection(TEST_PATH_PARTS):
        return True

    stem = path.stem
    lower_stem = stem.lower()
    return (
        lower_stem.startswith(("test_", "test-"))
        or lower_stem.endswith(("_test", "-test", ".test", "_tests", "-tests", ".tests"))
        or lower_stem.endswith(("_spec", "-spec", ".spec", "_specs", "-specs", ".specs"))
        or stem.endswith(("Test", "Tests", "Spec", "Specs"))
    )


def check_file_size(
    path: Path,
    lines: list[str],
    max_file_lines: int,
    metadata: dict[str, Any],
    result: dict[str, Any],
    *,
    max_added_lines: int = REVIEW_ADDED_LINE_LIMIT,
    review_warning_file_lines: int = REVIEW_FILE_REVIEW_WARNING_LIMIT,
) -> None:
    _check_file_size(path, len(lines), max_file_lines, metadata, result,
                     max_added_lines=max_added_lines, review_warning_file_lines=review_warning_file_lines)


def _file_findings(
    rows: list[dict[str, Any]], *, source_layout: dict[str, Any] | None = None,
) -> tuple[list, dict[str, Any] | None]:
    if not rows and (source_layout is None or not source_layout["paths"]):
        return [], None
    payload = {"files": rows}
    if source_layout is not None:
        payload["source_layout"] = source_layout
    native = NativeProbe.request("--completion-probe", "structure-file-size", payload)
    expected = {"findings", "source_layout"} if source_layout is not None else {"findings"}
    if native is not None and set(native) == expected:
        findings = native["findings"]
        if (isinstance(findings, list) and len(findings) == len(rows)
                and all(isinstance(row, list) and len(row) == 2
                        and all(isinstance(items, list) and all(isinstance(item, str) for item in items)
                                for items in row) for row in findings)):
            layout = native.get("source_layout")
            if isinstance(layout, dict) and {"added", "copied", "warnings"} <= layout.keys():
                if (all(type(layout[key]) is int and layout[key] >= 0 for key in ("added", "copied"))
                        and isinstance(layout["warnings"], list)
                        and all(isinstance(warning, str) for warning in layout["warnings"])
                        and all(value is None or isinstance(value, list)
                                and all(isinstance(finding, str) for finding in value)
                                for value in (layout.get("package_failures"), layout.get("owner_failures")))):
                    return findings, layout
            return findings, None
    findings = []
    for row in rows:
        result: dict[str, list[str]] = {"failures": [], "warnings": []}
        _check_file_size(**{key: value for key, value in row.items()
                            if key not in {"actions", "blocks", "block_spans"}},
                         result=result)
        action_failures, action_warnings = row.get("actions", ([], []))
        result["failures"].extend(action_failures)
        result["warnings"].extend(action_warnings)
        if "blocks" in row:
            block_failures, block_warnings = _block_review_findings(row["path"], row["blocks"])
            result["failures"].extend(block_failures)
            result["warnings"].extend(block_warnings)
        elif "block_spans" in row:
            prepared = row["block_spans"]
            current = _prepared_blocks(row["path"], prepared, prepared["limit"])
            block_failures, block_warnings = _block_review_findings(row["path"], {
                "limit": prepared["limit"], "initial": prepared["initial"], "current": current, "previous": [],
            })
            result["failures"].extend(block_failures)
            result["warnings"].extend(block_warnings)
        findings.append((result["failures"], result["warnings"]))
    return findings, None


def _check_file_size(
    path: Path | str,
    line_count: int,
    max_file_lines: int,
    metadata: dict[str, Any],
    result: dict[str, Any],
    *,
    max_added_lines: int,
    review_warning_file_lines: int,
) -> None:
    if metadata.get("initial_full_build"):
        if line_count > review_warning_file_lines:
            result["warnings"].append(
                f"{path} is an initial full-build file with {line_count} lines (no Git HEAD commit); "
                "per-commit line-addition caps do not block unbound full builds, "
                "but keep one clear module owner per file"
            )
        return
    status = metadata.get("status", "")
    added_lines = metadata.get("additions")
    if added_lines is None:
        added_lines = line_count if status == "A" else 0
    deleted_lines = metadata.get("deletions", 0)
    is_net_reducing_rewrite = status != "A" and deleted_lines > added_lines

    if status == "A" and line_count > max_file_lines:
        result["failures"].append(
            f"{path} is a new development source/style file with {line_count} lines; "
            f"new-file hard limit is {max_file_lines}; split by responsibility before approval"
        )
    if added_lines > max_added_lines and is_net_reducing_rewrite:
        result["warnings"].append(
            f"{path} adds {added_lines} lines but deletes {deleted_lines} lines, so the file "
            "is not growing; structure-review evidence is required instead of an addition-limit failure"
        )
    elif added_lines > max_added_lines:
        result["failures"].append(
            f"{path} adds {added_lines} lines in one development source/style file; "
            f"per-file addition limit is {max_added_lines}; split the change before approval. "
            "Move independently reviewable previews, demos, or samples to a subject-named "
            "sibling file, or extract the nearest real behavior owner"
        )
    if status != "A" and line_count > max_file_lines and added_lines > 0:
        result["warnings"].append(
            f"{path} is already over {max_file_lines} lines and adds {added_lines} line(s); "
            "structure-review evidence is required and the new responsibility should be extracted "
            "when it expands the public owner surface"
        )
    elif line_count > review_warning_file_lines:
        result["warnings"].append(
            f"{path} is a changed development source/style file with {line_count} lines; "
            f"review-pressure limit is {review_warning_file_lines}; "
            "structure-review evidence is required before approving more behavior"
        )


def large_block_failures(path: Path, lines: list[str], max_block_lines: int) -> list[str]:
    failures, _warnings = large_block_findings(
        Path("."),
        path,
        lines,
        max_block_lines,
        {"status": "A"},
        lambda _command, _cwd: {"returncode": 1, "stdout": "", "stderr": ""},
    )
    return failures


def large_block_findings(
    project: Path,
    path: Path,
    lines: list[str],
    max_block_lines: int,
    metadata: dict[str, Any],
    run_command: CommandRunner,
) -> tuple[list[str], list[str]]:
    facts = _block_review_facts(project, path, lines, max_block_lines, metadata, run_command)
    return _block_review_findings(str(path), facts) if facts else ([], [])


def _block_review_facts(
    project: Path,
    path: Path,
    lines: list[str],
    max_block_lines: int,
    metadata: dict[str, Any],
    run_command: CommandRunner,
) -> dict[str, Any] | None:
    current = oversized_blocks(path, lines, max_block_lines)
    if not current:
        return None
    initial = bool(metadata.get("initial_full_build"))
    previous = [] if initial else previous_oversized_blocks(project, path, metadata, run_command, max_block_lines)
    return {
        "initial": initial,
        "limit": max_block_lines,
        "current": [{key: value for key, value in record.items() if key != "path"} for record in current],
        "previous": [{"label": record["label"], "span": record["span"]} for record in previous],
    }


def _attach_block_baselines(project: Path, files: list[dict[str, Any]], run_command: CommandRunner) -> None:
    existing = [
        row for row in files
        if "block_spans" in row and not row["block_spans"]["initial"] and row["metadata"].get("status") != "A"
    ]
    if not existing:
        return
    inputs = [row.pop("block_spans") for row in existing]
    native = NativeProbe.request("--completion-probe", "structure-block-spans", {"files": inputs})
    spans = native.get("blocks") if native is not None and set(native) == {"blocks"} else None
    if not (isinstance(spans, list) and len(spans) == len(inputs) and all(
        isinstance(blocks, list) and all(
            isinstance(block, dict) and set(block) == {"label", "line", "span"}
            and isinstance(block["label"], str) and type(block["line"]) is int and block["line"] > 0
            and type(block["span"]) is int and block["span"] > 0 for block in blocks
        ) for blocks in spans
    )):
        spans = [_prepared_blocks(row["path"], prepared, prepared["limit"])
                 for row, prepared in zip(existing, inputs)]
    for row, prepared, current in zip(existing, inputs, spans):
        if not current:
            continue
        limit = prepared["limit"]
        baseline = _previous_block_spans(project, Path(row["path"]), row["metadata"], run_command)
        facts = {"initial": False, "limit": limit, "current": current, "previous": []}
        if baseline is not None:
            facts["previous_spans"] = {**baseline, "limit": limit}
        row["blocks"] = facts


def _block_review_findings(path: str, facts: dict[str, Any]) -> tuple[list[str], list[str]]:
    previous = facts["previous"]
    if "previous_spans" in facts:
        previous = _prepared_blocks(path, facts["previous_spans"], facts["limit"])
    previous_by_label = {str(record["label"]): record for record in previous}
    failures: list[str] = []
    warnings: list[str] = []
    for data in facts["current"]:
        record = {**data, "path": path}
        previous_record = previous_by_label.get(str(record["label"]))
        if facts["initial"]:
            warnings.append(initial_full_build_block_warning(record, facts["limit"]))
        elif previous_record and int(record["span"]) <= int(previous_record["span"]):
            warnings.append(preexisting_block_warning(record, int(previous_record["span"]), facts["limit"]))
        else:
            failures.append(block_failure(record, facts["limit"]))
    return failures, warnings


def previous_oversized_blocks(
    project: Path,
    path: Path,
    metadata: dict[str, Any],
    run_command: CommandRunner,
    max_block_lines: int,
) -> list[dict[str, Any]]:
    prepared = _previous_block_spans(project, path, metadata, run_command)
    return _prepared_blocks(path, prepared, max_block_lines) if prepared is not None else []


def _previous_block_spans(
    project: Path, path: Path, metadata: dict[str, Any], run_command: CommandRunner,
) -> dict[str, Any] | None:
    if metadata.get("status") == "A":
        return None
    previous_path = str(metadata.get("previous_path") or path.as_posix())
    previous = run_command(["git", "show", f"HEAD:{previous_path}"], project)
    if previous.get("returncode") != 0:
        return None
    return _block_span_input(path, str(previous.get("stdout") or "").splitlines())


def oversized_blocks(path: Path, lines: list[str], max_block_lines: int) -> list[dict[str, Any]]:
    return _prepared_blocks(path, _prepare_block_spans(path, lines), max_block_lines)


def _block_span_input(path: Path, lines: list[str]) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return {"kind": "python-source", "lines": lines, "unicode": unicodedata.unidata_version}
    if suffix in REVIEW_STYLE_EXTENSIONS:
        return {"kind": "style-source", "lines": lines}
    return {"kind": "brace-source", "lines": lines, "unicode": unicodedata.unidata_version}


def _prepare_block_spans(path: Path, lines: list[str]) -> dict[str, Any]:
    if path.suffix.lower() == ".py":
        starts = []
        levels = []
        for index, line in enumerate(lines):
            stripped = line.strip()
            levels.append(
                len(line) - len(line.lstrip(" ")) if stripped and not stripped.startswith(("#", "@"))
                else None
            )
            match = PYTHON_BLOCK_RE.match(line)
            if match:
                starts.append((index, match.group(2)))
        return {"kind": "indent", "levels": levels, "starts": starts}

    starts = []
    structural_lines = mask_brace_literals(lines)
    for index, line in enumerate(structural_lines):
        stripped = line.strip()
        if "{" in stripped and starts_review_block(path, stripped):
            starts.append((index, lines[index].strip()[:80].replace("`", "'")))
    return {
        "kind": "brace", "levels": [line.count("{") - line.count("}") for line in structural_lines],
        "starts": starts,
    }


def _prepared_blocks(path: Path | str, prepared: dict[str, Any], max_block_lines: int) -> list[dict[str, Any]]:
    if "lines" in prepared:
        prepared = _prepare_block_spans(Path(path), prepared["lines"])
    blocks = []
    levels = prepared["levels"]
    for start, label in prepared["starts"]:
        span = len(levels) - start
        if prepared["kind"] == "indent":
            for index in range(start + 1, len(levels)):
                if levels[index] is not None and levels[index] <= levels[start]:
                    span = index - start
                    break
        else:
            balance = 0
            for index in range(start, len(levels)):
                balance += levels[index]
                if balance <= 0:
                    span = index - start + 1
                    break
        if span > max_block_lines:
            blocks.append(block_record(path, start, label, span))
    return blocks


def mask_brace_literals(lines: list[str]) -> list[str]:
    """Ignore C-style comments and quoted text without moving source lines.

    Keep the existing structural heuristic for other syntax (including template
    interpolation); this is not a language parser. Ordinary quotes cannot span
    an unescaped newline, preventing a prose apostrophe from masking the file.
    """
    pattern = (
        r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\[\s\S]|[^"\\\n])*"'
        r"|'(?:\\[\s\S]|[^'\\\n])*'"
    )
    return re.sub(pattern, lambda match: re.sub(r"[^\n]", " ", match.group()),
                  "\n".join(lines)).split("\n")


def starts_review_block(path: Path, stripped_line: str) -> bool:
    if path.suffix.lower() in REVIEW_STYLE_EXTENSIONS:
        return bool(STYLE_BLOCK_RE.match(stripped_line))
    if BRACE_TYPE_BLOCK_RE.match(stripped_line):
        return False
    return bool(BRACE_BLOCK_RE.match(stripped_line))


def block_record(path: Path | str, start_index: int, label: str, span: int) -> dict[str, Any]:
    return {
        "path": path,
        "line": start_index + 1,
        "label": label,
        "span": span,
    }


def block_failure(record: dict[str, Any], max_block_lines: int) -> str:
    return (
        f"{record['path']}:{record['line']} block `{record['label']}` spans {record['span']} lines; "
        f"limit is {max_block_lines}; extract a cohesive private step with a focused check "
        "until the block is within the limit, or use an explicitly reviewed "
        "project-specific max-function-lines limit; "
        "structure-review prose alone does not bypass this hard gate"
    )


def initial_full_build_block_warning(record: dict[str, Any], max_block_lines: int) -> str:
    return (
        f"{record['path']}:{record['line']} block `{record['label']}` spans {record['span']} lines "
        f"in an initial full-build workspace (no Git HEAD commit); limit is {max_block_lines}; "
        "structure-review evidence is required, and cohesive private helpers should be extracted "
        "before incremental commits"
    )


def preexisting_block_warning(
    record: dict[str, Any],
    previous_span: int,
    max_block_lines: int,
) -> str:
    return (
        f"{record['path']}:{record['line']} block `{record['label']}` is a pre-existing "
        f"oversized unit spanning {record['span']} lines (previously {previous_span}); "
        f"limit is {max_block_lines}; structure-review evidence is required, but this "
        "does not block the current scoped change unless the diff grows the unit or adds "
        "a new responsibility"
    )
