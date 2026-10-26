---
keyflow_id: audit_skillspector_2026_10_26
status: draft
type: ai-generated
---

# Moru skill security inspection — 26 October 2026

Status: **draft; findings remain open; not a security certification**.

This report records an actual local SkillSpector run and a bounded follow-up
review of outbound HTTP paths. It does not establish that Moru Core, Moru Web,
the user's AI runtime, or a deployed service is free of vulnerabilities.

## Scope and reproducibility

| Item | Pinned input |
| --- | --- |
| Scanner | NVIDIA SkillSpector 2.12.0, commit `d7338f58200a9ae2a24810cee08911ab68b107a7` |
| Core baseline | `9ea31ed3ed85b9ef13b99d51d8312c457a506f67` plus the patches described below |
| Core skill scope | All 165 tracked `SKILL.md` bundles and their directory contents; 393 component records |
| Mode | `--no-llm --fail-on-findings --fail-on-incomplete`; no baseline or suppression |
| Web dependency input | Main commit `c677d02c7fbace947e864f4e85763619f1906ee3`, immutable package manifests |

The scanner and its lockfile were pinned before installation. Python 3.14 failed
to build YARA against the local OpenSSL; the successful run used an isolated
Python 3.12 environment and the unchanged upstream lockfile. No project
dependency was added. The scanner's own 32-skill recursive limit was avoided by
running a separate process for each tracked skill, with four concurrent processes.
All 165 processes produced reports successfully. Failure-policy exits were
retained: initially 133 exited 1 and 32 exited 0. Exit 1 here includes findings
and incomplete analysis, not just a crashed process.

For reproduction, check out the scanner revision and use its frozen lockfile
with `uv sync --frozen --no-dev --python 3.12`. Enumerate tracked manifests with
`git ls-files '*SKILL.md' '*skill.md'` and run the following for each parent
directory. Record the exit code even when a report was produced:

```sh
skillspector scan <SKILL_DIRECTORY> --no-llm --fail-on-findings \
  --fail-on-incomplete --format json --output <REPORT_JSON>
```

[inventory.json](inventory.json) binds every bundled file to its final SHA-256.
[summary.json](summary.json) preserves per-skill coverage and recommendations,
scanner-lock identity, initial raw artifact hashes and the targeted reruns.
[findings.json](findings.json) retains every final warning without suppression.
Machine-local source paths in these derived artifacts are replaced with
placeholders; raw scanner artifacts are retained outside the repository. The
final skill result set reuses 164 unchanged scans and the one changed skill's
rerun. Root scripts are outside those 165 bundles; three reviewed outbound
scripts were scanned separately after their patch, not silently counted as
part of the bundle coverage.

## Actual result, without reclassifying warnings as passes

| Final skill result | Count |
| --- | ---: |
| Scanner recommendation SAFE | 100 |
| Scanner recommendation CAUTION | 60 |
| Scanner recommendation DO_NOT_INSTALL | 5 |
| Complete analyses | 114 |
| Partial analyses | 51 |
| Unsuppressed finding records | 593 |

393 component records were inventoried: 390 fully inspected and three partially
inspected. File coverage and analysis completeness differ: unresolved references
can leave an analysis partial even when all bundled bytes were inspected.
The scanner retained 108 missing-reference exceptions, two parser-span limits
and one obfuscated-text limitation. Repository-root references and runtime
output paths can be outside an individual skill bundle; these are not evidence
of a confirmed attack, and are also not grounds to claim complete coverage.

The five DO_NOT_INSTALL results are agent-bootstrap, agent-runtime-integration,
ios-security, growth-conversion-optimization, and session-continuation-protocol.
They remain in the report. Their scores are scanner outputs, not proof of
malicious intent. For example, the growth guide explicitly prohibits the prompt
injection sentence that static pattern P1 flags; iOS security guidance mentions
Keychain and access tokens as secure-storage guidance. Other patterns need full
context rather than a bulk allowlist. In particular, the two unpinned `npx`
fallback warnings and the analysis gaps remain review items.

496 findings are AS3 cross-skill references. Moru intentionally composes reviewed
guidance; a link alone does not prove unauthorized snooping. We preserved these
findings instead of deleting useful cross-links or automatically clearing all
of them. Remaining finding records are marked `review_required`; this report
does not claim that all 593 have received individual security clearance.

### Follow-up review of HIGH findings

[high-findings-review.json](high-findings-review.json) records a bounded manual
context review of all 38 remaining HIGH findings, with source locations, file
hashes, excerpts and reasons. In 33 cases the cited text is a security
prohibition, secure-storage guidance, authorized setup documentation or another
domain-specific instruction; the cited context does not confirm the alleged
vulnerability. Five AE1 findings remain open coverage gaps. Manual reading
does not make the scanner's partial analyses complete.

The original scanner scores, recommendations and 593 finding records are
unchanged. Lower-severity findings have not all been individually reviewed.
The two RP1 unpinned package fallbacks remain open: current managed runtime
instructions mandate a latest-package fallback when the installed tool is
absent. Changing that operating policy requires its own explicit maintenance
scope; this review does not silently replace it with a different policy.

## Corrections and behavior-backed verification

1. The operating skill's ambiguous `never refuse` phrase was replaced with
   execution of safe, authorized, in-scope work while preserving safety refusals,
   permission boundaries and stop conditions. The targeted scan changed from
   score 42 / HIGH maximum issue to 21 / MEDIUM maximum issue; AR1 disappeared.
   Its overall recommendation remains CAUTION.
2. Manual code review found that two optional OpenRouter adapters used urllib's
   default redirect handling. A synthetic request reproduced forwarding of the
   Authorization header to a different HTTPS origin after a 302. No real key,
   provider request or historical breach was involved. Both adapters now share
   a transport restricted to the intended HTTPS origin that rejects redirects,
   including same-origin redirects. Normal HTTPS verification remains enabled.
3. Research preview mode no longer reads API-key files. Explicit live-mode help
   and integration documentation identify what data is sent. Arbitrary free
   text is not represented as automatically anonymized.

The real urllib response-processing chain was tested with synthetic responses
for 301/302/303/307/308, cross-origin, downgrade and same-origin redirects: no
second transport request occurred. Tests also cover rejecting other origins
before transport, normal POST/body/auth handling and no credential reads in
preview mode. Three transport tests, 24 research tests and ten marketing
tests passed without any live LLM calls. All three changed executable outbound
files separately received score 0, SAFE and complete static results.

## Data flow: what stays local, and what can leave

| Surface | Activation | Destination and data |
| --- | --- | --- |
| Wikimap index/search | Local commands | Local document index; update lookup is off by default. Optional update check requests public PyPI package metadata with a version User-Agent. |
| Project memory/mailbox | Local workflows | Local files; reviewed memory code invokes local Git for identity. No HTTP sender was identified in the inspected memory/mailbox owners. |
| Research source triage | Key plus explicit execute mode | OpenRouter and selected inference provider receive query and selected URL/title/text/date. Cache stores digest and validated judgment, not source bodies or credentials. |
| Marketing copy optimization | Key plus explicit live mode | OpenRouter receives selected product-profile fields, bottleneck and numeric claims. A profile may include text derived from the chosen project's README; review it before sending. |
| Figma handoff | Token and explicit integration invocation | Authenticated Figma requests retrieve selected design data; separate public asset downloads use existing URL and redirect checks. |
| Native AI runtime | User's chosen tool and configuration | Claude/Codex/AGY process their supplied context under their own service settings. Local indexing is not a guarantee that the whole AI session is offline. |

This audit did not send source contents to a scanner LLM. Static supply-chain
analysis can query OSV with dependency names and versions even in no-LLM mode.
Package installation and the supplemental npm audit also contact package
registries. Those are distinct from sending prompts or repository contents.

## Moru Web

No tracked skill manifests exist in the pinned Web commit, so SkillSpector skill
coverage is **not applicable**, not a zero-warning web security result. A separate
`npm audit --package-lock-only --ignore-scripts --json` against the immutable
lockfile reported zero known advisories across 118 dependencies. It does not
test auth, access control, SQL policies, PII flows, deployed environment settings,
or the active AGY working tree. That working tree was left untouched.

## Publication boundary

Suitable claim: “We ran pinned SkillSpector static checks on 165 Core skill
bundles, published the remaining warnings and coverage gaps, and repaired a
separately reproduced credential-redirect risk.” Do not claim NVIDIA
certification, a clean whole-product scan, no possible personal-data transfer,
or deployed remediation. The initial corrections and report were committed as
`813a67fe7c9b2211608d11766af54c20728e44c5` and integrated into local main.
That local integration is not evidence of installation or deployment.

Upstream: [NVIDIA/SkillSpector](https://github.com/NVIDIA/SkillSpector).
