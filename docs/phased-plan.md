# Phased implementation plan

## Phase 0: Security skeleton

- Establish settings and immutable server limits.
- Define DTOs/protocols and content-free logging.
- Implement private job lifecycle and fake OCR/test fixtures.
- Gate: malformed/spoofed/oversized uploads fail generically and clean up.

## Phase 1: Deterministic vertical slice

- Canonicalize image inputs.
- Normalize OCR tokens with character provenance.
- Add protected Presidio CRN recognition, multi-box mapping and pixel painting.
- Build a new image-only PDF and run structural/text verification.
- Gate: synthetic image and adversarial synthetic PDF tests meet AC-03 through
  AC-07.

## Phase 2: Full input surface

- Add bounded PDF rasterization, TIFF frame handling and secure DOCX preflight plus
  isolated LibreOffice conversion.
- Add rotation and page/pixel/resource controls.
- Gate: exact supported formats pass and hostile fixtures fail safely.

## Phase 3: Extensibility and optional semantics

- Add strict pattern configuration/API/UI with bounded evaluation.
- Add optional local GLiNER-through-Presidio adapter.
- Gate: unsafe patterns cannot exhaust the worker or affect built-in behavior;
  GLiNER absence does not change CRN tests.

## Phase 4: Product and operations hardening

- Complete accessible UI, output TTL/reaping, headers, deployment, health checks,
  dependency control and lightweight CI.
- Run failure injection, adversarial PDF, log-capture, cleanup and concurrency
  tests.
- Gate: all feasible acceptance criteria pass and residual risks are documented.

## Release gate

The orchestrator reconciles tests to `docs/acceptance-criteria.md`. QA records a
reproducible pass/fail/blocked result per criterion. Architect reviews material
deviations; implementation fixes them; QA reruns affected and regression suites.
No output-safety deviation is accepted as a warning-only issue.
