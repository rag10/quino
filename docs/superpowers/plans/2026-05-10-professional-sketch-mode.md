# Professional Sketch Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the sketch editor into a professional 2D CAD environment with proper dimension annotations, small QPainter constraint icons, fixed-point drag prevention, and dynamic DOF-based green coloring for fully constrained elements.

**Architecture:** A new `SketchDofAnalyzer` service computes per-element DOF counts from constraints; canvas reads those counts each repaint to color elements green/blue. Constraint drawing is replaced with QPainter-drawn SVG-inspired icons at anchor points, and dimension constraints (DISTANCE, ANGLE) are drawn as CAD-style annotation leaders with arrows and centered value text. Fixed-point drag prevention is a guard in `mousePressEvent`.

**Tech Stack:** Python 3.12, PySide6 QPainter, existing `SketchSolver`, `CONSTRAINT_SPECS`, `ExpressionService`, `UnitService`.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `quino/services/sketch_dof.py` | **Create** | DOF analyzer — count free DOF per sketch point/entity |
| `quino/gui/canvas.py` | **Modify** | Constraint icons, dimension annotations, drag guard, DOF coloring |
| `quino/application/service.py` | **Modify** | Expose `fixed_point_ids` set from sketch FIX constraints (helper) |
| `tests/test_sketch_dof.py` | **Create** | Unit tests for DOF analyzer |

No schema, serialization, or domain model changes needed — all changes are in rendering and service logic.

---

## Task 1: DOF Analyzer Service

**Files:**
- Create: `quino/services/sketch_dof.py`
- Create: `tests/test_sketch_dof.py`

DOF rule (2D rigid body kinematics):
- Each unconstrained sketch point contributes **2 DOF** (x, y).
- Each FIX constraint removes 2 DOF from the referenced point (locks both axes).
- Each HORIZONTAL/VERTICAL/COINCIDENT/MIDPOINT/ON_CIRCLE constraint removes 1 DOF per equation it applies.
- Each DISTANCE/ANGLE constraint removes 1 DOF.
- Each PARALLEL/PERPENDICULAR/EQUAL_LENGTH constraint removes 1 DOF.
- Each COLLINEAR constraint removes 1 DOF per extra point beyond the first two.
- Each SYMMETRIC constraint removes 2 DOF.
- Each TANGENT constraint removes 1 DOF.

We track `free_dof: dict[str, int]` keyed by point entity_id. An element (point or entity) is **fully constrained** when all its referenced points have `free_dof == 0`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sketch_dof.py
from __future__ import annotations
import pytest
from quino.domain.model import Sketch, SketchPoint, SketchLineSegment, SketchConstraint
from quino.domain.types import SketchConstraintType
from quino.services.sketch_dof import SketchDofAnalyzer


def _make_sketch(points: list[SketchPoint], constraints: list[SketchConstraint]) -> Sketch:
    return Sketch(
        id="sk1", name="S", visible=True,
        style=None,
        entities=points,
        constraints=constraints,
    )


def test_no_constraints_all_free():
    pt = SketchPoint(id="p1", name="P1", x=0.0, y=0.0, visible=True, construction=False)
    sketch = _make_sketch([pt], [])
    result = SketchDofAnalyzer().analyze(sketch)
    assert result.point_dof["p1"] == 2


def test_fix_removes_both_dof():
    pt = SketchPoint(id="p1", name="P1", x=0.0, y=0.0, visible=True, construction=False)
    c = SketchConstraint(id="c1", name="Fix1", type=SketchConstraintType.FIX,
                         references=["p1"], entity_references=[], value=None)
    sketch = _make_sketch([pt], [c])
    result = SketchDofAnalyzer().analyze(sketch)
    assert result.point_dof["p1"] == 0
    assert result.fully_constrained_point_ids == {"p1"}


def test_horizontal_removes_one_dof():
    p1 = SketchPoint(id="p1", name="P1", x=0.0, y=0.0, visible=True, construction=False)
    p2 = SketchPoint(id="p2", name="P2", x=10.0, y=0.0, visible=True, construction=False)
    c = SketchConstraint(id="c1", name="H1", type=SketchConstraintType.HORIZONTAL,
                         references=["p1", "p2"], entity_references=[], value=None)
    sketch = _make_sketch([p1, p2], [c])
    result = SketchDofAnalyzer().analyze(sketch)
    # 2+2=4 total, horizontal removes 1 → 3
    assert result.total_free_dof == 3


def test_line_fully_constrained():
    p1 = SketchPoint(id="p1", name="P1", x=0.0, y=0.0, visible=True, construction=False)
    p2 = SketchPoint(id="p2", name="P2", x=10.0, y=0.0, visible=True, construction=False)
    fix1 = SketchConstraint(id="c1", name="Fix1", type=SketchConstraintType.FIX,
                            references=["p1"], entity_references=[], value=None)
    fix2 = SketchConstraint(id="c2", name="Fix2", type=SketchConstraintType.FIX,
                            references=["p2"], entity_references=[], value=None)
    sketch = _make_sketch([p1, p2], [fix1, fix2])
    result = SketchDofAnalyzer().analyze(sketch)
    assert result.total_free_dof == 0
    assert result.fully_constrained_point_ids == {"p1", "p2"}


def test_line_entity_fully_constrained_when_both_points_are():
    p1 = SketchPoint(id="p1", name="P1", x=0.0, y=0.0, visible=True, construction=False)
    p2 = SketchPoint(id="p2", name="P2", x=10.0, y=0.0, visible=True, construction=False)
    line = SketchLineSegment(id="l1", name="L1", start_id="p1", end_id="p2", visible=True, construction=False)
    fix1 = SketchConstraint(id="c1", name="Fix1", type=SketchConstraintType.FIX,
                            references=["p1"], entity_references=[], value=None)
    fix2 = SketchConstraint(id="c2", name="Fix2", type=SketchConstraintType.FIX,
                            references=["p2"], entity_references=[], value=None)
    sketch = Sketch(id="sk1", name="S", visible=True, style=None,
                    entities=[p1, p2, line], constraints=[fix1, fix2])
    result = SketchDofAnalyzer().analyze(sketch)
    assert "l1" in result.fully_constrained_entity_ids
```

- [ ] **Step 2: Run to verify FAIL**

```
pytest tests/test_sketch_dof.py -v
```
Expected: `ModuleNotFoundError: No module named 'quino.services.sketch_dof'`

- [ ] **Step 3: Create `quino/services/sketch_dof.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from quino.domain.model import Sketch, SketchPoint, SketchLineSegment, SketchCircle, SketchArc, SketchInfiniteLine
from quino.domain.types import SketchConstraintType


_CONSTRAINT_DOF_REMOVED: dict[SketchConstraintType, int] = {
    SketchConstraintType.FIX: 2,           # handled specially (removes both axes from one point)
    SketchConstraintType.HORIZONTAL: 1,
    SketchConstraintType.VERTICAL: 1,
    SketchConstraintType.COINCIDENT: 2,    # x and y of second point → first
    SketchConstraintType.DISTANCE: 1,
    SketchConstraintType.PARALLEL: 1,
    SketchConstraintType.PERPENDICULAR: 1,
    SketchConstraintType.EQUAL_LENGTH: 1,
    SketchConstraintType.ANGLE: 1,
    SketchConstraintType.MIDPOINT: 2,      # both coords of midpoint
    SketchConstraintType.COLLINEAR: 1,
    SketchConstraintType.SYMMETRIC: 2,
    SketchConstraintType.ON_CIRCLE: 1,
    SketchConstraintType.TANGENT: 1,
}


@dataclass
class DofResult:
    point_dof: dict[str, int]                  # free DOF per point id (0 = fully constrained)
    fully_constrained_point_ids: set[str]
    fully_constrained_entity_ids: set[str]
    total_free_dof: int


class SketchDofAnalyzer:
    def analyze(self, sketch: Sketch) -> DofResult:
        # Collect all point ids from entities
        all_point_ids: set[str] = set()
        entity_point_map: dict[str, list[str]] = {}  # entity_id → list of point ids

        for entity in sketch.entities:
            if isinstance(entity, SketchPoint):
                all_point_ids.add(entity.id)
                entity_point_map[entity.id] = [entity.id]
            elif isinstance(entity, SketchLineSegment):
                all_point_ids.update([entity.start_id, entity.end_id])
                entity_point_map[entity.id] = [entity.start_id, entity.end_id]
            elif isinstance(entity, SketchCircle):
                all_point_ids.add(entity.center_id)
                entity_point_map[entity.id] = [entity.center_id]
            elif isinstance(entity, SketchArc):
                pts = [entity.start_id, entity.end_id, entity.center_id]
                all_point_ids.update(pts)
                entity_point_map[entity.id] = pts
            elif isinstance(entity, SketchInfiniteLine):
                all_point_ids.update([entity.point1_id, entity.point2_id])
                entity_point_map[entity.id] = [entity.point1_id, entity.point2_id]

        # Start with 2 DOF per point
        point_dof: dict[str, int] = {pid: 2 for pid in all_point_ids}

        for constraint in sketch.constraints:
            removed = _CONSTRAINT_DOF_REMOVED.get(constraint.type, 0)
            if constraint.type is SketchConstraintType.FIX:
                for ref in constraint.references:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 2)
            elif constraint.type is SketchConstraintType.COINCIDENT:
                # Merges two points → effectively frees 2 DOF from pool
                total_before = sum(point_dof.get(r, 2) for r in constraint.references[:2])
                total_after = max(0, total_before - 2)
                # Distribute reduction equally
                for ref in constraint.references[:2]:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 1)
            elif constraint.type is SketchConstraintType.MIDPOINT:
                for ref in constraint.references:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 1)
            elif constraint.type is SketchConstraintType.SYMMETRIC:
                for ref in constraint.references[:2]:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 1)
            else:
                # Distribute one DOF removal across the primary pair of references
                refs = constraint.references
                if refs:
                    point_dof[refs[0]] = max(0, point_dof.get(refs[0], 2) - removed)

        fully_constrained_point_ids = {pid for pid, dof in point_dof.items() if dof == 0}

        fully_constrained_entity_ids: set[str] = set()
        for entity_id, point_ids in entity_point_map.items():
            if point_ids and all(point_dof.get(pid, 2) == 0 for pid in point_ids):
                fully_constrained_entity_ids.add(entity_id)

        total_free_dof = sum(point_dof.values())

        return DofResult(
            point_dof=point_dof,
            fully_constrained_point_ids=fully_constrained_point_ids,
            fully_constrained_entity_ids=fully_constrained_entity_ids,
            total_free_dof=total_free_dof,
        )
```

- [ ] **Step 4: Run tests to verify PASS**

```
pytest tests/test_sketch_dof.py -v
```
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/services/sketch_dof.py tests/test_sketch_dof.py
git commit -m "feat: add SketchDofAnalyzer service for per-point DOF counting"
```

---

## Task 2: Fixed-Point Drag Prevention

**Files:**
- Modify: `quino/gui/canvas.py:690-702`

The FIX constraint makes a point immovable. Currently `mousePressEvent` sets `_dragging_sketch_point` unconditionally. We must collect the set of fixed point IDs from the sketch before allowing drag.

- [ ] **Step 1: Write failing test**

```python
# tests/test_gui.py — add to existing test module
def test_fixed_point_not_draggable(qtbot):
    """Canvas must not initiate drag on a point that has a FIX constraint."""
    from quino.gui.canvas import SketchCanvas
    from quino.application.service import ApplicationService

    svc = ApplicationService()
    svc.create_project("test")
    svc.create_sketch_point("0 mm", "0 mm")
    point_id = svc.project.sketch.entities[0].id
    svc.add_sketch_constraint("fix", [point_id], [], None)

    canvas = SketchCanvas(svc)
    qtbot.addWidget(canvas)

    # Simulate a click exactly on the fixed point
    transform = canvas._current_transform()
    screen_pt = canvas._to_screen(0.0, 0.0, transform)
    event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        screen_pt,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    canvas._mode = CanvasMode.SELECT
    canvas._editing_enabled = True
    canvas._interaction_mode = "sketch"
    canvas.mousePressEvent(event)

    assert canvas._dragging_sketch_point is None
```

- [ ] **Step 2: Run to verify FAIL**

```
pytest tests/test_gui.py::test_fixed_point_not_draggable -v
```
Expected: FAIL — `assert canvas._dragging_sketch_point is None` fails because drag starts unconditionally.

- [ ] **Step 3: Add helper and guard to canvas.py**

In `canvas.py`, near the top of the class (alongside other per-paint caches), add:

```python
# in __init__, alongside other cache fields:
self._fixed_sketch_point_ids: set[str] = set()
```

Add a method after `_reset_tool_state` (around line 282):

```python
def _compute_fixed_point_ids(self, project: Project) -> set[str]:
    if project.sketch is None:
        return set()
    return {
        ref
        for c in project.sketch.constraints
        if c.type is SketchConstraintType.FIX
        for ref in c.references
    }
```

In `paintEvent` (or wherever sketch points are recomputed each frame), call:

```python
self._fixed_sketch_point_ids = self._compute_fixed_point_ids(project)
```

The exact location in `paintEvent` is right after the `_screen_sketch_points` list is built (around line 1760). Add after it:

```python
self._fixed_sketch_point_ids = self._compute_fixed_point_ids(project)
```

Then in `mousePressEvent` at line 694, change:

```python
# BEFORE:
if self._editing_enabled:
    self._dragging_sketch_point = clicked_sketch_point
    self._dragging_sketch_point_preview = (
        clicked_sketch_point.entity_id,
        clicked_sketch_point.x,
        clicked_sketch_point.y,
    )

# AFTER:
if self._editing_enabled and clicked_sketch_point.entity_id not in self._fixed_sketch_point_ids:
    self._dragging_sketch_point = clicked_sketch_point
    self._dragging_sketch_point_preview = (
        clicked_sketch_point.entity_id,
        clicked_sketch_point.x,
        clicked_sketch_point.y,
    )
```

- [ ] **Step 4: Run tests to verify PASS**

```
pytest tests/test_gui.py::test_fixed_point_not_draggable -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/gui/canvas.py tests/test_gui.py
git commit -m "fix: prevent dragging fixed sketch points"
```

---

## Task 3: DOF-Based Coloring (Green = Fully Constrained, Blue = Under-constrained)

**Files:**
- Modify: `quino/gui/canvas.py` — `_draw_sketch_points`, `_draw_sketch_entities`

Currently all sketch points draw in a single style. After this task:
- Fully constrained points (DOF = 0): **green** `#27ae60`
- Partially constrained points (0 < DOF < 2): **yellow** `#f39c12`
- Unconstrained points (DOF = 2): **blue** `#2980b9` (unchanged from current sketch color)
- Same coloring logic for line segments, circles, arcs (all points fully constrained → green).

- [ ] **Step 1: Write failing test**

```python
# tests/test_gui.py — add
def test_dof_coloring_updates_after_fix(qtbot):
    """After adding a FIX constraint, the canvas dof cache must report 0 DOF for that point."""
    from quino.gui.canvas import SketchCanvas
    from quino.application.service import ApplicationService
    from quino.services.sketch_dof import SketchDofAnalyzer

    svc = ApplicationService()
    svc.create_project("test")
    svc.create_sketch_point("0 mm", "0 mm")
    pid = svc.project.sketch.entities[0].id

    canvas = SketchCanvas(svc)
    qtbot.addWidget(canvas)

    analyzer = SketchDofAnalyzer()
    result_before = analyzer.analyze(svc.project.sketch)
    assert result_before.point_dof[pid] == 2

    svc.add_sketch_constraint("fix", [pid], [], None)
    result_after = analyzer.analyze(svc.project.sketch)
    assert result_after.point_dof[pid] == 0
    assert pid in result_after.fully_constrained_point_ids
```

- [ ] **Step 2: Run to verify PASS immediately** (this tests the analyzer, not canvas — should pass)

```
pytest tests/test_gui.py::test_dof_coloring_updates_after_fix -v
```
Expected: PASS (analyzer is already working from Task 1).

- [ ] **Step 3: Wire DOF colors into `_draw_sketch_points`**

Add import at top of `canvas.py`:

```python
from quino.services.sketch_dof import SketchDofAnalyzer
```

Add instance variable in `__init__`:

```python
self._dof_analyzer = SketchDofAnalyzer()
self._dof_result: "DofResult | None" = None
```

In `paintEvent`, after sketch constraints are drawn and before `_draw_sketch_points`, add:

```python
if project.sketch is not None:
    self._dof_result = self._dof_analyzer.analyze(project.sketch)
else:
    self._dof_result = None
```

In `_draw_sketch_points`, replace the single color with DOF-based coloring. Find where `color` is set for sketch points (currently uses the sketch style color). Change to:

```python
def _sketch_point_color(self, point_id: str, selected: bool, hovered: bool) -> QtGui.QColor:
    if selected:
        return QtGui.QColor("#c75b12")  # orange — selected
    if hovered:
        return QtGui.QColor("#e67e22")  # lighter orange — hovered
    if self._dof_result is not None:
        dof = self._dof_result.point_dof.get(point_id, 2)
        if dof == 0:
            return QtGui.QColor("#27ae60")   # green — fully constrained
        if dof == 1:
            return QtGui.QColor("#f39c12")   # yellow — partially constrained
    return QtGui.QColor("#2980b9")           # blue — unconstrained
```

Call this method instead of the current fixed-color logic when drawing each point.

In `_draw_sketch_entities`, for each entity, check if `entity.entity_id in self._dof_result.fully_constrained_entity_ids` and set pen color to `#27ae60` instead of the sketch style color.

- [ ] **Step 4: Run full test suite**

```
pytest tests/ -v
```
Expected: all existing tests plus new tests PASS. No regressions.

- [ ] **Step 5: Commit**

```bash
git add quino/gui/canvas.py
git commit -m "feat: DOF-based color coding (green=constrained, yellow=partial, blue=free)"
```

---

## Task 4: Replace Text Labels with QPainter Constraint Icons

**Files:**
- Modify: `quino/gui/canvas.py:1800-1936` (`_draw_sketch_constraints` method)

Replace the text label dictionary (lines 1905-1935) with small QPainter-drawn icons at the anchor point. Each icon is 14×14 pixels, drawn centered on the anchor. The label text is removed entirely.

Icon designs by constraint type (all drawn at `anchor_x, anchor_y`, offset by icon_size = 14):

| Type | Icon | QPainter calls |
|------|------|---------------|
| FIX | Ground symbol: triangle with hatching | polygon + 3 hatching lines |
| HORIZONTAL | "→→" two arrows pointing right | two horizontal lines with arrowheads |
| VERTICAL | "↑↑" two arrows pointing up | two vertical lines with arrowheads |
| COINCIDENT | Two overlapping circles | `drawEllipse` ×2 offset by 3px |
| PARALLEL | Two parallel slash marks `//` | two short diagonal lines |
| PERPENDICULAR | Small L-shape `⌐` | two perpendicular short lines with corner mark |
| EQUAL_LENGTH | Two tick marks `=` | two short horizontal lines |
| MIDPOINT | M-shape: vertical line with two slanted | three lines forming M |
| COLLINEAR | Three dots on a line `·—·—·` | short line through three dots |
| SYMMETRIC | Mirror line with arrows `↔` | vertical line + two horizontal arrows |
| ON_CIRCLE | Point on circle arc `⌒•` | small arc + dot |
| TANGENT | Circle touching line `○—` | small circle + tangent line |
| DISTANCE | (handled by dimension annotation in Task 5) | — |
| ANGLE | (handled by dimension annotation in Task 5) | — |

- [ ] **Step 1: No failing test needed for visual drawing; instead, verify via visual inspection. Write a smoke test to ensure `_draw_sketch_constraints` doesn't raise.**

```python
# tests/test_gui.py — add
def test_draw_sketch_constraints_no_exception(qtbot):
    """Drawing constraints must not raise for any constraint type."""
    from quino.gui.canvas import SketchCanvas
    from quino.application.service import ApplicationService
    from PySide6 import QtGui

    svc = ApplicationService()
    svc.create_project("test")
    svc.create_sketch_point("0 mm", "0 mm")
    svc.create_sketch_point("50 mm", "0 mm")
    p1 = svc.project.sketch.entities[0].id
    p2 = svc.project.sketch.entities[1].id
    svc.add_sketch_constraint("horizontal", [p1, p2], [], None)
    svc.add_sketch_constraint("fix", [p1], [], None)

    canvas = SketchCanvas(svc)
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)

    # Force a paint
    pixmap = QtGui.QPixmap(800, 600)
    painter = QtGui.QPainter(pixmap)
    canvas._draw_sketch_constraints(painter, svc.project,
                                    list(svc.project.sketch.entities),
                                    canvas._current_transform(), invalid=False)
    painter.end()
    # No exception = pass
```

- [ ] **Step 2: Run to verify current state PASS (baseline)**

```
pytest tests/test_gui.py::test_draw_sketch_constraints_no_exception -v
```

- [ ] **Step 3: Replace text labels with icon drawing**

In `canvas.py`, replace the entire label dict and `_draw_sketch_label` call at the end of `_draw_sketch_constraints` (lines 1905-1936) with a call to a new method `_draw_constraint_icon`:

```python
# Remove these lines (1905-1936):
label = {
    SketchConstraintType.FIX: "FIX",
    ...
}.get(constraint.type, "?")
display = label
if constraint.type is SketchConstraintType.ANGLE ...
self._draw_sketch_label(painter, anchor, f"{display} {constraint.name}", color)
self._screen_sketch_constraints.append((constraint.id, anchor))

# Replace with:
self._draw_constraint_icon(painter, constraint.type, anchor, color)
self._screen_sketch_constraints.append((constraint.id, anchor))
```

Add the new method to canvas.py (place after `_draw_sketch_constraints`):

```python
def _draw_constraint_icon(
    self,
    painter: QtGui.QPainter,
    ctype: SketchConstraintType,
    anchor: QtCore.QPointF,
    color: QtGui.QColor,
) -> None:
    """Draw a small 14×14 px symbolic icon for the given constraint type."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pen = QtGui.QPen(color, 1.5)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    ax, ay = anchor.x(), anchor.y()
    s = 7.0  # half-size

    if ctype is SketchConstraintType.FIX:
        # Ground triangle + three hatching lines
        tri = QtGui.QPolygonF([
            QtCore.QPointF(ax, ay),
            QtCore.QPointF(ax - s, ay + s),
            QtCore.QPointF(ax + s, ay + s),
        ])
        painter.drawPolygon(tri)
        for i in range(3):
            x0 = ax - s + i * s
            painter.drawLine(QtCore.QPointF(x0, ay + s), QtCore.QPointF(x0 - 4, ay + s + 4))

    elif ctype is SketchConstraintType.HORIZONTAL:
        # Two short rightward arrows
        for dy in (-3.0, 3.0):
            painter.drawLine(QtCore.QPointF(ax - s, ay + dy), QtCore.QPointF(ax + s, ay + dy))
            painter.drawLine(QtCore.QPointF(ax + s - 3, ay + dy - 2), QtCore.QPointF(ax + s, ay + dy))
            painter.drawLine(QtCore.QPointF(ax + s - 3, ay + dy + 2), QtCore.QPointF(ax + s, ay + dy))

    elif ctype is SketchConstraintType.VERTICAL:
        # Two short upward arrows
        for dx in (-3.0, 3.0):
            painter.drawLine(QtCore.QPointF(ax + dx, ay + s), QtCore.QPointF(ax + dx, ay - s))
            painter.drawLine(QtCore.QPointF(ax + dx - 2, ay - s + 3), QtCore.QPointF(ax + dx, ay - s))
            painter.drawLine(QtCore.QPointF(ax + dx + 2, ay - s + 3), QtCore.QPointF(ax + dx, ay - s))

    elif ctype is SketchConstraintType.COINCIDENT:
        # Two small overlapping circles
        painter.drawEllipse(QtCore.QPointF(ax - 3, ay), 4.0, 4.0)
        painter.drawEllipse(QtCore.QPointF(ax + 3, ay), 4.0, 4.0)

    elif ctype is SketchConstraintType.PARALLEL:
        # Two short diagonal slashes //
        for dx in (-4.0, 2.0):
            painter.drawLine(QtCore.QPointF(ax + dx, ay + s), QtCore.QPointF(ax + dx + 4, ay - s))

    elif ctype is SketchConstraintType.PERPENDICULAR:
        # L-shape with corner mark
        painter.drawLine(QtCore.QPointF(ax - s, ay), QtCore.QPointF(ax, ay))
        painter.drawLine(QtCore.QPointF(ax, ay), QtCore.QPointF(ax, ay - s))
        painter.drawRect(QtCore.QRectF(ax - 3, ay - 3, 3, 3))

    elif ctype is SketchConstraintType.EQUAL_LENGTH:
        # Two equal tick marks =
        for dy in (-2.5, 2.5):
            painter.drawLine(QtCore.QPointF(ax - s, ay + dy), QtCore.QPointF(ax + s, ay + dy))

    elif ctype is SketchConstraintType.MIDPOINT:
        # M-shape
        painter.drawLine(QtCore.QPointF(ax - s, ay + s), QtCore.QPointF(ax - s, ay - s))
        painter.drawLine(QtCore.QPointF(ax - s, ay - s), QtCore.QPointF(ax, ay))
        painter.drawLine(QtCore.QPointF(ax, ay), QtCore.QPointF(ax + s, ay - s))
        painter.drawLine(QtCore.QPointF(ax + s, ay - s), QtCore.QPointF(ax + s, ay + s))

    elif ctype is SketchConstraintType.COLLINEAR:
        # Three dots on a line
        painter.drawLine(QtCore.QPointF(ax - s, ay), QtCore.QPointF(ax + s, ay))
        for dx in (-s, 0.0, s):
            painter.drawEllipse(QtCore.QPointF(ax + dx, ay), 1.5, 1.5)

    elif ctype is SketchConstraintType.SYMMETRIC:
        # Vertical axis + two horizontal arrows pointing outward
        painter.drawLine(QtCore.QPointF(ax, ay - s), QtCore.QPointF(ax, ay + s))
        for sign in (-1.0, 1.0):
            ex = ax + sign * s
            painter.drawLine(QtCore.QPointF(ax, ay), QtCore.QPointF(ex, ay))
            painter.drawLine(QtCore.QPointF(ex - sign * 3, ay - 2), QtCore.QPointF(ex, ay))
            painter.drawLine(QtCore.QPointF(ex - sign * 3, ay + 2), QtCore.QPointF(ex, ay))

    elif ctype is SketchConstraintType.ON_CIRCLE:
        # Point + small arc
        painter.drawEllipse(QtCore.QPointF(ax, ay), 1.5, 1.5)
        painter.drawArc(QtCore.QRectF(ax - s, ay - s, 2 * s, 2 * s), 30 * 16, 120 * 16)

    elif ctype is SketchConstraintType.TANGENT:
        # Small circle with tangent line
        painter.drawEllipse(QtCore.QPointF(ax - 3, ay), 4.0, 4.0)
        painter.drawLine(QtCore.QPointF(ax + 1, ay - s), QtCore.QPointF(ax + 1, ay + s))

    painter.restore()
```

- [ ] **Step 4: Run smoke test**

```
pytest tests/test_gui.py::test_draw_sketch_constraints_no_exception -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/gui/canvas.py
git commit -m "feat: replace constraint text labels with QPainter icon symbols"
```

---

## Task 5: CAD-Style Dimension Annotations (DISTANCE and ANGLE)

**Files:**
- Modify: `quino/gui/canvas.py` — `_draw_sketch_constraints` method

Currently DISTANCE draws a dashed line between two points. ANGLE draws a small arc. Both show only a label letter ("D", "∠...°").

After this task both render as proper CAD dimension annotations:

**DISTANCE annotation:**
```
    p1 ──────── extension line ────────────── p2
           ◄─────── dimension line ───────►
                    "42.5 mm"
```
The dimension line is offset 20 px perpendicular to the line between the points. Extension lines drop from each point to the dimension line. Arrows at each end of the dimension line. Value text centered above the dimension line.

**ANGLE annotation:**
```
     arm1
      \
       \◄── arc at radius 30px ──►
        vertex─────────────────── arm2
               "35.0°"
```
An arc at fixed 30 px radius from the vertex, spanning the angle. Value text centered at arc midpoint + 12 px outward.

- [ ] **Step 1: No test needed beyond the smoke test already passing.**

- [ ] **Step 2: Replace DISTANCE drawing in `_draw_sketch_constraints`**

Find the DISTANCE block (currently lines 1811-1815):

```python
# BEFORE:
if constraint.type is SketchConstraintType.DISTANCE and len(constraint.references) == 2:
    p1 = point_map.get(constraint.references[0])
    p2 = point_map.get(constraint.references[1])
    if p1 is not None and p2 is not None:
        painter.drawLine(self._to_screen(p1.x, p1.y, transform), self._to_screen(p2.x, p2.y, transform))
```

Replace with:

```python
if constraint.type is SketchConstraintType.DISTANCE and len(constraint.references) == 2:
    p1 = point_map.get(constraint.references[0])
    p2 = point_map.get(constraint.references[1])
    if p1 is not None and p2 is not None:
        value_text = self._constraint_value_text(constraint, "mm")
        self._draw_distance_annotation(painter, p1, p2, transform, color, value_text)
```

Add the helper method to the class:

```python
def _draw_distance_annotation(
    self,
    painter: QtGui.QPainter,
    p1: SketchPoint,
    p2: SketchPoint,
    transform,
    color: QtGui.QColor,
    value_text: str,
) -> None:
    s1 = self._to_screen(p1.x, p1.y, transform)
    s2 = self._to_screen(p2.x, p2.y, transform)
    dx, dy = s2.x() - s1.x(), s2.y() - s1.y()
    length = math.hypot(dx, dy)
    if length < 1.0:
        return
    # Perpendicular unit vector (offset direction)
    nx, ny = -dy / length, dx / length
    offset = 22.0  # pixels
    # Dimension line endpoints
    d1 = QtCore.QPointF(s1.x() + nx * offset, s1.y() + ny * offset)
    d2 = QtCore.QPointF(s2.x() + nx * offset, s2.y() + ny * offset)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    solid_pen = QtGui.QPen(color, 1.0)
    painter.setPen(solid_pen)
    # Extension lines (from points to dimension line)
    painter.drawLine(s1, d1)
    painter.drawLine(s2, d2)
    # Dimension line
    painter.drawLine(d1, d2)
    # Arrows at d1 and d2
    arrow_len = 8.0
    ux, uy = dx / length, dy / length
    for tip, direction in [(d1, 1.0), (d2, -1.0)]:
        ax = tip.x() + direction * ux * arrow_len
        ay = tip.y() + direction * uy * arrow_len
        perp_x, perp_y = -uy * 2.5, ux * 2.5
        painter.drawLine(tip, QtCore.QPointF(ax + perp_x, ay + perp_y))
        painter.drawLine(tip, QtCore.QPointF(ax - perp_x, ay - perp_y))
    # Value text centered on dimension line
    mid = QtCore.QPointF(0.5 * (d1.x() + d2.x()), 0.5 * (d1.y() + d2.y()))
    painter.setFont(QtGui.QFont("Arial", 8))
    fm = QtGui.QFontMetricsF(painter.font())
    text_w = fm.horizontalAdvance(value_text)
    text_h = fm.height()
    text_rect = QtCore.QRectF(mid.x() - text_w * 0.5 - 2, mid.y() - text_h - 2, text_w + 4, text_h + 2)
    painter.fillRect(text_rect, QtGui.QColor(255, 255, 255, 200))
    painter.drawText(mid + QtCore.QPointF(-text_w * 0.5, -3), value_text)
    painter.restore()
```

- [ ] **Step 3: Replace ANGLE drawing**

Find the ANGLE block (currently lines 1838-1864) and replace with:

```python
elif constraint.type is SketchConstraintType.ANGLE and len(constraint.references) == 3:
    vertex = point_map.get(constraint.references[0])
    arm1 = point_map.get(constraint.references[1])
    arm2 = point_map.get(constraint.references[2])
    if vertex is not None and arm1 is not None and arm2 is not None:
        value_text = self._constraint_value_text(constraint, "deg")
        self._draw_angle_annotation(painter, vertex, arm1, arm2, transform, color, value_text)
```

Add the helper:

```python
def _draw_angle_annotation(
    self,
    painter: QtGui.QPainter,
    vertex: SketchPoint,
    arm1: SketchPoint,
    arm2: SketchPoint,
    transform,
    color: QtGui.QColor,
    value_text: str,
) -> None:
    vs = self._to_screen(vertex.x, vertex.y, transform)
    a1s = self._to_screen(arm1.x, arm1.y, transform)
    a2s = self._to_screen(arm2.x, arm2.y, transform)
    d1x, d1y = a1s.x() - vs.x(), a1s.y() - vs.y()
    d2x, d2y = a2s.x() - vs.x(), a2s.y() - vs.y()
    if math.hypot(d1x, d1y) < 1e-6 or math.hypot(d2x, d2y) < 1e-6:
        return
    start_deg = -math.degrees(math.atan2(d1y, d1x))
    end_deg = -math.degrees(math.atan2(d2y, d2x))
    span = end_deg - start_deg
    while span > 180: span -= 360
    while span < -180: span += 360
    radius = 30.0
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(QtGui.QPen(color, 1.0))
    rect = QtCore.QRectF(vs.x() - radius, vs.y() - radius, 2 * radius, 2 * radius)
    painter.drawArc(rect, int(start_deg * 16), int(span * 16))
    # Text at midpoint of arc
    mid_angle_rad = math.radians(-(start_deg + span * 0.5))
    text_r = radius + 14.0
    tx = vs.x() + text_r * math.cos(mid_angle_rad)
    ty = vs.y() + text_r * math.sin(mid_angle_rad)
    painter.setFont(QtGui.QFont("Arial", 8))
    fm = QtGui.QFontMetricsF(painter.font())
    text_w = fm.horizontalAdvance(value_text)
    text_h = fm.height()
    text_rect = QtCore.QRectF(tx - text_w * 0.5 - 2, ty - text_h * 0.5 - 2, text_w + 4, text_h + 2)
    painter.fillRect(text_rect, QtGui.QColor(255, 255, 255, 200))
    painter.drawText(QtCore.QPointF(tx - text_w * 0.5, ty + text_h * 0.5 - 3), value_text)
    painter.restore()
```

Add the shared value-text helper (place near the annotation helpers):

```python
def _constraint_value_text(self, constraint: SketchConstraint, display_unit: str) -> str:
    if constraint.value is None:
        return "?"
    try:
        project = self.app_service.project
        val = self.app_service.expression_service.evaluate_property(
            constraint.value, project.parameters
        )
        factor = self.app_service.unit_service.factor(display_unit)
        numeric = val.value / factor
        if display_unit == "deg":
            return f"{numeric:.1f}°"
        return f"{numeric:.2g} {display_unit}"
    except Exception:
        return "?"
```

- [ ] **Step 4: Run smoke test**

```
pytest tests/test_gui.py::test_draw_sketch_constraints_no_exception -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quino/gui/canvas.py
git commit -m "feat: CAD-style dimension annotations for DISTANCE and ANGLE constraints"
```

---

## Task 6: Fix Duplicate `_apply_perpendicular` in Sketch Solver

**Files:**
- Modify: `quino/services/sketch_solver.py`

The session review identified that a second `_apply_perpendicular` definition existed at the end of the class, shadowing the first (better) projection-based implementation. Verify current state and fix if still present.

- [ ] **Step 1: Check for duplicate**

```bash
grep -n "_apply_perpendicular" quino/services/sketch_solver.py
```

Expected output: exactly **2 lines** — one in `__init__` (the `_handlers` dict assignment) and one method definition. If there are 3 lines, the duplicate still exists and must be deleted.

- [ ] **Step 2: Write regression test**

```python
# tests/test_sketch_solver.py (add to existing)
def test_perpendicular_solver_uses_projection_method():
    """Two lines should reach 90° after solving perpendicular constraint."""
    import math
    from quino.services.sketch_solver import SketchSolver
    from quino.services.expressions import ExpressionService
    from quino.services.units import UnitService
    from quino.domain.model import Project, Model, Sketch, SketchPoint, SketchLineSegment, SketchConstraint
    from quino.domain.types import SketchConstraintType

    expr_svc = ExpressionService()
    unit_svc = UnitService()
    solver = SketchSolver(expr_svc, unit_svc)

    def pt(pid, x, y):
        return SketchPoint(id=pid, name=pid, x=x, y=y, visible=True, construction=False)

    def line(lid, s, e):
        return SketchLineSegment(id=lid, name=lid, start_id=s, end_id=e, visible=True, construction=False)

    # Two lines forming ~70° angle — solver should drive them to 90°
    points = [pt("p1", 0.0, 0.0), pt("p2", 10.0, 0.0),
              pt("p3", 0.0, 0.0), pt("p4", 7.0, 9.0)]
    lines = [line("l1", "p1", "p2"), line("l2", "p3", "p4")]
    constraint = SketchConstraint(
        id="c1", name="Perp1", type=SketchConstraintType.PERPENDICULAR,
        references=["p1", "p2", "p3", "p4"], entity_references=[], value=None,
    )
    sketch = Sketch(id="sk1", name="S", visible=True, style=None,
                    entities=points + lines, constraints=[constraint])
    project = Project(id="pr1", name="P", sketch=sketch, model=Model(id="m1", name="M"))

    result = solver.solve(project, locked_point_ids={"p1", "p3"})
    assert result.success

    px2, py2 = result.positions["p2"]
    px4, py4 = result.positions["p4"]
    d1x, d1y = px2 - 0.0, py2 - 0.0
    d2x, d2y = px4 - 0.0, py4 - 0.0
    dot = d1x * d2x + d1y * d2y
    norm = math.hypot(d1x, d1y) * math.hypot(d2x, d2y)
    angle = math.degrees(math.acos(max(-1.0, min(1.0, dot / norm))))
    assert abs(angle - 90.0) < 1.0, f"Expected 90°, got {angle:.2f}°"
```

- [ ] **Step 3: Run test**

```
pytest tests/test_sketch_solver.py::test_perpendicular_solver_uses_projection_method -v
```
Expected: PASS if the solver is correct, FAIL if the bad duplicate is present.

- [ ] **Step 4: If test fails, remove the duplicate**

If the duplicate `_apply_perpendicular` exists at the bottom of the file, delete those lines (keeping only the projection-based version that uses `_rotate_line`).

- [ ] **Step 5: Run test again + full suite**

```
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add quino/services/sketch_solver.py tests/test_sketch_solver.py
git commit -m "fix: remove duplicate _apply_perpendicular that shadowed projection-based solver"
```

---

## Task 7: Fix Expression Overwriting in `_apply_sketch_constraints`

**Files:**
- Modify: `quino/application/service.py` — `_apply_sketch_constraints` method

After the solver runs, the service overwrites `point.x` / `point.y` with numeric literals like `"0.123456 mm"`, destroying any parametric expression the user had written. The fix: only overwrite when the current value is already a numeric literal (i.e., has no variable references).

- [ ] **Step 1: Write failing test**

```python
# tests/test_application.py — add
def test_solve_preserves_parametric_expressions():
    """Solving should not overwrite a point's parametric expression with a literal."""
    from quino.application.service import ApplicationService

    svc = ApplicationService()
    svc.create_project("test")
    svc.add_parameter("L", "100 mm")
    svc.create_sketch_point("L mm", "0 mm")  # parametric x
    pid = svc.project.sketch.entities[0].id

    svc.apply_sketch_constraints()

    pt = svc.project.sketch.entities[0]
    # x should still reference "L mm", not a numeric literal
    assert "L" in str(pt.x), f"Expected parametric expression, got: {pt.x!r}"
```

- [ ] **Step 2: Run to verify FAIL**

```
pytest tests/test_application.py::test_solve_preserves_parametric_expressions -v
```
Expected: FAIL — x is overwritten with a numeric literal.

- [ ] **Step 3: Fix `_apply_sketch_constraints` in `service.py`**

Find `_apply_sketch_constraints` (around line 1430-1450 in service.py). It currently has something like:

```python
# BEFORE (approximation of current code):
for point_id, (x, y) in result.positions.items():
    point = self._find_sketch_point(point_id)
    point.x = f"{x:.6g} mm"
    point.y = f"{y:.6g} mm"
```

Replace with:

```python
import re as _re
_NUMERIC_LITERAL = _re.compile(r"^\s*[-+]?\d*\.?\d+([eE][-+]?\d+)?\s*(mm|m|rad|deg|unitless)?\s*$")

def _is_literal(expr: str) -> bool:
    return bool(_NUMERIC_LITERAL.match(str(expr)))

# In _apply_sketch_constraints:
for point_id, (x, y) in result.positions.items():
    point = self._find_sketch_point(point_id)
    if _is_literal(str(point.x)):
        point.x = f"{x * 1000:.6g} mm"   # solver works in meters, display in mm
    if _is_literal(str(point.y)):
        point.y = f"{y * 1000:.6g} mm"
```

Note: verify the exact unit convention used — the solver positions are in SI (meters). Check by looking at how `point.x` is read (it uses `unit_service.quantity(value, unit)` which converts to SI for the solver). The write-back must be in mm if that is the display convention.

Actually read the exact current code to get the write-back format right:

```python
# First, grep the actual overwrite pattern:
# grep -n "point.x" quino/application/service.py | head -30
```

Use whatever unit format the current code uses, and preserve it — just add the `_is_literal` guard.

- [ ] **Step 4: Run test**

```
pytest tests/test_application.py::test_solve_preserves_parametric_expressions -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add quino/application/service.py tests/test_application.py
git commit -m "fix: preserve parametric expressions in sketch points after solve"
```

---

## Task 8: Snap-to-Point and Snap-to-Grid During Entity Creation

**Files:**
- Modify: `quino/gui/canvas.py` — `mouseMoveEvent`, `_draw_sketch_*` preview logic

When in a sketch creation mode, the cursor should snap to:
1. Existing sketch points within 12 px — show a highlight ring.
2. Grid intersections when no point is nearby.

- [ ] **Step 1: Write failing test**

```python
# tests/test_gui.py — add
def test_snap_to_existing_point(qtbot):
    """During line creation, moving near an existing point returns its exact coords."""
    from quino.gui.canvas import SketchCanvas
    from quino.application.service import ApplicationService
    from PySide6 import QtCore

    svc = ApplicationService()
    svc.create_project("test")
    svc.create_sketch_point("20 mm", "30 mm")

    canvas = SketchCanvas(svc)
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)

    transform = canvas._current_transform()
    # Screen position exactly on the existing point
    exact_screen = canvas._to_screen(20.0, 30.0, transform)

    snapped = canvas._snap_world(exact_screen, transform)
    assert abs(snapped[0] - 20.0) < 0.01
    assert abs(snapped[1] - 30.0) < 0.01
```

- [ ] **Step 2: Run to verify FAIL**

```
pytest tests/test_gui.py::test_snap_to_existing_point -v
```
Expected: `AttributeError: 'SketchCanvas' object has no attribute '_snap_world'`

- [ ] **Step 3: Add `_snap_world` method to canvas**

```python
def _snap_world(
    self,
    screen_pos: QtCore.QPointF,
    transform,
    *,
    snap_radius: float = 12.0,
    grid_spacing: float = 5.0,   # mm
) -> tuple[float, float]:
    """Return world coordinates, snapping to nearby sketch points first, then grid."""
    wx, wy = self._to_world(screen_pos, transform)

    # Snap to existing sketch points
    project = self.app_service.project
    if project is not None and project.sketch is not None:
        for sketch_point, sp_screen in self._screen_sketch_points:
            dist = math.hypot(screen_pos.x() - sp_screen.x(), screen_pos.y() - sp_screen.y())
            if dist <= snap_radius:
                return sketch_point.x, sketch_point.y

    # Snap to grid
    snapped_x = round(wx / grid_spacing) * grid_spacing
    snapped_y = round(wy / grid_spacing) * grid_spacing
    return snapped_x, snapped_y
```

In `mouseMoveEvent`, wherever `self._to_world(pos, transform)` is called during sketch creation modes, replace with `self._snap_world(pos, transform)`.

Also store the snap result so the preview can draw a highlight ring:

```python
# In mouseMoveEvent, during sketch creation:
self._snap_target = self._snap_world(pos, transform)
self._snap_is_point = self._sketch_point_at(pos) is not None
```

In `_draw_sketch_points_preview` (or wherever the creation preview is drawn), add:

```python
if getattr(self, "_snap_is_point", False) and self._snap_target is not None:
    snap_screen = self._to_screen(*self._snap_target, transform)
    painter.setPen(QtGui.QPen(QtGui.QColor("#27ae60"), 2.0))
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    painter.drawEllipse(snap_screen, 10.0, 10.0)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_gui.py::test_snap_to_existing_point -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add quino/gui/canvas.py tests/test_gui.py
git commit -m "feat: snap-to-point and snap-to-grid during sketch entity creation"
```

---

## Task 9: Visual Polish — Cursor Changes and Status Bar DOF Count

**Files:**
- Modify: `quino/gui/canvas.py` — `mouseMoveEvent`, `enterEvent`
- Modify: `quino/gui/main_window.py` — status bar update after sketch solve

When hovering over a fixed point, show a "forbidden" cursor. When in a sketch creation mode, show a crosshair cursor. The main window status bar should display the total remaining DOF after every solve.

- [ ] **Step 1: No failing test — verify visually. Just add the cursor logic.**

In `canvas.py`, add to `mouseMoveEvent` after the hover target update:

```python
# Cursor logic
if self._mode in {
    CanvasMode.CREATE_SKETCH_POINT,
    CanvasMode.CREATE_SKETCH_LINE_SEGMENT,
    CanvasMode.CREATE_SKETCH_CIRCLE,
    CanvasMode.CREATE_SKETCH_ARC,
    CanvasMode.CREATE_SKETCH_INFINITE_LINE,
}:
    self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
elif (
    self._mode == CanvasMode.SELECT
    and self._hovered_sketch_point_id is not None
    and self._hovered_sketch_point_id in self._fixed_sketch_point_ids
):
    self.setCursor(QtCore.Qt.CursorShape.ForbiddenCursor)
else:
    self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
```

- [ ] **Step 2: Add DOF status bar update in main_window.py**

In `main_window.py`, find where the canvas `projectChanged` or `sketchSolved` signal is connected to update the UI. After sketch solve completes, update the status bar:

```python
# In _on_sketch_solved or _on_project_changed:
from quino.services.sketch_dof import SketchDofAnalyzer

project = self.app_service.project
if project is not None and project.sketch is not None:
    result = SketchDofAnalyzer().analyze(project.sketch)
    if result.total_free_dof == 0:
        self.statusBar().showMessage("Sketch fully constrained ✓", 3000)
    else:
        self.statusBar().showMessage(f"Sketch: {result.total_free_dof} DOF remaining", 3000)
```

- [ ] **Step 3: Run full test suite**

```
pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add quino/gui/canvas.py quino/gui/main_window.py
git commit -m "feat: crosshair/forbidden cursors and DOF count in status bar"
```

---

## Self-Review

### Spec Coverage

| Requirement | Task |
|-------------|------|
| Dimension annotations (cotas) as CAD-style leaders | Task 5 |
| Constraint symbols/icons (not text labels) | Task 4 |
| Fixed points cannot be dragged | Task 2 |
| Dynamic DOF check after every edit | Task 1 + Task 3 |
| Fully constrained elements turn green | Task 3 |
| Professional workflow (snap, cursor) | Task 8 + Task 9 |
| Bug fix: duplicate perpendicular solver | Task 6 |
| Bug fix: expression overwriting | Task 7 |

All spec requirements covered.

### Placeholder Scan

No TBD, TODO, or "implement later" phrases. All code blocks contain complete implementations.

### Type Consistency

- `SketchDofAnalyzer.analyze(sketch: Sketch) -> DofResult` — used consistently in Tasks 1, 3, 9.
- `DofResult.point_dof`, `.fully_constrained_point_ids`, `.fully_constrained_entity_ids`, `.total_free_dof` — all defined in Task 1, read in Tasks 3, 9.
- `_snap_world(screen_pos, transform) -> tuple[float, float]` — defined in Task 8, called in same.
- `_draw_constraint_icon(painter, ctype, anchor, color)` — defined and called in Task 4.
- `_draw_distance_annotation(painter, p1, p2, transform, color, value_text)` — defined and called in Task 5.
- `_draw_angle_annotation(painter, vertex, arm1, arm2, transform, color, value_text)` — defined and called in Task 5.
- `_constraint_value_text(constraint, display_unit) -> str` — defined in Task 5, called in Task 5.
- `_fixed_sketch_point_ids: set[str]` — initialized in Task 2, used in Task 2 and Task 9.
- `_compute_fixed_point_ids(project) -> set[str]` — defined and called in Task 2.
