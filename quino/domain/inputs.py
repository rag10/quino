from __future__ import annotations

from dataclasses import dataclass

from quino.domain.types import JointEndpointKind, MarkerType


@dataclass(slots=True)
class MarkerInput:
    x: str
    y: str
    name: str | None = None
    marker_type: MarkerType = MarkerType.STRUCTURAL
    visible: bool = True


@dataclass(slots=True)
class SliderInput:
    origin_x: str
    origin_y: str
    angle: str
    travel_min: str | None = None
    travel_max: str | None = None


@dataclass(slots=True)
class JointEndpointInput:
    kind: JointEndpointKind
    body_id: str | None = None
    marker_id: str | None = None
    slider_id: str | None = None


@dataclass(slots=True)
class PropertyValueInput:
    kind: str
    value: str | bool | None


@dataclass(slots=True)
class SketchPointInput:
    x: str
    y: str
    name: str | None = None


@dataclass(slots=True)
class SketchLineSegmentInput:
    start_point_id: str
    end_point_id: str
    name: str | None = None


@dataclass(slots=True)
class SketchCircleInput:
    center_point_id: str
    radius: str
    name: str | None = None


@dataclass(slots=True)
class SketchArcInput:
    point_a_id: str
    point_b_id: str
    point_c_id: str
    name: str | None = None


@dataclass(slots=True)
class SketchInfiniteLineInput:
    point_a_id: str
    point_b_id: str
    name: str | None = None


@dataclass(slots=True)
class SketchSplineInput:
    control_point_ids: list[str]
    name: str | None = None


@dataclass(slots=True)
class SketchConstraintInput:
    constraint_type: str
    references: list[str]
    value: str | None = None
    name: str | None = None
