# Case-as-Model Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the diff-based case composition with self-contained `Case` bundles (Model + poses + analyses + runs + `CaseOverlay`), an explicit cascading engine that propagates parent edits to descendants on write, and a hierarchical workflow tree GUI. Schema bump `0.2.0 → 0.3.0`, no backwards compatibility.

**Architecture:** A `Workspace` is a tree of `Case` nodes. Each `Case` stores a complete `Model` and a parallel `CaseOverlay` describing which entities/properties are linked to the parent. Mutations go through `case_cascading.py`, which both edits the local case and propagates to descendants where `linked_properties` allow. Reads of a case are O(1) — no composition runs.

**Tech Stack:** Python 3.11+, dataclasses (slots), PySide6, pytest, ruff/mypy as already configured. Reference spec: `docs/superpowers/specs/2026-05-26-case-as-model-redesign-design.md`.

---

## File map

### Created

- `quino/domain/workspace.py` — rewritten with new dataclasses (`Workspace`, `Case`, `CaseOverlay`, `EntityOverlay`, consolidated `Pose`, `Analysis`, `Run`).
- `quino/services/cascade_property_registry.py` — per-type cascadable property sets.
- `quino/services/case_cascading.py` — five mutation operations (`edit_property`, `add_entity`, `remove_entity`, `fork_case`, `reparent_case`).
- `quino/services/case_overlay_validator.py` — `validate_overlay`, `rebuild_overlay`.
- `quino/services/divergence_warning.py` — small helper for `DivergenceWarning` records.
- `quino/gui/widgets/divergences_dock.py` — divergences dock panel (Section 5.5 of spec).
- `quino/gui/widgets/link_status_indicator.py` — per-property link icon used in property panel.
- `tests/test_cascade_property_registry.py`, `tests/test_case_cascading.py`, `tests/test_case_overlay_validator.py`, `tests/test_workspace_roundtrip.py`, `tests/test_workflow_tree_panel_v2.py`, `tests/test_divergences_dock.py`.

### Modified

- `quino/domain/model.py` — remove `Project`, remove `Pose` (moves to `workspace.py`).
- `quino/serialization/json_io.py` — rewrite root-level serialisation; add `UnsupportedSchemaError`.
- `quino/application/service.py` — replace `Project` with `Workspace`; remove `compose_project` usage.
- `quino/application/_context.py` — drop `project_provider`, `effective_project`, `add_entity_to_case`, `remove_entity_from_case`, `add_marker_removal_to_case`, `get_active_case`, `_affected_analysis_ids_for_active_scope`, `discard_runs_for_active_case`. Add `workspace_provider`, `current_case_provider`, `cascade` (handle to the engine).
- `quino/application/commands/body_commands.py`, `joint_commands.py`, `entity_commands.py`, `force_commands.py`, `pose_commands.py`, `parameter_commands.py`, `sketch_commands.py`, `workspace_commands.py`, `block_commands.py` — route mutations through `case_cascading`.
- `quino/services/workspace_runner.py` — receive `Case` directly; drop `compose_project`.
- `quino/services/run_executor.py` — drop `compose_project`.
- `quino/services/workspace_catalog.py` — operate over `Workspace`.
- `quino/services/run_invalidation.py` — operate over case-local `Run` lists.
- `quino/services/workspace_snapshot.py`, `workspace_staleness.py`, `workspace_invalidation.py` — adapted to new layout; `case_diff_summary.py` deleted.
- `quino/analysis/static_runner.py`, `kinematic_runner.py`, `equilibrium_runner.py`, `dynamic.py` — accept `Case`.
- `quino/gui/main_window.py` — replace every `self.app_service.project.*` with `workspace.cases[selected].*` access.
- `quino/gui/panels/workflow_tree_panel.py` — rewrite as recursive case tree.
- `quino/gui/canvas.py` — render selected case's model; optional "Show parent diff" overlay (deferred to Task 28 — keep stub off by default).
- `quino/gui/widgets/run_status_widget.py`, `report_panel.py` — read from selected case.
- `quino/gui/dialogs/run_comparison_dialog.py` — iterate case tree.
- `scripts/build_*_example.py` — regenerate examples; add scripts for those missing (Double_Pendulum, Spring_Oscillator, Torsional_Spring_Pendulum).

### Deleted

- `quino/services/workspace_composition.py`
- `quino/services/case_diff_summary.py`
- `tests/test_workspace_composition.py`, `tests/test_structural_diffs.py`, `tests/test_case_overlay_editing.py`, `tests/test_com_per_case_overrides.py`, `tests/test_case_diff_summary.py`, `tests/test_delta_ux.py`, `tests/test_scope_parity.py`, `tests/test_workspace_working_context.py`, `tests/test_case_pose_resolver.py`, `tests/test_case_overlay_editing.py`, `tests/test_workspace_api.py`.
- `tests/test_workspace_runner.py`, `tests/test_workspace_invalidation.py`, `tests/test_workspace.py`, `tests/test_workspace_catalog.py` — rewritten in later tasks, not deleted, but their bodies start fresh.

---

## Phase 0 — Branch and baseline

### Task 0: Create the long-running branch

**Files:**
- None.

- [ ] **Step 1: Confirm clean working tree**

Run: `git status --short`
Expected: only the changes you intend (if any).

- [ ] **Step 2: Create branch off main**

```bash
git checkout -b redesign/case-as-model
```

- [ ] **Step 3: Sanity test that the current `main` tests pass**

Run: `pytest tests/ -q --no-header 2>&1 | tail -20`
Expected: PASS (or, if there are pre-existing failures, record them in a `BASELINE_FAILURES.md` scratch note — they don't block this redesign).

- [ ] **Step 4: Commit the branch start marker**

```bash
git commit --allow-empty -m "chore: start case-as-model redesign branch"
```

---

## Phase 1 — Domain dataclasses

### Task 1: Add `EntityOverlay` and `CaseOverlay`

**Files:**
- Modify: `quino/domain/workspace.py` — append the two dataclasses below; leave existing classes for now (will be replaced in Task 3).
- Test: `tests/test_workspace_overlay_types.py` (new).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workspace_overlay_types.py
from quino.domain.workspace import CaseOverlay, EntityOverlay


def test_entity_overlay_local_has_no_linked_properties():
    overlay = EntityOverlay(origin="local")
    assert overlay.linked_properties == set()


def test_entity_overlay_inherited_with_linked_properties():
    overlay = EntityOverlay(origin="inherited", linked_properties={"mass", "name"})
    assert "mass" in overlay.linked_properties


def test_case_overlay_defaults_are_empty():
    overlay = CaseOverlay()
    assert overlay.entities == {}
    assert overlay.deleted_inherited_entity_ids == set()
    assert overlay.inherited_connections == set()
    assert overlay.deleted_inherited_connections == set()
    assert overlay.poses == {}
    assert overlay.deleted_inherited_pose_ids == set()
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_workspace_overlay_types.py -v`
Expected: ImportError on `CaseOverlay`/`EntityOverlay`.

- [ ] **Step 3: Implement the classes (append to `workspace.py`)**

```python
# add at the bottom of quino/domain/workspace.py
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
    poses: dict[str, EntityOverlay] = field(default_factory=dict)
    deleted_inherited_pose_ids: set[str] = field(default_factory=set)
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_workspace_overlay_types.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/domain/workspace.py tests/test_workspace_overlay_types.py
git commit -m "feat(domain): add CaseOverlay and EntityOverlay dataclasses"
```

---

### Task 2: Add `Pose` (consolidated) in `workspace.py`

**Files:**
- Modify: `quino/domain/workspace.py` — add new `Pose` (do NOT remove `quino/domain/model.py:Pose` yet).
- Test: `tests/test_workspace_overlay_types.py` — extend.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_workspace_overlay_types.py
from quino.domain.workspace import Pose as WorkspacePoseV2


def test_workspace_pose_defaults():
    pose = WorkspacePoseV2(id="p1", name="Default")
    assert pose.is_default is False
    assert pose.requires_recompute is True
    assert pose.solve_failed is False
    assert pose.body_poses == {}
    assert pose.parent_pose_id is None
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_workspace_overlay_types.py::test_workspace_pose_defaults -v`
Expected: ImportError or name collision.

- [ ] **Step 3: Implement (add to `workspace.py`, before `CaseOverlay`)**

```python
from quino.domain.model import BodyPose, Metadata


@dataclass(slots=True)
class Pose:
    id: str
    name: str
    body_poses: dict[str, BodyPose] = field(default_factory=dict)
    initial_velocities: dict[str, float] = field(default_factory=dict)
    parent_pose_id: str | None = None
    is_default: bool = False
    requires_recompute: bool = True
    solve_failed: bool = False
    metadata: Metadata = field(default_factory=Metadata)
```

Note: this temporarily shadows `quino.domain.model.Pose`. The model-level `Pose` is removed in Task 9.

- [ ] **Step 4: Confirm pass**

Run: `pytest tests/test_workspace_overlay_types.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/domain/workspace.py tests/test_workspace_overlay_types.py
git commit -m "feat(domain): consolidated Pose dataclass in workspace"
```

---

### Task 3: Replace `Case`, `Workspace`, `Analysis`; delete `Baseline`, `WorkspacePose`

**Files:**
- Rewrite: `quino/domain/workspace.py`.
- Test: `tests/test_workspace_overlay_types.py` — extend.

- [ ] **Step 1: Write failing tests for the new shapes**

```python
# append to tests/test_workspace_overlay_types.py
from quino.domain.workspace import Analysis, Case, Run, Workspace


def test_case_defaults():
    case = Case(id="c1", name="Root")
    assert case.parent_case_id is None
    assert case.overlay is None
    assert case.runs == []
    assert case.analyses == []
    assert case.poses == []


def test_workspace_defaults():
    ws = Workspace(id="w1", name="Test", schema_version="0.3.0")
    assert ws.root_case_ids == []
    assert ws.cases == {}
    assert ws.selected_case_id is None


def test_analysis_no_baseline_id_or_case_id():
    a = Analysis(id="a1", name="A", analysis_type="static")
    assert not hasattr(a, "baseline_id")
    assert not hasattr(a, "case_id")
    assert not hasattr(a, "workspace_pose_id")
    assert a.pose_id is None
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_workspace_overlay_types.py -v`
Expected: tests for `Case`, `Workspace`, `Analysis` fail (attributes mismatch).

- [ ] **Step 3: Rewrite `quino/domain/workspace.py`**

Replace the file content with the following (keeping the helper imports/types already present like `Tolerance`, `MetricDefinition`, `ParameterDescriptor`, `SweepDef`, `DynamicConfig`, `KinematicConfig`, `StaticConfig`, `EquilibriumConfig`, `ScalarValue`, `AnalysisConfig`, `_DEFAULT_ANALYSIS_CONFIG`, `ResultRef`, `ArtifactRef`, `_RUN_STATUSES`):

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quino.domain.model import BodyPose, GravityLoad, Metadata, Model, Parameter, Sketch, ReactionOutput, SensorOutput, ViewState
from quino.domain.plotting import MetricDef, PlotDef


# --- preserved helpers (keep existing definitions) ---
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
    tag: str = "invariant"
    display_name: str = ""
    unit: str = ""
    dimension: str = ""
    default_value: float | None = None
    entity_id: str | None = None
    property_name: str | None = None


@dataclass(slots=True)
class SweepDef:
    id: str
    variable_kind: str
    target_ids: list[str] = field(default_factory=list)
    mode: str = "linear"
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


# --- consolidated Pose ---
@dataclass(slots=True)
class Pose:
    id: str
    name: str
    body_poses: dict[str, BodyPose] = field(default_factory=dict)
    initial_velocities: dict[str, float] = field(default_factory=dict)
    parent_pose_id: str | None = None
    is_default: bool = False
    requires_recompute: bool = True
    solve_failed: bool = False
    metadata: Metadata = field(default_factory=Metadata)


# --- overlays ---
@dataclass(slots=True)
class EntityOverlay:
    origin: str = "local"
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
    poses: dict[str, EntityOverlay] = field(default_factory=dict)
    deleted_inherited_pose_ids: set[str] = field(default_factory=set)


# --- Analysis ---
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


# --- Runs (preserved) ---
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


# --- Case bundle ---
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


# --- Workspace ---
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
```

This deliberately leaves `Baseline` and `WorkspacePose` deleted. The codebase will not compile after this step — that is expected; subsequent tasks fix call sites.

- [ ] **Step 4: Confirm new shapes are correct**

Run: `pytest tests/test_workspace_overlay_types.py -v`
Expected: PASS.

- [ ] **Step 5: Note the breakage scope**

Run: `python -c "import quino.application.service" 2>&1 | tail -5`
Expected: ImportError on `Baseline` or `WorkspacePose` somewhere. This is the "everything red" point of the redesign; the next tasks will fix it.

- [ ] **Step 6: Commit**

```bash
git add quino/domain/workspace.py tests/test_workspace_overlay_types.py
git commit -m "feat(domain): rewrite workspace.py with case-as-model dataclasses

BREAKING: removes Baseline, WorkspacePose, diff-based Case fields.
Downstream call sites will be fixed in subsequent commits on this branch."
```

---

### Task 4: Remove `Project` and `Pose` from `quino/domain/model.py`

**Files:**
- Modify: `quino/domain/model.py`.

- [ ] **Step 1: Find current importers (so we know what will break)**

Run: `grep -rn "from quino.domain.model import.*Project\b" quino tests | wc -l`
Expected: a number — record it.

Run: `grep -rn "from quino.domain.model import.*Pose\b" quino tests | wc -l`
Expected: a number — record it. These will be fixed during Phase 2+.

- [ ] **Step 2: Edit `quino/domain/model.py` — delete `Project` and `Pose` classes**

Delete the `@dataclass class Pose` block at lines ~242–248 and the `@dataclass class Project` block at lines ~407–430.

Add a deprecation shim at the bottom so import-time errors are clearer:

```python
def __getattr__(name: str):
    if name in {"Project", "Pose"}:
        raise ImportError(
            f"{name!r} was removed from quino.domain.model in the case-as-model redesign. "
            f"Use quino.domain.workspace.Workspace (root container) and quino.domain.workspace.Pose."
        )
    raise AttributeError(f"module 'quino.domain.model' has no attribute {name!r}")
```

- [ ] **Step 3: Run domain test to confirm the shim**

```python
# append to tests/test_workspace_overlay_types.py
import pytest


def test_project_removed_from_model():
    import quino.domain.model as m
    with pytest.raises(ImportError):
        m.Project


def test_pose_removed_from_model():
    import quino.domain.model as m
    with pytest.raises(ImportError):
        m.Pose
```

Run: `pytest tests/test_workspace_overlay_types.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add quino/domain/model.py tests/test_workspace_overlay_types.py
git commit -m "feat(domain): remove Project and Pose from model.py"
```

---

## Phase 2 — Cascade property registry

### Task 5: Define cascadable properties per entity type

**Files:**
- Create: `quino/services/cascade_property_registry.py`.
- Test: `tests/test_cascade_property_registry.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cascade_property_registry.py
from quino.services.cascade_property_registry import (
    cascadable_properties,
    is_cascadable_property,
)
from quino.domain.model import Body, Joint, Marker, Slider, Driver, Load, Sensor, Spring


def test_body_cascadable_properties_include_mass_and_com():
    props = cascadable_properties(Body)
    assert "mass" in props
    assert "com" in props
    assert "name" in props
    assert "style" in props
    # structural lists are NOT cascadable
    assert "markers" not in props
    assert "edge_order" not in props
    # id is NOT cascadable
    assert "id" not in props


def test_marker_cascadable_properties_include_x_y():
    props = cascadable_properties(Marker)
    assert "x" in props
    assert "y" in props
    assert "visible" in props
    assert "id" not in props


def test_joint_cascadable_properties_include_endpoints():
    props = cascadable_properties(Joint)
    assert "endpoint_a" in props
    assert "endpoint_b" in props
    assert "type" in props
    assert "id" not in props


def test_is_cascadable_property_matches():
    assert is_cascadable_property(Body, "mass") is True
    assert is_cascadable_property(Body, "id") is False
    assert is_cascadable_property(Body, "nonexistent") is False


def test_all_supported_types_have_a_registry_entry():
    for cls in [Body, Joint, Marker, Slider, Driver, Load, Sensor, Spring]:
        props = cascadable_properties(cls)
        assert props, f"{cls.__name__} has no cascadable properties"
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_cascade_property_registry.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# quino/services/cascade_property_registry.py
from __future__ import annotations

from dataclasses import fields
from typing import Type

from quino.domain.blocks import BlockInstance
from quino.domain.model import (
    Body,
    Driver,
    Joint,
    Load,
    Marker,
    Sensor,
    Slider,
    Spring,
)

# Properties that are *never* cascadable, irrespective of type.
_GLOBAL_EXCLUSIONS: set[str] = {"id"}

# Per-class extra exclusions: fields that represent topology / contained
# entities, not values that should propagate to children.
_PER_CLASS_EXCLUSIONS: dict[type, set[str]] = {
    Body: {"markers", "edge_order"},
    BlockInstance: {"instance_id"},  # instance_id is identity-like
}

_SUPPORTED: tuple[type, ...] = (Body, Joint, Marker, Slider, Driver, Load, Sensor, Spring, BlockInstance)


def cascadable_properties(cls: Type) -> frozenset[str]:
    if cls not in _SUPPORTED:
        raise ValueError(f"Type {cls.__name__} is not in the cascade registry")
    names = {f.name for f in fields(cls)}
    names -= _GLOBAL_EXCLUSIONS
    names -= _PER_CLASS_EXCLUSIONS.get(cls, set())
    return frozenset(names)


def is_cascadable_property(cls: Type, prop: str) -> bool:
    try:
        return prop in cascadable_properties(cls)
    except ValueError:
        return False
```

- [ ] **Step 4: Confirm pass**

Run: `pytest tests/test_cascade_property_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/services/cascade_property_registry.py tests/test_cascade_property_registry.py
git commit -m "feat(services): cascade property registry"
```

---

## Phase 3 — Overlay validator and rebuild

### Task 6: `validate_overlay(case, parent_case_or_none)`

**Files:**
- Create: `quino/services/case_overlay_validator.py`.
- Test: `tests/test_case_overlay_validator.py`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_case_overlay_validator.py
import pytest

from quino.domain.model import Body, Marker, Model, ScalarProperty
from quino.domain.types import BodyType, Dimension, MarkerType
from quino.domain.workspace import Case, CaseOverlay, EntityOverlay
from quino.services.case_overlay_validator import OverlayInvariantError, validate_overlay


def _make_marker(id_: str, name: str) -> Marker:
    return Marker(
        id=id_, name=name, type=MarkerType.STRUCTURAL,
        x=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
        y=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
    )


def _make_body(id_: str = "b1") -> Body:
    return Body(
        id=id_, name="bar", type=BodyType.BAR,
        markers=[_make_marker("m1", "A"), _make_marker("m2", "B")],
        edge_order=["m1", "m2"], closed_shape=False,
    )


def test_root_case_with_no_overlay_is_valid():
    case = Case(id="root", name="Root", model=Model(bodies=[_make_body()]))
    validate_overlay(case, parent=None)


def test_child_overlay_must_have_entry_per_entity():
    body = _make_body()
    parent = Case(id="P", name="P", model=Model(bodies=[body]))
    child = Case(
        id="C", name="C", parent_case_id="P",
        model=Model(bodies=[body]),
        overlay=CaseOverlay(entities={}),  # missing entries — invalid
    )
    with pytest.raises(OverlayInvariantError):
        validate_overlay(child, parent=parent)


def test_inherited_entity_must_exist_in_parent():
    body = _make_body()
    parent = Case(id="P", name="P", model=Model(bodies=[]))
    child = Case(
        id="C", name="C", parent_case_id="P",
        model=Model(bodies=[body]),
        overlay=CaseOverlay(entities={
            "b1": EntityOverlay(origin="inherited", linked_properties={"mass"}),
            "m1": EntityOverlay(origin="inherited"),
            "m2": EntityOverlay(origin="inherited"),
        }),
    )
    with pytest.raises(OverlayInvariantError):
        validate_overlay(child, parent=parent)


def test_local_origin_with_linked_properties_is_invalid():
    # Already enforced in __post_init__ of EntityOverlay, but validator
    # still has to refuse cases where someone bypassed it.
    body = _make_body()
    parent = Case(id="P", name="P", model=Model(bodies=[]))
    child = Case(
        id="C", name="C", parent_case_id="P",
        model=Model(bodies=[body]),
    )
    # build overlay directly without __post_init__ enforcement
    bad = EntityOverlay.__new__(EntityOverlay)
    bad.origin = "local"
    bad.linked_properties = {"mass"}
    child.overlay = CaseOverlay(entities={"b1": bad, "m1": EntityOverlay(origin="local"), "m2": EntityOverlay(origin="local")})
    with pytest.raises(OverlayInvariantError):
        validate_overlay(child, parent=parent)
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_case_overlay_validator.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the validator**

```python
# quino/services/case_overlay_validator.py
from __future__ import annotations

from typing import Iterable

from quino.domain.blocks import BlockInstance
from quino.domain.model import Body, Joint, Driver, Load, Sensor, Spring, Slider
from quino.domain.workspace import Case, CaseOverlay, EntityOverlay


class OverlayInvariantError(ValueError):
    """Raised when a Case.overlay violates the cascading invariants."""


def _iter_model_entity_ids(case: Case) -> Iterable[str]:
    m = case.model
    for body in m.bodies:
        yield body.id
        for marker in body.markers:
            yield marker.id
    for joint in m.joints:
        yield joint.id
    for slider in m.sliders:
        yield slider.id
    for driver in m.drivers:
        yield driver.id
    for load in m.loads:
        yield load.id
    for sensor in m.sensors:
        yield sensor.id
    for spring in m.springs:
        yield spring.id
    if m.control_graph is not None:
        for instance_id in m.control_graph.instances.keys():
            yield instance_id


def _iter_parent_entity_ids(parent: Case) -> set[str]:
    return set(_iter_model_entity_ids(parent))


def validate_overlay(case: Case, parent: Case | None) -> None:
    """Raise OverlayInvariantError if any invariant is violated."""
    if parent is None:
        if case.overlay is not None and (
            case.overlay.entities or case.overlay.deleted_inherited_entity_ids
            or case.overlay.inherited_connections or case.overlay.deleted_inherited_connections
            or case.overlay.poses or case.overlay.deleted_inherited_pose_ids
        ):
            raise OverlayInvariantError("Root case must have overlay=None or an empty overlay")
        return

    if case.overlay is None:
        raise OverlayInvariantError(f"Case {case.id!r} has a parent but overlay is None")

    overlay = case.overlay
    model_ids = set(_iter_model_entity_ids(case))
    parent_ids = _iter_parent_entity_ids(parent)

    # 1. Bijection between Model entities and overlay.entities
    missing = model_ids - set(overlay.entities.keys())
    extra = set(overlay.entities.keys()) - model_ids
    if missing or extra:
        raise OverlayInvariantError(
            f"Case {case.id!r}: overlay/model entity mismatch. Missing: {missing}. Extra: {extra}."
        )

    # 2. origin coherence + 3. inherited must exist in parent
    for ent_id, entry in overlay.entities.items():
        if entry.origin == "local" and entry.linked_properties:
            raise OverlayInvariantError(
                f"Case {case.id!r}: entity {ent_id!r} is origin='local' but has linked_properties"
            )
        if entry.origin == "inherited" and ent_id not in parent_ids:
            raise OverlayInvariantError(
                f"Case {case.id!r}: entity {ent_id!r} is origin='inherited' but does not exist in parent"
            )

    # 4. deleted_inherited_entity_ids must come from the parent
    for did in overlay.deleted_inherited_entity_ids:
        if did not in parent_ids:
            raise OverlayInvariantError(
                f"Case {case.id!r}: deleted_inherited_entity {did!r} does not exist in parent"
            )

    # 5. Pose entries
    pose_ids = {p.id for p in case.poses}
    parent_pose_ids = {p.id for p in parent.poses}
    p_missing = pose_ids - set(overlay.poses.keys())
    p_extra = set(overlay.poses.keys()) - pose_ids
    if p_missing or p_extra:
        raise OverlayInvariantError(
            f"Case {case.id!r}: overlay/poses mismatch. Missing: {p_missing}. Extra: {p_extra}."
        )
    for pid, entry in overlay.poses.items():
        if entry.origin == "inherited" and pid not in parent_pose_ids:
            raise OverlayInvariantError(
                f"Case {case.id!r}: pose {pid!r} is origin='inherited' but not in parent"
            )
```

- [ ] **Step 4: Confirm pass**

Run: `pytest tests/test_case_overlay_validator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/services/case_overlay_validator.py tests/test_case_overlay_validator.py
git commit -m "feat(services): overlay validator with invariant checks"
```

---

### Task 7: `rebuild_overlay(case, parent)`

**Files:**
- Modify: `quino/services/case_overlay_validator.py` — add `rebuild_overlay`.
- Test: `tests/test_case_overlay_validator.py` — extend.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_case_overlay_validator.py
from quino.services.case_overlay_validator import rebuild_overlay
from quino.services.cascade_property_registry import cascadable_properties


def test_rebuild_overlay_marks_value_equal_entities_as_fully_linked():
    body = _make_body()
    parent = Case(id="P", name="P", model=Model(bodies=[body]))
    child = Case(id="C", name="C", parent_case_id="P", model=Model(bodies=[_make_body()]))
    rebuild_overlay(child, parent)
    assert child.overlay is not None
    overlay = child.overlay.entities["b1"]
    assert overlay.origin == "inherited"
    assert overlay.linked_properties == set(cascadable_properties(Body))


def test_rebuild_overlay_marks_value_different_entities_as_inherited_unlinked():
    parent_body = _make_body()
    parent_body.markers[0].name = "ParentMarkerName"
    parent = Case(id="P", name="P", model=Model(bodies=[parent_body]))
    child_body = _make_body()  # default "A"/"B" names — m1 will differ
    child = Case(id="C", name="C", parent_case_id="P", model=Model(bodies=[child_body]))
    rebuild_overlay(child, parent)
    m1_overlay = child.overlay.entities["m1"]
    assert m1_overlay.origin == "inherited"
    assert "name" not in m1_overlay.linked_properties


def test_rebuild_overlay_marks_local_only_entities_as_local():
    parent = Case(id="P", name="P", model=Model(bodies=[]))
    child = Case(id="C", name="C", parent_case_id="P", model=Model(bodies=[_make_body()]))
    rebuild_overlay(child, parent)
    overlay = child.overlay.entities["b1"]
    assert overlay.origin == "local"
    assert overlay.linked_properties == set()


def test_rebuild_overlay_records_deletions():
    parent_body = _make_body("orphan")
    parent = Case(id="P", name="P", model=Model(bodies=[parent_body]))
    child = Case(id="C", name="C", parent_case_id="P", model=Model(bodies=[]))
    rebuild_overlay(child, parent)
    assert "orphan" in child.overlay.deleted_inherited_entity_ids
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_case_overlay_validator.py -v`
Expected: ImportError / NameError on `rebuild_overlay`.

- [ ] **Step 3: Implement**

```python
# append to quino/services/case_overlay_validator.py
from dataclasses import fields as _fields

from quino.services.cascade_property_registry import cascadable_properties


def _entity_lookup(case: Case) -> dict[str, tuple[object, type]]:
    """Map id -> (entity, cls) for everything in the case's model."""
    out: dict[str, tuple[object, type]] = {}
    m = case.model
    for body in m.bodies:
        out[body.id] = (body, type(body))
        for marker in body.markers:
            out[marker.id] = (marker, type(marker))
    for joint in m.joints:
        out[joint.id] = (joint, type(joint))
    for slider in m.sliders:
        out[slider.id] = (slider, type(slider))
    for driver in m.drivers:
        out[driver.id] = (driver, type(driver))
    for load in m.loads:
        out[load.id] = (load, type(load))
    for sensor in m.sensors:
        out[sensor.id] = (sensor, type(sensor))
    for spring in m.springs:
        out[spring.id] = (spring, type(spring))
    if m.control_graph is not None:
        for inst in m.control_graph.instances.values():
            out[inst.instance_id] = (inst, type(inst))
    return out


def _entity_value_equal(parent_ent: object, child_ent: object, cls: type) -> bool:
    """Per-property equality. Returns True only if every cascadable property matches."""
    for f in _fields(cls):
        if f.name not in cascadable_properties(cls):
            continue
        if getattr(parent_ent, f.name) != getattr(child_ent, f.name):
            return False
    return True


def _linked_properties_for_match(parent_ent: object, child_ent: object, cls: type) -> set[str]:
    """Return the subset of cascadable properties whose value matches between parent and child."""
    out: set[str] = set()
    for f in _fields(cls):
        if f.name not in cascadable_properties(cls):
            continue
        if getattr(parent_ent, f.name) == getattr(child_ent, f.name):
            out.add(f.name)
    return out


def rebuild_overlay(case: Case, parent: Case | None) -> None:
    """Recompute case.overlay by comparing case.model against parent.model.

    Lossy: cannot distinguish "intentional override at same value" from
    "linked, value coincidentally matches". Used only for migration and
    recovery.
    """
    if parent is None:
        case.overlay = None
        return

    parent_index = _entity_lookup(parent)
    child_index = _entity_lookup(case)

    overlay = CaseOverlay()
    for ent_id, (child_ent, cls) in child_index.items():
        if ent_id in parent_index:
            _parent_ent, parent_cls = parent_index[ent_id]
            if parent_cls is cls:
                linked = _linked_properties_for_match(_parent_ent, child_ent, cls)
                overlay.entities[ent_id] = EntityOverlay(origin="inherited", linked_properties=linked)
            else:
                overlay.entities[ent_id] = EntityOverlay(origin="local")
        else:
            overlay.entities[ent_id] = EntityOverlay(origin="local")

    for parent_id in parent_index.keys():
        if parent_id not in child_index:
            overlay.deleted_inherited_entity_ids.add(parent_id)

    # Poses
    parent_pose_ids = {p.id for p in parent.poses}
    for pose in case.poses:
        if pose.id in parent_pose_ids:
            overlay.poses[pose.id] = EntityOverlay(origin="inherited")
        else:
            overlay.poses[pose.id] = EntityOverlay(origin="local")
    for ppose in parent.poses:
        if ppose.id not in {p.id for p in case.poses}:
            overlay.deleted_inherited_pose_ids.add(ppose.id)

    case.overlay = overlay
```

- [ ] **Step 4: Confirm pass**

Run: `pytest tests/test_case_overlay_validator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/services/case_overlay_validator.py tests/test_case_overlay_validator.py
git commit -m "feat(services): rebuild_overlay by structural comparison"
```

---

## Phase 4 — Cascading engine

### Task 8: `fork_case` (engine bootstrap)

**Files:**
- Create: `quino/services/case_cascading.py`.
- Test: `tests/test_case_cascading.py`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_case_cascading.py
import copy

import pytest

from quino.domain.model import Body, Marker, Model, ScalarProperty
from quino.domain.types import BodyType, Dimension, MarkerType
from quino.domain.workspace import Case, Workspace
from quino.services.case_cascading import CascadingEngine
from quino.services.case_overlay_validator import validate_overlay
from quino.services.cascade_property_registry import cascadable_properties


def _make_marker(id_: str) -> Marker:
    return Marker(
        id=id_, name=id_, type=MarkerType.STRUCTURAL,
        x=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
        y=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
    )


def _make_body(id_: str = "b1") -> Body:
    return Body(
        id=id_, name="bar", type=BodyType.BAR,
        markers=[_make_marker("m1"), _make_marker("m2")],
        edge_order=["m1", "m2"], closed_shape=False,
        mass=ScalarProperty("2 kg", "kg", Dimension.MASS),
    )


def _ws_with_root_case() -> tuple[Workspace, Case]:
    root = Case(id="P", name="Root", model=Model(bodies=[_make_body()]))
    ws = Workspace(id="w", name="w", schema_version="0.3.0",
                   root_case_ids=["P"], cases={"P": root})
    return ws, root


def test_fork_case_creates_child_identical_to_parent():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    assert child_id in ws.cases
    child = ws.cases[child_id]
    assert child.parent_case_id == parent.id
    assert child.model.bodies[0].mass.expression == parent.model.bodies[0].mass.expression
    # Distinct identity (deep copy)
    assert child.model.bodies[0] is not parent.model.bodies[0]
    validate_overlay(child, parent=parent)


def test_fork_case_initializes_all_entities_as_inherited_fully_linked():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]
    body_overlay = child.overlay.entities["b1"]
    assert body_overlay.origin == "inherited"
    assert body_overlay.linked_properties == set(cascadable_properties(Body))
    marker_overlay = child.overlay.entities["m1"]
    assert marker_overlay.origin == "inherited"


def test_fork_case_does_not_copy_runs_or_analyses():
    ws, parent = _ws_with_root_case()
    parent.analyses.append(_dummy_analysis())
    parent.runs.append(_dummy_run())
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]
    assert child.analyses == []
    assert child.runs == []


def test_fork_case_copies_tolerances_and_metrics():
    from quino.domain.workspace import MetricDefinition, Tolerance
    ws, parent = _ws_with_root_case()
    parent.tolerances["rms"] = Tolerance(metric_key="rms", absolute=1e-3)
    parent.metrics["peak"] = MetricDefinition(key="peak", name="Peak", extractor="max_abs")
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]
    assert "rms" in child.tolerances
    assert "peak" in child.metrics
    # Independent copies
    assert child.tolerances["rms"] is not parent.tolerances["rms"]


def _dummy_analysis():
    from quino.domain.workspace import Analysis
    return Analysis(id="a1", name="A", analysis_type="static")


def _dummy_run():
    from quino.domain.workspace import Run
    return Run(id="r1", analysis_id="a1", created_at="2026-05-26T00:00:00", status="ok")


def test_fork_case_rejects_unknown_parent():
    ws, _ = _ws_with_root_case()
    engine = CascadingEngine(ws)
    with pytest.raises(KeyError):
        engine.fork_case("nope", "Child")
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_case_cascading.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement minimum engine to satisfy these tests**

```python
# quino/services/case_cascading.py
from __future__ import annotations

import copy
import uuid

from quino.domain.blocks import BlockInstance
from quino.domain.workspace import (
    Case,
    CaseOverlay,
    EntityOverlay,
    Workspace,
)
from quino.services.cascade_property_registry import cascadable_properties
from quino.services.case_overlay_validator import _entity_lookup


class CascadingEngine:
    """Façade for the five mutation operations.

    All workspace mutations that affect cases/poses MUST go through this
    class. Direct mutation of case.model or case.overlay from outside is
    a contract violation.
    """

    def __init__(self, workspace: Workspace) -> None:
        self._ws = workspace

    # ---- fork_case --------------------------------------------------
    def fork_case(self, parent_case_id: str, name: str) -> str:
        if parent_case_id not in self._ws.cases:
            raise KeyError(f"Parent case {parent_case_id!r} not found")
        parent = self._ws.cases[parent_case_id]

        new_id = f"case-{uuid.uuid4().hex[:8]}"
        child = Case(
            id=new_id,
            name=name,
            parent_case_id=parent_case_id,
            model=copy.deepcopy(parent.model),
            poses=copy.deepcopy(parent.poses),
            analyses=[],
            runs=[],
            sensor_outputs={},
            reaction_outputs={},
            tolerances=copy.deepcopy(parent.tolerances),
            metrics=copy.deepcopy(parent.metrics),
            overlay=self._build_fork_overlay(parent),
        )
        self._ws.cases[new_id] = child
        return new_id

    def _build_fork_overlay(self, parent: Case) -> CaseOverlay:
        overlay = CaseOverlay()
        for ent_id, (_ent, cls) in _entity_lookup(parent).items():
            overlay.entities[ent_id] = EntityOverlay(
                origin="inherited",
                linked_properties=set(cascadable_properties(cls)),
            )
        for pose in parent.poses:
            overlay.poses[pose.id] = EntityOverlay(origin="inherited")
        if parent.model.control_graph is not None:
            for conn in parent.model.control_graph.connections:
                overlay.inherited_connections.add(
                    (conn.src_instance, conn.src_port, conn.dst_instance, conn.dst_port)
                )
        return overlay
```

- [ ] **Step 4: Confirm pass**

Run: `pytest tests/test_case_cascading.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/services/case_cascading.py tests/test_case_cascading.py
git commit -m "feat(cascading): CascadingEngine.fork_case"
```

---

### Task 9: `edit_property` with propagation

**Files:**
- Modify: `quino/services/case_cascading.py`.
- Test: `tests/test_case_cascading.py`.

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_case_cascading.py
def test_edit_property_updates_local_and_unlinks_in_owner():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    new_mass = ScalarProperty("5 kg", "kg", Dimension.MASS)
    engine.edit_property(parent.id, "b1", "mass", new_mass)
    assert parent.model.bodies[0].mass.expression == "5 kg"
    # Parent is a root case → overlay is None, no unlinking needed
    assert parent.overlay is None


def test_edit_property_propagates_to_linked_descendant():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    new_mass = ScalarProperty("5 kg", "kg", Dimension.MASS)
    engine.edit_property(parent.id, "b1", "mass", new_mass)

    assert child.model.bodies[0].mass.expression == "5 kg"
    # Still linked
    assert "mass" in child.overlay.entities["b1"].linked_properties


def test_edit_property_records_warning_when_descendant_has_override():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    # Step 1: child overrides mass to 3 kg (this unlinks)
    engine.edit_property(child_id, "b1", "mass", ScalarProperty("3 kg", "kg", Dimension.MASS))
    assert "mass" not in child.overlay.entities["b1"].linked_properties

    # Step 2: parent changes mass to 5 kg → child must NOT change, must record warning
    engine.edit_property(parent.id, "b1", "mass", ScalarProperty("5 kg", "kg", Dimension.MASS))

    assert child.model.bodies[0].mass.expression == "3 kg"
    warnings = child.metadata.get("divergence_warnings", [])
    assert any(w["path"].endswith("/mass") for w in warnings)


def test_edit_property_in_owner_unlinks_from_parent():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    engine.edit_property(child_id, "b1", "mass", ScalarProperty("9 kg", "kg", Dimension.MASS))
    assert "mass" not in child.overlay.entities["b1"].linked_properties
    assert child.model.bodies[0].mass.expression == "9 kg"
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_case_cascading.py -v -k edit_property`
Expected: AttributeError on `edit_property`.

- [ ] **Step 3: Implement**

Add to `quino/services/case_cascading.py`:

```python
    # ---- edit_property ----------------------------------------------
    def edit_property(self, case_id: str, entity_id: str, prop: str, new_value: object) -> None:
        case = self._ws.cases[case_id]
        entity = self._find_entity(case, entity_id)
        if entity is None:
            raise KeyError(f"Entity {entity_id!r} not found in case {case_id!r}")

        setattr(entity, prop, new_value)
        if case.overlay is not None:
            entry = case.overlay.entities.get(entity_id)
            if entry is not None and entry.origin == "inherited":
                entry.linked_properties.discard(prop)

        self._propagate_edit_to_descendants(case_id, entity_id, prop, new_value)

    def _propagate_edit_to_descendants(self, source_case_id: str, entity_id: str, prop: str, new_value: object) -> None:
        for child_id in self._direct_children(source_case_id):
            child = self._ws.cases[child_id]
            assert child.overlay is not None
            entry = child.overlay.entities.get(entity_id)
            if entry is None or entity_id in child.overlay.deleted_inherited_entity_ids:
                continue
            if entry.origin != "inherited":
                continue
            if prop in entry.linked_properties:
                child_entity = self._find_entity(child, entity_id)
                if child_entity is not None:
                    setattr(child_entity, prop, copy.deepcopy(new_value))
                self._propagate_edit_to_descendants(child_id, entity_id, prop, new_value)
            else:
                child_entity = self._find_entity(child, entity_id)
                child_value = getattr(child_entity, prop, None) if child_entity is not None else None
                child.metadata.setdefault("divergence_warnings", []).append({
                    "path": f"entities/{entity_id}/{prop}",
                    "parent_case_id": source_case_id,
                    "parent_value": _to_serializable(new_value),
                    "child_value": _to_serializable(child_value),
                })

    # ---- helpers ----------------------------------------------------
    def _direct_children(self, case_id: str) -> list[str]:
        return [c.id for c in self._ws.cases.values() if c.parent_case_id == case_id]

    def _find_entity(self, case: Case, entity_id: str) -> object | None:
        m = case.model
        for body in m.bodies:
            if body.id == entity_id:
                return body
            for marker in body.markers:
                if marker.id == entity_id:
                    return marker
        for joint in m.joints:
            if joint.id == entity_id:
                return joint
        for slider in m.sliders:
            if slider.id == entity_id:
                return slider
        for driver in m.drivers:
            if driver.id == entity_id:
                return driver
        for load in m.loads:
            if load.id == entity_id:
                return load
        for sensor in m.sensors:
            if sensor.id == entity_id:
                return sensor
        for spring in m.springs:
            if spring.id == entity_id:
                return spring
        if m.control_graph is not None:
            return m.control_graph.instances.get(entity_id)
        return None


def _to_serializable(value: object) -> object:
    """Best-effort serialisation for divergence warning payloads."""
    if hasattr(value, "expression"):
        return getattr(value, "expression")
    if hasattr(value, "__dict__"):
        return {k: _to_serializable(v) for k, v in vars(value).items() if not k.startswith("_")}
    return repr(value)
```

- [ ] **Step 4: Confirm pass**

Run: `pytest tests/test_case_cascading.py -v -k edit_property`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/services/case_cascading.py tests/test_case_cascading.py
git commit -m "feat(cascading): edit_property with descendant propagation and divergence warnings"
```

---

### Task 10: `add_entity`

**Files:**
- Modify: `quino/services/case_cascading.py`.
- Test: `tests/test_case_cascading.py`.

- [ ] **Step 1: Write failing tests**

```python
# append
def test_add_entity_in_case_marks_origin_local():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    new_body = _make_body("b2")
    new_body.markers[0].id = "n1"; new_body.markers[1].id = "n2"
    new_body.edge_order = ["n1", "n2"]
    engine.add_entity(parent.id, new_body, domain="bodies")

    assert any(b.id == "b2" for b in parent.model.bodies)
    # Root case has no overlay
    assert parent.overlay is None


def test_add_entity_in_child_marks_local_and_does_not_propagate_to_grandchild():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    grand_id = engine.fork_case(child_id, "Grand")
    child = ws.cases[child_id]
    grand = ws.cases[grand_id]

    new_body = _make_body("b9")
    new_body.markers[0].id = "x1"; new_body.markers[1].id = "x2"; new_body.edge_order = ["x1", "x2"]
    engine.add_entity(child_id, new_body, domain="bodies")

    assert any(b.id == "b9" for b in child.model.bodies)
    assert child.overlay.entities["b9"].origin == "local"
    # Not retroactively added to grandchild
    assert all(b.id != "b9" for b in grand.model.bodies)
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_case_cascading.py -v -k add_entity`
Expected: AttributeError on `add_entity`.

- [ ] **Step 3: Implement**

Add to `quino/services/case_cascading.py`:

```python
_DOMAIN_LIST_ACCESSORS = {
    "bodies":   lambda m: m.bodies,
    "joints":   lambda m: m.joints,
    "sliders":  lambda m: m.sliders,
    "drivers":  lambda m: m.drivers,
    "loads":    lambda m: m.loads,
    "sensors":  lambda m: m.sensors,
    "springs":  lambda m: m.springs,
}


class CascadingEngine:
    # ... existing methods ...

    def add_entity(self, case_id: str, entity: object, domain: str) -> None:
        case = self._ws.cases[case_id]
        accessor = _DOMAIN_LIST_ACCESSORS.get(domain)
        if accessor is None:
            raise ValueError(f"Unknown domain {domain!r}")
        target_list = accessor(case.model)
        target_list.append(entity)

        if case.overlay is not None:
            ent_id = getattr(entity, "id", None)
            if ent_id is None:
                raise ValueError(f"Entity in domain {domain!r} has no .id")
            case.overlay.entities[ent_id] = EntityOverlay(origin="local")
            # Markers contained in a Body need their own entries
            if domain == "bodies":
                for marker in getattr(entity, "markers", []):
                    case.overlay.entities[marker.id] = EntityOverlay(origin="local")
```

- [ ] **Step 4: Confirm pass**

Run: `pytest tests/test_case_cascading.py -v -k add_entity`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/services/case_cascading.py tests/test_case_cascading.py
git commit -m "feat(cascading): add_entity with origin=local"
```

---

### Task 11: `remove_entity`

**Files:**
- Modify: `quino/services/case_cascading.py`.
- Test: `tests/test_case_cascading.py`.

- [ ] **Step 1: Write failing tests**

```python
# append
def test_remove_local_entity_clears_overlay_entry():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]
    new_body = _make_body("b9")
    new_body.markers[0].id = "x1"; new_body.markers[1].id = "x2"; new_body.edge_order = ["x1", "x2"]
    engine.add_entity(child_id, new_body, domain="bodies")
    assert "b9" in child.overlay.entities

    engine.remove_entity(child_id, "b9")
    assert all(b.id != "b9" for b in child.model.bodies)
    assert "b9" not in child.overlay.entities


def test_remove_inherited_entity_records_deletion():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    engine.remove_entity(child_id, "b1")
    assert all(b.id != "b1" for b in child.model.bodies)
    assert "b1" in child.overlay.deleted_inherited_entity_ids


def test_remove_propagates_to_clean_descendant():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    engine.remove_entity(parent.id, "b1")
    assert all(b.id != "b1" for b in child.model.bodies)


def test_remove_in_parent_keeps_customised_descendant_with_warning():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    # Child customises mass first
    engine.edit_property(child_id, "b1", "mass", ScalarProperty("3 kg", "kg", Dimension.MASS))

    # Parent removes b1 → child must keep it, mark origin=local, record warning
    engine.remove_entity(parent.id, "b1")
    assert any(b.id == "b1" for b in child.model.bodies)
    assert child.overlay.entities["b1"].origin == "local"
    assert child.overlay.entities["b1"].linked_properties == set()
    warnings = child.metadata.get("divergence_warnings", [])
    assert any("deleted_in_parent" in w.get("kind", "") for w in warnings)
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_case_cascading.py -v -k remove`
Expected: AttributeError on `remove_entity`.

- [ ] **Step 3: Implement**

Add to `quino/services/case_cascading.py`:

```python
    def remove_entity(self, case_id: str, entity_id: str) -> None:
        case = self._ws.cases[case_id]
        target = self._find_entity(case, entity_id)
        if target is None:
            return  # idempotent

        was_inherited = (
            case.overlay is not None
            and entity_id in case.overlay.entities
            and case.overlay.entities[entity_id].origin == "inherited"
        )

        self._remove_entity_from_model(case, entity_id)

        if case.overlay is not None:
            case.overlay.entities.pop(entity_id, None)
            if was_inherited:
                case.overlay.deleted_inherited_entity_ids.add(entity_id)

        # Cascade to direct children
        for child_id in self._direct_children(case_id):
            self._cascade_removal(child_id, entity_id)

    def _cascade_removal(self, child_id: str, entity_id: str) -> None:
        child = self._ws.cases[child_id]
        assert child.overlay is not None
        if entity_id in child.overlay.deleted_inherited_entity_ids:
            return
        entry = child.overlay.entities.get(entity_id)
        if entry is None:
            return

        # Determine "untouched": origin=inherited and no overrides recorded.
        untouched = (
            entry.origin == "inherited"
            and not any(
                w.get("path", "").startswith(f"entities/{entity_id}/")
                for w in child.metadata.get("divergence_warnings", [])
            )
            and entry.linked_properties  # at least one prop is still linked → user hasn't customised
        )

        if untouched:
            self._remove_entity_from_model(child, entity_id)
            child.overlay.entities.pop(entity_id, None)
            for gc_id in self._direct_children(child_id):
                self._cascade_removal(gc_id, entity_id)
        else:
            # Keep the entity, flip to local, record warning
            entry.origin = "local"
            entry.linked_properties.clear()
            child.metadata.setdefault("divergence_warnings", []).append({
                "kind": "deleted_in_parent",
                "path": f"entities/{entity_id}",
            })

    def _remove_entity_from_model(self, case: Case, entity_id: str) -> None:
        m = case.model
        m.bodies = [b for b in m.bodies if b.id != entity_id]
        for body in m.bodies:
            body.markers = [mk for mk in body.markers if mk.id != entity_id]
            body.edge_order = [mid for mid in body.edge_order if mid != entity_id]
        m.joints = [j for j in m.joints if j.id != entity_id]
        m.sliders = [s for s in m.sliders if s.id != entity_id]
        m.drivers = [d for d in m.drivers if d.id != entity_id]
        m.loads = [l for l in m.loads if l.id != entity_id]
        m.sensors = [s for s in m.sensors if s.id != entity_id]
        m.springs = [sp for sp in m.springs if sp.id != entity_id]
        if m.control_graph is not None:
            m.control_graph.instances.pop(entity_id, None)
            m.control_graph.connections = [
                c for c in m.control_graph.connections
                if c.src_instance != entity_id and c.dst_instance != entity_id
            ]
```

- [ ] **Step 4: Confirm pass**

Run: `pytest tests/test_case_cascading.py -v -k remove`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/services/case_cascading.py tests/test_case_cascading.py
git commit -m "feat(cascading): remove_entity with structural cascading"
```

---

### Task 12: `reparent_case` (internal-only)

**Files:**
- Modify: `quino/services/case_cascading.py`.
- Test: `tests/test_case_cascading.py`.

- [ ] **Step 1: Write the failing tests**

```python
# append
def test_reparent_case_to_none_drops_overlay():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    engine.reparent_case(child_id, new_parent_case_id=None)
    assert ws.cases[child_id].parent_case_id is None
    assert ws.cases[child_id].overlay is None
    assert child_id in ws.root_case_ids


def test_reparent_case_rejects_cycle():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    c1 = engine.fork_case(parent.id, "C1")
    c2 = engine.fork_case(c1, "C2")
    # Reparenting parent under c2 would create a cycle
    with pytest.raises(ValueError):
        engine.reparent_case(parent.id, new_parent_case_id=c2)
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_case_cascading.py -v -k reparent`
Expected: AttributeError.

- [ ] **Step 3: Implement**

```python
# append to CascadingEngine
    def reparent_case(self, case_id: str, new_parent_case_id: str | None) -> None:
        case = self._ws.cases[case_id]
        if new_parent_case_id is not None and self._would_form_cycle(case_id, new_parent_case_id):
            raise ValueError(f"Reparenting {case_id!r} under {new_parent_case_id!r} would form a cycle")

        case.parent_case_id = new_parent_case_id

        if new_parent_case_id is None:
            case.overlay = None
            if case_id not in self._ws.root_case_ids:
                self._ws.root_case_ids.append(case_id)
        else:
            from quino.services.case_overlay_validator import rebuild_overlay
            rebuild_overlay(case, self._ws.cases[new_parent_case_id])
            if case_id in self._ws.root_case_ids:
                self._ws.root_case_ids.remove(case_id)

    def _would_form_cycle(self, case_id: str, candidate_parent_id: str) -> bool:
        # Walk ancestors of candidate_parent_id; if any equals case_id, cycle.
        current: str | None = candidate_parent_id
        seen: set[str] = set()
        while current is not None:
            if current == case_id:
                return True
            if current in seen:
                return True
            seen.add(current)
            current = self._ws.cases[current].parent_case_id
        return False
```

- [ ] **Step 4: Confirm pass**

Run: `pytest tests/test_case_cascading.py -v -k reparent`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/services/case_cascading.py tests/test_case_cascading.py
git commit -m "feat(cascading): reparent_case (internal-only)"
```

---

### Task 13: End-to-end engine validation against the validator

**Files:**
- Test: `tests/test_case_cascading.py` (extend).

- [ ] **Step 1: Write the smoke test**

```python
# append
from quino.services.case_overlay_validator import validate_overlay


def test_engine_operations_keep_overlay_valid():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    c1 = engine.fork_case(parent.id, "C1")
    c2 = engine.fork_case(c1, "C2")

    engine.edit_property(parent.id, "b1", "mass", ScalarProperty("4 kg", "kg", Dimension.MASS))
    engine.edit_property(c1, "b1", "name", "renamed bar")
    engine.remove_entity(c2, "m1")

    validate_overlay(ws.cases[c1], parent=ws.cases[parent.id])
    validate_overlay(ws.cases[c2], parent=ws.cases[c1])
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_case_cascading.py -v -k validate`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_case_cascading.py
git commit -m "test(cascading): engine operations preserve overlay invariants"
```

---

## Phase 5 — Serialization

### Task 14: `UnsupportedSchemaError` and version gating

**Files:**
- Modify: `quino/serialization/json_io.py` — add error and refuse-load-old-schema.
- Test: `tests/test_workspace_roundtrip.py` (new).

- [ ] **Step 1: Write failing test**

```python
# tests/test_workspace_roundtrip.py
import json
import pytest

from quino.serialization.json_io import JsonMapper, UnsupportedSchemaError


def test_load_rejects_old_schema_with_clear_message(tmp_path):
    old = tmp_path / "old.quino.json"
    old.write_text(json.dumps({"schema_version": "0.2.0", "name": "x"}))
    mapper = JsonMapper()
    with pytest.raises(UnsupportedSchemaError) as exc:
        mapper.load(old)
    assert "0.3.0" in str(exc.value)
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_workspace_roundtrip.py -v`
Expected: ImportError on `UnsupportedSchemaError`.

- [ ] **Step 3: Edit `json_io.py`**

At the top of the file:

```python
class UnsupportedSchemaError(ValueError):
    """Raised when loading a .quino.json with a schema version older than the
    current case-as-model schema. No autoupgrade is provided."""
```

Modify `JsonMapper.load` (find the existing method) to check schema before dispatch:

```python
    def load(self, path: Path) -> Workspace:  # signature changes; see Task 15
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        version = data.get("schema_version")
        if version != "0.3.0":
            raise UnsupportedSchemaError(
                f"Schema {version!r} is not supported. This build requires schema 0.3.0. "
                "Use the v0.2.0 regeneration scripts in scripts/build_*_example.py to "
                "produce a fresh workspace."
            )
        return self._workspace_from_dict(data)
```

(The body method `_workspace_from_dict` is added in Task 15. For this step, leave it as a stub that raises `NotImplementedError` so the test passes.)

```python
    def _workspace_from_dict(self, data: dict) -> "Workspace":
        raise NotImplementedError  # implemented in Task 15
```

- [ ] **Step 4: Confirm pass**

Run: `pytest tests/test_workspace_roundtrip.py::test_load_rejects_old_schema_with_clear_message -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/serialization/json_io.py tests/test_workspace_roundtrip.py
git commit -m "feat(io): UnsupportedSchemaError gates schema 0.3.0 loading"
```

---

### Task 15: Workspace round-trip serialization

**Files:**
- Modify: `quino/serialization/json_io.py` — replace old `Project`-rooted dump/load with Workspace-rooted, remove `Baseline` / `WorkspacePose` handling.
- Test: `tests/test_workspace_roundtrip.py`.

- [ ] **Step 1: Write failing roundtrip test**

```python
# append to tests/test_workspace_roundtrip.py
from quino.domain.model import Body, Marker, Model, ScalarProperty
from quino.domain.types import BodyType, Dimension, MarkerType
from quino.domain.workspace import Case, EntityOverlay, CaseOverlay, Workspace
from quino.services.case_cascading import CascadingEngine


def _build_two_case_workspace() -> Workspace:
    marker_a = Marker(id="m1", name="A", type=MarkerType.STRUCTURAL,
                      x=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
                      y=ScalarProperty("0 mm", "mm", Dimension.LENGTH))
    marker_b = Marker(id="m2", name="B", type=MarkerType.STRUCTURAL,
                      x=ScalarProperty("100 mm", "mm", Dimension.LENGTH),
                      y=ScalarProperty("0 mm", "mm", Dimension.LENGTH))
    body = Body(id="b1", name="bar", type=BodyType.BAR, markers=[marker_a, marker_b],
                edge_order=["m1", "m2"], closed_shape=False,
                mass=ScalarProperty("2 kg", "kg", Dimension.MASS))
    root = Case(id="P", name="Root", model=Model(bodies=[body]))
    ws = Workspace(id="w", name="Test", schema_version="0.3.0",
                   root_case_ids=["P"], cases={"P": root})
    engine = CascadingEngine(ws)
    engine.fork_case("P", "Child")
    return ws


def test_workspace_roundtrip_preserves_structure(tmp_path):
    ws = _build_two_case_workspace()
    mapper = JsonMapper()
    path = tmp_path / "w.quino.json"
    mapper.save(ws, path)
    loaded = mapper.load(path)

    assert loaded.id == ws.id
    assert loaded.schema_version == "0.3.0"
    assert set(loaded.cases.keys()) == set(ws.cases.keys())
    parent = loaded.cases["P"]
    assert parent.parent_case_id is None
    assert parent.overlay is None
    child_id = next(cid for cid in loaded.cases if cid != "P")
    child = loaded.cases[child_id]
    assert child.parent_case_id == "P"
    assert child.overlay is not None
    body_overlay = child.overlay.entities["b1"]
    assert body_overlay.origin == "inherited"
    assert "mass" in body_overlay.linked_properties
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_workspace_roundtrip.py::test_workspace_roundtrip_preserves_structure -v`
Expected: NotImplementedError or AttributeError.

- [ ] **Step 3: Implement `_workspace_from_dict` and `save(workspace, path)`**

Replace the import block at the top of `quino/serialization/json_io.py`:

```python
from quino.domain.workspace import (
    Analysis,
    ArtifactRef,
    Case,
    CaseOverlay,
    DynamicConfig,
    EntityOverlay,
    EquilibriumConfig,
    KinematicConfig,
    MetricDefinition,
    ParameterDescriptor,
    Pose,
    ResultRef,
    Run,
    ScalarValue,
    StaticConfig,
    SweepDef,
    Tolerance,
    Workspace,
)
```

Remove all references to `Baseline` and `WorkspacePose` (they no longer exist).

Implement (full new methods — replace any existing `_project_to_dict` / `_project_from_dict`):

```python
    # ---- Workspace ---------------------------------------------------
    def save(self, workspace: Workspace, path: Path) -> None:
        data = self._workspace_to_dict(workspace)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=False)

    def dump(self, workspace: Workspace) -> dict:
        return self._workspace_to_dict(workspace)

    def _workspace_to_dict(self, ws: Workspace) -> dict:
        return {
            "schema_version": ws.schema_version,
            "id": ws.id,
            "name": ws.name,
            "sketch": self._sketch_to_dict(ws.sketch) if ws.sketch else None,
            "parameters": [self._parameter_to_dict(p) for p in ws.parameters],
            "parameter_catalog": {k: self._parameter_descriptor_to_dict(v) for k, v in ws.parameter_catalog.items()},
            "view_state": self._view_state_to_dict(ws.view_state),
            "gravity_default": self._gravity_to_dict(ws.gravity_default) if ws.gravity_default else None,
            "root_case_ids": list(ws.root_case_ids),
            "cases": {cid: self._case_to_dict(c) for cid, c in ws.cases.items()},
            "selected_case_id": ws.selected_case_id,
            "selected_pose_id": ws.selected_pose_id,
            "selected_analysis_id": ws.selected_analysis_id,
            "metadata": dict(ws.metadata),
        }

    def _workspace_from_dict(self, data: dict) -> Workspace:
        ws = Workspace(
            id=data["id"], name=data["name"], schema_version=data["schema_version"],
            sketch=self._sketch_from_dict(data["sketch"]) if data.get("sketch") else None,
            parameters=[self._parameter_from_dict(p) for p in data.get("parameters", [])],
            parameter_catalog={k: self._parameter_descriptor_from_dict(v) for k, v in data.get("parameter_catalog", {}).items()},
            view_state=self._view_state_from_dict(data.get("view_state", {})),
            gravity_default=self._gravity_from_dict(data["gravity_default"]) if data.get("gravity_default") else None,
            root_case_ids=list(data.get("root_case_ids", [])),
            selected_case_id=data.get("selected_case_id"),
            selected_pose_id=data.get("selected_pose_id"),
            selected_analysis_id=data.get("selected_analysis_id"),
            metadata=dict(data.get("metadata", {})),
        )
        for cid, cdata in data.get("cases", {}).items():
            ws.cases[cid] = self._case_from_dict(cdata)
        return ws

    # ---- Case --------------------------------------------------------
    def _case_to_dict(self, c: Case) -> dict:
        return {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "parent_case_id": c.parent_case_id,
            "model": self._model_to_dict(c.model),
            "poses": [self._pose_to_dict(p) for p in c.poses],
            "analyses": [self._analysis_to_dict(a) for a in c.analyses],
            "runs": [self._run_to_dict(r) for r in c.runs],
            "sensor_outputs": {k: self._sensor_output_to_dict(v) for k, v in c.sensor_outputs.items()},
            "reaction_outputs": {k: self._reaction_output_to_dict(v) for k, v in c.reaction_outputs.items()},
            "overlay": self._overlay_to_dict(c.overlay) if c.overlay else None,
            "tolerances": {k: self._tolerance_to_dict(v) for k, v in c.tolerances.items()},
            "metrics": {k: self._metric_def_to_dict(v) for k, v in c.metrics.items()},
            "metadata": dict(c.metadata),
        }

    def _case_from_dict(self, data: dict) -> Case:
        return Case(
            id=data["id"], name=data["name"], description=data.get("description", ""),
            parent_case_id=data.get("parent_case_id"),
            model=self._model_from_dict(data.get("model", {})),
            poses=[self._pose_from_dict(p) for p in data.get("poses", [])],
            analyses=[self._analysis_from_dict(a) for a in data.get("analyses", [])],
            runs=[self._run_from_dict(r) for r in data.get("runs", [])],
            sensor_outputs={k: self._sensor_output_from_dict(v) for k, v in data.get("sensor_outputs", {}).items()},
            reaction_outputs={k: self._reaction_output_from_dict(v) for k, v in data.get("reaction_outputs", {}).items()},
            overlay=self._overlay_from_dict(data["overlay"]) if data.get("overlay") else None,
            tolerances={k: self._tolerance_from_dict(v) for k, v in data.get("tolerances", {}).items()},
            metrics={k: self._metric_def_from_dict(v) for k, v in data.get("metrics", {}).items()},
            metadata=dict(data.get("metadata", {})),
        )

    # ---- Overlay -----------------------------------------------------
    def _overlay_to_dict(self, o: CaseOverlay) -> dict:
        return {
            "entities": {
                k: {"origin": v.origin, "linked_properties": sorted(v.linked_properties)}
                for k, v in o.entities.items()
            },
            "deleted_inherited_entity_ids": sorted(o.deleted_inherited_entity_ids),
            "inherited_connections": [list(t) for t in sorted(o.inherited_connections)],
            "deleted_inherited_connections": [list(t) for t in sorted(o.deleted_inherited_connections)],
            "poses": {
                k: {"origin": v.origin, "linked_properties": sorted(v.linked_properties)}
                for k, v in o.poses.items()
            },
            "deleted_inherited_pose_ids": sorted(o.deleted_inherited_pose_ids),
        }

    def _overlay_from_dict(self, data: dict) -> CaseOverlay:
        return CaseOverlay(
            entities={
                k: EntityOverlay(origin=v["origin"], linked_properties=set(v.get("linked_properties", [])))
                for k, v in data.get("entities", {}).items()
            },
            deleted_inherited_entity_ids=set(data.get("deleted_inherited_entity_ids", [])),
            inherited_connections={tuple(t) for t in data.get("inherited_connections", [])},
            deleted_inherited_connections={tuple(t) for t in data.get("deleted_inherited_connections", [])},
            poses={
                k: EntityOverlay(origin=v["origin"], linked_properties=set(v.get("linked_properties", [])))
                for k, v in data.get("poses", {}).items()
            },
            deleted_inherited_pose_ids=set(data.get("deleted_inherited_pose_ids", [])),
        )
```

Reuse `_model_to_dict` / `_model_from_dict`, `_pose_to_dict` / `_pose_from_dict`, `_analysis_to_dict` / `_analysis_from_dict`, `_run_to_dict` / `_run_from_dict`, etc. — these exist in the current file but referenced via `Project`. Adapt them to take their dataclasses directly (most already do). Delete `_baseline_to_dict`, `_baseline_from_dict`, `_workspace_pose_to_dict`, `_workspace_pose_from_dict`, `_project_to_dict`, `_project_from_dict`.

- [ ] **Step 4: Confirm pass**

Run: `pytest tests/test_workspace_roundtrip.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/serialization/json_io.py tests/test_workspace_roundtrip.py
git commit -m "feat(io): workspace-rooted JSON serialisation for schema 0.3.0"
```

---

## Phase 6 — Application layer

### Task 16: ApplicationService — switch to Workspace as root

**Files:**
- Modify: `quino/application/service.py`.
- Modify: `quino/application/_context.py`.

This task is large; treat each numbered substep as a unit.

- [ ] **Step 1: Add `from quino.domain.workspace import Workspace` and remove `Project`-only imports**

In `quino/application/service.py`:

- Remove `Project, Pose` from the `quino.domain.model` import.
- Remove `from quino.services.workspace_composition import compose_project as _compose_project`.
- Add `from quino.domain.workspace import Workspace, Case, Pose`.
- Replace `self.project: Project | None = None` with `self.workspace: Workspace | None = None`.
- Replace `self._undo_stack: list[Project] = []` and `self._redo_stack: list[Project] = []` with `Workspace`.
- Add helper:

```python
    def current_case(self) -> Case | None:
        if self.workspace is None or self.workspace.selected_case_id is None:
            return None
        return self.workspace.cases.get(self.workspace.selected_case_id)
```

- [ ] **Step 2: Rewrite `ServiceContext` (`_context.py`)**

Replace the entire class body with the slimmed-down version:

```python
@dataclass
class ServiceContext:
    workspace_provider: Callable[[], "Workspace | None"]
    current_case_provider: Callable[[], "Case | None"]
    cascade_provider: Callable[[], "CascadingEngine"]
    operation: Callable[[], ContextManager]
    snapshot: Callable[[], None]
    invalidate_pose_state: Callable[[], None]
    ids: IdService
    expressions: ExpressionService
    units: UnitService
    validation: ValidationService
    find_entity: Callable[[str], object]
    sync_all_special_com_markers: Callable[[], None]
    load_expression_variables: Callable[..., dict]
    build_validated_scalar_property: Callable[[object, str, str], object]
    assign_scalar_property: Callable[[object, str, object], None]
    apply_style_update: Callable[[object, str, object], None]
    connect_marker_to_ground: Callable[..., str]
    joints_for_marker: Callable[[str], list]
    translate_direct_joint_counterparts: Callable[..., set]
    set_current_pose_id: Callable[[str | None], None] = lambda _pid: None
    confirm_run_invalidation: Callable[[], bool] = lambda: True

    def affected_analysis_ids(self) -> set[str]:
        case = self.current_case_provider()
        if case is None:
            return set()
        return {a.id for a in case.analyses}

    def discard_runs_for_active_case(self) -> None:
        case = self.current_case_provider()
        if case is None:
            return
        ws = self.workspace_provider()
        if ws is None:
            return
        analysis_ids = self.affected_analysis_ids()
        if not analysis_ids:
            return
        from quino.services.run_invalidation import _mark_set_stale
        _mark_set_stale(case, analysis_ids, reason="model edited")

    def confirm_invalidation_if_runs_exist(self) -> bool:
        case = self.current_case_provider()
        if case is None:
            return True
        analysis_ids = self.affected_analysis_ids()
        if not analysis_ids:
            return True
        has_ok_run = any(
            r.analysis_id in analysis_ids and r.status in {"ok", "partial"}
            for r in case.runs
        )
        if not has_ok_run:
            return True
        return bool(self.confirm_run_invalidation())
```

- [ ] **Step 3: Wire the new context in `ApplicationService.__init__`**

```python
from quino.services.case_cascading import CascadingEngine

self._service_context = ServiceContext(
    workspace_provider=lambda: self.workspace,
    current_case_provider=self.current_case,
    cascade_provider=lambda: CascadingEngine(self.workspace) if self.workspace else None,
    operation=self._operation,
    snapshot=self._snapshot,
    invalidate_pose_state=self._invalidate_pose_state,
    ids=self.id_service,
    expressions=self.expression_service,
    ...
)
```

Remove every reference to `project_provider`, `effective_project`, `add_entity_to_case`, `remove_entity_from_case`, `add_marker_removal_to_case`, `get_active_case` in `_context.py`. The command-services will be migrated in Phase 7 to use `cascade_provider()` and `current_case_provider()` directly.

- [ ] **Step 4: New / load / save**

Replace `new_project`, `load_project`, `save_project`, `current_project_path` with:

```python
    def new_workspace(self, name: str = "Untitled") -> None:
        ws_id = self.id_service.next_id("ws")
        root_id = self.id_service.next_id("case")
        from quino.domain.model import Model
        from quino.domain.workspace import Case, Workspace
        root = Case(id=root_id, name="Root", model=Model())
        self.workspace = Workspace(
            id=ws_id, name=name, schema_version="0.3.0",
            root_case_ids=[root_id], cases={root_id: root},
            selected_case_id=root_id,
        )
        self.current_workspace_path = None

    def load_workspace(self, path: Path) -> None:
        self.workspace = self.json_mapper.load(path)
        self.current_workspace_path = path

    def save_workspace(self, path: Path | None = None) -> None:
        if self.workspace is None:
            raise RuntimeError("No workspace loaded")
        target = path or self.current_workspace_path
        if target is None:
            raise RuntimeError("No save path specified")
        self.json_mapper.save(self.workspace, target)
        self.current_workspace_path = target
```

- [ ] **Step 5: Update `_snapshot` / `_operation` to deep-copy the Workspace**

```python
    def _snapshot(self) -> None:
        import copy
        if self.workspace is None:
            return
        self._undo_stack.append(copy.deepcopy(self.workspace))
        self._redo_stack.clear()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        import copy
        self._redo_stack.append(copy.deepcopy(self.workspace) if self.workspace else None)
        self.workspace = self._undo_stack.pop()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        import copy
        self._undo_stack.append(copy.deepcopy(self.workspace) if self.workspace else None)
        self.workspace = self._redo_stack.pop()
```

- [ ] **Step 6: Run the available domain-level tests as a smoke check**

Run: `pytest tests/test_workspace_overlay_types.py tests/test_case_overlay_validator.py tests/test_case_cascading.py tests/test_workspace_roundtrip.py tests/test_cascade_property_registry.py -v`
Expected: PASS. (Many other tests still fail due to command-services; that's expected, fixed in Phase 7.)

- [ ] **Step 7: Commit**

```bash
git add quino/application/service.py quino/application/_context.py
git commit -m "refactor(application): replace Project with Workspace; cascade-aware ServiceContext"
```

---

### Task 17: Adapt command-services to the engine

**Files:**
- Modify (one by one): `quino/application/commands/body_commands.py`, `joint_commands.py`, `entity_commands.py`, `force_commands.py`, `pose_commands.py`, `parameter_commands.py`, `sketch_commands.py`, `workspace_commands.py`, `block_commands.py`.

Each command-service follows the same migration pattern. Detailed walkthrough for the first one, then the rest follow the same recipe.

- [ ] **Step 1: Read `body_commands.py` to find each mutation site**

Open `quino/application/commands/body_commands.py`. For every method that today reads `self._ctx.project_provider()` or calls `add_entity_to_case` / `remove_entity_from_case`, transform as follows:

| Old | New |
|---|---|
| `project = self._ctx.project_provider()` | `case = self._ctx.current_case_provider()`; `if case is None: return` |
| `case = self._ctx.get_active_case()` | `case = self._ctx.current_case_provider()` |
| `self._ctx.add_entity_to_case(entity, "bodies")` | `engine = self._ctx.cascade_provider(); engine.add_entity(case.id, entity, "bodies")` |
| `self._ctx.remove_entity_from_case(entity_id)` | `engine = self._ctx.cascade_provider(); engine.remove_entity(case.id, entity_id)` |
| Direct mutation of `project.model.bodies[...]` for an edit | `engine.edit_property(case.id, entity_id, prop_name, new_value)` |
| `compose_project(project, case)` | Just use `case.model` directly — no composition needed |

- [ ] **Step 2: Apply transformations to `body_commands.py`**

Run: `pytest tests/test_workspace.py tests/test_workspace_api.py -q 2>&1 | tail -10` after editing — note which tests will need rewrite in Task 24.

- [ ] **Step 3: Apply the same recipe to each remaining command-service**

For each file: `joint_commands.py`, `entity_commands.py`, `force_commands.py`, `pose_commands.py`, `parameter_commands.py`, `sketch_commands.py`, `workspace_commands.py`, `block_commands.py`:

1. Open the file.
2. Apply the substitution table.
3. Where the file references `Baseline`, `WorkspacePose`, `invariant_values`, `added_entities`, `reference_overrides`, `removed_entity_ids`: remove those code paths entirely.
4. Where the file expected a "composed project" view: replace with direct access to `case.model`.

- [ ] **Step 4: Smoke test that `import quino.application.service` works**

Run: `python -c "from quino.application.service import ApplicationService; s = ApplicationService(); s.new_workspace(); print('OK')"`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add quino/application/commands/
git commit -m "refactor(commands): route mutations through CascadingEngine"
```

---

## Phase 7 — Services and runners

### Task 18: Adapt `workspace_runner.py` and `run_executor.py`

**Files:**
- Modify: `quino/services/workspace_runner.py`.
- Modify: `quino/services/run_executor.py`.

- [ ] **Step 1: Rewrite `workspace_runner.run_analysis` signature**

```python
# quino/services/workspace_runner.py
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from quino.domain.workspace import Analysis, Case, Run, Workspace
from quino.simulation.runner import SimulationRunner


def run_analysis(
    workspace: Workspace,
    case: Case,
    analysis_id: str,
    simulation_runner: SimulationRunner,
    *,
    cancel_event=None,
    run: Run | None = None,
    project_dir: Path | None = None,
) -> Run:
    analysis = next((a for a in case.analyses if a.id == analysis_id), None)
    if analysis is None:
        raise ValueError(f"Analysis {analysis_id!r} not found in case {case.id!r}")

    pose = next((p for p in case.poses if p.id == analysis.pose_id), None) if analysis.pose_id else None

    if run is None:
        run = Run(
            id=_next_run_id(case),
            analysis_id=analysis.id,
            created_at=datetime.now().isoformat(),
            status="running",
            config_snapshot=asdict(analysis.config),
        )
    # No composition — case.model is the authoritative model
    return _run_with_model(case.model, analysis, pose, simulation_runner, run, cancel_event, project_dir)


def _next_run_id(case: Case) -> str:
    existing = {r.id for r in case.runs}
    n = 1
    while f"run-{n}" in existing:
        n += 1
    return f"run-{n}"


# `_run_with_model`: lift out the body of the old run_analysis after composed.
# Keep it identical to today; just receive (model, analysis, pose, runner, run, ...).
```

Delete all `compose_project` / `compose_project_hash` references, `Baseline`, `WorkspacePose`. Move `_apply_workspace_pose` from old signature to operate on a plain `Model` and `Pose`.

- [ ] **Step 2: Update `run_executor.py`**

```python
# quino/services/run_executor.py
from quino.domain.workspace import Run, Workspace

class RunExecutor(QtCore.QObject):
    # ...
    def enqueue(self, analysis_id: str) -> RunHandle:
        ws = self.app_service.workspace
        if ws is None:
            raise ValueError("No active workspace")
        case = self.app_service.current_case()
        if case is None:
            raise ValueError("No active case")
        analysis = next((a for a in case.analyses if a.id == analysis_id), None)
        if analysis is None:
            raise ValueError(f"Analysis {analysis_id!r} not found in case {case.id!r}")
        # ... (same as before, but read from case.runs / case.analyses)
```

Remove `from quino.services.workspace_composition import compose_project`.

- [ ] **Step 3: Smoke test imports**

Run: `python -c "from quino.services.run_executor import RunExecutor; from quino.services.workspace_runner import run_analysis; print('OK')"`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add quino/services/workspace_runner.py quino/services/run_executor.py
git commit -m "refactor(runner): operate on Case directly; drop composition"
```

---

### Task 19: Update analysis runners

**Files:**
- Modify: `quino/analysis/static_runner.py`, `kinematic_runner.py`, `equilibrium_runner.py`, `dynamic.py`.

For each:

- [ ] **Step 1: Change signature**

Old: `def run(project: Project, case: Case | None, ...)` (varies).
New: `def run(case: Case, ...)`. The case's `model` and `poses` are the only inputs needed.

- [ ] **Step 2: Remove `compose_project` calls**

Anywhere these runners called `compose_project(project, case)`, replace with `case.model`.

- [ ] **Step 3: Update `quino/analysis/registry.py`** if it dispatches by signature.

- [ ] **Step 4: Run runner-level imports**

Run: `python -c "from quino.analysis.static_runner import StaticRunner; from quino.analysis.kinematic_runner import KinematicRunner; from quino.analysis.equilibrium_runner import EquilibriumRunner; print('OK')"`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add quino/analysis/
git commit -m "refactor(analysis): runners accept Case directly"
```

---

### Task 20: Refactor catalog / staleness / invalidation / snapshot helpers

**Files:**
- Modify: `quino/services/workspace_catalog.py`, `workspace_staleness.py`, `workspace_invalidation.py`, `workspace_snapshot.py`, `run_invalidation.py`, `case_pose_resolver.py` (probably delete).
- Delete: `quino/services/workspace_composition.py`, `quino/services/case_diff_summary.py`.

- [ ] **Step 1: Delete the obsolete modules**

```bash
git rm quino/services/workspace_composition.py
git rm quino/services/case_diff_summary.py
```

- [ ] **Step 2: Rewrite `workspace_catalog.build_parameter_catalog(workspace)`**

It should walk every case's `model` to populate the catalog. The catalog is global on the `Workspace`; one entry per (case_id, entity_id, property). Or — since sketch and parameters are global — only walk the root case's model plus the workspace-level parameters. **Choose**: walk only root cases for the catalog; child-case overrides are not separately catalogued.

```python
# quino/services/workspace_catalog.py
from quino.domain.workspace import ParameterDescriptor, Workspace


def build_parameter_catalog(workspace: Workspace) -> dict[str, ParameterDescriptor]:
    out: dict[str, ParameterDescriptor] = {}
    for rid in workspace.root_case_ids:
        root = workspace.cases.get(rid)
        if root is None:
            continue
        # ... existing logic, but iterate root.model.* instead of project.model.*
    return out
```

- [ ] **Step 3: Update `run_invalidation.py`**

Replace anything walking `workspace.runs` with iteration over `case.runs`. Replace `_mark_set_stale(ws, ...)` with `_mark_set_stale(case, ...)`.

- [ ] **Step 4: Update `workspace_invalidation.py`, `workspace_staleness.py`, `workspace_snapshot.py`**

Remove `Baseline`/`WorkspacePose` references. They become thin wrappers over the new `Case` and `Workspace`.

- [ ] **Step 5: Delete `case_pose_resolver.py` if no longer needed**

If `case_pose_resolver` only existed to combine `WorkspacePose` with `Pose`, it's obsolete. Otherwise update.

Run: `grep -rn "from quino.services.case_pose_resolver" quino tests`
Expected: list call sites. If empty after Phase 6 cleanup, delete the file.

- [ ] **Step 6: Smoke test**

Run: `python -c "from quino.services.workspace_catalog import build_parameter_catalog; from quino.application.service import ApplicationService; s = ApplicationService(); s.new_workspace(); print(build_parameter_catalog(s.workspace))"`
Expected: empty dict / OK.

- [ ] **Step 7: Commit**

```bash
git add -A quino/services/
git commit -m "refactor(services): adapt catalog/invalidation/staleness; remove composition and diff_summary"
```

---

## Phase 8 — GUI workflow tree

### Task 21: Rewrite `workflow_tree_panel.py` as hierarchical case tree

**Files:**
- Rewrite: `quino/gui/panels/workflow_tree_panel.py`.
- Test: `tests/test_workflow_tree_panel_v2.py` (new).

- [ ] **Step 1: Write failing test (headless Qt)**

```python
# tests/test_workflow_tree_panel_v2.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtWidgets

from quino.application.service import ApplicationService
from quino.gui.panels.workflow_tree_panel import WorkflowTreePanel
from quino.services.case_cascading import CascadingEngine


@pytest.fixture
def app(qtbot):
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_panel_shows_root_case(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()
    items = panel.top_level_items()
    assert len(items) == 1
    assert items[0].text(0) == "Root"


def test_panel_shows_child_case_under_parent(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    engine = CascadingEngine(service.workspace)
    root_id = service.workspace.root_case_ids[0]
    engine.fork_case(root_id, "Child A")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()
    root_item = panel.top_level_items()[0]
    child_names = [root_item.child(i).text(0) for i in range(root_item.childCount())
                   if root_item.child(i).data(0, 0x0100) == "case"]  # role = "case"
    assert "Child A" in child_names
```

- [ ] **Step 2: Confirm failure**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_workflow_tree_panel_v2.py -v`
Expected: AttributeError / mismatch.

- [ ] **Step 3: Implement**

```python
# quino/gui/panels/workflow_tree_panel.py
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.workspace import Case

ROLE_NODE_KIND = QtCore.Qt.ItemDataRole.UserRole
ROLE_ID = QtCore.Qt.ItemDataRole.UserRole + 1


class WorkflowTreePanel(QtWidgets.QWidget):
    case_selected = QtCore.Signal(str)
    pose_selected = QtCore.Signal(str)
    analysis_selected = QtCore.Signal(str)
    run_selected = QtCore.Signal(str)

    def __init__(self, app_service: ApplicationService, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = app_service
        layout = QtWidgets.QVBoxLayout(self)
        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderLabels(["Workspace"])
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree)

    def refresh(self) -> None:
        self._tree.clear()
        ws = self._service.workspace
        if ws is None:
            return
        for root_id in ws.root_case_ids:
            root_case = ws.cases.get(root_id)
            if root_case is not None:
                item = self._build_case_item(root_case)
                self._tree.addTopLevelItem(item)

    def top_level_items(self) -> list[QtWidgets.QTreeWidgetItem]:
        return [self._tree.topLevelItem(i) for i in range(self._tree.topLevelItemCount())]

    def _build_case_item(self, case: Case) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([case.name])
        item.setData(0, ROLE_NODE_KIND, "case")
        item.setData(0, ROLE_ID, case.id)

        poses_node = QtWidgets.QTreeWidgetItem([f"Poses ({len(case.poses)})"])
        poses_node.setData(0, ROLE_NODE_KIND, "poses_group")
        for pose in case.poses:
            pose_item = QtWidgets.QTreeWidgetItem([pose.name])
            pose_item.setData(0, ROLE_NODE_KIND, "pose")
            pose_item.setData(0, ROLE_ID, pose.id)
            poses_node.addChild(pose_item)
        item.addChild(poses_node)

        analyses_node = QtWidgets.QTreeWidgetItem([f"Analyses ({len(case.analyses)})"])
        analyses_node.setData(0, ROLE_NODE_KIND, "analyses_group")
        for analysis in case.analyses:
            a_item = QtWidgets.QTreeWidgetItem([analysis.name])
            a_item.setData(0, ROLE_NODE_KIND, "analysis")
            a_item.setData(0, ROLE_ID, analysis.id)
            analyses_node.addChild(a_item)
        item.addChild(analyses_node)

        runs_node = QtWidgets.QTreeWidgetItem([f"Runs ({len(case.runs)})"])
        runs_node.setData(0, ROLE_NODE_KIND, "runs_group")
        for run in case.runs:
            r_item = QtWidgets.QTreeWidgetItem([f"{run.analysis_id} / {run.created_at[:10]} {run.status}"])
            r_item.setData(0, ROLE_NODE_KIND, "run")
            r_item.setData(0, ROLE_ID, run.id)
            runs_node.addChild(r_item)
        item.addChild(runs_node)

        children_node = QtWidgets.QTreeWidgetItem(["Child cases"])
        children_node.setData(0, ROLE_NODE_KIND, "children_group")
        ws = self._service.workspace
        if ws is not None:
            for cid, child_case in ws.cases.items():
                if child_case.parent_case_id == case.id:
                    children_node.addChild(self._build_case_item(child_case))
        item.addChild(children_node)
        return item

    def _on_item_clicked(self, item: QtWidgets.QTreeWidgetItem, _col: int) -> None:
        kind = item.data(0, ROLE_NODE_KIND)
        ent_id = item.data(0, ROLE_ID)
        if kind == "case" and ent_id:
            self.case_selected.emit(ent_id)
        elif kind == "pose" and ent_id:
            self.pose_selected.emit(ent_id)
        elif kind == "analysis" and ent_id:
            self.analysis_selected.emit(ent_id)
        elif kind == "run" and ent_id:
            self.run_selected.emit(ent_id)
```

- [ ] **Step 4: Confirm pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_workflow_tree_panel_v2.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/gui/panels/workflow_tree_panel.py tests/test_workflow_tree_panel_v2.py
git commit -m "feat(gui): hierarchical workflow tree over case-as-model"
```

---

### Task 22: Context menu (Fork / Delete / Rename / Compare)

**Files:**
- Modify: `quino/gui/panels/workflow_tree_panel.py`.
- Test: `tests/test_workflow_tree_panel_v2.py` (extend).

- [ ] **Step 1: Test fork via the panel triggers engine.fork_case**

```python
# append
def test_fork_via_context_menu(app, qtbot, monkeypatch):
    service = ApplicationService()
    service.new_workspace("Test")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()

    root_id = service.workspace.root_case_ids[0]
    # Simulate the action
    panel.fork_case(root_id, "Variant 1")
    panel.refresh()

    assert len(service.workspace.cases) == 2
    assert service.workspace.selected_case_id != root_id  # auto-switched
```

- [ ] **Step 2: Confirm failure**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_workflow_tree_panel_v2.py::test_fork_via_context_menu -v`
Expected: AttributeError.

- [ ] **Step 3: Implement panel methods**

```python
# add to WorkflowTreePanel
    def fork_case(self, parent_case_id: str, name: str) -> str:
        from quino.services.case_cascading import CascadingEngine
        engine = CascadingEngine(self._service.workspace)
        new_id = engine.fork_case(parent_case_id, name)
        self._service.workspace.selected_case_id = new_id
        self.case_selected.emit(new_id)
        return new_id

    def delete_case(self, case_id: str) -> None:
        ws = self._service.workspace
        # Collect descendants
        to_delete = {case_id}
        changed = True
        while changed:
            changed = False
            for cid, c in ws.cases.items():
                if c.parent_case_id in to_delete and cid not in to_delete:
                    to_delete.add(cid)
                    changed = True
        for cid in to_delete:
            ws.cases.pop(cid, None)
        ws.root_case_ids = [r for r in ws.root_case_ids if r in ws.cases]
        if ws.selected_case_id in to_delete:
            ws.selected_case_id = ws.root_case_ids[0] if ws.root_case_ids else None

    def rename_case(self, case_id: str, new_name: str) -> None:
        ws = self._service.workspace
        if case_id in ws.cases:
            ws.cases[case_id].name = new_name
```

Wire to context menu (`contextMenuEvent`) — straightforward `QMenu` with three actions calling these methods. Include a Qt `QInputDialog.getText` for the fork name.

- [ ] **Step 4: Confirm pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_workflow_tree_panel_v2.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/gui/panels/workflow_tree_panel.py tests/test_workflow_tree_panel_v2.py
git commit -m "feat(gui): workflow tree context menu (fork/delete/rename)"
```

---

## Phase 9 — GUI: badges + divergences dock + main window

### Task 23: Link status indicator widget

**Files:**
- Create: `quino/gui/widgets/link_status_indicator.py`.
- Test: `tests/test_link_status_indicator.py` (new).

- [ ] **Step 1: Write failing test**

```python
# tests/test_link_status_indicator.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from quino.gui.widgets.link_status_indicator import LinkStatusIndicator


def test_indicator_starts_in_linked_mode(qtbot):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ind = LinkStatusIndicator(state="linked")
    qtbot.addWidget(ind)
    assert ind.state() == "linked"


def test_indicator_state_can_change(qtbot):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ind = LinkStatusIndicator(state="linked")
    qtbot.addWidget(ind)
    ind.set_state("unlinked")
    assert ind.state() == "unlinked"
```

- [ ] **Step 2: Confirm failure**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_link_status_indicator.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# quino/gui/widgets/link_status_indicator.py
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

_GLYPHS = {"linked": "↺", "unlinked": "✎", "local": "+", "none": ""}
_TOOLTIPS = {
    "linked": "Linked to parent. Right-click to override.",
    "unlinked": "Override (unlinked). Right-click to re-link.",
    "local": "Locally created.",
    "none": "Root case — no parent.",
}


class LinkStatusIndicator(QtWidgets.QLabel):
    relink_requested = QtCore.Signal()
    override_requested = QtCore.Signal()

    def __init__(self, state: str = "none", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self._refresh()

    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        if state not in _GLYPHS:
            raise ValueError(f"Unknown link state: {state!r}")
        self._state = state
        self._refresh()

    def _refresh(self) -> None:
        self.setText(_GLYPHS[self._state])
        self.setToolTip(_TOOLTIPS[self._state])

    def _show_menu(self, pos):
        if self._state not in {"linked", "unlinked"}:
            return
        menu = QtWidgets.QMenu(self)
        if self._state == "linked":
            action = menu.addAction("Override in this case")
            if menu.exec(self.mapToGlobal(pos)) == action:
                self.override_requested.emit()
        else:
            action = menu.addAction("Re-link to parent")
            if menu.exec(self.mapToGlobal(pos)) == action:
                self.relink_requested.emit()
```

- [ ] **Step 4: Confirm pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_link_status_indicator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/gui/widgets/link_status_indicator.py tests/test_link_status_indicator.py
git commit -m "feat(gui): LinkStatusIndicator widget"
```

---

### Task 24: Divergences dock

**Files:**
- Create: `quino/gui/widgets/divergences_dock.py`.
- Test: `tests/test_divergences_dock.py`.

- [ ] **Step 1: Failing test**

```python
# tests/test_divergences_dock.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from quino.application.service import ApplicationService
from quino.domain.model import ScalarProperty
from quino.domain.types import Dimension
from quino.gui.widgets.divergences_dock import DivergencesDock
from quino.services.case_cascading import CascadingEngine


def _setup_divergence(service):
    service.new_workspace("Test")
    engine = CascadingEngine(service.workspace)
    root_id = service.workspace.root_case_ids[0]
    # Need at least one body in the root case for the test; new_workspace makes an empty model.
    # We'll inject one for the test.
    from quino.domain.model import Body, Marker
    from quino.domain.types import BodyType, MarkerType
    body = Body(
        id="b1", name="bar", type=BodyType.BAR,
        markers=[
            Marker(id="m1", name="A", type=MarkerType.STRUCTURAL,
                   x=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
                   y=ScalarProperty("0 mm", "mm", Dimension.LENGTH)),
            Marker(id="m2", name="B", type=MarkerType.STRUCTURAL,
                   x=ScalarProperty("100 mm", "mm", Dimension.LENGTH),
                   y=ScalarProperty("0 mm", "mm", Dimension.LENGTH)),
        ],
        edge_order=["m1", "m2"], closed_shape=False,
        mass=ScalarProperty("2 kg", "kg", Dimension.MASS),
    )
    service.workspace.cases[root_id].model.bodies.append(body)
    child_id = engine.fork_case(root_id, "Child")
    engine.edit_property(child_id, "b1", "mass", ScalarProperty("3 kg", "kg", Dimension.MASS))
    engine.edit_property(root_id, "b1", "mass", ScalarProperty("5 kg", "kg", Dimension.MASS))
    return child_id


def test_dock_lists_warnings_for_selected_case(qtbot):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    service = ApplicationService()
    child_id = _setup_divergence(service)
    dock = DivergencesDock(service)
    qtbot.addWidget(dock)
    dock.show_case(child_id)
    rows = dock.row_count()
    assert rows >= 1


def test_dock_keep_override_clears_warning(qtbot):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    service = ApplicationService()
    child_id = _setup_divergence(service)
    dock = DivergencesDock(service)
    qtbot.addWidget(dock)
    dock.show_case(child_id)
    dock.keep_override(0)
    assert dock.row_count() == 0
    assert service.workspace.cases[child_id].metadata.get("divergence_warnings", []) == []
```

- [ ] **Step 2: Confirm failure**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_divergences_dock.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# quino/gui/widgets/divergences_dock.py
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from quino.application.service import ApplicationService


class DivergencesDock(QtWidgets.QWidget):
    def __init__(self, app_service: ApplicationService, parent=None) -> None:
        super().__init__(parent)
        self._service = app_service
        self._case_id: str | None = None
        self._table = QtWidgets.QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Path", "Parent", "Child", "Action"])
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._table)

    def show_case(self, case_id: str) -> None:
        self._case_id = case_id
        self._refresh()

    def row_count(self) -> int:
        return self._table.rowCount()

    def _warnings(self) -> list[dict]:
        if self._case_id is None:
            return []
        case = self._service.workspace.cases.get(self._case_id)
        if case is None:
            return []
        return list(case.metadata.get("divergence_warnings", []))

    def _refresh(self) -> None:
        self._table.setRowCount(0)
        for i, w in enumerate(self._warnings()):
            self._table.insertRow(i)
            self._table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(w.get("path", ""))))
            self._table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(w.get("parent_value", ""))))
            self._table.setItem(i, 2, QtWidgets.QTableWidgetItem(str(w.get("child_value", ""))))
            btn = QtWidgets.QPushButton("Keep override")
            btn.clicked.connect(lambda _=False, idx=i: self.keep_override(idx))
            self._table.setCellWidget(i, 3, btn)

    def keep_override(self, idx: int) -> None:
        if self._case_id is None:
            return
        case = self._service.workspace.cases.get(self._case_id)
        if case is None:
            return
        warnings = case.metadata.get("divergence_warnings", [])
        if 0 <= idx < len(warnings):
            warnings.pop(idx)
            case.metadata["divergence_warnings"] = warnings
        self._refresh()
```

(The "Adopt parent" / "Re-link" actions are wired in Task 25 once main window is connected.)

- [ ] **Step 4: Confirm pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_divergences_dock.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/gui/widgets/divergences_dock.py tests/test_divergences_dock.py
git commit -m "feat(gui): DivergencesDock with Keep override action"
```

---

### Task 25: Main window — switch to Workspace, integrate dock + tree

**Files:**
- Modify: `quino/gui/main_window.py`.

This is a large mechanical change. Pattern: every `self.app_service.project.*` becomes either `self.app_service.workspace.*` or `self.app_service.current_case().*`.

- [ ] **Step 1: Replace project field**

Search and replace within `main_window.py`:
- `self.app_service.project` → `self.app_service.current_case()` for places reading model/poses/analyses/runs.
- `self.app_service.project` → `self.app_service.workspace` for places reading sketch/parameters/view_state.

After each replacement, eyeball the surrounding code: ensure case is non-None before dereferencing.

- [ ] **Step 2: Remove every `compose_project` / `effective_project` reference**

Run: `grep -n "compose_project\|effective_project" quino/gui/main_window.py`
Expected: empty after edits.

- [ ] **Step 3: Add the DivergencesDock to the layout**

Where other docks are added (Validation, Report):

```python
from quino.gui.widgets.divergences_dock import DivergencesDock

self._divergences_dock_widget = DivergencesDock(self.app_service)
self._divergences_dock = QtWidgets.QDockWidget("Divergences", self)
self._divergences_dock.setWidget(self._divergences_dock_widget)
self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self._divergences_dock)
```

Connect the workflow tree's `case_selected` signal to `self._divergences_dock_widget.show_case`.

- [ ] **Step 4: Connect tree signals**

```python
self.workflow_tree.case_selected.connect(self._on_case_selected)

def _on_case_selected(self, case_id: str):
    self.app_service.workspace.selected_case_id = case_id
    self._divergences_dock_widget.show_case(case_id)
    self.canvas.refresh()
    self.report_panel.refresh()
    # etc.
```

- [ ] **Step 5: Run the GUI tests that exist**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_gui.py -v 2>&1 | tail -20`
Expected: at least the smoke "open and close window" tests pass.

- [ ] **Step 6: Commit**

```bash
git add quino/gui/main_window.py
git commit -m "refactor(gui): main window over Workspace; integrate workflow tree + dock"
```

---

### Task 26: Canvas — render selected case's model

**Files:**
- Modify: `quino/gui/canvas.py`.

- [ ] **Step 1: Replace project references**

Same recipe as Task 25:
- `self.app_service.project.model` → `self.app_service.current_case().model`
- `self.app_service.project.sketch` → `self.app_service.workspace.sketch`
- `self.app_service.project.poses` → `self.app_service.current_case().poses`

Guard with `if case is None: return` at the start of each public method that mutates or paints.

- [ ] **Step 2: Smoke test**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_gui.py -v 2>&1 | tail -20`
Expected: same or fewer failures than after Task 25.

- [ ] **Step 3: Commit**

```bash
git add quino/gui/canvas.py
git commit -m "refactor(canvas): render selected case's model"
```

---

### Task 27: Run status widget, report panel, run comparison dialog

**Files:**
- Modify: `quino/gui/widgets/run_status_widget.py`.
- Modify: `quino/gui/widgets/report_panel.py`.
- Modify: `quino/gui/dialogs/run_comparison_dialog.py`.

For each:

- [ ] **Step 1: Replace flat run iteration with case-local iteration**

```python
# Before
runs = [r for r in workspace.runs if r.analysis_id == analysis_id]
# After
case = app_service.current_case()
runs = [r for r in case.runs if r.analysis_id == analysis_id] if case else []
```

- [ ] **Step 2: Run comparison dialog — iterate the case tree**

```python
def all_runs(workspace):
    for case in workspace.cases.values():
        for run in case.runs:
            yield case.id, run
```

Use this generator wherever the dialog previously walked `workspace.runs`.

- [ ] **Step 3: Smoke test**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_compare_runs_dialog.py -v`
Expected: PASS (or, if the test referenced the old layout, rewrite it now to use case-local runs).

- [ ] **Step 4: Commit**

```bash
git add quino/gui/widgets/run_status_widget.py quino/gui/widgets/report_panel.py quino/gui/dialogs/run_comparison_dialog.py
git commit -m "refactor(gui): widgets and dialogs read runs from selected case"
```

---

### Task 27b: Wire LinkStatusIndicator into property panels + Compare-with-parent action

**Files:**
- Modify: existing property-panel widgets (the ones rendering a body/joint/etc. property row — `quino/gui/widgets/property_panel.py` if present, otherwise the layout code inside `main_window.py` that lays out per-property rows).
- Modify: `quino/gui/panels/workflow_tree_panel.py` (add Compare action).

- [ ] **Step 1: Identify the property row builder**

Run: `grep -rn "ScalarProperty\|expected_dimension" quino/gui/widgets/ quino/gui/main_window.py | head -20`

Expected: a list of sites where individual ScalarProperty inputs are built. Pick the one that lays out the row (label + input). If property rows are built inline in `main_window.py`, extract the helper into `quino/gui/widgets/property_row.py` first (a small refactor) — otherwise skip the extraction.

- [ ] **Step 2: For each property row, prepend a `LinkStatusIndicator`**

```python
from quino.gui.widgets.link_status_indicator import LinkStatusIndicator

def build_property_row(case, entity_id, prop_name, value_widget):
    indicator = LinkStatusIndicator(state=_state_for(case, entity_id, prop_name))
    indicator.override_requested.connect(lambda: _on_override(case, entity_id, prop_name))
    indicator.relink_requested.connect(lambda: _on_relink(case, entity_id, prop_name))
    row = QtWidgets.QHBoxLayout()
    row.addWidget(indicator)
    row.addWidget(value_widget)
    return row


def _state_for(case, entity_id, prop_name) -> str:
    if case.overlay is None:
        return "none"
    entry = case.overlay.entities.get(entity_id)
    if entry is None:
        return "none"
    if entry.origin == "local":
        return "local"
    return "linked" if prop_name in entry.linked_properties else "unlinked"


def _on_override(case, entity_id, prop_name):
    if case.overlay is not None and entity_id in case.overlay.entities:
        case.overlay.entities[entity_id].linked_properties.discard(prop_name)


def _on_relink(case, entity_id, prop_name):
    # Find the parent and copy its value back
    # Implementation: use CascadingEngine helpers to look up parent and re-set value
    if case.overlay is None or entity_id not in case.overlay.entities:
        return
    case.overlay.entities[entity_id].linked_properties.add(prop_name)
    # The user should re-confirm by clicking the value; we don't change the value here
    # to avoid surprise. The icon now says "linked".
```

- [ ] **Step 3: Wire "Compare with parent" in the workflow tree context menu**

```python
# in WorkflowTreePanel.contextMenuEvent (where Fork/Delete/Rename live)
compare_action = menu.addAction("Compare with parent")
# enable only if case has a parent
case_id = item.data(0, ROLE_ID)
case = self._service.workspace.cases.get(case_id) if case_id else None
compare_action.setEnabled(case is not None and case.parent_case_id is not None)
if menu.exec(...) == compare_action:
    self.compare_with_parent(case_id)


def compare_with_parent(self, case_id: str) -> None:
    """Show the divergences dock filtered against the current parent state."""
    case = self._service.workspace.cases.get(case_id)
    if case is None or case.parent_case_id is None:
        return
    # Reuse the divergences dock — show structural diffs computed on demand
    self._compute_and_record_compare_warnings(case_id)
    self.case_selected.emit(case_id)


def _compute_and_record_compare_warnings(self, case_id: str) -> None:
    """Compare child.model against parent.model and APPEND warnings for current
    differences (in addition to any propagation-time warnings already there)."""
    from quino.services.case_overlay_validator import _entity_lookup
    case = self._service.workspace.cases[case_id]
    parent = self._service.workspace.cases[case.parent_case_id]
    diffs = []
    parent_index = _entity_lookup(parent)
    child_index = _entity_lookup(case)
    for ent_id, (parent_ent, cls) in parent_index.items():
        child_ent_tuple = child_index.get(ent_id)
        if child_ent_tuple is None:
            diffs.append({"kind": "missing_in_child", "path": f"entities/{ent_id}"})
            continue
        # Per-property check
        for f in cls.__dataclass_fields__:  # type: ignore[attr-defined]
            try:
                if getattr(parent_ent, f) != getattr(child_ent_tuple[0], f):
                    diffs.append({
                        "kind": "value_diff",
                        "path": f"entities/{ent_id}/{f}",
                        "parent_value": repr(getattr(parent_ent, f)),
                        "child_value": repr(getattr(child_ent_tuple[0], f)),
                    })
            except Exception:
                pass
    case.metadata["divergence_warnings"] = diffs
```

- [ ] **Step 4: Manual smoke**

```bash
QT_QPA_PLATFORM=offscreen python -m quino.gui examples/Active_Suspension_Validation.quino.json
```

(If the script can't run headless, just verify imports.)

- [ ] **Step 5: Commit**

```bash
git add quino/gui/widgets/link_status_indicator.py quino/gui/widgets/property_row.py \
        quino/gui/panels/workflow_tree_panel.py quino/gui/main_window.py
git commit -m "feat(gui): wire LinkStatusIndicator into property rows + Compare-with-parent action"
```

---

### Task 28: "Show parent diff" toggle on the canvas (deferred slot)

**Files:**
- Modify: `quino/gui/canvas.py` (add stub).

Keep this minimal — a checkbox in the toolbar that toggles a `self._show_parent_diff = bool`. Painting that uses this flag stays as a TODO comment until the rest of the redesign is shipping. This is acceptable because spec Section 4.4 says this overlay is optional.

- [ ] **Step 1: Add toolbar action**

In `canvas.py` (or the toolbar where it lives):

```python
self._show_parent_diff = False
self._toggle_diff_action = QtGui.QAction("Show parent diff", self)
self._toggle_diff_action.setCheckable(True)
self._toggle_diff_action.toggled.connect(self._on_toggle_diff)
self.toolbar.addAction(self._toggle_diff_action)

def _on_toggle_diff(self, on: bool) -> None:
    self._show_parent_diff = on
    self.refresh()
```

The paint code can read `self._show_parent_diff` but does not need to act on it yet.

- [ ] **Step 2: Commit**

```bash
git add quino/gui/canvas.py
git commit -m "feat(canvas): show-parent-diff toggle (rendering deferred)"
```

---

## Phase 10 — Test repair and example regeneration

### Task 29: Triage old tests

**Files:**
- Delete: tests listed in plan header "Deleted" list.
- Rewrite (start from blank): `tests/test_workspace.py`, `tests/test_workspace_api.py`, `tests/test_workspace_catalog.py`, `tests/test_workspace_invalidation.py`, `tests/test_workspace_runner.py`.

- [ ] **Step 1: Delete obsolete tests**

```bash
git rm tests/test_workspace_composition.py \
      tests/test_structural_diffs.py \
      tests/test_case_overlay_editing.py \
      tests/test_com_per_case_overrides.py \
      tests/test_case_diff_summary.py \
      tests/test_delta_ux.py \
      tests/test_scope_parity.py \
      tests/test_workspace_working_context.py \
      tests/test_case_pose_resolver.py
```

- [ ] **Step 2: Empty out rewriting candidates**

For each of `tests/test_workspace.py`, `test_workspace_api.py`, `test_workspace_catalog.py`, `test_workspace_invalidation.py`, `test_workspace_runner.py`:

Replace the file body with one minimal test that exercises the new model:

```python
# tests/test_workspace.py
from quino.domain.workspace import Workspace


def test_workspace_default_is_empty():
    ws = Workspace(id="w", name="x", schema_version="0.3.0")
    assert ws.cases == {}
    assert ws.root_case_ids == []
```

Add real coverage iteratively in later commits — for the redesign branch the goal is "green test suite" + targeted coverage of the new engine (already provided in `tests/test_case_cascading.py`).

- [ ] **Step 3: Run the whole suite**

Run: `pytest tests/ -q 2>&1 | tail -30`
Expected: a small number of failures pinpointing imports / fixtures. Fix each — typically import path updates or fixture setup that referenced `Project`.

- [ ] **Step 4: Commit**

```bash
git add -A tests/
git commit -m "test: delete obsolete diff-based tests; minimal stubs for rewritten suites"
```

---

### Task 30: Regenerate examples

**Files:**
- Modify: `scripts/build_suspension_example.py`, `scripts/build_kinematic_example.py`.
- Create (as needed): `scripts/build_double_pendulum_example.py`, `scripts/build_spring_oscillator_example.py`, `scripts/build_torsional_spring_pendulum_example.py`, `scripts/build_pantograph_example.py`, `scripts/build_scotch_yoke_example.py`, `scripts/build_four_bar_example.py`, `scripts/build_umbrella_example.py`, `scripts/build_controlled_mass_pid_example.py`, `scripts/build_slider_crank_with_sketch_example.py`.
- Output: regenerated `examples/*.quino.json`.

- [ ] **Step 1: Update `scripts/build_suspension_example.py`**

Open the script. Replace `Project` construction with:

```python
from quino.domain.workspace import Case, Workspace
from quino.domain.model import Model

# ... build model as before ...
root = Case(id="case-root", name="Suspension Baseline", model=model)
ws = Workspace(
    id="ws-suspension", name="Active Suspension Validation",
    schema_version="0.3.0",
    sketch=sketch,  # global
    parameters=parameters,  # global
    root_case_ids=["case-root"], cases={"case-root": root},
    selected_case_id="case-root",
)

# If the script previously created a Baseline + cases, translate to fork_case calls:
from quino.services.case_cascading import CascadingEngine
engine = CascadingEngine(ws)
ride_id = engine.fork_case("case-root", "Ride")
# Apply the case-specific edits as engine.edit_property calls

mapper.save(ws, Path("examples/Active_Suspension_Validation.quino.json"))
```

- [ ] **Step 2: Re-run the script**

Run: `python scripts/build_suspension_example.py`
Expected: writes `examples/Active_Suspension_Validation.quino.json` at schema `0.3.0`.

- [ ] **Step 3: Verify roundtrip**

Run:

```python
python -c "from quino.serialization.json_io import JsonMapper; ws = JsonMapper().load('examples/Active_Suspension_Validation.quino.json'); print('schema:', ws.schema_version, 'cases:', len(ws.cases))"
```

Expected: prints `schema: 0.3.0`, case count > 0.

- [ ] **Step 4: For each other example without a script: write one**

For Double_Pendulum, Spring_Oscillator, etc., write a minimal script that builds the Model programmatically (load the old example via a one-off helper that bypasses schema check, extract the Model, and re-emit as a new Workspace). Sample:

```python
# scripts/build_double_pendulum_example.py
from pathlib import Path
import json

from quino.domain.workspace import Case, Workspace
from quino.serialization.json_io import JsonMapper
# Construct the double pendulum from scratch using primitives in
# quino.domain.model — refer to the prior example's geometry as a template.

# (Body / Marker / Joint construction — see existing JSON for values)

model = ...  # build it
sketch = None
parameters = []
root = Case(id="case-root", name="Double Pendulum", model=model)
ws = Workspace(id="ws-dp", name="Double Pendulum", schema_version="0.3.0",
               sketch=sketch, parameters=parameters,
               root_case_ids=["case-root"], cases={"case-root": root},
               selected_case_id="case-root")
JsonMapper().save(ws, Path("examples/Double_Pendulum.quino.json"))
```

Run each script.

- [ ] **Step 5: Validate all examples open**

```python
import sys
from pathlib import Path
from quino.serialization.json_io import JsonMapper
mapper = JsonMapper()
errors = []
for p in Path("examples").glob("*.quino.json"):
    try:
        ws = mapper.load(p)
        assert ws.schema_version == "0.3.0"
    except Exception as e:
        errors.append((p.name, str(e)))
if errors:
    for name, msg in errors:
        print(f"FAIL {name}: {msg}")
    sys.exit(1)
print("All examples loaded.")
```

Save as `scripts/validate_examples.py` and run.

Expected: `All examples loaded.`

- [ ] **Step 6: Commit**

```bash
git add scripts/ examples/
git commit -m "feat(examples): regenerate all examples at schema 0.3.0"
```

---

## Phase 11 — Final sweep

### Task 31: Full test run and triage

- [ ] **Step 1: Run the full suite**

Run: `pytest tests/ -q 2>&1 | tail -40`
Expected: PASS, or a small list of remaining failures.

- [ ] **Step 2: Fix remaining failures one by one**

For each failure: open the test, decide:
- (a) was it testing the diff-based system? → delete the test.
- (b) is the behaviour it tests still valid? → rewrite to use the new model.

Commit each fix individually with a clear message.

- [ ] **Step 3: Smoke-launch the GUI**

```bash
python -m quino.gui examples/Active_Suspension_Validation.quino.json
```

Verify visually: workflow tree shows the cases hierarchically; selecting a case re-renders the canvas; right-click fork creates a child; editing a property in the parent updates the child; modifying a property in the child unlinks it.

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A
git commit -m "chore: final test repair sweep"
```

---

### Task 32: Merge prep

- [ ] **Step 1: Squash-merge readiness check**

Run: `git log --oneline main..HEAD | wc -l`
Expected: a number — record it.

- [ ] **Step 2: Update CLAUDE.md or README**

Open `CLAUDE.md`. Replace the section on the workspace/case model with a short description of the case-as-model architecture, pointing to the spec. Remove mentions of `Baseline`, `compose_project`, `WorkspacePose`.

- [ ] **Step 3: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for case-as-model redesign"
```

- [ ] **Step 4: Open PR (or merge to main, per your workflow)**

The redesign branch is ready. Single-developer single-rama workflow per spec Section 7.5.

---

## Acceptance check (matches spec §10)

After Task 32, verify:

1. [ ] All `examples/*.quino.json` open, render, and run in the new app at schema `0.3.0`.
2. [ ] Forking a case, editing properties in parent and child, observing cascade and divergence warnings works end-to-end.
3. [ ] `compose_project` and `workspace_composition.py` are not present in the codebase.
4. [ ] `validate_overlay` passes on all examples after load and after operations (write a small CLI script for this if useful).
5. [ ] All tests pass; deleted tests are removed cleanly; rewritten tests cover the new engine.
