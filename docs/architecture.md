# Architecture

## Purpose and assurance boundary

Doc Redact is a local-first web application that finds **format-valid Centrelink
CRN candidates** and other configured patterns, irreversibly paints their source
pixels black, and returns only output that passes structural and content
verification.

Format validity is not issuance validity. The application never contacts
Services Australia and cannot establish whether an identifier was actually
issued.

The assurance claim is deliberately narrow:

> For a target detected by the configured pipeline, the released PDF is a new
> image-only document whose covered source pixels and source PDF structures have
> not been retained, and which passed the configured verification profile.

It is not a claim that OCR or PII detection finds every sensitive value.

## Component view

```text
Browser
  |
  | multipart upload + opaque job capability
  v
FastAPI boundary
  |- request/size/concurrency limits
  |- content sniffing and container validation
  v
Job service in a private temporary directory
  |
  +--> DOCX preflight --> bounded LibreOffice subprocess --> PDF
  |
  +--> image decoder / PDF rasterizer --> canonical page raster(s)
  |
  +--> PP-OCRv5 adapter --------+
  |                              |
  |                              v
  |                   normalized OCR document
  |                              |
  |                   Presidio analysis engine
  |                    |- protected CRN recognizer
  |                    |- bounded user patterns
  |                    `- optional local GLiNER
  |                              |
  |                    span-to-token-box mapper
  |                              |
  +---------------------> pixel redactor
                                 |
                      new image-only PDF builder
                                 |
                         verification gate
                         |- text absence
                         |- structure allowlist
                         `- optional re-OCR
                                 |
                         capability-scoped download
```

Only the verified output crosses the processing boundary. Inputs, intermediate
rasters, OCR text, detections, converted PDFs, and failed outputs remain in the
job directory and are cleaned up.

## Package boundaries

Names are logical contracts; exact modules may vary without changing them.

### `api`

Owns HTTP parsing, content length checks, authentication/capability checks, rate
or concurrency limiting, generic errors, headers, and response streaming. It does
not inspect document contents beyond passing a bounded stream to `ingest`.

### `ingest`

```python
class InputInspector(Protocol):
    def inspect(self, stream: BinaryIO, display_name: str) -> InspectedInput: ...

class DocumentCanonicalizer(Protocol):
    def pages(self, source: InspectedInput, workdir: Path) -> Iterator[PageRaster]: ...
```

`InspectedInput` contains a server-selected media type, byte count, and sanitized
display name. `PageRaster` contains a page index, pixel dimensions, DPI and an
RGB/RGBA raster owned by the application. It contains no retained PDF object.

The inspector rejects before conversion. The canonicalizer applies limits while
decoding, not solely after all pages are in memory.

### `ocr`

```python
@dataclass(frozen=True)
class OCRToken:
    page: int
    text: str
    polygon: tuple[Point, ...]
    confidence: float
    reading_order: int
    line_id: str | None

class OCREngine(Protocol):
    def recognize(self, page: PageRaster) -> Sequence[OCRToken]: ...
```

The Paddle implementation pins/configures PP-OCRv5 explicitly. The fake
implementation implements the same contract. OCR confidence is preserved; it is
not treated as proof of identifier validity.

### `analysis`

OCR tokens are assembled into a `NormalizedOCRDocument` with:

- original token text;
- a normalized analysis string;
- a character-to-token index map;
- page, line and reading-order boundaries;
- explicit synthetic separators added by reconstruction.

The analyzer returns immutable detections:

```python
@dataclass(frozen=True)
class Detection:
    entity_type: str
    output_label: str
    start: int
    end: int
    confidence: float
    token_indexes: tuple[int, ...]
    source: str
```

The analyzer must not include matched text in logs, exceptions, metrics, job
status, or response DTOs.

The built-in recognizer is registered independently of user configuration and
cannot be overridden by entity type, name, or identifier. Context adjustment is
deterministic. Reconstruction is bounded: it joins adjacent OCR fragments in
reading order only when geometry/line rules permit and never crosses pages.

### `patterns`

```python
class PatternSpec(BaseModel):
    id: str
    name: str
    regex: str
    context_terms: list[str]
    confidence: float
    enabled: bool
    output_label: str
```

Validation uses strict schemas and bounded fields. Prefer a linear-time regex
engine or a conservative accepted subset. If the Python backtracking engine is
used, evaluation must run with a real deadline in an isolatable worker and on a
bounded normalized string. A thread-only timeout is insufficient because a
pathological match can retain the GIL.

### `redaction`

The mapper resolves every detection token index to a page polygon, converts it to
an axis-aligned rectangle, expands it by configured pixel or physical-unit
padding, clamps it, and merges overlapping rectangles. A detection spanning
multiple lines yields multiple rectangles unless their expanded rectangles
overlap; it must not black out the whitespace band between unrelated line areas.

The renderer creates a copy/canonical raster and paints `(0, 0, 0, 255)` over
each rectangle. Output alpha is flattened before PDF encoding.

### `output`

The builder accepts redacted rasters only. It constructs a new PDF with one
full-page image per page and minimal generated metadata. It has no interface that
accepts a source PDF object, preventing accidental copying.

```python
class PDFBuilder(Protocol):
    def build(self, pages: Iterable[PageRaster], destination: Path) -> None: ...

class OutputVerifier(Protocol):
    def verify(
        self,
        output: Path,
        targets: Sequence[NormalizedTarget],
        profile: VerificationProfile,
    ) -> VerificationReport: ...
```

`VerificationReport.passed` is true only when every required check ran and
passed. The service exposes a download handle only after `passed`; exceptions and
indeterminate results are failures.

### `jobs`

The application may start with in-process jobs, but owns a concurrency semaphore,
per-stage monotonic deadlines, cancellation and a private job root. Job state is
minimal (`queued`, `processing`, `needs_confirmation`, `verified`, `failed`,
`expired`). Status exposes counts and assurance profile, never matched values.
Restart durability is out of MVP scope; abandoned directories are reaped by age.

## Processing sequence

1. Stream a bounded upload to a private job directory while hashing/counting.
2. Inspect magic bytes and fully preflight the container/image within limits.
3. If DOCX, run a macro/external-link/archive check, then LibreOffice with an
   isolated user profile, no network, a deadline, and resource limits. Treat the
   produced PDF as untrusted input.
4. Rasterize PDF pages or decode image frames into canonical raster pages while
   enforcing page/pixel limits.
5. OCR each page locally through the selected adapter.
6. Build normalized analysis text and character-to-token mapping.
7. Run protected CRN, enabled bounded patterns, and optional local GLiNER through
   Presidio.
8. Convert detections to padded/clamped page rectangles. Show only a count/label
   summary if confirmation is enabled.
9. Paint pixels and build a fresh image-only PDF.
10. Verify structure, extracted-text target absence, and required re-OCR.
11. Atomically mark the output verified, expose a short-lived download
    capability, and delete it after download/expiry.
12. On any error or timeout, suppress output, record a content-free error code,
    and clean the job directory.

## Limits and configuration

Security limits are server-owned and have conservative defaults:

- upload bytes;
- pages/frames;
- width, height, pixels per page, and total pixels;
- DOCX archive entries, compressed/uncompressed bytes and ratio;
- OCR tokens and normalized characters;
- custom pattern count and lengths;
- concurrent jobs;
- per-stage and whole-job timeouts;
- output lifetime.

Client-provided values cannot raise server maxima. Configuration is validated once
at startup. Production refuses an internally inconsistent or disabled mandatory
verification configuration.

## Trust boundaries and data classification

All uploads and user patterns are hostile. OCR/model output is also untrusted
because malformed model responses can create invalid geometry or very large
strings. LibreOffice, PDF/image decoders, rasterizers and OCR libraries are
high-risk parser/model boundaries and should be isolated by container,
subprocess/resource limit, and update policy.

Raw input, rendered pages, OCR text, candidates, and output are sensitive
document data. Logs, traces and metrics are non-sensitive operational data and
must contain only job correlation IDs, timings, byte/page counts, labels/counts,
result codes and version/config fingerprints.

## Observability without content disclosure

Allowed fields include opaque job ID, stage, duration, size bucket, page count,
detector name, detection count, verification check/result, and stable error code.
Disallowed fields include filenames before normalization, document bytes, OCR
text, matched substrings, token boxes, regex input strings, filesystem paths, and
exception representations from parsers that may embed content.

## Accessibility baseline

The server-rendered UI uses semantic form controls, visible labels, keyboard
operation, focus movement to status/errors, a live region for progress, sufficient
contrast, non-color-only status, and a plain-language assurance warning.

## Out of scope for the MVP

- Verifying issuance of a CRN.
- Guaranteed discovery of all PII or handwriting.
- Returning editable DOCX or preserving searchable PDF text.
- Remote/cloud processing or public deployment.
- Multi-tenant persistent document storage.
- Manual coordinate editing beyond optional confirm/reject of reported labels.
