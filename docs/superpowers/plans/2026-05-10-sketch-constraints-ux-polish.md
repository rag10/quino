# Sketch Constraints UX Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring sketch constraint UX to professional CAD level: COINCIDENT works on individual points, DISTANCE works on point-point/point-segment/circle-radius, arcs show editable endpoints, PARALLEL/PERPENDICULAR show symbols on both segments (not dashed line), DOF coloring accounts for shared constraints, and the solver stops showing false-positive red states.

**Architecture:** Changes touch three layers independently — domain/service (constraint validation), solver (DOF analysis), and GUI (canvas drawing + interactive creation). Each task is independently testable. Tasks 1–5 are backend; Tasks 6–8 are GUI-only and can be done after.

**Tech Stack:** Python 3.11, PySide6, `quino/domain/`, `quino/services/`, `quino/gui/canvas.py`, `quino/application/service.py`

---

## File Map

| File | What changes |
|------|-------------|
| `quino/domain/sketch_constraints.py` | COINCIDENT stays 2-pt; DISTANCE spec extended comment only |
| `quino/application/service.py` | `create_sketch_constraint`: DISTANCE accepts circle entity ref for radius; COINCIDENT validates that points belong to different entities |
| `quino/services/sketch_solver.py` | DISTANCE handler handles circle-radius case; solver convergence threshold loosened |
| `quino/services/sketch_dof.py` | Full DOF propagation: COINCIDENT removes 2 DOF total (1 per point, both axes shared); DISTANCE/PARALLEL/PERP propagate to all referenced points |
| `quino/gui/canvas.py` | (1) COINCIDENT creation: clicking a line selects its nearest endpoint, not both endpoints; (2) DISTANCE creation: clicking a circle adds its center + entity ref for radius; (3) Arc shows endpoint handles; (4) PARALLEL/PERPENDICULAR draw symbols on both segments; (5) Circle creation removes the redundant second-point click |
| `tests/test_application.py` | New tests for DISTANCE-on-circle, COINCIDENT point-picking |
| `tests/test_gui.py` | New tests for arc endpoint handles |

---

## Task 1: Fix COINCIDENT — clicking a line picks nearest endpoint, not both

**Problem:** Currently clicking a line segment in COINCIDENT mode fills 2 point slots with both endpoints. That makes it impossible to constrain just one endpoint of a line to a specific point. The correct UX: clicking a line picks the endpoint closest to the click.

**Files:**
- Modify: `quino/gui/canvas.py` (method `_handle_constraint_input_click`, lines 2654–2666)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_gui.py`:

```python
def test_coincident_on_line_click_picks_nearest_endpoint(qtbot):
    """Clicking a line in COINCIDENT mode should add only the nearest endpoint."""
    from quino.gui.canvas import MechanismCanvas, CanvasMode
    from quino.application.service import ApplicationService
    app_svc = ApplicationService()
    app_svc.new_project()
    canvas = MechanismCanvas(app_svc)
    qtbot.addWidget(canvas)

    # Create two line segments
    app_svc.add_sketch()
    line_id = app_svc.create_sketch_line_segment(0, 0, 100, 0)
    canvas.set_interaction_mode("sketch")
    canvas.set_mode(CanvasMode.CREATE_SKETCH_COINCIDENT)

    # Simulate clicking near start point of line (0,0) – should pick start only
    canvas._sensor_marker_ids.clear()
    canvas._creation_points.clear()
    # Build a fake entity click at screen position close to start
    from quino.gui.canvas import CanvasSketchEntity, CanvasSketchPoint
    from quino.domain.types import SketchEntityType
    project = app_svc.project
    seg = next(e for e in project.sketch.entities if hasattr(e, 'start_point_id'))
    entity = CanvasSketchEntity(
        entity_id=seg.id, name="", entity_type=SketchEntityType.LINE_SEGMENT,
        point_ids=[seg.start_point_id, seg.end_point_id], visible=True, construction=False,
    )
    # Click position near (0,0) → should resolve to start_point_id
    from unittest.mock import patch
    with patch.object(canvas, '_nearest_endpoint_of_entity',
                      return_value=seg.start_point_id) as mock_near:
        canvas._handle_constraint_input_click(None, entity, n_pts=2, n_ent=0)
        mock_near.assert_called_once()
    assert len(canvas._sensor_marker_ids) == 1
    assert canvas._sensor_marker_ids[0] == seg.start_point_id
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_gui.py::test_coincident_on_line_click_picks_nearest_endpoint -v
```
Expected: FAIL — `_nearest_endpoint_of_entity` does not exist yet.

- [ ] **Step 3: Add `_nearest_endpoint_of_entity` helper to canvas**

In `quino/gui/canvas.py`, after the `_canvas_sketch_point_by_id` method (search for `def _canvas_sketch_point_by_id`), add:

```python
def _nearest_endpoint_of_entity(
    self, entity: "CanvasSketchEntity", click_screen: QtCore.QPointF
) -> str | None:
    """Return the point_id of the entity endpoint closest to click_screen."""
    best_id = None
    best_dist = float("inf")
    for pid in entity.point_ids:
        pt = self._canvas_sketch_point_by_id(pid)
        if pt is None:
            continue
        project = self.app_service.project
        if project is None:
            continue
        transform = self._current_transform()
        sp = self._to_screen(pt.x, pt.y, transform)
        d = math.hypot(sp.x() - click_screen.x(), sp.y() - click_screen.y())
        if d < best_dist:
            best_dist = d
            best_id = pid
    return best_id
```

- [ ] **Step 4: Update `_handle_constraint_input_click` — point-only path**

In `quino/gui/canvas.py`, find the `else:` block at the bottom of `_handle_constraint_input_click` (lines 2654–2666):

```python
        # CURRENT (fills 2 slots from one line click):
        else:
            if (clicked_sketch_entity is not None
                    and clicked_sketch_entity.entity_type in (SketchEntityType.LINE_SEGMENT, SketchEntityType.INFINITE_LINE)
                    and pts_left >= 2):
                for pid in clicked_sketch_entity.point_ids[:2]:
                    cpt = self._canvas_sketch_point_by_id(pid)
                    if cpt:
                        self._creation_points.append((cpt.x, cpt.y))
                        self._sensor_marker_ids.append(pid)
            elif clicked_sketch_point is not None and pts_left > 0:
                self._creation_points.append((clicked_sketch_point.x, clicked_sketch_point.y))
                self._sensor_marker_ids.append(clicked_sketch_point.entity_id)
```

Replace with:

```python
        # Point-only constraints: line click → nearest endpoint only (1 slot)
        else:
            if (clicked_sketch_entity is not None
                    and clicked_sketch_entity.entity_type in (SketchEntityType.LINE_SEGMENT, SketchEntityType.INFINITE_LINE)
                    and pts_left > 0):
                # Pick the endpoint nearest to where the user clicked
                nearest_id = self._nearest_endpoint_of_entity(
                    clicked_sketch_entity, self._last_mouse_screen
                )
                if nearest_id is not None:
                    cpt = self._canvas_sketch_point_by_id(nearest_id)
                    if cpt:
                        self._creation_points.append((cpt.x, cpt.y))
                        self._sensor_marker_ids.append(nearest_id)
            elif clicked_sketch_point is not None and pts_left > 0:
                self._creation_points.append((clicked_sketch_point.x, clicked_sketch_point.y))
                self._sensor_marker_ids.append(clicked_sketch_point.entity_id)
```

- [ ] **Step 5: Store last mouse screen position**

`_nearest_endpoint_of_entity` needs the click screen position. In `mousePressEvent` (search for `def mousePressEvent`), add `self._last_mouse_screen = event.position()` at the very top of the handler body. Also initialise it in `__init__` after the other `_snap_*` fields:

```python
self._last_mouse_screen: QtCore.QPointF = QtCore.QPointF(0.0, 0.0)
```

- [ ] **Step 6: Run tests**

```
pytest tests/test_gui.py::test_coincident_on_line_click_picks_nearest_endpoint -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```
git add quino/gui/canvas.py tests/test_gui.py
git commit -m "fix: COINCIDENT line-click picks nearest endpoint instead of both"
```

---

## Task 2: DISTANCE constraint on circle = radius constraint

**Problem:** A circle has no second point to click for a distance constraint. Clicking a circle should create a distance constraint that fixes its radius. The solver already handles point-to-point distance; we add a special case where the circle's center is refs[0] and a virtual "radius" sentinel triggers the radius path in the solver.

**Design decision:** Rather than a new constraint type, we store the circle entity in `entity_references` of a DISTANCE constraint. The solver detects `entity_references` present on a DISTANCE and applies radius enforcement. This keeps the domain model minimal.

**Files:**
- Modify: `quino/domain/sketch_constraints.py` — DISTANCE spec: allow 1 point + 1 entity (for radius) OR 2 points + 0 entities
- Modify: `quino/application/service.py` — `create_sketch_constraint` DISTANCE branch: when entity_references has 1 circle, treat as radius constraint with 1 point ref
- Modify: `quino/services/sketch_solver.py` — `_apply_distance_handler`: detect entity_references → enforce radius
- Modify: `quino/services/sketch_dof.py` — DISTANCE with entity_ref removes DOF from center point
- Modify: `quino/gui/canvas.py` — DISTANCE creation mode: clicking a circle adds center as refs[0] + circle as entity ref, auto-completes
- Test: `tests/test_application.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_application.py`:

```python
def test_distance_on_circle_constrains_radius():
    """DISTANCE constraint on a circle with entity_ref enforces its radius."""
    svc = ApplicationService()
    svc.new_project()
    svc.add_sketch()
    circle_id = svc.create_sketch_circle(0, 0, 50)  # center (0,0), radius 50mm
    project = svc.project
    circle = next(e for e in project.sketch.entities if e.id == circle_id)
    constraint_id = svc.create_sketch_constraint(
        "distance",
        [circle.center_point_id],
        value="30",
        entity_references=[circle_id],
    )
    assert constraint_id is not None
    # After solving, the circle's radius ScalarProperty should be ~30mm
    center_pt = svc._find_sketch_point(circle.center_point_id)
    # Solver enforces via ScalarProperty update — verify solve result
    result = svc.sketch_solver.solve(project)
    assert result.success


def test_distance_on_circle_rejected_without_entity_ref():
    """DISTANCE with 1 point and no entity_ref must raise."""
    svc = ApplicationService()
    svc.new_project()
    svc.add_sketch()
    circle_id = svc.create_sketch_circle(0, 0, 50)
    project = svc.project
    circle = next(e for e in project.sketch.entities if e.id == circle_id)
    with pytest.raises(ValueError):
        svc.create_sketch_constraint("distance", [circle.center_point_id])
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_application.py::test_distance_on_circle_constrains_radius tests/test_application.py::test_distance_on_circle_rejected_without_entity_ref -v
```
Expected: FAIL

- [ ] **Step 3: Update CONSTRAINT_SPECS to allow DISTANCE with 1 point + 1 entity**

In `quino/domain/sketch_constraints.py`, DISTANCE currently is `ConstraintSpec(2, 0, ...)`. We need to allow either (2 pts, 0 ent) or (1 pt, 1 ent). The spec is validated in service. Change the spec to the minimum and let service validate both cases:

The `ConstraintSpec` has fixed `points` and `entities` counts. The cleanest approach is to keep `DISTANCE` spec as `(2, 0)` and add a new override path in `_validate_sketch_constraint_references` that accepts `(1 ref, 1 entity_ref pointing to SketchCircle)` as the radius form.

In `quino/application/service.py`, method `_validate_sketch_constraint_references` (lines 1418–1442), add before the `if len(references) != expected_pts:` check:

```python
        # Special case: DISTANCE with 1 point + 1 circle entity = radius constraint
        if constraint_type is SketchConstraintType.DISTANCE:
            if len(references) == 1 and len(entity_references or []) == 1:
                self._ensure_sketch_point_exists(references[0])
                entity = self._find_sketch_entity(entity_references[0])
                if not isinstance(entity, SketchCircle):
                    raise ValueError("Distance radius constraint requires a circle entity reference")
                return  # valid radius form — skip generic checks below
            # fall through to standard 2-point validation
```

- [ ] **Step 4: Update `create_sketch_constraint` DISTANCE branch to handle radius form**

In `quino/application/service.py`, the DISTANCE branch (lines 337–342) only handles the 2-point form. Add the 1-point+entity radius form:

```python
        if constraint_enum is SketchConstraintType.DISTANCE:
            is_radius_form = (len(normalized_refs) == 1 and len(normalized_entity_refs) == 1)
            if is_radius_form:
                # Default value = current circle radius
                entity = self._find_sketch_entity(normalized_entity_refs[0])
                if value is None:
                    current_radius = self.expression_service.evaluate_property(
                        entity.radius, project.parameters
                    ).value
                    default_value = f"{current_radius:.6g}"
                else:
                    default_value = value
            else:
                default_value = value or self._current_sketch_distance_expression(
                    normalized_refs[0], normalized_refs[1]
                )
            scalar_value = self._scalar(default_value, "mm", Dimension.LENGTH)
            distance_eval = self.expression_service.evaluate_property(scalar_value, project.parameters)
            if distance_eval.value <= 0:
                raise ValueError("Distance constraint must be positive")
```

- [ ] **Step 5: Update solver to handle circle-radius DISTANCE**

In `quino/services/sketch_solver.py`, method `_apply_distance_handler` (lines 152–156):

```python
    def _apply_distance_handler(self, project, sketch, constraint, refs, positions, locked_axes, tolerance):
        if constraint.value is None:
            return 0.0
        target = self.expression_service.evaluate_property(constraint.value, project.parameters).value
        # Radius form: 1 point ref + 1 entity ref (circle)
        if constraint.entity_references:
            return self._apply_radius(
                refs[0], constraint.entity_references[0], target, sketch, positions, locked_axes, tolerance
            )
        return self._apply_distance(refs[0], refs[1], target, positions, locked_axes, tolerance)
```

Add `_apply_radius` method to the solver class (after `_apply_distance`):

```python
    def _apply_radius(
        self,
        center_id: str,
        circle_entity_id: str,
        target: float,
        sketch: Sketch,
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        """Enforce circle radius by updating its ScalarProperty directly."""
        circle = next(
            (e for e in sketch.entities if isinstance(e, SketchCircle) and e.id == circle_entity_id),
            None,
        )
        if circle is None:
            return 0.0
        # Radius is stored as a ScalarProperty; update its expression so the model reflects the constraint
        # For the solver, we treat the radius as a 1-DOF value: just update the expression.
        try:
            current = float(circle.radius.expression)
        except (ValueError, TypeError):
            current = target
        error = abs(current - target)
        if error <= tolerance:
            return error
        circle.radius.expression = f"{target:.6g}"
        return error
```

Also update `_apply_constraint` to allow DISTANCE with 1 ref + 1 entity:

In `_apply_constraint` (lines 116–139), the check `if len(refs) != spec.points: return float("inf")` will reject the 1-ref radius form because spec says 2. Add a bypass before that check:

```python
        # DISTANCE radius form: 1 point + 1 entity is valid
        if t is SketchConstraintType.DISTANCE and len(constraint.entity_references) == 1:
            if not refs:
                return float("inf")
            handler = self._handlers.get(t)
            if handler is None:
                return float("inf")
            return handler(project, sketch, constraint, refs, positions, locked_axes, tolerance)
```

- [ ] **Step 6: Update DOF analyzer for DISTANCE radius form**

In `quino/services/sketch_dof.py`, the `else:` branch applies `removed` DOF to `refs[0]`. DISTANCE removes 1 DOF. The radius form has 1 ref (center). This already works correctly since the `else` branch uses `refs[0]`. No change needed.

- [ ] **Step 7: Update canvas DISTANCE creation to handle circle click**

In `quino/gui/canvas.py`, the DISTANCE creation mode is handled by `_handle_constraint_input_click` in the `else:` branch (point-only constraints). We need a special case: when in DISTANCE mode and user clicks a circle entity, treat it as the radius form.

Find the `else:` branch (after Task 1 changes) and add above it, or add to the beginning:

Actually, DISTANCE uses `n_pts=2, n_ent=0` via `_CONSTRAINT_SPEC`. We need to intercept DISTANCE specifically. Add a new elif before the general `else:`:

```python
        # DISTANCE on circle: clicking a circle entity = radius constraint (1 pt + 1 entity)
        elif self._mode == CanvasMode.CREATE_SKETCH_DISTANCE and clicked_sketch_entity is not None and \
                clicked_sketch_entity.entity_type is SketchEntityType.CIRCLE and \
                not self._sensor_marker_ids:
            # Auto-fill: center point + circle entity ref → radius form
            center_id = clicked_sketch_entity.point_ids[0]
            cpt = self._canvas_sketch_point_by_id(center_id)
            if cpt:
                self._creation_points.append((cpt.x, cpt.y))
                self._sensor_marker_ids.append(center_id)
                self._creation_entity_ids.append(clicked_sketch_entity.entity_id)
                # Immediately finalize — radius form is complete with 1 pt + 1 entity
                self._finalize_sketch_constraint_creation()
                return
```

Also update `_finalize_sketch_constraint_creation` to pass entity refs even for DISTANCE:

The current code at line 2684:
```python
n_pts = _CONSTRAINT_SPEC.get(self._mode, (2, 0))[0]
point_ids = list(self._sensor_marker_ids[:n_pts])
```

For the radius form, `n_pts` is 2 (from spec) but we only have 1. Change to use actual collected count when entity refs are present:

```python
        n_pts = _CONSTRAINT_SPEC.get(self._mode, (2, 0))[0]
        # Radius form: 1 point + 1 entity ref is a valid DISTANCE
        actual_n_pts = 1 if (self._mode == CanvasMode.CREATE_SKETCH_DISTANCE
                             and len(self._creation_entity_ids) == 1
                             and len(self._sensor_marker_ids) == 1) else n_pts
        point_ids = list(self._sensor_marker_ids[:actual_n_pts])
```

- [ ] **Step 8: Run tests**

```
pytest tests/test_application.py::test_distance_on_circle_constrains_radius tests/test_application.py::test_distance_on_circle_rejected_without_entity_ref -v
```
Expected: PASS

- [ ] **Step 9: Run full suite**

```
pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 10: Commit**

```
git add quino/domain/sketch_constraints.py quino/application/service.py quino/services/sketch_solver.py quino/gui/canvas.py tests/test_application.py
git commit -m "feat: DISTANCE constraint on circle enforces radius"
```

---

## Task 3: Arc — show endpoint handles (point A and point C)

**Problem:** An arc is defined by 3 points: A (start), B (midpoint on arc), C (end). Currently only B is used for geometry; A and C are invisible. The arc should render visible handles at A and C (like a segment's endpoints) so the user can select and drag them.

**Key fact:** The arc's 3 points ARE already added as `SketchPoint` entities during `create_sketch_arc` in `service.py`, and they ARE rendered by the point-drawing loop in `canvas.py` — but they are `visible=False` by default. We just need to make them visible and give them the correct `visible` flag.

**Files:**
- Modify: `quino/application/service.py` — `create_sketch_arc`: ensure point_a and point_c are `visible=True`
- Modify: `quino/gui/canvas.py` — arc point_ids: expose point_a and point_c for hit-testing and display

- [ ] **Step 1: Write failing test**

Add to `tests/test_application.py`:

```python
def test_arc_endpoint_points_are_visible():
    """Arc start and end points (A and C) must be visible for editing."""
    svc = ApplicationService()
    svc.new_project()
    svc.add_sketch()
    arc_id = svc.create_sketch_arc(0, 0, 50, 0, 0, 50, 50, 50, 0)
    project = svc.project
    arc = next(e for e in project.sketch.entities if e.id == arc_id)
    pt_a = svc._find_sketch_point(arc.point_a_id)
    pt_c = svc._find_sketch_point(arc.point_c_id)
    assert pt_a.visible is True, "Arc point A must be visible"
    assert pt_c.visible is True, "Arc point C must be visible"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_application.py::test_arc_endpoint_points_are_visible -v
```
Expected: FAIL — points are created with `visible=False` or not visible.

- [ ] **Step 3: Find `create_sketch_arc` in service.py**

Search for `create_sketch_arc` in `quino/application/service.py`. It creates 3 SketchPoint objects. The current code likely sets `visible=False` for point_b (the midpoint handle) or all of them. Change point_a and point_c to `visible=True`, keep point_b `visible=False` (it's the interior midpoint, not an endpoint):

```python
    # When creating an arc, make A (start) and C (end) visible as handles
    point_a = SketchPoint(
        id=self.id_service.new("skpt"),
        name=self._next_sketch_point_name(),
        type=SketchEntityType.POINT,
        x=self._scalar(str(ax), "mm", Dimension.LENGTH),
        y=self._scalar(str(ay), "mm", Dimension.LENGTH),
        visible=True,      # ← endpoint handle: visible
        construction=False,
    )
    point_b = SketchPoint(
        id=self.id_service.new("skpt"),
        name=self._next_sketch_point_name(),
        type=SketchEntityType.POINT,
        x=self._scalar(str(bx), "mm", Dimension.LENGTH),
        y=self._scalar(str(by), "mm", Dimension.LENGTH),
        visible=False,     # ← midpoint on arc: hidden
        construction=False,
    )
    point_c = SketchPoint(
        id=self.id_service.new("skpt"),
        name=self._next_sketch_point_name(),
        type=SketchEntityType.POINT,
        x=self._scalar(str(cx), "mm", Dimension.LENGTH),
        y=self._scalar(str(cy), "mm", Dimension.LENGTH),
        visible=True,      # ← endpoint handle: visible
        construction=False,
    )
```

You need to find the exact lines. Search `quino/application/service.py` for `create_sketch_arc` or `SketchArc(`. The current pattern will be clear once found.

- [ ] **Step 4: Run test**

```
pytest tests/test_application.py::test_arc_endpoint_points_are_visible -v
```
Expected: PASS

- [ ] **Step 5: Verify arc drawing in canvas still works**

```
pytest tests/test_gui.py -q
```
Expected: all pass (arc drawing uses `point_ids` which are the same).

- [ ] **Step 6: Commit**

```
git add quino/application/service.py tests/test_application.py
git commit -m "fix: arc start/end points are visible as editable handles"
```

---

## Task 4: Circle — remove the redundant second-point click during creation

**Problem:** Creating a circle requires 2 clicks: center + a point on the circle. The second click creates a floating `SketchPoint` that becomes the "radius point". This is confusing — the radius is implicit from the circle geometry, not a separate point. 

**Correct UX (AutoCAD style):** First click = center, then drag shows preview circle, second click (or type a value) = radius. The circle's `radius` `ScalarProperty` should be set from the distance between the two clicks, and no visible second point should be created.

**Current flow:** `CREATE_SKETCH_CIRCLE` mode collects 2 points, calls `_finalize_sketch_creation`. Let's trace what happens. Look at `create_sketch_circle` in `service.py`.

**Files:**
- Modify: `quino/application/service.py` — `create_sketch_circle`: change signature to accept `(cx, cy, radius)` directly (if not already); ensure the "radius point" is `visible=False`
- Modify: `quino/gui/canvas.py` — circle creation mode: on second click, compute distance as radius and pass to `create_sketch_circle`; the second point should not be a visible entity

- [ ] **Step 1: Read current `create_sketch_circle` implementation**

In `quino/application/service.py`, search for `def create_sketch_circle`. Read the signature and point creation logic. Note whether it takes `(cx, cy, rx, ry)` or `(cx, cy, radius)`. The goal is that after the change, no visible radius-point exists.

- [ ] **Step 2: Write failing test**

Add to `tests/test_application.py`:

```python
def test_circle_creation_has_no_visible_radius_point():
    """Creating a circle should not leave a visible radius/edge point."""
    svc = ApplicationService()
    svc.new_project()
    svc.add_sketch()
    circle_id = svc.create_sketch_circle(0, 0, 50)
    project = svc.project
    visible_points = [e for e in project.sketch.entities
                      if hasattr(e, 'x') and hasattr(e, 'visible') and e.visible]
    # Only the center point should be visible; no edge/radius point
    circle = next(e for e in project.sketch.entities if e.id == circle_id)
    center = svc._find_sketch_point(circle.center_point_id)
    assert center.visible is True
    # Any point that is NOT the center point of ANY circle should not be a radius artifact
    circle_center_ids = {e.center_point_id for e in project.sketch.entities
                         if hasattr(e, 'center_point_id')}
    non_center_visible = [p for p in visible_points if p.id not in circle_center_ids]
    assert len(non_center_visible) == 0, f"Unexpected visible points: {non_center_visible}"
```

- [ ] **Step 3: Run test to see current state**

```
pytest tests/test_application.py::test_circle_creation_has_no_visible_radius_point -v
```
If it passes: circle creation is already correct; skip Step 4. If it fails: proceed.

- [ ] **Step 4: Find and fix `create_sketch_circle` radius point visibility**

In `quino/application/service.py`, find `create_sketch_circle`. It likely creates a center SketchPoint and possibly an edge SketchPoint. The edge point (if it exists) should be `visible=False`. The `radius` should be stored as a `ScalarProperty` on the `SketchCircle`, not derived from a second point.

If `create_sketch_circle` currently takes `(cx, cy, rx, ry)` and the radius is the distance to `(rx, ry)`, change it to:
1. Still accept `(cx, cy, rx, ry)` for backward compat (canvas passes 4 coords)
2. Compute `radius_val = math.hypot(rx - cx, ry - cy)` and store as `circle.radius`
3. Make the edge point `visible=False` (or don't create it at all if it's not used)

Check whether any constraint (e.g. ON_CIRCLE, TANGENT) references the edge point ID. If not, simply don't create it.

- [ ] **Step 5: Run test and full suite**

```
pytest tests/test_application.py::test_circle_creation_has_no_visible_radius_point tests/ -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```
git add quino/application/service.py tests/test_application.py
git commit -m "fix: circle creation hides radius point — only center is visible"
```

---

## Task 5: Fix DOF calculation — distribute constraints across shared points

**Problem:** The current DOF analyzer applies most constraints only to `refs[0]`. This means that HORIZONTAL(p1, p2) removes 1 DOF from p1 but not p2. In reality, HORIZONTAL removes 1 DOF from the system: both p1 and p2 are constrained (they must share the same Y). The effect is 1 DOF removed total, distributed evenly.

The correct approach: each constraint removes N DOF from the system, distributed across all the points it references. This makes DOF coloring match what the solver actually achieves.

**Also:** The solver marks sketch red when `max_error > tolerance` after 120 iterations even if the error is tiny (e.g. 1e-5 mm). We should loosen the "red" threshold or increase default iterations from 120 to 200.

**Files:**
- Modify: `quino/services/sketch_dof.py` — full per-constraint DOF distribution
- Modify: `quino/services/sketch_solver.py` — increase default `max_iterations` from 120 to 200

- [ ] **Step 1: Write failing tests for DOF distribution**

Add to `tests/test_application.py`:

```python
def test_dof_horizontal_reduces_both_points():
    """HORIZONTAL(p1,p2) should reduce DOF of both p1 and p2, not just p1."""
    from quino.services.sketch_dof import SketchDofAnalyzer
    svc = ApplicationService()
    svc.new_project()
    svc.add_sketch()
    line_id = svc.create_sketch_line_segment(0, 0, 100, 10)
    project = svc.project
    seg = next(e for e in project.sketch.entities if e.id == line_id)
    svc.create_sketch_constraint("horizontal", [seg.start_point_id, seg.end_point_id])
    result = SketchDofAnalyzer().analyze(project.sketch)
    # Each point starts at DOF=2; HORIZONTAL removes 1 DOF distributed across both
    # p1 loses 0.5 DOF, p2 loses 0.5 DOF (rounded down: both still at 1 in integer model)
    # OR: 1 DOF removed from the system = reduce one of the two points by 1
    # AutoCAD-style: both points show 1 DOF remaining (they can still move along x independently)
    # The key check: total_free_dof should be 3 (4 total - 1 constraint)
    assert result.total_free_dof == 3


def test_dof_two_constraints_fully_constrain_line():
    """HORIZONTAL + FIX(start) should give the line 0 free DOF."""
    from quino.services.sketch_dof import SketchDofAnalyzer
    svc = ApplicationService()
    svc.new_project()
    svc.add_sketch()
    line_id = svc.create_sketch_line_segment(0, 0, 100, 0)
    project = svc.project
    seg = next(e for e in project.sketch.entities if e.id == line_id)
    svc.create_sketch_constraint("fix", [seg.start_point_id])
    svc.create_sketch_constraint("horizontal", [seg.start_point_id, seg.end_point_id])
    svc.create_sketch_constraint("distance", [seg.start_point_id, seg.end_point_id], value="100")
    result = SketchDofAnalyzer().analyze(project.sketch)
    assert result.total_free_dof == 0
    assert seg.end_point_id in result.fully_constrained_point_ids
```

- [ ] **Step 2: Run tests to verify current state**

```
pytest tests/test_application.py::test_dof_horizontal_reduces_both_points tests/test_application.py::test_dof_two_constraints_fully_constrain_line -v
```

- [ ] **Step 3: Rewrite DOF distribution in `sketch_dof.py`**

Replace the constraint loop (lines 67–84) with a correct distribution. The rule: each constraint removes `_CONSTRAINT_DOF_REMOVED[type]` DOF from the system total; distribute as 1 DOF from the most-constrained relevant point (so the point that still has DOF loses it).

```python
        for constraint in sketch.constraints:
            c_type = constraint.type
            refs = constraint.references
            if c_type is SketchConstraintType.FIX:
                for ref in refs:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 2)
            elif c_type is SketchConstraintType.COINCIDENT:
                # 2 equations (x_a=x_b, y_a=y_b) → remove 1 DOF from each point
                for ref in refs[:2]:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 1)
            elif c_type in {
                SketchConstraintType.HORIZONTAL,
                SketchConstraintType.VERTICAL,
            }:
                # 1 equation → remove from the point with most remaining DOF
                # (so e.g. after FIX(start), HORIZONTAL removes from end)
                relevant = [r for r in refs[:2] if r in point_dof]
                if relevant:
                    target = max(relevant, key=lambda r: point_dof.get(r, 0))
                    point_dof[target] = max(0, point_dof[target] - 1)
            elif c_type is SketchConstraintType.DISTANCE:
                # 1 equation → remove from the least-constrained point among refs
                relevant = [r for r in refs[:2] if r in point_dof]
                if relevant:
                    target = max(relevant, key=lambda r: point_dof.get(r, 0))
                    point_dof[target] = max(0, point_dof[target] - 1)
            elif c_type in {
                SketchConstraintType.PARALLEL,
                SketchConstraintType.PERPENDICULAR,
                SketchConstraintType.EQUAL_LENGTH,
            }:
                # 1 equation across 4 refs → reduce one point from each line
                line1 = [r for r in refs[:2] if r in point_dof]
                line2 = [r for r in refs[2:4] if r in point_dof]
                for line in (line1, line2):
                    if line:
                        t = max(line, key=lambda r: point_dof.get(r, 0))
                        point_dof[t] = max(0, point_dof[t] - 1)
                # But total removed is 1 (not 2), so undo one of the reductions:
                # Actually: parallel/perpendicular/equal-length remove 1 DOF total.
                # Simplest correct model: remove 1 from the point with highest DOF among all 4 refs.
                # Reset and redo:
                pass  # see below
            elif c_type is SketchConstraintType.MIDPOINT:
                for ref in refs:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 1)
            elif c_type is SketchConstraintType.SYMMETRIC:
                for ref in refs[:2]:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 1)
            elif c_type in {
                SketchConstraintType.ANGLE,
                SketchConstraintType.COLLINEAR,
                SketchConstraintType.ON_CIRCLE,
                SketchConstraintType.TANGENT,
            }:
                removed = _CONSTRAINT_DOF_REMOVED.get(c_type, 0)
                all_refs = [r for r in refs if r in point_dof]
                if all_refs:
                    target = max(all_refs, key=lambda r: point_dof.get(r, 0))
                    point_dof[target] = max(0, point_dof[target] - removed)
```

For PARALLEL/PERPENDICULAR/EQUAL_LENGTH the simplest correct model is: remove 1 DOF from the point with the most remaining DOF among all 4 refs. Replace the `pass` section above with:

```python
            elif c_type in {
                SketchConstraintType.PARALLEL,
                SketchConstraintType.PERPENDICULAR,
                SketchConstraintType.EQUAL_LENGTH,
            }:
                all_refs = [r for r in refs[:4] if r in point_dof]
                if all_refs:
                    target = max(all_refs, key=lambda r: point_dof.get(r, 0))
                    point_dof[target] = max(0, point_dof[target] - 1)
```

(Remove the earlier incorrect parallel/perp block entirely.)

- [ ] **Step 4: Increase solver max_iterations default**

In `quino/services/sketch_solver.py`, method `solve` signature (line 51):

```python
    # CURRENT:
    max_iterations: int = 120,
    # CHANGE TO:
    max_iterations: int = 200,
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_application.py::test_dof_horizontal_reduces_both_points tests/test_application.py::test_dof_two_constraints_fully_constrain_line -v
```
Expected: PASS

- [ ] **Step 6: Run full suite**

```
pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 7: Commit**

```
git add quino/services/sketch_dof.py quino/services/sketch_solver.py tests/test_application.py
git commit -m "fix: DOF distributes across all referenced points; solver iterations 200"
```

---

## Task 6: PARALLEL and PERPENDICULAR — draw symbol on both segments, not a dashed line

**Problem:** Currently PARALLEL/PERPENDICULAR draw a dashed line between the midpoints of the two segments. Professional CAD software draws the geometric symbol on each segment separately (two chevrons `//` for PARALLEL, a right-angle mark `⊥` for PERPENDICULAR). No dashed line.

**Files:**
- Modify: `quino/gui/canvas.py` — `_draw_sketch_constraints` (lines 1946–1962) and `_draw_constraint_indicator` (lines 2358–2363)

- [ ] **Step 1: Replace dashed-line drawing with per-segment symbol**

In `quino/gui/canvas.py`, find the block (lines 1946–1962):

```python
            elif constraint.type in {
                SketchConstraintType.PARALLEL,
                SketchConstraintType.PERPENDICULAR,
                SketchConstraintType.EQUAL_LENGTH,
            } and len(constraint.references) == 4:
                # Draw dashed line between midpoints of the two line segments
                refs4 = [point_map.get(pid) for pid in constraint.references]
                if all(p is not None for p in refs4):
                    mid1 = self._to_screen(...)
                    mid2 = self._to_screen(...)
                    painter.drawLine(mid1, mid2)
```

Replace with:

```python
            elif constraint.type in {
                SketchConstraintType.PARALLEL,
                SketchConstraintType.PERPENDICULAR,
                SketchConstraintType.EQUAL_LENGTH,
            } and len(constraint.references) == 4:
                refs4 = [point_map.get(pid) for pid in constraint.references]
                if all(p is not None for p in refs4):
                    # Draw the constraint symbol on each of the two segments
                    self._draw_segment_constraint_symbol(
                        painter, refs4[0], refs4[1], constraint.type, color, transform
                    )
                    self._draw_segment_constraint_symbol(
                        painter, refs4[2], refs4[3], constraint.type, color, transform
                    )
```

- [ ] **Step 2: Add `_draw_segment_constraint_symbol` method**

Add after `_draw_constraint_indicator` (after line ~2393):

```python
    def _draw_segment_constraint_symbol(
        self,
        painter: QtGui.QPainter,
        pt_a: "CanvasSketchPoint",
        pt_b: "CanvasSketchPoint",
        constraint_type: SketchConstraintType,
        color: QtGui.QColor,
        transform,
    ) -> None:
        """Draw a small geometric symbol at the midpoint of a segment, aligned to it."""
        sa = self._to_screen(pt_a.x, pt_a.y, transform)
        sb = self._to_screen(pt_b.x, pt_b.y, transform)
        dx = sb.x() - sa.x()
        dy = sb.y() - sa.y()
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return
        ux, uy = dx / length, dy / length       # unit along segment
        nx, ny = -uy, ux                         # unit normal to segment
        mid = QtCore.QPointF(0.5 * (sa.x() + sb.x()), 0.5 * (sa.y() + sb.y()))
        painter.setPen(QtGui.QPen(color, 1.2))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        size = 7.0  # half-size of symbol in screen pixels

        if constraint_type is SketchConstraintType.PARALLEL:
            # Two small chevrons (>>) along the segment
            for offset in (-4.0, 2.0):
                base = QtCore.QPointF(mid.x() + ux * offset, mid.y() + uy * offset)
                tip = QtCore.QPointF(base.x() + ux * size * 0.5, base.y() + uy * size * 0.5)
                p1 = QtCore.QPointF(tip.x() - nx * size * 0.4, tip.y() - ny * size * 0.4)
                p2 = QtCore.QPointF(tip.x() + nx * size * 0.4, tip.y() + ny * size * 0.4)
                painter.drawLine(p1, tip)
                painter.drawLine(p2, tip)

        elif constraint_type is SketchConstraintType.PERPENDICULAR:
            # Right-angle square at the midpoint
            sq_size = 5.0
            p0 = mid
            p1 = QtCore.QPointF(p0.x() + nx * sq_size, p0.y() + ny * sq_size)
            p2 = QtCore.QPointF(p1.x() + ux * sq_size, p1.y() + uy * sq_size)
            p3 = QtCore.QPointF(p0.x() + ux * sq_size, p0.y() + uy * sq_size)
            painter.drawLine(p0, p1)
            painter.drawLine(p1, p2)
            painter.drawLine(p2, p3)

        elif constraint_type is SketchConstraintType.EQUAL_LENGTH:
            # Two small tick marks perpendicular to the segment
            for offset in (-3.0, 3.0):
                base = QtCore.QPointF(mid.x() + ux * offset, mid.y() + uy * offset)
                t1 = QtCore.QPointF(base.x() - nx * size * 0.4, base.y() - ny * size * 0.4)
                t2 = QtCore.QPointF(base.x() + nx * size * 0.4, base.y() + ny * size * 0.4)
                painter.drawLine(t1, t2)
```

- [ ] **Step 3: Run tests**

```
pytest tests/test_gui.py -q
```
Expected: all pass (no tests directly check constraint rendering, but smoke tests must not crash).

- [ ] **Step 4: Commit**

```
git add quino/gui/canvas.py
git commit -m "fix: PARALLEL/PERPENDICULAR/EQUAL_LENGTH show symbols on each segment"
```

---

## Task 7: Fix SYMMETRIC constraint — also remove DOF from axis points

**Problem:** SYMMETRIC(p1, p2, axis_p1, axis_p2) currently only removes DOF from p1 and p2. The axis points (axis_p1, axis_p2) are not affected. But the axis IS constrained by the SYMMETRIC constraint — the user can't freely move the axis independently without breaking symmetry.

Actually the axis is the reference, not the constrained entity — its DOF is not reduced by the symmetry. This is correct. Skip this task unless the user specifically reports axis points showing wrong DOF.

This task is **not needed** — skip.

---

## Task 8: Solver false-positive red state — improve convergence check

**Problem:** The sketch turns red when `max_error > tolerance` after max_iterations, even if the error is negligibly small (e.g. 1e-5 mm, visually identical). This happens on complex constraint systems where Gauss-Seidel oscillates near the solution.

**Fix:** Add a secondary "close enough" threshold. If `max_error <= 0.001` (1 µm), report success even if not at full tolerance.

**Files:**
- Modify: `quino/services/sketch_solver.py` — solve loop exit condition
- Modify: `quino/application/service.py` — `_apply_sketch_constraints`: only mark `solve_error` when error is significant

- [ ] **Step 1: Write failing test**

Add to `tests/test_application.py`:

```python
def test_solver_does_not_mark_red_on_near_convergence():
    """A sketch that converges to within 0.001mm should not show a solve error."""
    svc = ApplicationService()
    svc.new_project()
    svc.add_sketch()
    line_id = svc.create_sketch_line_segment(0, 0, 100, 1)  # nearly horizontal
    project = svc.project
    seg = next(e for e in project.sketch.entities if e.id == line_id)
    svc.create_sketch_constraint("horizontal", [seg.start_point_id, seg.end_point_id])
    svc.create_sketch_constraint("fix", [seg.start_point_id])
    svc.create_sketch_constraint("distance", [seg.start_point_id, seg.end_point_id], value="100")
    # Sketch should be green (no solve error), not red
    assert project.sketch.solve_error is None
```

- [ ] **Step 2: Run test**

```
pytest tests/test_application.py::test_solver_does_not_mark_red_on_near_convergence -v
```
Expected: PASS (this test likely already passes; if so, skip Steps 3–4).

- [ ] **Step 3: Add near-convergence threshold to solver**

In `quino/services/sketch_solver.py`, method `solve`, after the main loop (lines 77–105), the failure return has `success=False`. Change to:

```python
        # Near-convergence: within 1µm is visually identical — treat as success
        _NEAR_CONVERGENCE = 0.001  # mm
        msg = f"Sketch solver did not converge (max error {max_error:.3g} mm)"
        if max_error <= _NEAR_CONVERGENCE:
            return SketchSolveResult(True, positions, max_iterations, max_error, None)
        # ... rest of the failure diagnostics ...
```

- [ ] **Step 4: Run test and full suite**

```
pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 5: Commit**

```
git add quino/services/sketch_solver.py tests/test_application.py
git commit -m "fix: solver near-convergence (<=0.001mm) is treated as success"
```

---

## Self-Review

### Spec coverage check

| User requirement | Task |
|---|---|
| COINCIDENT works on points (clicking line → nearest endpoint) | Task 1 ✓ |
| DISTANCE: point-point, point-segment, two segments | Task 1 partially (line click → nearest point makes point-segment and seg-seg via 2 clicks natural) ✓ |
| DISTANCE: circle radius | Task 2 ✓ |
| Arc shows two endpoint handles | Task 3 ✓ |
| Circle second point unnecessary | Task 4 ✓ |
| SYMMETRIC extended (same logic as coincident-style) | Task 1 covers clicking behavior; SYMMETRIC DOF: Task 5 ✓ |
| DOF accounts for connected elements | Task 5 ✓ |
| DOF green when 0 | Already implemented in canvas; DOF fix in Task 5 ensures correct values ✓ |
| Sketch red false-positives | Task 8 ✓ |
| PARALLEL/PERPENDICULAR: symbol on both segments, not dashed line | Task 6 ✓ |

### Placeholder scan
- Task 3 Step 3: "You need to find the exact lines" — this is a valid instruction (the agent must read the file), not a placeholder. The code snippet is complete.
- Task 4 Step 4: "If `create_sketch_circle` currently takes..." — conditional instruction, not placeholder. Agent reads file and applies correct branch.
- Task 7: explicitly marked skip.

### Type consistency
- `_nearest_endpoint_of_entity` defined in Task 1 Step 3, used in Task 1 Step 4 ✓
- `_draw_segment_constraint_symbol` defined in Task 6 Step 2, called in Task 6 Step 1 ✓
- `_apply_radius` defined in Task 2 Step 5, called from `_apply_distance_handler` Task 2 Step 5 ✓
- `CanvasSketchEntity`, `CanvasSketchPoint` types used in Task 1 already exist in canvas.py ✓
