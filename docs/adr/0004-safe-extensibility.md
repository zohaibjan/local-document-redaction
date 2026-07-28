# ADR 0004: Constrain user-defined recognizers

- Status: accepted
- Date: 2026-07-28

## Context

Regex patterns provide useful local extensibility but can cause denial of service,
false assurance, accidental disclosure in errors, or shadow mandatory behavior.

## Decision

Accept strict, bounded pattern specifications. Reserve the built-in CRN identifier
and entity type. Use a linear-time regex engine or a conservative pattern subset;
otherwise isolate evaluation behind a real deadline and bounded input. Do not log
patterns, inputs or matches. Invalid patterns are rejected before jobs run.

## Consequences

- Some advanced regex syntax is unavailable.
- User patterns can affect what is redacted but cannot mutate the protected
  recognizer.
- Runtime limits are part of the public configuration contract.
