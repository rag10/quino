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


def test_parallel_lines_align_directions():
    # PARALLEL uses 4 point refs: [l1_start, l1_end, l2_start, l2_end]
    # L1 is fixed horizontal (p1=0,0 → p2=10,0).
    # L2 initially at a non-horizontal angle (p3=0,5; p4=10,8).
    # Parallel constraint should make L2 also horizontal → p4.y == p3.y == 5.
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("0 mm", "5 mm", "P3")
    p4 = svc.create_sketch_point("10 mm", "8 mm", "P4")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    svc.create_sketch_constraint("fix", [p3])
    svc.create_sketch_constraint("parallel", [p1, p2, p3, p4])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    # L1 is horizontal; L2 parallel → p4.y must equal p3.y = 5
    assert abs(result.positions[p4][1] - 5.0) < 1e-3


def test_perpendicular_lines():
    # PERPENDICULAR uses 4 point refs: [l1_start, l1_end, l2_start, l2_end]
    # L1 is fixed along x-axis (p1=0,0 → p2=10,0).
    # L2 starts at an angle (p3=0,0; p4=5,5).
    # Perpendicular constraint → L2 must become vertical → p4.x ≈ p3.x = 0.
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("0 mm", "0 mm", "P3")
    p4 = svc.create_sketch_point("5 mm", "5 mm", "P4")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    svc.create_sketch_constraint("fix", [p3])
    svc.create_sketch_constraint("perpendicular", [p1, p2, p3, p4])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    # L1 along x-axis; L2 perpendicular → p4.x ≈ p3.x = 0
    assert abs(result.positions[p4][0] - 0.0) < 1e-3


def test_equal_length_lines():
    # EQUAL_LENGTH uses 4 point refs: [l1_start, l1_end, l2_start, l2_end]
    # L1 fixed with length 10 (p1=0,0 → p2=10,0).
    # L2 initially shorter (p3=0,5; p4=3,5).
    # Equal-length constraint → L2 length becomes 10 → p4.x = 10 (since p3 is fixed).
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("0 mm", "5 mm", "P3")
    p4 = svc.create_sketch_point("3 mm", "5 mm", "P4")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    svc.create_sketch_constraint("fix", [p3])
    svc.create_sketch_constraint("equal_length", [p1, p2, p3, p4])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    x4, y4 = result.positions[p4]
    length = ((x4 - 0.0) ** 2 + (y4 - 5.0) ** 2) ** 0.5
    assert abs(length - 10.0) < 1e-3


def test_angle_between_lines_45_degrees():
    # ANGLE uses 3 point refs: [vertex, arm1_point, arm2_point]
    # vertex=p1 (0,0), arm1=p2 (10,0) → L1 along x-axis.
    # arm2=p3 (10,5) initially → angle is arctan(5/10) ≈ 26.6°.
    # Angle constraint of 45° → p3 should be on y=x line from origin.
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("10 mm", "5 mm", "P3")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    svc.create_sketch_constraint("angle", [p1, p2, p3], "45 deg")
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    # L1 along x-axis from p1; L2 from p1 to p3 at 45° → p3 on y=x line
    x3, y3 = result.positions[p3]
    assert abs(x3 - y3) < 1e-3


def test_midpoint_constraint():
    # MIDPOINT uses 3 point refs: [midpoint, end1, end2]
    # end1=pA (0,0), end2=pB (10,0) — line along x-axis, both fixed.
    # p_mid starts off-target at (3,1); constraint moves it to midpoint (5,0).
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p_a = svc.create_sketch_point("0 mm", "0 mm", "PA")
    p_b = svc.create_sketch_point("10 mm", "0 mm", "PB")
    p_mid = svc.create_sketch_point("3 mm", "1 mm", "PM")
    svc.create_sketch_constraint("fix", [p_a])
    svc.create_sketch_constraint("fix", [p_b])
    svc.create_sketch_constraint("midpoint", [p_mid, p_a, p_b])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    assert abs(result.positions[p_mid][0] - 5.0) < 1e-3
    assert abs(result.positions[p_mid][1] - 0.0) < 1e-3
