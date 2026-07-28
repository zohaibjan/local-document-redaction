from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = int(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    max_upload_bytes: int = 25 * 1024 * 1024
    max_pages: int = 50
    max_pixels_per_page: int = 50_000_000
    max_total_pixels: int = 250_000_000
    render_dpi: int = 300
    redaction_padding_px: int = 8
    processing_timeout_seconds: int = 180
    libreoffice_timeout_seconds: int = 60
    max_patterns: int = 50
    max_pattern_length: int = 256
    max_ocr_characters: int = 2_000_000
    regex_timeout_seconds: float = 0.05
    ocr_backend: str = "paddle"
    verify_with_ocr: bool = True
    gliner_enabled: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            max_upload_bytes=_env_int(
                "DOC_REDACT_MAX_UPLOAD_BYTES",
                25 * 1024 * 1024,
                minimum=1024,
                maximum=250 * 1024 * 1024,
            ),
            max_pages=_env_int("DOC_REDACT_MAX_PAGES", 50, minimum=1, maximum=500),
            max_pixels_per_page=_env_int(
                "DOC_REDACT_MAX_PIXELS_PER_PAGE",
                50_000_000,
                minimum=1_000_000,
                maximum=200_000_000,
            ),
            max_total_pixels=_env_int(
                "DOC_REDACT_MAX_TOTAL_PIXELS",
                250_000_000,
                minimum=1_000_000,
                maximum=1_000_000_000,
            ),
            render_dpi=_env_int("DOC_REDACT_RENDER_DPI", 300, minimum=150, maximum=600),
            redaction_padding_px=_env_int(
                "DOC_REDACT_REDACTION_PADDING_PX", 8, minimum=0, maximum=100
            ),
            processing_timeout_seconds=_env_int(
                "DOC_REDACT_PROCESSING_TIMEOUT_SECONDS", 180, minimum=10, maximum=1800
            ),
            libreoffice_timeout_seconds=_env_int(
                "DOC_REDACT_LIBREOFFICE_TIMEOUT_SECONDS", 60, minimum=5, maximum=600
            ),
            max_patterns=_env_int("DOC_REDACT_MAX_PATTERNS", 50, minimum=0, maximum=200),
            max_pattern_length=_env_int(
                "DOC_REDACT_MAX_PATTERN_LENGTH", 256, minimum=16, maximum=1024
            ),
            max_ocr_characters=_env_int(
                "DOC_REDACT_MAX_OCR_CHARACTERS", 2_000_000, minimum=1000, maximum=10_000_000
            ),
            ocr_backend=os.getenv("DOC_REDACT_OCR_BACKEND", "paddle").casefold(),
            verify_with_ocr=_env_bool("DOC_REDACT_VERIFY_WITH_OCR", True),
            gliner_enabled=_env_bool("DOC_REDACT_GLINER_ENABLED", False),
        )

