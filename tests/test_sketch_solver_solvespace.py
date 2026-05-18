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
