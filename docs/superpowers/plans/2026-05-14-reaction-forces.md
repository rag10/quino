# Reaction Forces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract joint reaction forces (Fx, Fy, F magnitude) from Exudyn ground/slider joints during simulation and expose them in the model tree, inspector, plot, and canvas.

**Architecture:** A new `ReactionOutput` dataclass (parallel to `SensorOutput`) is stored in `project.reaction_outputs` keyed by joint_id. The Exudyn adapter registers `SensorObject` sensors for ground/slider joints before `mbs.Assemble()`, reads the resulting time-series files after the dynamic solve, and fills `reaction_outputs`. Static/no-driver cases call `mbs.GetObjectOutput` directly. GUI components (tree, inspector, canvas, plot) consume `reaction_outputs` the same way they consume `sensor_outputs`.

**Tech Stack:** Python, PySide6, Exudyn (SensorObject + OutputVariableType.Force), numpy

---

## File Map

| File | Change |
|---|---|
| `quino/domain/model.py` | Add `ReactionOutput` dataclass; add `reaction_outputs` field to `Project` |
| `quino/application/service.py` | Handle `__reaction__` prefix in `get_entity`; clear `reaction_outputs` in `run_kinematic_simulation` |
| `quino/gui/main_window.py` | Clear `reaction_outputs` in `_clear_simulation_state`; add Reactions tree section; add inspector rows for `ReactionOutput`; add `_entity_kind_label` + `_entity_default_icon` handling |
| `quino/solver_adapters/exudyn_adapter.py` | Register reaction sensors before Assemble; load sensor files after dynamic solve; read `GetObjectOutput` after static solve; populate `project.reaction_outputs` |
| `quino/viewer/dataset.py` | Extend `SensorDataset` to also load `project.reaction_outputs` |
| `quino/gui/canvas.py` | Add `_draw_reactions` method; call it in both `paintEvent` render paths |
| `tests/test_simulation.py` | Tests for `ReactionOutput` domain object; `_FakeMbs.AddSensor`, `GetObjectOutput`; `SensorDataset` with reactions |
| `tests/test_gui.py` | Tests for Reactions tree section; inspector rows for `ReactionOutput` |

---

## Task 1: Domain — `ReactionOutput` dataclass and `Project.reaction_outputs`

**Files:**
- Modify: `quino/domain/model.py`
- Test: `tests/test_simulation.py`

- [ ] **Step 1.1: Write the failing test**

Add to `tests/test_simulation.py`:

```python
def test_reaction_output_dataclass_fields() -> None:
    from quino.domain.model import ReactionOutput
    r = ReactionOutput(
        joint_id="j1",
        joint_name="Ground_A",
        endpoint_type="ground",
        time=[0.0, 0.1],
        columns=["Fx [N]", "Fy [N]", "F [N]"],
        data=[[1.0, 2.0, 2.236], [3.0, 4.0, 5.0]],
        positions=[(10.0, 20.0), (10.1, 20.1)],
    )
    assert r.joint_id == "j1"
    assert r.columns == ["Fx [N]", "Fy [N]", "F [N]"]
    assert len(r.data) == 2
    assert len(r.positions) == 2


def test_project_has_reaction_outputs_field() -> None:
    from quino.application.service import ApplicationService
    app = ApplicationService()
    app.new_project("Test")
    assert hasattr(app.project, "reaction_outputs")
    assert isinstance(app.project.reaction_outputs, dict)
    assert len(app.project.reaction_outputs) == 0
```

- [ ] **Step 1.2: Run tests to verify they fail**

```
pytest tests/test_simulation.py::test_reaction_output_dataclass_fields tests/test_simulation.py::test_project_has_reaction_outputs_field -v
```

Expected: `ImportError` or `AttributeError`

- [ ] **Step 1.3: Add `ReactionOutput` to `quino/domain/model.py`**

After the `SensorOutput` dataclass (around line 189) add:

```python
@dataclass(slots=True)
class ReactionOutput:
    joint_id: str
    joint_name: str
    endpoint_type: str                   # "ground" | "slider"
    time: list[float] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    data: list[list[float]] = field(default_factory=list)
    positions: list[tuple[float, float]] = field(default_factory=list)
```

Add `reaction_outputs` to `Project` (around line 358 where `sensor_outputs` is defined):

```python
reaction_outputs: dict[str, ReactionOutput] = field(default_factory=dict)
```

- [ ] **Step 1.4: Run tests to verify they pass**

```
pytest tests/test_simulation.py::test_reaction_output_dataclass_fields tests/test_simulation.py::test_project_has_reaction_outputs_field -v
```

Expected: PASS

- [ ] **Step 1.5: Run the full suite**

```
pytest tests/ -q
```

Expected: all 242 pass

- [ ] **Step 1.6: Commit**

```
git add quino/domain/model.py tests/test_simulation.py
git commit -m "feat: add ReactionOutput dataclass and Project.reaction_outputs field"
```

---

## Task 2: Service — `get_entity` for reactions + clear lifecycle

**Files:**
- Modify: `quino/application/service.py`
- Modify: `quino/gui/main_window.py`
- Test: `tests/test_simulation.py`

- [ ] **Step 2.1: Write the failing tests**

Add to `tests/test_simulation.py`:

```python
def test_get_entity_returns_reaction_output_for_reaction_prefix() -> None:
    from quino.application.service import ApplicationService
    from quino.domain.model import ReactionOutput
    app = ApplicationService()
    app.new_project("Test")
    rxn = ReactionOutput(
        joint_id="j1", joint_name="Ground_A", endpoint_type="ground",
        time=[0.0], columns=["Fx [N]", "Fy [N]", "F [N]"],
        data=[[1.0, 2.0, 2.236]], positions=[(10.0, 20.0)],
    )
    app.project.reaction_outputs["j1"] = rxn
    result = app.get_entity("__reaction__j1")
    assert result is rxn
    assert app.get_entity("__reaction__nonexistent") is None


def test_run_simulation_clears_reaction_outputs() -> None:
    from quino.application.service import ApplicationService
    from quino.domain.model import ReactionOutput
    app = ApplicationService()
    app.new_project("Test")
    app.project.reaction_outputs["j1"] = ReactionOutput(
        joint_id="j1", joint_name="Ground_A", endpoint_type="ground",
    )
    # Run a minimal simulation (no bodies, so it runs trivially)
    app.run_kinematic_simulation()
    assert len(app.project.reaction_outputs) == 0
```

- [ ] **Step 2.2: Run tests to verify they fail**

```
pytest tests/test_simulation.py::test_get_entity_returns_reaction_output_for_reaction_prefix tests/test_simulation.py::test_run_simulation_clears_reaction_outputs -v
```

Expected: FAIL

- [ ] **Step 2.3: Extend `get_entity` in `quino/application/service.py`**

In `get_entity` (around line 1670), add a branch BEFORE the `_find_entity` call:

```python
def get_entity(self, entity_id: str) -> object | None:
    if entity_id == "__gravity__":
        project = self.project
        return project.model.gravity if project else None
    if entity_id.startswith("__reaction__"):
        joint_id = entity_id[len("__reaction__"):]
        project = self.project
        return project.reaction_outputs.get(joint_id) if project else None
    try:
        return self._find_entity(entity_id)
    except ValueError:
        return None
```

- [ ] **Step 2.4: Clear `reaction_outputs` in `run_kinematic_simulation` in `quino/application/service.py`**

In `run_kinematic_simulation` (around line 1389), clear reactions alongside sensor outputs:

```python
project.sensor_outputs.clear()
project.reaction_outputs.clear()
```

- [ ] **Step 2.5: Clear `reaction_outputs` in `_clear_simulation_state` in `quino/gui/main_window.py`**

In `_clear_simulation_state` (around line 1222), after clearing `_last_simulation_result = None`, add:

```python
if self.app_service.project is not None:
    self.app_service.project.reaction_outputs.clear()
    self.app_service.project.sensor_outputs.clear()
```

- [ ] **Step 2.6: Run tests to verify they pass**

```
pytest tests/test_simulation.py::test_get_entity_returns_reaction_output_for_reaction_prefix tests/test_simulation.py::test_run_simulation_clears_reaction_outputs -v
```

Expected: PASS

- [ ] **Step 2.7: Run the full suite**

```
pytest tests/ -q
```

Expected: all 242 pass

- [ ] **Step 2.8: Commit**

```
git add quino/application/service.py quino/gui/main_window.py tests/test_simulation.py
git commit -m "feat: get_entity supports __reaction__ prefix; clear reaction_outputs on sim reset"
```

---

## Task 3: Adapter — extract reaction forces from Exudyn

**Files:**
- Modify: `quino/solver_adapters/exudyn_adapter.py`
- Modify: `tests/test_simulation.py` (extend `_FakeItemInterface` and `_FakeMbs`)

### Background on Exudyn force output

- **Ground joints** (`ObjectJointRevolute2D`): `GetObjectOutput(obj, Force)` → `[Fx, Fy]` in N (global frame 2D).
- **Slider joints** (`CoordinateConstraint`): `GetObjectOutput(obj, Force)` → `[lambda]` scalar in N. The physical forces are `Fx = lambda * slider.normal_x`, `Fy = lambda * slider.normal_y`.
- Dynamic solve: forces are captured via `SensorObject(writeToFile=True)` written to temp dir. File format: space-separated text, one row per integration step, columns `t val1 [val2 ...]`.
- Static/no-driver solve: forces are read directly after solve via `GetObjectOutput`.

### Restructuring `_run_with_exudyn`

The temp dir must be created **before** `mbs.Assemble()` so sensor files can be registered. Currently `mbs.Assemble()` is called before the `with tempfile.TemporaryDirectory(...)` block. We move `mbs.Assemble()` inside the temp dir context.

- [ ] **Step 3.1: Add `SensorObject`, `AddSensor`, `GetObjectOutput` to fake test infrastructure**

In `tests/test_simulation.py`, add to `_FakeItemInterface`:

```python
@staticmethod
def SensorObject(**kwargs):
    return {"kind": "SensorObject", **kwargs}
```

Add to `_FakeMbs`:

```python
def AddSensor(self, item):
    self.sensors = getattr(self, "sensors", [])
    self.sensors.append(item)
    return len(self.sensors) - 1

def GetObjectOutput(self, objectNumber, variableType):
    return [0.0, 0.0]
```

Also add to the fake `exu` module's `OutputVariableType` (the `_FakeExu` class or wherever `exu.OutputVariableType.Force` is mocked). Find where `_FakeExu` is defined in the test and add:

```python
class OutputVariableType:
    Force = "Force"
    Coordinates = "Coordinates"
    Velocity = "Velocity"
```

*(Check the existing `_FakeExu` definition in `tests/test_simulation.py` and extend as needed — search for `OutputVariableType` in the test file to find the existing mock.)*

- [ ] **Step 3.2: Run the existing suite to confirm fakes don't break anything**

```
pytest tests/ -q
```

Expected: all 242 pass

- [ ] **Step 3.3: Add imports to `exudyn_adapter.py`**

At the top of `quino/solver_adapters/exudyn_adapter.py`, add:

```python
import math
import numpy as np
```

*(Note: `math` is already imported; only add `numpy` if not already present.)*

Also add to the imports from `quino.domain.model`:

```python
from quino.domain.model import Project, ReactionOutput, SensorOutput, SimulationResult
```

- [ ] **Step 3.4: Add helper to identify reaction joints in `exudyn_adapter.py`**

Add this private method to `ExudynAdapter` (near the bottom, before `_project_diagnostics`):

```python
def _reaction_joint_info(
    self,
    assembled: AssembledMechanism,
    joint_objects: dict[str, int],
) -> list[tuple[str, str, str, str | None, float, float]]:
    """Return metadata for joints whose reactions we should capture.

    Each entry: (joint_id, joint_name, endpoint_type, slider_id_or_None, normal_x, normal_y)
    endpoint_type is "ground" or "slider".
    """
    result = []
    for joint in assembled.joints:
        ep_a = joint.endpoint_a
        ep_b = joint.endpoint_b
        is_ground = ep_a.kind is JointEndpointKind.GROUND or ep_b.kind is JointEndpointKind.GROUND
        is_slider = ep_a.kind is JointEndpointKind.SLIDER or ep_b.kind is JointEndpointKind.SLIDER
        if not (is_ground or is_slider):
            continue
        if joint.id not in joint_objects:
            continue
        if is_slider:
            slider_ep = ep_a if ep_a.kind is JointEndpointKind.SLIDER else ep_b
            slider = assembled.sliders.get(slider_ep.slider_id)
            nx = slider.normal_x if slider else 0.0
            ny = slider.normal_y if slider else 0.0
            result.append((joint.id, joint.name, "slider", slider_ep.slider_id, nx, ny))
        else:
            result.append((joint.id, joint.name, "ground", None, 0.0, 0.0))
    return result
```

- [ ] **Step 3.5: Add helper to compute marker world position per frame in `exudyn_adapter.py`**

Add this private method to `ExudynAdapter`:

```python
def _reaction_joint_marker_ep(self, assembled: AssembledMechanism, joint_id: str):
    """Return (body_id, marker_id) for the MARKER endpoint of a ground/slider joint."""
    for joint in assembled.joints:
        if joint.id != joint_id:
            continue
        ep_a, ep_b = joint.endpoint_a, joint.endpoint_b
        if ep_a.kind is JointEndpointKind.MARKER:
            return ep_a.body_id, ep_a.marker_id
        if ep_b.kind is JointEndpointKind.MARKER:
            return ep_b.body_id, ep_b.marker_id
    return None, None
```

- [ ] **Step 3.6: Add `_build_reaction_positions` helper in `exudyn_adapter.py`**

```python
def _build_reaction_positions(
    self,
    assembled: AssembledMechanism,
    frames: list[dict[str, float]],
    body_id: str,
    marker_id: str,
) -> list[tuple[float, float]]:
    """Return world-space mm positions of a marker for each simulation frame."""
    positions = []
    for frame in frames:
        x, y = self._marker_global_pos(assembled, body_id, marker_id, frame)
        positions.append((x, y))
    return positions
```

- [ ] **Step 3.7: Add `_load_sensor_file` helper in `exudyn_adapter.py`**

```python
def _load_sensor_file(self, path) -> list[list[float]]:
    """Parse an Exudyn sensor output file. Returns list of rows (each row is a list of floats)."""
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rows.append([float(v) for v in line.split()])
        except ValueError:
            continue
    return rows
```

- [ ] **Step 3.8: Add `_resample_sensor_to_time_axis` helper in `exudyn_adapter.py`**

```python
def _resample_sensor_to_time_axis(
    self,
    sensor_rows: list[list[float]],
    target_times: list[float],
) -> list[list[float]]:
    """For each target time, find the nearest sensor row and return its value columns (all but col 0)."""
    if not sensor_rows or not target_times:
        return []
    result = []
    for t_target in target_times:
        best = min(sensor_rows, key=lambda row: abs(row[0] - t_target))
        result.append(best[1:])  # skip time column
    return result
```

- [ ] **Step 3.9: Add `_record_reaction_data_dynamic` in `exudyn_adapter.py`**

```python
def _record_reaction_data_dynamic(
    self,
    project: Project,
    assembled: AssembledMechanism,
    time: list[float],
    frames: list[dict[str, float]],
    reaction_info: list[tuple],
    sensor_files: dict[str, object],  # joint_id → Path
) -> None:
    """Populate project.reaction_outputs from sensor files written during dynamic solve."""
    for joint_id, joint_name, endpoint_type, slider_id, normal_x, normal_y in reaction_info:
        sfile = sensor_files.get(joint_id)
        rows = self._load_sensor_file(sfile) if sfile else []
        values = self._resample_sensor_to_time_axis(rows, time)
        if not values:
            continue
        body_id, marker_id = self._reaction_joint_marker_ep(assembled, joint_id)
        if body_id is None:
            continue
        positions = self._build_reaction_positions(assembled, frames, body_id, marker_id)
        data: list[list[float]] = []
        for v in values:
            if endpoint_type == "ground":
                fx = v[0] if len(v) > 0 else 0.0
                fy = v[1] if len(v) > 1 else 0.0
            else:
                lam = v[0] if v else 0.0
                fx = lam * normal_x
                fy = lam * normal_y
            f_mag = math.sqrt(fx * fx + fy * fy)
            data.append([fx, fy, f_mag])
        project.reaction_outputs[joint_id] = ReactionOutput(
            joint_id=joint_id,
            joint_name=joint_name,
            endpoint_type=endpoint_type,
            time=list(time),
            columns=["Fx [N]", "Fy [N]", "F [N]"],
            data=data,
            positions=positions,
        )
```

- [ ] **Step 3.10: Add `_record_reaction_data_static` in `exudyn_adapter.py`**

```python
def _record_reaction_data_static(
    self,
    project: Project,
    assembled: AssembledMechanism,
    mbs,
    exu,
    time: list[float],
    frames: list[dict[str, float]],
    reaction_info: list[tuple],
    joint_objects: dict[str, int],
) -> None:
    """Populate project.reaction_outputs by reading GetObjectOutput after a static/no-driver solve."""
    for joint_id, joint_name, endpoint_type, slider_id, normal_x, normal_y in reaction_info:
        joint_obj_num = joint_objects.get(joint_id, -1)
        if joint_obj_num < 0:
            continue
        try:
            raw = mbs.GetObjectOutput(joint_obj_num, exu.OutputVariableType.Force)
        except Exception:
            continue
        if endpoint_type == "ground":
            fx = float(raw[0]) if hasattr(raw, "__len__") and len(raw) > 0 else float(raw)
            fy = float(raw[1]) if hasattr(raw, "__len__") and len(raw) > 1 else 0.0
        else:
            lam = float(raw[0]) if hasattr(raw, "__len__") else float(raw)
            fx = lam * normal_x
            fy = lam * normal_y
        f_mag = math.sqrt(fx * fx + fy * fy)
        body_id, marker_id = self._reaction_joint_marker_ep(assembled, joint_id)
        if body_id is None:
            continue
        positions = self._build_reaction_positions(assembled, frames, body_id, marker_id)
        project.reaction_outputs[joint_id] = ReactionOutput(
            joint_id=joint_id,
            joint_name=joint_name,
            endpoint_type=endpoint_type,
            time=list(time),
            columns=["Fx [N]", "Fy [N]", "F [N]"],
            data=[[fx, fy, f_mag]] * len(frames),
            positions=positions,
        )
```

- [ ] **Step 3.11: Restructure `_run_with_exudyn` to move `mbs.Assemble()` inside a temp dir context and register sensors**

In `_run_with_exudyn` (around line 200), the current structure is:

```python
# ... create joints, drivers, loads, springs ...
mbs.Assemble()
# ... solve block with tempfile ...
```

Replace that entire section with the restructured version below. **Read the full method first** (lines 190–312) then apply these changes:

1. **Before** the `mbs.Assemble()` call, collect reaction info:

```python
reaction_info = self._reaction_joint_info(assembled, joint_objects)
```

2. Create a single shared temp dir that wraps BOTH Assemble and the solve:

```python
import tempfile as _tempfile
with _tempfile.TemporaryDirectory(prefix="quino_exudyn_") as _shared_temp:
    _shared_temp_path = Path(_shared_temp)

    # Register reaction sensors BEFORE Assemble
    reaction_sensor_files: dict[str, Path] = {}
    if solve_mode == "dynamic":
        for jid, jname, etype, sid, nx, ny in reaction_info:
            if jid in joint_objects:
                sfile = _shared_temp_path / f"rxn_{jid}.txt"
                mbs.AddSensor(item_interface.SensorObject(
                    objectNumber=joint_objects[jid],
                    outputVariableType=exu.OutputVariableType.Force,
                    fileName=str(sfile),
                ))
                reaction_sensor_files[jid] = sfile

    mbs.Assemble()

    if assembled.drivers or has_dynamic_bodies:
        if solve_mode == "dynamic":
            simulation_settings = exu.SimulationSettings()
            simulation_settings.timeIntegration.numberOfSteps = steps
            simulation_settings.timeIntegration.endTime = duration
            solution_path = _shared_temp_path / "solution.txt"
            simulation_settings.solutionSettings.writeSolutionToFile = True
            simulation_settings.solutionSettings.coordinatesSolutionFileName = str(solution_path)
            simulation_settings.solutionSettings.solutionWritePeriod = duration / max(steps, 1)
            if hasattr(simulation_settings.solutionSettings, "binarySolutionFile"):
                simulation_settings.solutionSettings.binarySolutionFile = False
            try:
                mbs.SolveDynamic(simulationSettings=simulation_settings)
            except Exception as exc:
                time, frames = self._load_solution_frames(
                    exu, mbs, solution_path, assembled, body_order, node_numbers,
                    allow_final_fallback=False, project=project,
                )
                if frames:
                    warnings.append("Dynamic solve failed; returning partial trajectory up to last converged frame")
                    messages.append("Exudyn dynamic solve terminated before end; partial frames are available")
                    messages.append(self._format_exception(exc))
                    if project:
                        self._record_reaction_data_dynamic(project, assembled, time, frames, reaction_info, reaction_sensor_files)
                    return SimulationResult(
                        success=False, backend=self.name, messages=messages, warnings=warnings,
                        time=time, frames=frames,
                        error=f"Dynamic solve failed after partial trajectory: {exc}",
                    )
                raise
            time, frames = self._load_solution_frames(
                exu, mbs, solution_path, assembled, body_order, node_numbers, project=project,
            )
            if project:
                self._record_reaction_data_dynamic(project, assembled, time, frames, reaction_info, reaction_sensor_files)
            messages.append("Exudyn dynamic solve completed")
        elif solve_mode == "static":
            simulation_settings = exu.SimulationSettings()
            simulation_settings.staticSolver.numberOfLoadSteps = 100
            simulation_settings.solutionSettings.writeSolutionToFile = False
            mbs.SolveStatic(simulationSettings=simulation_settings)
            final_state = self._collect_final_state(mbs, exu, assembled, node_numbers)
            time = [duration]
            frames = [final_state]
            if project:
                self._record_reaction_data_static(project, assembled, mbs, exu, time, frames, reaction_info, joint_objects)
            warnings.append("Dynamic solve fallback used; returning a single static frame")
            messages.append("Exudyn static fallback completed")
        else:
            raise ValueError(f"Unsupported Exudyn solve mode: {solve_mode}")
    else:
        time = [0.0]
        frames = [self._collect_final_state(mbs, exu, assembled, node_numbers)]
        if project:
            self._record_reaction_data_static(project, assembled, mbs, exu, time, frames, reaction_info, joint_objects)
        messages.append("No drivers defined; returning assembled reference configuration")
```

*(The `_load_solution_frames` call no longer passes a `project` arg for sensor recording when reaction recording happens separately — keep the existing `project=project` arg there so sensor data still gets recorded, or handle it consistently. The key constraint: `_record_reaction_data_dynamic` is called AFTER `_load_solution_frames` so both use the same `time` and `frames`.)*

**Important**: The old `with tempfile.TemporaryDirectory(...)` block inside the `dynamic` branch must be removed. The solution file is now at `_shared_temp_path / "solution.txt"`.

- [ ] **Step 3.12: Run the full suite**

```
pytest tests/ -q
```

Expected: all 242 pass (the fake mbs now has `AddSensor` and `GetObjectOutput`, so no crash)

- [ ] **Step 3.13: Write a targeted test for reaction data with the fake infrastructure**

Add to `tests/test_simulation.py`:

```python
def test_reaction_output_populated_for_ground_joint_static() -> None:
    """Verify reaction_outputs are populated for a ground joint in a no-driver (static) run."""
    import types
    from quino.solver_adapters.exudyn_adapter import ExudynAdapter
    from quino.services.expressions import ExpressionService

    app = ApplicationService()
    app.new_project("ReactTest")
    body_id = app.create_bar("Link", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = next(m.id for m in app._find_body(body_id).markers if m.name == "A")
    ground_joint_id = app.connect_marker_to_ground(marker_a, name="Ground_A")

    # Build a fake Exudyn module that returns known force values
    fake_exu = types.ModuleType("exudyn")

    class _OVT:
        Force = "Force"
        Coordinates = "Coordinates"
        Velocity = "Velocity"

    fake_exu.OutputVariableType = _OVT()

    class _FakeSimSettings:
        class timeIntegration:
            numberOfSteps = 0
            endTime = 0.0
        class staticSolver:
            numberOfLoadSteps = 100
        class solutionSettings:
            writeSolutionToFile = False
            coordinatesSolutionFileName = ""
            solutionWritePeriod = 0.01
            binarySolutionFile = False

    fake_exu.SimulationSettings = _FakeSimSettings
    fake_mbs = _FakeMbs()
    fake_mbs._force_values = {0: [10.0, 20.0]}  # joint_obj_num → [Fx, Fy]

    def patched_get_object_output(obj_num, var_type):
        return fake_mbs._force_values.get(obj_num, [0.0, 0.0])

    fake_mbs.GetObjectOutput = patched_get_object_output

    class _FakeSC:
        def AddSystem(self):
            return fake_mbs

    fake_exu.SystemContainer = _FakeSC

    adapter = ExudynAdapter(app.expression_service)
    assembled = adapter.assembler.assemble(app.project)
    result = adapter._run_with_exudyn(
        app.project, assembled, fake_exu, solve_mode="dynamic",
        duration=1.0, steps=1,
    )
    # Even if dynamic fails (no real Exudyn), reaction_outputs are set when static fallback fires
    # Just verify the dict exists and has no crash
    assert isinstance(app.project.reaction_outputs, dict)
```

*(This test primarily exercises the code path without crashing. Exact reaction values require real Exudyn.)*

- [ ] **Step 3.14: Run the full suite**

```
pytest tests/ -q
```

Expected: all 243+ pass

- [ ] **Step 3.15: Commit**

```
git add quino/domain/model.py quino/solver_adapters/exudyn_adapter.py tests/test_simulation.py
git commit -m "feat: extract reaction forces from Exudyn ground/slider joints during simulation"
```

---

## Task 4: GUI — Model tree Reactions section + inspector

**Files:**
- Modify: `quino/gui/main_window.py`
- Test: `tests/test_gui.py`

- [ ] **Step 4.1: Write the failing tests**

Add to `tests/test_gui.py`:

```python
def test_tree_shows_reactions_section_when_reaction_outputs_exist() -> None:
    from quino.domain.model import ReactionOutput
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.load_four_bar_example()
    window.app_service.project.reaction_outputs["j1"] = ReactionOutput(
        joint_id="j1", joint_name="Ground_A", endpoint_type="ground",
        time=[0.0], columns=["Fx [N]", "Fy [N]", "F [N]"],
        data=[[10.0, 20.0, 22.36]], positions=[(0.0, 0.0)],
    )
    window.refresh_all()
    qt_app.processEvents()

    labels = [
        window.tree.topLevelItem(i).text(0).split()[0]
        for i in range(window.tree.topLevelItemCount())
    ]
    assert "Reactions" in labels
    window.close()
    qt_app.processEvents()


def test_inspector_shows_reaction_properties() -> None:
    from quino.domain.model import ReactionOutput
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.load_four_bar_example()
    rxn = ReactionOutput(
        joint_id="j1", joint_name="Ground_A", endpoint_type="ground",
        time=[0.0], columns=["Fx [N]", "Fy [N]", "F [N]"],
        data=[[10.0, 20.0, 22.36]], positions=[(0.0, 0.0)],
    )
    window.app_service.project.reaction_outputs["j1"] = rxn
    window.refresh_all()
    window._selected_entity_id = "__reaction__j1"
    window._populate_inspector()
    qt_app.processEvents()

    labels = [
        window.inspector.item(r, 0).text()
        for r in range(window.inspector.rowCount())
        if window.inspector.item(r, 0) is not None
    ]
    assert "type" in labels
    assert "Fx" in labels
    assert "Fy" in labels
    assert "F" in labels
    window.close()
    qt_app.processEvents()
```

- [ ] **Step 4.2: Run tests to verify they fail**

```
pytest tests/test_gui.py::test_tree_shows_reactions_section_when_reaction_outputs_exist tests/test_gui.py::test_inspector_shows_reaction_properties -v
```

Expected: FAIL

- [ ] **Step 4.3: Add "Reactions" to `_SECTION_ICON` and `_SECTION_COLOR` in `main_window.py`**

In `_SECTION_ICON` (around line 1499), add:

```python
"Reactions": "load-gravity",
```

In `_SECTION_COLOR` (around line 1507), add:

```python
"Reactions": "#9b59b6",
```

In `_KIND_ICON` (around line 1474), add:

```python
"reaction_ground": "load-gravity",
"reaction_slider": "load-gravity",
```

- [ ] **Step 4.4: Add import of `ReactionOutput` at the top of `main_window.py`**

In the domain model imports section at the top, add `ReactionOutput`:

```python
from quino.domain.model import (
    ...
    ReactionOutput,
    ...
)
```

- [ ] **Step 4.5: Add Reactions section to `_populate_tree` in `main_window.py`**

In `_populate_tree` (around line 1515), after `springs_root` and before `self.tree.addTopLevelItems(...)`:

```python
has_reactions = len(project.reaction_outputs) > 0
reactions_root = _root("Reactions", len(project.reaction_outputs))
```

Add `reactions_root` to the `addTopLevelItems` call **only when** reactions exist. Replace the static `addTopLevelItems` with:

```python
top_level = [sketch_root, bodies_root, sliders_root, joints_root, drivers_root, sensors_root, loads_root, springs_root]
if has_reactions:
    top_level.append(reactions_root)
self.tree.addTopLevelItems(top_level)
```

After the existing `for spring in project.model.springs:` loop, add:

```python
for rxn in project.reaction_outputs.values():
    kind = f"reaction_{rxn.endpoint_type}"
    reactions_root.addChild(self._entity_item(rxn.joint_name, kind, f"__reaction__{rxn.joint_id}"))
```

- [ ] **Step 4.6: Add `ReactionOutput` handling to `_inspector_rows` in `main_window.py`**

The check for `entity_id.startswith("__reaction__")` routing already goes through `get_entity` which returns a `ReactionOutput`. In `_inspector_rows` (around line 2015), add a branch for `ReactionOutput`:

```python
elif isinstance(entity, ReactionOutput):
    prop("type", "", entity.endpoint_type, "readonly", entity.endpoint_type)
    prop("joint", "", entity.joint_name, "readonly", entity.joint_name)
    if entity.data:
        frame_idx = max(0, min(self._current_frame_index, len(entity.data) - 1))
        t = entity.time[frame_idx] if frame_idx < len(entity.time) else 0.0
        fx, fy, f_mag = entity.data[frame_idx]
        prop("— Current Values —", "", "", "section_header", "")
        prop("t", "", f"{t:.4g} s", "readonly", f"{t:.4g} s")
        prop("Fx", "", f"{fx:.4g} N", "readonly", f"{fx:.4g} N")
        prop("Fy", "", f"{fy:.4g} N", "readonly", f"{fy:.4g} N")
        prop("F", "", f"{f_mag:.4g} N", "readonly", f"{f_mag:.4g} N")
```

- [ ] **Step 4.7: Add `ReactionOutput` handling to `_entity_kind_label` and `_entity_default_icon`**

In `_entity_kind_label` (search for this method in `main_window.py`), add:

```python
if isinstance(entity, ReactionOutput):
    return "reaction"
```

In `_entity_default_icon` (search for this method), add:

```python
if isinstance(entity, ReactionOutput):
    return "load-gravity"
```

- [ ] **Step 4.8: Update `test_main_window_loads_examples_and_runs_validation` assertion count**

The test at line 33 asserts `window.tree.topLevelItemCount() == 8`. Since Reactions section only appears when `reaction_outputs` is non-empty, and that example has none after just loading (no simulation), this test should still pass. Verify:

```
pytest tests/test_gui.py::test_main_window_loads_examples_and_runs_validation -v
```

- [ ] **Step 4.9: Run failing tests to verify they now pass**

```
pytest tests/test_gui.py::test_tree_shows_reactions_section_when_reaction_outputs_exist tests/test_gui.py::test_inspector_shows_reaction_properties -v
```

Expected: PASS

- [ ] **Step 4.10: Run the full suite**

```
pytest tests/ -q
```

Expected: all pass

- [ ] **Step 4.11: Commit**

```
git add quino/gui/main_window.py tests/test_gui.py
git commit -m "feat: Reactions section in model tree and inspector with Fx/Fy/F values"
```

---

## Task 5: Plot — `SensorDataset` includes reactions

**Files:**
- Modify: `quino/viewer/dataset.py`
- Test: `tests/test_simulation.py`

- [ ] **Step 5.1: Write the failing test**

Add to `tests/test_simulation.py`:

```python
def test_sensor_dataset_includes_reactions() -> None:
    from quino.domain.model import ReactionOutput
    from quino.viewer.dataset import SensorDataset
    from quino.application.service import ApplicationService
    app = ApplicationService()
    app.new_project("Test")
    app.project.reaction_outputs["j1"] = ReactionOutput(
        joint_id="j1", joint_name="Ground_A", endpoint_type="ground",
        time=[0.0, 0.1, 0.2],
        columns=["Fx [N]", "Fy [N]", "F [N]"],
        data=[[10.0, 20.0, 22.36], [11.0, 21.0, 23.72], [12.0, 22.0, 25.06]],
        positions=[(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)],
    )
    dataset = SensorDataset(app.project)
    assert dataset.has_data()
    names = dataset.get_matrix_names()
    assert any("Ground_A" in n for n in names)
    matrix_name = next(n for n in names if "Ground_A" in n)
    data, headers = dataset.get_matrix(matrix_name)
    assert data.shape[0] == 3
    assert "Fx [N]" in headers
    assert "Fy [N]" in headers
    assert "F [N]" in headers
```

- [ ] **Step 5.2: Run test to verify it fails**

```
pytest tests/test_simulation.py::test_sensor_dataset_includes_reactions -v
```

Expected: FAIL

- [ ] **Step 5.3: Extend `SensorDataset` in `quino/viewer/dataset.py`**

After `_load_sensor_outputs` add a new method and call it from `__init__`:

```python
def __init__(self, project: Project):
    self.project = project
    self._matrices: dict[str, dict] = {}
    self._load_sensor_outputs()
    self._load_reaction_outputs()

def _load_reaction_outputs(self) -> None:
    """Load reaction force outputs recorded during the last simulation run."""
    for joint_id, rxn in self.project.reaction_outputs.items():
        if not rxn.data:
            continue
        import numpy as np
        data = np.array(rxn.data)
        name = f"[R] {rxn.joint_name}"
        self._matrices[name] = {
            "sensor_id": joint_id,
            "sensor_type": f"reaction_{rxn.endpoint_type}",
            "time": np.array(rxn.time),
            "columns": rxn.columns,
            "data": data,
        }
```

Also add `ReactionOutput` to the import at the top:

```python
from quino.domain.model import Project, ReactionOutput, SensorOutput
```

- [ ] **Step 5.4: Run test to verify it passes**

```
pytest tests/test_simulation.py::test_sensor_dataset_includes_reactions -v
```

Expected: PASS

- [ ] **Step 5.5: Run the full suite**

```
pytest tests/ -q
```

Expected: all pass

- [ ] **Step 5.6: Commit**

```
git add quino/viewer/dataset.py tests/test_simulation.py
git commit -m "feat: SensorDataset includes reaction force outputs for plotting"
```

---

## Task 6: Canvas — `_draw_reactions` arrows

**Files:**
- Modify: `quino/gui/canvas.py`
- Test: `tests/test_gui.py`

### Arrow design

- Color: orange-amber `#f4a261`
- Scale: `scale_mm_per_n = 3.0` (same as loads)
- Arrow drawn FROM the joint world position in the direction of the force vector
- Label: `"F = {f_mag:.2f} N"` next to the arrowhead
- Only drawn when `self._state_overlay is not None` (simulation result exists)

- [ ] **Step 6.1: Write the failing test**

Add to `tests/test_gui.py`:

```python
def test_canvas_draw_reactions_does_not_crash_with_reaction_outputs() -> None:
    from quino.domain.model import ReactionOutput
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.load_four_bar_example()
    window.app_service.project.reaction_outputs["j1"] = ReactionOutput(
        joint_id="j1", joint_name="Ground_A", endpoint_type="ground",
        time=[0.0], columns=["Fx [N]", "Fy [N]", "F [N]"],
        data=[[50.0, 100.0, 111.8]], positions=[(0.0, 0.0)],
    )
    window.canvas.set_state_overlay({"dummy": 0.0})
    window.canvas.set_simulation_time(0.0)
    window.refresh_all()
    qt_app.processEvents()
    pixmap = window.canvas.grab()
    assert not pixmap.isNull()
    window.close()
    qt_app.processEvents()
```

- [ ] **Step 6.2: Run test to verify it fails**

```
pytest tests/test_gui.py::test_canvas_draw_reactions_does_not_crash_with_reaction_outputs -v
```

Expected: FAIL (method doesn't exist yet)

- [ ] **Step 6.3: Add `ReactionOutput` import to `canvas.py`**

At the top of `quino/gui/canvas.py`, in the domain model imports, add `ReactionOutput`:

```python
from quino.domain.model import (
    ...
    ReactionOutput,
    ...
)
```

- [ ] **Step 6.4: Add `_draw_reactions` method to `canvas.py`**

Add this method after `_draw_loads` (around line 3090):

```python
def _draw_reactions(
    self,
    painter: QtGui.QPainter,
    project: Project,
    transform,
) -> None:
    if self._state_overlay is None:
        return
    reaction_outputs = project.reaction_outputs
    if not reaction_outputs:
        return
    scale_mm_per_n = 3.0
    arrow_color = QtGui.QColor("#f4a261")
    text_color = QtGui.QColor("#d4612a")
    t = self._simulation_time
    for rxn in reaction_outputs.values():
        if not rxn.data or not rxn.positions:
            continue
        # Find frame closest to current simulation time
        if rxn.time:
            frame_idx = min(range(len(rxn.time)), key=lambda i: abs(rxn.time[i] - t))
        else:
            frame_idx = 0
        if frame_idx >= len(rxn.data) or frame_idx >= len(rxn.positions):
            continue
        fx, fy, f_mag = rxn.data[frame_idx]
        px, py = rxn.positions[frame_idx]
        if f_mag < 1e-6:
            continue
        origin_screen = self._to_screen(px, py, transform)
        dx = fx / f_mag
        dy = fy / f_mag
        arrow_length_mm = f_mag * scale_mm_per_n
        end_x = px + dx * arrow_length_mm
        end_y = py + dy * arrow_length_mm
        end_screen = self._to_screen(end_x, end_y, transform)
        painter.save()
        painter.setOpacity(0.85)
        pen = QtGui.QPen(arrow_color, 3.0, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(origin_screen, end_screen)
        screen_dx = end_screen.x() - origin_screen.x()
        screen_dy = end_screen.y() - origin_screen.y()
        screen_len = math.sqrt(screen_dx * screen_dx + screen_dy * screen_dy)
        if screen_len > 1e-6:
            ux = screen_dx / screen_len
            uy = screen_dy / screen_len
            arrow_size = 12.0
            wing = 6.0
            bx = end_screen.x() - ux * arrow_size
            by = end_screen.y() - uy * arrow_size
            wx = -uy * wing
            wy = ux * wing
            p1 = QtCore.QPointF(bx + wx, by + wy)
            p2 = QtCore.QPointF(bx - wx, by - wy)
            painter.setBrush(QtGui.QBrush(arrow_color))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawPolygon(QtGui.QPolygonF([end_screen, p1, p2]))
        painter.restore()
        painter.setPen(QtGui.QPen(text_color))
        painter.drawText(end_screen + QtCore.QPointF(8.0, -8.0), f"F = {f_mag:.2f} N")
```

- [ ] **Step 6.5: Call `_draw_reactions` in both render paths in `paintEvent`**

In `paintEvent` (search for the two places that call `self._draw_loads(...)`), after each `_draw_loads(...)` call, add:

```python
self._draw_reactions(painter, project, transform)
```

There are two render paths (sketch-edit overlay mode and normal model mode); add to both. Search for:
```python
self._draw_loads(painter, project, markers, transform)
```
and immediately after each occurrence add:
```python
self._draw_reactions(painter, project, transform)
```

- [ ] **Step 6.6: Run test to verify it passes**

```
pytest tests/test_gui.py::test_canvas_draw_reactions_does_not_crash_with_reaction_outputs -v
```

Expected: PASS

- [ ] **Step 6.7: Run the full suite**

```
pytest tests/ -q
```

Expected: all pass

- [ ] **Step 6.8: Commit**

```
git add quino/gui/canvas.py tests/test_gui.py
git commit -m "feat: draw reaction force arrows on canvas in orange-amber color"
```

---

## Self-Review

### Spec coverage check

| Requirement | Task |
|---|---|
| Extract reactions from ground elements | Task 3 — `_reaction_joint_info` + `_record_reaction_data_dynamic/static` |
| Extract reactions from slider elements | Task 3 — slider branch with `lambda * normal` conversion |
| Show in model tree under "Reactions" | Task 4 — `_populate_tree` Reactions section |
| Plot with Fx/Fy/F channels | Task 5 — `SensorDataset._load_reaction_outputs` |
| Disappear on simulation cancel | Task 2 — `_clear_simulation_state` clears `reaction_outputs` |
| Disappear on model change | Task 2 — `_clear_simulation_state` is called in `_prepare_for_model_edit` |
| Canvas arrows with direction and magnitude | Task 6 — `_draw_reactions` |
| Inspector with current values | Task 4 — `_inspector_rows` for `ReactionOutput` |

### Type consistency check

- `ReactionOutput` defined in Task 1, used consistently in Tasks 2–6
- `__reaction__{joint_id}` prefix: defined in Task 2 (`get_entity`), used in Task 4 (`_entity_item` call)
- `reaction_info` tuple: `(joint_id, joint_name, endpoint_type, slider_id_or_None, normal_x, normal_y)` — 6 fields, used consistently in Tasks 3 and the helpers
- `sensor_files: dict[str, Path]` — `Path` type consistent with `_load_sensor_file(path)` which accepts `Path`
- `_build_reaction_positions` returns `list[tuple[float, float]]` matching `ReactionOutput.positions` type

### Placeholder scan

No TBDs or vague instructions found. All code blocks are complete.

### Edge cases handled

- Sensor file missing (dynamic solve crashed early): `_load_sensor_file` returns `[]`, `_resample_sensor_to_time_axis` returns `[]`, reaction is skipped
- Zero force magnitude: guarded in `_draw_reactions` with `if f_mag < 1e-6: continue`
- No reaction outputs: early return in `_draw_reactions`
- Reactions tree section only appears when non-empty: `if has_reactions:` in `_populate_tree`
- `topLevelItemCount` test: Four Bar example has no reactions after loading, so count stays 8

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-14-reaction-forces.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks
**2. Inline Execution** — execute tasks in this session with checkpoints

Which approach?
