---
keyflow_id: sys_api_contract_compatibility
status: stable
type: human-reviewed-needed
---

# API Contract Compatibility

Use when changing HTTP APIs, DTOs, schemas, SDK clients, route contracts,
deep links, events, webhooks, queues, import/export formats, or shared fixtures.

For SOLID, Interface Segregation, substitutable implementations, and dependency
direction around code-level contracts, also use
`common/skills/solid-design-principles/SKILL.md`.

## Default

Treat contracts as product surfaces. A contract is not only server code; it is
what clients, tests, docs, integrations, and users can rely on.

## Rules

- Identify the contract owner and consumers before changing fields or routes.
- Prefer additive changes over breaking changes.
- Do not add a required request field without a compatibility or migration plan.
- Do not remove, rename, narrow, or repurpose response fields without checking
  all clients.
- Keep stable identifiers stable. Changing ID shape is a breaking change.
- Keep error shape typed and documented enough for clients to recover.
- Define pagination, sorting, filtering, timezone, currency, locale, and null
  behavior explicitly when they affect users or clients.
- Use idempotency or duplicate handling for retries, writes, billing, webhooks,
  background jobs, and import flows.
- Keep auth, tenant, permission, entitlement, and quota enforcement at the trusted
  boundary, not only in the client.
- Keep code-level client and server interfaces narrow. Do not force clients,
  adapters, fakes, or tests to implement unrelated operations to satisfy one
  broad API surface.

## Request And Response Models

- Use separate request and response types. A request is owned by the caller
  producing the write and contains only fields that are transmitted.
- Model a response after the received server or transport shape. Do not hide a
  missing required response field with a default value.
- Apply display fallbacks after transport mapping in domain or UI policy, not
  in the response DTO.
- Keep transport DTOs out of domain, entity, UI, and other public contracts
  unless the transport type is intentionally the public wire contract.
- Keep read/response and write/request models and mapping paths separate; do
  not reuse one direction's mapper as the other direction's contract.

## Switching A Client To Another Endpoint

When a client screen moves its data source to a different endpoint (a new list
API, a replacement detail API, a consolidated feed), the old response may have
carried values that existing behavior still needs.

- Before switching, list every user action on that screen (open, swipe, menu,
  leave, delete, edit). For each action, record the values it uses, with the old
  response field beside the new response field.
- Do not silently fill a missing value with an extra call. Raise it as a contract
  request to the API owner and report it.
- If a stopgap call is unavoidable until the contract changes, make it only
  when the action actually runs, for example after the user confirms. Never make
  it just to decide which branch to show. Record the stopgap where the next
  maintainer will see it.
- Compare the action rules with the other clients and other entry points for the
  same feature. Owner, permission and closed-state branches diverge most often.
- Read the field descriptions in the new contract. Usage conditions written
  there, such as "owners cannot leave an active room", must map to client
  branches.

## Compatibility Questions

- Which released client versions or external integrations depend on this shape?
- Is the change backward compatible, forward compatible, or intentionally
  breaking?
- What happens when an old client talks to a new server?
- What happens when a new client talks to an old server?
- Are fake data, fixtures, generated clients, docs, and tests updated together?
- Is the contract versioned by URL, schema version, event type, feature flag, or
  migration window?

## Tests

Cover contract tests or equivalent verification for:

- request validation
- response shape
- denied access and cross-tenant access
- old-client compatibility when relevant
- error shape and retry behavior
- fixture or generated client parity
