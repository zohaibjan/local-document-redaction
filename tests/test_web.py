from __future__ import annotations

import asyncio
from pathlib import Path
import re
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from doc_redact.errors import ProcessingFailed, VerificationFailed
from doc_redact.models import ProcessingReport
from doc_redact.ocr import FakeOCREngine
from doc_redact.pipeline import RedactionPipeline
from doc_redact.recognizers import DetectionService
from doc_redact.web import RequestSizeLimitMiddleware, create_app

from conftest import SYNTHETIC_CRN_COMPACT, image_bytes, synthetic_pdf_bytes


class SuccessfulPipeline:
    def process(self, data: bytes, filename: str, output: Path) -> ProcessingReport:
        assert not output.exists()
        output.write_bytes(synthetic_pdf_bytes())
        return ProcessingReport(
            output_path=output,
            source_pages=1,
            detections=1,
            labels={"Format-valid Centrelink CRN candidate": 1},
            verification={"all_checks": True},
        )


class FailingPipeline:
    def __init__(self, exception: Exception) -> None:
        self.exception = exception

    def process(self, data: bytes, filename: str, output: Path):
        raise self.exception


def test_home_is_accessible_warns_and_has_no_premature_download(
    lightweight_settings,
) -> None:
    client = TestClient(
        create_app(lightweight_settings, lambda patterns: SuccessfulPipeline())
    )

    response = client.get("/")

    assert response.status_code == 200
    html = response.text.casefold()
    assert '<html lang="en">' in html
    assert 'name="viewport"' in html
    assert "<h1" in html
    assert 'for="document"' in html
    assert 'id="document"' in html
    assert "format-valid centrelink crn candidates" in html
    assert "does not confirm" in html
    assert "automated detection is not guaranteed" in html
    for supported in ("pdf", "docx", "jpeg", "png", "tiff"):
        assert supported in html
    download_anchor = re.search(r'<a id="download-link"([^>]*)>', html)
    assert download_anchor is not None
    assert "href=" not in download_anchor.group(1)
    css = client.get("/assets/app.css").text
    assert "@media (max-width:" in css
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"]


def test_untrusted_host_is_rejected_to_reduce_dns_rebinding_risk(
    lightweight_settings,
) -> None:
    client = TestClient(
        create_app(lightweight_settings, lambda patterns: SuccessfulPipeline())
    )

    response = client.get("/", headers={"host": "attacker.example"})

    assert response.status_code == 400
    assert not response.content.startswith(b"%PDF")


def test_declared_oversized_request_is_rejected_before_multipart_parsing(
    lightweight_settings,
) -> None:
    client = TestClient(
        create_app(lightweight_settings, lambda patterns: SuccessfulPipeline())
    )

    response = client.post(
        "/redact",
        content=b"",
        headers={
            "content-type": "multipart/form-data; boundary=synthetic",
            "content-length": str(lightweight_settings.max_upload_bytes + 300_000),
        },
    )

    assert response.status_code == 413
    assert not response.content.startswith(b"%PDF")


def test_streamed_body_exceeding_limit_is_rejected_despite_lying_length(
    lightweight_settings,
) -> None:
    app = create_app(lightweight_settings, lambda patterns: SuccessfulPipeline())

    async def exercise() -> httpx.Response:
        async def chunks():
            for _ in range(8):
                yield b"x" * 300_000

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/redact",
                content=chunks(),
                headers={
                    "content-type": "application/octet-stream",
                    "content-length": "1",
                },
            )

    response = asyncio.run(exercise())

    assert response.status_code == 413
    assert not response.content.startswith(b"%PDF")


def test_slow_chunked_upload_receive_times_out_before_parser() -> None:
    downstream_called = False
    sent_messages = []

    async def downstream(scope, receive, send):
        nonlocal downstream_called
        downstream_called = True

    async def slow_receive():
        await asyncio.sleep(0.05)
        return {"type": "http.request", "body": b"x", "more_body": True}

    async def capture_send(message):
        sent_messages.append(message)

    middleware = RequestSizeLimitMiddleware(
        downstream,
        max_body_bytes=100,
        job_semaphore=asyncio.Semaphore(1),
        receive_timeout_seconds=0.01,
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/redact",
        "raw_path": b"/redact",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }

    asyncio.run(middleware(scope, slow_receive, capture_send))

    assert downstream_called is False
    assert sent_messages[0]["status"] == 408


def test_verified_success_returns_only_safe_pdf_download(lightweight_settings) -> None:
    client = TestClient(
        create_app(lightweight_settings, lambda patterns: SuccessfulPipeline())
    )

    response = client.post(
        "/redact",
        files={"document": ("../../leaky name.png", image_bytes("PNG"), "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="redacted-document.pdf"'
    )
    assert response.headers["x-redaction-verified"] == "true"
    assert response.headers["x-redaction-detections"] == "1"
    assert response.headers["x-redaction-pages"] == "1"
    assert "leaky" not in str(response.headers).casefold()
    assert response.content.startswith(b"%PDF")


def test_browser_mutations_reject_cross_site_origin(lightweight_settings) -> None:
    client = TestClient(
        create_app(lightweight_settings, lambda patterns: SuccessfulPipeline())
    )
    payload = {
        "identifier": "SYNTH_CASE_ID",
        "name": "Synthetic case",
        "regex": r"CASE-[0-9]{4}",
        "context_terms": [],
        "confidence": 0.7,
        "enabled": True,
        "output_label": "Synthetic case identifier",
    }

    response = client.put(
        "/api/patterns/SYNTH_CASE_ID",
        json=payload,
        headers={"Origin": "https://attacker.invalid", "Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403
    assert response.json() == {"error": "cross-site request rejected"}
    assert client.get("/api/patterns").json()["patterns"] == []


def test_oversized_upload_is_rejected_before_pipeline(lightweight_settings) -> None:
    called = False

    def factory(patterns):
        nonlocal called
        called = True
        return SuccessfulPipeline()

    client = TestClient(create_app(lightweight_settings, factory))
    response = client.post(
        "/redact",
        files={
            "document": (
                "too-large.png",
                b"x" * (lightweight_settings.max_upload_bytes + 1),
                "image/png",
            )
        },
    )

    assert response.status_code == 413
    assert called is False
    assert "x" * 20 not in response.text
    assert "content-disposition" not in response.headers


def test_api_rejects_filename_content_mismatch_through_real_validation(
    lightweight_settings,
) -> None:
    def factory(patterns):
        return RedactionPipeline(
            lightweight_settings,
            FakeOCREngine(),
            DetectionService(lightweight_settings, patterns),
        )

    client = TestClient(create_app(lightweight_settings, factory))

    response = client.post(
        "/redact",
        files={"document": ("spoofed.pdf", image_bytes("PNG"), "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json() == {"error": "document could not be safely processed"}
    assert "content-disposition" not in response.headers
    assert "x-redaction-verified" not in response.headers


@pytest.mark.asyncio
async def test_concurrent_api_jobs_are_bounded_isolated_and_cleaned(
    lightweight_settings,
) -> None:
    lock = threading.Lock()
    active = 0
    maximum_active = 0
    output_paths: list[Path] = []

    class TrackingPipeline:
        def process(self, data: bytes, filename: str, output: Path) -> ProcessingReport:
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
                output_paths.append(output)
            try:
                time.sleep(0.04)
                output.write_bytes(synthetic_pdf_bytes())
                return ProcessingReport(output, 1, 0, verification={"safe": True})
            finally:
                with lock:
                    active -= 1

    app = create_app(lightweight_settings, lambda patterns: TrackingPipeline())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        responses = await asyncio.gather(
            *[
                client.post(
                    "/redact",
                    files={
                        "document": (
                            f"synthetic-{index}.png",
                            image_bytes("PNG"),
                            "image/png",
                        )
                    },
                )
                for index in range(5)
            ]
        )

    assert all(response.status_code == 200 for response in responses)
    assert all(response.headers["x-redaction-verified"] == "true" for response in responses)
    assert maximum_active == 2
    assert len(set(output_paths)) == 5
    assert all(not path.exists() for path in output_paths)


def test_failed_verification_has_no_pdf_or_download_headers(
    lightweight_settings,
) -> None:
    client = TestClient(
        create_app(
            lightweight_settings,
            lambda patterns: FailingPipeline(
                VerificationFailed("synthetic internal check was indeterminate")
            ),
        )
    )

    response = client.post(
        "/redact",
        files={"document": ("synthetic.png", image_bytes("PNG"), "image/png")},
    )

    assert response.status_code == 422
    assert not response.content.startswith(b"%PDF")
    assert "content-disposition" not in response.headers
    assert "x-redaction-verified" not in response.headers
    assert response.json() == {"error": "document could not be safely processed"}


def test_error_response_does_not_echo_content_temp_path_or_internal_details(
    lightweight_settings,
) -> None:
    sensitive_detail = (
        f"matched {SYNTHETIC_CRN_COMPACT} in /private/tmp/doc-redact-secret/source.pdf"
    )
    client = TestClient(
        create_app(
            lightweight_settings,
            lambda patterns: FailingPipeline(ProcessingFailed(sensitive_detail)),
        )
    )

    response = client.post(
        "/redact",
        files={"document": ("synthetic.png", image_bytes("PNG"), "image/png")},
    )

    assert response.status_code == 422
    assert response.json() == {"error": "document could not be safely processed"}
    assert SYNTHETIC_CRN_COMPACT not in response.text
    assert "/private/tmp" not in response.text


def test_pattern_api_schema_and_protected_builtin(lightweight_settings) -> None:
    client = TestClient(
        create_app(lightweight_settings, lambda patterns: SuccessfulPipeline())
    )
    payload = {
        "identifier": "SYNTH_CASE_ID",
        "name": "Synthetic case",
        "regex": r"CASE-[0-9]{4}",
        "context_terms": ["reference"],
        "confidence": 0.7,
        "enabled": True,
        "output_label": "Synthetic case identifier",
    }

    created = client.put("/api/patterns/SYNTH_CASE_ID", json=payload)
    listed = client.get("/api/patterns")
    protected_delete = client.delete("/api/patterns/AU_CENTRELINK_CRN")
    mismatch = client.put("/api/patterns/Other", json=payload)
    unsafe = client.put(
        "/api/patterns/Unsafe",
        json={**payload, "name": "Unsafe", "regex": "(a+)+$"},
    )

    assert created.status_code == 200
    assert listed.json()["protected"]["enabled"] is True
    assert listed.json()["protected"]["identifier"] == "AU_CENTRELINK_CRN"
    assert listed.json()["patterns"] == [payload]
    assert protected_delete.status_code == 409
    assert mismatch.status_code == 409
    assert unsafe.status_code == 422


def test_pattern_api_enforces_effective_configured_regex_limit(
    lightweight_settings,
) -> None:
    from dataclasses import replace

    settings = replace(lightweight_settings, max_pattern_length=16)
    client = TestClient(create_app(settings, lambda patterns: SuccessfulPipeline()))
    payload = {
        "identifier": "TOO_LONG",
        "name": "Too long",
        "regex": "x" * 17,
        "context_terms": [],
        "confidence": 0.7,
        "enabled": True,
        "output_label": "Too long",
    }

    response = client.put("/api/patterns/TOO_LONG", json=payload)

    assert response.status_code in {409, 422}
    assert client.get("/api/patterns").json()["patterns"] == []


def test_ui_exposes_live_status_and_user_pattern_configuration(
    lightweight_settings,
) -> None:
    client = TestClient(
        create_app(lightweight_settings, lambda patterns: SuccessfulPipeline())
    )

    html = client.get("/").text.casefold()

    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert "custom redaction pattern" in html
    for field in ("identifier", "name", "regex", "context_terms", "confidence", "enabled", "output_label"):
        assert f'name="{field}"' in html
    script = client.get("/assets/app.js").text
    assert 'requestPattern("/api/patterns")' in script
    assert "response.protected" in script
    assert 'createChip("Protected"' in script
