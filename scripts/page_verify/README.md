---
keyflow_id: sys_moru_page_verify_readme
status: draft
type: ai-generated
---

# Page verification

A stop-time check of a finished web page: it serves the built page, drives it in a real browser and hands
what it found back to the agent that built it.

## What runs without any model

Always, when node and a browser are present: the page loads without errors, the main action changes the
page, pointer input reaches the visible controls and the scene (nothing invisible sits over them), a short
touch-viewport look, and a half-second timeline of the page's own numbers. Failures go back to the builder,
and the builder is asked to look at its own running page once.

## An optional second model

A model that did not build the page can judge the request's acceptance items from the screenshots, the
timeline and the source. It is **off unless you choose it**. Nothing is chosen because a key or a CLI exists.

Choose once in `~/.moru/verify.json`, or for one run with environment variables (the environment wins):

```json
{"backend": "codex", "model": "<model>", "effort": "low"}
```

| backend | what it uses | cost |
| --- | --- | --- |
| `none` (default) | no judge | none |
| `codex` | the local `codex exec`, read-only, no user config, no kept session | your Codex plan |
| `openrouter` | OpenRouter, only with `MORU_VERIFY_ALLOW_PAID=1` as well | billed per call |

Environment: `MORU_VERIFY_BACKEND`, `MORU_VERIFY_MODEL`, `MORU_VERIFY_EFFORT`, `MORU_VERIFY_CONFIG`
(path of the file). A judge service for sandboxed agents is `judge_service.py`; it needs the same choice.

## Is the judge worth it

Each judged check appends one line to `~/.moru/verify-effect.jsonl` (override with
`MORU_VERIFY_EFFECT_LOG`): backend, model, seconds, how many items passed, were contradicted, could not be
verified, and which failed. Compare runs with and without a judge before keeping one.
