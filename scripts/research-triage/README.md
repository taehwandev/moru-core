---
keyflow_id: sys_moru_ms_research_triage_adapter
status: review
type: ai-generated
---

# OpenRouter Research Triage Adapter

This repository-owned CLI optionally evaluates collected research sources with
OpenRouter's Decisions API. It defaults to the free Mercury Decide model and can
explicitly use Microsoft-Decision-1. It ranks relevance and classifies source
type; it neither searches the web nor generates names, ideas, or a report.
Every input source remains in the output, including failures and low scores.

## Ownership And Acceptance

Owner: `scripts/research-triage/microsoft_decision.py`, one optional CLI adapter.
Allowed imports: Python standard library. Forbidden imports: Moru lifecycle,
permission, routing, other model providers, and external SDK dependencies.
Callers: agents selecting the optional planning-research step, or an operator.
Tests: `tests/research-triage/test_microsoft_decision.py`.
Verification: offline CLI/HTTP-contract tests, cache invalidation/resume tests,
workflow validation, and diff hygiene. A live response needs separate credential
availability and matching usage authority; mocks do not establish model quality.

Documentation decision: created this integration contract and updated the
planning-research entrypoint. No existing executable research adapter was found.
Common research policy remains in the source-triage reference.

## Input And Execution

Create an ignored research input JSON file with a nonempty `query` and a
`sources` array. Each source needs a unique `id`, `url`, `title`, and nonempty
`text`; `published_at` and boolean `required` are optional. `required` marks
sources that must be read regardless of ranking.

```json
{
  "query": "Which user complaints should inform a note-taking product?",
  "sources": [{
    "id": "interviews",
    "url": "https://example.org/interviews",
    "title": "Interview findings",
    "text": "Participants reported difficulty finding previously saved notes.",
    "required": true
  }]
}
```

From the Moru checkout, inspect reusable decisions without network calls or
cache writes:

```sh
python3 scripts/research-triage/microsoft_decision.py \
  --input .moru/research-input.json --cache-dir .moru/research-cache/ms
```

New calls require `--execute`. Read `OPENROUTER_API_KEY` from the invoking
process environment; the CLI does not create credentials, read env files, or
print the key. The free model has provider rate limits; an OpenRouter account
and credits are needed for paid requests. There is no automatic paid fallback.
The operator can manage a capped key in the provider console.

Keep the key in the user-level file `~/.moru/research.env` with file permissions
`600`. It lives outside every repository, so all checkouts, worktrees, other
target repositories and agent sessions share one location. It is not in shell
profiles such as `~/.zshrc`; an agent that finds `OPENROUTER_API_KEY` unset
should look for this file before concluding there is no key. The agent then
sources it and runs the call itself; it never asks the user to paste the key
or run the command. Put this line in it and fill in the value locally:

```sh
export OPENROUTER_API_KEY=
```

Load that file in the same shell that runs the CLI:

```sh
source ~/.moru/research.env
```

The adapter does not load this file automatically. An already-running agent
does not inherit an export from a different terminal; load the file in the
invoking shell instead. Never paste the key into chat or tracked files. A
checkout-local `.moru/research.env` also works because `.moru/` is Git-ignored,
but it is visible only to that checkout.

```sh
python3 scripts/research-triage/microsoft_decision.py \
  --input .moru/research-input.json --cache-dir .moru/research-cache/ms \
  --execute --max-calls 10
```

From another target repository, use the adapter's path under the Moru root
instead of writing a project-local script:

```sh
source ~/.moru/research.env && python3 <MORU_ROOT>/scripts/research-triage/microsoft_decision.py \
  --input .moru/research-input.json --cache-dir .moru/research-cache/ms \
  --execute --max-calls 10
```

The default `inception/mercury-decide:free` has zero listed input and output
token price. Select `--model microsoft/microsoft-decision-1` only when a paid
comparison or a quality check justifies it. On 2026-10-13, OpenRouter listed
that model at $0.042 per million input tokens and zero output cost. These are
different models with the same Decisions request/response contract; lower price
does not prove better ranking. Check important-source misses on labeled Korean
and English samples before trusting either model's score. The selected model is
part of the cache key, so switching models cannot reuse another model's result.

For another target repository, execute the script from its resolved `<MORU_ROOT>`
path and place inputs/cache in that target's ignored local directory. Confirm
the directory is ignored before saving research data. Use collected public
sources for the first experiment; remote disclosure still needs matching scope.

The default is at most 10 new calls per invocation. Cache hits do not spend that
limit. Missing keys, exhausted call limits, HTTP errors, and invalid decisions
leave items unscored; ordinary research can continue. There are no automatic
retries, alternative models, or background calls. HTTP 400/413 skips the affected
source (`source_rejected` with `http_status`); an invalid response skips that
source (`invalid_response`). Other HTTP errors, including authentication,
credits, rate limits and server errors, or transport/cache-write failures stop
further calls while existing cache hits remain usable. A shared request-format
error can also produce 400 for several sources; the call cap still applies.

Before a new call, requests over 24,000 UTF-8 bytes are left unscored as
`request_too_large`, without consuming the call cap. This conservative bound
covers the whole JSON request, including the research question and rubrics;
it is not an exact tokenizer count or a guarantee of provider acceptance.
Prepare a relevant excerpt for long documents and retain the original URL.
The adapter does not silently truncate text. Changed excerpts have new cache
keys, and their judgment applies only to the supplied excerpt.

The five source-type probabilities must each be finite and between zero and
one. Their sum may differ from one by at most 0.025, allowing five values rounded
to two decimal places. Original provider values are preserved; larger deviations
are rejected. Provider rounding precision remains unverified by a live call.

Output is JSON with input-order `results`, a separate `ranked_ids` view, cache
hits, actual network-call count, and newly reported cost when available.
Unscored sources and `required` sources remain first in the review view. Unknown
source type or low relevance never causes automatic deletion or exclusion.

## Cache Contract

Each successful result is stored atomically under the digest of the full API
request and cache schema. The request includes the question, source URL/title/
text/date, fixed rubrics, endpoint, and configured model. Source IDs, retrieval
timestamps, `required`, and output ordering do not affect the decision key.
The cache stores the digest, evaluation time, and validated answers/provenance,
not the source body or credentials. Keep invocations serial for one cache;
concurrent invocations can duplicate a miss and bill twice.

Entries expire after 24 hours by default (`--ttl-hours` changes this). Use
`--refresh --execute` only when new evaluation is needed. A provider model alias
can change without changing its name; record the returned model, retain the
bounded lifetime, and refresh a small labeled sample after a known update.
Changing local ranking or thresholds reuses stored probabilities.

## Verification And Sources

```sh
python3 -m unittest discover -s tests/research-triage -p test_microsoft_decision.py
python3 scripts/workflow.py validate
```

Official API contracts checked on 2026-10-13:

- [OpenRouter Decisions API](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request):
  typed `state`/`questions` request and typed `answers` response.
- [Mercury Decide free model on OpenRouter](https://openrouter.ai/inception/mercury-decide%3Afree):
  model identifier, zero listed token price, and free-tier limits.
- [Microsoft model on OpenRouter](https://openrouter.ai/microsoft/microsoft-decision-1):
  model identifier and mutable weights. Provider prompt-cache support is unconfirmed.
- [Microsoft usage guide](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision):
  bounded judgments and workload-specific threshold validation.

Start with ranking only. A live smoke test on 2026-10-13 scored three synthetic
Korean/English sources in the expected order with $0 reported cost. Test actual
research sources and inspect important-source misses before considering exclusion.
Comparative quality against the paid model remains unverified.
