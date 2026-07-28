from __future__ import annotations

import io
import math
import os
import tempfile
import time
from collections import Counter
from pathlib import Path

import fitz
from PIL import ImageDraw

from .config import Settings
from .errors import ProcessingFailed, VerificationFailed
from .ingest import PageRaster, render_pages, validate_input
from .models import Box, OCRToken, ProcessingReport
from .ocr import OCREngine
from .recognizers import DetectionService
from .verify import verify_output_pdf


class RedactionPipeline:
    def __init__(
        self,
        settings: Settings,
        ocr_engine: OCREngine,
        detector: DetectionService,
    ) -> None:
        self.settings = settings
        self.ocr_engine = ocr_engine
        self.detector = detector

    def process(self, data: bytes, filename: str, output_path: Path) -> ProcessingReport:
        output_path.unlink(missing_ok=True)
        deadline = time.monotonic() + self.settings.processing_timeout_seconds
        source = validate_input(data, filename, self.settings)
        labels: Counter[str] = Counter()
        required_entities: set[str] = set()
        detections_count = 0

        with tempfile.TemporaryDirectory(prefix="doc-redact-") as temp_name:
            workdir = Path(temp_name)
            pages = render_pages(source, workdir, self.settings)
            self._check_deadline(deadline)
            if not pages:
                raise ProcessingFailed("document contains no renderable pages")

            staged_output = workdir / "verified-output.pdf"
            try:
                for page_index, page_raster in enumerate(pages):
                    self._check_deadline(deadline)
                    image = page_raster.image
                    tokens = self._validated_tokens(
                        self.ocr_engine.recognize(image, page_index),
                        image.width,
                        image.height,
                        page_index,
                    )
                    _, detections = self.detector.detect(tokens)
                    self._check_deadline(deadline)
                    draw = ImageDraw.Draw(image)
                    for mapped in detections:
                        detections_count += 1
                        labels[mapped.detection.display_label] += 1
                        required_entities.add(mapped.detection.entity_type)
                        for box in mapped.boxes:
                            padded = box.padded(
                                self.settings.redaction_padding_px,
                                image.width,
                                image.height,
                            )
                            draw.rectangle(
                                (padded.left, padded.top, padded.right, padded.bottom),
                                fill=(0, 0, 0),
                            )
                self._write_image_only_pdf(pages, staged_output)
                checks = verify_output_pdf(
                    staged_output,
                    required_entities,
                    ocr_callback=(
                        self.ocr_engine.recognize if self.settings.verify_with_ocr else None
                    ),
                    redetect_callback=lambda tokens: self.detector.detect(tokens)[1],
                    expected_pages=len(pages),
                    deadline=deadline,
                    ocr_dpi=self.settings.render_dpi,
                )
                if not checks or not all(value is True for value in checks.values()):
                    raise VerificationFailed("output verification was indeterminate")
                self._check_deadline(deadline)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_output, output_path)
            finally:
                for page in pages:
                    page.image.close()

        return ProcessingReport(
            output_path=output_path,
            source_pages=len(pages),
            detections=detections_count,
            labels=dict(labels),
            verification=checks,
        )

    @staticmethod
    def _check_deadline(deadline: float) -> None:
        if time.monotonic() > deadline:
            raise ProcessingFailed("document processing timed out")

    @staticmethod
    def _validated_tokens(
        tokens: list[OCRToken], width: int, height: int, page_index: int
    ) -> list[OCRToken]:
        validated: list[OCRToken] = []
        for token in tokens:
            if (
                not token.text
                or not math.isfinite(float(token.confidence))
                or token.confidence < 0
                or token.confidence > 1
            ):
                raise ProcessingFailed("OCR returned an invalid token")
            box = Box(
                max(0, min(width, int(token.box.left))),
                max(0, min(height, int(token.box.top))),
                max(0, min(width, int(token.box.right))),
                max(0, min(height, int(token.box.bottom))),
            )
            if box.right <= box.left or box.bottom <= box.top:
                raise ProcessingFailed("OCR returned invalid bounding-box geometry")
            validated.append(
                OCRToken(
                    token.text,
                    box,
                    float(token.confidence),
                    token.line_id,
                    page_index,
                )
            )
        return validated

    @staticmethod
    def _write_image_only_pdf(pages: list[PageRaster], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document = fitz.open()
        try:
            for page_raster in pages:
                image = page_raster.image
                buffer = io.BytesIO()
                image.save(buffer, format="PNG", optimize=True)
                page = document.new_page(
                    width=page_raster.width_points,
                    height=page_raster.height_points,
                )
                page.insert_image(page.rect, stream=buffer.getvalue())
            document.set_metadata({})
            document.save(
                str(output_path),
                garbage=4,
                deflate=True,
                clean=True,
                encryption=fitz.PDF_ENCRYPT_NONE,
            )
        except Exception as exc:
            raise ProcessingFailed("could not create the safe image-only PDF") from exc
        finally:
            document.close()
