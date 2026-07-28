from __future__ import annotations

from collections.abc import Callable
import math
import threading
from typing import Any, Protocol

from PIL import Image

from .models import Box, OCRToken
from .errors import ProcessingFailed


class OCREngine(Protocol):
    name: str

    def recognize(self, image: Image.Image, page_index: int) -> list[OCRToken]: ...


class FakeOCREngine:
    """Lightweight deterministic adapter for CI; scripted tokens are synthetic."""

    name = "fake-ci"

    def __init__(
        self,
        pages: dict[int, list[OCRToken]] | None = None,
        callback: Callable[[Image.Image, int], list[OCRToken]] | None = None,
    ) -> None:
        self.pages = pages or {}
        self.callback = callback

    def recognize(self, image: Image.Image, page_index: int) -> list[OCRToken]:
        if self.callback:
            return self.callback(image, page_index)
        return list(self.pages.get(page_index, []))


class PaddleOCRV5Engine:
    """PP-OCRv5 adapter. Model inference is local after model acquisition."""

    name = "paddle-pp-ocrv5"

    def __init__(self) -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "PP-OCRv5 is unavailable; install the 'ocr' optional dependencies"
            ) from exc
        self._ocr = PaddleOCR(
            ocr_version="PP-OCRv5",
            lang="en",
            use_doc_orientation_classify=True,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )
        # Paddle predictor thread safety is not part of the adapter contract.
        # Serialize access to the shared model instance across request workers.
        self._predict_lock = threading.Lock()

    def recognize(self, image: Image.Image, page_index: int) -> list[OCRToken]:
        # PaddleOCR accepts a numpy array; the import stays here to keep CI lightweight.
        import numpy

        with self._predict_lock:
            raw_results = self._ocr.predict(numpy.asarray(image.convert("RGB")))
            if raw_results is None:
                raise ProcessingFailed("OCR returned an invalid result")
            try:
                result_items = list(raw_results)
            except TypeError as exc:
                raise ProcessingFailed("OCR returned an invalid result") from exc
            if not result_items:
                raise ProcessingFailed("OCR returned an invalid result")
        tokens: list[OCRToken] = []
        for raw in result_items:
            payload = self._payload(raw)
            texts = payload.get("rec_texts")
            scores = payload.get("rec_scores")
            polygons = payload.get("dt_polys", payload.get("rec_polys"))
            if (
                not isinstance(texts, (list, tuple))
                or not isinstance(scores, (list, tuple))
                or not isinstance(polygons, (list, tuple))
                or not (len(texts) == len(scores) == len(polygons))
            ):
                raise ProcessingFailed("OCR returned an invalid result")
            for text, score, polygon in zip(texts, scores, polygons, strict=True):
                if not text or float(score) < 0.20:
                    continue
                try:
                    xs = [float(point[0]) for point in polygon]
                    ys = [float(point[1]) for point in polygon]
                except (TypeError, ValueError, IndexError) as exc:
                    raise ProcessingFailed("OCR returned invalid bounding-box geometry") from exc
                if (
                    len(xs) < 4
                    or len(ys) < 4
                    or not all(math.isfinite(value) for value in xs + ys)
                ):
                    raise ProcessingFailed("OCR returned invalid bounding-box geometry")
                left = max(0, min(image.width, int(min(xs))))
                top = max(0, min(image.height, int(min(ys))))
                right = max(0, min(image.width, int(max(xs) + 1)))
                bottom = max(0, min(image.height, int(max(ys) + 1)))
                if right <= left or bottom <= top or not math.isfinite(float(score)):
                    raise ProcessingFailed("OCR returned an unusable token")
                tokens.append(
                    OCRToken(
                        text=str(text),
                        confidence=float(score),
                        box=Box(
                            left=left,
                            top=top,
                            right=right,
                            bottom=bottom,
                        ),
                        # PP-OCR's flat result does not expose stable line ids.
                        # Reading order is kept contiguous; boxes remain separate.
                        line_id=None,
                        page_index=page_index,
                    )
                )
        return tokens

    @staticmethod
    def _payload(raw: Any) -> dict[str, Any]:
        value = getattr(raw, "json", raw)
        if callable(value):
            value = value()
        if isinstance(value, dict) and "res" in value:
            value = value["res"]
        if not isinstance(value, dict):
            raise ProcessingFailed("OCR returned an invalid result")
        return value


def make_ocr_engine(backend: str) -> OCREngine:
    if backend == "fake":
        return FakeOCREngine()
    if backend != "paddle":
        raise ValueError("DOC_REDACT_OCR_BACKEND must be 'paddle' or 'fake'")
    return PaddleOCRV5Engine()
