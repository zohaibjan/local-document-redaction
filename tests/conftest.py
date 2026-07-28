from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping

import fitz
import pytest
from PIL import Image

from doc_redact.config import Settings


SYNTHETIC_CRN_SPACED = "123 456 789A"
SYNTHETIC_CRN_COMPACT = "123456789A"


@pytest.fixture
def lightweight_settings() -> Settings:
    return Settings(
        max_upload_bytes=2_000_000,
        max_pages=4,
        max_pixels_per_page=2_000_000,
        max_total_pixels=4_000_000,
        render_dpi=150,
        redaction_padding_px=3,
        processing_timeout_seconds=10,
        libreoffice_timeout_seconds=5,
        max_patterns=4,
        max_pattern_length=128,
        max_ocr_characters=10_000,
        regex_timeout_seconds=0.01,
        ocr_backend="fake",
        verify_with_ocr=False,
        gliner_enabled=False,
    )


def image_bytes(
    image_format: str = "PNG",
    *,
    size: tuple[int, int] = (120, 80),
    frames: int = 1,
) -> bytes:
    images = [Image.new("RGB", size, "white") for _ in range(frames)]
    stream = io.BytesIO()
    if image_format == "TIFF":
        images[0].save(
            stream,
            format=image_format,
            save_all=True,
            append_images=images[1:],
            compression="tiff_deflate",
        )
    else:
        images[0].save(stream, format=image_format)
    for image in images:
        image.close()
    return stream.getvalue()


def synthetic_pdf_bytes(*, pages: int = 1, text: str | None = None) -> bytes:
    document = fitz.open()
    try:
        for index in range(pages):
            page = document.new_page(width=240, height=160)
            if text:
                page.insert_text((20, 50), f"{text} page {index + 1}")
        return document.tobytes(garbage=4, deflate=True, clean=True)
    finally:
        document.close()


def docx_bytes(
    *,
    extra_files: Mapping[str, bytes] | None = None,
    content_types: bytes | None = None,
    relationships: bytes | None = None,
) -> bytes:
    content_types = content_types or (
        b'<?xml version="1.0"?>'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Default Extension="xml" ContentType="application/xml"/>'
        b'<Override PartName="/word/document.xml" '
        b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        b"</Types>"
    )
    document_xml = (
        b'<?xml version="1.0"?>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body><w:p><w:r><w:t>Synthetic document</w:t></w:r></w:p></w:body>"
        b"</w:document>"
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document_xml)
        if relationships is not None:
            archive.writestr("word/_rels/document.xml.rels", relationships)
        for name, value in (extra_files or {}).items():
            archive.writestr(name, value)
    return stream.getvalue()
