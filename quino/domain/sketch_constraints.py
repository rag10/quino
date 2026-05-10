from __future__ import annotations

from dataclasses import dataclass

from quino.domain.types import Dimension, SketchConstraintType


@dataclass(frozen=True, slots=True)
class ConstraintSpec:
    points: int
    entities: int
    value_dim: Dimension | None
    value_kind: str
    label: str


CONSTRAINT_SPECS: dict[SketchConstraintType, ConstraintSpec] = {
    SketchConstraintType.FIX: ConstraintSpec(1, 0, None, "none", "Fix"),
    SketchConstraintType.HORIZONTAL: ConstraintSpec(2, 0, None, "none", "Horizontal"),
    SketchConstraintType.VERTICAL: ConstraintSpec(2, 0, None, "none", "Vertical"),
    SketchConstraintType.COINCIDENT: ConstraintSpec(2, 0, None, "none", "Coincident"),
    SketchConstraintType.DISTANCE: ConstraintSpec(2, 0, Dimension.LENGTH, "length", "Distance"),
    SketchConstraintType.PARALLEL: ConstraintSpec(4, 0, None, "none", "Parallel"),
    SketchConstraintType.PERPENDICULAR: ConstraintSpec(4, 0, None, "none", "Perpendicular"),
    SketchConstraintType.EQUAL_LENGTH: ConstraintSpec(4, 0, None, "none", "Equal Length"),
    SketchConstraintType.ANGLE: ConstraintSpec(3, 0, Dimension.ANGLE, "angle", "Angle"),
    SketchConstraintType.MIDPOINT: ConstraintSpec(3, 0, None, "none", "Midpoint"),
    SketchConstraintType.COLLINEAR: ConstraintSpec(3, 0, None, "none", "Collinear"),
    SketchConstraintType.SYMMETRIC: ConstraintSpec(4, 0, None, "none", "Symmetric"),
    SketchConstraintType.ON_CIRCLE: ConstraintSpec(1, 1, None, "none", "On Circle"),
    SketchConstraintType.TANGENT: ConstraintSpec(2, 1, Dimension.UNITLESS, "sign", "Tangent"),
}
