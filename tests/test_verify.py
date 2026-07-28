from __future__ import annotations

import io
import time
from pathlib import Path

import fitz
import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

from doc_redact.errors import VerificationFailed
from doc_redact.ingest import PageRaster
from doc_redact.models import Box, OCRToken
from doc_redact.pipeline import RedactionPipeline
from doc_redact.patterns import PatternDefinition
from doc_redact.recognizers import CRN_ENTITY, DetectionService
from doc_redact.verify import verify_output_pdf

from conftest import SYNTHETIC_CRN_SPACED


def safe_image_pdf(path: Path, *, pages: int = 1) -> None:
    rasters = [
        PageRaster(Image.new("RGB", (80, 60), "white"), 80.0, 60.0)
        for _ in range(pages)
    ]
    try:
        RedactionPipeline._write_image_only_pdf(rasters, path)
    finally:
        for raster in rasters:
            raster.image.close()


def test_safe_image_only_pdf_passes_all_structural_checks(tmp_path: Path) -> None:
    output = tmp_path / "safe.pdf"
    safe_image_pdf(output, pages=2)

    checks = verify_output_pdf(output, set(), expected_pages=2)

    assert checks
    assert all(checks.values())


def test_page_count_mismatch_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "safe.pdf"
    safe_image_pdf(output)

    with pytest.raises(VerificationFailed, match="page_count_matches"):
        verify_output_pdf(output, set(), expected_pages=2)


@pytest.mark.parametrize(
    "catalog_key",
    ["/OpenAction", "/AA", "/AcroForm", "/OCProperties"],
)
def test_active_or_hidden_catalog_structures_fail_closed(
    tmp_path: Path, catalog_key: str
) -> None:
    clean = tmp_path / "clean.pdf"
    unsafe = tmp_path / "unsafe.pdf"
    safe_image_pdf(clean)
    reader = PdfReader(clean)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.root_object[NameObject(catalog_key)] = DictionaryObject(
        {
            NameObject("/S"): NameObject("/JavaScript"),
            NameObject("/JS"): TextStringObject("synthetic action"),
        }
    )
    with unsafe.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(VerificationFailed):
        verify_output_pdf(unsafe, set(), expected_pages=1)


def test_annotation_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "annotated.pdf"
    safe_image_pdf(output)
    document = fitz.open(output)
    document[0].add_text_annot((5, 5), "synthetic annotation").update()
    document.save(tmp_path / "saved.pdf")
    document.close()

    with pytest.raises(VerificationFailed):
        verify_output_pdf(tmp_path / "saved.pdf", set(), expected_pages=1)


def test_embedded_file_fails_closed(tmp_path: Path) -> None:
    clean = tmp_path / "clean.pdf"
    unsafe = tmp_path / "unsafe.pdf"
    safe_image_pdf(clean)
    writer = PdfWriter(clone_from=clean)
    writer.add_attachment("synthetic.txt", b"synthetic attachment")
    with unsafe.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(VerificationFailed):
        verify_output_pdf(unsafe, set(), expected_pages=1)


def test_reocr_rediscovery_of_required_entity_fails_closed(
    tmp_path: Path, lightweight_settings
) -> None:
    output = tmp_path / "safe.pdf"
    safe_image_pdf(output)
    tokens = [
        OCRToken("CRN", Box(1, 1, 10, 8)),
        OCRToken(SYNTHETIC_CRN_SPACED, Box(12, 1, 65, 8)),
    ]
    detector = DetectionService(lightweight_settings)

    with pytest.raises(VerificationFailed, match="ocr_targets_absent"):
        verify_output_pdf(
            output,
            {CRN_ENTITY},
            ocr_callback=lambda image, page: tokens,
            redetect_callback=lambda values: detector.detect(values)[1],
            expected_pages=1,
        )


def test_reocr_rediscovery_of_custom_pattern_fails_closed(
    tmp_path: Path, lightweight_settings
) -> None:
    output = tmp_path / "safe.pdf"
    safe_image_pdf(output)
    definition = PatternDefinition(
        identifier="SYNTH_CASE_ID",
        name="Synthetic case ID",
        regex=r"CASE-[0-9]{4}",
        context_terms=["reference"],
        confidence=0.7,
        enabled=True,
        output_label="Synthetic case identifier",
    )
    detector = DetectionService(lightweight_settings, [definition])
    tokens = [
        OCRToken("reference", Box(1, 1, 25, 8)),
        OCRToken("CASE-1234", Box(28, 1, 70, 8)),
    ]

    with pytest.raises(VerificationFailed, match="ocr_targets_absent"):
        verify_output_pdf(
            output,
            {"SYNTH_CASE_ID"},
            ocr_callback=lambda image, page: tokens,
            redetect_callback=lambda values: detector.detect(values)[1],
            expected_pages=1,
        )


def test_reocr_exception_and_timeout_fail_closed(tmp_path: Path) -> None:
    output = tmp_path / "safe.pdf"
    safe_image_pdf(output)

    with pytest.raises(VerificationFailed, match="safely verified"):
        verify_output_pdf(
            output,
            set(),
            ocr_callback=lambda image, page: (_ for _ in ()).throw(
                RuntimeError("synthetic OCR failure")
            ),
            redetect_callback=lambda tokens: [],
            expected_pages=1,
        )

    with pytest.raises(VerificationFailed, match="timed out"):
        verify_output_pdf(
            output,
            set(),
            ocr_callback=lambda image, page: [],
            redetect_callback=lambda tokens: [],
            expected_pages=1,
            deadline=time.monotonic() - 1,
        )


def test_source_text_pdf_is_not_mistaken_for_image_only(tmp_path: Path) -> None:
    output = tmp_path / "text.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 40), f"Synthetic CRN {SYNTHETIC_CRN_SPACED}")
    document.save(output)
    document.close()

    with pytest.raises(VerificationFailed):
        verify_output_pdf(output, {CRN_ENTITY}, expected_pages=1)
