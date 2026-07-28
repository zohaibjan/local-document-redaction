from __future__ import annotations

import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from doc_redact.errors import ProcessingFailed
from doc_redact.ocr import PaddleOCRV5Engine, make_ocr_engine
from doc_redact.recognizers import DetectionService, LocalGlinerRecognizer


def test_paddle_adapter_explicitly_selects_v5_and_orientation(
    monkeypatch,
) -> None:
    observed = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            observed.update(kwargs)

        def predict(self, array):
            return [
                {
                    "res": {
                        "rec_texts": ["synthetic"],
                        "rec_scores": [0.98],
                        "dt_polys": [
                            [[1.2, 2.1], [20.4, 2.0], [20.1, 10.4], [1.0, 10.0]]
                        ],
                    }
                }
            ]

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", module)

    engine = PaddleOCRV5Engine()
    tokens = engine.recognize(Image.new("RGB", (30, 20), "white"), 3)

    assert observed == {
        "ocr_version": "PP-OCRv5",
        "lang": "en",
        "use_doc_orientation_classify": True,
        "use_doc_unwarping": False,
        "use_textline_orientation": True,
    }
    assert len(tokens) == 1
    assert tokens[0].text == "synthetic"
    assert tokens[0].confidence == pytest.approx(0.98)
    assert tokens[0].page_index == 3
    assert (tokens[0].box.left, tokens[0].box.top) == (1, 2)
    assert (tokens[0].box.right, tokens[0].box.bottom) == (21, 11)


def test_paddle_adapter_rejects_invalid_polygon(monkeypatch) -> None:
    class FakePaddleOCR:
        def __init__(self, **kwargs):
            pass

        def predict(self, array):
            return [
                {
                    "res": {
                        "rec_texts": ["synthetic"],
                        "rec_scores": [0.98],
                        "dt_polys": [[[1, 2], [2, 2]]],
                    }
                }
            ]

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", module)

    with pytest.raises(ProcessingFailed, match="bounding-box"):
        PaddleOCRV5Engine().recognize(Image.new("RGB", (30, 20), "white"), 0)


@pytest.mark.parametrize(
    "result",
    [
        [{"unexpected": "shape"}],
        [{"res": {"rec_texts": ["one"], "rec_scores": [], "dt_polys": []}}],
        [{"res": "not-a-mapping"}],
        [],
        None,
    ],
)
def test_paddle_adapter_rejects_malformed_or_mismatched_results(
    monkeypatch, result
) -> None:
    class FakePaddleOCR:
        def __init__(self, **kwargs):
            pass

        def predict(self, array):
            return result

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", module)

    with pytest.raises(ProcessingFailed, match="invalid result"):
        PaddleOCRV5Engine().recognize(Image.new("RGB", (30, 20), "white"), 0)


def test_paddle_adapter_accepts_explicit_valid_empty_result(monkeypatch) -> None:
    class FakePaddleOCR:
        def __init__(self, **kwargs):
            pass

        def predict(self, array):
            return [{"res": {"rec_texts": [], "rec_scores": [], "dt_polys": []}}]

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", module)

    assert (
        PaddleOCRV5Engine().recognize(Image.new("RGB", (30, 20), "white"), 0)
        == []
    )


def test_shared_paddle_predictor_calls_are_serialized(monkeypatch) -> None:
    active = 0
    maximum_active = 0
    state_lock = threading.Lock()

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            pass

        def predict(self, array):
            nonlocal active, maximum_active
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.02)
            with state_lock:
                active -= 1
            return [{"res": {"rec_texts": [], "rec_scores": [], "dt_polys": []}}]

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", module)
    engine = PaddleOCRV5Engine()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda page: engine.recognize(
                    Image.new("RGB", (30, 20), "white"),
                    page,
                ),
                [0, 1],
            )
        )

    assert results == [[], []]
    assert maximum_active == 1


def test_gliner_is_local_optional_presidio_recognizer(
    monkeypatch, lightweight_settings
) -> None:
    observed = {}

    class FakeModel:
        def predict_entities(self, text, labels, threshold):
            return [
                {
                    "label": "person",
                    "start": 0,
                    "end": 9,
                    "score": 0.91,
                }
            ]

    class FakeGLiNER:
        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            observed["model_name"] = model_name
            observed.update(kwargs)
            return FakeModel()

    module = types.ModuleType("gliner")
    module.GLiNER = FakeGLiNER
    monkeypatch.setitem(sys.modules, "gliner", module)

    recognizer = LocalGlinerRecognizer("synthetic/local-model")
    service = DetectionService(
        lightweight_settings, semantic_recognizer=recognizer
    )
    registered = service.registry.get_recognizers(
        language="en", entities=["GLINER_PERSON"], all_fields=True
    )
    detections = recognizer.detect("Synthetic")

    assert observed == {
        "model_name": "synthetic/local-model",
        "local_files_only": True,
    }
    assert any(item.name == "LOCAL_GLINER_PRESIDIO" for item in registered)
    assert detections[0].entity_type == "GLINER_PERSON"
    assert all(item.entity_type != "AU_CENTRELINK_CRN" for item in detections)


def test_fake_backend_does_not_require_heavy_models() -> None:
    engine = make_ocr_engine("fake")
    assert engine.name == "fake-ci"
    assert engine.recognize(Image.new("RGB", (5, 5), "white"), 0) == []


def test_unknown_ocr_backend_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be 'paddle' or 'fake'"):
        make_ocr_engine("remote")
