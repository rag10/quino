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
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SweepParameter:
    parameter_path: str
    values: list[ScalarValue] = field(default_factory=list)


@dataclass(slots=True)
class CaseGroup:
    id: str
    name: str
    baseline_id: str = ""
    sweep_parameters: list[SweepParameter] = field(default_factory=list)
    generated_case_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StudyConfig:
    duration: float = 1.0
    steps: int = 100
    translation_driver_mode: str = "constraint"
    solver_settings: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StudyMask:
    include_cases: list[str] | None = None
    exclude_cases: list[str] | None = None
    include_baseline: bool = True


@dataclass(slots=True)
class StudyOverlay:
    parameter_overrides: dict[str, ScalarValue] = field(default_factory=dict)
    block_diagram_overlay: "BlockDiagram | None" = None  # type: ignore[name-defined]


@dataclass(slots=True)
class Study:
    id: str
    name: str
    study_type: str = "dynamic"
    config: StudyConfig = field(default_factory=StudyConfig)
    variable_values: dict[str, ScalarValue] = field(default_factory=dict)
    mask: StudyMask = field(default_factory=StudyMask)
    overlay: StudyOverlay | None = None


@dataclass(slots=True)
class WorkspacePose:
    id: str
    name: str
    baseline_id: str | None = None
    case_id: str | None = None
    project_pose_id: str | None = None
    is_default: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Analysis:
    id: str
    name: str
    analysis_type: str = "dynamic"
    baseline_id: str | None = None
    case_id: str | None = None
    workspace_pose_id: str | None = None
    config: StudyConfig = field(default_factory=StudyConfig)
    metadata: dict[str, Any] = field(default_factory=dict)


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


@dataclass(slots=True)
class RunEntry:
    id: str
    scope: str  # "baseline" | "case"
    baseline_id: str | None = None
    case_id: str | None = None
    status: str = "not_run"  # "not_run" | "running" | "ok" | "failed" | "stale"
    fingerprint: str = ""
    stale_reasons: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None
    result_ref: ResultRef | None = None
    artifacts: list[ArtifactRef] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    error_message: str = ""


@dataclass(slots=True)
class Run:
    id: str
    study_id: str | None
    created_at: str
    analysis_id: str | None = None
    status: str = "not_run"  # "running" | "completed" | "failed" | "cancelled"
    entries: list[RunEntry] = field(default_factory=list)


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
    case_groups: list[CaseGroup] = field(default_factory=list)
    studies: list[Study] = field(default_factory=list)
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
            and not self.case_groups
            and not self.studies
            and not self.runs
            and not self.parameter_catalog
            and not self.model_snapshots
            and not self.promotion_history
            and self.next_sequence == 1
        )
