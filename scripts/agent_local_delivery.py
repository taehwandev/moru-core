"""Read-only Git proof for a reviewed staged unit and its local integration.

Owner: LocalDeliveryProof. Allowed imports: stdlib; Git is an injected reader.
Forbidden: Git writes, subprocess/provider execution and inferred authority.
Callers/tests: pending publication; test_agent_local_delivery.
Verification: unrelated commits, foreign repositories and absent target refs fail.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


class LocalDeliveryProof:
    CONTRACT = "staged_v1"
    INTEGRATION = "publication.integrate"

    @staticmethod
    def _identity(output: str | None, *, index: bool = False) -> str:
        if output is None or len(output) > 8 * 1024 * 1024:
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
        staged = cls._identity(git(project, "ls-files", "--stage", "-z"), index=True)
        original = cls._identity(git(project, "ls-tree", "-r", "-z", base))
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
        if cached:
            if (re.fullmatch(r'[0-9a-f]{40,64}', cached)
                    and git(project, 'merge-base', '--is-ancestor', base, cached) is not None
                    and any(git(project, 'merge-base', '--is-ancestor', cached, h) is not None for h in heads)
                    and cls._identity(git(project, 'ls-tree', '-r', '-z', cached)) == expected):
                return cached
        for head in heads:
            candidates = git(project, 'rev-list', '--reverse', '--ancestry-path', base + '..' + head)
            if candidates is None or len(candidates) > 4 * 1024 * 1024:
                raise ValueError('local commit history exceeds the observation budget')
            for candidate in candidates.splitlines()[:64]:
                if cls._identity(git(project, 'ls-tree', '-r', '-z', candidate)) == expected:
                    return candidate
        return ''

    @classmethod
    def observe(cls, project: Path, record: dict, checkpoint: str, git) -> tuple[str, str]:
        try:
            proof = record["local_delivery"]
            if proof["project"] != str(project.resolve()) or proof["common"] != cls._common(project, git):
                return "", "local delivery belongs to a different repository or checkout"
            expected, base, source = proof["staged_sha256"], record["base_head"], record["source_branch"]
            if not re.fullmatch(r"[0-9a-f]{64}", expected) or not re.fullmatch(r"[0-9a-f]{40,64}", base):
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
