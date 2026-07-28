from __future__ import annotations

import re
from collections.abc import Iterable

from presidio_analyzer import EntityRecognizer, RecognizerRegistry, RecognizerResult

from .models import Box, Detection, MappedDetection, OCRToken
from .patterns import PatternDefinition, SafeRegexPatternRecognizer
from .config import Settings

CRN_ENTITY = "AU_CENTRELINK_CRN"
CRN_LABEL = "Format-valid Centrelink CRN candidate"
_CRN_RE = re.compile(
    r"(?<![A-Za-z0-9])\d(?:[ \u00a0\n]?\d){8}[ \u00a0\n]?[A-Za-z](?![A-Za-z0-9])"
)
_CRN_CONTEXT = (
    "crn",
    "customer reference",
    "customer ref",
    "centrelink",
    "services australia",
)


def normalize_crn(value: str) -> str:
    return "".join(value.split()).upper()


def _crn_score(text: str, start: int, end: int) -> float:
    candidate = text[start:end]
    nearby = text[max(0, start - 100) : min(len(text), end + 100)].casefold()
    has_context = any(term in nearby for term in _CRN_CONTEXT)
    has_grouping = any(char.isspace() for char in candidate)
    # Unspaced ten-character identifiers are too ambiguous without context.
    return min(1.0, 0.55 + (0.25 if has_context else 0.0) + (0.10 if has_grouping else 0.0))


def detect_crn_candidates(text: str, *, minimum_score: float = 0.65) -> list[Detection]:
    detections: list[Detection] = []
    for match in _CRN_RE.finditer(text):
        if match.group(0).count("\n") > 1:
            continue
        normalized = normalize_crn(match.group(0))
        if len(normalized) != 10 or not normalized[:9].isdigit() or not normalized[-1].isalpha():
            continue
        score = _crn_score(text, match.start(), match.end())
        if score < minimum_score:
            continue
        detections.append(
            Detection(
                entity_type=CRN_ENTITY,
                start=match.start(),
                end=match.end(),
                score=score,
                normalized_value=normalized,
                display_label=CRN_LABEL,
                source="deterministic-presidio",
            )
        )
    return detections


class CentrelinkCrnRecognizer(EntityRecognizer):
    """Protected deterministic Presidio recognizer for format-valid candidates."""

    def __init__(self) -> None:
        super().__init__(supported_entities=[CRN_ENTITY], supported_language="en", name=CRN_ENTITY)

    def load(self) -> None:
        return None

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts=None,
    ) -> list[RecognizerResult]:
        if entities and CRN_ENTITY not in entities:
            return []
        return [
            RecognizerResult(
                entity_type=CRN_ENTITY,
                start=detection.start,
                end=detection.end,
                score=detection.score,
                recognition_metadata={
                    RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                    RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                },
            )
            for detection in detect_crn_candidates(text)
        ]


def build_ocr_text(tokens: Iterable[OCRToken]) -> tuple[str, list[tuple[int, int, OCRToken]]]:
    pieces: list[str] = []
    spans: list[tuple[int, int, OCRToken]] = []
    cursor = 0
    previous_line: int | None = None
    for token in tokens:
        if pieces:
            separator = "\n" if (
                previous_line is not None
                and token.line_id is not None
                and token.line_id != previous_line
            ) else " "
            pieces.append(separator)
            cursor += len(separator)
        start = cursor
        pieces.append(token.text)
        cursor += len(token.text)
        spans.append((start, cursor, token))
        previous_line = token.line_id
    return "".join(pieces), spans


def map_detection_boxes(
    detection: Detection,
    token_spans: list[tuple[int, int, OCRToken]],
) -> MappedDetection | None:
    relevant = [
        token for start, end, token in token_spans if end > detection.start and start < detection.end
    ]
    if not relevant:
        return None

    grouped: dict[int, Box] = {}
    for index, token in enumerate(relevant):
        key = token.line_id if token.line_id is not None else index
        grouped[key] = grouped[key].union(token.box) if key in grouped else token.box
    return MappedDetection(detection=detection, boxes=tuple(grouped.values()))


class DetectionService:
    def __init__(
        self,
        settings: Settings,
        patterns: list[PatternDefinition] | None = None,
        semantic_recognizer: "SemanticRecognizer | None" = None,
    ) -> None:
        self.settings = settings
        self.patterns = patterns or []
        self.semantic_recognizer = semantic_recognizer
        self.crn_recognizer = CentrelinkCrnRecognizer()
        self.pattern_recognizers = [
            SafeRegexPatternRecognizer(definition, settings)
            for definition in self.patterns
        ]
        self.registry = RecognizerRegistry()
        self.registry.add_recognizer(self.crn_recognizer)
        for recognizer in self.pattern_recognizers:
            self.registry.add_recognizer(recognizer)
        if isinstance(self.semantic_recognizer, EntityRecognizer):
            self.registry.add_recognizer(self.semantic_recognizer)

    def detect(self, tokens: list[OCRToken]) -> tuple[str, list[MappedDetection]]:
        text, spans = build_ocr_text(tokens)
        if len(text) > self.settings.max_ocr_characters:
            text = text[: self.settings.max_ocr_characters]
            spans = [span for span in spans if span[0] < len(text)]

        # The protected primary path is a registered Presidio EntityRecognizer.
        crn_recognizer = self._registered_recognizer(CRN_ENTITY, self.crn_recognizer.name)
        crn_results = crn_recognizer.analyze(text, [CRN_ENTITY])
        detections = [
            Detection(
                entity_type=result.entity_type,
                start=result.start,
                end=result.end,
                score=result.score,
                normalized_value=normalize_crn(text[result.start : result.end]),
                display_label=CRN_LABEL,
                source="deterministic-presidio",
            )
            for result in crn_results
        ]
        for recognizer in self.pattern_recognizers:
            registered = self._registered_recognizer(
                recognizer.definition.identifier,
                recognizer.name,
            )
            for result in registered.analyze(text, [recognizer.definition.identifier]):
                detections.append(
                    Detection(
                        entity_type=result.entity_type,
                        start=result.start,
                        end=result.end,
                        score=result.score,
                        normalized_value=text[result.start : result.end],
                        display_label=recognizer.definition.output_label,
                        source="user-pattern-presidio",
                    )
                )
        if isinstance(self.semantic_recognizer, LocalGlinerRecognizer):
            registered = self._registered_recognizer(
                self.semantic_recognizer._entity_types[0],
                self.semantic_recognizer.name,
            )
            results = registered.analyze(text, self.semantic_recognizer._entity_types)
            detections.extend(self.semantic_recognizer.as_detections(results))
        elif self.semantic_recognizer is not None:
            detections.extend(self.semantic_recognizer.detect(text))

        mapped: list[MappedDetection] = []
        seen: set[tuple[str, int, int]] = set()
        for detection in sorted(detections, key=lambda item: (item.start, -item.score)):
            key = (detection.entity_type, detection.start, detection.end)
            if key in seen:
                continue
            seen.add(key)
            result = map_detection_boxes(detection, spans)
            if result is not None:
                mapped.append(result)
        return text, mapped

    def _registered_recognizer(
        self, entity_type: str, recognizer_name: str
    ) -> EntityRecognizer:
        registered = self.registry.get_recognizers(
            language="en",
            entities=[entity_type],
        )
        for recognizer in registered:
            if recognizer.name == recognizer_name:
                return recognizer
        raise RuntimeError("required Presidio recognizer is not registered")


class SemanticRecognizer:
    def detect(self, text: str) -> list[Detection]:
        raise NotImplementedError


class LocalGlinerRecognizer(SemanticRecognizer, EntityRecognizer):
    """Optional local-only GLiNER adapter; never used for deterministic CRNs."""

    def __init__(self, model_name: str = "urchade/gliner_small-v2.1") -> None:
        self._entity_types = [
            "GLINER_PERSON",
            "GLINER_ADDRESS",
            "GLINER_PHONE_NUMBER",
            "GLINER_EMAIL_ADDRESS",
            "GLINER_DATE_OF_BIRTH",
        ]
        EntityRecognizer.__init__(
            self,
            supported_entities=self._entity_types,
            supported_language="en",
            name="LOCAL_GLINER_PRESIDIO",
        )
        try:
            from gliner import GLiNER
        except ImportError as exc:
            raise RuntimeError("install the 'gliner' optional dependency") from exc
        self.model = GLiNER.from_pretrained(model_name, local_files_only=True)

    def load(self) -> None:
        return None

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts=None,
    ) -> list[RecognizerResult]:
        labels = ["person", "address", "phone number", "email address", "date of birth"]
        results = self.model.predict_entities(text, labels, threshold=0.6)
        recognized: list[RecognizerResult] = []
        for item in results:
            entity_type = f"GLINER_{item['label'].upper().replace(' ', '_')}"
            if entities and entity_type not in entities:
                continue
            recognized.append(
                RecognizerResult(
                    entity_type=entity_type,
                    start=int(item["start"]),
                    end=int(item["end"]),
                    score=float(item["score"]),
                    recognition_metadata={
                        RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                        RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                    },
                )
            )
        return recognized

    def detect(self, text: str) -> list[Detection]:
        return self.as_detections(self.analyze(text, self._entity_types))

    @staticmethod
    def as_detections(results: list[RecognizerResult]) -> list[Detection]:
        return [
            Detection(
                entity_type=item.entity_type,
                start=item.start,
                end=item.end,
                score=item.score,
                normalized_value="[semantic pii]",
                display_label=(
                    f"Potential "
                    f"{item.entity_type.removeprefix('GLINER_').lower().replace('_', ' ')}"
                ),
                source="local-gliner-presidio",
            )
            for item in results
        ]
