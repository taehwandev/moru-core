---
keyflow_id: sys_web_react_ui
status: review
type: human-reviewed-needed
---

# Web React UI

Use when creating, changing, moving, or reviewing React routes, pages, feature
components, hooks, forms, UI state, server-state wiring, reusable components, or
frontend tests.

For architecture choice, also read `common/skills/architecture-design/SKILL.md`. For
data ownership, cache, forms, mocks, and browser persistence, also read
`platforms/web/skills/web-state-data/SKILL.md`. For route/file layout and import direction, also read
`platforms/web/skills/web-code-structure/SKILL.md`. For reusable UI extraction and design-system work,
also read `common/skills/reusable-code-design/SKILL.md`,
`common/skills/design-system/SKILL.md`, and `platforms/web/skills/web-design-system/SKILL.md`.

## React Layers

Use this shape unless the repo has a stricter local pattern:

```text
Route/Page -> Feature Container -> Screen/View -> Section Component
-> Feature Component -> Design-System Primitive
```

- Route/page owns URL params, route loaders/actions, layout shell, auth/session
  boundary composition, and top-level data dependencies.
- Feature container owns one user workflow and wires server state, form state,
  permission checks, and mutations.
- Screen/view renders the whole workflow from explicit state and callbacks.
- Section or block components render a coherent area of a screen. They receive
  only the view model slice and callbacks needed for that area.
- Feature components may know display models but not raw DTOs, API clients,
  routers, storage, or analytics dispatch.
- Design-system primitives own visual and interaction contracts, not product
  policy or business workflows.

## Mandatory Component Split

React screens must be split into named components instead of placing the full
page tree in one route, page, or screen file. A screen may own the top-level
state switch, but headers, filters, forms, table regions, rows, cards, dialogs,
empty states, error states, permission states, and action bars must become
section/block or feature components as soon as they have a distinct visual or
interaction responsibility.

Use a feature-local `components/`, `sections/`, or `blocks/` folder for UI that
belongs to one feature, and split it by role from the start with folders such as
`inputs`, `feedback`, `cards`, `tables`, `dialogs`, `navigation`, or
`data-display`. Promote only stable, domain-free controls into the web
design-system package.

Do not:

- Do not approve React UI that keeps distinct sections, rows, cards, dialogs,
  feedback states, and actions in one route/page/screen component or one file.
- Do not put every component for a route into `page.tsx`, `route.tsx`, or one
  `Screen.tsx` file because JSX makes nesting easy.
- Do not leave header, body, filters, table rows, empty/error/loading state,
  dialogs, and bottom actions inside one large component.
- Do not keep many named components in one `components.tsx` or `index.tsx` file
  once they can be tested, imported, previewed, or reviewed independently.
- Do not create a flat `components` folder that mixes unrelated inputs, cards,
  dialogs, table rows, feedback states, and feature-only product sections.
- Do not pass the entire screen state into every child to avoid designing
  smaller props.
- Do not import raw third-party primitives throughout features when the app has
  or needs product-prefixed design-system wrappers.
- Do not expose a library component unchanged as the product component. The
  wrapper must define semantic variants, slots, accessibility, loading/disabled
  behavior, token ownership, and supported escape hatches.

## Architecture Tracks

Choose the smallest track that protects the real risk:

| Track | Use When | Shape |
| --- | --- | --- |
| Simple Page | Static or local interaction only. | `Page -> component state` |
| Feature MVVM | Async data, form submit, permission state, or multi-state UI. | `Page/Container -> view model hook -> Screen` |
| Query/Mutation Boundary | Server state, cache invalidation, optimistic updates, or retries. | `Container -> query/mutation hooks -> client/mapper` |
| Clean Architecture | Domain policy, auth/tenant/billing, offline/sync, multiple clients, or reusable business rules. | `Screen -> feature hook/store -> use case -> repository/client` |
| Reducer/State Machine | Many events, explicit transitions, optimistic rollback, or complex form wizard. | `Component -> reducer/machine -> effects/use cases` |

Do not create a global store, use case layer, repository folder, or generic hook
only for ceremony. Add a layer when it isolates a real state owner, product
rule, side effect, or test boundary.

## React Runtime Boundaries

Use React APIs for their intended ownership:

- Render derives UI from props and state. Do not store derived values in state
  unless there is a sync or transition reason.
- Effects synchronize with external systems: subscriptions, browser APIs,
  timers, network boundaries not owned by a framework query layer, focus, media,
  or imperative integrations. Effects need dependencies and cleanup.
- Memoization is a performance or identity tool, not a correctness tool. Do not
  rely on `useMemo` or `useCallback` to hide mutable state or missing
  dependencies.
- Context is for stable cross-tree state or dependency boundaries. Do not add a
  provider for one route's temporary modal, tab, or draft state.
- Reducers or state machines are for eventful workflows with explicit
  transitions, not for simple field state.
- Error boundaries, suspense/loading boundaries, and route `loading`/`error`
  files should match the user-visible state they represent.
- Keys should identify stable list items. Do not use array index keys when item
  identity, local state, animation, or reorder behavior matters.

For frameworks with server/client components or server actions:

- Keep secrets, database access, server SDK clients, and trusted mutations in
  server boundaries.
- Pass serializable display data into client components.
- Isolate interactive client components instead of marking a whole page
  client-only.
- Treat hydration warnings as real bugs unless the repo has a documented,
  narrow exception.

For Next.js App Router specifically:

- A file marked `'use client'` must not export an async component. Fetch data in
  a Server Component, route handler, query layer, or explicit client effect
  boundary and pass state into the client component.
- Server-to-client props must be plain, browser-safe display data. Convert
  `Date` to strings, `Map` and `Set` to arrays or objects, class instances to
  plain objects, and never pass server request objects, clients, or raw records.
- Server Actions are the narrow exception for passing callable functions from a
  server boundary into client UI. Treat every other function prop across the
  server/client boundary as invalid.
- Wrap client hooks that force client rendering, such as `useSearchParams()` or
  dynamic-route `usePathname()`, in the Suspense boundary required by the
  framework version.
- Put route-level loading, error, not-found, unauthorized, and forbidden states
  in framework boundary files when those files are the nearest user-visible
  state owner.

## Feature Folder Shape

A feature can use:

```text
features/members/
  routes/MemberSettingsPage.tsx     URL and route boundary
  MemberSettingsContainer.tsx       data, permissions, mutations
  MemberSettingsScreen.tsx          pure screen rendering
  blocks/
    MemberListBlock.tsx             screen section, no data fetching
    InviteMemberBlock.tsx           screen section, callbacks out
  components/                       feature-local components
  model/
    memberSettingsTypes.ts          UiState, actions, display models
    memberSettingsMappers.ts        DTO/domain -> UI models
    memberSettingsPolicy.ts         named product rules
  api/
    memberSettingsClient.ts         HTTP/SDK boundary
  hooks/
    useMemberSettings.ts            state/effect wiring
  __tests__/
```

Adapt names to the repo's framework. Next.js, Remix, React Router, Expo Web,
and custom routers may place route files differently; keep the same ownership
boundaries.

## UiState Shape

Represent UI states explicitly. Prefer discriminated unions for mutually
exclusive screen states:

```ts
type ProfileUiState =
  | { kind: "loading" }
  | { kind: "content"; profile: ProfileViewData }
  | { kind: "empty" }
  | { kind: "permissionDenied" }
  | { kind: "offline"; cached?: ProfileViewData }
  | { kind: "error"; error: ErrorViewData };
```

Use structs with typed sub-states when content can have independent regions:

```ts
type CheckoutUiState = {
  form: CheckoutFormState;
  submit: "idle" | "submitting" | "succeeded" | "failed";
  entitlement: EntitlementState;
  banner?: BannerState;
};
```

Rules:

- Loading, empty, error, permission denied, offline, disabled, and submitted
  states must be representable when the flow can reach them.
- Avoid impossible boolean combinations such as `isLoading && error && data`.
- Convert DTOs before rendering. JSX must consume display models or UI models,
  not transport details.
- Keep protected access rules in named helpers or policy functions. UI hiding is
  not authorization.
- Keep one-off effects such as toast, navigation, focus, and file download
  separate from persistent state.

## Render Node And UiState Split

Treat `UiState` as a render and observation contract, not as a requirement to
pass one screen-shaped object through every React node. Split state and
components by owner, update cadence, render cost, and reuse contract.

Use a coarse screen `UiState` for top-level loading, content, empty, error,
permission, selected ids, stable summary values, and workflow capabilities.
Keep high-churn state closer to the React node that observes it:

- chat or conversation messages, virtualized list windows, row delivery status,
  read receipts, typing indicators, and presence
- text drafts before commit, focus, hover, drag, scroll, animation, timers,
  playback progress, live metrics, and cursors
- query/cache subscription data where selectors can update only the section,
  row, badge, or indicator that changed

For conversation UI, do not put the full message list, typing, presence, unread
markers, delivery status, and composer draft in one screen state object if each
change re-renders the whole screen. Use a stable screen state for thread
metadata and capabilities, a query/cache or external subscription for messages,
row display models with stable keys, and section-local state for composer and
interaction details. Use virtualization when list size or update cadence makes
the rendered node count a risk.

`memo`, `useMemo`, and `useCallback` are not substitutes for a correct state
boundary. Use them after the state owner and prop shape are right, and only for
real identity or render-cost issues. Avoid hiding a whole `UiState`, store, or
query result in context when a section prop, selector, or feature-local hook can
make the invalidation boundary explicit.

## Container And Screen Split

Containers may:

- Read URL params, route data, session, feature flags, permissions, and query
  results.
- Call framework query/mutation hooks or feature hooks.
- Map server state and mutation state into `UiState`.
- Pass callbacks such as `onRetry`, `onSubmit`, `onInvite`, or `onClose`.

Screens should:

- Receive `state`, callbacks, optional slots, and simple display models.
- Render states and emit intent.
- Avoid direct fetch calls, storage reads, router mutation, analytics dispatch,
  and permission policy evaluation.
- Keep local state only for presentation details such as menu open, dialog open,
  focus, draft text before commit, selected tab, hover, or transient animation.

## Section And Block Components

Use blocks to make large screens reviewable without creating a new product
boundary. A block is a named section of one screen, such as a summary strip,
filter bar, settings group, empty state area, table region, or side panel.

Blocks should:

- Render one coherent section from an explicit view model slice.
- Emit user intent through callbacks such as `onRetry`, `onSelect`, or
  `onOpenSettings`.
- Own only transient presentation state that is local to that section.
- Stay feature-local when the copy, layout, or policy is specific to one
  workflow.
- Use design-system primitives or feature components for repeated controls.

Blocks should not:

- Fetch data, read browser storage, mutate routes, or evaluate permissions.
- Import raw DTOs, API clients, repositories, analytics dispatchers, or server
  modules.
- Become shared components merely because a screen is long.
- Hide product policy behind props such as `mode`, `source`, `isAdmin`,
  `isBilling`, or caller-specific variants.

Promote a block to a reusable component only when there are at least two real
callers or a stable design-system contract, the caller still owns copy and
policy, and the component can be previewed or tested without the feature
container.

Leaf components should receive the smallest data shape they need. Do not pass a
whole `UiState` into a button, row, badge, or card when a smaller model works.

## Hooks

Use hooks for reusable state/effect wiring, not hidden product policy.

Good hook contracts:

```ts
const { state, submit, retry } = useCheckoutSession(orderId);
const policy = usePermissionPolicy(session);
```

Rules:

- Hook names should describe the state owner or integration boundary.
- Hooks that fetch or mutate server state should delegate HTTP/SDK details to a
  client and map DTOs at the boundary.
- Effects must have dependencies, cleanup, and abort behavior when relevant.
- Do not use `useEffect` to store derived state that can be calculated during
  render.
- Do not add context/provider state for one route's temporary interaction.

## Server State, Forms, And Mutations

- Use the repo's query/cache tool for server state when one exists. Do not copy
  server state into local state without a sync reason.
- Define invalidation after create, update, delete, invite, role, permission,
  billing, or tenant changes.
- Put optimistic updates behind explicit rollback behavior.
- Forms should model validation errors, dirty state, submit pending, success,
  permission denied, and network error.
- Do not put secrets or protected tokens in `localStorage`, `sessionStorage`,
  query params, logs, or client-visible config.

## Component Reuse

Before extracting a component or hook:

- Are there at least two real call sites or a stable design-system contract?
- Can it be named without the original feature name?
- Are copy, routes, analytics, permissions, and business rules owned by callers?
- Can Storybook, examples, component tests, or fixtures show the important
  states without feature setup?
- Will extraction remove duplicated fixes without creating a flag-heavy API?

Keep sections local when reuse would require `variant`, `mode`, `source`, and
many nullable options just to support unrelated screens.

## Verification

Choose the closest checks configured in the repo:

- TypeScript/typecheck for changed files.
- Unit tests for policy, mapper, reducer, state machine, and hook behavior.
- Component tests with Testing Library using role, label, visible text, and
  user interaction.
- E2E tests with Playwright/Cypress for critical flows, routing, auth,
  permissions, forms, and mutation paths.
- Accessibility checks for labels, roles, focus order, keyboard operation,
  contrast, text scaling, and dialog/menu behavior.
- Visual checks or screenshots for layout, responsive states, long text, empty
  state, error state, loading state, and dark mode when affected.

Review the final diff for raw fetch calls inside components, DTOs leaking into
JSX, duplicated permission checks, global providers for local state, missing
failure states, and reusable components that absorbed product-specific policy.
