from __future__ import annotations

import io
import time
from dataclasses import replace
from pathlib import Path

import fitz
import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    TextStringObject,
)

from doc_redact.errors import InputRejected, ProcessingFailed, VerificationFailed
from doc_redact.models import Box, OCRToken
from doc_redact.ocr import FakeOCREngine
from doc_redact.pipeline import RedactionPipeline
from doc_redact.recognizers import DetectionService

from conftest import (
    SYNTHETIC_CRN_COMPACT,
    SYNTHETIC_CRN_SPACED,
    image_bytes,
    synthetic_pdf_bytes,
)


def split_crn_tokens() -> list[OCRToken]:
    return [
        OCRToken("CRN:", Box(2, 2, 22, 12), line_id=0),
        OCRToken("123", Box(30, 20, 48, 32)),
        OCRToken("456", Box(52, 20, 70, 32)),
        OCRToken("789A", Box(74, 20, 98, 32)),
    ]


def pipeline_for(settings, *, engine=None) -> RedactionPipeline:
    return RedactionPipeline(
        settings,
        engine or FakeOCREngine({0: split_crn_tokens()}),
        DetectionService(settings),
    )


def test_pipeline_redacts_every_split_box_with_padding_and_black_pixels(
    tmp_path: Path, lightweight_settings
) -> None:
    output = tmp_path / "safe.pdf"

    report = pipeline_for(lightweight_settings).process(
        image_bytes("PNG"), "synthetic.png", output
    )

    assert report.detections == 1
    assert report.labels == {"Format-valid Centrelink CRN candidate": 1}
    assert output.is_file()
    assert all(report.verification.values())

    document = fitz.open(output)
    try:
        assert document.page_count == 1
        pixmap = document[0].get_pixmap(colorspace=fitz.csRGB, alpha=False)
        rendered = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        try:
            for box in split_crn_tokens()[1:]:
                padded = box.box.padded(3, rendered.width, rendered.height)
                for point in (
                    (padded.left, padded.top),
                    (padded.right - 1, padded.top),
                    (padded.left, padded.bottom - 1),
                    (padded.right - 1, padded.bottom - 1),
                    (
                        (padded.left + padded.right) // 2,
                        (padded.top + padded.bottom) // 2,
                    ),
                ):
                    assert rendered.getpixel(point) == (0, 0, 0)
            assert rendered.getpixel((110, 70)) == (255, 255, 255)
        finally:
            rendered.close()
    finally:
        document.close()


def _adversarial_pdf() -> bytes:
    base = fitz.open(stream=synthetic_pdf_bytes(text=f"CRN {SYNTHETIC_CRN_SPACED}"), filetype="pdf")
    try:
        base.set_metadata(
            {
                "title": f"Synthetic metadata {SYNTHETIC_CRN_COMPACT}",
                "author": "Synthetic QA",
            }
        )
        annotation = base[0].add_text_annot(
            (10, 10), f"synthetic annotation {SYNTHETIC_CRN_COMPACT}"
        )
        annotation.update()
        base.embfile_add(
            "synthetic.txt",
            f"attachment {SYNTHETIC_CRN_COMPACT}".encode(),
            filename="synthetic.txt",
        )
        enriched = base.tobytes(garbage=4, deflate=True, clean=True)
    finally:
        base.close()

    reader = PdfReader(io.BytesIO(enriched))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    root = writer.root_object
    javascript = DictionaryObject(
        {
            NameObject("/S"): NameObject("/JavaScript"),
            NameObject("/JS"): TextStringObject(
                f"app.alert('{SYNTHETIC_CRN_COMPACT}')"
            ),
        }
    )
    root[NameObject("/OpenAction")] = javascript
    root[NameObject("/AA")] = DictionaryObject({NameObject("/WC"): javascript})
    root[NameObject("/AcroForm")] = DictionaryObject(
        {
            NameObject("/Fields"): ArrayObject(),
            NameObject("/XFA"): TextStringObject(SYNTHETIC_CRN_COMPACT),
        }
    )
    root[NameObject("/OCProperties")] = DictionaryObject(
        {NameObject("/OCGs"): ArrayObject()}
    )
    writer.add_metadata({"/Subject": f"Synthetic {SYNTHETIC_CRN_COMPACT}"})
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_adversarial_pdf_is_rebuilt_without_forbidden_structures_or_target(
    tmp_path: Path, lightweight_settings
) -> None:
    output = tmp_path / "safe.pdf"
    source = _adversarial_pdf()
    assert SYNTHETIC_CRN_COMPACT.encode() in source
    assert b"/OpenAction" in source
    assert b"/EmbeddedFiles" in source

    report = pipeline_for(lightweight_settings).process(
        source, "synthetic.pdf", output
    )

    assert all(report.verification.values())
    raw = output.read_bytes()
    assert SYNTHETIC_CRN_COMPACT.encode() not in raw
    for forbidden in (
        b"/JavaScript",
        b"/OpenAction",
        b"/AA",
        b"/AcroForm",
        b"/XFA",
        b"/OCProperties",
        b"/EmbeddedFiles",
        b"/Filespec",
        b"/Launch",
        b"/URI",
    ):
        assert forbidden not in raw
    assert raw.count(b"%%EOF") == 1
    assert raw.count(b"startxref") == 1

    reader = PdfReader(output, strict=True)
    assert "".join(page.extract_text() or "" for page in reader.pages) == ""
    assert all(not page.get("/Annots") for page in reader.pages)
    assert "/AcroForm" not in reader.trailer["/Root"]
    assert "/Names" not in reader.trailer["/Root"]
    assert SYNTHETIC_CRN_COMPACT not in str(reader.metadata)


def test_verifier_exception_suppresses_and_removes_preexisting_output(
    monkeypatch, tmp_path: Path, lightweight_settings
) -> None:
    output = tmp_path / "safe.pdf"
    output.write_bytes(b"stale output must disappear")

    def fail(*args, **kwargs):
        raise VerificationFailed("synthetic verifier exception")

    monkeypatch.setattr("doc_redact.pipeline.verify_output_pdf", fail)

    with pytest.raises(VerificationFailed):
        pipeline_for(lightweight_settings).process(
            image_bytes("PNG"), "synthetic.png", output
        )
    assert not output.exists()


def test_indeterminate_verifier_result_is_not_published(
    monkeypatch, tmp_path: Path, lightweight_settings
) -> None:
    output = tmp_path / "safe.pdf"
    monkeypatch.setattr(
        "doc_redact.pipeline.verify_output_pdf",
        lambda *args, **kwargs: {"image_only": True, "indeterminate": False},
    )

    with pytest.raises((ProcessingFailed, VerificationFailed)):
        pipeline_for(lightweight_settings).process(
            image_bytes("PNG"), "synthetic.png", output
        )
    assert not output.exists()


def test_invalid_input_removes_preexisting_output(
    tmp_path: Path, lightweight_settings
) -> None:
    output = tmp_path / "safe.pdf"
    output.write_bytes(b"stale output must disappear")

    with pytest.raises(InputRejected):
        pipeline_for(lightweight_settings).process(b"bad", "synthetic.png", output)
    assert not output.exists()


def test_processing_deadline_fails_closed_after_slow_ocr(
    tmp_path: Path, lightweight_settings
) -> None:
    settings = replace(lightweight_settings, processing_timeout_seconds=0.001)

    def slow_ocr(image, page_index):
        time.sleep(0.01)
        return split_crn_tokens()

    output = tmp_path / "safe.pdf"
    with pytest.raises(ProcessingFailed, match="timed out"):
        pipeline_for(settings, engine=FakeOCREngine(callback=slow_ocr)).process(
            image_bytes("PNG"), "synthetic.png", output
        )
    assert not output.exists()


def test_multi_frame_tiff_preserves_page_order_and_dimensions(
    tmp_path: Path, lightweight_settings
) -> None:
    first = Image.new("RGB", (120, 80), "white")
    second = Image.new("RGB", (120, 80), (180, 180, 180))
    stream = io.BytesIO()
    first.save(
        stream,
        format="TIFF",
        save_all=True,
        append_images=[second],
        compression="tiff_deflate",
    )
    first.close()
    second.close()
    engine = FakeOCREngine({0: split_crn_tokens(), 1: split_crn_tokens()})
    output = tmp_path / "multi.pdf"

    report = pipeline_for(lightweight_settings, engine=engine).process(
        stream.getvalue(), "synthetic.tiff", output
    )

    assert report.source_pages == 2
    assert report.detections == 2
    document = fitz.open(output)
    try:
        assert document.page_count == 2
        assert [(page.rect.width, page.rect.height) for page in document] == [
            (120.0, 80.0),
            (120.0, 80.0),
        ]
        colors = []
        for page in document:
            pixmap = page.get_pixmap(colorspace=fitz.csRGB, alpha=False)
            rendered = Image.frombytes(
                "RGB", (pixmap.width, pixmap.height), pixmap.samples
            )
            colors.append(rendered.getpixel((110, 70)))
            rendered.close()
        assert colors == [(255, 255, 255), (180, 180, 180)]
    finally:
        document.close()


def test_invalid_ocr_token_geometry_suppresses_output(
    tmp_path: Path, lightweight_settings
) -> None:
    engine = FakeOCREngine(
        {
            0: [
                OCRToken(
                    "synthetic",
                    Box(20, 20, 10, 30),
                    confidence=1.0,
                )
            ]
        }
    )
    output = tmp_path / "safe.pdf"

    with pytest.raises(ProcessingFailed, match="bounding-box"):
        pipeline_for(lightweight_settings, engine=engine).process(
            image_bytes("PNG"), "synthetic.png", output
        )
    assert not output.exists()


@pytest.mark.parametrize("verifier_fails", [False, True])
def test_private_pipeline_temp_directory_is_removed_on_all_paths(
    monkeypatch, tmp_path: Path, lightweight_settings, verifier_fails: bool
) -> None:
    import tempfile

    actual = tempfile.TemporaryDirectory
    observed: list[Path] = []

    class TrackingTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            self.inner = actual(*args, **kwargs)

        def __enter__(self):
            name = self.inner.__enter__()
            observed.append(Path(name))
            assert observed[-1].stat().st_mode & 0o077 == 0
            return name

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

    monkeypatch.setattr(
        "doc_redact.pipeline.tempfile.TemporaryDirectory",
        TrackingTemporaryDirectory,
    )
    if verifier_fails:
        monkeypatch.setattr(
            "doc_redact.pipeline.verify_output_pdf",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                VerificationFailed("synthetic verifier failure")
            ),
        )

    output = tmp_path / "safe.pdf"
    if verifier_fails:
        with pytest.raises(VerificationFailed):
            pipeline_for(lightweight_settings).process(
                image_bytes("PNG"), "synthetic.png", output
            )
    else:
        pipeline_for(lightweight_settings).process(
            image_bytes("PNG"), "synthetic.png", output
        )

    assert observed
    assert all(not path.exists() for path in observed)
