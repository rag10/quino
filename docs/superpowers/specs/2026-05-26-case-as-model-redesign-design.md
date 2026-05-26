# Case-as-Model Redesign

**Date**: 2026-05-26
**Status**: Draft for review
**Schema bump**: `0.2.0` → `0.3.0` (breaking change, no autoupgrade)

## 1. Motivation

The current workspace stores each case as a structural diff against a baseline (`Case.added_entities`, `Case.removed_entity_ids`, `Case.reference_overrides`, `Case.invariant_values`). To read the model of a case, `compose_project()` deep-copies the base and re-applies the chain of diffs from the case's ancestry. The `Baseline` and `Case` dataclasses live side by side in `Workspace`; `Pose` exists both in `Project` and as `WorkspacePose` in `Workspace`; analyses and runs are stored in flat lists at workspace level, referencing cases by foreign-key ids.

This design has accumulated three concrete problems:

1. **Editing cases is fragile.** Diffs touch private deserialisers (`JsonMapper._body_from_dict`, etc.) and contain special cases for `CoMAnchor`, `BlockInstance.parameters`, joint metadata with `_deg` suffixes. Small edits routinely cause re-composition inconsistencies.
2. **Composition runs in every read.** `compose_project()` is O(depth × model size) and runs on every access. Validation (`_validate_workspace_override_scope`) also runs there. The composer module is ~660 LOC of branching logic that has to be understood whenever a new feature touches cases.
3. **Cohesion is broken.** Poses, analyses and runs all live as flat lists at the workspace level, joined to cases by foreign keys. "What does this case own?" requires manual joins across four lists.

This spec replaces the diff-based composition model with **case-as-model**: each case stores a complete `Model` plus a small parallel `CaseOverlay` that records which entities and properties are linked to the parent. Parent-to-child propagation becomes an explicit operation that runs on edit, not on read.

## 2. Architecture overview

### 2.1 Conceptual change

- A case is a bundle: `Model` + poses + analyses + runs + outputs + `CaseOverlay`. The bundle is autonomous — reading a case requires no recomposition.
- The `CaseOverlay` is a parallel structure that records, for each entity and pose in the case's model, whether it is inherited from the parent and which of its properties are linked.
- Baseline is no longer a separate concept; a root case (a case with `parent_case_id is None`) plays the role.
- Cross-case shared state (sketch, parameters, view) lives at the `Workspace` level.

### 2.2 Cascading semantics

- Parent edits propagate automatically to descendants whose overlay has the corresponding property marked as `linked`.
- A descendant property marked as `unlinked` (the child has its own override) is never silently overwritten; instead, a divergence warning is recorded against the descendant.
- A descendant entity created locally (`origin="local"`) is never overwritten by parent propagation.
- An entity deleted by the parent propagates as deletion in descendants only if the descendant has not customised it; otherwise the descendant keeps it as `origin="local"` with a divergence warning.

### 2.3 What disappears

- `compose_project()` and the entire `quino/services/workspace_composition.py`.
- `Baseline` dataclass and all references to baseline-specific concepts in code and serialisation.
- `WorkspacePose` (merged into `Pose`).
- `Project` dataclass (merged into `Workspace`).
- `Case.added_entities`, `Case.removed_entity_ids`, `Case.reference_overrides`, `Case.removed_connections`, `Case.invariant_values`, `Case.model_snapshot_id`, `Case.baseline_id`.
- `Workspace.baselines`, `Workspace.model_snapshots`, `Workspace.promotion_history`, `Workspace.active_baseline_id`, flat `Workspace.poses` / `Workspace.analyses` / `Workspace.runs`.
- The scope validator (`_validate_workspace_override_scope`).
- `approval_status` / `approved_run_id` (no active code consumes them).

### 2.4 What is new

- `Workspace` becomes the root container (replaces `Project`) and serialises directly to `.quino.json`.
- `Case` bundles model + poses + analyses + runs + overlay.
- `CaseOverlay` and `EntityOverlay` carry the linked/unlinked metadata.
- `quino/services/case_cascading.py` implements five mutation operations.
- `quino/services/case_overlay_validator.py` implements `validate_overlay` and `rebuild_overlay`.
- `quino/services/cascade_property_registry.py` defines the set of cascadable properties per entity type.

## 3. Data model

### 3.1 Workspace

```python
@dataclass(slots=True)
class Workspace:
    id: str
    name: str
    schema_version: str            # "0.3.0"

    # Cross-case shared state
    sketch: Sketch | None = None
    parameters: list[Parameter] = field(default_factory=list)
    parameter_catalog: dict[str, ParameterDescriptor] = field(default_factory=dict)
    view_state: ViewState = field(default_factory=ViewState)
    gravity_default: GravityLoad | None = None

    # Case tree
    root_case_ids: list[str] = field(default_factory=list)
    cases: dict[str, Case] = field(default_factory=dict)

    # UI / session state
    selected_case_id: str | None = None
    selected_pose_id: str | None = None      # local id within selected case
    selected_analysis_id: str | None = None  # local id within selected case

    metadata: dict[str, Any] = field(default_factory=dict)
```

### 3.2 Case

```python
@dataclass(slots=True)
class Case:
    id: str
    name: str
    description: str = ""

    parent_case_id: str | None = None  # None ⇒ root case

    # The cohesive bundle
    model: Model = field(default_factory=Model)
    poses: list[Pose] = field(default_factory=list)
    analyses: list[Analysis] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)
    sensor_outputs: dict[str, SensorOutput] = field(default_factory=dict)
    reaction_outputs: dict[str, ReactionOutput] = field(default_factory=dict)

    overlay: CaseOverlay | None = None  # None for root cases

    # Copied from parent at fork time, local thereafter
    tolerances: dict[str, Tolerance] = field(default_factory=dict)
    metrics: dict[str, MetricDefinition] = field(default_factory=dict)

    metadata: dict[str, Any] = field(default_factory=dict)
```

### 3.3 Pose (consolidated)

```python
@dataclass(slots=True)
class Pose:
    id: str
    name: str
    body_poses: dict[str, BodyPose] = field(default_factory=dict)
    initial_velocities: dict[str, float] = field(default_factory=dict)
    parent_pose_id: str | None = None  # chaining within the same case
    is_default: bool = False
    requires_recompute: bool = True
    solve_failed: bool = False
    metadata: Metadata = field(default_factory=Metadata)
```

### 3.4 Analysis (simplified)

```python
@dataclass(slots=True)
class Analysis:
    id: str
    name: str
    analysis_type: str = "dynamic"
    pose_id: str | None = None     # local id within the same case
    config: AnalysisConfig = field(default=None)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 3.5 Run

`Run` is preserved structurally as in current `workspace.py`. Its `analysis_id` is interpreted as local to the owning case. Runs are never cascaded; they are always `origin="local"` and never appear in `CaseOverlay`.

### 3.6 CaseOverlay

```python
@dataclass(slots=True)
class EntityOverlay:
    origin: str                                  # "inherited" | "local"
    linked_properties: set[str] = field(default_factory=set)
    # Convention: origin="local" ⇒ linked_properties == ∅

@dataclass(slots=True)
class CaseOverlay:
    # Entities of the Model (bodies, joints, sliders, drivers, loads, sensors,
    # springs, markers, block_instances). Keyed by entity id (or instance_id).
    entities: dict[str, EntityOverlay] = field(default_factory=dict)
    deleted_inherited_entity_ids: set[str] = field(default_factory=set)

    # Control graph connections (no stable id; keyed by 4-tuple).
    inherited_connections: set[tuple[str, str, str, str]] = field(default_factory=set)
    deleted_inherited_connections: set[tuple[str, str, str, str]] = field(default_factory=set)

    # Poses
    poses: dict[str, EntityOverlay] = field(default_factory=dict)
    deleted_inherited_pose_ids: set[str] = field(default_factory=set)
```

Analyses, runs, tolerances and metrics do **not** appear in the overlay (they are always local).

### 3.7 Cascadable properties

The set of properties considered cascadable per entity type is defined by `cascade_property_registry.py`. The rule of thumb is:

- `ScalarProperty` fields, `Expression` fields, primitive fields (name, color, visible, closed_shape), `Metadata.values`, `Style`, and auxiliary dataclass fields (`JointEndpoint`, `SpringEndpoint`, `CoMAnchor`, `GravityLoad`) are cascadable.
- `id` and structural list fields (`Body.markers`, `Body.edge_order`) are **not** cascadable — they define identity / topology. Markers are themselves cascadable as separate entities in `overlay.entities`.

## 4. Cascading engine

`quino/services/case_cascading.py` exposes five operations. All mutations of the workspace go through these — no direct mutation of `Case.model` or `Case.overlay` from outside the module. This is the structural invariant that keeps the overlay consistent.

### 4.1 `edit_property(case_id, entity_id, prop, new_value)`

In `case_id`:
1. Set the new value on the entity.
2. `case.overlay.entities[entity_id].linked_properties.discard(prop)`.

Recursively, for each descendant `H`:
- If `H` has the entity with `origin="inherited"` and `prop in linked_properties`: apply the same value in `H`; recurse to `H`'s descendants.
- If `H` has the entity but `prop` is unlinked: record a divergence warning in `H.metadata["divergence_warnings"]` (parent value, child value, path). Do **not** modify `H`. Do **not** recurse into `H`'s descendants (the override in `H` is the cascade ceiling).
- If `H` has the entity in `deleted_inherited_entity_ids`: skip.

### 4.2 `add_entity(case_id, entity, domain)`

In `case_id`:
1. Append to the corresponding domain list in `case.model`.
2. `case.overlay.entities[entity.id] = EntityOverlay(origin="local", linked_properties=∅)`.

Descendants are **not** retroactively updated. The new entity is local to the case where it was added. A subsequent `fork_case` from this case will copy the entity into the new child as `origin="inherited"`.

### 4.3 `remove_entity(case_id, entity_id)`

In `case_id`:
- If `origin="local"`: remove from model and overlay.
- If `origin="inherited"`: remove from model, add `entity_id` to `case.overlay.deleted_inherited_entity_ids`.
- Compute dependents (joints attached, drivers, loads, sensors, springs) and recursively apply `remove_entity` for each.

Recursively, for each descendant `H`:
- If the entity in `H` is `origin="inherited"`, fully linked, and value-identical to the parent: silently remove from `H` as well.
- Otherwise (`H` has overrides or local additions touching it): keep the entity in `H`, flip its `origin` to `"local"`, clear `linked_properties`, record a divergence warning.
- If `H` already lists it in `deleted_inherited_entity_ids`: no-op.

### 4.4 `fork_case(parent_case_id, name) -> new_case_id`

1. Create new `Case H` with `H.parent_case_id = parent_case_id`.
2. `H.model` ← deep copy of parent's model (ids preserved — they are the basis of cascading).
3. `H.poses` ← deep copy of parent's poses.
4. `H.analyses = []`, `H.runs = []`, `H.sensor_outputs = {}`, `H.reaction_outputs = {}` (locals are not copied at fork).
5. `H.tolerances` and `H.metrics` ← deep copy of parent's (heritable at fork, local thereafter).
6. `H.overlay` constructed fresh: every entity has `origin="inherited"` with `linked_properties = registry.cascadable(entity_type)`; every pose similarly; `inherited_connections` mirrors the parent's control graph connections; all `deleted_inherited_*` sets empty.

After fork, `H` is structurally identical to its parent and fully linked. The GUI switches `selected_case_id` to `H` (see Section 5.2).

### 4.5 `reparent_case(case_id, new_parent_case_id | None)`

Not exposed in the GUI for v1. Available internally and for `rebuild_overlay`. Steps:

1. Validate no cycle would form.
2. If `new_parent_case_id is None`: drop overlay, case becomes a root case.
3. Else: rebuild overlay by structural comparison against the new parent (see 4.7). Records a user-facing warning about loss of "intentional override at same value" semantics.

### 4.6 Invariants

After every operation the engine guarantees:

1. **Model ↔ overlay.entities bijection**: every entity in the model has exactly one entry in `overlay.entities`; no orphans.
2. **Origin coherence**: `origin="local"` ⇒ `linked_properties == ∅`.
3. **Parent-child consistency**: an `origin="inherited"` entry in `H` corresponds to an entity present in the parent's model.
4. **No cycles in parent chain**.
5. **Stable ids**: an `origin="inherited"` entry's id matches the parent's entity id verbatim.

`case_overlay_validator.validate_overlay(case, parent)` walks all rules. Run in tests always; runnable in production via a debug flag.

### 4.7 `rebuild_overlay(case, parent)`

Reconstructs an overlay from scratch by comparing `case.model` against `parent.model`:
- Same id, value-equal: `origin="inherited"`, `linked_properties=all cascadable`.
- Same id, value-different: `origin="inherited"`, `linked_properties=∅`.
- Only in child: `origin="local"`.
- Only in parent: added to `deleted_inherited_entity_ids` of child.

This is a recovery / migration utility. It loses the distinction between "intentional override at same value" and "never touched", but is acceptable as a fallback.

### 4.8 Scope validation

The previous concept of "invariant vs variable parameter" (encoded in `Baseline.invariant_parameter_keys` and `ParameterDescriptor.tag`) is no longer enforced at composition time. The notion can resurface in the GUI as:

- Visual markers on properties (gray = "this is a project constant by convention") driven by `ParameterDescriptor.tag`.
- An optional save-time linter that warns if certain paths differ across cases.

Both are out of scope of this redesign.

## 5. GUI

### 5.1 Workflow tree (panel)

Replaces the flat lists (Baselines / Cases / Poses / Analyses / Runs) with a real case tree, rooted at `Workspace.root_case_ids`. Each case node expands to show its poses, analyses, runs and child cases. The previous "Baselines" concept disappears from the UI — a root case is just a case with no parent.

Per-node badges:

- `↺` linked to parent
- `✎` unlinked / locally modified
- `+` added locally
- `⊘` inherited but deleted locally
- `⚠ N` outstanding divergence warnings (count next to the case name)

### 5.2 Selection

`Workspace` carries three id fields: `selected_case_id`, `selected_pose_id`, `selected_analysis_id`. The latter two are interpreted as local ids inside the selected case. Switching cases is O(1) — the canvas re-renders against `case.model`, no composition runs.

After `fork_case`, the GUI automatically sets `selected_case_id` to the new child.

### 5.3 Property panel (per-entity)

Each property displays a link icon to its left:

- `↺` (blue) linked. Hover: shows parent value. Right-click → "Override here" (marks unlinked without changing value).
- `✎` (orange) unlinked. Hover: shows parent value and whether it diverges. Right-click → "Re-link to parent" (with confirmation if values differ).
- `+` (green) entity created locally.
- No icon: root case.

Editing a property automatically unlinks it (with no confirmation prompt — editing is the expected user action; the icon update is the informative feedback).

### 5.4 Canvas overlay (optional toggle)

Toolbar button **Show parent diff**, off by default. When on:

- `origin="local"` entities drawn with a green halo.
- `origin="inherited"` with at least one unlinked property: orange halo.
- `deleted_inherited_entity_ids` of the parent: drawn as gray ghosts (only as informational — they're not in this case's model anymore).

### 5.5 Divergences dock

A docked panel (sibling tab to Validation / Report). Lists all outstanding `case.metadata["divergence_warnings"]` for the selected case:

| Path | Parent value | Child value | Actions |
|---|---|---|---|
| bodies/body123/mass | 5 kg | 2 kg (override) | Adopt parent / Keep override / Re-link |
| poses/pose_default/body_poses/bodyA/angle | 30° | 25° (override) | Adopt parent / Keep override / Re-link |
| bodies/bodyD (parent deleted) | — | exists locally | Delete here too / Convert to local |

Actions:

- **Adopt parent**: copies parent value, keeps property unlinked, clears warning.
- **Keep override**: clears warning, value unchanged. User acknowledges.
- **Re-link**: copies parent value, re-marks linked, clears warning.
- **Convert to local**: only for "parent deleted" warnings — flips `origin` to `"local"`.

Warnings live in `case.metadata["divergence_warnings"]` (a queue of pending user tasks, not a model state). The engine only adds; the GUI resolves.

### 5.6 New UI operations

- Right-click on a case in the tree → Fork, Delete, Rename, Compare with parent.
- Toggle "Show parent diff" in canvas toolbar.

Reparenting and root-cloning are not exposed in v1.

### 5.7 Simplifications removed from current GUI

- No more distinction between Baselines and Cases.
- No more "active baseline + active case" dual selection — only `selected_case_id`.
- Run status widget filters by `selected_case_id` only.
- Run comparison dialog iterates the case tree rather than a flat run list.

## 6. Serialisation

### 6.1 Schema version

- Current: `0.2.0`.
- New: `0.3.0`.
- `JsonMapper.load()` raises `UnsupportedSchemaError` for schema < `0.3.0` with a clear message. No autoupgrade.

### 6.2 File layout

The `.quino.json` root is a `Workspace`. Example shape:

```json
{
  "schema_version": "0.3.0",
  "id": "...",
  "name": "Suspension Validation",
  "sketch": { "...": "..." },
  "parameters": [],
  "parameter_catalog": {},
  "view_state": {},
  "gravity_default": null,
  "selected_case_id": "case-A",
  "selected_pose_id": "pose-default",
  "selected_analysis_id": null,
  "root_case_ids": ["case-A"],
  "cases": {
    "case-A": {
      "id": "case-A",
      "name": "Baseline",
      "parent_case_id": null,
      "model": {},
      "poses": [],
      "analyses": [],
      "runs": [],
      "sensor_outputs": {},
      "reaction_outputs": {},
      "overlay": null,
      "tolerances": {},
      "metrics": {},
      "metadata": {}
    },
    "case-B": {
      "id": "case-B",
      "name": "High speed",
      "parent_case_id": "case-A",
      "model": {},
      "overlay": {
        "entities": {
          "body123": { "origin": "inherited", "linked_properties": ["mass", "name"] }
        },
        "deleted_inherited_entity_ids": [],
        "inherited_connections": [],
        "deleted_inherited_connections": [],
        "poses": {},
        "deleted_inherited_pose_ids": []
      }
    }
  },
  "metadata": {}
}
```

### 6.3 Stability conventions

- `set[str]` and `set[tuple]` are serialised as alphabetically sorted lists, for git-diff stability.
- `EntityOverlay.linked_properties` is serialised as a sorted list of strings.

## 7. Migration

### 7.1 What is demolished

| Target | Action |
|---|---|
| `quino/services/workspace_composition.py` | Deleted (~660 LOC) |
| `compose_project`, `compose_project_hash` | Deleted; all call sites updated |
| `Baseline` dataclass + serialisers | Deleted |
| `WorkspacePose` dataclass + serialisers | Deleted (merged into `Pose`) |
| `Project` dataclass | Deleted (replaced by `Workspace` as root) |
| `Case.added_entities`, `Case.removed_entity_ids`, `Case.reference_overrides`, `Case.removed_connections`, `Case.invariant_values`, `Case.model_snapshot_id`, `Case.baseline_id` | Deleted |
| `Workspace.baselines`, `Workspace.model_snapshots`, `Workspace.promotion_history`, `Workspace.active_baseline_id`, flat `Workspace.poses`/`analyses`/`runs`, `Workspace.active_case_id` | Deleted |
| `Workspace.next_sequence` | Deleted (auto-numbering uses `IdService`; no shared counter is needed) |
| `_validate_workspace_override_scope` | Deleted |
| `Baseline.approval_status` / `approved_run_id` | Deleted (no active code path consumes them) |
| `tests/test_workspace_composition.py`, `tests/test_structural_diffs.py`, `tests/test_case_overlay_editing.py`, `tests/test_com_per_case_overrides.py` | Deleted |
| `tests/test_workspace_catalog.py` | Rewritten against new Workspace |

### 7.2 What is created

| Target | Purpose |
|---|---|
| `quino/services/case_cascading.py` | Engine with five operations |
| `quino/services/case_overlay_validator.py` | `validate_overlay`, `rebuild_overlay` |
| `quino/services/cascade_property_registry.py` | Per-type cascadable property sets |
| `quino/domain/workspace.py` (rewritten) | New dataclasses |

### 7.3 Code touched (severity)

| Module | Severity |
|---|---|
| `quino/domain/workspace.py` | High (rewrite) |
| `quino/domain/model.py` | Medium (remove `Project`, move `Pose`) |
| `quino/serialization/json_io.py` | High (root-level rewrite) |
| `quino/application/service.py` | High |
| `quino/application/_context.py` | Medium |
| `quino/application/commands/*.py` | High (mutate via cascading engine) |
| `quino/services/workspace_runner.py`, `run_executor.py`, `case_pose_resolver.py` | Medium |
| `quino/services/workspace_catalog.py` | Low |
| `quino/analysis/*_runner.py` | Medium |
| `quino/gui/panels/workflow_tree_panel.py` | High (hierarchical tree) |
| `quino/gui/main_window.py` | High (all `project.*` → `workspace.cases[selected].*`) |
| `quino/gui/canvas.py` | Medium (renders selected case's model; optional diff overlay) |
| `quino/gui/widgets/run_status_widget.py`, `report_panel.py` | Low |
| `quino/gui/dialogs/run_comparison_dialog.py` | Low |
| Tests | High (≈30 files updated, 5–10 deleted) |

Rough estimate: 3,000–5,000 LOC touched. Affected layers are domain, services, application, GUI. Solvers, sketch solver and the mechanism domain are untouched.

### 7.4 Examples regeneration

All `examples/*.quino.json` (11 files) are regenerated to schema `0.3.0`. Existing scripts under `scripts/build_*_example.py` are updated; missing scripts are written for examples that lack one (Double_Pendulum variants, Spring_Oscillator, Torsional_Spring_Pendulum).

### 7.5 Migration mode

Single long-running branch `redesign/case-as-model`. No feature flag, no temporary compatibility shim. The branch contains all changes and merges once when complete.

### 7.6 Suggested execution order

(High-level; the detailed plan is the next document.)

1. Domain dataclasses (`Workspace`, `Case`, `CaseOverlay`, `EntityOverlay`, consolidated `Pose`); delete `Project`, `Baseline`, `WorkspacePose`.
2. `cascade_property_registry.py`.
3. `case_cascading.py` (five operations) with unit tests.
4. `case_overlay_validator.py` with `validate_overlay` and `rebuild_overlay`.
5. `json_io.py` adapted; round-trip tests.
6. `ApplicationService` and command-services adapted to the engine.
7. Runners receive `Case` directly.
8. Workflow tree rewritten as hierarchical.
9. Badges and divergences dock.
10. Remaining GUI (main_window, canvas, dialogs).
11. Regenerate examples.

Each step ships with passing tests before the next begins.

## 8. Risks and known limitations

1. **Mass cascade on `remove_entity`** in a deeply forked root case can produce many deep copies. Mitigation: measure; add a confirmation dialog if a single operation touches more than N descendants.
2. **Control graph connection matching** relies on stable instance ids; renaming an `instance_id` of a `BlockInstance` would break the overlay's `inherited_connections` set. Convention: instance ids are immutable after creation.
3. **`rebuild_overlay` loses intentionality**: "override at same value" cannot be distinguished from "untouched, value coincides with parent". Documented limitation; only used in recovery and reparenting.
4. **Large workspace JSON sizes**: each case stores a full model. For workspaces with many cases this multiplies disk size compared to the diff-based format. Acceptable for current mechanism sizes (tens of KB per model). Revisit only if a real workspace exceeds practical limits.
5. **Long-running redesign branch** without a feature flag means the GUI is non-functional while in progress. Accepted as a single-developer trade-off for cleanliness.

## 9. Out of scope

- Refactor of `canvas.py` (5850 LOC) and `main_window.py` (4532 LOC) beyond what the redesign requires.
- Plotting, metrics, sweep editor: structurally unchanged (adapted to receive a `Case`).
- Sketch solver (Solvespace) untouched.
- Exudyn integration untouched.
- Cross-case parameter sweeps (sweeping a single `Parameter` across cases). Parameters are global; if cross-case sweeps are needed later, that is a separate redesign.
- Reparenting and root-cloning operations in the GUI (the engine supports reparenting internally for recovery).

## 10. Acceptance criteria

The redesign is complete when:

1. All `examples/*.quino.json` open, render, and run in the new app at schema `0.3.0`.
2. Forking a case, editing properties in parent and child, and observing cascade / divergence warnings works end-to-end through the GUI.
3. `compose_project` and `workspace_composition.py` are deleted from the codebase.
4. `validate_overlay` passes on all examples after load and after any user operation.
5. All tests pass; deleted tests are removed cleanly; rewritten tests cover the new engine.
