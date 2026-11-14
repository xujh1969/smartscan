"""Shared data structures. No Qt, no image I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .geometry import order_quad, quad_bbox

Point = tuple[float, float]


class OrientationState:
    UNKNOWN = "unknown"
    AUTO = "auto"
    MANUAL = "manual"


class Flags:
    INCOMPLETE = "incomplete"
    UNCERTAIN = "uncertain"
    LOW_CONFIDENCE = "low_confidence"
    AUTO_ROTATED = "auto"


@dataclass
class PhotoQuad:
    points: list[Point]
    tilt_deg: float = 0.0
    confidence: float = 1.0
    status: str = "ok"
    fill_ratio: float = 1.0
    occlusion: list[Point] | None = None
    visible_mask: object | None = None

    def ordered(self) -> list[Point]:
        return order_quad(self.points)

    def bbox(self) -> tuple[float, float, float, float]:
        return quad_bbox(self.points)

    def flags(self) -> list[str]:
        out: list[str] = []
        if self.status == Flags.INCOMPLETE:
            out.append(Flags.INCOMPLETE)
        elif self.status == Flags.UNCERTAIN:
            out.append(Flags.UNCERTAIN)
        if self.confidence < 0.6:
            out.append(Flags.LOW_CONFIDENCE)
        return out


@dataclass
class SplitResult:
    path: Path
    source: str
    digest: str
    rotation: int = 0
    orientation: str = OrientationState.UNKNOWN
    tilt_deg: float = 0.0
    confidence: float = 1.0
    flags: list[str] = field(default_factory=list)


@dataclass
class BatchConfig:
    source_files: list[Path]
    output_dir: Path
    max_tilt_deg: float = 20.0
    fill_mode: str = "background"
    min_area_ratio: float = 0.01
    require_review: bool = False

    def __post_init__(self) -> None:
        if not self.source_files:
            raise ValueError("source_files must not be empty")
        if self.output_dir is None:
            raise ValueError("output_dir is required")
        self.source_files = [Path(p) for p in self.source_files]
        self.output_dir = Path(self.output_dir)
        if self.fill_mode not in ("background", "inset", "alpha"):
            raise ValueError("fill_mode must be background, inset or alpha")


@dataclass
class BatchResult:
    ok: list[SplitResult] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    review: list[Path] = field(default_factory=list)
    completed: list[Path] = field(default_factory=list)
