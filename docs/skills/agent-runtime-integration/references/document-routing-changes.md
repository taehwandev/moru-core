---
keyflow_id: sys_document_routing_changes
status: review
type: human-reviewed-needed
---

# Document Routing Changes

Read this only when changing how the router selects guidance documents:
routing rules, required/reference tiers, graph edges, concern inference or
selection budgets. Ordinary tasks never load it.

- Select command documents before the budget, and verified owner/action rules
  before generic tiers. An inference cannot displace certain guidance.
- Path rules carry surface-wide contracts; action rules carry procedures for
  the change. Honor `narrows` and `reference_only`; do not retain broader
  keyword or ecosystem matches after resolution without owner evidence or
  explicit `required_priority`.
- Keyword-inferred concerns are references except security, auth, billing,
  credential-broker and migration, which remain required on inference. Record
  why an inferred risk does not apply rather than skipping its card. Release
  guidance is selected by the release/ship command.
- `--concern` is a verified assertion: use an explicit user concern or
  repository-proven owner/action, never infer Compose/navigation from generic
  screen, route or UI wording.
- Follow graph `requires` edges only from selected sources. Inspect
  `required_doc_reasons` to diagnose excess selection; split a
  `platform_default` card that bundles detailed procedures rather than
  dropping the platform contract.
- A guidance split may remove routing-system instructions owned by the router
  and duplicate rules, folding unique clauses into the surviving owner. Move
  every other rule to its applicable sibling. Account for deleted sections and
  check that each surviving rule appears once; do not copy the whole library
  into a target repo.
- Reading-savings claims include conditionally required follow-up reads and
  distinguish selected bytes, observed reads and end-to-end latency. Making an
  applicable document a reference alone does not save its read.
