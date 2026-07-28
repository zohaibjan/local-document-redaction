# Secure MVP acceptance criteria

Status: architecture gate v1, 2026-07-28

These criteria are normative. A test may be skipped only for a documented
environmental reason; a skip must not silently weaken a production security
default. The final gate is fail-closed: an unverifiable output is not released.

## AC-01: Input boundary

- The application accepts PDF, DOCX, JPEG/JPG, PNG, and TIFF only.
- Detection is based on bytes/content, not a client MIME header or filename.
  A misleading extension, unsupported type, malformed file, and unsupported
  encrypted/password-protected file are rejected.
- Configured byte, page, frame, archive-entry, decompression, and total-pixel
  limits are checked as early as possible and again after decoding.
- User filenames are display-only after normalization and are never joined to a
  filesystem path.
- DOCX is treated as an untrusted ZIP container. Macro-enabled/active content,
  traversal entries, links to external resources, and archive bombs are rejected
  before a bounded headless LibreOffice conversion.

## AC-02: Privacy and lifecycle

- Document bytes, OCR text, matched text, and detection coordinates are never
  sent to a remote service.
- Those values are not logged or placed in user-facing exception details.
- Each job uses an unpredictable, private temporary directory. Files are removed
  on success, failure, timeout, and cancellation as far as the operating system
  permits.
- Processing has bounded concurrency and stage timeouts. Output downloads are
  scoped to an unguessable job capability and expire.
- The UI and README state that processing is local by default and automated PII
  detection is not guaranteed.

## AC-03: OCR contract

- The production OCR adapter explicitly selects PP-OCRv5 and returns, per token,
  page number, normalized text, polygon/axis-aligned box, confidence, and reading
  order.
- Orientation/rotation handling is enabled and documented.
- A deterministic fake OCR adapter permits CI and most integration tests to run
  without downloading OCR or GLiNER models.

## AC-04: CRN detection semantics

- A protected built-in Presidio recognizer named `AU_CENTRELINK_CRN` is the
  primary CRN detector.
- All product copy calls detections **format-valid CRN candidates**. It never
  says a candidate was issued by or verified with Services Australia.
- It recognizes synthetic nine-digit-plus-letter forms with common OCR spacing,
  including `123 456 789A` and `123456789A`, and reconstructs bounded splits
  across tokens and reasonable line boundaries.
- Normalization never broadens the pattern beyond nine digits followed by one
  ASCII letter. Context and confidence thresholds control false positives.
- Each character span maps back to every contributing OCR token. Redaction covers
  the union of all contributing boxes, not just the token containing the final
  letter.
- Optional local GLiNER integration is mediated through Presidio, is disabled or
  absent without changing built-in behavior, and is not the primary CRN detector.

## AC-05: Pixel redaction

- Every detection box is expanded by configured padding, clamped to the page,
  unioned as needed, and painted with fully opaque black pixels.
- No original pixels beneath a redaction rectangle survive in an output image.
- Multi-box and multi-line candidates redact every source box.

## AC-06: Irreversible PDF construction

- Each PDF page is rasterized at configured high DPI before redaction.
- The output is a newly constructed, image-only PDF.
- No source text layer, annotation, form, attachment, link, JavaScript, metadata,
  optional-content group/hidden layer, object history, or incremental update is
  copied.
- DOCX enters this same pipeline after conversion. It never becomes a sanitized
  DOCX output.

## AC-07: Output verification gate

- Before release, output PDF text extraction does not contain any normalized
  target candidate.
- The PDF contains page image content only and no annotations, forms, embedded
  files, JavaScript/actions, or copied sensitive metadata.
- In the high-assurance profile, re-OCR of rendered output must not rediscover a
  target candidate. Re-OCR can be configurable for constrained development, but
  production defaults and the resulting assurance level are explicit.
- Any verification exception, timeout, or failed assertion suppresses download
  and removes or quarantines the output. The caller receives a generic failure.

## AC-08: Extensible patterns

- User patterns have a stable schema: identifier, name, regex, context terms,
  confidence, enabled flag, and output label.
- Identifier/name/label lengths, pattern length/count, context count/length, and
  confidence range are bounded. Unknown schema keys are rejected.
- Compile-time validation and bounded evaluation prevent catastrophic regex
  behavior. Unsupported/unsafe constructs are rejected.
- User patterns cannot delete, disable, shadow, or mutate the built-in
  `AU_CENTRELINK_CRN` recognizer.

## AC-09: API and UI

- The accessible workflow is upload, process/review a count-only summary where
  practical, confirm redaction, and download verified output.
- The UI lists supported formats and effective limits and shows privacy and
  detection-limit warnings.
- Errors are generic and do not echo document content, regex match contents, temp
  paths, or internal stack traces.
- Job and download access cannot be enumerated or used to access another job.

## AC-10: Automated evidence

- Unit, API, and integration tests use only clearly synthetic examples.
- Coverage includes spaced/unspaced candidates, punctuation and OCR token splits,
  reasonable line splits, context-positive and false-positive cases, rotated or
  scanned fixtures where feasible, invalid/unsafe regex, spoofed MIME, malformed
  and oversized input, excessive decompression/pixels, cleanup, padding, and
  multi-box redaction.
- An adversarial PDF fixture includes source text, metadata, annotation and/or
  attachment. Verification proves the output target is absent and forbidden
  structures were not copied.
- Failure-path tests prove an output is not returned when verification fails.

## AC-11: Deployment and dependency control

- The application has a non-root container deployment, bounded worker
  configuration, and a health check.
- Dependencies are pinned or otherwise controlled and model versions are
  explicitly configured.
- LibreOffice, PDF rasterization, PP-OCRv5 model download/storage, and optional
  GLiNER requirements are documented.
- CI runs the lightweight suite without large model downloads.

## AC-12: Delivery evidence

- Repository includes README, architecture and ADRs, threat model, `AGENTS.md`,
  pattern examples, orchestration status log, tests, container configuration, CI,
  and a final report.
- All feasible criteria are green. Remaining risks and reproducible environmental
  blockers are listed; no skipped gate is represented as passing.
