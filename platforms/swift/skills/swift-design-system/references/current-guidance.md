---
keyflow_id: sys_swift_design_system
status: review
type: human-reviewed-needed
---

# Swift Design System

Use when creating, changing, reviewing, or adopting SwiftUI, UIKit, or AppKit
design-system tokens, primitives, component variants, layout patterns, themes,
interaction states, previews, or visual QA rules.

Also use:

- `common/skills/design-system/SKILL.md` for the cross-platform design-system
  baseline.
- `common/skills/component-api-design/SKILL.md` for reusable component contracts,
  slots, callbacks, and caller-owned policy.
- `common/skills/ui-visual-verification/SKILL.md` for visual and interaction evidence.
- `common/skills/accessibility-i18n/SKILL.md` for labels, Dynamic Type, localization,
  input, and accessible states.
- `platforms/swift/skills/swift-code-structure/SKILL.md` for design-system package ownership and resource
  boundaries.
- `platforms/ios/skills/ios-swiftui-ui/SKILL.md` or `platforms/ios/skills/ios-uikit-ui/SKILL.md` when the component is
  part of an iOS screen workflow.

## Layer Model

Use this ownership model:

```text
tokens -> styles/modifiers -> primitives -> composed controls
-> product patterns -> screens
```

- Tokens define semantic decisions: color role, typography, spacing, radius,
  stroke, shadow/elevation, motion, icon size, density, and z-order.
- Styles/modifiers translate tokens into SwiftUI `ViewModifier`, `ButtonStyle`,
  `LabelStyle`, `TextFieldStyle`, or UIKit/AppKit configuration helpers.
- Primitives define accessible behavior and styling contracts: button, input,
  label, badge, chip, menu, popover, sheet, dialog, list row, toolbar item,
  skeleton, progress, toast, empty state, permission state.
- Composed controls combine primitives into reusable UI shapes: search field,
  settings row, metric tile, status pill, form section, action toolbar.
- Product patterns may know a workflow, such as onboarding, invite, billing,
  permission, or account recovery.
- Screens compose product patterns and feature-local sections.

Do not push product policy, navigation, analytics names, repository calls,
permission decisions, or feature copy into primitives.

## Product-Prefixed Wrappers

SwiftUI, UIKit, and AppKit controls used across the product must enter
features through product/repo-prefixed design-system wrappers, styles, or
configuration helpers. Even a button must become a stable primitive such as
`<Product>Button`, `AppButton`, `DsButton`, or the repo's established prefix
when it appears in repeated product UI.

The wrapper must own semantic variants, token mapping, loading/disabled/error
states, Dynamic Type behavior, accessibility labels/traits, slots, sizing, and
platform appearance defaults. The feature should not need to know whether the
primitive is backed by native SwiftUI, UIKit/AppKit, or a third-party library.

Do not:

- Do not scatter raw `Button`, `TextField`, `Toggle`, `Picker`, `Menu`, `List`,
  UIKit/AppKit controls, or third-party controls throughout feature screens when
  a design-system primitive must own the product contract.
- Do not expose every native or third-party parameter unchanged. Keep supported
  customization narrow and semantic; add explicit escape hatches only when a
  real caller needs them.
- Do not postpone wrappers because final visual design is missing. Start with
  the smallest semantic primitive and evolve tokens, variants, and examples as
  the design matures.
- Do not let a feature screen become the first and only place that defines
  product button, input, card, dialog, or feedback behavior.

## Token Rules

Prefer semantic tokens over raw values:

```text
color.surface.default
color.surface.raised
color.text.primary
color.text.secondary
color.border.subtle
color.accent.interactive
color.status.success
color.status.warning
typography.body
typography.label
spacing.controlGap
radius.control
motion.fast
```

Rules:

- Tokens describe role, state, hierarchy, density, and platform behavior, not
  only hue names or first-screen styling.
- Dark mode, increased contrast, reduced motion, Dynamic Type, control density,
  and disabled/focused/selected/error states should be token or primitive
  decisions when the repo supports them.
- Avoid raw `Color`, `UIColor`, `NSColor`, `Font`, `UIFont`, `NSFont`, shadow,
  radius, or spacing values in repeated feature screens when an existing token
  or primitive can express the need.
- Typography tokens should cover body, label, title, compact UI, numeric text,
  monospaced/code text, and dense controls. Do not use hero-scale type inside
  compact panels, tables, forms, dialogs, or toolbars.
- Motion tokens should include duration and easing. Never make animation
  required to understand state.
- Domain and data models should not carry platform color, font, image, or view
  types. Use display semantics such as `status: .warning`, then map to tokens
  at the UI boundary.

## Primitive Contracts

A Swift design-system primitive must define:

- states: default, pressed, focused, disabled, loading, invalid, selected,
  expanded, read-only, empty, and destructive when applicable
- accessibility: label, hint, value, traits, focus behavior, hit target,
  VoiceOver behavior, keyboard behavior, and reduced-motion behavior
- layout contract: intrinsic size, minimum size, text wrapping/truncation, icon
  alignment, control density, safe-area behavior, and container constraints
- theme contract: light, dark, increased contrast, material/vibrancy, and
  platform appearance behavior when supported
- caller contract: controlled value, bindings, callbacks, slots, variants, and
  what product policy remains outside

Use semantic variants such as `primary`, `secondary`, `destructive`,
`success`, `warning`, `ghost`, `compact`, or repo-local equivalents. Do not
name primitive variants after pages, roles, customers, plans, or workflows.

## SwiftUI API Shape

For reusable SwiftUI components:

- Prefer explicit initializers, `@Binding` for caller-owned editable state, and
  callbacks named by user intent such as `onSubmit`, `onRetry`,
  `onDismiss`, and `onSelectionChange`.
- Use `@ViewBuilder` slots for caller-owned content when the visual shell is
  stable and product copy or actions vary.
- Use styles and modifiers when the caller should keep the native control
  behavior but adopt design-system visuals.
- Keep transient UI state local: focus, hover, pressed, expanded, selection,
  draft input before commit, animation phase, and popover open state.
- Avoid many boolean flags that create impossible combinations. Prefer a typed
  variant, configuration value, or small state model.
- Avoid `AnyView` or broad type erasure unless it protects a real public API or
  storage boundary.
- Keep theme values in scoped environment keys only when the dependency is a UI
  concern. Do not use the environment to hide repositories, analytics,
  permissions, or domain services inside primitives.

## UIKit And AppKit Bridge

For UIKit or AppKit surfaces:

- Prefer explicit component wrappers, configuration helpers, or style objects
  over broad global appearance changes.
- Use `UIAppearance` or app-wide AppKit appearance overrides only when the
  design-system contract is intentionally global and verified across screens.
- Bridge semantic tokens to `UIColor`/`NSColor`, `UIFont`/`NSFont`, materials,
  vibrancy, and control metrics at the platform boundary.
- Respect trait collection, content size category, increased contrast, focus,
  keyboard navigation, safe areas, and window size changes.
- Keep UIKit/AppKit wrapper code out of domain and data packages.

## Previews And Fixtures

Every new or meaningfully changed primitive, composed control, or product
pattern needs a preview, fixture, story, snapshot, or equivalent visual check
when the repo supports one.

Cover affected states:

- default, hover/pressed/focused, disabled, loading, error, empty, selected,
  expanded, destructive
- light and dark appearance
- Dynamic Type or long localized text
- compact and regular width or relevant window sizes
- permission denied, unavailable, or offline states when the component displays
  platform capability

Previews and fixtures must not call network, persistence, Keychain, random data,
current time, real credentials, device-only services, or user-specific files.

## Adoption And Migration

When introducing or expanding a Swift design system:

1. Inventory repeated controls and the states each currently supports.
2. Extract the smallest stable token, style, primitive, or composed control.
3. Name variants from semantic product roles, not first-screen styling.
4. Add previews, fixtures, or tests for important states before broad
   replacement.
5. Replace one feature, screen, package, or target at a time.
6. Leave old patterns with a removal condition when they cannot be removed in
   the same slice.
7. Verify accessibility, Dynamic Type, long text, appearance changes, focus,
   keyboard behavior, and platform-specific sizing.

Do not rewrite a whole app for visual consistency unless the user asked for a
design-system migration and acceptance criteria define rollout scope.

## Verification

Choose the strongest practical evidence:

- SwiftUI previews, preview snapshots, or equivalent fixture review for variants
  and states
- XCTest or Swift Testing for configuration, style mapping, formatter, and
  callback behavior when it is testable without rendering UI
- XCUITest or manual UI smoke for critical controls, forms, dialogs, menus,
  permissions, keyboard, and focus behavior
- accessibility checks for labels, traits, focus order, Dynamic Type, contrast,
  hit target, and reduced motion
- token scan for one-off colors, fonts, radii, spacing, shadows, z-order, or
  motion values in repeated UI

Report which layer changed: token, style/modifier, primitive, composed control,
product pattern, or screen.
