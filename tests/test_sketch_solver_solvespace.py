"""Tests for SolvespaceBackend.

These tests target the backend directly (not via ApplicationService) for
fast feedback. Constraint emission is not yet implemented; these tests
exercise the empty-sketch and points-only paths.
"""
from quino import ApplicationService
from quino.services.expressions import ExpressionService
from quino.services.sketch_solving.solvespace_backend import SolvespaceBackend
from quino.services.units import UnitService


def _make_backend() -> SolvespaceBackend:
    units = UnitService()
    expressions = ExpressionService(units)
    return SolvespaceBackend(expressions, units)


def test_solve_with_no_sketch_returns_empty_success():
    svc = ApplicationService()
    svc.new_project("T")
    result = _make_backend().solve(svc.project)
    assert result.success is True
    assert result.positions == {}


def test_solve_empty_sketch_returns_success():
    # Note: create_sketch auto-creates a default origin point, so positions
    # will contain that single point (not literally empty).
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    result = _make_backend().solve(svc.project)
    assert result.success is True
    # Default origin point exists at (0, 0).
    assert all(pos == (0.0, 0.0) for pos in result.positions.values())


def test_solve_sketch_with_only_points_returns_their_positions():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("10 mm", "20 mm", "P1")
    p2 = svc.create_sketch_point("30 mm", "40 mm", "P2")
    result = _make_backend().solve(svc.project)
    assert result.success is True
    assert result.positions[p1] == (10.0, 20.0)
    assert result.positions[p2] == (30.0, 40.0)


def test_distance_constraint_pulls_points_to_target_length():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("distance", [p1, p2], "10 mm")
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    x1, y1 = result.positions[p1]
    x2, y2 = result.positions[p2]
    assert abs(x1 - 0.0) < 1e-6
    assert abs(y1 - 0.0) < 1e-6
    dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    assert abs(dist - 10.0) < 1e-4


def test_horizontal_constraint_aligns_line():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "3 mm", "P2")
    svc.create_sketch_line_segment(p1, p2, "L1")
    svc.create_sketch_constraint("fix", [p1])
    # HORIZONTAL takes 2 point refs per domain spec; solvespace backend
    # builds an implicit line from those two point handles.
    svc.create_sketch_constraint("horizontal", [p1, p2])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    _, y2 = result.positions[p2]
    assert abs(y2 - 0.0) < 1e-4


def test_vertical_constraint_aligns_line():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("4 mm", "10 mm", "P2")
    svc.create_sketch_line_segment(p1, p2, "L1")
    svc.create_sketch_constraint("fix", [p1])
    # VERTICAL takes 2 point refs per domain spec; solvespace backend
    # builds an implicit line from those two point handles.
    svc.create_sketch_constraint("vertical", [p1, p2])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    x2, _ = result.positions[p2]
    assert abs(x2 - 0.0) < 1e-4


def test_coincident_points_collapse_to_same_position():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "10 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("coincident", [p1, p2])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    assert abs(result.positions[p2][0] - 0.0) < 1e-4
    assert abs(result.positions[p2][1] - 0.0) < 1e-4
