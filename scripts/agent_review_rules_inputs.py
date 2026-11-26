"""Conservative content binding for a separate shared review-rules checkout."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

from agent_execution_capsule_state import git_repository_root, observed_git_state
from agent_worktree_fingerprint import git_output, worktree_signature


# These own shell admission, not review/finish acceptance. Unknown production
# files remain included. Do not grow this set from an agent's prose claim.
_ADMISSION_ONLY = frozenset({
    "scripts/claude_bash_http.py", "scripts/claude_bash_readonly.py",
    "scripts/claude_bash_git.py", "scripts/claude_bash_paths.py",
    "scripts/claude_bash_syntax.py",
})


def review_rules_inputs(project: Path, rules: Path) -> str | None:
    """Return the legacy input digest without a documentation exception."""
    return review_rules_digests(project, rules)[0]


def _admission_or_test(name: str) -> bool:
    return name in _ADMISSION_ONLY or name.startswith("tests/")


def _optional_document(name: str, required_docs: set[str]) -> bool:
    path = Path(name)
    reserved = {"scripts", "native", "hooks", "hook", "workflows", "workflow", "commands"}
    return (path.suffix == ".md" and name not in required_docs
            and path.name not in {"AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CODEX.md"}
            and not any(part.startswith(".") or part in reserved for part in path.parts))


def _bind_git_entries(rules, head, required_docs, digest, protected):
    # Bind the base tree and the index separately from working file bytes. An
    # unstaged restore must not conceal a staged validator or executable mode.
    for args in (("ls-tree", "-rz", head), ("ls-files", "--stage", "-z")):
        for target in (digest, protected):
            target.update(args[0].encode() + b"\0")
        for entry in git_output(rules, *args).split("\0"):
            if not entry:
                continue
            metadata, name = entry.split("\t", 1)
            encoded = entry.encode() + b"\0"
            if not _admission_or_test(name):
                digest.update(encoded)
            if not metadata.startswith("100644 ") or not _optional_document(name, required_docs):
                protected.update(encoded)


def review_rules_digests(
    project: Path, rules: Path, required_docs: set[str] | None = None,
) -> tuple[str | None, str | None]:
    """Return the review digest and its optional-doc comparison from one bounded scan.

    Failure to inspect is never permission to reuse. Without a bound document
    manifest preserve the legacy digest for existing receipts and callers.
    """
    try:
        rules = rules.resolve()
        if git_repository_root(project) == git_repository_root(rules):
            return None, None
        if git_repository_root(rules) != rules.resolve():
            return None, None  # Subdirectory rule roots retain the conservative path.
        # The opening state may be the one this hook already observed; the
        # closing check below always reads afresh, so a tree that moved since
        # that observation fails the comparison and nothing is reused.
        before, signature = observed_git_state(rules) or (
            git_output(rules, "rev-parse", "HEAD").strip(),
            worktree_signature(rules),
        )
        paths = sorted(set(git_output(
            rules, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
        ).split("\0")) - {""})
        digest = hashlib.sha256(b"review-rules-inputs-v1\0")
        protected = hashlib.sha256(b"review-protected-inputs-v1\0") if required_docs else None
        if required_docs:
            _bind_git_entries(rules, before, required_docs, digest, protected)
        budget = 64 * 1024 * 1024
        for name in paths:
            included = not _admission_or_test(name)
            if not included and protected is None:
                continue
            path = rules / name
            try:
                info = path.lstat()
            except FileNotFoundError:
                value = b"deleted\0"
                executable = False
            else:
                if not stat.S_ISREG(info.st_mode) or path.parent.resolve() != path.parent.absolute():
                    return None, None
                budget -= info.st_size
                if budget < 0:
                    return None, None
                content = hashlib.sha256(path.read_bytes()).digest()
                if path.lstat() != info:
                    return None, None
                value = str(stat.S_IMODE(info.st_mode)).encode() + b"\0" + content
                executable = bool(info.st_mode & 0o111)
            entry = name.encode() + b"\0" + value
            if included:
                digest.update(entry)
            if protected is not None and (executable or not _optional_document(name, required_docs)):
                protected.update(entry)
        if (git_output(rules, "rev-parse", "HEAD").strip() != before
                or worktree_signature(rules) != signature):
            return None, None
        return digest.hexdigest(), protected.hexdigest() if protected is not None else None
    except (OSError, RuntimeError, ValueError):
        return None, None
