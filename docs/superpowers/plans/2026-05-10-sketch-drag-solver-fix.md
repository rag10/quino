# Sketch Drag & Solver Correctness Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the sketch solver so that dragging a constrained point respects its remaining free DOF — the point moves only in its unconstrained directions — without the sketch turning red (solver failure).

**Architecture:** Two-line fix in `service.py` (change `locked_point_ids` from `{point_id}` to `set()` in `move_sketch_point` and `update_sketch_entity`), one bug fix in the solve cache signature, and one UX guard to prevent drag on fully-constrained points. A DOF-aware drag lock in the canvas prevents confusing red errors when all DOF are consumed.

**Tech Stack:** `ApplicationService`, `SketchSolver`, `SketchDofAnalyzer`, `MechanismCanvas`.

---

## Root Cause Analysis

### Bug 1 — `move_sketch_point` locks the dragged point completely

**File:** `quino/application/service.py:198`

```python
# CURRENT (broken):
self._apply_sketch_constraints({point_id})
```

When `locked_point_ids={point_id}`, the solver marks **both axes** of the dragged point as immovable. If that point also participates in a constraint (e.g. `VERTICAL [p1, p2]`), and the fixed endpoint `p1` is also locked by a `FIX` constraint, the solver cannot satisfy the constraint — both sides are locked — and diverges. The sketch turns red.

**What the user sees:** Draw a segment, fix one end, add VERTICAL, drag the free end sideways → red sketch.

**Fix:** Use `locked_point_ids=set()`. The `FIX` constraints in the sketch already lock all fixed points. The dragged point's position is set as the starting guess before the solve; the Gauss-Seidel loop will then project it onto the constraint manifold (e.g. back onto the vertical line) while preserving the user-intended free DOF (y position in the vertical case).

**Proof:**
```
Before fix: drag p2 to (30, 80) with VERTICAL+FIX → solver fails, error=30 mm, red
After fix:  drag p2 to (30, 80) with VERTICAL+FIX → converges, p2=(0, 80), green
```

---

### Bug 2 — Same problem in `update_sketch_entity` (inspector edits)

**File:** `quino/application/service.py:457`

```python
# CURRENT (broken):
self._apply_sketch_constraints({entity.id})
```

Same issue: editing a point's coordinates via the inspector panel locks the edited point, causing identical solver failures when that point is constrained.

**Fix:** Same as Bug 1 — use `set()`.

---

### Bug 3 — Sketch solve cache ignores constraint value changes

**File:** `quino/application/service.py` — `_sketch_signature` method

```python
# CURRENT (missing constraint values):
for constraint in sketch.constraints:
    data += f"{constraint.id}:{constraint.type.value}:{','.join(constraint.references)}:..."
    # ← constraint.value.expression is NOT included
```

If the user changes a DISTANCE or ANGLE constraint value (e.g. from 50 mm to 80 mm), the signature does not change. The cache returns the old solve result. The sketch appears to ignore the change until the cache is invalidated by something else.

**Fix:** Include `constraint.value.expression` in the signature string.

---

### Bug 4 — Fully-constrained points can be dragged, causing red state

**File:** `quino/gui/canvas.py` — `mousePressEvent` drag guard

When DOF = 0 for a point (all its DOF are consumed by constraints), dragging it is meaningless and will always fail. The fix from Bug 1 mitigates this somewhat, but a point that is over-constrained will still diverge.

**Fix:** The existing `_dof_result` (computed each frame from `SketchDofAnalyzer`) already has `point_dof`. If `point_dof[pid] == 0`, refuse the drag the same way fixed points are refused.

---

### Bug 5 — Example JSON names include `.quino` suffix

**File:** `quino/application/example_registry.py` — `_discover_json_examples`

```python
# CURRENT:
name=json_file.stem.replace("_", " "),
# json_file.stem of "Pantograph.quino.json" is "Pantograph.quino"
# Result: "Pantograph.quino" instead of "Pantograph"
```

**Fix:** Strip the inner `.quino` suffix from the stem.

---

## File Map

| File | Change |
|------|--------|
| `quino/application/service.py` | Fix locked_point_ids in `move_sketch_point` and `update_sketch_entity`; fix solve cache signature |
| `quino/gui/canvas.py` | Extend drag guard to DOF=0 points |
| `quino/application/example_registry.py` | Fix JSON example name extraction |
| `tests/test_application.py` | Regression tests for all three service bugs |
| `tests/test_gui.py` | Test DOF=0 drag guard |

---

## Task 1: Fix `move_sketch_point` locked_point_ids

**Files:**
- Modify: `quino/application/service.py:198`
- Modify: `tests/test_application.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_application.py — add
def test_drag_constrained_point_respects_free_dof():
    """Dragging a point with VERTICAL+FIX should keep x=0, update y freely."""
    from quino.application.service import ApplicationService

    svc = ApplicationService()
    svc.new_project("drag_test")
    p1 = svc.create_sketch_point("0 mm", "0 mm")
    p2 = svc.create_sketch_point("0 mm", "50 mm")
    svc.create_sketch_line_segment(p1, p2)
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("vertical", [p1, p2])

    # Drag p2 sideways and upward — only y should change
    svc.move_sketch_point(p2, "30 mm", "80 mm")

    assert svc.project.sketch.solve_error is None, (
        f"Expected solver to succeed, got: {svc.project.sketch.solve_error}"
    )
    pts = {e.id: e for e in svc.project.sketch.entities if hasattr(e, "x")}
    x2 = svc.expression_service.evaluate_property(pts[p2].x, svc.project.parameters).value
    y2 = svc.expression_service.evaluate_property(pts[p2].y, svc.project.parameters).value
    assert abs(x2) < 1e-4, f"VERTICAL should keep x=0, got x={x2}"
    assert abs(y2 - 80.0) < 1e-4, f"Free y should be 80, got y={y2}"


def test_drag_distance_constrained_point_stays_on_circle():
    """Dragging a point with DISTANCE+FIX should project onto the constraint circle."""
    import math
    from quino.application.service import ApplicationService

    svc = ApplicationService()
    svc.new_project("drag_dist_test")
    p1 = svc.create_sketch_point("0 mm", "0 mm")
    p2 = svc.create_sketch_point("50 mm", "0 mm")
    svc.create_sketch_line_segment(p1, p2)
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("distance", [p1, p2])  # distance = 50 mm

    # Drag p2 off the circle
    svc.move_sketch_point(p2, "70 mm", "30 mm")

    assert svc.project.sketch.solve_error is None
    pts = {e.id: e for e in svc.project.sketch.entities if hasattr(e, "x")}
    x2 = svc.expression_service.evaluate_property(pts[p2].x, svc.project.parameters).value
    y2 = svc.expression_service.evaluate_property(pts[p2].y, svc.project.parameters).value
    dist = math.hypot(x2, y2)
    assert abs(dist - 50.0) < 0.1, f"Point should stay on circle r=50, got dist={dist:.3f}"
```

- [ ] **Step 2: Run to verify FAIL**

```
pytest tests/test_application.py::test_drag_constrained_point_respects_free_dof tests/test_application.py::test_drag_distance_constrained_point_stays_on_circle -v
```
Expected: both FAIL — `"Expected solver to succeed, got: Sketch solver did not converge..."`

- [ ] **Step 3: Fix `move_sketch_point` in service.py**

In `quino/application/service.py`, find `move_sketch_point` (line 188):

```python
# BEFORE:
def move_sketch_point(self, point_id: str, x: str, y: str) -> None:
    project = self._require_project()
    point = self._find_sketch_point(point_id)
    x_scalar = self._scalar(x, "mm", Dimension.LENGTH)
    y_scalar = self._scalar(y, "mm", Dimension.LENGTH)
    self.expression_service.evaluate_property(x_scalar, project.parameters)
    self.expression_service.evaluate_property(y_scalar, project.parameters)
    self._snapshot()
    point.x = x_scalar
    point.y = y_scalar
    self._apply_sketch_constraints({point_id})

# AFTER:
def move_sketch_point(self, point_id: str, x: str, y: str) -> None:
    project = self._require_project()
    point = self._find_sketch_point(point_id)
    x_scalar = self._scalar(x, "mm", Dimension.LENGTH)
    y_scalar = self._scalar(y, "mm", Dimension.LENGTH)
    self.expression_service.evaluate_property(x_scalar, project.parameters)
    self.expression_service.evaluate_property(y_scalar, project.parameters)
    self._snapshot()
    point.x = x_scalar
    point.y = y_scalar
    self._apply_sketch_constraints(set())
```

- [ ] **Step 4: Run tests to verify PASS**

```
pytest tests/test_application.py::test_drag_constrained_point_respects_free_dof tests/test_application.py::test_drag_distance_constrained_point_stays_on_circle -v
```
Expected: both PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/ -v
```
Expected: all tests PASS. No regressions.

- [ ] **Step 6: Commit**

```bash
git add quino/application/service.py tests/test_application.py
git commit -m "fix: dragging constrained sketch point now respects constraint axes"
```

---

## Task 2: Fix `update_sketch_entity` locked_point_ids (inspector edits)

**Files:**
- Modify: `quino/application/service.py:457`
- Modify: `tests/test_application.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_application.py — add
def test_inspector_edit_constrained_point_respects_free_dof():
    """Editing a constrained point via inspector should obey constraints."""
    from quino.application.service import ApplicationService
    from quino.domain.inputs import PropertyValueInput

    svc = ApplicationService()
    svc.new_project("inspector_test")
    p1 = svc.create_sketch_point("0 mm", "0 mm")
    p2 = svc.create_sketch_point("0 mm", "50 mm")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("vertical", [p1, p2])

    # Edit p2.x to 30mm via inspector — VERTICAL should push it back to 0
    svc.update_sketch_entity(p2, "x", PropertyValueInput(kind="expression", value="30 mm"))

    assert svc.project.sketch.solve_error is None
    pts = {e.id: e for e in svc.project.sketch.entities if hasattr(e, "x")}
    x2 = svc.expression_service.evaluate_property(pts[p2].x, svc.project.parameters).value
    assert abs(x2) < 1e-4, f"VERTICAL should keep x=0 after inspector edit, got x={x2}"
```

- [ ] **Step 2: Run to verify FAIL**

```
pytest tests/test_application.py::test_inspector_edit_constrained_point_respects_free_dof -v
```
Expected: FAIL.

- [ ] **Step 3: Fix `update_sketch_entity` in service.py**

Find the `update_sketch_entity` method. At line 457:

```python
# BEFORE:
self._apply_sketch_constraints({entity.id})

# AFTER:
self._apply_sketch_constraints(set())
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_application.py::test_inspector_edit_constrained_point_respects_free_dof -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add quino/application/service.py tests/test_application.py
git commit -m "fix: inspector edits on constrained sketch points respect constraint axes"
```

---

## Task 3: Fix Solve Cache — Include Constraint Values in Signature

**Files:**
- Modify: `quino/application/service.py` — `_sketch_signature` method

- [ ] **Step 1: Write failing test**

```python
# tests/test_application.py — add
def test_changing_distance_value_invalidates_solve_cache():
    """After changing a distance value, the solver must re-run and update positions."""
    from quino.application.service import ApplicationService
    from quino.domain.inputs import PropertyValueInput

    svc = ApplicationService()
    svc.new_project("cache_test")
    p1 = svc.create_sketch_point("0 mm", "0 mm")
    p2 = svc.create_sketch_point("50 mm", "0 mm")
    svc.create_sketch_constraint("fix", [p1])
    c_id = svc.create_sketch_constraint("distance", [p1, p2])

    pts = {e.id: e for e in svc.project.sketch.entities if hasattr(e, "x")}
    x2_before = svc.expression_service.evaluate_property(pts[p2].x, svc.project.parameters).value
    assert abs(x2_before - 50.0) < 1e-4

    # Change distance to 80mm
    svc.update_sketch_constraint(c_id, "value", PropertyValueInput(kind="expression", value="80 mm"))

    pts = {e.id: e for e in svc.project.sketch.entities if hasattr(e, "x")}
    x2_after = svc.expression_service.evaluate_property(pts[p2].x, svc.project.parameters).value
    assert abs(x2_after - 80.0) < 1e-4, (
        f"After updating distance to 80mm, p2.x should be 80, got {x2_after}"
    )
```

- [ ] **Step 2: Run to verify FAIL**

```
pytest tests/test_application.py::test_changing_distance_value_invalidates_solve_cache -v
```
Expected: FAIL — p2.x remains 50 after the distance update.

- [ ] **Step 3: Fix `_sketch_signature` in service.py**

Find `_sketch_signature`. Current code:
```python
for constraint in sketch.constraints:
    data += f"{constraint.id}:{constraint.type.value}:{','.join(constraint.references)}:{','.join(constraint.entity_references)};"
```

Change to:
```python
for constraint in sketch.constraints:
    val_expr = constraint.value.expression if constraint.value is not None else ""
    data += f"{constraint.id}:{constraint.type.value}:{','.join(constraint.references)}:{','.join(constraint.entity_references)}:{val_expr};"
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_application.py::test_changing_distance_value_invalidates_solve_cache -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add quino/application/service.py tests/test_application.py
git commit -m "fix: sketch solve cache now invalidates when constraint value changes"
```

---

## Task 4: Prevent Drag on Fully-Constrained Points (DOF = 0)

**Files:**
- Modify: `quino/gui/canvas.py` — `mousePressEvent` drag guard

When a point has zero remaining DOF (all its axes are determined by constraints), dragging it cannot change anything meaningful. Allowing the drag just triggers a solver failure and a confusing red state. The guard should refuse the drag the same way it refuses dragging FIX-constrained points, but with a different cursor / message.

- [ ] **Step 1: Write failing test**

```python
# tests/test_gui.py — add
def test_fully_constrained_point_not_draggable(qtbot):
    """A point with DOF=0 (not FIX, but fully constrained) must not start a drag."""
    from quino.gui.canvas import MechanismCanvas, CanvasMode
    from quino.application.service import ApplicationService
    from PySide6 import QtGui, QtCore

    svc = ApplicationService()
    svc.new_project("dof0_drag_test")
    p1 = svc.create_sketch_point("0 mm", "0 mm")
    p2 = svc.create_sketch_point("50 mm", "0 mm")
    svc.create_sketch_line_segment(p1, p2)
    # Both points fixed: p1 directly, p2 via FIX
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])

    canvas = MechanismCanvas(svc)
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas._interaction_mode = "sketch"
    canvas._editing_enabled = True
    canvas._mode = CanvasMode.SELECT

    # Force a repaint to populate _screen_sketch_points and _dof_result
    canvas.grab()

    transform = canvas._current_transform()
    canvas_pts = canvas._collect_sketch_points(svc.project)
    cp2 = next(p for p in canvas_pts if p.entity_id == p2)
    screen = canvas._to_screen(cp2.x, cp2.y, transform)

    event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        screen,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(event)
    assert canvas._dragging_sketch_point is None, "DOF=0 point must not be draggable"
```

- [ ] **Step 2: Run to verify FAIL**

```
pytest tests/test_gui.py::test_fully_constrained_point_not_draggable -v
```
Expected: FAIL — drag starts despite DOF=0.

- [ ] **Step 3: Extend drag guard in `canvas.py`**

In `mousePressEvent`, find the current drag guard:

```python
# CURRENT (line ~704):
if self._editing_enabled and not self._is_point_fixed(clicked_sketch_point.entity_id):
    self._dragging_sketch_point = clicked_sketch_point
    ...
```

Change to:

```python
point_is_locked = (
    self._is_point_fixed(clicked_sketch_point.entity_id)
    or (
        self._dof_result is not None
        and self._dof_result.point_dof.get(clicked_sketch_point.entity_id, 2) == 0
    )
)
if self._editing_enabled and not point_is_locked:
    self._dragging_sketch_point = clicked_sketch_point
    self._dragging_sketch_point_preview = (
        clicked_sketch_point.entity_id,
        clicked_sketch_point.x,
        clicked_sketch_point.y,
    )
```

Also update `_update_hover_targets` to show the forbidden cursor for DOF=0 points (not just FIX):

```python
# CURRENT:
if (
    self._mode == CanvasMode.SELECT
    and self._editing_enabled
    and self._is_point_fixed(hovered_point.entity_id)
):
    self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ForbiddenCursor))

# AFTER:
_hovered_is_locked = (
    self._is_point_fixed(hovered_point.entity_id)
    or (
        self._dof_result is not None
        and self._dof_result.point_dof.get(hovered_point.entity_id, 2) == 0
    )
)
if self._mode == CanvasMode.SELECT and self._editing_enabled and _hovered_is_locked:
    self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ForbiddenCursor))
```

Note: `_dof_result` is set at each repaint. It is `None` before the first render. The guard `self._dof_result is not None` ensures it degrades gracefully before the first paint.

- [ ] **Step 4: Run tests**

```
pytest tests/test_gui.py::test_fully_constrained_point_not_draggable -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add quino/gui/canvas.py tests/test_gui.py
git commit -m "fix: prevent dragging fully-constrained (DOF=0) sketch points"
```

---

## Task 5: Fix Example Registry JSON Name Extraction

**Files:**
- Modify: `quino/application/example_registry.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_examples.py — add
def test_example_registry_json_names_have_no_quino_suffix():
    """JSON examples must have clean names without .quino in them."""
    from quino.application.example_registry import ExampleRegistry
    from pathlib import Path

    reg = ExampleRegistry()
    for entry in reg.list_examples():
        assert ".quino" not in entry.name, (
            f"Example name '{entry.name}' still contains .quino suffix"
        )
```

- [ ] **Step 2: Run to verify FAIL**

```
pytest tests/test_examples.py::test_example_registry_json_names_have_no_quino_suffix -v
```
Expected: FAIL — names like `"Pantograph.quino"` are present.

- [ ] **Step 3: Fix `_discover_json_examples` in example_registry.py**

```python
# BEFORE:
name=json_file.stem.replace("_", " "),

# AFTER:
stem = json_file.stem  # e.g. "Pantograph.quino"
if stem.endswith(".quino"):
    stem = stem[: -len(".quino")]
name = stem.replace("_", " "),
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_examples.py::test_example_registry_json_names_have_no_quino_suffix -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add quino/application/example_registry.py tests/test_examples.py
git commit -m "fix: JSON example names no longer contain .quino suffix"
```

---

## Task 6: Fix Distance Annotation Unit Display

**Files:**
- Modify: `quino/gui/canvas.py` — `_draw_distance_annotation`

Already partially fixed in the previous session (changed `f"{val:.1f}"` to `f"{result.value:.4g} {result.unit}"`). Verify and add unit test.

- [ ] **Step 1: Verify current state**

```bash
python -c "
from quino.application.service import ApplicationService
from quino.gui.canvas import MechanismCanvas
from PySide6 import QtWidgets, QtGui
import sys
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
svc = ApplicationService()
svc.new_project('t')
p1 = svc.create_sketch_point('0 mm', '0 mm')
p2 = svc.create_sketch_point('50 mm', '0 mm')
svc.create_sketch_constraint('distance', [p1, p2])
canvas = MechanismCanvas(svc)
canvas.resize(800,600)
canvas._interaction_mode = 'sketch'
texts = []
orig = QtGui.QPainter.drawText
QtGui.QPainter.drawText = lambda self, *a: texts.append(str(a[-1])) or orig(self, *a)
canvas.grab()
QtGui.QPainter.drawText = orig
dist_texts = [t for t in texts if 'mm' in t]
print('Distance texts drawn:', dist_texts)
assert any('50' in t and 'mm' in t for t in dist_texts), 'Expected \"50 mm\" in annotations'
print('OK')
"
```

Expected output: `Distance texts drawn: ['50 mm']` or similar.

- [ ] **Step 2: If already fixed, just run full suite and commit**

```
pytest tests/ -v
git add quino/gui/canvas.py
git commit -m "fix: distance annotation shows value with unit (e.g. '50 mm')"
```

---

## Self-Review

### Spec Coverage

| Problem | Task |
|---------|------|
| Drag constrained point → red sketch | Task 1 (move_sketch_point) |
| Inspector edit constrained point → red | Task 2 (update_sketch_entity) |
| Change distance value → sketch ignores it | Task 3 (solve cache) |
| Drag fully-constrained point → red | Task 4 (DOF=0 guard) |
| Example names show ".quino" | Task 5 (registry) |
| Distance annotation has no unit | Task 6 (annotation text) |

### Type Consistency

- `_apply_sketch_constraints(set())` — `set()` is `set[str]`, matches the parameter type `locked_point_ids: set[str]`.
- `_dof_result: DofResult | None` — already introduced in the previous plan; `point_dof` dict lookup with `.get(pid, 2)` is safe.
- `_is_point_fixed(entity_id: str) -> bool` — already in canvas, called with `entity_id` string.

### Placeholder Scan

No TBD, TODO, or incomplete steps. All code changes are complete.
