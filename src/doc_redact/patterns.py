from __future__ import annotations

import re
from typing import Annotated

import regex
from presidio_analyzer import EntityRecognizer, RecognizerResult
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import Settings
from .errors import ProcessingFailed
from .models import Detection

PROTECTED_ENTITY = "AU_CENTRELINK_CRN"
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_UNSAFE_REGEX = (
    re.compile(r"\\[1-9]"),  # backreferences
    re.compile(r"\(\?<[=!].*?\)"),  # lookbehind
    re.compile(r"\(\?R\)|\(\?0\)"),  # recursion
    re.compile(r"\([^)]*[+*][^)]*\)[+*{]"),  # obvious nested repetition
    re.compile(r"(?:\.\*|\.\+){2,}"),  # repeated broad wildcard
)


class PatternDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    identifier: str
    name: str
    regex: str
    context_terms: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=20
    )
    confidence: float = Field(default=0.6, ge=0.1, le=1.0)
    enabled: bool = True
    output_label: str = Field(min_length=1, max_length=64)

    @field_validator("identifier")
    @classmethod
    def valid_identifier(cls, value: str) -> str:
        if not _NAME_RE.fullmatch(value):
            raise ValueError("use letters, numbers, underscore or hyphen; start with a letter")
        if value.casefold() == PROTECTED_ENTITY.casefold():
            raise ValueError("the built-in AU_CENTRELINK_CRN recognizer is protected")
        return value

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value or len(value) > 64:
            raise ValueError("name must contain between 1 and 64 characters")
        if value.casefold() == PROTECTED_ENTITY.casefold():
            raise ValueError("the built-in AU_CENTRELINK_CRN recognizer is protected")
        return value

    @field_validator("context_terms")
    @classmethod
    def valid_context_terms(cls, value: list[str]) -> list[str]:
        cleaned = [term.strip() for term in value]
        if any(not term for term in cleaned):
            raise ValueError("context terms cannot be blank")
        if len({term.casefold() for term in cleaned}) != len(cleaned):
            raise ValueError("context terms must be unique")
        return cleaned

    @field_validator("regex")
    @classmethod
    def safe_regex(cls, value: str) -> str:
        # The schema enforces the absolute ceiling. PatternStore applies the
        # effective per-app setting before mutation.
        if len(value) > 1024:
            raise ValueError("regex exceeds the absolute 1024-character limit")
        if any(check.search(value) for check in _UNSAFE_REGEX):
            raise ValueError("regex uses a construct disallowed by the safe pattern policy")
        try:
            regex.compile(value, regex.VERSION1)
        except regex.error as exc:
            raise ValueError("regex is invalid") from exc
        return value


def detect_patterns(
    text: str, definitions: list[PatternDefinition], settings: Settings
) -> list[Detection]:
    bounded = text[: settings.max_ocr_characters]
    detections: list[Detection] = []
    for definition in definitions[: settings.max_patterns]:
        if not definition.enabled:
            continue
        compiled = regex.compile(definition.regex, regex.VERSION1 | regex.IGNORECASE)
        try:
            matches = compiled.finditer(
                bounded,
                timeout=settings.regex_timeout_seconds,
                concurrent=True,
            )
            for match in matches:
                window = bounded[max(0, match.start() - 80) : min(len(bounded), match.end() + 80)]
                context_hit = any(term.casefold() in window.casefold() for term in definition.context_terms)
                if definition.context_terms and not context_hit:
                    continue
                detections.append(
                    Detection(
                        entity_type=definition.identifier,
                        start=match.start(),
                        end=match.end(),
                        score=min(1.0, definition.confidence + (0.1 if context_hit else 0.0)),
                        normalized_value=match.group(0),
                        display_label=definition.output_label,
                        source="user-pattern",
                    )
                )
        except (TimeoutError, regex.error) as exc:
            raise ProcessingFailed("a configured pattern could not be evaluated safely") from exc
    return detections


class SafeRegexPatternRecognizer(EntityRecognizer):
    """A bounded user pattern adapter registered in the Presidio framework."""

    def __init__(self, definition: PatternDefinition, settings: Settings) -> None:
        self.definition = definition
        self.settings = settings
        super().__init__(
            supported_entities=[definition.identifier],
            supported_language="en",
            name=f"SAFE_USER_PATTERN_{definition.identifier}",
        )

    def load(self) -> None:
        return None

    def detect(self, text: str) -> list[Detection]:
        return detect_patterns(text, [self.definition], self.settings)

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts=None,
    ) -> list[RecognizerResult]:
        if entities and self.definition.identifier not in entities:
            return []
        return [
            RecognizerResult(
                entity_type=detection.entity_type,
                start=detection.start,
                end=detection.end,
                score=detection.score,
                recognition_metadata={
                    RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                    RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                },
            )
            for detection in self.detect(text)
        ]
