"""Regression tests for SketchCommands extraction.

These exercise the sketch API via ApplicationService (public facade), to ensure
that delegation to the extracted SketchCommands preserves behavior.
"""
from __future__ import annotations

import pytest

from quino.application.service import ApplicationService
from quino.domain.inputs import PropertyValueInput


def _make_app() -> ApplicationService:
    app = ApplicationService()
    app.new_project("SketchTest")
    return app


def test_create_sketch_creates_origin_and_fix_constraint() -> None:
    app = _make_app()
    sketch_id = app.create_sketch()
    assert sketch_id.startswith("sketch_")
    sketch = app.project.sketch
    assert sketch is not None
    # Origin point + tangent helpers/etc: at least 1 point and 1 fix constraint
    assert any(c.type.value == "fix" for c in sketch.constraints.values())


def test_create_sketch_point_and_line_segment_are_persisted() -> None:
    app = _make_app()
    app.create_sketch()
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("50 mm", "0 mm", "B")
    line_id = app.create_sketch_line_segment(p1, p2, "L1")
    sketch = app.project.sketch
    assert p1 in sketch.entities and p2 in sketch.entities
    assert line_id in sketch.entities
    assert sketch.entities[line_id].name == "L1"


def test_distance_constraint_solves_and_updates_point() -> None:
    app = _make_app()
    app.create_sketch()
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("30 mm", "0 mm", "B")
    cid = app.create_sketch_constraint("distance", [p1, p2], value="100 mm")
    sketch = app.project.sketch
    assert cid in sketch.constraints
    # Solver should have moved p2 to satisfy the 100 mm distance.
    point_b = sketch.entities[p2]
    val_x = app._evaluate_sketch_expression(point_b.x, app.project.parameters)
    assert val_x == pytest.approx(100.0, abs=0.1)


def test_solve_sketch_returns_report_without_raising() -> None:
    app = _make_app()
    app.create_sketch()
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("10 mm", "0 mm", "B")
    app.create_sketch_constraint("horizontal", [p1, p2])
    report = app.solve_sketch()
    assert any(m.code == "sketch_solved" for m in report.messages)


def test_delete_sketch_entity_removes_point_and_dependents() -> None:
    app = _make_app()
    app.create_sketch()
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("50 mm", "0 mm", "B")
    line_id = app.create_sketch_line_segment(p1, p2)
    app.delete_sketch_entity(p1)
    sketch = app.project.sketch
    assert p1 not in sketch.entities
    # Line depending on p1 should be cascade-deleted
    assert line_id not in sketch.entities


def test_update_sketch_constraint_value_updates_distance() -> None:
    app = _make_app()
    app.create_sketch()
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("30 mm", "0 mm", "B")
    cid = app.create_sketch_constraint("distance", [p1, p2], value="40 mm")
    app.update_sketch_constraint(cid, "value", PropertyValueInput("expression", "80 mm"))
    constraint = app._find_sketch_constraint(cid)
    assert constraint.value is not None
    assert "80" in constraint.value.expression


def test_set_sketch_visible_toggles_flag_and_snapshots() -> None:
    app = _make_app()
    app.create_sketch()
    assert app.project.sketch.visible is True
    app.set_sketch_visible(False)
    assert app.project.sketch.visible is False
    app.set_sketch_visible(True)
    assert app.project.sketch.visible is True


def test_toggle_sketch_construction_flips_all_targets() -> None:
    app = _make_app()
    app.create_sketch()
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("10 mm", "0 mm", "B")
    line = app.create_sketch_line_segment(p1, p2)
    sketch = app.project.sketch
    assert sketch.entities[line].construction is False
    new_value = app.toggle_sketch_construction([line])
    assert new_value is True
    assert sketch.entities[line].construction is True
