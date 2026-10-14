---
keyflow_id: sys_browser_runtime_testing
status: stable
type: human-reviewed-needed
moru_card_contract: strict
---

# Browser Runtime Testing

Use when verifying browser UI behavior, runtime wiring, network calls, console
errors, DOM state, accessibility tree, storage, routing, forms, or performance
signals.

The goal is to inspect the running browser path, not only the source code.

## Use When

- A web UI change affects navigation, interaction, form state, rendering,
  assets, network, storage, auth, or browser-only APIs.
- A bug only appears in the browser.
- A review needs evidence from console, network, DOM, accessibility, or
  performance tools.
- A web performance pass needs runtime data.

For pure server or non-browser code, use the matching platform verification
card instead.

## Inspect First

- Repo-local dev server, preview, test, and browser automation commands.
- Affected route, viewport, user state, fixture data, and environment variables.
- Existing Playwright, Cypress, Testing Library, visual, or accessibility setup.
- Security and privacy boundaries for auth, tokens, storage, and logs.

## Decision Rule

Use browser runtime evidence when source-level checks cannot prove that the user
path is reachable, visible, wired to the intended command, free of runtime
errors, and behaving under relevant states.

## Process

1. Start the repo-supported local server or preview only when needed.
2. Open the affected route and perform the user action.
3. Check console errors and warnings relevant to the change.
4. Check network requests, status codes, payload shape, and caching when the
   change touches data or assets.
5. Check visible DOM, accessibility roles/labels, focus, and state changes.
6. Capture screenshot, geometry, trace, or test evidence when useful.
7. Stop temporary servers before finishing unless the user needs them running.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "The component test passed." | Verify the browser path when routing, assets, auth, network, or storage can break it. |
| "No compile errors means it renders." | Open the route or run a browser test for browser-only behavior. |
| "The screenshot looks fine." | Also check the action, network, console, and accessibility evidence relevant to the change. |
| "Manual clicking is enough." | Record scenario, environment, action, expected result, and observed result. |

## Red Flags

- Console errors appear after the changed interaction.
- Network calls fail, retry endlessly, or return unexpected cache/stale data.
- The DOM is visible but the intended command does not execute.
- Assets, fonts, icons, or images fail to load.
- Focus, labels, keyboard interaction, or responsive layout break at relevant
  viewport sizes.

## Do Not

- Do not claim browser verification from a build, typecheck, or unit test alone.
- Do not inspect authenticated or sensitive storage values unless the task
  requires it and privacy policy allows it.
- Do not leave dev servers running without reporting the URL, port, and stop
  condition.
- Do not use screenshots as proof that network writes, permissions, or trusted
  commands succeeded.
- Do not ignore browser warnings that point to the changed boundary.

## Stop If

- Required credentials, seed data, or environment values are missing and would
  make browser evidence misleading.
- Browser execution would mutate external state without approval.
- The test environment would expose secrets, private data, or production
  resources.

## Verification

Use Playwright/Cypress/browser tests, Testing Library in browser mode,
screenshots, accessibility-tree assertions, network/console checks, performance
traces, or a documented manual smoke. Match the evidence to the claim.

## Report

Report the browser, route, viewport, user action, observed result, console or
network findings, and whether any server remains running.
