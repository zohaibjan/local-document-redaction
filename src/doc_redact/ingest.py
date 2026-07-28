from __future__ import annotations

import io
import os
import subprocess
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import fitz
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import Settings
from .errors import InputRejected, ProcessingFailed

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
IMAGE_MIMES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "TIFF": "image/tiff",
}


@dataclass(frozen=True, slots=True)
class ValidatedInput:
    mime_type: str
    data: bytes
    safe_stem: str = "document"


@dataclass(slots=True)
class PageRaster:
    image: Image.Image
    width_points: float
    height_points: float


def _validate_zip_safety(archive: zipfile.ZipFile, settings: Settings) -> None:
    entries = archive.infolist()
    if len(entries) > 5_000:
        raise InputRejected("DOCX contains too many archive entries")
    total = 0
    for entry in entries:
        normalized = entry.filename.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise InputRejected("DOCX contains an unsafe archive path")
        total += entry.file_size
        if total > max(100 * 1024 * 1024, settings.max_upload_bytes * 10):
            raise InputRejected("DOCX expands beyond the permitted size")
        if entry.compress_size and entry.file_size / entry.compress_size > 200:
            raise InputRejected("DOCX contains a suspicious compression ratio")
        lowered = normalized.casefold()
        if (
            lowered.endswith("vbaproject.bin")
            or "/activex/" in lowered
            or "/embeddings/" in lowered
            or lowered.endswith(".exe")
        ):
            raise InputRejected("DOCX active or embedded content is not supported")


def _validate_docx(data: bytes, settings: Settings) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            _validate_zip_safety(archive, settings)
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise InputRejected("ZIP content is not a valid DOCX document")
            content_types = archive.read("[Content_Types].xml")
            if b"macroEnabled" in content_types or b"vbaProject" in content_types:
                raise InputRejected("macro-enabled Word documents are not supported")
            for name in names:
                if name.endswith(".rels"):
                    root = ElementTree.fromstring(archive.read(name))
                    for relation in root:
                        if relation.attrib.get("TargetMode", "").casefold() == "external":
                            raise InputRejected("DOCX external relationships are not supported")
    except (zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise InputRejected("malformed DOCX document") from exc


def _validate_pdf(data: bytes, settings: Settings) -> None:
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise InputRejected("malformed PDF document") from exc
    try:
        if document.needs_pass:
            raise InputRejected("password-protected PDFs are not supported")
        if document.page_count < 1 or document.page_count > settings.max_pages:
            raise InputRejected(f"PDF page count must be between 1 and {settings.max_pages}")
        total_pixels = 0
        zoom = settings.render_dpi / 72.0
        for page in document:
            pixels = int(page.rect.width * zoom) * int(page.rect.height * zoom)
            if pixels > settings.max_pixels_per_page:
                raise InputRejected("a PDF page exceeds the configured pixel limit")
            total_pixels += pixels
            if total_pixels > settings.max_total_pixels:
                raise InputRejected("PDF exceeds the total pixel limit")
    finally:
        document.close()


def _validate_image(data: bytes, settings: Settings) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            detected_format = image.format
            if detected_format not in IMAGE_MIMES:
                raise InputRejected("image content is not JPEG, PNG, or TIFF")
            frames = int(getattr(image, "n_frames", 1))
            if frames > settings.max_pages:
                raise InputRejected(f"image frame count exceeds {settings.max_pages}")
            total_pixels = 0
            for index in range(frames):
                image.seek(index)
                pixels = image.width * image.height
                if pixels > settings.max_pixels_per_page:
                    raise InputRejected("an image frame exceeds the configured pixel limit")
                total_pixels += pixels
                if total_pixels > settings.max_total_pixels:
                    raise InputRejected("image exceeds the total pixel limit")
            image.verify()
            return IMAGE_MIMES[detected_format]
    except InputRejected:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        EOFError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise InputRejected("malformed image") from exc


def validate_input(data: bytes, filename: str, settings: Settings) -> ValidatedInput:
    if not data:
        raise InputRejected("the uploaded file is empty")
    if len(data) > settings.max_upload_bytes:
        raise InputRejected(f"upload exceeds {settings.max_upload_bytes} bytes")

    if data.startswith(b"%PDF-"):
        _validate_pdf(data, settings)
        mime = PDF_MIME
    elif data.startswith(b"PK\x03\x04"):
        _validate_docx(data, settings)
        mime = DOCX_MIME
    else:
        mime = _validate_image(data, settings)

    extension = Path(filename).suffix.casefold()
    allowed_extensions = {
        PDF_MIME: {".pdf"},
        DOCX_MIME: {".docx"},
        "image/jpeg": {".jpg", ".jpeg"},
        "image/png": {".png"},
        "image/tiff": {".tif", ".tiff"},
    }
    if extension not in allowed_extensions[mime]:
        raise InputRejected("filename extension does not match the detected content type")

    # The original path and name are never trusted or reproduced.
    return ValidatedInput(mime_type=mime, data=data, safe_stem="redacted-document")


def docx_to_pdf(source: ValidatedInput, workdir: Path, settings: Settings) -> bytes:
    input_path = workdir / "source.docx"
    input_path.write_bytes(source.data)
    profile_path = workdir / "libreoffice-profile"
    profile_path.mkdir(mode=0o700)
    converter_temp = workdir / "libreoffice-temp"
    converter_temp.mkdir(mode=0o700)
    sanitized_env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "TMPDIR"}
    }
    sanitized_env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    sanitized_env["TMPDIR"] = str(converter_temp)
    try:
        process = subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--norestore",
                f"-env:UserInstallation={profile_path.as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(workdir),
                str(input_path),
            ],
            check=False,
            capture_output=True,
            timeout=settings.libreoffice_timeout_seconds,
            env=sanitized_env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ProcessingFailed("DOCX conversion is unavailable or timed out") from exc
    output_path = workdir / "source.pdf"
    if process.returncode != 0 or not output_path.is_file():
        raise ProcessingFailed("DOCX conversion failed")
    converted = output_path.read_bytes()
    _validate_pdf(converted, settings)
    return converted


def render_pages(
    source: ValidatedInput,
    workdir: Path,
    settings: Settings,
) -> list[PageRaster]:
    if source.mime_type == DOCX_MIME:
        source = ValidatedInput(PDF_MIME, docx_to_pdf(source, workdir, settings))

    if source.mime_type == PDF_MIME:
        document = fitz.open(stream=source.data, filetype="pdf")
        pages: list[PageRaster] = []
        try:
            matrix = fitz.Matrix(settings.render_dpi / 72, settings.render_dpi / 72)
            for page in document:
                pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
                pages.append(
                    PageRaster(
                        image=Image.frombytes(
                            "RGB", (pixmap.width, pixmap.height), pixmap.samples
                        ),
                        width_points=float(page.rect.width),
                        height_points=float(page.rect.height),
                    )
                )
        finally:
            document.close()
        return pages

    image = Image.open(io.BytesIO(source.data))
    pages = []
    for index in range(int(getattr(image, "n_frames", 1))):
        image.seek(index)
        raster = ImageOps.exif_transpose(image.copy()).convert("RGB")
        dpi = image.info.get("dpi", (72, 72))
        try:
            x_dpi, y_dpi = float(dpi[0]), float(dpi[1])
        except (TypeError, ValueError, IndexError):
            x_dpi = y_dpi = 72.0
        if not 36 <= x_dpi <= 1200:
            x_dpi = 72.0
        if not 36 <= y_dpi <= 1200:
            y_dpi = 72.0
        pages.append(
            PageRaster(
                image=raster,
                width_points=raster.width * 72.0 / x_dpi,
                height_points=raster.height * 72.0 / y_dpi,
            )
        )
    image.close()
    return pages
