from __future__ import annotations

import io
import subprocess
from pathlib import Path

import fitz
import pytest
from PIL import Image

from doc_redact.errors import InputRejected, ProcessingFailed
from doc_redact.ingest import (
    DOCX_MIME,
    PDF_MIME,
    ValidatedInput,
    docx_to_pdf,
    render_pages,
    validate_input,
)

from conftest import docx_bytes, image_bytes, synthetic_pdf_bytes


@pytest.mark.parametrize(
    ("payload", "filename", "mime"),
    [
        (image_bytes("JPEG"), "scan.jpg", "image/jpeg"),
        (image_bytes("JPEG"), "scan.jpeg", "image/jpeg"),
        (image_bytes("PNG"), "scan.png", "image/png"),
        (image_bytes("TIFF"), "scan.tif", "image/tiff"),
        (image_bytes("TIFF"), "scan.tiff", "image/tiff"),
        (synthetic_pdf_bytes(), "scan.pdf", PDF_MIME),
        (docx_bytes(), "scan.docx", DOCX_MIME),
    ],
)
def test_supported_types_are_detected_from_content(
    payload: bytes, filename: str, mime: str, lightweight_settings
) -> None:
    result = validate_input(payload, filename, lightweight_settings)

    assert result.mime_type == mime
    assert result.safe_stem == "redacted-document"
    assert filename not in result.safe_stem


@pytest.mark.parametrize(
    ("payload", "filename"),
    [
        (image_bytes("PNG"), "spoofed.pdf"),
        (synthetic_pdf_bytes(), "spoofed.png"),
        (docx_bytes(), "spoofed.pdf"),
        (b"", "empty.pdf"),
        (b"%PDF-truncated", "bad.pdf"),
        (b"PK\x03\x04not-a-zip", "bad.docx"),
        (b"not an image", "payload.png"),
    ],
)
def test_malformed_empty_and_extension_mismatch_are_rejected(
    payload: bytes, filename: str, lightweight_settings
) -> None:
    with pytest.raises(InputRejected):
        validate_input(payload, filename, lightweight_settings)


def test_upload_size_limit_is_checked_before_decode(lightweight_settings) -> None:
    settings = lightweight_settings.__class__(
        **{
            **{
                field: getattr(lightweight_settings, field)
                for field in lightweight_settings.__dataclass_fields__
            },
            "max_upload_bytes": 8,
        }
    )

    with pytest.raises(InputRejected, match="upload exceeds"):
        validate_input(b"x" * 9, "payload.pdf", settings)


def test_pillow_decompression_bomb_warning_is_rejected(
    monkeypatch, lightweight_settings
) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    with pytest.raises(InputRejected, match="malformed image"):
        validate_input(
            image_bytes("PNG", size=(20, 20)), "oversized.png", lightweight_settings
        )


def test_decoded_pixel_and_frame_limits_are_rejected(lightweight_settings) -> None:
    pixel_settings = lightweight_settings.__class__(
        **{
            **{
                field: getattr(lightweight_settings, field)
                for field in lightweight_settings.__dataclass_fields__
            },
            "max_pixels_per_page": 99,
        }
    )
    frame_settings = lightweight_settings.__class__(
        **{
            **{
                field: getattr(lightweight_settings, field)
                for field in lightweight_settings.__dataclass_fields__
            },
            "max_pages": 1,
        }
    )

    with pytest.raises(InputRejected, match="pixel limit"):
        validate_input(image_bytes("PNG", size=(10, 10)), "large.png", pixel_settings)
    with pytest.raises(InputRejected, match="frame count"):
        validate_input(
            image_bytes("TIFF", size=(5, 5), frames=2), "multi.tiff", frame_settings
        )


def test_pdf_page_limit_is_rejected(lightweight_settings) -> None:
    settings = lightweight_settings.__class__(
        **{
            **{
                field: getattr(lightweight_settings, field)
                for field in lightweight_settings.__dataclass_fields__
            },
            "max_pages": 1,
        }
    )
    with pytest.raises(InputRejected, match="page count"):
        validate_input(synthetic_pdf_bytes(pages=2), "multi.pdf", settings)


def test_password_protected_pdf_is_rejected(lightweight_settings) -> None:
    document = fitz.open()
    document.new_page()
    protected = document.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="synthetic-owner",
        user_pw="synthetic-user",
    )
    document.close()

    with pytest.raises(InputRejected, match="password-protected"):
        validate_input(protected, "protected.pdf", lightweight_settings)


def test_exif_rotated_image_is_transposed_before_ocr(
    tmp_path: Path, lightweight_settings
) -> None:
    image = Image.new("RGB", (10, 20), "white")
    exif = Image.Exif()
    exif[274] = 6
    stream = io.BytesIO()
    image.save(stream, format="JPEG", exif=exif)
    image.close()
    source = validate_input(stream.getvalue(), "rotated.jpg", lightweight_settings)

    pages = render_pages(source, tmp_path, lightweight_settings)

    try:
        assert len(pages) == 1
        assert pages[0].image.size == (20, 10)
    finally:
        pages[0].image.close()


def test_docx_suspicious_compression_ratio_is_rejected(lightweight_settings) -> None:
    payload = docx_bytes(extra_files={"word/styles.xml": b"A" * 500_000})

    with pytest.raises(InputRejected, match="compression ratio"):
        validate_input(payload, "compressed.docx", lightweight_settings)


@pytest.mark.parametrize(
    "payload",
    [
        docx_bytes(extra_files={"../escape.txt": b"x"}),
        docx_bytes(extra_files={"word/vbaProject.bin": b"x"}),
        docx_bytes(extra_files={"word/activeX/activeX1.bin": b"x"}),
        docx_bytes(
            content_types=(
                b'<Types><Override ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/>'
                b"</Types>"
            )
        ),
        docx_bytes(
            relationships=(
                b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                b'<Relationship Id="rId1" Target="https://example.invalid/x" '
                b'TargetMode="External" Type="x"/></Relationships>'
            )
        ),
    ],
)
def test_docx_active_external_and_traversal_content_is_rejected(
    payload: bytes, lightweight_settings
) -> None:
    with pytest.raises(InputRejected):
        validate_input(payload, "unsafe.docx", lightweight_settings)


def test_libreoffice_uses_isolated_profile_and_bounded_timeout(
    monkeypatch, tmp_path: Path, lightweight_settings
) -> None:
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        (tmp_path / "source.pdf").write_bytes(synthetic_pdf_bytes())
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = docx_to_pdf(
        ValidatedInput(DOCX_MIME, docx_bytes()), tmp_path, lightweight_settings
    )

    assert result.startswith(b"%PDF")
    assert any(
        item.startswith("-env:UserInstallation=file:") for item in observed["command"]
    )
    assert observed["kwargs"]["timeout"] == lightweight_settings.libreoffice_timeout_seconds
    assert "HOME" not in observed["kwargs"]["env"]
    assert observed["kwargs"]["env"]["TMPDIR"] == str(
        tmp_path / "libreoffice-temp"
    )
    assert (tmp_path / "libreoffice-profile").stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "libreoffice-temp").stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("failure", [FileNotFoundError(), subprocess.TimeoutExpired("lo", 1)])
def test_libreoffice_unavailable_or_timeout_fails_closed(
    monkeypatch, tmp_path: Path, lightweight_settings, failure: Exception
) -> None:
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ProcessingFailed, match="unavailable or timed out"):
        docx_to_pdf(
            ValidatedInput(DOCX_MIME, docx_bytes()), tmp_path, lightweight_settings
        )
    assert not (tmp_path / "source.pdf").exists()
