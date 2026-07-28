# Agent protocol

This repository uses an architect → implementation → QA feedback loop for every
security-relevant change.

## Roles

- **Orchestrator** owns scope, assignments, the shared status log, feedback routing,
  and the final release gate. It reviews every deliverable and does not mark the gate
  green while a feasible acceptance criterion is failing.
- **Architect** owns acceptance criteria, data flow, threat model, ADRs, public
  interfaces, and review of material deviations. Security properties are expressed as
  testable requirements before implementation.
- **Implementation** owns production code, deployment assets, operational
  documentation, and fixes. It works to accepted interfaces, reports deviations, and
  does not weaken a fail-closed gate to make a test pass.
- **QA** owns synthetic fixtures, unit/API/integration/adversarial tests, independent
  output inspection, reproducible failure reports, and the evidence matrix. QA does not
  use real identifiers or personal data.
- **UI/UX**, when assigned, owns accessible trust copy and interaction quality without
  weakening verified-only release or exposing detected values.

## Required loop

1. Inspect the repository, `ORCHESTRATION_LOG.md`, relevant ADRs, threat model, and
   acceptance criteria before editing.
2. Architect publishes or amends testable acceptance criteria.
3. Implementation produces a bounded pass and identifies every known deviation.
4. QA tests that exact pass and records the command, environment, result, and a minimal
   reproduction for each failure.
5. Orchestrator routes failures and architecture deviations back to implementation.
6. Architect reviews any material design change; implementation fixes the accepted
   design; QA reruns affected tests and the lightweight suite.
7. Repeat until all feasible criteria pass. Environmental blockers must be reproduced,
   scoped, and listed as open—not relabeled as passing.
8. Orchestrator updates the log and final report, then closes the gate.

## Non-negotiable invariants

- Call Centrelink matches **format-valid CRN candidates**; never imply issuance or
  verification by Services Australia.
- Keep processing local. Never log document bytes, OCR text, match values, or
  coordinates.
- The deterministic protected `AU_CENTRELINK_CRN` Presidio recognizer remains primary.
- Render source pages to pixels and build a fresh image-only PDF. Never copy a source
  PDF object graph or text layer.
- Stage output privately. A failed or incomplete verifier result must never be promoted.
- Extensible patterns cannot mutate, shadow, disable, or delete the protected built-in.
- Use clearly synthetic fixtures only.
- Production defaults stay high-assurance. CI uses injected fakes, not weakened
  production behavior.

## Coordination

Shared files are visible immediately. Announce ownership before editing high-conflict
files, preserve unrelated changes, and record each handoff/review/fix in
`ORCHESTRATION_LOG.md`. Architecture owns `docs/architecture.md`, `docs/threat-model.md`,
ADRs, and acceptance criteria. QA owns `tests/` and test evidence. Implementation owns
`src/`, deployment configuration, and the README unless explicitly coordinated.

