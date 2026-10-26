---
keyflow_id: sys_web_design_system
status: review
type: human-reviewed-needed
---

# Web Design System

Use when creating, changing, reviewing, or adopting web UI tokens, primitives,
component variants, layout patterns, themes, interaction states, or visual QA
rules.

Also use:
- `common/skills/design-system/SKILL.md` for the cross-platform design-system baseline.
- `common/skills/component-api-design/SKILL.md` for reusable component API contracts.
- `common/skills/ui-visual-verification/SKILL.md` for visual and interaction evidence.
- `web-accessibility-i18n.md` for labels, focus, keyboard, responsive copy, and
  localization.
- `platforms/web/skills/web-react-ui/SKILL.md` when a component also owns React state, hooks, or feature
  workflow behavior.

## Layer Model

Use this model to decide ownership:

```text
tokens -> primitives -> composed components -> product patterns -> screens
```

- Tokens define semantic decisions: color role, type scale, spacing, radius,
  elevation, motion, z-index, breakpoint, and density.
- Primitives define accessible behavior and styling contracts: button, input,
  label, tooltip, dialog, menu, popover, tabs, checkbox, switch, select, table,
  toast, skeleton.
- Composed components combine primitives into reusable UI shapes: search field,
  metric tile, empty state, settings row, data table toolbar.
- Product patterns may know a workflow: invite panel, billing plan picker,
  permission editor, onboarding step.
- Screens compose product patterns and feature-local sections.

Do not skip directly from tokens to screens for repeated controls. Do not push
product policy down into primitives.

## Product-Prefixed Wrappers

Web features must consume product/repo-prefixed design-system primitives
instead of raw third-party or browser controls for repeated UI. Even a button
must become a stable primitive such as `<Product>Button`, `AppButton`,
`DsButton`, or the repo's established prefix when it appears in repeated product
surfaces.

The wrapper must own semantic variants, token mapping, loading/disabled/error
states, focus-visible behavior, accessibility, slots, sizing, and responsive
defaults. The feature should not need to know whether the primitive is backed by
native HTML, Radix, shadcn, MUI, Chakra, Bootstrap, or another UI library.

Do not:

- Do not scatter raw `button`, `input`, `select`, dialog/menu primitives, or
  third-party UI components throughout feature screens when a design-system
  primitive must own the product contract.
- Do not expose every library prop unchanged. Keep supported customization
  narrow and semantic; add explicit escape hatches only when a real caller needs
  them.
- Do not postpone wrappers because final visual design is missing. Start with
  the smallest semantic primitive and evolve tokens, variants, and stories as
  the design matures.
- Do not let a feature screen become the first and only place that defines
  product button, input, card, dialog, table, or feedback behavior.

## Token Rules

Prefer semantic tokens over raw values:

```text
surface.default
surface.raised
text.primary
text.muted
border.subtle
accent.interactive
status.success
status.warning
focus.ring
motion.fast
radius.control
```

Rules:

- Tokens should describe purpose, state, and hierarchy, not only hue names.
- Dark mode, high contrast, reduced motion, and density changes should be token
  decisions when the repo supports them.
- Avoid introducing one-off colors, shadows, radii, and breakpoints in feature
  screens when an existing token or primitive can express the need.
- Typography tokens should cover body, label, heading, code, numeric, and
  compact UI text. Do not use hero-scale type inside dense tools, tables, cards,
  dialogs, or sidebars.
- Motion tokens should include duration and easing; never make animation
  required to understand state.

## Primitive Contracts

A primitive must define:

- states: default, hover, active, focus-visible, disabled, loading, invalid,
  selected, expanded, read-only when applicable
- accessibility: role, name, keyboard behavior, focus handling, ARIA state,
  target size, and screen-reader behavior
- layout contract: intrinsic size, min/max size, text wrapping, icon alignment,
  density, and responsive behavior
- theme contract: light, dark, high contrast, and reduced motion behavior when
  supported
- caller contract: controlled value, callbacks, slots, variant names, and what
  product policy stays outside

Do not make primitive variants named after specific pages, customers, plans,
roles, or workflows. Use semantic names such as `primary`, `secondary`,
`danger`, `ghost`, `compact`, `dense`, `success`, or repo-local equivalents.

## Component API Shape

For reusable web components:

- Prefer explicit props and slots over many boolean flags.
- Use caller-owned callbacks such as `onSubmit`, `onRetry`, `onDismiss`, and
  `onSelectionChange`.
- Let callers own copy, route decisions, analytics event names, permissions,
  billing, tenant filtering, and network/cache behavior.
- Keep transient UI state local: focus, hover, expanded, draft text before
  commit, drag state, popover open.
- Make controlled state explicit when persistence, URL sync, or cross-component
  coordination matters.
- Provide examples, fixtures, stories, or tests for important states before
  replacing existing UI at scale.

Avoid APIs like:

```text
variant="adminBillingInviteDangerMode"
isWorkspacePage
shouldNavigateAfterSave
analyticsEventName hidden inside the primitive
repository/client/router props
```

Those are signals the component is absorbing feature policy.

## Styling Ownership

Use the repo's styling system first: CSS variables, Tailwind/theme tokens,
CSS modules, vanilla-extract, styled-components, design-system classes, or
component library variants.

Rules:

- Keep styling decisions close to the component that owns the visual contract.
- Keep layout primitives separate from product sections. A stack/grid/surface
  primitive must not know feature copy or data.
- Avoid nested cards and decorative wrappers that create unclear hierarchy.
- Define stable dimensions for fixed-format controls, tables, grids, toolbars,
  boards, and icon buttons so hover, loading, badge, and long-text states do not
  resize the layout unexpectedly.
- Long localized text must wrap or truncate intentionally. Buttons, tabs, menu
  items, cards, and table cells need overflow behavior.
- Icon-only controls need accessible names and tooltips when the icon meaning is
  not obvious.

## Adoption And Migration

When introducing or expanding a web design system:

1. Inventory repeated UI patterns and the states they currently support.
2. Pick the smallest stable primitive or composed component to extract.
3. Define token and variant names from product semantics, not first-screen
   styling.
4. Add examples or tests for key states before broad replacement.
5. Replace one surface or feature at a time.
6. Leave old patterns with a removal condition or deprecation note when they
   cannot be removed immediately.
7. Verify layout, focus, keyboard, long text, theme, and responsive states.

Do not rewrite a whole app for visual consistency unless the user asked for a
design-system migration and the acceptance criteria include rollout scope.

Do not merge a reusable web primitive or composed component without a story,
fixture, preview route, component test, visual snapshot, or Playwright screenshot
when the repo has any practical way to produce one. The preview must be
deterministic and cover the states affected by the change; it must not fetch
real data, depend on current time, or require credentials.

## Verification

Choose the strongest practical evidence:

- component tests for roles, labels, keyboard behavior, controlled state, and
  callbacks
- visual snapshots or Playwright screenshots for responsive layout, dark mode,
  long text, empty/loading/error states, and dense screens
- accessibility checks for focus order, ARIA state, dialog/menu behavior, form
  labels, contrast, and hit targets
- story/fixture review for all variants and states
- token scan for one-off colors, type sizes, radii, z-index, or motion values

Report which layer changed: token, primitive, composed component, product
pattern, or screen.
