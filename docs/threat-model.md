# Threat model

## Method and security objectives

This model uses data-flow trust boundaries plus STRIDE-style abuse analysis.
Primary objectives are:

1. never release a PDF that retains a detected target or removable cover;
2. prevent input/pattern abuse from escaping the process or exhausting the host;
3. keep document content local and out of operational records;
4. prevent cross-job access and stale sensitive files;
5. describe detection uncertainty honestly.

## Assets

- Source documents and converted/raster intermediates.
- OCR text and detection locations.
- Redacted output before and after verification.
- User-defined patterns, which may themselves reveal sensitive conventions.
- Host availability and integrity.
- Assurance status: a false `verified` state is a security asset failure.

## Threat actors and assumptions

An unauthenticated or local network caller may submit intentionally malformed
files and regexes, race job/download endpoints, guess identifiers, interrupt
processing, or attempt resource exhaustion. A document author may hide content in
PDF structures or exploit parsers. A recipient may actively inspect output
objects, text layers, metadata and pixels or remove annotations.

The host administrator and packaged native libraries are trusted. PP-OCRv5 and
optional GLiNER execute locally; model files must come from documented,
integrity-controlled sources. Browser compromise and a malicious host
administrator are outside the application assurance boundary.

## Threat/control matrix

| ID | Threat | Impact | Required controls | Evidence |
|---|---|---|---|---|
| T01 | Extension/MIME spoof or malformed parser input | Parser exploit, bypass | Magic/content inspection, strict allowlist, parse failure rejection, updated libraries, container isolation | API/input tests |
| T02 | Oversized image/PDF/TIFF or decompression bomb | CPU/memory/disk exhaustion | Streaming byte cap, preflight dimensions/pages/frames, per-page and total pixel caps, decoder bomb errors, deadlines | adversarial limit tests |
| T03 | DOCX ZIP bomb, traversal, macro, OLE, external link | Resource abuse, code/network access | ZIP entry/path/ratio caps; reject macro/active content/external relationships; isolated no-network LibreOffice subprocess/profile | DOCX preflight tests |
| T04 | PDF text, layer, attachment, form, annotation or incremental history copied | Redaction reversible/content leak | Rasterize each page; builder accepts rasters only; construct new PDF; structural allowlist verification | adversarial PDF test |
| T05 | Black annotation or transparent overlay instead of pixel overwrite | Recipient reveals value | Opaque black pixel paint on canonical raster; alpha flattening; pixel tests | redaction tests |
| T06 | Split candidate maps to only one OCR token | Partial value remains | Character-to-token provenance map; all contributing boxes; multi-line rectangle policy | split-token tests |
| T07 | OCR misses/incorrectly reads a candidate | Sensitive value remains | High-DPI render, rotation support, context/confidence tuning, optional high-assurance output re-OCR, prominent limitation; manual review recommended | OCR fixtures/README |
| T08 | Verification error treated as success | Unsafe file returned | Tri-state checks collapsed fail-closed; output handle created only after success; failure injection tests | verifier/API tests |
| T09 | Catastrophic user regex | Service denial | Strict lengths/counts, conservative syntax or linear-time engine, bounded input, isolatable deadline | unsafe-regex tests |
| T10 | User disables/shadows built-in CRN | Required protection bypass | Built-in registered separately; reserved IDs/entity; immutable merge rules; startup invariant | configuration tests |
| T11 | Job ID enumeration/cross-job download | Privacy breach | Cryptographically random capability, ownership/session binding where applicable, constant generic 404, expiry, no listing | API authorization tests |
| T12 | Temp/output residue on failure or crash | Privacy breach | Mode-0700 random dirs, structured cleanup, startup/periodic stale reaper, short TTL, dedicated volume | lifecycle tests/ops docs |
| T13 | Logs/errors expose OCR/matches/paths | Privacy breach | Structured allowlist logging, generic external errors, redaction middleware, no parser exception passthrough | log-capture tests |
| T14 | Concurrent flood or slow upload | Availability loss | Reverse-proxy/server request limit, upload deadline, semaphore/queue cap, bounded workers, rate limit where exposed | load/config evidence |
| T15 | Model or dependency substitution | Code or result integrity loss | controlled versions, hashes where practical, trusted model cache, SBOM/scanning/update process | lock/container/CI |
| T16 | Browser active content/filename injection | XSS/path issue | Escape templates, CSP/security headers, display-only normalized name, `Content-Disposition` encoding | UI/API tests |
| T17 | Metadata or generated identifier leaks source information | Privacy breach | generated minimal metadata, no source filename in output metadata, structural verifier | PDF tests |
| T18 | Claims imply issuance verification | User over-trust | canonical phrase “format-valid CRN candidate,” no Services Australia lookup, UI/README warning | copy tests/review |
| T19 | SSRF/network exfiltration through converter/model | Document disclosure | local model cache; outbound network denied; reject external DOCX relations; conversion no-network | deployment config/tests |
| T20 | Geometry outside page/NaN/confidence abuse from OCR | Crash or missed redaction | validate finite coordinates/ranges, clamp boxes, reject invalid token contract, token/string caps | unit/property tests |

## PDF verification allowlist

Verification should distrust the output builder and inspect its result
independently. For each PDF:

- it opens cleanly and has the expected page count;
- each page has one or a documented small number of image XObjects covering the
  page and no text-showing operators;
- extracted text is empty (and normalized targets are absent);
- `/Annots`, `/AcroForm`, `/EmbeddedFiles`, `/Filespec`, `/JavaScript`, launch,
  URI actions, optional content and XFA are absent;
- generated metadata contains no input metadata or filename;
- the file is a completed new document, not an incremental append;
- when required, rendered output re-OCR produces no target detection.

Library inspection alone can miss unusual object encodings. Prefer two
independent checks where practical (for example pypdf structural checks plus
Poppler text extraction/rendering). An unsupported construct is a failure, not an
ignore.

## Residual risks

- OCR and deterministic patterns can miss blurred, handwritten, stylized,
  low-contrast, occluded or unexpectedly formatted content.
- A black rectangle communicates the location and approximate length of removed
  information.
- Native parsing/OCR dependencies can contain unknown vulnerabilities; container
  and subprocess isolation reduce but do not eliminate this risk.
- Re-OCR cannot mathematically prove pixel absence. The stronger property comes
  from raster ownership and opaque overwrite plus structural reconstruction.
- Local-first does not protect a compromised host, browser, container runtime or
  administrator.
- A user-defined pattern may over-redact or under-redact. Safe execution is not
  semantic correctness.

Users should visually inspect results and use the high-assurance profile for
sensitive distribution.
