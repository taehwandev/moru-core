---
keyflow_id: sys_auth_rbac_implementation
status: review
type: human-reviewed-needed
---

# Auth RBAC Implementation

Use when implementing login, session refresh, organization/workspace
membership, role assignment, permissions, entitlement checks, tenant scoping,
protected actions, or authorization tests.

Also read `product-patterns/skills/auth-rbac-permissions/SKILL.md`, `common/skills/security-privacy-review/SKILL.md`,
and the matching server/client platform cards.

## Model Separation

Keep these concepts separate in code:

```text
Identity -> Session -> Membership -> Role -> Permission -> Entitlement
-> Resource Scope
```

- Identity answers who the user is.
- Session answers whether the caller is currently authenticated.
- Membership answers whether the user belongs to the tenant/workspace/org.
- Role answers which product bundle the user has.
- Permission answers whether one action is allowed.
- Entitlement answers whether the commercial plan enables a feature.
- Resource scope answers which tenant/resource the permission applies to.

Do not use role names as a substitute for action permission checks in server
commands.

## Enforcement Layers

- Server/API/use case is the final authority.
- Client checks are for UX, route prevention, and better error messaging only.
- Database queries must include tenant/resource scope by construction.
- Background jobs, webhooks, CLI commands, admin tools, and scheduled tasks must
  enforce the same policy as HTTP routes when they mutate protected resources.
- Cached permissions must be invalidated on logout, org switch, role change,
  membership revoke, invite accept, plan change, and session refresh.

## Permission API Shape

Prefer named actions and typed context:

```text
can(actor, "member.invite", { tenantId })
can(actor, "billing.manage", { billingAccountId })
can(actor, "document.delete", { documentId, tenantId })
```

Rules:

- Permission helpers should return allow/deny with a reason code when the UI
  needs to distinguish unauthenticated, unauthorized, not-a-member, plan-limited,
  or resource-not-found states.
- Server errors should avoid leaking private resource existence unless product
  policy allows it.
- UI copy should distinguish role limitation from plan limitation.
- Audit protected mutations with actor, tenant/resource, action, target, result,
  and correlation id when applicable.

## Role And Permission Changes

- Only authorized actors can assign roles.
- An actor cannot assign a role or permission broader than their own authority
  unless an explicit owner/system policy allows it.
- Last-owner, sole-admin, billing-owner, and service-account changes need
  special checks.
- Role changes should refresh sessions, caches, UI state, and open tabs when the
  product requires immediate enforcement.
- Downgrades or revoked permissions must block commands, not only hide buttons.

## Tenant Isolation

- Tenant id should come from trusted context or validated route scope, not from
  arbitrary client body fields.
- Queries should make cross-tenant access difficult by construction.
- Shared resources need explicit sharing records and permission checks.
- Imports, exports, search, autocomplete, analytics, notifications, and audit
  views must honor tenant scope.

## Tests

Cover:

- unauthenticated caller
- authenticated but not a member
- wrong tenant
- insufficient role
- missing action permission
- plan-limited entitlement
- stale session after role revoke
- org/workspace switch
- last-owner or sole-admin edge case
- server command blocked even when UI button is hidden
- background job/webhook/admin path enforcing the same policy
- cache refresh after role, membership, invite, or entitlement change

Review the final diff for role-name checks scattered in UI, optional tenant
filters, client-owned role/tenant fields, duplicated permission rules, and
protected mutations without audit or test coverage.
