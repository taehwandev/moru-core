"""Read-only Git proof for a reviewed staged unit and its local integration.

Owner: LocalDeliveryProof. Allowed imports: stdlib and source-bound identity probe.
Git is an injected reader. Forbidden: Git writes, providers and inferred authority.
Callers/tests: pending publication; test_agent_local_delivery.
Verification: unrelated commits, foreign repositories and absent target refs fail.
"""

from __future__ import annotations

import hashlib
import json
import locale
import re
from pathlib import Path

from agent_worktree_fingerprint import git_output
from support.native_probe_transport import NativeProbe


class LocalDeliveryProof:
    CONTRACT = "staged_v1"
    INTEGRATION = "publication.integrate"
    UNBORN = "unborn"
    _MAX_LISTING = 8 * 1024 * 1024

    @staticmethod
    def _identity(output: str | None, *, index: bool = False) -> str:
        if output is None or len(output) > LocalDeliveryProof._MAX_LISTING:
            raise ValueError("Git tree cannot be read within the local proof budget")
        entries = []
        for entry in output.split("\0"):
            if not entry:
                continue
            metadata, path = entry.split("\t", 1)
            parts = metadata.split()
            if len(parts) != 3 or (index and parts[2] != "0"):
                raise ValueError("Git index is unmerged or malformed")
            mode, oid = (parts[0], parts[1]) if index else (parts[0], parts[2])
            entries.append((path, mode, oid))
        encoded = json.dumps(sorted(entries), ensure_ascii=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _common(project: Path, git) -> str:
        common = git(project, "rev-parse", "--git-common-dir")
        if not common:
            raise ValueError("Git repository identity is unavailable")
        return str((project / common).resolve())

    @classmethod
    def capture(cls, project: Path, base: str, source: str, items: list, git, *, native: bool = False) -> dict:
        initial = base == cls.UNBORN
        if not initial and native and (proof := _prepare_native(project, base, source, items)) is not None:
            return proof
        if git(project, 'diff', '--no-ext-diff', '--no-textconv', '--quiet', '--exit-code') is None:
            raise ValueError('tracked worktree content must match the reviewed index')
        original_listing = "" if initial else git(project, "ls-tree", "-r", "-z", base)
        staged, original = _capture_identities(git(project, "ls-files", "--stage", "-z"), original_listing)
        commit = any(item["checkpoint"] == "publication.commit" for item in items)
        if initial and (not commit or any(item["checkpoint"].startswith(cls.INTEGRATION + "/") for item in items)):
            raise ValueError("unborn branch proof requires a first commit without local integration")
        if commit and staged == original:
            raise ValueError("stage the reviewed changes before declaring a post-finish commit")
        if not commit and staged != original:
            raise ValueError("declare a local commit before integrating staged changes")
        targets = {}
        for item in items:
            name = item["checkpoint"]
            if not name.startswith(cls.INTEGRATION + "/"):
                continue
            target = name.partition("/")[2]
            if target == source or git(project, "check-ref-format", "refs/heads/" + target) is None:
                raise ValueError("local integration needs a valid different target branch")
            head = git(project, "rev-parse", "--verify", "refs/heads/" + target)
            if not head:
                raise ValueError("local integration target must already exist")
            targets[target] = head
        if initial:
            unchanged = _is_unborn(project) and git(project, "symbolic-ref", "--short", "HEAD") == source
        else:
            unchanged = git(project, "rev-parse", "HEAD") == base
        if not unchanged:
            raise ValueError("HEAD changed while preparing local delivery")
        return dict(project=str(project.resolve()), common=cls._common(project, git),
                    staged_sha256=staged, commit_declared=commit, targets=targets)

    @classmethod
    def _committed(cls, project: Path, proof: dict, base: str, source: str, expected: str, git) -> str:
        head = git(project, 'rev-parse', '--verify', 'refs/heads/' + source)
        if base == cls.UNBORN:
            return _first_commit(project, head, proof, expected, git)
        heads = [head] if head else [git(project, 'rev-parse', '--verify', 'refs/heads/' + target)
                                    for target in proof['targets']]
        heads = [value for value in heads if value and git(project, 'merge-base', '--is-ancestor', base, value) is not None]
        if not heads:
            raise ValueError('source or prepared target no longer contains the base')
        if not proof['commit_declared']:
            return base
        cached = proof.get('reviewed_commit')
        if not (cached and re.fullmatch(r'[0-9a-f]{40,64}', cached)
                and git(project, 'merge-base', '--is-ancestor', base, cached) is not None
                and any(git(project, 'merge-base', '--is-ancestor', cached, h) is not None for h in heads)):
            cached = ""
        return _search_commit(project, base, heads, cached, expected, git)

    @classmethod
    def observe(cls, project: Path, record: dict, checkpoint: str, git, *, native: bool = False) -> tuple[str, str]:
        try:
            proof = record["local_delivery"]
            initial = record["base_head"] == cls.UNBORN
            if not initial and native and (result := _observe_native(project, proof, record, checkpoint)) is not None:
                return result
            if proof["project"] != str(project.resolve()) or proof["common"] != cls._common(project, git):
                return "", "local delivery belongs to a different repository or checkout"
            expected, base, source = proof["staged_sha256"], record["base_head"], record["source_branch"]
            valid_base = initial or re.fullmatch(r"[0-9a-f]{40,64}", base)
            if not re.fullmatch(r"[0-9a-f]{64}", expected) or not valid_base:
                return "", "local delivery proof is malformed"
            approved = cls._committed(project, proof, base, source, expected, git)
            if not approved:
                return "", "the reviewed staged content has not been observed in a commit"
            if checkpoint.startswith(cls.INTEGRATION + "/"):
                target = checkpoint.partition("/")[2]
                if target not in proof["targets"]:
                    return "", "local integration target was not prepared"
                current = git(project, "rev-parse", "--verify", "refs/heads/" + target)
                if not current or git(project, "merge-base", "--is-ancestor", approved, current) is None:
                    return "", "target branch does not contain the reviewed commit"
                return f"target {target} contains reviewed commit {approved}", ""
            if checkpoint != "publication.commit":
                return "", "not a local delivery checkpoint"
            return f"reviewed staged content committed as {approved}", ""
        except (OSError, ValueError, TypeError, KeyError):
            return "", "local delivery proof cannot be verified"


def _is_unborn(project: Path) -> bool:
    try:
        return git_output(project, "rev-parse", "--verify", "HEAD").strip() == LocalDeliveryProof.UNBORN
    except RuntimeError:
        return False


def _is_root_commit(project: Path, head: str, git) -> bool:
    commit = git(project, "--no-replace-objects", "cat-file", "commit", head)
    if not commit:
        return False
    headers = commit.partition("\n\n")[0].splitlines()
    return not any(line.startswith("parent ") for line in headers)


def _first_commit(project: Path, head: str | None, proof: dict, expected: str, git) -> str:
    if not head or not proof["commit_declared"] or proof["targets"]:
        return ""
    reviewed = proof.get("reviewed_commit")
    if reviewed:
        if (not re.fullmatch(r"[0-9a-f]{40,64}", reviewed)
                or git(project, "--no-replace-objects", "merge-base", "--is-ancestor", reviewed, head) is None):
            return ""
        head = reviewed
    if not _is_root_commit(project, head, git):
        return ""
    committed = LocalDeliveryProof._identity(git(project, "--no-replace-objects", "ls-tree", "-r", "-z", head))
    return head if committed == expected else ""


def _capture_identities(index: str | None, base: str | None) -> tuple[str, str]:
    if index is not None and base is not None and len(index) + len(base) <= 1024 * 1024:
        result = NativeProbe.request(
            "--completion-probe", "staged-v1", {"index": index, "base": base},
        )
        if (result is not None and set(result) == {"staged", "base"}
                and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                        for value in result.values())):
            return result["staged"], result["base"]
    return LocalDeliveryProof._identity(index, index=True), LocalDeliveryProof._identity(base)


def _observe_native(project, proof, record, checkpoint):
    if type(proof) is not dict:
        return None
    targets = proof.get("targets")
    declared = proof.get("commit_declared")
    if (type(targets) is not dict or type(declared) is not bool
            or locale.getpreferredencoding(False).lower() != "utf-8"):
        return None
    result = NativeProbe.request(
        "--completion-probe", "staged-v1-observe",
        {"project": str(project), "recorded_project": proof.get("project"), "recorded_common": proof.get("common"),
         "base": record.get("base_head"), "source": record.get("source_branch"), "targets": list(targets),
         "cached": proof.get("reviewed_commit") or "", "expected": proof.get("staged_sha256"),
         "checkpoint": checkpoint, "commit_declared": declared},
    )
    if result is not None and set(result) == {"observation", "reason"}:
        observation, reason = result["observation"], result["reason"]
        if isinstance(observation, str) and isinstance(reason, str) and bool(observation) != bool(reason):
            return observation, reason
    return None


def _prepare_native(project, base, source, items):
    if (locale.getpreferredencoding(False).lower() != "utf-8"
            or any(type(item) is not dict or type(item.get("checkpoint")) is not str for item in items)):
        return None
    result = NativeProbe.request(
        "--completion-probe", "staged-v1-prepare",
        {"project": str(project), "base": base, "source": source,
         "checkpoints": [item["checkpoint"] for item in items]},
    )
    if result is None:
        return None
    if set(result) == {"reason"} and isinstance(result["reason"], str) and result["reason"]:
        raise ValueError(result["reason"])
    if set(result) == {"proof"} and isinstance(result["proof"], dict):
        return result["proof"]
    return None


def _search_commit(project, base, heads, cached, expected, git):
    if cached and LocalDeliveryProof._identity(git(project, 'ls-tree', '-r', '-z', cached)) == expected:
        return cached
    for head in heads:
        candidates = git(project, 'rev-list', '--reverse', '--ancestry-path', base + '..' + head)
        if candidates is None or len(candidates) > 4 * 1024 * 1024:
            raise ValueError('local commit history exceeds the observation budget')
        for candidate in candidates.splitlines()[:64]:
            if LocalDeliveryProof._identity(git(project, 'ls-tree', '-r', '-z', candidate)) == expected:
                return candidate
    return ''
