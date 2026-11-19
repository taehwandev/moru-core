"""Keep declared post-finish commit/push visible until Git itself shows it happened.

Owner: declared delivery items deferred by a finished run's admitted effect;
they are never waived. New staged_v1 contracts bind reviewed index content,
checkout/repository identity and local integration target refs. Stop observes
local commit/integration only after actual Git proof; it performs no Git writes.
Legacy commit receipts retain descendant/clean-tree proof and explicit settle.
Push still requires the upstream remote's branch equal to HEAD. Free text
is never proof. A `publication.pull-request/<target>` item remains
pending after preparation regardless of the provider. A caller-supplied provider
observation must match the source branch, reviewed commit and target; an unchecked
PR is never assumed to exist. The caller is responsible for observing the provider.
A push or PR is observed for the reviewed finish HEAD itself (a commit made
before finish) or, when a `publication.commit` item is also declared, for a
descendant of it.
Allowed: bounded local reads, atomic receipt writes, fixed read-only Git argv
(`rev-parse`, `merge-base`, `status`, `config`, `ls-remote`, tree/index/history
inspection). Forbidden: Git
writes, executing provider commands, inferring authority, widening a run's effect.
Every unreadable, missing or foreign receipt counts as still owed.
Callers/tests: agent_work_completion, agent-hook finish, claude_stop_gate,
codex_stop_gate; test_agent_pending_publication.
"""

from __future__ import annotations

import hashlib
import json
import locale
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent_continuation_outbound import assert_no_continuation_outbound
from agent_execution_capsule_state import atomic_write_json
from agent_publication_status import observe_pull_request, observe_upstream
from workflow_intent_envelope import EFFECT_RANK
from agent_local_delivery import LocalDeliveryProof
from support.native_probe_transport import NativeProbe

# checkpoint slug -> effect the run must already be admitted for.
PUBLICATION_CHECKPOINTS = {
    "publication.commit": "git_write",
    "publication.push": "external_write",
    "publication.pull-request": "external_write",
    LocalDeliveryProof.INTEGRATION: "git_write",
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
    return head if head in (PULL_REQUEST, LocalDeliveryProof.INTEGRATION) and _NAME.fullmatch(target) else ""


def split_remaining(preflight: dict, remaining: list, project: Path | None = None) -> tuple[list, list]:
    """(blocking, deferred); only a commit route's admitted exact checkpoint defers.

    A pull request needs an explicit target branch. A provider interface is
    optional at preparation time and is required only for automatic settlement.
    """
    granted = EFFECT_RANK.get(admitted_effect(preflight), -1)
    commit_route = (preflight.get("route") or {}).get("command") == DEFERRING_ROUTE
    route = preflight.get("route") or {}
    from workflow_effect_policy import route_minimum_effect
    local = (route.get("local_delivery_contract") == LocalDeliveryProof.CONTRACT
             and route_minimum_effect(route.get("command", "")) in {"local_write", "git_write"})
    if type(remaining) is list and remaining and (commit_route or local):
        mask = _native_partition(remaining, commit_route, local, granted)
        if mask is not None:
            return ([item for item, deferred in zip(remaining, mask) if not deferred],
                    [item for item, deferred in zip(remaining, mask) if deferred])
    blocking, deferred = [], []
    for item in remaining or []:
        needed = PUBLICATION_CHECKPOINTS.get(kind(item.get("checkpoint"))) if isinstance(item, dict) else None
        checkpoint = kind(item.get("checkpoint")) if isinstance(item, dict) else ""
        local_kind = checkpoint in ("publication.commit", LocalDeliveryProof.INTEGRATION)
        eligible = (local if checkpoint == LocalDeliveryProof.INTEGRATION else
                    commit_route or (local and local_kind))
        ok = eligible and needed and granted >= EFFECT_RANK[needed]
        (deferred if ok else blocking).append(item)
    return blocking, deferred


def _native_partition(remaining: list, commit_route: bool, local: bool, granted: int) -> list[bool] | None:
    checkpoints = [item.get("checkpoint") if isinstance(item, dict) else None for item in remaining]
    if any(name is not None and type(name) is not str for name in checkpoints):
        return None
    result = NativeProbe.request("--completion-probe", "pending-publication-partition", {
        "checkpoints": checkpoints, "commit_route": commit_route, "local_delivery": local,
        "git_write": granted >= EFFECT_RANK["git_write"],
        "external_write": granted >= EFFECT_RANK["external_write"],
    })
    if result is not None and set(result) == {"deferred"}:
        mask = result["deferred"]
        if isinstance(mask, list) and len(mask) == len(remaining) and all(type(entry) is bool for entry in mask):
            return mask
    return None


def _path(evidence: Path) -> Path:
    return evidence.with_name(_FILE)


def _sha(evidence: Path) -> str:
    return hashlib.sha256(evidence.read_bytes()).hexdigest()


def _store(evidence: Path, record: dict) -> None:
    path = _path(evidence)
    if NativeProbe.available():
        assert_no_continuation_outbound({"path": path, "payload": record}, boundary="artifact")
        result = NativeProbe.request("--completion-probe", "pending-publication-replace", {
            "evidence": str(evidence), "record": record, "temporary": uuid.uuid4().hex,
        })
        if result is not None:
            if result == {"error": None}:
                return
            errors = (FileExistsError, FileNotFoundError, PermissionError, IsADirectoryError, NotADirectoryError)
            error = next((error for error in errors if error.__name__ == result.get("error")), OSError)
            raise error("native receipt replacement failed")
    atomic_write_json(path, record, write_payload=NativeProbe.encode_publication_receipt)


def _load(evidence: Path) -> tuple[dict | None, str]:
    """(record, "") when valid; (None, "missing") or (None, reason) otherwise."""
    result = NativeProbe.request("--completion-probe", "pending-publication-read", {"evidence": str(evidence)})
    if result is not None and set(result) == {"record", "problem"}:
        record, problem = result["record"], result["problem"]
        if isinstance(record, dict) and problem == "":
            return record, ""
        if record is None and problem in ("missing", "unreadable", "foreign or malformed"):
            return None, problem
    return _load_python(evidence)


def _load_python(evidence: Path) -> tuple[dict | None, str]:
    try:
        record = json.loads(_path(evidence).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError):
        return None, "unreadable"
    try:
        valid = (
            isinstance(record, dict) and type(record.get("schema_version")) is int
            and record.get("schema_version") in (1, 2)
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


_LOCAL_DELIVERY_GIT = _git


def _native_record(operation: str, payload: dict) -> dict | None:
    result = NativeProbe.request("--completion-probe", operation, payload)
    if result is not None and set(result) == {"record"} and isinstance(result["record"], dict):
        return result["record"]
    return None


def _new_record(fields: dict, wanted: list, local_proof: dict | None) -> dict:
    native = _native_record("pending-publication-prepare", {
        **fields, "checkpoints": wanted, "local_delivery": local_proof,
    })
    if native is not None:
        return native
    record = {
        "schema_version": 1, **fields,
        "items": [{"checkpoint": c, "state": "pending", "observation": ""} for c in dict.fromkeys(wanted)],
    }
    if local_proof is not None:
        record.update(schema_version=2, local_delivery=local_proof)
    return record


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
    branch = _git(project, "symbolic-ref", "--short", "HEAD")
    if not head or not branch:
        return "project HEAD or source branch could not be read to anchor the pending publication"
    try:
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        local_contract = (payload.get("route") or {}).get("local_delivery_contract")
        local_proof = None
        if any(kind(c) == LocalDeliveryProof.INTEGRATION for c in wanted) and local_contract != LocalDeliveryProof.CONTRACT:
            return "local integration requires the current local delivery contract"
        if local_contract == LocalDeliveryProof.CONTRACT and any(
                kind(c) in ("publication.commit", LocalDeliveryProof.INTEGRATION) for c in wanted):
            if split_remaining(payload, deferred, project)[0]:
                return "local delivery is not admitted by this run"
            try:
                local_proof = LocalDeliveryProof.capture(
                    project, head, branch, deferred, _git, native=_git is _LOCAL_DELIVERY_GIT)
            except ValueError as error:
                return f'local delivery preparation refused: {error}'
        record = _new_record({
            "run_id": evidence.parent.name,
            "evidence_sha256": _sha(evidence),
            "base_head": head,
            "source_branch": branch,
        }, wanted, local_proof)
        _store(evidence, record)
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
    return _status(evidence, declared)[0]


def _status(evidence: Path, declared: list | None) -> tuple[list[str], str]:
    names = [i["checkpoint"] for i in declared or [] if isinstance(i, dict) and kind(i.get("checkpoint"))]
    result = NativeProbe.request("--completion-probe", "pending-publication-status", {
        "evidence": str(evidence), "declared": names,
    })
    if result is not None and set(result) == {"owed", "reason"}:
        owed, reason = result["owed"], result["reason"]
        if (isinstance(owed, list) and all(isinstance(name, str) for name in owed)
                and isinstance(reason, str) and bool(owed) == bool(reason)):
            return owed, reason
    owed = _outstanding_python(evidence, names)
    return owed, _status_reason_python(owed)


def _outstanding_python(evidence: Path, names: list[str]) -> list[str]:
    record, problem = _load_python(evidence)
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
    return _status(evidence, declared_deferrable(project, evidence))[1]


def _status_reason_python(owed: list[str]) -> str:
    if not owed:
        return ""
    return (
        f"Moru publication. finish passed, but declared publication is not yet observed ({', '.join(owed)}). "
        "Perform it only under the run's admitted effect and the publication gate, then run "
        "agent_pending_publication.py settle for that checkpoint, which verifies the result in Git. "
        "Never report it as published before then; if it cannot proceed, say it is NOT PUBLISHED and why."
    )


def pending_session_reason(project: Path, identity: dict[str, str]) -> str:
    from agent_repository_checkouts import checkouts_with_run_state

    roots = [project] if os.environ.get('MORU_WORKER_EVIDENCE', '').strip() else [project, *checkouts_with_run_state(project)]
    return '\n'.join(reason for root in roots if (reason := _pending_checkout_reason(root, identity)))


def _pending_checkout_reason(project: Path, identity: dict[str, str]) -> str:
    """Observe local Git facts only; preserve debt across completed session runs."""
    from agent_runtime_session import completed_session_evidence

    reasons = []
    for evidence in completed_session_evidence(project, identity):
        record, _ = _load(evidence)
        observation_error = ""
        if record and record.get("schema_version") == 2:
            for item in record["items"]:
                if item["state"] == "pending" and kind(item["checkpoint"]) in (
                        "publication.commit", LocalDeliveryProof.INTEGRATION):
                    observation_error = settle(project, evidence, item["checkpoint"]) or observation_error
        reason = pending_reason(project, evidence)
        if reason:
            owed = outstanding(project, evidence)
            local_owed = [name for name in owed if kind(name) in (
                'publication.commit', LocalDeliveryProof.INTEGRATION)]
            if record and record.get("schema_version") == 2 and local_owed and len(local_owed) == len(owed):
                reason = (f"Local delivery is still pending ({', '.join(local_owed)}); verification did not publish it. "
                          "Perform only the already authorized commit/integration. Closeout observes Git automatically. "
                          + observation_error)
            reasons.append(reason)
    return "\n".join(reasons)


def _upstream_config(project: Path) -> tuple[str, str]:
    if _git is _LOCAL_DELIVERY_GIT and locale.getpreferredencoding(False).lower() == "utf-8":
        result = NativeProbe.request("--completion-probe", "publication-upstream-config", {"project": str(project)})
        if result is not None and set(result) == {"remote", "merge"}:
            remote, merge = result["remote"], result["merge"]
            if isinstance(remote, str) and isinstance(merge, str):
                if not remote and not merge:
                    return "", ""
                if remote and not remote.startswith("-") and merge.startswith("refs/heads/"):
                    return remote, merge
    branch = _git(project, "symbolic-ref", "--short", "HEAD")
    if not branch:
        return "", ""
    remote = _git(project, "config", f"branch.{branch}.remote")
    merge = _git(project, "config", f"branch.{branch}.merge")
    return remote or "", merge or ""


def _remote_head(project: Path, head: str) -> tuple[str, str]:
    remote, merge = _upstream_config(project)
    if not (remote and merge and merge.startswith("refs/heads/")):
        return "", "the branch has no configured upstream to check"
    listed = _git(project, "ls-remote", "--exit-code", remote, merge)
    return observe_upstream(listed, remote, merge, head)


def _observe(project: Path, record: dict, item: dict, observation_path: Path | None = None) -> tuple[str, str]:
    """Check Git and the caller's provider observation against the reviewed unit."""
    checkpoint, base_head = kind(item["checkpoint"]), record["base_head"]
    if record.get("schema_version") == 2:
        local = checkpoint in ("publication.commit", LocalDeliveryProof.INTEGRATION)
        observation, refusal = LocalDeliveryProof.observe(
            project, record, item["checkpoint"] if local else "publication.commit", _git,
            native=_git is _LOCAL_DELIVERY_GIT)
        if local or refusal:
            return observation, refusal
    if checkpoint == LocalDeliveryProof.INTEGRATION:
        return "", "local integration requires a bound staged-content proof"
    head, refusal = _legacy_local_head(project, record, checkpoint)
    if refusal:
        return "", refusal
    if checkpoint == "publication.commit":
        return f"HEAD {head} descends from {base_head}", ""
    pushed, refusal = _remote_head(project, head)
    if refusal or checkpoint == "publication.push":
        return pushed, refusal
    return observe_pull_request(project, head, item["checkpoint"].partition("/")[2], _git, observation_path)


def _legacy_local_head(project: Path, record: dict, checkpoint: str) -> tuple[str, str]:
    items = record.get("items")
    if (_git is _LOCAL_DELIVERY_GIT and locale.getpreferredencoding(False).lower() == "utf-8"
            and isinstance(items, list) and all(isinstance(item, dict) and "checkpoint" in item for item in items)):
        requires_commit = checkpoint == "publication.commit" or any(
            kind(item["checkpoint"]) == "publication.commit" for item in items)
        result = NativeProbe.request("--completion-probe", "legacy-publication-head", {
            "project": str(project), "source": record.get("source_branch") or "",
            "base": record["base_head"], "requires_commit": requires_commit,
        })
        if result is not None and set(result) == {"head", "reason"}:
            head, reason = result["head"], result["reason"]
            if isinstance(head, str) and isinstance(reason, str) and bool(head) != bool(reason):
                return head, reason
    return _legacy_local_head_python(project, record, checkpoint)


def _legacy_local_head_python(project: Path, record: dict, checkpoint: str) -> tuple[str, str]:
    base_head = record["base_head"]
    branch = _git(project, "symbolic-ref", "--short", "HEAD")
    if not record.get("source_branch"):
        return "", "source branch was not recorded; re-prepare this publication under current authority"
    if branch != record["source_branch"]:
        return "", "source branch differs from the finished publication"
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
    return head, ""


def _observed_record(record: dict, item: dict, observation: str, observed_at: str) -> dict:
    checkpoint = item["checkpoint"]
    native = _native_record("pending-publication-observe", {
        "record": record, "checkpoint": checkpoint, "observation": observation, "observed_at": observed_at,
    })
    if native is not None:
        return native
    item.update(state="observed", observation=observation, observed_at=observed_at)
    if record.get("schema_version") == 2 and kind(checkpoint) in ("publication.commit", LocalDeliveryProof.INTEGRATION):
        candidate = observation.rsplit(" ", 1)[-1]
        if re.fullmatch(r"[0-9a-f]{40,64}", candidate):
            record["local_delivery"]["reviewed_commit"] = candidate
    return record


def settle(project: Path, evidence: Path, checkpoint: str, observation_path: Path | None = None) -> str:
    """Mark one item observed only when Git shows it. Returns "" or the refusal."""
    record, problem = _load(evidence)
    if record is None:
        return f"no usable pending publication record for this run ({problem})"
    if record.get("schema_version") == 2:
        from agent_registry_read import completed_evidence_binding

        if not completed_evidence_binding(project, evidence):
            return "local delivery observation requires a completed bound run"
    for item in record["items"]:
        if item["checkpoint"] == checkpoint and item["state"] == "pending":
            observation, refusal = _observe(project, record, item, observation_path)
            if refusal:
                return refusal
            record = _observed_record(record, item, observation, datetime.now(timezone.utc).isoformat())
            try:
                _store(evidence, record)
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
