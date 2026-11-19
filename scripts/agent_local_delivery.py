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

from support.native_probe_transport import NativeProbe


class LocalDeliveryProof:
    CONTRACT = "staged_v1"
    INTEGRATION = "publication.integrate"
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
    def capture(cls, project: Path, base: str, source: str, items: list, git) -> dict:
        if git(project, 'diff', '--no-ext-diff', '--no-textconv', '--quiet', '--exit-code') is None:
            raise ValueError('tracked worktree content must match the reviewed index')
        staged, original = _capture_identities(
            git(project, "ls-files", "--stage", "-z"), git(project, "ls-tree", "-r", "-z", base),
        )
        commit = any(item["checkpoint"] == "publication.commit" for item in items)
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
        if git(project, "rev-parse", "HEAD") != base:
            raise ValueError("HEAD changed while preparing local delivery")
        return dict(project=str(project.resolve()), common=cls._common(project, git),
                    staged_sha256=staged, commit_declared=commit, targets=targets)

    @classmethod
    def _committed(cls, project: Path, proof: dict, base: str, source: str, expected: str, git) -> str:
        head = git(project, 'rev-parse', '--verify', 'refs/heads/' + source)
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
            if proof["project"] != str(project.resolve()) or proof["common"] != cls._common(project, git):
                return "", "local delivery belongs to a different repository or checkout"
            expected, base, source = proof["staged_sha256"], record["base_head"], record["source_branch"]
            if not re.fullmatch(r"[0-9a-f]{64}", expected) or not re.fullmatch(r"[0-9a-f]{40,64}", base):
                return "", "local delivery proof is malformed"
            if native and (result := _observe_native(project, proof, base, source, expected, checkpoint)) is not None:
                return result
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


def _observe_native(project, proof, base, source, expected, checkpoint):
    targets = proof.get("targets")
    declared = proof.get("commit_declared")
    if (type(targets) is not dict or type(declared) is not bool
            or locale.getpreferredencoding(False).lower() != "utf-8"):
        return None
    result = NativeProbe.request(
        "--completion-probe", "staged-v1-observe",
        {"project": str(project), "base": base, "source": source, "targets": list(targets),
         "cached": proof.get("reviewed_commit") or "", "expected": expected,
         "checkpoint": checkpoint, "commit_declared": declared},
    )
    if result is not None and set(result) == {"observation", "reason"}:
        observation, reason = result["observation"], result["reason"]
        if isinstance(observation, str) and isinstance(reason, str) and bool(observation) != bool(reason):
            return observation, reason
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
