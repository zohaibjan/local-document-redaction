from __future__ import annotations

import asyncio
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .errors import DocRedactError
from .ocr import make_ocr_engine
from .patterns import PROTECTED_ENTITY, PatternDefinition
from .pipeline import RedactionPipeline
from .recognizers import DetectionService, LocalGlinerRecognizer

_UI_DIRECTORY = Path(__file__).with_name("ui")
_INDEX_TEMPLATE = (_UI_DIRECTORY / "index.html").read_text(encoding="utf-8")
_APP_CSS = (_UI_DIRECTORY / "app.css").read_text(encoding="utf-8")
_APP_JS = (_UI_DIRECTORY / "app.js").read_text(encoding="utf-8")


class RequestSizeLimitMiddleware:
    """Bound the full HTTP body before Starlette's multipart parser can spool it."""

    def __init__(
        self,
        app: ASGIApp,
        max_body_bytes: int,
        job_semaphore: asyncio.Semaphore,
        receive_timeout_seconds: float,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.job_semaphore = job_semaphore
        self.receive_timeout_seconds = receive_timeout_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != "/redact"
        ):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except ValueError:
                await self._reject(scope, receive, send, status_code=400)
                return
            if declared_length < 0 or declared_length > self.max_body_bytes:
                await self._reject(scope, receive, send, status_code=413)
                return

        acquired = False
        try:
            try:
                await asyncio.wait_for(
                    self.job_semaphore.acquire(),
                    timeout=self.receive_timeout_seconds,
                )
                acquired = True
            except TimeoutError:
                await self._reject(scope, receive, send, status_code=503)
                return

            buffered: list[Message] = []
            total = 0
            try:
                async with asyncio.timeout(self.receive_timeout_seconds):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        if message["type"] != "http.request":
                            continue
                        total += len(message.get("body", b""))
                        if total > self.max_body_bytes:
                            await self._reject(scope, receive, send, status_code=413)
                            return
                        buffered.append(message)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await self._reject(scope, receive, send, status_code=408)
                return

            async def replay() -> Message:
                if buffered:
                    return buffered.pop(0)
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.app(scope, replay, send)
        finally:
            if acquired:
                self.job_semaphore.release()

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
    ) -> None:
        response = JSONResponse(
            {"error": "request could not be safely processed"},
            status_code=status_code,
        )
        await response(scope, receive, send)


class PatternStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._patterns: dict[str, PatternDefinition] = {}
        self._lock = threading.Lock()

    def list(self) -> list[PatternDefinition]:
        with self._lock:
            return list(self._patterns.values())

    def put(self, definition: PatternDefinition) -> None:
        if len(definition.regex) > self.settings.max_pattern_length:
            raise ValueError(
                f"regex exceeds the configured {self.settings.max_pattern_length} characters"
            )
        with self._lock:
            existing = next(
                (
                    identifier
                    for identifier in self._patterns
                    if identifier.casefold() == definition.identifier.casefold()
                ),
                None,
            )
            if existing is None and len(self._patterns) >= self.settings.max_patterns:
                raise ValueError("pattern limit reached")
            if existing and existing != definition.identifier:
                del self._patterns[existing]
            self._patterns[definition.identifier] = definition

    def delete(self, identifier: str) -> bool:
        if identifier.casefold() == PROTECTED_ENTITY.casefold():
            raise ValueError("the built-in recognizer is protected")
        with self._lock:
            actual = next(
                (
                    candidate
                    for candidate in self._patterns
                    if candidate.casefold() == identifier.casefold()
                ),
                None,
            )
            if actual is None:
                return False
            del self._patterns[actual]
            return True


def _home_html(settings: Settings) -> str:
    if settings.max_upload_bytes % (1024 * 1024) == 0:
        upload_label = f"{settings.max_upload_bytes // (1024 * 1024)} MB"
    else:
        upload_label = f"{settings.max_upload_bytes / (1024 * 1024):.1f} MB"
    replacements = {
        "{{MAX_UPLOAD_BYTES}}": str(settings.max_upload_bytes),
        "{{MAX_UPLOAD_LABEL}}": upload_label,
        "{{MAX_PAGES}}": str(settings.max_pages),
        "{{MAX_PATTERN_LENGTH}}": str(settings.max_pattern_length),
        "{{MAX_PATTERNS}}": str(settings.max_patterns),
    }
    page = _INDEX_TEMPLATE
    for marker, value in replacements.items():
        page = page.replace(marker, value)
    return page


def create_app(
    settings: Settings | None = None,
    pipeline_factory: Callable[[list[PatternDefinition]], RedactionPipeline] | None = None,
) -> FastAPI:
    configured = settings or Settings.from_env()
    store = PatternStore(configured)
    semaphore = asyncio.Semaphore(2)
    engine_lock = threading.Lock()
    engine_cache = None
    semantic_cache = None

    def default_factory(patterns: list[PatternDefinition]) -> RedactionPipeline:
        nonlocal engine_cache, semantic_cache
        with engine_lock:
            if engine_cache is None:
                engine_cache = make_ocr_engine(configured.ocr_backend)
            if configured.gliner_enabled and semantic_cache is None:
                semantic_cache = LocalGlinerRecognizer()
        return RedactionPipeline(
            configured,
            engine_cache,
            DetectionService(configured, patterns, semantic_cache),
        )

    factory = pipeline_factory or default_factory
    app = FastAPI(
        title="Doc Redact",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
        www_redirect=False,
    )
    app.add_middleware(
        RequestSizeLimitMiddleware,
        # Allow bounded multipart headers while keeping the file limit exact in
        # the endpoint and content validator.
        max_body_bytes=configured.max_upload_bytes + 256 * 1024,
        job_semaphore=semaphore,
        receive_timeout_seconds=min(
            60.0,
            float(configured.processing_timeout_seconds),
        ),
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # Browser form/API mutations are same-origin only. API clients that do not
        # send browser Origin/Fetch Metadata headers remain supported.
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site", "").casefold()
        host = request.headers.get("host", "").casefold()
        try:
            origin_host = urlsplit(origin).netloc.casefold() if origin else ""
        except ValueError:
            origin_host = ""
        cross_site_mutation = request.method in {"POST", "PUT", "PATCH", "DELETE"} and (
            fetch_site == "cross-site"
            or bool(origin and (origin == "null" or origin_host != host))
        )
        if cross_site_mutation:
            response = JSONResponse(
                {"error": "cross-site request rejected"},
                status_code=403,
            )
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; frame-src blob:; form-action 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        return response

    @app.exception_handler(DocRedactError)
    async def safe_error(_: Request, __: DocRedactError):
        return JSONResponse(
            {"error": "document could not be safely processed"},
            status_code=422,
        )

    @app.get("/", response_class=HTMLResponse)
    async def home() -> str:
        return _home_html(configured)

    @app.get("/assets/app.css", include_in_schema=False)
    async def app_css() -> Response:
        return Response(_APP_CSS, media_type="text/css; charset=utf-8")

    @app.get("/assets/app.js", include_in_schema=False)
    async def app_js() -> Response:
        return Response(_APP_JS, media_type="text/javascript; charset=utf-8")

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "ocr_backend": configured.ocr_backend}

    @app.get("/api/patterns")
    async def list_patterns() -> dict[str, object]:
        return {
            "protected": {
                "identifier": PROTECTED_ENTITY,
                "name": "Centrelink CRN",
                "output_label": "Format-valid Centrelink CRN candidate",
                "enabled": True,
            },
            "patterns": [pattern.model_dump() for pattern in store.list()],
        }

    @app.put("/api/patterns/{identifier}")
    async def put_pattern(
        identifier: str, definition: PatternDefinition
    ) -> PatternDefinition:
        if identifier != definition.identifier:
            raise HTTPException(409, "path and body pattern identifiers must match")
        try:
            store.put(definition)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return definition

    @app.delete("/api/patterns/{identifier}", status_code=204)
    async def delete_pattern(identifier: str) -> Response:
        try:
            deleted = store.delete(identifier)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not deleted:
            raise HTTPException(404, "pattern not found")
        return Response(status_code=204)

    @app.post("/redact")
    async def redact(document: UploadFile = File(...)) -> Response:
        filename = document.filename or "upload"
        data = await document.read(configured.max_upload_bytes + 1)
        await document.close()
        if len(data) > configured.max_upload_bytes:
            raise HTTPException(413, "upload exceeds the configured size limit")

        with tempfile.TemporaryDirectory(prefix="doc-redact-request-") as temp_name:
            output = Path(temp_name) / "redacted-document.pdf"
            pipeline = await asyncio.to_thread(factory, store.list())
            report = await asyncio.to_thread(pipeline.process, data, filename, output)
            payload = output.read_bytes()
        return Response(
            payload,
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'attachment; filename="redacted-document.pdf"',
                "X-Redaction-Detections": str(report.detections),
                "X-Redaction-Pages": str(report.source_pages),
                "X-Redaction-Verified": "true",
            },
        )

    return app


app = create_app()


def run() -> None:
    uvicorn.run("doc_redact.web:app", host="127.0.0.1", port=8000, access_log=False)
