---
keyflow_id: audit_skillspector_2026_10_26
status: draft
type: ai-generated
---

# Moru skill security inspection — refreshed 26 October 2026

Status: **rescanned; open items remain; not a security certification**.

We reran pinned NVIDIA SkillSpector against current local main after the earlier
credential-redirect and preview-mode fixes. This report preserves the scanner's
results and separates them from a source-bound contextual review. A warning is
an investigation input, not automatically a confirmed vulnerability or a pass.

## Current source and method

| Input | Recorded value |
| --- | --- |
| Scanner | SkillSpector 2.12.0, commit `d7338f58200a9ae2a24810cee08911ab68b107a7` |
| Core baseline | `7df738a5` plus the reference, validation, bootstrap and packet-contract repairs below; full commit in summary.json |
| Scope | All 168 tracked skill bundles, scanned individually with four local processes |
| Mode | `--no-llm --fail-on-findings --fail-on-incomplete`; no suppressions or baseline exclusions |
| Coverage | 112 complete analyses; 56 partial analyses |
| Final scanner results | 652 raw finding records; SAFE 97 / CAUTION 66 / DO_NOT_INSTALL 5 |

All 168 full-scan processes produced reports after the reference repair. A
concurrent main update then strengthened two design-guidance and four business
bundles; those six were rescanned and the 162 unchanged reports retained. Final inventory hashes
bind every scanned bundle to current source bytes. Exit 1 is the
configured outcome for findings or incomplete analysis; it
is not silently treated as a crash or a clean pass.

The original scanner installation and frozen lockfile were reused. Reproduce
the per-bundle scan using the pinned scanner's Python 3.12 environment:

```sh
skillspector scan <SKILL_DIRECTORY> --no-llm --fail-on-findings \
  --fail-on-incomplete --format json --output <REPORT_JSON>
```

[inventory.json](inventory.json) binds final bundle bytes to SHA-256 values.
[summary.json](summary.json) records the baseline, every bundle's coverage and
recommendation, raw artifact hashes and the before/after comparison.
[findings.json](findings.json) retains all 652 unsuppressed scanner findings.
[triage.json](triage.json) binds each contextual disposition to its finding ID,
source location, source hash, excerpt and reason. Local paths in published
artifacts are redacted; original outputs remain in the local evidence folder.

## Why 593 did not mean 593 confirmed bugs

The previous snapshot covered 165 skills with 593 findings. Current main adds
three skill bundles and five cross-skill-reference detections, producing 598
findings before the wording repair. That repair removed one AR1 finding,
leaving 597 raw records at that stage. Independent Claude review then found
broken references and a checker blind spot. Repairing obsolete spellings to
explicit current skill paths added 53 reference-pattern detections, yielding
650 raw records in the full scan. The concurrent design-guidance update then
added two scanner-coverage warnings, giving **652 final raw records**. This is a pattern-match count,
not an unresolved-defect count or evidence that remediation added vulnerabilities.

| Contextual disposition | Finding records | Evidence and boundary |
| --- | ---: | --- |
| Expected internal skill references | 506 | Each literal written path resolves from its referring file or documented repository root; source and target hashes and literal spellings are recorded. Filename-suffix matching is rejected. Resolution is not whole-skill security clearance. |
| External source citations | 48 | Reviewed provenance maps identify repositories and pinned snapshots. No remote skill was fetched, installed or cleared by this review. |
| Other reviewed context | 89 | Secure-storage guidance, prohibitions, quoted attack examples and scoped task rules do not confirm the alleged vulnerability in the cited context. Original scanner severities remain. |
| Unpinned fallback execution | 2 | Open supply-chain risk: missing-binary `npx` fallback is not version-pinned. |
| Scanner coverage-gap findings | 7 | Open deterministic parser/reconstruction limitations across four document surfaces; manual reading does not repair scanner coverage. |

The first three categories total **643 context-reviewed records**. The last
two total **9 warning records about policy or coverage**. These are
review dispositions, not suppressed warnings, 643 fixed bugs or safety
certification. Scanner coverage also remains partial for **56 skills**; those
bundle-level gaps are separate from the seven emitted coverage-gap findings.
The nine records are not nine unique vulnerabilities: two concern one
unpinned-fallback policy at two instruction locations, and seven describe
analysis limits across four documents.

## Additional repair and verification

Independent Claude review found 51 broken relative references in 19 guidance
files, and a validation gap: the checker ignored backtick paths beginning
with `../`. The intermediate triage also incorrectly marked 32 of those
records as resolved because only the filename suffix matched an existing
skill. That classification was invalid and is replaced in the current report.

Claude supplied a concrete patch, which the parent applied and verified. The
51 relative references and another 34 obsolete bare skill names in the owned
files now point to current documents. The checker validates relative paths,
removed-document references and the product-pattern root. Two new tests failed
against the old checker, then passed after repair; the additional product-root
negative control also failed before its repair. **31 reference-checker tests
pass**. An independent literal resolver finds zero unresolved `../` code
references in its scanned scope. Every current internal-reference disposition
also includes the literal source spelling; suffix-only records fail validation.

Bootstrap fallback guidance now uses the mandated `@latest` form only when
the installed binary is missing. The broader "or latest-package fallback"
wording is removed. This aligns the existing policy and narrows invocation;
it does not pin the package, so both RP1 risk records remain.

The continuation contract said later hooks “never refuse,” while describing
legacy evidence-path compatibility. That wording could be mistaken for
disabling authority or safety checks. It now states precisely that a missing
legacy packet alone does not reject an already-started run, while authority,
safety, evidence and gate checks still apply.

The targeted rescan removed AR1. The bundle's recommendation changed from
DO_NOT_INSTALL to CAUTION, retaining its other findings and partial coverage.
No useful cross-skill links or security prohibitions were deleted for a score.

The earlier authenticated-request redirect rejection and research preview
credential-read fixes remain in the scanned baseline. Their relevant suites
were rerun: transport 3, research 24, marketing 10, Figma API 8, Figma secret
boundary 4 and document-surface checks 72: **121 tests passed**. No live model
or Figma calls were made for these tests. The prior HIGH-only review in
[high-findings-review.json](high-findings-review.json) is historical evidence
for the preceding snapshot; the current all-finding review is triage.json.

## What remains open

- Two unpinned fallback findings remain. Current managed runtime instructions
  require a latest-package fallback when the installed tool is absent. This
  review does not silently rewrite that operating policy or claim pinning.
- Four document surfaces produce seven scanner-gap warnings: verification
  policy, Swift design-system and UI-visual-verification parser limits, plus
  runtime-write-isolation reconstruction limits. They require compatible coverage or an
  independently justified alternative check before being called complete.
  Local diagnostics traced the triggers to a shell-log example, Swift prose
  containing an apostrophe, and the deletion-command explanation. The source
  is not encoded text; diagnosing the heuristic does not make coverage complete.
- Most other partial analyses concern references outside an individual skill
  bundle or runtime-generated paths. Their coverage status is retained.

## Data flow and publication limits

No external scanner LLM was used. Static dependency checks can query OSV using
package coordinates. Existing local Wikimap/CodeGraph lookup is distinct from
optional OpenRouter/Figma adapters and the user's native AI provider: those
providers can receive explicitly supplied task data under their own settings.
The earlier report's disclosure and authenticated HTTP fixes remain relevant.

This is a dated Core source inspection, not NVIDIA certification, endorsement,
a continuously running scanner, deployed remediation or a Web penetration
test. The earlier Web lockfile check was against historical `c677d02`; it is
not repeated here or presented as current application security evidence.
Claude used the existing local CLI for independent review and patch authoring;
the scanner itself still made no LLM calls.

Upstream: [NVIDIA/SkillSpector](https://github.com/NVIDIA/SkillSpector).
