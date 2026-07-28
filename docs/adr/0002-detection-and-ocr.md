# ADR 0002: Deterministic CRN detection is primary

- Status: accepted
- Date: 2026-07-28

## Context

The required CRN shape is stable and deterministic, while OCR fragments can split
the value. A general semantic model adds latency and variability and cannot prove
issuance.

## Decision

Use PP-OCRv5 explicitly for production OCR and Microsoft Presidio as the analysis
framework. Register an immutable custom `AU_CENTRELINK_CRN` recognizer as the
primary detector. Assemble a bounded normalized analysis string with
character-to-token provenance, then map every matched span back to all source
boxes.

GLiNER is an optional, local Presidio recognizer for other semantic PII. Its
absence or failure cannot disable or weaken built-in CRN detection. CI uses an
injectable deterministic OCR fake.

## Consequences

- Detection behavior is testable and explainable.
- Context/confidence tuning is needed to limit false positives.
- OCR quality is still a material source of false negatives.
- The product must consistently say “format-valid CRN candidate,” not “valid” or
  “verified CRN.”
