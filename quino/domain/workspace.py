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
class Baseline:
    id: str
    name: str
    description: str = ""
    tolerances: dict[str, Tolerance] = field(default_factory=dict)
    metrics: dict[str, MetricDefinition] = field(default_factory=dict)


@dataclass(slots=True)
class Case:
    id: str
    name: str
    baseline_id: str | None = None
    invariant_values: dict[str, ScalarValue] = field(default_factory=dict)
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
class ResultRef:
    run_entry_id: str
    artifact_path: str
    checksum: str


@dataclass(slots=True)
class RunEntry:
    id: str
    scope: str  # "baseline" | "case"
    case_id: str | None = None
    status: str = "not_run"  # "not_run" | "running" | "ok" | "failed" | "stale"
    result_ref: ResultRef | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    error_message: str = ""


@dataclass(slots=True)
class Run:
    id: str
    study_id: str
    created_at: str
    status: str = "not_run"  # "running" | "completed" | "failed" | "cancelled"
    entries: list[RunEntry] = field(default_factory=list)


@dataclass(slots=True)
class Workspace:
    baselines: list[Baseline] = field(default_factory=list)
    cases: list[Case] = field(default_factory=list)
    case_groups: list[CaseGroup] = field(default_factory=list)
    studies: list[Study] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)
    next_sequence: int = 1

    def is_empty(self) -> bool:
        return (
            not self.baselines
            and not self.cases
            and not self.case_groups
            and not self.studies
            and not self.runs
            and self.next_sequence == 1
        )
