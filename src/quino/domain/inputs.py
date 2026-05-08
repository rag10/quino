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
class SensorInput:
    name: str
    sensor_type: str
    marker_ids: list[str]
