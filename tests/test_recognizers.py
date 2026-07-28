from __future__ import annotations

import pytest

from doc_redact.models import Box, OCRToken
from doc_redact.recognizers import (
    CRN_ENTITY,
    DetectionService,
    build_ocr_text,
    detect_crn_candidates,
)

from conftest import SYNTHETIC_CRN_COMPACT, SYNTHETIC_CRN_SPACED


@pytest.mark.parametrize(
    ("text", "normalized"),
    [
        (f"CRN: {SYNTHETIC_CRN_SPACED}.", SYNTHETIC_CRN_COMPACT),
        (f"Centrelink reference {SYNTHETIC_CRN_COMPACT}", SYNTHETIC_CRN_COMPACT),
        ("Customer reference 123\u00a0456\u00a0789A", SYNTHETIC_CRN_COMPACT),
        ("Customer ref 123 456\n789 A", SYNTHETIC_CRN_COMPACT),
    ],
)
def test_crn_positive_variants_are_format_candidates(text: str, normalized: str) -> None:
    result = detect_crn_candidates(text)

    assert len(result) == 1
    assert result[0].entity_type == CRN_ENTITY
    assert result[0].normalized_value == normalized
    assert "format-valid" in result[0].display_label.casefold()
    assert "verified" not in result[0].display_label.casefold()


@pytest.mark.parametrize(
    "text",
    [
        f"Inventory code {SYNTHETIC_CRN_COMPACT}",  # ambiguous compact form, no context
        "CRN 12345678A",  # eight digits
        "CRN 1234567890A",  # ten digits
        "CRN 123456789Å",  # non-ASCII letter
        "CRN X123456789A",  # embedded in another identifier
        "CRN 123456789AB",  # two trailing letters
    ],
)
def test_crn_false_positives_are_suppressed(text: str) -> None:
    assert detect_crn_candidates(text) == []


def test_split_tokens_and_lines_map_every_contributing_box(lightweight_settings) -> None:
    tokens = [
        OCRToken("CRN:", Box(2, 2, 25, 12), line_id=0),
        OCRToken("123", Box(30, 2, 55, 12), line_id=0),
        OCRToken("456", Box(60, 2, 85, 12), line_id=0),
        OCRToken("789", Box(30, 16, 55, 26), line_id=1),
        OCRToken("A", Box(58, 16, 66, 26), line_id=1),
        OCRToken("unrelated", Box(70, 16, 115, 26), line_id=1),
    ]

    text, spans = build_ocr_text(tokens)
    assert text == "CRN: 123 456\n789 A unrelated"
    _, mapped = DetectionService(lightweight_settings).detect(tokens)

    assert len(mapped) == 1
    assert mapped[0].detection.normalized_value == SYNTHETIC_CRN_COMPACT
    assert mapped[0].boxes == (
        Box(30, 2, 85, 12),
        Box(30, 16, 66, 26),
    )
    assert all("unrelated" not in text[start:end] for start, end, _ in spans[:-1])


def test_tokens_without_line_ids_remain_separate_boxes(lightweight_settings) -> None:
    tokens = [
        OCRToken("CRN", Box(0, 0, 20, 10)),
        OCRToken("123", Box(25, 0, 45, 10)),
        OCRToken("456", Box(50, 0, 70, 10)),
        OCRToken("789A", Box(75, 0, 105, 10)),
    ]

    _, mapped = DetectionService(lightweight_settings).detect(tokens)

    assert len(mapped) == 1
    assert mapped[0].boxes == (
        Box(25, 0, 45, 10),
        Box(50, 0, 70, 10),
        Box(75, 0, 105, 10),
    )


def test_detection_service_registers_protected_presidio_recognizer(
    lightweight_settings,
) -> None:
    service = DetectionService(lightweight_settings)

    registered = service.registry.get_recognizers(
        language="en", entities=[CRN_ENTITY], all_fields=True
    )
    assert any(recognizer.name == CRN_ENTITY for recognizer in registered)
