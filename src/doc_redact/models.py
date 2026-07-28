from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    def padded(self, amount: int, width: int, height: int) -> "Box":
        return Box(
            max(0, self.left - amount),
            max(0, self.top - amount),
            min(width, self.right + amount),
            min(height, self.bottom + amount),
        )

    def union(self, other: "Box") -> "Box":
        return Box(
            min(self.left, other.left),
            min(self.top, other.top),
            max(self.right, other.right),
            max(self.bottom, other.bottom),
        )


@dataclass(frozen=True, slots=True)
class OCRToken:
    text: str
    box: Box
    confidence: float = 1.0
    line_id: int | None = None
    page_index: int | None = None


@dataclass(frozen=True, slots=True)
class Detection:
    entity_type: str
    start: int
    end: int
    score: float
    normalized_value: str
    display_label: str
    source: str


@dataclass(frozen=True, slots=True)
class MappedDetection:
    detection: Detection
    boxes: tuple[Box, ...]


@dataclass(slots=True)
class ProcessingReport:
    output_path: Path
    source_pages: int
    detections: int
    labels: dict[str, int] = field(default_factory=dict)
    verification: dict[str, bool] = field(default_factory=dict)
