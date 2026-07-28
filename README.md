# Doc Redact

Doc Redact is a local-first web application that detects and irreversibly covers
**format-valid Australian Centrelink Customer Reference Number (CRN) candidates**.
It does not and cannot verify whether Services Australia actually issued a candidate.

The secure output path renders every input page to pixels, draws opaque black pixels
over every mapped OCR box, and creates a brand-new image-only PDF. Source text layers,
annotations, forms, attachments, optional-content layers, metadata, and incremental
history are not copied. A structural and optional re-OCR gate fails closed before the
result is made available.

> Automated PII detection is not guaranteed. Review the visual output before sharing
> it. Image-only PDFs lose searchable text and document accessibility structure.

## Supported inputs

Content is detected from bytes and must agree with its filename extension:

| Content | Extensions |
|---|---|
| PDF | `.pdf` |
| Word Open XML | `.docx` |
| JPEG | `.jpg`, `.jpeg` |
| PNG | `.png` |
| TIFF | `.tif`, `.tiff` |

Legacy `.doc`, macro-enabled documents, archives, password-protected PDFs, SVG, and
other formats are rejected. DOCX external relationships, macros, ActiveX, and embedded
objects are rejected before conversion.

## Run locally

Prerequisites are Python 3.11–3.13 and LibreOffice for DOCX conversion.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[ocr]'
uvicorn doc_redact.web:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open `http://127.0.0.1:8000`. PaddleOCR is explicitly initialized with
`ocr_version="PP-OCRv5"`. Its model artifacts may be downloaded by Paddle on first
acquisition; acquire them deliberately, then run document processing without network
access. No document is sent to an external service.

For lightweight CI or interface development:

```bash
pip install -e '.[test]'
DOC_REDACT_OCR_BACKEND=fake DOC_REDACT_VERIFY_WITH_OCR=false pytest
```

The fake adapter contains no implicit detections. Tests inject synthetic OCR tokens and
boxes, so CI does not download PaddleOCR or GLiNER models.

## Container

```bash
docker compose build
docker compose up
```

The container runs as an unprivileged user with a read-only root filesystem and a
private temporary filesystem. The Compose application network is marked internal to
block normal outbound access. Pre-acquire PP-OCRv5 model assets in a controlled build or
mounted cache before enabling that boundary. Do not expose this MVP directly to the
public internet; it has no authentication or malware scanner.

## Configuration

All limits have conservative bounds and invalid values stop startup.

| Variable | Default |
|---|---:|
| `DOC_REDACT_MAX_UPLOAD_BYTES` | `26214400` |
| `DOC_REDACT_MAX_PAGES` | `50` |
| `DOC_REDACT_MAX_PIXELS_PER_PAGE` | `50000000` |
| `DOC_REDACT_MAX_TOTAL_PIXELS` | `250000000` |
| `DOC_REDACT_RENDER_DPI` | `300` |
| `DOC_REDACT_REDACTION_PADDING_PX` | `8` |
| `DOC_REDACT_OCR_BACKEND` | `paddle` |
| `DOC_REDACT_VERIFY_WITH_OCR` | `true` |
| `DOC_REDACT_GLINER_ENABLED` | `false` |

GLiNER is optional, local-only, and deliberately not the CRN detector:

```bash
pip install -e '.[ocr,gliner]'
DOC_REDACT_GLINER_ENABLED=true uvicorn doc_redact.web:app --host 127.0.0.1
```

The configured GLiNER model must already exist locally; the adapter requests
`local_files_only=True`.

## Extensible patterns

The protected `AU_CENTRELINK_CRN` recognizer cannot be replaced or deleted. Named
user patterns use a bounded schema and the `regex` engine with per-evaluation timeout.
Backreferences, lookbehind, recursion, obvious nested repetition, overlong expressions,
and excessive context are rejected. A timeout fails the entire job.

```bash
curl -X PUT http://127.0.0.1:8000/api/patterns/SYNTHETIC_CASE_ID \
  -H 'content-type: application/json' \
  --data @examples/patterns/synthetic-case-id.json
```

Pattern configuration is in-memory in this MVP; restart clears it. The API is intended
for local administration only.

## Security model and limitations

- Upload bodies, OCR text, detection values, and source filenames are not logged.
- `/redact` request bodies are byte-counted before multipart parsing. At most two
  request/job slots may receive buffered uploads or process documents concurrently;
  declared and streamed limits, queue timeout, and receive timeout fail before parsing.
  The container also limits the server to eight concurrent connections.
- Browser service hosts are restricted to `localhost`, `127.0.0.1`, IPv6 loopback,
  and the test client host to reduce loopback DNS-rebinding risk. A deliberate
  reverse-proxy/LAN deployment must update this code-level allowlist and add
  authentication and TLS; that topology is outside this local MVP.
- Unpredictable per-job directories are deleted, and outputs are staged there.
- A result is atomically promoted only after all enabled verification checks pass.
- The PDF verifier rejects text, annotations, forms/XFA, attachments/filespecs,
  JavaScript, actions/URIs, optional content, copied metadata, extra revisions, and
  unexpected page drawing/content operators.
- Regex work, upload bytes, pages, pixels, OCR text, patterns, and concurrency are
  bounded. Process-level isolation and hard termination of native OCR are future work.
- The shared PP-OCRv5 predictor is serialized because its cross-thread inference safety
  is not assumed. LibreOffice uses both a private profile and private `TMPDIR` inside
  the per-job cleanup boundary.
- LibreOffice runs with a private user profile, but is a large parser. For hostile
  multi-tenant use, isolate each job in a sandboxed worker with CPU/memory/time limits.
- This MVP does not include authentication, authorization, antivirus scanning,
  audit persistence, high-availability workers, or public deployment hardening.

See [architecture](docs/architecture.md), [threat model](docs/threat-model.md),
[acceptance criteria](docs/acceptance-criteria.md), and the ADRs in `docs/adr/`.

## Test and inspect

```bash
pytest
pytest --cov=doc_redact --cov-report=term-missing
```

All fixtures and identifiers must be synthetic. The lightweight suite covers the
recognizer, OCR-token mapping, malicious and mismatched inputs, API behavior,
black-pixel output, and independent image-only PDF verification.
