# QA plan and acceptance mapping

This plan is the executable quality gate for the secure MVP. All fixtures and
identifiers used by the test suite must be synthetic. A passing format check
means only "format-valid CRN candidate"; it never asserts that Services
Australia issued the value.

## Test modes

- **Lightweight/CI:** fake OCR and semantic recognizers; no PaddleOCR or GLiNER
  model download. Exercises recognition, span-to-box mapping, raster redaction,
  PDF rebuilding, verification, API validation, and security limits.
- **Full/local:** PP-OCRv5 and optional local GLiNER enabled. Exercises scanned,
  rotated, and OCR-noisy fixtures. This suite may be skipped with a clear reason
  when the large local models are unavailable.

## Acceptance matrix

| ID | AC | Requirement | Primary evidence | Gate |
| --- | --- | --- | --- | --- |
| QA-CRN-01 | AC-04, AC-10 | Spaced `123 456 789A`-shaped synthetic input is identified as `AU_CENTRELINK_CRN` and called a format-valid candidate | recognizer unit test | Required |
| QA-CRN-02 | AC-04, AC-10 | Unspaced `123456789A`-shaped synthetic input is identified | recognizer unit test | Required |
| QA-CRN-03 | AC-04, AC-10 | Common OCR whitespace/newline splits are handled without widening to unrelated text | recognizer and span-map tests | Required |
| QA-CRN-04 | AC-04, AC-10 | Context and confidence suppress unrelated 9-digit-plus-letter false positives | positive/negative parametrized unit tests | Required |
| QA-CRN-05 | AC-04, AC-09 | The product never claims that a candidate is an issued/verified CRN | API/UI copy test | Required |
| QA-CRN-06 | AC-04, AC-08 | Built-in CRN recognizer cannot be deleted or disabled through user pattern configuration | API/config tests | Required |
| QA-MAP-01 | AC-04, AC-05 | A match spanning multiple OCR tokens maps to all and only overlapping boxes | geometry unit test | Required |
| QA-MAP-02 | AC-04, AC-05, AC-10 | Split-line CRNs map to multiple boxes and all pixels are covered with bounded padding | geometry/image assertion | Required |
| QA-MAP-03 | AC-03, AC-05, AC-10 | Rotation/coordinate transforms preserve redaction placement | image/integration test | Required if implemented; otherwise documented risk |
| QA-PAT-01 | AC-08 | Named custom regex patterns support context, confidence, enabled flag, and output label | config/API tests | Required |
| QA-PAT-02 | AC-08, AC-10 | Invalid, empty, oversized, duplicate, or unsafe regex patterns fail closed | adversarial API/unit tests | Required |
| QA-PAT-03 | AC-08 | Pattern matching is bounded by input size and/or timeout/safe-regex validation | adversarial timing/validation test | Required |
| QA-IN-01 | AC-01 | PDF, DOCX, JPEG/JPG, PNG, and TIFF are accepted by content, not filename alone | API/integration tests | Required |
| QA-IN-02 | AC-01, AC-10 | Extension/MIME mismatch, malformed content, unsupported type, and empty file are rejected | adversarial API tests | Required |
| QA-IN-03 | AC-01, AC-10 | Configured file-size, page-count, image-pixel, and document-count limits fail before expensive work | unit/API tests | Required |
| QA-IN-04 | AC-01 | Macro-enabled/active DOCX and archive-like input are rejected or safely flattened by documented policy | adversarial fixture test | Required |
| QA-IN-05 | AC-01, AC-02 | DOCX conversion failures/timeouts are fail-closed and produce no output | integration test with fake converter | Required |
| QA-PDF-01 | AC-06 | Every source PDF page is rasterized and output is a newly built image-only PDF | PDF object inspection | Required |
| QA-PDF-02 | AC-06, AC-07 | Output PDF has no extractable source text, annotations, forms, attachments, JavaScript, hidden layers, incremental-update remnants, or copied metadata | pypdf/PyMuPDF/Poppler inspection | Required |
| QA-PDF-03 | AC-06, AC-07, AC-10 | Source secrets in text layer, annotation, form, attachment, and metadata do not survive output | malicious synthetic PDF fixture | Required |
| QA-PDF-04 | AC-05, AC-10 | Black pixel boxes irreversibly cover every matched OCR box with configured padding | rendered pixel inspection | Required |
| QA-PDF-05 | AC-07, AC-10 | Text extraction confirms matched target absent; optional re-OCR failure causes no file to be returned | verification/API tests | Required |
| QA-PDF-06 | AC-06 | Multi-page documents preserve page count/order and readable raster dimensions | PDF inspection/render comparison | Required |
| QA-API-01 | AC-01, AC-09 | Upload returns a safe, deterministic media type and sanitized content-disposition filename | API test | Required |
| QA-API-02 | AC-07, AC-09, AC-10 | Failed recognition, conversion, rendering, redaction, or verification never returns a document | injected-failure API tests | Required |
| QA-API-03 | AC-02, AC-09 | Concurrent work uses isolated unpredictable directories and cleans up success/failure paths | concurrency/unit tests | Required |
| QA-PRIV-01 | AC-02, AC-09 | Logs, errors, metrics, and filenames do not contain document text or detected values | captured-error/API tests | Required |
| QA-PRIV-02 | AC-02, AC-04 | Processing remains local; optional GLiNER is local and no network client is required at runtime | dependency/config and adapter tests | Required |
| QA-PRIV-03 | AC-02, AC-09 | UI clearly warns that automated PII detection is not guaranteed | HTML copy test | Required |
| QA-DEP-01 | AC-11 | Container has bounded, non-root runtime and documents LibreOffice/model requirements | Dockerfile/config review | Required |
| QA-CI-01 | AC-10, AC-11 | CI runs the lightweight suite without OCR/GLiNER downloads | workflow inspection plus local command | Required |

## Adversarial fixture set

All strings below are generated within tests and are synthetic examples:

- A one-page PDF with a visually rendered CRN-shaped string and a different
  hidden text-layer string.
- A PDF containing metadata, a URI/text annotation, an AcroForm widget,
  JavaScript/open action, and an embedded text file containing a CRN-shaped
  string.
- A multi-page PDF containing a candidate split across OCR tokens and lines.
- JPEG, PNG, and TIFF images; a rotated image; oversized-dimension image with
  small encoded size; truncated/corrupt encodings; and polyglot/signature
  mismatches.
- Plain DOCX, macro-enabled/active-content variants, malformed ZIP, ZIP-bomb
  metadata, and a converter timeout/failure fake.
- Regex denial-of-service candidates such as nested ambiguous quantifiers,
  excessive pattern length, and catastrophic non-matches over bounded text.

## PDF inspection procedure

For each successful PDF output:

1. Reopen it with `pypdf.PdfReader`.
2. Assert the page count/order is expected.
3. Assert each page has image content but no source text extraction result.
4. Assert zero `/Annots`, no `/AcroForm`, `/Names` embedded files, JavaScript,
   `/OpenAction`, optional-content configuration, or copied custom metadata.
5. Use `pdfplumber`/`pdftotext` as an independent text extraction check.
6. Render every page with Poppler and inspect the target pixel rectangle for
   solid black coverage and surrounding non-target readability.
7. When re-OCR verification is enabled, inject a fake positive and require the
   processing/API layer to fail closed without returning bytes.

## Release gate

The lightweight suite must pass with no required acceptance item failing.
Full-model cases may be reported as environment-blocked only when the exact
missing model/runtime and a reproducible command are documented. Security
failures involving output reconstruction, verification, data leakage, input
limits, or temporary-file cleanup are never waivable for the MVP.
