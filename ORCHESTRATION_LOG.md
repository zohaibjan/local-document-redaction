# Orchestration Log

This file records the architect → implementation → QA feedback loop for the secure MVP.

## Repository orientation

- 2026-07-28: Connected GitHub repository `zohaibjan/Doc_redact` confirmed private, empty, default branch `main`, with admin/push permission.
- 2026-07-28: Local directory confirmed empty except task work/output directories; initialized a local `main` Git repository and configured the specified HTTPS origin.
- 2026-07-28: System Git is unavailable because Apple developer tools are not installed. The bundled Git runtime is used locally. Prior task context reports HTTPS/SSH terminal authentication unavailable; publication will prefer the connected GitHub app.
- 2026-07-28: Connected-app publication was attempted after the final green gate. The first remote write was rejected before changing the repository because the platform's automatic approval review could not run after the account reached its Codex usage limit. The private repository therefore remains empty; the validated local tree is preserved for publication when the allowance is restored.

## Agent loop

| Pass | Owner | Deliverable / review | Status |
|---|---|---|---|
| 1 | Architect | Published AC1–AC12, data flow, threat model T01–T20, ADRs, interfaces, and phased plan | Accepted |
| 1 | Implementation | Delivered the first modular FastAPI/OCR/Presidio/raster-PDF/verifier pass plus deployment and documentation scaffolding | Returned for review |
| 1 | Architect + orchestrator | Found split-token line handling, Presidio bypass, swallowed regex timeout, invalid OCR geometry, pre-verification output placement, incomplete PDF denylist, inconsistent re-OCR normalization, and wrong PDF physical sizing | Returned to implementation |
| 2 | Implementation | Fixed the architecture deviations; added strict ingest, private staging, detector-consistent verification, protected patterns, API/UI, Docker/Compose, CI, README, `AGENTS.md`, and draft final report | Returned to QA/UI |
| 2 | QA | Reproduced Pillow decompression exception leakage | Fixed; batch rerun 53 passed |
| 3 | QA | Reproduced indeterminate-verifier publication, client-visible sensitive error details, and missing upload label | Fixed; batch rerun 79 passed |
| 3 | UI/UX | Published UI-AC1–10 and integrated polished local-only upload, progress, verified result/preview, patterns, accessibility, responsive layout, and safe errors | Returned for browser/orchestrator review |
| 4 | QA | Reproduced effective pattern-length bypass | Fixed before store mutation |
| 4 | Orchestrator browser/UI review | Desktop and 320 px layout, focus, no overflow, custom-pattern flow, verified-only synthetic upload/download/preview, and safe malformed-input error | Passed; neutral target/page summary and cross-site protection findings returned |
| 4 | UI/UX + implementation | Added neutral target/page summary, Origin/Fetch-Metadata rejection, protected pattern UI, and packaged local assets | Fixed; UI gate passed |
| 5 | Orchestrator | Found loopback DNS-rebinding exposure through arbitrary matching `Host` | Fixed with loopback `TrustedHostMiddleware` and attacker-host regression |
| 6 | Architect final code challenge | Reproduced malformed Paddle payload fail-open, pre-parser multipart resource exposure, inherited LibreOffice `TMPDIR`, and unproven shared predictor thread safety | Returned to implementation |
| 6 | Implementation | Enforced Paddle result schema and serialized inference; bounded `/redact` before multipart using the shared two-job slot and queue/receive deadline; isolated converter `TMPDIR` | Fixed with focused regressions |
| 6 | QA + architect + orchestrator | Independent full lightweight/adversarial reruns, AC reconciliation, Poppler/pypdf/PyMuPDF inspection, browser smoke, and wheel-content inspection | 110 passed, 0 failed/skipped, 88% coverage; no executed-gate blocker |

## Acceptance gate

Final local status: **GREEN** — all feasible lightweight, API, adversarial PDF,
browser, and packaging gates passed. Real PP-OCRv5/GLiNER inference, native DOCX
conversion, Docker runtime, and hosted GitHub Actions remain environment-unexecuted
and are explicitly documented; they are not represented as passing.

Repository publication status: **BLOCKED BEFORE REMOTE MUTATION** by the platform
approval/usage gate. The next action is to publish the validated source tree to `main`
through the connected GitHub app after the allowance is restored, then run hosted CI.
