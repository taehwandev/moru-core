---
keyflow_id: sys_agent_credential_broker_ideation
status: review
type: ai-generated
---

# Agent Credential Broker Ideation

Use when brainstorming, comparing, or reviewing credential-broker, vault,
proxy, scoped-token, egress-control, or approval-loop patterns for AI agents.
This card is for ideation and architecture framing. It is not an implementation
runbook and must not replace the always-on secret-handling rules in
`../common/skills/secure-development-baseline/SKILL.md`.

## Source Boundary

Keep the split clear:

- Common guardrails belong in `../common/skills/secure-development-baseline/SKILL.md` and
  repo-local security instructions: do not expose secrets, do not log
  credential values, keep server-only secrets out of clients, use least
  privilege, and follow the trusted enforcement boundary.
- This card owns reusable product-pattern ideation: where authority lives, how
  an agent receives limited authority, how access is approved, revoked, logged,
  and denied by default.
- Repo-local docs own concrete providers, ports, environment variables,
  deployment topology, secret-store setup, role matrices, and operational
  runbooks.

## Decision Rule

Prefer a mediated credential pattern when an agent needs to call external APIs
but should not directly possess long-lived credentials.

For non-developer users, do not make "do not paste secrets into the prompt" the
main control. Treat that as a fallback warning only. The product or operator
workflow should provide a safe credential entry path, brokered access, scoped
approval, or delegated setup so the user does not need to understand prompt
hygiene to stay safe.

Keep a simpler direct-token setup only when all of these are true:

- the token is short-lived, low-privilege, and easy to revoke
- the runtime is trusted enough to hold it
- prompt injection or tool-output exfiltration is not a meaningful risk for the
  task
- logs, artifacts, crash reports, and support exports cannot capture the token

If any condition is false, compare brokered access, scoped capabilities,
approval flows, and egress controls before choosing the design.

## Pattern Families

### Brokered Proxy

The agent sends normal network requests through a broker. The broker injects
credentials and enforces host or path policy.

Use for broad API compatibility, proxy-aware tools, and centralized request
logging.

Watch for proxy bypass, CA trust management, response-body leakage,
private-network placement, and latency.

### Scoped Capability Token

An orchestrator mints a short-lived token that grants a narrow action set,
service, vault, route, or session.

Use for ephemeral sandboxes, CI-like jobs, and disposable coding-agent sessions.

Watch for token theft, broad scopes, missing revocation, and unclear ownership.

### Proposal And Approval Loop

The agent cannot add credentials or new services directly. It proposes access,
and a human or policy engine approves the change.

Use for unknown future APIs, high-risk credentials, and audit-friendly
workflows.

Watch for approval fatigue, vague requests, weak obtain instructions, and stale
pending proposals.

### External Secret Store Backend

The broker reads from a dedicated secret manager rather than storing every
credential itself.

Use when the organization already operates a secret manager or needs dynamic
secrets, rotation, and centralized access policy.

Watch for secret-zero bootstrapping, permission drift, sync lag, and incident
response complexity.

### Egress-Allowlisted Sandbox

The runtime blocks direct outbound access except to the broker or a narrow
destination list.

Use for non-cooperative agents that may ignore proxy variables or try direct
network access.

Watch for runtime privileges, DNS behavior, metadata endpoints, local-network
escapes, and maintenance cost.

## Design Questions

- What exact API actions does the agent need?
- Is the user expected to be a developer/operator, or should the product hide
  credential mechanics behind safe UI, approval, or setup flows?
- Which actor is allowed to see the raw credential value?
- Can the agent operate with a dummy credential, scoped capability, broker route,
  or proposal instead of a real secret?
- What happens when the agent asks for a new host, path, or action?
- How is access revoked during and after a session?
- What is logged without storing bodies, query strings, auth headers, or
  credential-bearing responses?
- What bypass path exists if the agent and broker share a host, network,
  filesystem, browser profile, or shell environment?
- What is the smallest pilot that tests the trust boundary before production
  hardening?

## Do Not

- Do not move always-on secret rules into optional skill or ideation docs.
- Do not design a non-developer workflow whose primary protection is telling the
  user not to paste credentials into chat.
- Do not copy one vendor's API shape, role model, or deployment topology into
  shared Moru Core guidance.
- Do not assume a proxy alone prevents exfiltration when the agent can bypass
  the proxy through direct network, local files, logs, screenshots, or another
  tool.
- Do not treat request logging as safe unless credential-bearing headers,
  bodies, query strings, and responses are excluded or redacted.

## Verification

For ideation-only work, verify that the output separates guardrails, optional
patterns, and project-specific decisions.

For design review, verify:

- the trusted enforcement boundary is named
- raw credential visibility is explicit
- non-developer users are not responsible for enforcing prompt-secret hygiene
- bypass paths are listed
- revocation and audit surfaces are defined
- the recommended pilot does not require production credentials

For implementation work, also load the relevant platform security card, server
or application architecture card, and `../common/skills/security-privacy-review/SKILL.md`.

## Report

When this card governs the work, report:

- which authority pattern was considered or recommended
- which guardrails were already covered elsewhere
- which project-specific decisions remain outside shared guidance
- the highest-risk bypass or leakage path still needing validation
