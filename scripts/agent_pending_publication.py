"""Keep declared post-finish commit/push visible until Git itself shows it happened.

Owner: pending publication items of a finished `commit` run. A
`publication.commit` / `publication.push` remaining_work item is deferred past
finish only when the run's admitted effect already covers it; it is never
waived. Finish records it in `pending-publication.json`, and it stays owed until
`settle` observes the result in Git (a descendant HEAD with a clean tracked tree
for a commit; the upstream remote's branch equal to HEAD for a push). Free text
is never accepted as proof. A `publication.pull-request/<target>` item remains
pending after preparation regardless of the provider. A caller-supplied provider
observation must match the source branch, reviewed commit and target; an unchecked
PR is never assumed to exist. The caller is responsible for observing the provider.
A push or PR is observed for the reviewed finish HEAD itself (a commit made
before finish) or, when a `publication.commit` item is also declared, for a
descendant of it.
Allowed: bounded local reads, atomic receipt writes, fixed read-only Git argv
(`rev-parse`, `merge-base`, `status`, `config`, `ls-remote`). Forbidden: Git
writes, executing provider commands, inferring authority, widening a run's effect.
Every unreadable, missing or foreign receipt counts as still owed.
Callers/tests: agent_work_completion, agent-hook finish, claude_stop_gate,
codex_stop_gate; test_agent_pending_publication.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent_execution_capsule_state import atomic_write_json
from agent_publication_status import observe_pull_request
from workflow_intent_envelope import EFFECT_RANK

# checkpoint slug -> effect the run must already be admitted for.
PUBLICATION_CHECKPOINTS = {
    "publication.commit": "git_write",
    "publication.push": "external_write",
    "publication.pull-request": "external_write",
}
PULL_REQUEST = "publication.pull-request"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
DEFERRING_ROUTE = "commit"
_FILE = "pending-publication.json"
_GIT_TIMEOUT = 30


def admitted_effect(preflight: dict) -> str:
    envelope = ((preflight.get("route") or {}).get("request_classification") or {}).get("intent_envelope") or {}
    if (envelope.get("authority") != "envelope" or not envelope.get("schema_valid")
            or envelope.get("failures") != []):
        return ""
    effect = envelope.get("effective_effect")
    return effect if effect in EFFECT_RANK else ""


def kind(checkpoint: object) -> str:
    """Canonical publication kind of a checkpoint name; "" when it is not one.

    A pull request must name its target branch: `publication.pull-request/<target>`.
    """
    if not isinstance(checkpoint, str):
        return ""
    if checkpoint in ("publication.commit", "publication.push"):
        return checkpoint
    head, _, target = checkpoint.partition("/")
    return PULL_REQUEST if head == PULL_REQUEST and _NAME.fullmatch(target) else ""


def split_remaining(preflight: dict, remaining: list, project: Path | None = None) -> tuple[list, list]:
    """(blocking, deferred); only a commit route's admitted exact checkpoint defers.

    A pull request needs an explicit target branch. A provider interface is
    optional at preparation time and is required only for automatic settlement.
    """
    granted = EFFECT_RANK.get(admitted_effect(preflight), -1)
    commit_route = (preflight.get("route") or {}).get("command") == DEFERRING_ROUTE
    blocking, deferred = [], []
    for item in remaining or []:
        needed = PUBLICATION_CHECKPOINTS.get(kind(item.get("checkpoint"))) if isinstance(item, dict) else None
        ok = commit_route and needed and granted >= EFFECT_RANK[needed]
        (deferred if ok else blocking).append(item)
    return blocking, deferred


def _path(evidence: Path) -> Path:
    return evidence.with_name(_FILE)


def _sha(evidence: Path) -> str:
    return hashlib.sha256(evidence.read_bytes()).hexdigest()


def _load(evidence: Path) -> tuple[dict | None, str]:
    """(record, "") when valid; (None, "missing") or (None, reason) otherwise."""
    try:
        record = json.loads(_path(evidence).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError):
        return None, "unreadable"
    try:
        valid = (
            isinstance(record, dict) and record.get("schema_version") == 1
            and record.get("run_id") == evidence.parent.name
            and record.get("evidence_sha256") == _sha(evidence)
            and isinstance(record.get("base_head"), str) and record["base_head"]
            and isinstance(record.get("items"), list)
            and all(isinstance(i, dict) and kind(i.get("checkpoint"))
                    and i.get("state") in ("pending", "observed") for i in record["items"])
        )
    except OSError:
        valid = False
    return (record, "") if valid else (None, "foreign or malformed")


def _git(project: Path, *arguments: str) -> str | None:
    """stdout of one read-only Git call, or None on any failure (fail closed)."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        result = subprocess.run(["git", "-C", str(project), *arguments], check=False,
                                capture_output=True, text=True, timeout=_GIT_TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def record_pending(project: Path, evidence: Path, deferred: list) -> str:
    """Persist deferred items beside the run. Returns "" or why it could not be stored.

    A valid existing record is never reset (settled items stay settled); an
    unreadable one is a failure, not something to overwrite silently.
    """
    if not deferred:
        return ""
    wanted = [i["checkpoint"] for i in deferred]
    existing, problem = _load(evidence)
    if existing is not None:
        have = {i["checkpoint"] for i in existing["items"]}
        return "" if set(wanted) <= have else "existing pending-publication record misses declared items"
    if problem != "missing":
        return f"pending-publication record is {problem}"
    head = _git(project, "rev-parse", "HEAD")
    if not head:
        return "project HEAD could not be read to anchor the pending publication"
    try:
        atomic_write_json(_path(evidence), {
            "schema_version": 1,
            "run_id": evidence.parent.name,
            "evidence_sha256": _sha(evidence),
            "base_head": head,
            "items": [{"checkpoint": c, "state": "pending", "observation": ""} for c in dict.fromkeys(wanted)],
        })
    except (OSError, ValueError) as error:
        return f"pending-publication record could not be written ({type(error).__name__})"
    stored, problem = _load(evidence)
    return "" if stored is not None else f"pending-publication record failed read-back ({problem})"


def outstanding(project: Path, evidence: Path, declared: list | None = None) -> list[str]:
    """Checkpoints still owed. Missing, corrupt or foreign receipts are owed, never complete.

    `declared` is the bound packet's remaining_work; a deferrable item it names
    without a receipt entry stays owed. Without it, only an existing receipt
    can speak.
    """
    names = [i["checkpoint"] for i in declared or [] if isinstance(i, dict) and kind(i.get("checkpoint"))]
    record, problem = _load(evidence)
    if record is None:
        if problem == "missing":
            return list(dict.fromkeys(names))
        return list(dict.fromkeys(names)) or [f"receipt ({problem})"]
    pending = [i["checkpoint"] for i in record["items"] if i["state"] == "pending"]
    recorded = {i["checkpoint"] for i in record["items"]}
    return pending + [n for n in dict.fromkeys(names) if n not in recorded]


def declared_deferrable(project: Path, evidence: Path) -> list:
    """Deferrable remaining_work from the run's bound packet; [] when it is unreadable."""
    try:
        from agent_work_completion import bound_work_packet
        from agent_execution_capsule_state import read_json_object

        packet = bound_work_packet(project, evidence) or {}
        preflight = read_json_object(evidence)
        return split_remaining(preflight, (packet.get("work") or {}).get("remaining_work") or [], project)[1]
    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
        return []


def pending_reason(project: Path, evidence: Path) -> str:
    owed = outstanding(project, evidence, declared_deferrable(project, evidence))
    if not owed:
        return ""
    return (
        f"Moru publication. finish passed, but declared publication is not yet observed ({', '.join(owed)}). "
        "Perform it only under the run's admitted effect and the publication gate, then run "
        "agent_pending_publication.py settle for that checkpoint, which verifies the result in Git. "
        "Never report it as published before then; if it cannot proceed, say it is NOT PUBLISHED and why."
    )


def _remote_head(project: Path, head: str) -> tuple[str, str]:
    branch = _git(project, "symbolic-ref", "--short", "HEAD")
    remote = _git(project, "config", f"branch.{branch}.remote") if branch else None
    merge = _git(project, "config", f"branch.{branch}.merge") if branch else None
    if not (remote and merge and merge.startswith("refs/heads/")):
        return "", "the branch has no configured upstream to check"
    listed = _git(project, "ls-remote", "--exit-code", remote, merge)
    if not listed or listed.split()[0] != head:
        return "", "the upstream branch does not point at HEAD"
    return f"{remote} {merge} is {head}", ""


def _observe(project: Path, record: dict, item: dict, observation_path: Path | None = None) -> tuple[str, str]:
    """Check Git and the caller's provider observation against the reviewed unit."""
    checkpoint, base_head = kind(item["checkpoint"]), record["base_head"]
    head = _git(project, "rev-parse", "HEAD")
    if not head:
        return "", "HEAD could not be read"
    advanced = head != base_head and _git(project, "merge-base", "--is-ancestor", base_head, head) is not None
    commit_declared = any(kind(i["checkpoint"]) == "publication.commit" for i in record["items"])
    if checkpoint == "publication.commit" or commit_declared:
        if not advanced:
            return "", "HEAD has not advanced from the finished commit base"
    elif head != base_head:
        return "", "HEAD is not the reviewed finish commit and no declared commit covers it"
    if _git(project, "status", "--porcelain", "--untracked-files=no") != "":
        return "", "tracked changes remain uncommitted"
    if checkpoint == "publication.commit":
        return f"HEAD {head} descends from {base_head}", ""
    pushed, refusal = _remote_head(project, head)
    if refusal or checkpoint == "publication.push":
        return pushed, refusal
    return observe_pull_request(project, head, item["checkpoint"].partition("/")[2], _git, observation_path)


def settle(project: Path, evidence: Path, checkpoint: str, observation_path: Path | None = None) -> str:
    """Mark one item observed only when Git shows it. Returns "" or the refusal."""
    record, problem = _load(evidence)
    if record is None:
        return f"no usable pending publication record for this run ({problem})"
    for item in record["items"]:
        if item["checkpoint"] == checkpoint and item["state"] == "pending":
            observation, refusal = _observe(project, record, item, observation_path)
            if refusal:
                return refusal
            item.update(state="observed", observation=observation,
                        observed_at=datetime.now(timezone.utc).isoformat())
            try:
                atomic_write_json(_path(evidence), record)
            except (OSError, ValueError) as error:
                return f"observation could not be stored ({type(error).__name__})"
            return ""
    return "that checkpoint is not pending"


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("settle", "status"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--checkpoint", default="")
    parser.add_argument("--observation-file", type=Path)
    args = parser.parse_args(argv)
    if args.action == "status":
        print(pending_reason(args.project, args.evidence) or "no pending publication")
        return 0
    failure = settle(args.project, args.evidence, args.checkpoint, args.observation_file)
    print(f"FAIL publication settle: {failure}" if failure else "publication observation recorded")
    return 2 if failure else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
