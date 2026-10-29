---
name: design-system
description: "Design System: Use when creating or changing shared UI primitives, tokens, patterns, component defaults, or reusable interaction rules."
keyflow_id: sys_common_design_system_md_skill
status: stable
type: ai-generated
required_contract: core
metadata:
  internal: true
---

# Design System

Use when creating or changing shared UI primitives, tokens, patterns, component defaults, or reusable interaction rules.

## Read

The core below is the required contract. Open `references/current-guidance.md` only for an unresolved in-scope question:

- `## Layers` to decide which layer (token, primitive, composed, product pattern, screen) owns a decision.
- `## Existing product evidence` when control reuse or screen-section ownership is unclear.
- `## Caller and visual-variant gate` before changing a shared card, row, button, token, or default.
- `## Component Structure` for folder split and file ownership.
- `## Token Modeling`, `## Component Contract` for token naming or a component API checklist.
- `## Previews And Examples` for the state/variant coverage list.
- `## Do Not` for the full prohibition list.

Also use `common/skills/reusable-code-design/SKILL.md`, and `component-api-design.md` for API shape, slots, controlled state. For visual quality (type scale, spacing, color, depth, motion) without an existing brand system, use `common/skills/minimal-visual-design/SKILL.md`.

## Must

- Do not bypass the design system: use or extend existing tokens, primitives, variants, previews. With none, create the smallest layer first: semantic tokens, one primitive, an example/preview.
- Before a feature UI edit, map each changed control to an existing primitive or adopted product pattern and one direct caller. Inspect its appearance and state contract; reading tokens or importing a button alone is not reuse evidence. Keep this bounded mapping in the normal task review, not a new gate.
- Inspect the containing screen before adding a section or field. Integrate with the existing section that owns the same user task; require a user decision for a new input. Reuse icon roles and placement from direct callers. Do not substitute a raw/native control or feature-only styling when the product already owns the equivalent pattern.
- Extract from repeated product needs; a design-system API needs a second credible caller or a foundational primitive need.
- Wrap raw third-party/platform controls in a product-namespaced primitive that encodes tokens, accessibility, loading/disabled, density, slots, variants. No raw library usage in feature screens; no pass-through wrapper that only renames or re-exports.
- Tokens are semantic (role, state, density, emphasis); components consume roles, not raw palette or one feature's exact values. No raw colors, fonts, spacing, radii, shadows, motion, z-index where a token or primitive fits. Token holders follow the platform stability model.
- Primitives own behavior and accessibility, never routes, feature ids, analytics, permission/billing policy, repository calls, DTOs, fake data, product copy. Product patterns may know domain workflow.
- Components cover loading, disabled, error, empty, focus, hover, pressed; accessibility labels, roles, focus, touch targets; long text, localization, small screen, dark mode, high contrast.
- Defaults are stable, deterministic, side-effect free; theme context only, no product state, globals, repositories, runtime config.
- Use slots for caller-owned content. No boolean flags or nullable option bags for caller variants: split, keep feature-local, or model typed state.
- Number/unit display is a contract: take formatted strings or a typed format policy (value, unit, scale, grouping, precision, locale, missing/invalid); primitives never format ad hoc, use the shared locale-aware formatter.
- Shared change: write a caller/variant inventory (reference frame, owner, data owner, affected and unchanged callers, evidence per caller). Similar screenshots are not a shared contract; one card type's need stays in its caller.
- Keep different fields in separate slots, never newline/padding joins. No fixed height/size on text surfaces that can clip; min height only as explicit contract. Server-owned colors, labels, options stay data inputs.
- Each component owns a small public API file in a capability folder (`buttons/`, `inputs/`, `feedback/`, `navigation/`, `data-display/`, `layout/`); feature-only UI under the feature. No named components in screen files, catch-all files, one barrel export, flat folders.
- Promotion needs a stable name, examples/previews, and migration guidance; a replacement needs adoption guidance.

## Stop If

- No second caller or foundational need justifies a shared API.
- Unchanged callers of a shared component have no evidence for the change.
- The component needs a repository, route, whole screen state, feature DTO, or many caller flags; it is a product pattern or feature-local.

## Verification

- Examples, previews, stories, fixtures, snapshots, or focused tests for each affected state and variant, for changed and unchanged callers; deterministic fixtures, no network, persistence, time, randomness, device services.
- Review for raw tokens, raw library use in screens, pass-through wrappers, boolean variants, product policy in primitives, clipping fixed sizes.
- Compare changed controls with an existing caller inside the actual screen shell, theme providers and style entry point. Check supported light/dark and narrow layouts, default/checked/disabled and keyboard focus/activation states as applicable. Isolated feature fixtures and passing logic tests alone do not establish design-system compliance; report missing rendered evidence explicitly.
- Report layer chosen, caller inventory, tokens/primitives reused or added, evidence run/not run.
