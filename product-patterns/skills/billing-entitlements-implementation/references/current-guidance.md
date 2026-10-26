---
keyflow_id: sys_billing_entitlements_implementation
status: review
type: human-reviewed-needed
---

# Billing Entitlements Implementation

Use when implementing plans, subscriptions, seats, quota, trial, downgrade,
payment failure, invoices, provider webhooks, billing permissions, or feature
gates.

Also read `product-patterns/skills/billing-entitlements/SKILL.md`, `product-patterns/skills/auth-rbac-implementation/SKILL.md`,
`platforms/server/skills/server-api-implementation/SKILL.md`, and
`common/skills/server-side-caching/SKILL.md`.

## Model Separation

Keep these concepts separate:

```text
Billing Account -> Subscription -> Plan -> Entitlement -> Usage
-> Permission -> Provider Record
```

- Billing account owns who pays and who can manage billing.
- Subscription owns commercial lifecycle and provider status.
- Plan is a named commercial package, not an authorization primitive.
- Entitlement is the product capability the app enforces.
- Usage is measured consumption against quota or limits.
- Permission controls who can view/manage billing or consume a feature.
- Provider record stores external ids and webhook state behind an adapter.

Do not scatter raw plan-name checks across UI, API handlers, or jobs.

## Entitlement Boundary

Prefer one entitlement query surface:

```text
entitlements.canUse("ai.export", { tenantId, actorId })
entitlements.limitFor("members.seats", { billingAccountId })
entitlements.usageFor("storage.gb", { tenantId })
```

Rules:

- Server commands enforce entitlements before protected side effects.
- Client checks explain disabled states and avoid doomed requests, but are not
  final authority.
- Entitlement responses should include reason codes when UI copy must
  distinguish plan limited, quota exceeded, payment failed, trial expired, or
  permission denied.
- Cache entitlement reads only with explicit invalidation after provider
  webhook, plan change, role change, usage write, downgrade, cancellation, or
  payment recovery.

## Subscription States

Model product behavior for:

- trial active
- trial ended
- active
- payment failed / past due
- cancelled but active until period end
- scheduled downgrade
- downgraded
- paused or suspended when product supports it
- provider state unknown or webhook delayed

Each state should define what is still usable, what is read-only, what is
blocked, and what recovery action is shown.

## Seats And Quota

- Seat checks should happen before invite accept, member add, role change, and
  account restore when they can increase billable usage.
- Quota checks should define soft limit, hard limit, grace, warning, retry, and
  recovery behavior.
- Usage writes should be idempotent or reconcilable.
- Downgrade should define which features/data remain accessible, archived,
  read-only, blocked, or scheduled for cleanup.
- Billing manager permission is separate from product admin/editor permission.

## Provider Webhooks

- Verify provider signature and timestamp.
- Store processed event ids for replay protection.
- Treat webhooks as eventually consistent; product state should tolerate delay.
- Make plan, subscription, invoice, payment, and cancellation updates
  idempotent.
- Reconcile provider state when webhook order is unexpected or missed.
- Avoid exposing raw provider error payloads or credentials to clients.

## UI States

UI should distinguish:

- permission denied
- plan limited
- quota exceeded
- seat limit reached
- trial ending
- trial ended
- payment failed
- downgrade scheduled
- provider unavailable
- billing manager required

Do not show "upgrade" as the only answer when the user lacks permission to
manage billing.

## Tests

Cover:

- entitlement allowed/blocked
- quota under, warning, exceeded, and recovered
- seat limit on invite/member add
- revoked billing manager
- stale entitlement cache after webhook or plan change
- trial end, cancellation, payment failure, and downgrade
- provider webhook signature failure, replay, out-of-order event, and retry
- server command blocked even when UI is disabled
- UI copy distinguishing permission denied from plan limited

Review the final diff for raw plan-name checks, client-only entitlement gates,
missing webhook replay protection, quota writes without idempotency, stale cache
risk, and billing UI that lets unauthorized users attempt billing actions.
