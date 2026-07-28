# Secure MVP delivery report

Date: 2026-07-28  
Gate owner: orchestration agent  
Current status: **LOCAL RELEASE GATE GREEN; repository publication blocked by platform approval/usage gate**

## Delivered

- FastAPI local web application and injectable processing pipeline.
- Explicit PP-OCRv5 production adapter plus scripted lightweight fake adapter.
- Protected deterministic Presidio `AU_CENTRELINK_CRN` recognizer using
  “format-valid CRN candidate” semantics, context scoring, OCR span reconstruction,
  and all-token box mapping.
- Optional local-only GLiNER Presidio recognizer, disabled by default.
- Content/extension validation for PDF, DOCX, JPEG, PNG, and TIFF with byte, page,
  archive, decompression, pixel, active-content, and malformed-input limits.
- Private DOCX conversion profile and common high-DPI raster pipeline.
- Opaque black pixel redaction with padding/clamping.
- Newly constructed image-only PDF with physical page size preserved.
- Private staging, independent structural/text/optional re-OCR verification, and atomic
  promotion only after a green gate.
- Bounded Presidio user-pattern adapters with protected built-in semantics.
- Controlled dependencies, non-root container/Compose deployment, local-only pattern
  example, and lightweight CI without model downloads.
- Architecture, ADRs, threat model, acceptance criteria, phased/QA plans, orchestration
  protocol, and status log.

## Commands

Lightweight suite:

```bash
python -m pip install -e '.[test]'
DOC_REDACT_OCR_BACKEND=fake DOC_REDACT_VERIFY_WITH_OCR=false pytest
```

Production local mode:

```bash
python -m pip install -e '.[ocr]'
uvicorn doc_redact.web:app --host 127.0.0.1 --port 8000 --no-access-log
```

Container:

```bash
docker compose build
docker compose up
```

## Evidence status

The macOS system Python is blocked by missing Apple Command Line Tools, but the bundled
Python 3.12 runtime was located and used. After repeated
architect/implementation/QA/UI feedback passes, the current lightweight suite passed:

```text
110 passed
TOTAL coverage: 88%
```

This includes recognizer, ingestion, strict OCR-adapter result handling, bounded
pre-multipart upload handling, pipeline, verifier, adversarial PDF, API, security, and
UI tests. Desktop and 320 px browser smoke covered custom-pattern interaction,
verified-only result/download/preview behavior, responsive overflow, focus, and safe
malformed-input errors. Wheel inspection confirmed all HTML/CSS/JavaScript assets are
packaged.

## Known residual risks

- Native OCR and office parsers are in-process/external parser dependencies. Cooperative
  deadlines detect overrun at stage boundaries, and LibreOffice/regex have explicit
  timeouts, but forcibly terminating a wedged native OCR call requires a future
  process-isolated worker.
- OCR/GLiNER model acquisition is a supply-chain and operational step. Pin, scan, and
  pre-acquire model artifacts before running the container with outbound networking
  disabled.
- The MVP has no authentication, authorization, malware scanner, durable job service,
  or multi-tenant isolation and must not be exposed publicly.
- Image-only output intentionally loses searchable text and semantic accessibility.
- Automated detection can miss identifiers; a human must review redacted pixels before
  sharing.

## Prioritized improvements

### Release blockers

None remain in the executed local lightweight gate. The heavyweight runtime checks
below must be completed before representing a specific model/container build as
production-validated.

### Next iteration

1. Move native OCR and office conversion into killable, resource-limited worker
   processes so a hung native call can be terminated, not merely prevented from
   publishing output after it returns.
2. Pre-acquire and integrity-control PP-OCRv5 and optional GLiNER model artifacts,
   then run accuracy/rotation/adversarial recall tests on synthetic scans.
3. Run actual LibreOffice DOCX conversion and Docker/Compose smoke tests in the target
   deployment environment.
4. Add authentication, durable capability-scoped jobs, malware scanning, rate limits,
   and multi-tenant isolation before any network exposure beyond loopback.

### Nice to have

- Granular backend progress rather than staged client-side status.
- Branded accessible confirmation dialogs instead of native browser confirms.
- Wider browser/assistive-technology testing and performance baselines for large
  multi-page documents.

## Environment-unexecuted checks

These commands describe the remaining full-runtime evidence; none is counted as
passing in the local gate:

```bash
# Install heavyweight local model runtimes, pre-acquire trusted model assets,
# then start the high-assurance path for synthetic-only manual/fixture testing.
python -m pip install -e '.[ocr,gliner]'
DOC_REDACT_OCR_BACKEND=paddle \
DOC_REDACT_VERIFY_WITH_OCR=true \
DOC_REDACT_GLINER_ENABLED=true \
uvicorn doc_redact.web:app --host 127.0.0.1 --port 8000 --no-access-log

# In an environment where the LibreOffice executable is named `libreoffice`,
# run the full suite including native conversion coverage.
pytest -m requires_libreoffice

# Container/runtime evidence.
docker compose build
docker compose up --wait
docker compose exec app python -c \
  'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/healthz")'
```

The hosted GitHub Actions run remains pending until the repository is published.

## Repository publication

The target is the private repository `zohaibjan/Doc_redact`, default branch `main`.
Local terminal HTTPS/SSH Git authentication is unavailable. The orchestration agent
attempted the explicitly authorized connected-GitHub-app publication. The app rejected
the first repository write before any remote change because automatic approval review
could not run after the account reached its Codex usage limit. GitHub therefore remains
empty; no commit SHA exists.

After the usage/approval allowance is restored, publish this exact validated source
tree to `main` through the connected GitHub app, then run the hosted lightweight CI
workflow. Do not publish `.venv/`, `.coverage`, `.pytest_cache/`, `work/`, `outputs/`,
or Python cache files.
