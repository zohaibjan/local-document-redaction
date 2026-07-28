# ADR 0003: Gate every download on independent verification

- Status: accepted
- Date: 2026-07-28

## Context

Pipeline success does not prove safe output. Libraries can retain structures,
builders can regress, and exceptions can create partially written files.

## Decision

Build into a non-downloadable staging path. Independently verify normalized
target text absence and an image-only structural allowlist; use re-OCR in the
high-assurance profile. Atomically create a download capability only after all
required checks pass.

An exception, timeout, unavailable mandatory verifier, unexpected structure or
indeterminate result is failure. Failed output is not returned.

## Consequences

- Verification latency is part of processing time.
- Tests can inject verifier failures and prove suppression.
- Development may define a lower-cost profile, but it must be visibly labelled
  and production must not silently downgrade.
