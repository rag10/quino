from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quino.domain.model import (
    BodyPose,
    GravityLoad,
    Metadata,
    Model,
    Parameter,
    ReactionOutput,
    SensorOutput,
    Sketch,
    ViewState,
)
from quino.domain.plotting import MetricDef, PlotDef


# ---------------------------------------------------------------------------
# Scalar / tolerance helpers
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ScalarValue:
    value: float
    unit: str = ""


@dataclass(slots=True)
class Tolerance:
    metric_key: str
    absolute: float | None = None
    relative: float | None = None


@dataclass(slots=True)
class MetricDefinition:
    key: str
    name: str
    extractor: str
    unit: str = ""


@dataclass(slots=True)
class MetricResult:
    value: Any
    status: str  # "ok" | "error" | "no_data"
    error: str = ""
    evaluated_at: str | None = None


@dataclass(slots=True)
class Metric:
    id: str
    name: str
    description: str = ""
    value_type: str = "float"  # "float" | "bool" | "int" | "str"
    code: str = ""             # body of eval(data, meta), must `return`
    result: MetricResult | None = None


@dataclass(slots=True)
class ParameterDescriptor:
    path: str
    tag: str = "invariant"  # "invariant" | "variable"
    display_name: str = ""
    unit: str = ""
    dimension: str = ""
    default_value: float | None = None
    entity_id: str | None = None
    property_name: str | None = None


# ---------------------------------------------------------------------------
# Sweep / analysis config types
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SweepDef:
    id: str
    variable_kind: str  # see master plan §5.1 for the 6 allowed kinds
    target_ids: list[str] = field(default_factory=list)
    mode: str = "linear"     # "linear" | "list"
    start: float = 0.0
    end: float = 0.0
    steps: int = 1
    values: list[float] = field(default_factory=list)
    label: str = ""
    reference_mode: str = "absolute"  # "absolute" | "relative"

    def resolved_values(self) -> list[float]:
        if self.mode == "list":
            return list(self.values)
        if self.steps <= 1:
            return [self.start]
        delta = (self.end - self.start) / (self.steps - 1)
        return [self.start + delta * i for i in range(self.steps)]


@dataclass(slots=True)
class DynamicConfig:
    duration: float = 1.0
    steps: int = 100
    dt: float = 0.01
    integrator: str = "implicit"
    solver_settings: dict[str, Any] = field(default_factory=dict)
    plots: list[PlotDef] = field(default_factory=list)
    metrics: list[MetricDef] = field(default_factory=list)


@dataclass(slots=True)
class KinematicConfig:
    sweeps: list[SweepDef] = field(default_factory=list)
    allow_failed_steps: bool = True
    plots: list[PlotDef] = field(default_factory=list)
    metrics: list[MetricDef] = field(default_factory=list)


@dataclass(slots=True)
class StaticConfig:
    gravity_enabled: bool = True
    tolerance: float = 1e-6
    report_reactions: bool = True
    report_spring_energy: bool = True
    plots: list[PlotDef] = field(default_factory=list)
    metrics: list[MetricDef] = field(default_factory=list)


@dataclass(slots=True)
class EquilibriumConfig:
    gravity_enabled: bool = True
    initial_perturbations: list[float] = field(default_factory=lambda: [0.0, 0.05, -0.05])
    stability_check: bool = True
    pose_match_tolerance: float = 1e-3
    plots: list[PlotDef] = field(default_factory=list)
    metrics: list[MetricDef] = field(default_factory=list)


AnalysisConfig = DynamicConfig | KinematicConfig | StaticConfig | EquilibriumConfig

_DEFAULT_ANALYSIS_CONFIG = {
    "dynamic":     DynamicConfig,
    "kinematic":   KinematicConfig,
    "static":      StaticConfig,
    "equilibrium": EquilibriumConfig,
}


# ---------------------------------------------------------------------------
# Pose (consolidated workspace-level pose)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Pose:
    """Consolidated Pose dataclass for workspace-level poses.

    This temporarily shadows `quino.domain.model.Pose` and will eventually
    replace it after Task 4 removes the model-level Pose class.
    """
    id: str
    name: str
    body_poses: dict[str, BodyPose] = field(default_factory=dict)
    initial_velocities: dict[str, float] = field(default_factory=dict)
    parent_pose_id: str | None = None
    is_default: bool = False
    requires_recompute: bool = True
    solve_failed: bool = False
    metadata: Metadata = field(default_factory=Metadata)


# ---------------------------------------------------------------------------
# Entity / Case overlay helpers
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class EntityOverlay:
    origin: str = "local"  # "inherited" | "local"
    linked_properties: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.origin not in {"inherited", "local"}:
            raise ValueError(f"EntityOverlay.origin must be 'inherited' or 'local', got {self.origin!r}")
        if self.origin == "local" and self.linked_properties:
            raise ValueError("EntityOverlay with origin='local' must have empty linked_properties")


@dataclass(slots=True)
class CaseOverlay:
    entities: dict[str, EntityOverlay] = field(default_factory=dict)
    deleted_inherited_entity_ids: set[str] = field(default_factory=set)
    inherited_connections: set[tuple[str, str, str, str]] = field(default_factory=set)
    deleted_inherited_connections: set[tuple[str, str, str, str]] = field(default_factory=set)


def create_default_pose(pose_id: str, name: str = "Reference") -> Pose:
    """Create the local default pose every case owns independently."""
    return Pose(id=pose_id, name=name, is_default=True)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Analysis:
    id: str
    name: str
    analysis_type: str = "dynamic"
    pose_id: str | None = None
    config: AnalysisConfig = field(default=None)  # type: ignore[assignment]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.config is None:
            ctor = _DEFAULT_ANALYSIS_CONFIG.get(self.analysis_type)
            if ctor is None:
                raise ValueError(f"Unknown analysis_type {self.analysis_type!r}")
            self.config = ctor()


# ---------------------------------------------------------------------------
# Run artifacts
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ResultRef:
    run_entry_id: str
    artifact_path: str
    checksum: str


@dataclass(slots=True)
class ArtifactRef:
    kind: str
    path: str
    checksum: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


_RUN_STATUSES = {"to_be_run", "queued", "running", "ok", "partial", "failed", "stale"}


@dataclass(slots=True)
class Run:
    id: str
    analysis_id: str
    created_at: str
    finished_at: str | None = None
    status: str = "to_be_run"
    note: str = ""
    result_ref: ResultRef | None = None
    artifacts: list[ArtifactRef] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error_message: str = ""
    config_snapshot: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in _RUN_STATUSES:
            raise ValueError(f"Run status {self.status!r} is not allowed")


# ---------------------------------------------------------------------------
# Case (case-as-model: each case owns a full Model)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Case:
    id: str
    name: str
    description: str = ""
    parent_case_id: str | None = None
    model: Model = field(default_factory=Model)
    poses: list[Pose] = field(default_factory=list)
    analyses: list[Analysis] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)
    sensor_outputs: dict[str, SensorOutput] = field(default_factory=dict)
    reaction_outputs: dict[str, ReactionOutput] = field(default_factory=dict)
    overlay: CaseOverlay | None = None
    tolerances: dict[str, Tolerance] = field(default_factory=dict)
    metrics: dict[str, MetricDefinition] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Workspace (top-level container)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Workspace:
    id: str
    name: str
    schema_version: str
    sketch: Sketch | None = None
    parameters: list[Parameter] = field(default_factory=list)
    parameter_catalog: dict[str, ParameterDescriptor] = field(default_factory=dict)
    view_state: ViewState = field(default_factory=ViewState)
    gravity_default: GravityLoad | None = None
    root_case_ids: list[str] = field(default_factory=list)
    cases: dict[str, Case] = field(default_factory=dict)
    selected_case_id: str | None = None
    selected_pose_id: str | None = None
    selected_analysis_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
