from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
class ParameterDescriptor:
    path: str
    tag: str = "invariant"  # "invariant" | "variable"
    display_name: str = ""
    unit: str = ""
    dimension: str = ""
    default_value: float | None = None
    entity_id: str | None = None
    property_name: str | None = None


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


@dataclass(slots=True)
class KinematicConfig:
    sweeps: list[SweepDef] = field(default_factory=list)
    allow_failed_steps: bool = True


@dataclass(slots=True)
class StaticConfig:
    gravity_enabled: bool = True
    tolerance: float = 1e-6
    report_reactions: bool = True
    report_spring_energy: bool = True


@dataclass(slots=True)
class EquilibriumConfig:
    gravity_enabled: bool = True
    initial_perturbations: list[float] = field(default_factory=lambda: [0.0, 0.05, -0.05])
    stability_check: bool = True
    pose_match_tolerance: float = 1e-3


@dataclass(slots=True)
class Baseline:
    id: str
    name: str
    description: str = ""
    source_run_id: str | None = None
    model_snapshot_id: str | None = None
    model_hash: str | None = None
    invariant_parameter_keys: list[str] = field(default_factory=list)
    approval_status: str | None = None
    approved_run_id: str | None = None
    tolerances: dict[str, Tolerance] = field(default_factory=dict)
    metrics: dict[str, MetricDefinition] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Case:
    id: str
    name: str
    baseline_id: str | None = None
    parent_case_id: str | None = None
    model_snapshot_id: str | None = None
    invariant_values: dict[str, ScalarValue] = field(default_factory=dict)
    # Structural diffs vs parent baseline/case
    added_entities: dict[str, list[dict]] = field(default_factory=dict)
    #   key: domain ("bodies", "joints", "sliders", "drivers", "loads", "sensors", "springs")
    removed_entity_ids: list[str] = field(default_factory=list)
    reference_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    #   key: entity_id, value: {property_name: new_value}
    # Connections have no id, so removals are recorded as 4-tuples of
    # (src_instance, src_port, dst_instance, dst_port).
    removed_connections: list[tuple[str, str, str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkspacePose:
    id: str
    name: str
    baseline_id: str | None = None
    case_id: str | None = None
    project_pose_id: str | None = None
    is_default: bool = False
    parent_pose_id: str | None = None
    requires_recompute: bool = True
    solve_failed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


AnalysisConfig = DynamicConfig | KinematicConfig | StaticConfig | EquilibriumConfig

_DEFAULT_ANALYSIS_CONFIG = {
    "dynamic":     DynamicConfig,
    "kinematic":   KinematicConfig,
    "static":      StaticConfig,
    "equilibrium": EquilibriumConfig,
}


@dataclass(slots=True)
class Analysis:
    id: str
    name: str
    analysis_type: str = "dynamic"
    baseline_id: str | None = None
    case_id: str | None = None
    workspace_pose_id: str | None = None
    config: AnalysisConfig = field(default=None)  # type: ignore[assignment]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.config is None:
            ctor = _DEFAULT_ANALYSIS_CONFIG.get(self.analysis_type)
            if ctor is None:
                raise ValueError(f"Unknown analysis_type {self.analysis_type!r}")
            self.config = ctor()


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


@dataclass(slots=True)
class Workspace:
    baselines: list[Baseline] = field(default_factory=list)
    active_baseline_id: str | None = None
    active_case_id: str | None = None
    selected_pose_id: str | None = None
    selected_analysis_id: str | None = None
    cases: list[Case] = field(default_factory=list)
    poses: list[WorkspacePose] = field(default_factory=list)
    analyses: list[Analysis] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)
    parameter_catalog: dict[str, ParameterDescriptor] = field(default_factory=dict)
    model_snapshots: dict[str, str] = field(default_factory=dict)
    promotion_history: list[dict[str, Any]] = field(default_factory=list)
    next_sequence: int = 1

    def is_empty(self) -> bool:
        return (
            not self.baselines
            and self.active_baseline_id is None
            and self.active_case_id is None
            and self.selected_pose_id is None
            and self.selected_analysis_id is None
            and not self.cases
            and not self.poses
            and not self.analyses
            and not self.runs
            and not self.parameter_catalog
            and not self.model_snapshots
            and not self.promotion_history
            and self.next_sequence == 1
        )
