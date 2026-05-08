from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quino.domain.types import BodyType, Dimension, DriverType, JointEndpointKind, JointType, MarkerType, SensorType


@dataclass(slots=True)
class Metadata:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Style:
    color: str = "#000000"
    visible: bool = True
    line_width: float = 1.0
    marker_size: float = 6.0


@dataclass(slots=True)
class ScalarProperty:
    expression: str
    unit: str
    expected_dimension: Dimension
    last_value: float | None = None
    last_unit: str | None = None
    error: str | None = None


@dataclass(slots=True)
class Parameter:
    id: str
    name: str
    expression: str
    unit: str
    description: str = ""
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class Marker:
    id: str
    name: str
    type: MarkerType
    x: ScalarProperty
    y: ScalarProperty
    visible: bool = True
    style: Style = field(default_factory=Style)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class Body:
    id: str
    name: str
    type: BodyType
    markers: list[Marker]
    edge_order: list[str]
    closed_shape: bool
    mass: ScalarProperty | None = None
    inertia: ScalarProperty | None = None
    style: Style = field(default_factory=Style)
    metadata: Metadata = field(default_factory=Metadata)

    def structural_markers(self) -> list[Marker]:
        return [marker for marker in self.markers if marker.type is MarkerType.STRUCTURAL]

    def com_marker(self) -> Marker:
        for marker in self.markers:
            if marker.type is MarkerType.COM:
                return marker
        raise ValueError(f"Body {self.id} is missing a CoM marker")


@dataclass(slots=True)
class Slider:
    id: str
    name: str
    origin_x: ScalarProperty
    origin_y: ScalarProperty
    angle: ScalarProperty
    travel_min: ScalarProperty | None = None
    travel_max: ScalarProperty | None = None
    style: Style = field(default_factory=Style)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class JointEndpoint:
    kind: JointEndpointKind
    body_id: str | None = None
    marker_id: str | None = None
    slider_id: str | None = None


@dataclass(slots=True)
class Joint:
    id: str
    name: str
    type: JointType
    endpoint_a: JointEndpoint
    endpoint_b: JointEndpoint
    style: Style = field(default_factory=Style)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class Driver:
    id: str
    name: str
    type: DriverType
    target_joint_id: str
    law: ScalarProperty
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class Sensor:
    id: str
    name: str
    type: SensorType
    marker_ids: list[str] = field(default_factory=list)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class SensorOutput:
    sensor_id: str
    time: list[float] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    data: list[list[float]] = field(default_factory=list)


@dataclass(slots=True)
class Model:
    bodies: list[Body] = field(default_factory=list)
    sliders: list[Slider] = field(default_factory=list)
    joints: list[Joint] = field(default_factory=list)
    drivers: list[Driver] = field(default_factory=list)
    sensors: list[Sensor] = field(default_factory=list)


@dataclass(slots=True)
class ViewState:
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    show_grid: bool = True
    show_markers: bool = True
    show_com: bool = False
    show_sliders: bool = True


@dataclass(slots=True)
class Project:
    id: str
    name: str
    schema_version: str
    model: Model = field(default_factory=Model)
    parameters: list[Parameter] = field(default_factory=list)
    view_state: ViewState = field(default_factory=ViewState)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class ValidationMessage:
    level: str
    code: str
    message: str
    entity_id: str | None = None


@dataclass(slots=True)
class ValidationReport:
    messages: list[ValidationMessage] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(message.level == "error" for message in self.messages)


@dataclass(slots=True)
class SimulationResult:
    success: bool
    time: list[float] = field(default_factory=list)
    frames: list[dict[str, float]] = field(default_factory=list)
    states: list[dict[str, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    error: str | None = None
    backend: str | None = None

    def __post_init__(self) -> None:
        if not self.frames and self.states:
            self.frames = list(self.states)
        if not self.states and self.frames:
            self.states = list(self.frames)
        if not self.time and self.frames:
            self.time = [float(index) for index in range(len(self.frames))]
