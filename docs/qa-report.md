# Final QA report

Date: 2026-07-28  
Gate: **PASS for the lightweight/local-fake MVP suite, with the explicitly
unexecuted heavyweight and container checks below**

All automated fixtures use synthetic-only identifiers and documents.

## Automated result

Command:

```bash
.venv/bin/pytest --cov=doc_redact --cov-report=term-missing -q
```

Result:

- 110 passed, 0 failed, 0 skipped
- 88% total line/branch-aware coverage
- Only PyMuPDF SWIG deprecation warnings were emitted
- No PaddleOCR or GLiNER model was downloaded

QA independently reran 109 cases after the final blocker pass. Implementation then
added one stricter malformed outer-empty Paddle result to the existing parametrized
regression and reran the complete 110-case suite successfully.

The test suite is split across:

- `tests/test_recognizers.py`: deterministic CRN semantics, context, false
  positives, token/line splits, and Presidio registration
- `tests/test_patterns.py`: safe schema, context, disabled patterns, protected
  built-in, unsafe regex rejection, bounded count/text, and timeout fail-closed
- `tests/test_ingest.py`: supported formats, byte/extension mismatch,
  malformed/empty files, upload/page/frame/pixel/decompression limits,
  password-protected PDF, EXIF rotation, DOCX active/external/traversal content,
  and LibreOffice private-profile/private-`TMPDIR` isolation and failure
  contracts
- `tests/test_ocr.py`: explicit PP-OCRv5/orientation configuration, Paddle result
  mapping, malformed/mismatched result fail-closed behavior, explicit
  valid-empty distinction, invalid geometry, serialized shared-predictor
  access, deterministic fake, and local-only GLiNER-through-Presidio behavior
  using model fakes
- `tests/test_pipeline.py`: solid-black padded pixel coverage of every split
  token, adversarial PDF rebuilding, forbidden-structure stripping, staged
  verification, indeterminate/exception suppression, stale-output removal,
  timeout result suppression, multi-frame order/dimensions, invalid OCR
  geometry, and cleanup on all paths
- `tests/test_verify.py`: image-only PDF structure, page count, actions,
  annotations, forms/hidden content, embedded files, source text, verifier
  exceptions/timeouts, and built-in/custom-pattern re-OCR rediscovery
- `tests/test_web.py`: generic errors, no failed download, sanitized success
  response, pre-multipart declared/streamed body limits including a lying
  `Content-Length`, bounded upload queue and receive timeout, shared
  receive-through-processing concurrency, request isolation/cleanup,
  loopback-only Host/DNS-rebinding defense, cross-site mutation rejection,
  protected pattern API, effective regex limits, and accessible/UI safety copy
- `tests/test_delivery.py`: required artifacts, lightweight CI, non-root/bounded
  container settings, README disclosures, and synthetic pattern example

## AC reconciliation

| AC | Status | Evidence |
| --- | --- | --- |
| AC-01 Input boundary | Pass, lightweight | All accepted content types; declared and streamed bodies are bounded before multipart parsing even with a lying `Content-Length`; spoofed extension/client MIME, malformed, empty, oversized, excess pages/frames/pixels, Pillow bomb, compressed DOCX, traversal, active content, external relationships, password PDF, and converter failure tests |
| AC-02 Privacy/lifecycle | Pass with residual hard-timeout risk | Generic content-free responses, no user filename reuse, private job paths plus private LibreOffice profile/`TMPDIR`, cleanup on success/failure, a shared receive-through-processing concurrency slot, queue/receive deadlines, concurrent request isolation, and pipeline deadline suppressing output |
| AC-03 OCR contract | Pass by adapter/fake | PP-OCRv5/orientation arguments, strict result schema, malformed and length-mismatched result rejection, explicit valid-empty results, serialized shared inference, token fields/geometry, and fake CI path tested; real model inference not executed |
| AC-04 CRN semantics | Pass | Presidio registry, spaced/unspaced/punctuation/NBSP/newline forms, compact-without-context false positive, exact ASCII format, all split boxes, optional local GLiNER not primary |
| AC-05 Pixel redaction | Pass | Poppler/PyMuPDF render plus exact black-pixel corner/center checks, padding, clamping, multi-token and multi-page coverage |
| AC-06 Irreversible PDF | Pass | Adversarial source has text, metadata, annotation, attachment, JavaScript/OpenAction/AA, form/XFA, and optional content; output is a single-revision image-only PDF without copied structures or target bytes |
| AC-07 Verification gate | Pass | Empty text extraction, strict image-only stream, structure denylist, page count, built-in/custom re-OCR rediscovery, exception, timeout, false/indeterminate result, staging, and no-publish tests |
| AC-08 Patterns | Pass | Full bounded schema, effective app limit, count/input bound, unsafe constructs, regex timeout, context/enable/confidence/label, and protected built-in mutation/deletion tests |
| AC-09 API/UI | Pass | Safe headers/filename/media type, verified-only response, generic failures, loopback-only trusted Host allowlist blocks arbitrary-Host DNS rebinding, cross-site mutation rejection, protected pattern flow, accessible labels/live region/copy, responsive CSS assertion, local desktop/320 px browser smoke, and no usable download URL before verified success |
| AC-10 Automated evidence | Pass | 110 synthetic-only unit/API/integration/adversarial tests |
| AC-11 Deployment | Pass by inspection; runtime not executed | CI installs only test extras with fake OCR; Dockerfile is non-root, one worker, health checked; Compose is read-only/no-new-privileges/internal network |
| AC-12 Delivery | Pass for local repository contents | Required code, docs, ADRs, threat model, AGENTS, orchestration log, pattern example, tests, container, CI, and final-report files exist; remote publication is outside QA ownership |

The detailed QA-to-AC mapping is in `docs/qa-plan.md`.

## Independent PDF evidence

The passing split-token output was independently rendered with Poppler and
inspected visually. It showed a fully opaque black redaction on an otherwise
white page with no rendering defect. `pdfinfo` reported:

- one page, 120 x 80 points
- no metadata stream or custom metadata
- no form or JavaScript
- not encrypted

`pypdf`, PyMuPDF, and the application verifier independently confirmed empty
text extraction, one image content stream per page, no annotations/widgets,
no embedded files, no active content/optional content, no copied sensitive
metadata, and one `startxref`/`%%EOF` revision.

## Environment-limited checks

These are not represented as passing full-runtime tests:

- **PP-OCRv5/PaddleOCR:** `paddleocr` and `paddle` are not installed in the QA
  environment, so actual model acquisition/inference, rotated scan accuracy,
  and OCR recall/precision were not measured. The adapter contract is tested
  with a deterministic injected Paddle class.
- **GLiNER:** the `gliner` package/model is not installed. Local-only loading,
  Presidio registration, output mapping, and non-CRN scope are tested with an
  injected local model fake.
- **LibreOffice:** the environment exposes `soffice` (LibreOfficeDev
  26.8.0.0.alpha0), while production invokes `libreoffice`. Actual end-to-end
  DOCX conversion was therefore not run here. Command arguments, isolated
  private profile and private converter `TMPDIR`, sanitized environment,
  timeout/failure handling, DOCX ZIP safety, and converted-PDF validation are
  automated with fakes.
- **Docker:** no Docker CLI/daemon is available, so image build, health check,
  read-only filesystem, internal network, and container model acquisition were
  inspected statically rather than executed.
- **GitHub Actions:** the workflow was inspected and the identical lightweight
  pytest command was run locally; an actual hosted Actions run is outside this
  environment.

## Residual risks

- The in-process deadline detects a slow OCR/native stage after it returns and
  prevents output publication, but it cannot forcibly terminate a hung native
  OCR call. The README correctly identifies process-level isolation and hard
  termination as future work.
- Detection quality under real PP-OCRv5, especially damaged, handwriting-heavy,
  skewed, or unusually split scans, remains model- and document-dependent.
- Full browser assistive-technology and cross-browser visual testing is not
  part of this Python suite; automated semantic/static UI gates are green.
- The application is a local MVP without authentication, malware scanning, or
  multi-tenant worker isolation and must not be treated as a public service.

No reproducible product failure remains in the executed lightweight gate.
