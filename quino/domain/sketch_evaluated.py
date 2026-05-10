from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Vec2:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class BBox:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    def contains(self, x: float, y: float) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    def intersects(self, other: BBox) -> bool:
        return not (
            other.max_x < self.min_x
            or other.min_x > self.max_x
            or other.max_y < self.min_y
            or other.min_y > self.max_y
        )


@dataclass(frozen=True, slots=True)
class EvaluatedPoint:
    position: Vec2
    bbox: BBox


@dataclass(frozen=True, slots=True)
class EvaluatedLineSegment:
    start: Vec2
    end: Vec2
    bbox: BBox


@dataclass(frozen=True, slots=True)
class EvaluatedCircle:
    center: Vec2
    radius: float
    bbox: BBox


@dataclass(frozen=True, slots=True)
class EvaluatedArc:
    center: Vec2
    radius: float
    start_angle: float
    end_angle: float
    bbox: BBox
