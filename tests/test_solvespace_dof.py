"""Tests for SolvespaceBackend.analyze_dof() — DOF derived from Solvespace
via per-axis perturbation testing."""
from quino import ApplicationService
from quino.services.expressions import ExpressionService
from quino.services.sketch_solving.solvespace_backend import SolvespaceBackend
from quino.services.units import UnitService


def _make_backend() -> SolvespaceBackend:
    u = UnitService()
    return SolvespaceBackend(ExpressionService(u), u)


def test_empty_sketch_returns_zero_dof():
    # create_sketch auto-creates a fixed origin point, so an "empty" sketch has
    # one fixed point (DOF=0) and zero total free DOF.
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    result = _make_backend().analyze_dof(svc.project)
    assert result.total_free_dof == 0
    assert all(dof == 0 for dof in result.point_dof.values())


def test_unconstrained_point_has_2_dof():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p = svc.create_sketch_point("0 mm", "0 mm", "P")
    result = _make_backend().analyze_dof(svc.project)
    assert result.point_dof[p] == 2
    assert p not in result.fully_constrained_point_ids


def test_fixed_point_has_0_dof():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p = svc.create_sketch_point("0 mm", "0 mm", "P")
    svc.create_sketch_constraint("fix", [p])
    result = _make_backend().analyze_dof(svc.project)
    assert result.point_dof[p] == 0
    assert p in result.fully_constrained_point_ids


def test_distance_constraint_leaves_one_dof():
    """One point fixed, second has only distance constraint → 1 DOF (angle is free)."""
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("distance", [p1, p2], value="10 mm")
    result = _make_backend().analyze_dof(svc.project)
    assert result.point_dof[p1] == 0
    assert result.point_dof[p2] == 1


def test_line_with_both_endpoints_fixed_is_fully_constrained():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    line = svc.create_sketch_line_segment(p1, p2, "L")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    result = _make_backend().analyze_dof(svc.project)
    assert line in result.fully_constrained_entity_ids


def test_total_free_dof_counts_axes():
    """Two unconstrained points = 4 free axes total."""
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    svc.create_sketch_point("0 mm", "0 mm", "P1")
    svc.create_sketch_point("5 mm", "0 mm", "P2")
    result = _make_backend().analyze_dof(svc.project)
    assert result.total_free_dof == 4
