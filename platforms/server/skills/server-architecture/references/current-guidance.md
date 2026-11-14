---
keyflow_id: sys_5401647d98b8
status: review
type: ai-generated
---

# Server Architecture

Use for API, worker, database, auth, tenancy, and integration-service work.

For migrations, transactions, jobs, webhooks, queues, or external systems, also
use `server-data-jobs.md`. For auth, tenant isolation, API input, rate limits,
uploads, webhooks, outbound calls, or secrets, also use `server-security.md`.
For concrete route/resolver, request validation, use case, repository, and
response/error implementation details, also use `server-api-implementation.md`.

## Boundaries

```text
Route/Handler -> Use Case/Service -> Repository/Client -> Database/External System
```

## Package And Module Boundaries

Apply `common/nodes/package-module-boundaries.md` and
`common/skills/code-structure-ownership/SKILL.md` when structuring server
packages or workspace modules:

- Organize server code **by domain capability first** (`billing/`, `accounts/`,
  `orders/`), then by layer inside the capability (`router`/`handler`, `schema`,
  `service`/`usecase`, `repository`, `domain`), rather than growing repo-wide
  horizontal `controllers/`, `services/`, `models/`, and `utils/` directories.
- Cross-capability dependencies must go through the other capability's narrow
  public contract (`api` module, service interface, or exported facade) — never
  import another capability's ORM models, SQL queries, or repository
  implementation directly.
- In monorepos or multi-process services (`api`, `worker`, `scheduler`), extract
  shared capabilities into narrow `core/<capability>` or `<capability>-contract`
  packages instead of importing the HTTP `api` app into background workers.
- Audit any package root exceeding ~20 files or mixing 3+ roles; move **all**
  existing root files of an extracted role (no half-applied splits) and forbid
  `common`, `shared`, `utils`, or `helpers` dump packages. Verify forbidden
  cross-capability repository/ORM imports with `rg`.

## Rules

- Keep request parsing separate from product rules.
- Enforce auth, permission, tenant boundary on the server.
- Keep DB schema/entity details out of API response shaping when possible.
- Make side effects explicit: email, billing, webhooks, jobs, files.
- Use idempotency for retries, payments, webhooks, and background jobs.
- Log operational detail without leaking secrets or personal data.

## Do Not

- Do not trust client-provided tenant, role, owner, billing, quota, visibility,
  audit, or server-owned fields.
- Do not let route handlers own validation, authorization, product rules,
  transactions, external calls, response shaping, and logging in one block.
- Do not expose database rows, provider payloads, stack traces, raw SQL,
  credentials, or private existence signals as public API responses.
- Do not make tenant filters, permission checks, idempotency keys, or transaction
  boundaries optional call-site conventions.
- Do not add a service or repository layer that only renames one call without
  adding validation, transaction ownership, mapping, retry policy, or tests.

## Refactor Signals

- Route handler owns validation, permission, DB, and side effects.
- Tenant filter is optional or repeated manually.
- External API errors leak directly to clients.
- Background job retry behavior is unclear.

## Verification

- route/resolver test for request parsing, auth, permission, tenant, status, and
  response/error shape
- use case/service test for product rule, idempotency, transaction, retry, and
  side-effect orchestration
- repository/client test for query constraints, mapping, external errors,
  timeouts, and safe retry metadata
- migration/backfill check for reversibility, locks, partial failure, rollback,
  and forward-fix path when persisted data changed
