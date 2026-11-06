---
keyflow_id: sys_figma_handoff_verification
status: review
type: ai-generated
---

# Verification Harness

Figma handoff verification has three layers: offline regression, generated
bundle validation, and optional live smoke testing. It does not require a
specific team's token or Figma file as a default fixture.

## 1. Offline Regression

The tests inject fake API clients and response streams; they do not use the
network.

- `test_figma_handoff.py`: URL/node parsing, fetch batching, prototype flow,
  styles, variables, asset formats, and fallback behavior
- `test_figma_api.py`: authenticated redirect isolation, error sanitization,
  public-host enforcement, bounded downloads, format signatures, and retry caps
- `test_figma_flow_fetch.py`: partial batch failure isolation
- `test_figma_render.py`: asset deduplication, format-specific fallbacks,
  concurrency, path containment, and asset caps
- `test_figma_metadata_fetch.py`: optional variable metadata when Dev Mode or
  the current account/plan denies the variables endpoint
- `test_figma_analysis.py`: overlapping-root deduplication
- `test_figma_validate.py`: malformed summary shapes, schema-v4 visibility
  partition leaks, excluded asset/action leaks, and validator CLI behavior
- `test_figma_live_smoke.py`: frame-scale and non-empty layout negative controls
- `test_figma_fidelity_harness.py`: synthetic golden coverage for rotation,
  opacity, strokes, masks, blend modes, gradients, variable aliases, text runs,
  inherited visibility, hidden work-list/action exclusion, and node-scoped paints
- `test_figma_visibility_analysis.py`: focused self/ancestor visibility,
  implementation partition, and exact node-paint provenance
- `test_figma_standalone.py`: dry-run behavior from another working directory,
  Python isolated mode, default output, and safe error information
- `test_figma_secrets_boundary.py`: local-path, token-material, and runtime
  import boundaries

Run from the repository root:

```bash
python3 -m py_compile scripts/figma-handoff/figma-handoff.py \
  scripts/figma-handoff/figma_*.py scripts/figma-handoff/live_smoke.py
python3 -m unittest discover -s tests -p 'test_figma*.py'
```

Every offline test must pass without a token or Figma network access. New fetch
behavior must go through the existing network mocks.

## 2. Bundle Validator

`figma_validate.py` reads any `design-summary.json` and checks schema invariants
and fidelity coverage.

Installed runtimes expose `<MORU_LAUNCHER> figma-validate <summary-path>`.
Native validation preserves problem ordering, schema-v4 visibility exclusions,
coverage deduplication, report text and exit status. The source-bound launcher
handles ordinary file errors with the original argument spelling, UTF-8 errors
with byte offsets, and JSON syntax errors with Unicode character positions.
Decoding precedes universal-newline conversion and JSON validation. Numeric
summation and diagnostic differences use checked build profiles. It defers before
output for unsupported strings/depth, streams or numeric conversion exceptions. Direct
Python and imported callers remain the reference path.
The numeric build profile distinguishes sequential sums, compensated float-only
sums, and compensated float/integer sums. Its boundary probes track the
[CPython 3.9](https://github.com/python/cpython/blob/v3.9.0/Python/bltinmodule.c),
[3.12](https://github.com/python/cpython/blob/v3.12.0/Python/bltinmodule.c), and
[3.14](https://github.com/python/cpython/blob/v3.14.0/Python/bltinmodule.c)
implementations, including the transition to generic addition after C-long
overflow. An unrecognized profile fails the build instead of guessing.
`test_native_figma_decode` covers version-specific trailing commas, invalid
escapes, BOMs, integer digit limits, multibyte text, CRLF/CR and invalid UTF-8
across buffer-sized boundaries. Existing parser consumers retain their prior
invalid-versus-unsupported classification; diagnostics do not silently widen it.
`test_native_figma_validate` compares both processes and repeats supported cases
with no executables in PATH; portable bundle smoke exercises the same alias.

```bash
python3 scripts/figma-handoff/figma_validate.py \
  <bundle>/summary/design-summary.json
```

- Exit `0`: no schema violations
- Exit `1`: schema invariant violation
- Exit `2`: argument or file-read failure

The CLI runs the same validator during bundle creation and reports problems in
`warnings` and stderr. When adding or changing summary fields, update the
validator, schema document, and synthetic fidelity fixture together.

For schema v4, include a negative control that injects an excluded node into a
rendered implementation list. The validator must reject the overlap or leak;
a passing happy-path fixture alone does not prove the guard.

## 3. Live Smoke

`live_smoke.py` calls the real Figma API to check frame downloads, requested
render scale, non-empty layout coverage, asset format selection, and image-fill
recovery. It has no embedded default URL; provide a small frame URL that the
caller is authorized to use. Dev Mode is not required, and denied variable
metadata is reported as a non-fatal warning.

```bash
python3 scripts/figma-handoff/live_smoke.py \
  --url "$FIGMA_SMOKE_URL" --scale 3
```

Use `--quick` to skip asset export and check only the schema, frame PNG, and
layout coverage. Use `--token-env` to select a different environment variable.

- If the token environment variable is missing, the harness prints `SKIP` and exits `0`.
- If a token is present but the URL is missing, it reports a usage error.
- It writes real artifacts to a temporary directory and removes them on exit.
- It does not print tokens or signed render URLs.

Offline tests do not prove behavior that requires the real API. Conversely, a
token-less CI environment should not treat the intentional live-smoke skip as a
failure. A configured token without access to a suitable test file is also not
evidence of a broken CLI; it means the live permission boundary remains
unverified until an authorized URL is supplied.

## 4. Documentation And Independence Checks

Before release, also verify that:

- Markdown links in the skill and tool point to files that exist in this checkout
- shared execution docs contain no external CLI checkout, personal absolute
  path, company identifier, or AI-runtime-specific fallback
- `.figma-handoff-work/`, legacy output directories, tokens, signed URLs, and
  Python caches are not tracked
- the token setup instructions use an environment variable or secret manager,
  never a command-line argument or checked-in file
