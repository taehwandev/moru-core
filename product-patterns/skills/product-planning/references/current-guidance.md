---
keyflow_id: sys_product_planning
status: review
type: ai-generated
moru_card_contract: strict
---

# Product Planning

## Use When

Turn a rough idea or customer problem into a product proposal and requirements
handoff. Do not redo discovery for an accepted specification or replace
`workflows/skills/prd-creation/SKILL.md` with a second PRD owner.

## Inspect First

Read the current request, existing product brief and available user evidence.
Identify the intended audience, current workaround, desired outcome, constraints
and known product capabilities. Missing evidence stays unknown; one request is
not proof of broad customer demand. Keep company strategy and budgets local.

## Decision Rule

1. Separate observed problems, user requirements, assumptions and open decisions.
   Ask only about missing information that changes scope, risk or acceptance;
   continue useful drafting with explicit reversible assumptions elsewhere.
2. Write a concise proposal: problem, intended user, outcome, candidate solution,
   alternatives including the current approach, first scope, exclusions and risks.
   One request supports that requester's problem, not a population-wide claim.
   Inferred users, conflict rules and feature behavior remain proposed assumptions
   until the owner accepts them; do not hide policy in an acceptance candidate.
3. Give requirements stable local IDs when later work needs traceability. Define
   observable acceptance candidates and name unknown policies without choosing
   permissions, billing, retention or other consequential defaults silently.
   For permissions, preserve the stated subject, action and resource: allowing
   one role to view does not authorize every signed-in user to view. Leave
   unstated roles/actions unknown. A later decision resolves only its stated
   scope; do not rewrite an earlier unknown as an implicitly accepted policy.
4. Propose the smallest useful validation: evidence to collect, outcome to observe
   and the decision it would inform. Label forecasts and targets as such.
5. Hand off the proposal, evidence and unresolved decisions to the existing PRD
   workflow. Reuse its accepted scope and downstream design/test ownership;
   this note does not authorize implementation, publication or spending.

## Output

Produce a proposal brief with evidence/assumptions, proposed scope, requirement
candidates, acceptance candidates, open decisions and next owner. For a simple
answer keep it short; for a downstream artifact use the shared artifact-handoff
contract. Do not fabricate estimates merely to fill a template.

## Common Rationalizations

- "A convincing proposal needs market numbers." Omit unsupported numbers or
  state the research question; do not invent a market or interview results.
- "Every unknown needs an approval." Reuse settled decisions and authority;
  ask only about material unresolved decisions.

## Red Flags

Proposed features appear as shipped capabilities; assumptions become evidence;
requirements change meaning while keeping an apparently unchanged version.

## Do Not

Do not invent customer research, demand, competitor facts or committed delivery
dates. Do not treat a model response as customer validation or silently broaden
an already accepted requirement.

## Stop If

A final recommendation depends on unavailable evidence or an unresolved material
policy decision. Deliver the bounded draft and mark that recommendation blocked.

## Verification

Trace each factual claim to its source and each requirement to the request or
an explicit proposal. Check that acceptance candidates describe observable
outcomes, open decisions are visible and the PRD owner receives the same version.
For a material revision, check only the affected downstream scope for staleness.
Apply the shared artifact-handoff verification to the actual revised content
before handing it on; a list of future fixes is not a corrected deliverable.

## Report

Name the proposal/version, evidence, assumptions, unresolved decisions, validation
needed and PRD handoff. Distinguish a prepared plan from validated demand or code.

## Sources

- [GOV.UK user needs](https://www.gov.uk/service-manual/user-research/start-by-learning-user-needs):
  evidence-supported problems and outcomes; suggestions remain assumptions.
- [Atlassian PRDs](https://www.atlassian.com/agile/product-management/requirements):
  product purpose, requirements and success criteria. Consulted 2026-10-26.
