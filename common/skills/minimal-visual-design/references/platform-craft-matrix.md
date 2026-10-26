---
keyflow_id: sys_common_minimal_visual_design_platform_craft_matrix
status: review
type: ai-generated
---

# Platform Craft & Execution Matrix

Concrete execution rules for high-detail, high-craft UI across every Moru
platform. Load only the section matching the target platform or framework. Each
row pairs a recurring low-detail symptom with its native implementation recipe
and the falsifying check that proves it.

A repository's own design system, tokens, or Figma specification always takes
precedence over these defaults. For server/API error contracts and CLI boundary
ownership, pair this matrix with
`platforms/server/skills/server-api-implementation/SKILL.md`,
`platforms/python/skills/python-web-service/SKILL.md`, and
`platforms/application/skills/application-command-ui/SKILL.md`.

## 1. Web & React (`web`, `react-native` web)

| Low-Detail Symptom | Native Recipe | Falsifying Check |
| --- | --- | --- |
| Live counters, timers, prices, or table columns jitter horizontally when digits change | Apply `font-variant-numeric: tabular-nums` on every metric, badge, table cell, pagination counter, and timer | Update values across `1` -> `8` width extremes; assert bounding-box width remains constant (`delta == 0px`) |
| Bold or medium hover state shifts sibling labels or wraps a row | Keep font weight constant across `:hover`/`:active`, or reserve width via an invisible bold pseudo-element / grid track | Toggle hover/focus across nav items and buttons; verify `getBoundingClientRect().width` does not change |
| Scrollbars appearing or disappearing shifts page or modal layout | Set `scrollbar-gutter: stable` on scrollable containers and preserve scroll lock without body width jump | Toggle modal/drawer and short-to-long filter results; assert horizontal X coordinates of header/content stay fixed |
| Clicking a search icon, unit suffix, or currency prefix inside an input box fails to focus the input | Wrap the input and affixes in a `<label>` or delegate container `onMouseDown`/`onClick` to `inputRef.current?.focus()` | Click the outer padding and leading/trailing affix; assert `document.activeElement` is the `<input>` |
| Double-clicking a button, tab, chip, or toggle highlights its label text | Set `user-select: none` on interactive controls (`button`, `[role="button"]`, tabs, segmented controls) while keeping data/prose selectable | Rapidly double-click interactive controls; assert `window.getSelection().toString() === ""` |
| Skeleton loader or async image swap jumps the surrounding card or list | Match skeleton height, padding, and grid tracks to the loaded component; reserve media `aspect-ratio` and use `min-height` instead of collapsing during refetch | Throttle network or toggle loading -> loaded state; assert cumulative layout shift (CLS) for adjacent siblings is `0` |
| Nested card/button or input-in-toolbar corners look pinched or uneven | Compute concentric radii: `r_inner = max(0px, r_outer - padding)` (for example `12px` card with `4px` inset -> `8px` inner control) | Inspect nested corners at 200% zoom; inner and outer curves share a common center |
| Text hugs the edge of a card, button, badge or table cell, or mobile content is flush to the screen | Put `padding` on the element that paints the background (a `width: 100%` child with its own background needs its own), pad scroll content rather than its clipping wrapper, and set the page gutter once on the layout shell | Run the content-to-edge padding check from `ui-visual-verification` at 375px and 1280px; zero unexplained surfaces |
| Hover-only action menu (`:hover` / `group-hover`) is unreachable on touch | Pair hover reveal with an explicit tap/click trigger, `:focus-visible` reveal, and outside-tap / `Escape` dismissal | Emulate a coarse-pointer touch viewport; open, activate, and dismiss the action without hover |

## 2. iOS SwiftUI & UIKit (`ios`, `swift`)

| Low-Detail Symptom | Native Recipe | Falsifying Check |
| --- | --- | --- |
| Text clips or truncates mid-word at Accessibility Dynamic Type (`AX1`-`AX5`) | Never put fixed `.frame(height:)` on text-bearing views. Scale icon/badge dimensions with `@ScaledMetric` and switch `HStack` to `VStack` via `ViewThatFits` or `@Environment(\.dynamicTypeSize.isAccessibilitySize)` | Preview or run with `DynamicTypeSize.accessibility3` and `.accessibility5`; assert zero clipped glyphs or overlapping controls |
| SF Symbols look too thin, too heavy, or misaligned next to text | Bind `.font()` weight and `.imageScale()` to the adjacent text style, use `Label` or `.alignmentGuide(.firstTextBaseline)`, and apply `.symbolRenderingMode(.hierarchical)` or `.palette` intentionally | Inspect icon+label rows at default and `AX3` sizes; symbol stroke weight and baseline match the text |
| Rounded cards look harsh or mismatched against iOS hardware bezels | Use `.clipShape(.rect(cornerRadius: r, style: .continuous))` (or concentric container shapes) and keep inner/outer radii concentric (`r_inner = max(0, r_outer - inset)`) | Render light/dark previews; verify continuous squircle curvature and concentric nested insets |
| Live numeric changes snap abruptly or cause horizontal jitter | Use `.monospacedDigit()` on changing counters/metrics and pair value updates with `.contentTransition(.numericText())` inside `withAnimation` | Step values up and down; digits transition smoothly without shifting adjacent views |
| Double bottom padding or clipped CTA when the software keyboard opens | Consume safe-area and keyboard insets once at the screen container (`safeAreaInset(edge: .bottom)` or root `NavigationStack`/`ScrollView`); do not stack manual bottom padding on child overlays | Open and dismiss the software keyboard on an input screen; bottom CTA and last field remain visible with no double gap |
| Destructive, toggle, or confirmation actions feel flat and unresponsive | Attach contextual haptics via `.sensoryFeedback(.selection, trigger:)` or `.sensoryFeedback(.warning, trigger:)` (or `UIImpactFeedbackGenerator` / `UINotificationFeedbackGenerator` in UIKit) | Trigger state change; verify sensory feedback modifier is bound to the state transition rather than raw tap down |
| Card or capsule fill runs right up to the label | Order modifiers `.padding()` then `.background()`/`.overlay()`; `List`/`Form` rows keep system insets, and custom `ScrollView` content uses `.contentMargins` or inner padding | Snapshot or view-debugger check: label frame sits inside the background frame by the expected inset on all sides |
| Small icon buttons miss taps near their visual edges | Ensure every interactive control has at least a `44x44pt` hit region via `.contentShape(.rect)` and minimum frame constraints | Inspect in Accessibility Inspector; assert hit frame is `>= 44x44pt` |

## 3. Android Jetpack Compose (`android`)

| Low-Detail Symptom | Native Recipe | Falsifying Check |
| --- | --- | --- |
| Status bar, navigation bar, or IME keyboard either overlaps content or adds double padding | Use one root `Scaffold` (or repo design-system scaffold) that passes `innerPadding` to content and consumes `WindowInsets` once. Choose a single IME owner (`imePadding()` on the root or bottom bar, never both) | Test with gesture navigation and 3-button navigation, IME open and closed; assert zero overlap and zero double-inset gap |
| `Surface`/`Card`/`Box` with a background shows text touching its edge, or a `LazyColumn` clips its first and last items | Order `Modifier.background(...)` (or `Surface`) before `.padding(...)` so the inset is inside the fill; use `contentPadding` on lazy lists instead of outer padding; a `fillMaxWidth()` child with its own background carries its own padding | UI test compares `getBoundsInRoot()` of the text node and its surface from the unmerged tree; each edge differs by at least the expected dp |
| Compact icon buttons, chips, or trailing actions are hard to tap | Keep touch targets at least `48.dp` via `Modifier.minimumInteractiveComponentSize()` or explicit padding before `clickable` in the modifier chain | Run Compose semantics/accessibility check; assert all clickable nodes report `>= 48.dp` touch bounds |
| Icon + text or metric + unit rows look vertically off-center | Align text and unit labels with `Modifier.alignBy(FirstBaseline)` (or `alignByBaseline()`) and center leading icons against the first line cap-height rather than the multi-line container height | Render 1-line and 2-line wrapped text in `@Preview`; icon stays anchored to line 1 and units share the text baseline |
| Expanding cards, filter chips, or async state swaps snap or overshoot | Use finite spring specifications (`Spring.DampingRatioNoBouncy`, `Spring.StiffnessMediumLow`) with `animateContentSize()` or `AnimatedContent`, and key transitions by stable state identity | Toggle state expansion and loading -> content; transition settles smoothly without bounce overshoot or layout jump |
| Dark-mode cards blend into the background when tonal elevation contrast is low | Add a `1.dp` `MaterialTheme.colorScheme.outlineVariant` (or low-alpha semantic border token) hairline on elevated dark surfaces when surface luminance delta is `< 4%` | Render dark-theme `@Preview(uiMode = UI_MODE_NIGHT_YES)`; card boundaries remain clearly distinguishable |
| Font scaling (`fontScale = 2.0f`) clips text inside cards, badges, or buttons | Never use fixed `Modifier.height(x.dp)` on text containers; use `Modifier.heightIn(min = x.dp)` and allow rows to wrap (`FlowRow` or adaptive column) | Render `@Preview(fontScale = 2.0f)`; assert no vertical text clipping or ellipsis on primary values |

## 4. Flutter & KMP Compose Multiplatform (`flutter`, `kmp`)

| Low-Detail Symptom | Native Recipe | Falsifying Check |
| --- | --- | --- |
| Non-linear system font scaling (`MediaQuery.textScalerOf(context)` / KMP density) overflows fixed containers | Replace fixed `SizedBox(height:)` / `Container(height:)` around text with `ConstrainedBox(constraints: BoxConstraints(minHeight: ...))` and adaptive `Wrap` or column reflow when text scale exceeds `1.3x` | Pump widget/composable test at `TextScaler.linear(2.0)` / `fontScale = 2.0f`; assert zero `RenderFlex overflowed` or clipped text |
| `Card`, `Container(color:)` or `DecoratedBox` content touches the edge (`Card` adds no inner padding) | Wrap card content in `Padding`, give `ListView`/`CustomScrollView` a `padding` or `SliverPadding`, and set the page gutter at the screen scaffold | Widget test compares `tester.getRect(find.text(...))` with the card's rect; each edge clears the expected inset |
| Desktop/web builds feel like stretched mobile apps with no pointer or keyboard affordances | Provide `MouseRegion` / `InkWell` hover states, `Shortcuts` + `Actions` (`FocusTraversalGroup`), and compact desktop density while keeping `48dp`/`48px` touch targets and platform scroll physics on mobile | Verify pointer hover cursor/highlight and `Tab`/`Enter`/`Escape` keyboard traversal on desktop target, plus touch bounds on mobile target |
| High-frequency ticker, chart, or shimmer animation repaints the whole screen | Isolate high-frequency custom paint or animation subtrees with `RepaintBoundary` (Flutter) or lambda-based draw/layout phase reads (`Modifier.drawWithCache`, `graphicsLayer { }`) in KMP Compose after profiling confirms repaint fan-out | Inspect repaint rainbow / composition counts; animated child updates without dirtying parent screen sections |
| Shared multiplatform UI ships raw Material chrome that feels alien on iOS or macOS | Route platform-sensitive chrome (dialogs, sheets, scrollbars, back gestures, menu bars) through target-aware design-system wrappers (`expect`/`actual` or platform theme adaptation) | Render on both mobile/desktop targets; navigation, scroll physics, and dialogs match target conventions |

## 5. Desktop Application & CLI (`application`)

| Low-Detail Symptom | Native Recipe | Falsifying Check |
| --- | --- | --- |
| Closing or resizing the window or split panes loses user workspace layout | Persist and restore shell geometry (window bounds, display clamp for disconnected monitors, split-pane ratios, collapsed sidebars) separately from product data | Resize window and split panes, restart/reopen, and test off-screen coordinates; geometry restores safely within visible screen bounds |
| Primary actions require hunting through nested menus with a mouse | Route every multi-entry-point action through a shared `Command` owner exposed in a keyboard-first Command Palette (`Cmd/Ctrl+K`), menu bar, and tooltip shortcut hint | Trigger the same command from keyboard shortcut, command palette, and toolbar; assert identical enabled/disabled guard and execution result |
| Panels, sidebars and table cells in dense desktop layouts drop horizontal padding | Keep dense density on vertical padding only; side panels, toolbars and cells keep at least 12px horizontal inset aligned with the panel edge | Capture the window at minimum and wide sizes; run the matching platform bounds check and inspect panel edges at native scale |
| Large log views, file trees, or data tables freeze window resize or scrolling | Virtualize rows (`LazyColumn` / virtual list), fix column widths with `tabular-nums`, and keep `1px` crisp hairline splitters aligned to device pixel ratio | Render 10,000-row fixture and resize window; scrolling and splitter drag remain responsive without main-thread stalls |
| Long-running background tasks or CLI commands hang silently or fail with an opaque exit code | Show determinate/indeterminate status-bar or CLI progress, support cancellation (`Ctrl+C` / cancel button) with resource cleanup, and emit structured failure output (what failed, why, and the exact copyable remediation command) | Cancel an in-flight command and trigger a failure path; assert zero leaked child processes/watchers and verify remediation message |

## 6. Server, Python & API Contracts (`server`, `python`, `web-service`)

Use this section when a UI/client quality task crosses into an API boundary or
when reviewing end-to-end recovery quality alongside
`platforms/server/skills/server-api-implementation/SKILL.md`:

| Low-Detail Symptom | Native Recipe | Falsifying Check |
| --- | --- | --- |
| Client UI can only show "Something went wrong" because the server returns raw strings or inconsistent `400`/`500` JSON | Return RFC 9457 Problem Details (or the repo's typed error envelope) with a stable machine `code`, `field_errors` (`field` path + reason), `request_id`/`correlation_id`, `retryable` boolean, and safe user summary | Contract test asserts validation, authz, conflict, and rate-limit responses include `code`, `request_id`, `retryable`, and field paths without leaking stack traces |
| Empty search/list state renders as a broken error screen (or vice versa) | Return `200 OK` with an empty collection (`items: []`, pagination metadata) for valid queries with zero matches; reserve `404` for a missing parent/target resource | Query an existing scope with zero items vs. a non-existent resource ID; assert `200 []` vs. `404` with distinct machine code |
| Retrying a slow mutation duplicates records or charges | Require or accept an `Idempotency-Key` on state-mutating POST/PATCH endpoints and return deterministic cursor pagination (`next_cursor`, stable sort tie-breaker) on lists | Replay the same mutation request with identical `Idempotency-Key`; assert single side effect and identical response |

## Sources

Ranked for relevance with the repository's OpenRouter research-triage pipeline
(`scripts/research-triage/microsoft_decision.py`, model
`inception/mercury-decide:free`, all 5 scored `0.94`-`0.99`):

- IETF RFC 9457, Problem Details for HTTP APIs (`0.9890`):
  https://www.rfc-editor.org/rfc/rfc9457.html
- Android Developers, Material Design 3 in Compose & Edge-to-Edge WindowInsets
  (`0.9859`):
  https://developer.android.com/develop/ui/compose/designsystems/material3
- Apple Human Interface Guidelines, Typography, Layout & SF Symbols (`0.9707`):
  https://developer.apple.com/design/human-interface-guidelines
- Flutter Documentation, Adaptive and Responsive Design (`0.9669`):
  https://docs.flutter.dev/ui/adaptive-responsive
- Rauno Freiberg / Vercel Web Interface Guidelines, Interaction & Micro-Detail
  Craft (`0.9399`):
  https://interfaces.rauno.me/
