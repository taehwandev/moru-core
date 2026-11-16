"""Plan-backed collaboration metadata, never execution or delivery proof.

Owner: CollaborationPlanRecords. Allowed: stdlib, canonical plan path/schema.
Forbidden: provider calls, ledger writes, execution and inferred authority.
Callers/tests: gate-batch, finish; test_agent_collaboration_plan_records.
Verification: malformed/overlapping plans and changed byte proofs fail closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from agent_delegation_plan import delegation_plan_path, validate_delegation_plan_structure


class CollaborationPlanRecords:
    GATES = ("roles", "write scopes", "agent briefs")
    PREFIX = "plan-backed collaboration sha256="

    @staticmethod
    def _load(project: Path) -> tuple[dict, str]:
        try:
            with delegation_plan_path(project).open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("delegation plan exceeds 64 KiB")
            plan = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise ValueError("delegation plan is missing or unreadable; prepare a valid plan first") from error
        if not isinstance(plan, dict):
            raise ValueError("delegation plan must be an object")
        failures = validate_delegation_plan_structure(plan)
        if failures:
            raise ValueError("; ".join(failures))
        return plan, hashlib.sha256(raw).hexdigest()

    @classmethod
    def build(cls, project: Path, gates: list[str] | None = None, *, recorded: dict | None = None) -> list[dict]:
        plan, digest = cls._load(project)
        stale = {gate for gate, text in (recorded or {}).items() if gate in cls.GATES
                 and text.startswith(cls.PREFIX) and text[len(cls.PREFIX):].split(';', 1)[0] != digest}
        selected = [gate for gate in cls.GATES if gates is None or gate in gates or gate in stale]
        if not selected:
            raise ValueError("this run has no remaining plan-backed metadata gates")
        lead = plan["integration_review"].get("owner") or plan["integration_review"]["integration_owner"]
        projections = {
            "roles": {"lead": lead, "workers": [
                {key: worker[key] for key in ("id", "role")} for worker in plan["workers"]]},
            "write scopes": {"workers": [
                {key: worker[key] for key in ("id", "owned_scope", "forbidden_scope")}
                for worker in plan["workers"]]},
            "agent briefs": {"workers": plan["workers"], "proof": "brief metadata only; delivery is not attested"},
        }
        return [dict(
            gate=gate, status="SUCCESS", source="delegation_plan",
            evidence=cls.PREFIX + digest + "; " + json.dumps(projections[gate], ensure_ascii=False, sort_keys=True),
            fields={"plan_sha256": digest},
        ) for gate in selected]

    @classmethod
    def failures(cls, project: Path | None, evidence: dict[str, str]) -> list[str]:
        proofs = [text[len(cls.PREFIX):].split(";", 1)[0]
                  for gate, text in evidence.items()
                  if gate in cls.GATES and text.startswith(cls.PREFIX)]
        if not proofs:
            return []
        if project is None:
            return ["plan-backed collaboration requires its bound project"]
        try:
            _, current = cls._load(project)
        except ValueError as error:
            return [str(error)]
        if any(not re.fullmatch(r"[0-9a-f]{64}", digest) or digest != current for digest in proofs):
            return ["plan-backed collaboration proof is stale; inspect the changed plan and record its metadata again"]
        return []
