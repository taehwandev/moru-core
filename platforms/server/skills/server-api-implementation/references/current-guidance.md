---
keyflow_id: sys_server_api_implementation
status: review
type: human-reviewed-needed
---

# Server API Implementation

Use when creating, changing, moving, or reviewing HTTP handlers, GraphQL resolvers, RPC methods, webhooks, service methods, repositories, API validation, tenant boundaries, or response contracts.

For database transactions, migrations, queues, schedules, and webhooks, also read `server-data-jobs.md`. For auth, tenant isolation, input, SSRF, rate limits, and secrets, also read `server-security.md`.

## API Layers

Use this shape unless the repo has a stricter local pattern:

```text
Route/Resolver -> Request DTO/Validator -> Use Case/Service
-> Repository/Client -> Database/External System
```

- Route/resolver owns transport concerns: params, body, headers, status codes, response shape, and framework middleware.
- Validator owns parsing, normalization, allowlists, and safe defaults.
- Use case/service owns product rules, authz decisions, idempotency, and side-effect orchestration.
- Repository owns persistence queries and transaction boundaries.
- Client owns external API calls, retries, timeout, error mapping, and provider DTO conversion.

Do not put validation, permission checks, database queries, external calls, and response shaping all inside one handler.

## File And Handler Split

Apply `../../common/skills/code-structure-ownership/SKILL.md` before growing server runtime
files. Default to one primary route/resolver handler, validator,
request/response DTO family, use case, service, repository, client, mapper, job,
fixture, or assertion owner per file.

Split files before adding behavior when transport parsing, validation, authz,
tenant scope, product rule, transaction, external client call, response mapping,
side effect, and logging can be named or tested independently.

Review must fail when a server runtime file keeps multiple independently
importable owners in one file: route handlers, resolvers, validators, DTO
families, use cases, services, repositories, clients, mappers, jobs, fixtures,
or assertion helpers.

Do not:

- Put route registration, handler, validator, use case, repository query,
  external API client, DTO mapper, and response/error mapping in one file.
- Export unrelated handlers, services, repositories, DTOs, and jobs from one
  `services`, `models`, `helpers`, or barrel file.
- Hide auth, tenant, transaction, or side-effect ownership behind nested helper
  classes or anonymous inline callbacks.
- Add a service or repository file that only renames one call; split only when
  the file owns a real rule, transaction, dependency edge, or test boundary.

## Handler Contract

Every endpoint should identify:

- actor: authenticated user, service, webhook provider, anonymous caller
- tenant/workspace/account scope
- permission or entitlement needed for the action
- accepted input fields and rejected server-owned fields
- idempotency key when retries can duplicate side effects
- rate limit or abuse boundary when the endpoint is expensive or public
- success response, stable error shape, and HTTP status code
- audit log, correlation id, and privacy-safe diagnostics

## Request Validation

- Validate path params, query params, body, headers, file metadata, and webhook payload before product logic.
- Normalize emails, slugs, ids, dates, currencies, locale, pagination, sort, and filter values at the boundary.
- Use explicit field allowlists to prevent mass assignment.
- Keep server-owned fields such as role, tenant id, billing status, owner id, createdBy, quota, and audit fields out of client-controlled writes.
- Bound pagination, search, includes, sort, filter, batch size, upload size, and timeout.
- Treat malformed input as a typed, user-safe error, not an internal exception.

## Use Case Rule

Use cases should:

- Receive typed input and actor/context, not raw request objects.
- Recheck auth, permission, tenant, entitlement, and resource existence.
- Own transaction and idempotency decisions when multiple writes or side effects are involved.
- Return typed result or domain error that route code maps to response shape.
- Trigger side effects through named ports/clients so tests can isolate them.

Avoid use cases that only forward to one repository method without enforcing a rule, transaction, side effect, or test boundary.

## Repository And Query Rule

- Tenant filters should be required by construction, not optional call-site details.
- Use parameterized queries, safe ORM APIs, and explicit include/sort/filter allowlists.
- Keep database entities out of public API responses unless they are already the documented API contract.
- Model uniqueness, constraints, foreign keys, and soft-delete behavior in the repository or schema boundary.
- Define transaction isolation, retry, rollback, and forward-fix behavior for multi-write invariants.

## Response And Error Shape

- Map domain errors to stable response codes and payloads. Prefer RFC 9457
  Problem Details (or the repo's typed error envelope) with a deterministic
  machine `code`, `field_errors` (`field` path + reason),
  `request_id`/`correlation_id`, `retryable` boolean, and a safe user-facing
  summary so clients never have to fall back to generic error strings.
- Distinguish an empty collection (`200 OK` with `items: []` and pagination
  metadata) from a missing target or parent resource (`404 Not Found`), and use
  deterministic cursor pagination (stable sort tie-breaker) on list endpoints so
  client UIs render empty and paginated states accurately.
- Avoid leaking whether private users, tenants, resources, invites, tokens, or billing accounts exist unless product policy allows it.
- Include correlation id or request id where the repo standard supports it.
- Keep retryability explicit for clients when useful, and pair mutating retryable
  endpoints with `Idempotency-Key` handling.
- Never return stack traces, provider credentials, SQL, secrets, or internal provider payloads to callers.
- When clients need shared failure UX, the API may return presentation hints such as inline, toast/banner, alert/dialog, full-page, retry metadata, action label key, and deep link or route intent. Keep these as stable enum fields and allowlisted actions, not server-provided UI components, raw HTML, executable commands, or client-specific class names.
- Document the fallback when a client does not support a presentation hint. Clients still own platform rendering, localization, accessibility behavior, and whether a deep-link action is valid in the current screen.

## Tests

Choose the closest checks configured in the repo:

- Handler/route tests for request parsing, validation, response shape, and status codes.
- Use case tests for permission, tenant, entitlement, idempotency, and product rules.
- Repository tests for query constraints, transactions, migrations, uniqueness, soft delete, and cross-tenant isolation.
- Contract tests or generated-client checks for public API changes.
- Security tests for unauthenticated, forbidden, cross-tenant, mass assignment, injection-shaped input, rate limit, malformed payload, and secret/log leaks.

Review the final diff for optional tenant filters, client-controlled server fields, raw request objects in use cases, database entities in responses, duplicated permission logic, and side effects outside idempotent boundaries.
