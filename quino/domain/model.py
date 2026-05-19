from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quino.domain.types import (
    BodyType,
    Dimension,
    DriverType,
    JointEndpointKind,
    JointType,
    MarkerType,
    SensorType,
    SketchConstraintType,
    SketchEntityType,
    SpringEndpointKind,
    SpringType,
)


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
class Expression:
    """Lightweight parametric expression used by sketch entities."""

    text: str
    unit: str = "mm"


@dataclass(slots=True)
class Variable:
    """Sketch-level variable for parametric formulas."""

    name: str
    expression: str


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
class SpringEndpoint:
    kind: SpringEndpointKind
    body_id: str | None = None
    marker_id: str | None = None
    ground_x: ScalarProperty | None = None
    ground_y: ScalarProperty | None = None


@dataclass(slots=True)
class Spring:
    id: str
    name: str
    spring_type: SpringType
    endpoint_a: SpringEndpoint
    endpoint_b: SpringEndpoint
    rest_value: ScalarProperty | None = None
    law: ScalarProperty | None = None
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
class Load:
    id: str
    name: str
    target_marker_id: str
    fx: ScalarProperty
    fy: ScalarProperty
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
class ReactionOutput:
    joint_id: str
    joint_name: str
    endpoint_type: str                    # "ground" | "slider"
    time: list[float] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    data: list[list[float]] = field(default_factory=list)
    positions: list[tuple[float, float]] = field(default_factory=list)


@dataclass(slots=True)
class BodyPose:
    body_id: str
    x: float
    y: float
    angle: float


@dataclass(slots=True)
class Pose:
    id: str
    name: str
    body_poses: dict[str, BodyPose] = field(default_factory=dict)
    initial_velocities: dict[str, float] = field(default_factory=dict)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class SketchPoint:
    id: str
    name: str
    type: SketchEntityType
    x: Expression
    y: Expression
    visible: bool = True
    construction: bool = False
    selectable: bool = True
    style: Style = field(default_factory=Style)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class SketchLineSegment:
    id: str
    name: str
    type: SketchEntityType
    start_point_id: str
    end_point_id: str
    visible: bool = True
    construction: bool = False
    selectable: bool = True
    style: Style = field(default_factory=Style)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class SketchCircle:
    id: str
    name: str
    type: SketchEntityType
    center_point_id: str
    radius: Expression
    visible: bool = True
    construction: bool = False
    selectable: bool = True
    style: Style = field(default_factory=Style)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class SketchArc:
    id: str
    name: str
    type: SketchEntityType
    center_point_id: str
    start_point_id: str
    end_point_id: str
    visible: bool = True
    construction: bool = False
    selectable: bool = True
    style: Style = field(default_factory=Style)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class SketchInfiniteLine:
    id: str
    name: str
    type: SketchEntityType
    point_a_id: str
    point_b_id: str
    visible: bool = True
    construction: bool = False
    selectable: bool = True
    style: Style = field(default_factory=Style)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class SketchSpline:
    id: str
    name: str
    type: SketchEntityType
    control_point_ids: list[str]
    visible: bool = True
    construction: bool = False
    selectable: bool = True
    style: Style = field(default_factory=Style)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class SketchConstraint:
    id: str
    name: str
    type: SketchConstraintType
    references: list[str]
    value: ScalarProperty | None = None
    entity_references: list[str] = field(default_factory=list)
    enabled: bool = True
    driving: bool = True
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(slots=True)
class Sketch:
    id: str
    name: str
    visible: bool = True
    style: Style = field(default_factory=Style)
    entities: dict[
        str, SketchPoint | SketchLineSegment | SketchCircle | SketchArc | SketchInfiniteLine | SketchSpline
    ] = field(default_factory=dict)
    constraints: dict[str, SketchConstraint] = field(default_factory=dict)
    variables: dict[str, Variable] = field(default_factory=dict)
    metadata: Metadata = field(default_factory=Metadata)
    solve_error: str | None = None
    bad_constraint_ids: list[str] = field(default_factory=list)

    def points(self) -> list[SketchPoint]:
        return [entity for entity in self.entities.values() if isinstance(entity, SketchPoint)]


@dataclass(slots=True)
class SketchAnalysis:
    dof_count: int
    unconstrained_entities: list[str] = field(default_factory=list)
    conflicting_constraints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GravityLoad:
    magnitude: float = 9.81
    direction_x: float = 0.0
    direction_y: float = -1.0


@dataclass(slots=True)
class Model:
    bodies: list[Body] = field(default_factory=list)
    sliders: list[Slider] = field(default_factory=list)
    joints: list[Joint] = field(default_factory=list)
    drivers: list[Driver] = field(default_factory=list)
    loads: list[Load] = field(default_factory=list)
    sensors: list[Sensor] = field(default_factory=list)
    springs: list[Spring] = field(default_factory=list)
    gravity: GravityLoad | None = None


@dataclass(slots=True)
class ViewState:
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    show_grid: bool = True
    show_sensors: bool = True
    show_markers: bool = True
    show_com: bool = False
    show_sliders: bool = True
    show_sensors: bool = True


@dataclass(slots=True)
class Project:
    id: str
    name: str
    schema_version: str
    model: Model = field(default_factory=Model)
    parameters: list[Parameter] = field(default_factory=list)
    sketch: Sketch | None = None
    poses: list[Pose] = field(default_factory=list)
    simulation_initial_pose_id: str | None = None
    view_state: ViewState = field(default_factory=ViewState)
    metadata: Metadata = field(default_factory=Metadata)
    sensor_outputs: dict[str, SensorOutput] = field(default_factory=dict)
    reaction_outputs: dict[str, ReactionOutput] = field(default_factory=dict)


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
