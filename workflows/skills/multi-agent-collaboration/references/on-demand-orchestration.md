---
keyflow_id: sys_on_demand_orchestration
status: stable
type: ai-generated
---

# On-Demand Orchestration

Use when choosing whether exploration, implementation, challenge, or closeout
needs a separate agent. One lead owns requirements, decisions, integration, and
the final report. Keep work completable with the currently available runtime.

## Roles And Reasons

A persona defines its purpose, trigger, allowed scope, output, and stop condition.
The lead may perform every role in the same session. A role name grants no tools
or authority and is never assigned permanently to one provider or model.

| Role | Trigger | Allowed scope and output | Stop condition |
| --- | --- | --- | --- |
| Explorer | A source, behavior, or current fact blocks a named decision | Read bounded sources; return the answer, exact evidence, and remaining uncertainty | Enough evidence answers the question or a concrete access limit is established |
| Builder | Scope and acceptance checks are clear | Change only owned paths; return changed paths, checks, and blockers | The bounded result is verified or a new decision returns to the lead |
| Challenger | A consequential assumption needs a counterexample | Inspect requirements and the exact change; return reproducible failure conditions and impact; no edits | The named risk is assessed with evidence or remains explicitly unresolved |
| Closer | Work is ready for a completion claim | Compare the original request, final result, and valid evidence; return gaps and residual uncertainty; no publication | Every requirement has evidence or an explicit unmet outcome |

Combine challenge and closeout for small changes. Separate challenge only when
the risk or decision benefits from another perspective. Existing explorer,
worker, and reviewer roles can perform these jobs; no new agent installation
is needed merely to name a persona.

## Choose Execution

1. Use same-session role changes for bounded exploration and ordinary closeout.
2. Use a native worker when isolating substantial search output or running
   independent work improves the result enough to cover startup, context,
   token, waiting, and integration cost. Parallel work retains the contract and
   ownership rules in [the collaboration reference](current-guidance.md).
3. Use another runtime only for a needed review perspective or confirmed tool
   access, through an available execution and result-return path. Another
   product does not by itself prove a different model or independent evidence.
4. Start with at most two helpers. Add a third only for a distinct benefit.
   Do not launch helpers merely because a phase, role, or provider exists.
5. Keep helpers one-shot and bounded: reuse one valid `handoff` capsule across
   same-wave workers, stay within `<= 4` handoffs per run, close helper threads
   once their slice returns, and avoid persistent message/wait polling loops or
   unrequested external runtime consultations inside multi-slice goal runs.

The brief names the question or risk, the decision its answer may change,
owned/read-only and forbidden scope, relevant evidence, acceptance checks,
expected output, and stop condition. Pass the necessary instructions and
required-doc takeaways through the existing valid handoff; keep raw search
results and logs in the worker context. With a valid handoff brief, workers do
not re-read `AGENTS.md`, `SKILL.md`, `preflight.json`, or `required_docs`. For
CLI helper invocations (`codex exec -o <result> ... > <log> 2>&1` or redirected
`claude -p`), spool intermediate `stdout`/`stderr` to run-local files and return
only the bounded `worker_result_v1` summary (`<= 4096` bytes, preserving
`blockers` and spilling long details to a local artifact). The lead integrates
bounded findings.

## Multi-Perspective Deliberation

Use when helpers are asked for ideas, framings, or judgments rather than one
verifiable answer. The goal is a map of distinct options, not the most
confident voice's conclusion.

1. **Blind first round.** Give every helper the same neutral brief: confirmed
   facts, available evidence with its limits, constraints, and open questions.
   Leave out the lead's draft, other helpers' output, and any role or wording
   that presupposes a conclusion. The lead records its own position before
   reading theirs.
2. **Ask for divergence.** Request a premise challenge and two or three
   directions that differ in framing or mental model, not variants of one idea.
   Each direction states its audience, evidence status (present, partial,
   missing and which check would supply it), misuse risk, and the strongest
   argument against it.
3. **Anonymous cross round.** Give each helper the other directions without
   names. Ask it to steelman the strongest opposing direction, say what it
   would adopt or reject and on what evidence, and name the disagreement that
   remains. Do not ask helpers to converge.
4. **Weigh evidence, not force.** Do not rank directions by confidence,
   length, repetition, or how many helpers echoed them. Keep a direction backed
   by one helper when its evidence holds; drop a popular one when its evidence
   does not. Note where a helper only restated the brief.
5. **Report an option map.** Shared ground, real disagreements with the
   evidence or decision that would settle each, and the choices left to the
   user. Give a single recommendation only when asked, labeled as the lead's
   view and separate from the map.

Helpers from the same model family, or shown the same draft, are not
independent; say so when reporting. Stop when the options and the remaining
disagreements are mapped.

## Existing Access And Failures

Check a provider only when its help is needed; do not inventory every product
at startup. Never assume installation, authentication, subscription, quota,
tools, or permission. Unknown access remains unknown. Classify an observed
failure as unavailable tool, authentication, quota, permission/policy, or
transient execution/network failure; do not infer a missing subscription from
a generic failure or a sandbox-restricted credential lookup.

An established unavailable state stops equivalent calls during that task until
the condition changes. Retry a transient read once only after the prior call
has ended and the failure is understood; retain pending handles without
duplicate launches. Continue with available tools and same-session work when
they can satisfy acceptance. Never install, log in, upgrade, enable billing,
switch to paid APIs, or create recurring calls automatically.

## Closeout And Verification

Reuse checks only while their covered inputs and freshness remain valid. Add
the missing behavior evidence appropriate to the change, such as reproduction,
tests, measurements, or actual UI verification. Keep same-session self-review,
a separately executed review, and direct execution evidence distinct.

Unavailable optional review does not block an otherwise evidenced result. A
required independent review or acceptance check remains unmet until satisfied;
self-review cannot waive it. Report that limit and the unresolved requirement.
Preserve the route's required gates, authority, and publication boundaries.

For initial evaluation, note useful findings and rework avoided when observable.
Use time or usage only when already available; no extra telemetry or model
calls are needed to measure the policy.
