"""Dispatch verification policy over canonical observed execution receipts.

Owner: DispatchVerification; allowed imports: stdlib and ExecutionReceipts;
forbidden: test/provider execution, writes or receipt claims from worker prose.
Callers/tests: dispatch completion/launch; test_workflow_dispatch_verification.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agent_verification_receipts import ExecutionReceipts

PROCESS_COMPLETION = "process_completion"
CALLER_REPORT = "caller_report"
OBSERVED_VERIFICATION = "observed_verification"


def classify_worker_checks(packet):
    if not isinstance(packet, Mapping) or not isinstance(packet.get("checks"), list) or not packet["checks"]:
        return "missing"
    return (PROCESS_COMPLETION if all(isinstance(item, Mapping)
        and item.get("provenance") == PROCESS_COMPLETION
        and item.get("cmd") == "worker process exit" for item in packet["checks"])
        else CALLER_REPORT)


def requires_verification(prepared, *, allow_findings=False, required_verification=None, authoring_policy=""):
    if required_verification is True:
        return True, {"selectors": [], "test_directory": "tests"}
    if isinstance(required_verification, Mapping):
        selectors = required_verification.get("selectors", [])
        directory = required_verification.get('test_directory', 'tests')
        if (type(required_verification.get('required', True)) is not bool
                or set(required_verification) - {'required', 'selectors', 'test_directory'}
                or not isinstance(selectors, list) or len(selectors) > 64
                or not all(isinstance(s, str) and s and len(s) <= 240
                           and all(part.isidentifier() for part in s.split('.')) for s in selectors)
                or not isinstance(directory, str) or not directory or Path(directory).is_absolute()
                or '..' in Path(directory).parts):
            return True, {'invalid': True}
        return required_verification.get("required", True) is True, {
            "selectors": selectors, "test_directory": str(required_verification.get("test_directory") or "tests")}
    if required_verification is False:
        return False, {}
    if required_verification is not None:
        return True, {'invalid': True}
    if isinstance(prepared, Mapping):
        if prepared.get("required_verification") is not None:
            return requires_verification(None, allow_findings=allow_findings,
                required_verification=prepared["required_verification"], authoring_policy=authoring_policy)
        # Parent route gates belong to the lead, including with capsule reuse.
        # Legacy worker completion never certifies those gates. Only an explicit
        # per-worker declaration opts into execution-backed completion checks.
    return False, {}


def assess_completion_verification(packet, *, prepared=None, required_verification=None,
                                  allow_findings=False, working_dir=None, authoring_policy=""):
    classification = classify_worker_checks(packet)
    required, spec = requires_verification(prepared, allow_findings=allow_findings,
        required_verification=required_verification, authoring_policy=authoring_policy)
    result = {"verification_required": required, "satisfied": not required,
              "classification": classification, "reason": "verification_not_required"}
    if not required:
        return result
    if spec.get('invalid'):
        return {**result, 'reason': 'invalid_required_verification'}
    if not isinstance(prepared, Mapping) or not prepared.get("rules") or not working_dir:
        return {**result, "reason": "missing_handoff_evidence_context"}
    reader = ExecutionReceipts(working_dir, prepared["rules"])
    reason = "missing_canonical_preflight"
    for key in ("worker_preflight_evidence", "preflight_evidence"):
        if not prepared.get(key):
            continue
        # Keep the lexical path; resolving first would conceal a symlink.
        observed = reader.inspect(Path(str(prepared[key])), selectors=spec["selectors"],
                                  test_directory=spec["test_directory"])
        if observed["ok"]:
            return {**result, "satisfied": True, "classification": OBSERVED_VERIFICATION,
                    "reason": observed["reason"], "execution_id": observed["id"]}
        reason = observed["reason"]
    return {**result, "reason": reason}
