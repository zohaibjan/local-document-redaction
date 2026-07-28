from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path

import fitz
from PIL import Image
from pypdf import PdfReader

from .errors import VerificationFailed
from .models import MappedDetection, OCRToken

_FORBIDDEN_PDF_NAMES = (
    "/JavaScript",
    "/OpenAction",
    "/AA",
    "/AcroForm",
    "/XFA",
    "/OCProperties",
    "/EmbeddedFiles",
    "/Filespec",
    "/Launch",
    "/URI",
)
_IMAGE_ONLY_STREAM = re.compile(
    rb"\A\s*q\s+[-+0-9.eE]+\s+[-+0-9.eE]+\s+[-+0-9.eE]+\s+"
    rb"[-+0-9.eE]+\s+[-+0-9.eE]+\s+[-+0-9.eE]+\s+cm\s+"
    rb"/[A-Za-z0-9_.-]+\s+Do\s+Q\s*\Z"
)


def _catalog_has_embedded_files(reader: PdfReader) -> bool:
    root = reader.trailer["/Root"]
    names = root.get("/Names")
    if names and names.get_object().get("/EmbeddedFiles"):
        return True
    return False


def verify_output_pdf(
    output_path: Path,
    required_entities: set[str],
    *,
    ocr_callback: Callable[[Image.Image, int], list[OCRToken]] | None = None,
    redetect_callback: Callable[[list[OCRToken]], list[MappedDetection]] | None = None,
    expected_pages: int | None = None,
    deadline: float | None = None,
    ocr_dpi: int = 300,
) -> dict[str, bool]:
    checks = {
        "text_absent": False,
        "image_only": False,
        "no_annotations": False,
        "no_embedded_files": False,
        "no_forms": False,
        "no_active_content": False,
        "no_metadata": False,
        "single_revision": False,
        "page_count_matches": False,
        "ocr_targets_absent": ocr_callback is None,
    }
    try:
        raw_pdf = output_path.read_bytes()
        checks["single_revision"] = (
            raw_pdf.count(b"%%EOF") == 1
            and raw_pdf.count(b"startxref") == 1
            and raw_pdf.rstrip().endswith(b"%%EOF")
        )
        reader = PdfReader(str(output_path), strict=True)
        extracted = "".join(page.extract_text() or "" for page in reader.pages)
        checks["text_absent"] = not extracted.strip()
        checks["no_annotations"] = all(not page.get("/Annots") for page in reader.pages)
        checks["no_embedded_files"] = not _catalog_has_embedded_files(reader)
        checks["no_forms"] = "/AcroForm" not in reader.trailer["/Root"]
        checks["page_count_matches"] = expected_pages is None or len(reader.pages) == expected_pages
        info = reader.metadata
        checks["no_metadata"] = not info or not any(
            value for key, value in info.items() if key not in {"/Producer"} and value
        )

        document = fitz.open(str(output_path))
        try:
            object_definitions = "\n".join(
                document.xref_object(xref, compressed=False)
                for xref in range(1, document.xref_length())
            )
            checks["no_active_content"] = not any(
                re.search(re.escape(name) + r"(?![A-Za-z0-9])", object_definitions)
                for name in _FORBIDDEN_PDF_NAMES
            )
            image_only = document.page_count > 0
            for page in document:
                streams = [document.xref_stream(xref) for xref in page.get_contents()]
                image_only = image_only and (
                    len(page.get_images(full=True)) == 1
                    and len(streams) == 1
                    and bool(_IMAGE_ONLY_STREAM.fullmatch(streams[0]))
                    and not page.get_text("text").strip()
                    and not page.get_drawings()
                    and page.first_annot is None
                    and page.first_widget is None
                )
            checks["image_only"] = image_only
            if ocr_callback is not None:
                if redetect_callback is None:
                    raise VerificationFailed("re-OCR verification detector is unavailable")
                rediscovered_entities: set[str] = set()
                for page_index, page in enumerate(document):
                    if deadline is not None and time.monotonic() > deadline:
                        raise VerificationFailed("output verification timed out")
                    pix = page.get_pixmap(
                        matrix=fitz.Matrix(ocr_dpi / 72.0, ocr_dpi / 72.0),
                        colorspace=fitz.csRGB,
                        alpha=False,
                    )
                    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    tokens = ocr_callback(image, page_index)
                    detections = redetect_callback(tokens)
                    rediscovered_entities.update(
                        mapped.detection.entity_type for mapped in detections
                    )
                checks["ocr_targets_absent"] = not (
                    rediscovered_entities & required_entities
                )
        finally:
            document.close()
    except Exception as exc:
        if isinstance(exc, VerificationFailed):
            raise
        raise VerificationFailed("output PDF could not be safely verified") from exc

    if not all(checks.values()):
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        raise VerificationFailed(f"output PDF failed closed: {failed}")
    return checks
