from __future__ import annotations

import pytest
from pydantic import ValidationError

from doc_redact.errors import ProcessingFailed
from doc_redact.patterns import PatternDefinition, detect_patterns


def pattern(**overrides) -> PatternDefinition:
    values = {
        "identifier": "SYNTH_CASE_ID",
        "name": "Synthetic case ID",
        "regex": r"CASE-[0-9]{4}",
        "context_terms": ["reference"],
        "confidence": 0.7,
        "enabled": True,
        "output_label": "Synthetic case identifier",
    }
    values.update(overrides)
    return PatternDefinition.model_validate(values)


def test_pattern_schema_and_context(lightweight_settings) -> None:
    definition = pattern()

    found = detect_patterns(
        "case reference CASE-1234", [definition], lightweight_settings
    )
    absent = detect_patterns("inventory CASE-1234", [definition], lightweight_settings)

    assert len(found) == 1
    assert found[0].entity_type == "SYNTH_CASE_ID"
    assert found[0].display_label == "Synthetic case identifier"
    assert found[0].score == pytest.approx(0.8)
    assert absent == []


def test_disabled_pattern_does_not_detect(lightweight_settings) -> None:
    assert (
        detect_patterns(
            "case CASE-1234", [pattern(enabled=False)], lightweight_settings
        )
        == []
    )


@pytest.mark.parametrize("field", ["identifier", "name"])
def test_builtin_cannot_be_shadowed(field: str) -> None:
    with pytest.raises(ValidationError, match="protected"):
        pattern(**{field: "AU_CENTRELINK_CRN"})


@pytest.mark.parametrize(
    "unsafe",
    [
        r"(a+)+$",
        r"(.*)+$",
        r"(a*){2,}",
        r"(foo)\1",
        r"(?<=secret)[0-9]+",
        r"(?R)",
        r".*.*secret",
    ],
)
def test_unsafe_regex_constructs_are_rejected(unsafe: str) -> None:
    with pytest.raises(ValidationError, match="disallowed"):
        pattern(regex=unsafe)


def test_unknown_keys_and_schema_bounds_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PatternDefinition.model_validate(
            {
                **pattern().model_dump(),
                "unknown": "not accepted",
            }
        )
    with pytest.raises(ValidationError):
        pattern(confidence=0.0)
    with pytest.raises(ValidationError):
        pattern(context_terms=["x"] * 21)
    with pytest.raises(ValidationError):
        pattern(output_label="x" * 65)


def test_pattern_count_and_input_text_are_bounded(lightweight_settings) -> None:
    definitions = [
        pattern(
            identifier=f"PATTERN_{index}",
            name=f"Pattern {index}",
            regex=rf"ID{index}",
            context_terms=[],
        )
        for index in range(8)
    ]
    settings = lightweight_settings.__class__(
        **{
            **{
                field: getattr(lightweight_settings, field)
                for field in lightweight_settings.__dataclass_fields__
            },
            "max_patterns": 2,
            "max_ocr_characters": 10,
        }
    )

    result = detect_patterns("ID0 ID1 xx ID2", definitions, settings)

    assert [item.entity_type for item in result] == ["PATTERN_0", "PATTERN_1"]


def test_regex_timeout_fails_closed(monkeypatch, lightweight_settings) -> None:
    class TimedOut:
        def finditer(self, *args, **kwargs):
            raise TimeoutError

    monkeypatch.setattr("doc_redact.patterns.regex.compile", lambda *args, **kwargs: TimedOut())

    with pytest.raises(ProcessingFailed, match="evaluated safely"):
        detect_patterns("case CASE-1234", [pattern()], lightweight_settings)
