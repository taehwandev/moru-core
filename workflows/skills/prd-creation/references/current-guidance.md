---
keyflow_id: sys_prd_creation_workflow
status: stable
type: human-reviewed-needed
---

# PRD Creation Workflow

Use when the deliverable is a PRD or product requirements note before ARD,
implementation, tests, or release planning.

For agent execution, run the canonical start once before writing the PRD:

```text
<MORU_LAUNCHER> start --project <TARGET_REPO> --rules <MORU_ROOT> --command prd --request "<USER_REQUEST>" --platform <platform> --concern <concern>
```

Open every route `required_docs` entry directly. Run the review hook after
meaningful changes and the finish hook before handoff. Direct `workflow.py
route`, `agent-preflight.py`, and `agent-finish-check.py` calls are lower-level
diagnostic fallbacks when the hook is unavailable.

Use `workflows/skills/product-architecture-delivery/SKILL.md` only when the work continues
from PRD into ARD and code.

## Read

- target repo-local agent instructions and product docs
- `workflows/skills/ambiguity-gate/SKILL.md`
- `common/skills/product-spec-to-implementation/SKILL.md`
- matching platform, product-pattern, security, data, accessibility, or release
  cards when those surfaces shape the PRD

## Steps

1. Source of truth: read the request, repo-local instructions, current product
   docs, issue, design note, or existing PRD before writing new requirements.
2. Alignment brief: before drafting the PRD, tell the user the minimum useful
   alignment: shared understanding, possible differences, unsupported
   assumptions or unknowns, and at most the blocker questions that would change
   behavior, risk, or verification.
3. Ambiguity check: classify unknowns as blocker, researchable, assumable, or
   out-of-scope. Ask only when the answer can change behavior, risk, or
   verification.
4. Actor and outcome: name the user or system actor and the outcome that should
   change.
5. Scope: define what is in scope, explicitly out of scope, and what should not
   change.
6. States and surfaces: cover success, loading, empty, error, permission denied,
   offline, conflict, rollback, data, auth, permission, billing, privacy,
   external services, and release impact when relevant.
7. Acceptance criteria: write testable criteria before ARD or code. Prefer
   Given/When/Then when behavior has clear inputs and outcomes.
8. Open decisions: name decisions that block ARD, implementation, security,
   data, release, or verification.
9. Handoff: state where the PRD lives, what evidence was used, and the next
   recommended route: `product`, `planning`, `ambiguity`, or stop.

Show a gate signal after each completed step when using a scripted route.

## Output

Use this shape unless the target repo has a PRD template:

```text
Alignment:
- Same understanding:
- May differ:
- Unsupported assumptions or unknowns:
- Minimal questions:

PRD:
- User or actor:
- Desired outcome:
- Current behavior:
- Proposed behavior:
- In scope:
- Out of scope:
- States:
- Data/auth/permission/billing/privacy/external surfaces:
- Acceptance criteria:
- Open decisions:
- Verification signals:
- Next route:
```

The alignment section is not a long questionnaire. Prefer one to three concise
blocker questions, and only ask them when the answer would change the PRD,
architecture, risk, or verification. If no blocker question is needed, say which
default assumption will be used.

## Stop If

- The PRD would invent product, legal, billing, security, or data policy not
  present in the target repo.
- Acceptance criteria cannot be made testable without a blocker answer.
- The request is already implementation-ready and a lightweight note is enough.
- The agent cannot identify the target project or source of truth.
