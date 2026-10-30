---
keyflow_id: sys_web_3d_guidance_review
status: review
type: ai-generated
---

# Interactive Web 3D Guidance And First-Delivery Evaluation

## Scope And Acceptance

Improve applicable skill selection and useful 3D/option-UI guidance. Do not
claim token savings, prescribe an engine or module count, constrain creative
ambition, or modify historical generated applications. The current user selected
first delivery only: one initial product request per condition, not a second
evaluator-directed repair round. Both conditions retain the same natural-language
request and free implementation choices.

This is a bounded shared-guidance/routing slice, not a new product or runtime.
The existing action-rule schema and required-document contract are retained.
Acceptance: the original English 3D-webpage request and supported Korean/engine
requests select the new skill and UI quality companion before implementation;
unrelated tasks and explicit exclusions do not. Provider critique and observed
reading must be reported separately from demonstrated output improvement.

## Responsibilities And Read Timing

- Production owner: `platforms/web/skills/web-3d-interaction/SKILL.md`.
- Quality companion: `common/skills/ui-visual-verification/SKILL.md`.
- Selection owner: `workflow-doc-surfaces.json`, using existing scoped action
  rules, not blanket startup reads or a new concern/risk gate.
- Request/exclusion semantics owner: `scripts/workflow_doc_surfaces.py`.
- Focused regressions: `tests/test_workflow_web_3d_routing.py` and the existing
  document-surface and required-selection suites.

Read the production skill before scene/camera/option design and the quality
companion before styling controls. Use the companion's content-to-edge padding
and overlap sections at verification. Reuse unchanged readings already present
in the active context. Selection alone is not observed reading or application.

The existing `minimal-visual-design` skill explicitly stops for bold/maximal or
brand-expressive direction. Do not force its quiet palette/restraint onto an
expressive 3D experience merely to make a quality skill appear in a read log.
The routed UI quality companion covers legibility, spacing, input and actual
rendered verification without choosing the artistic style.

The action parser preserves dotted identifiers such as `Three.js` within a
clause. Previously splitting every dot prevented a specific 3D request from
matching its engine and scene subject together. Exclusion parsing uses the same
boundary so a prohibited dotted subject does not become an affirmative match.
Korean patterns account for the existing Latin/Hangul normalization.

## Review And Disposition

Both reviewers received the proposed skill and the scope, in read-only mode.
They did not edit a benchmark artifact or test the final router themselves.

| Review | Useful finding | Applied decision |
| --- | --- | --- |
| Claude Code | Separate evaluator protocol from generator guidance | Move comparison/read-evidence rules here; keep the skill about making/verifying the experience |
| Claude Code | Make framing and control failures observable | Check usable canvas, default/intermediate/final views, long labels and narrow touch layout |
| Claude Code | Avoid treating routing as reading or quality proof | Use separate manifest, tool-read, artifact and effect evidence |
| OpenRouter / DeepSeek V3.2 | Reserve control space before camera framing | Specify a panel budget, discoverable scrolling/reflow and an inspectable subject |
| OpenRouter / DeepSeek V3.2 | Keep creative ambition; make the initial subject readable | Retain style freedom and default-state inspection without prescribing a subject or palette |
| Both | Remove generic read/reuse/evaluation overhead from the skill body | Retain that policy at the orchestration/evaluation boundary |

The native responses and request are retained locally with the task evidence.
OpenRouter's review is advice, not certification or proof of improved output.

## First-Generation Code Separation: Preserved Flash Pair

App scope is `src/**` plus `index.html`; dependencies, built bundles, Git
metadata, configuration and docs are outside these file counts. Only the first
artifact from each current pilot lane is compared here.

| Responsibility | Moru bridge ON | Moru OFF |
| --- | --- | --- |
| App files | 9: seven JS modules, CSS, HTML | 12: ten JS modules, CSS, HTML |
| Composition root | `src/main.js` | `src/main.js` |
| Scene/environment | `src/scene.js`: camera, pad, lighting/environment | Separate environment, assembly-pad and camera-helper modules |
| Model/materials | `src/spaceship.js`, 725 lines, includes themes and geometry | Builder, 898 lines, plus shared materials module |
| UI | `src/ui.js`, 350 lines | `src/ui/uiController.js`, 629 lines, including multiple part variants |
| Motion/effects/audio | Separate flight, particle and audio modules | Separate flight, particle and audio modules |

Both implementations chose modular code without a forced file-count prompt.
OFF separates several scene responsibilities more finely. Both retain large
model-construction owners; the larger OFF builder also provides additional
variants. File count and line count alone do not rank maintainability or visual
quality. Both flight controllers manipulate the camera, so a separate camera
filename alone does not establish exclusive camera ownership.

The first OFF artifact's variant-click handler uses `THREE.Vector3` without a
module import, reproduced as `THREE is not defined`. Its public auto-assembly
path still renders and flies. ON's manual attach path works, while its default
flight and alternate chase captures lose the visible ship in the software
browser environment. These are distinct observable behaviors, not a source
similarity score. Neither justifies declaring ON generally better.

The first ON mobile option cards are visibly compressed/clipped despite
reachable controls; OFF's first mobile snapshot has 36px body overflow and a
crowded header. A click succeeding does not establish a finished option UI.
Historical second artifacts remain evidence only and are not first-pass scores.

## First-Delivery Evaluation Contract

Freeze the task, permissions, model/profile, tooling, resource limits and
scenarios before dispatch. Preserve all setup failures separately. One initial
user request may include the model's own design, checks and corrections before
its first final delivery; count and time that entire request. Do not forbid
normal self-verification only in one condition. After delivery, the evaluator
only observes: no defect-feedback prompt, source repair or replacement artifact.

Keep these outcome dimensions separate, with no invented composite score:

1. Requested behavior: meaningful assembly/state changes, valid enabled/disabled
   actions, coherent motion and camera/input behavior, runtime errors.
2. Option UI finish: understandable labels and selection, observed effect of
   every promised choice, consistent alignment/padding, no clipped text or
   overlapping controls, long-option handling, visible focus and reachable
   controls on desktop and narrow touch layouts. Body overflow is measured
   separately from intentional scrolling within a panel.
3. Visible craft: readable focal subject, intentional composition/light/material
   contrast, satisfying meaningful motion and effects that preserve visibility.
   A deliberately quiet scene and a bold scene are both valid when requested.
4. Structure: responsibility boundaries, dependency correctness, state ownership
   and coupling; no reward for more files or an arbitrary line count.
5. Effort: initial-request wall time, native usage and interruptions. Cache reads
   and account usage percentages are not a dollar-cost calculation.

Capture equal viewports and relevant initial, intermediate, final and selected
states. Preserve render engine/browser differences and missing observations.
Do not let correct code or a counter compensate for an unusable option panel.
Human craft ratings require a declared rubric and independent assessment;
observer screenshots alone are not a measured aesthetic improvement.

## Evidence Levels And Current Limits

| Level | Appropriate evidence | Insufficient substitute |
| --- | --- | --- |
| Selected | Required-document manifest for the actual request | Skill file exists |
| Read | Successful file-read tool events, path/content scope and ordering | Manifest membership or agent assertion |
| Applied | Output behavior and rendered option/scene observations | A read receipt or build success |
| Improved | Matched first-delivery comparisons with declared coverage | One successful read or one favorable screenshot |

A Claude read-only planning smoke received the router-selected paths and
successfully read both complete skill entrypoints through two native `Read`
calls before returning its plan (no offsets or limits requested). That is a bounded
read-path check, not an automatic AGY generation experiment. AGY's next real
first-delivery run must separately record selected/read/applied evidence before
claiming this guidance improved its result. No new generation cohort is implied
by this shared-guidance change.

The generic skill-creator validator was unavailable in the default interpreter
because PyYAML is absent. Moru's own workflow/frontmatter/link validator is the
canonical format check for its extended skill metadata. Two document-byte-budget
assertions in the broader required-selection suite also fail unchanged on clean
main (cleanup 12,192 vs 10,000; PRD 16,024 vs 16,000). They are baseline findings,
not effects of this 3D selection change; do not loosen their limits here.
