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


def test_collinear_four_points():
    # COLLINEAR uses 4 point refs: first two define the anchor line, next two lie on it.
    # Anchor: p1=(0,0) fixed, p2=(10,0) fixed → line along y=0.
    # p3=(5,3) and p4=(8,-2) start off the line; constraint pulls them to y=0.
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("5 mm", "3 mm", "P3")   # off-line
    p4 = svc.create_sketch_point("8 mm", "-2 mm", "P4")  # off-line
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    svc.create_sketch_constraint("collinear", [p1, p2, p3, p4])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    # p3 and p4 must have y ≈ 0 (on the anchor line y=0)
    assert abs(result.positions[p3][1] - 0.0) < 1e-3
    assert abs(result.positions[p4][1] - 0.0) < 1e-3


def test_symmetric_about_axis_line():
    # SYMMETRIC uses 4 point refs: [p1, p2, axis_point_a, axis_point_b]
    # axis_a=(-10,0), axis_b=(10,0) → axis is y=0.
    # p1=(0,5) is fixed. p2=(0,-3) starts asymmetric.
    # Constraint → p2 must mirror p1 about y=0 → p2.y = -5.
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "5 mm", "P1")
    p2 = svc.create_sketch_point("0 mm", "-3 mm", "P2")   # asymmetric
    axis_a = svc.create_sketch_point("-10 mm", "0 mm", "AA")
    axis_b = svc.create_sketch_point("10 mm", "0 mm", "AB")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [axis_a])
    svc.create_sketch_constraint("fix", [axis_b])
    svc.create_sketch_constraint("symmetric", [p1, p2, axis_a, axis_b])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    # p2 must mirror p1 about y=0 → p2.y ≈ -5
    assert abs(result.positions[p2][1] - (-5.0)) < 1e-3


def test_on_circle_pulls_point_to_circumference():
    # ON_CIRCLE: references=[point_id], entity_references=[circle_entity_id].
    # Center at (0,0) fixed, circle radius=10 mm.
    # pt=(5,5) starts off the circle (dist ≈ 7.07 mm); constraint pulls it to radius.
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    center = svc.create_sketch_point("0 mm", "0 mm", "C")
    circle = svc.create_sketch_circle(center, "10 mm", "Circ")
    pt = svc.create_sketch_point("5 mm", "5 mm", "PT")  # dist ≈ 7.07 (off circle)
    svc.create_sketch_constraint("fix", [center])
    svc.create_sketch_constraint("on_circle", [pt], entity_references=[circle])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    x, y = result.positions[pt]
    radius = (x * x + y * y) ** 0.5
    assert abs(radius - 10.0) < 1e-3


def test_radius_constraint_updates_circle_radius():
    """RADIUS constraint must change the circle's stored radius to the target."""
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    center = svc.create_sketch_point("0 mm", "0 mm", "C")
    circle = svc.create_sketch_circle(center, "5 mm", "Circ")  # initial radius 5 mm
    svc.create_sketch_constraint("fix", [center])
    # RADIUS API: references=[center_point_id], entity_references=[circle_id], value=radius
    svc.create_sketch_constraint("distance", [center], value="12 mm", entity_references=[circle])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    assert circle in result.radius_updates, f"radius_updates={result.radius_updates}"
    assert abs(result.radius_updates[circle] - 12.0) < 1e-4


def test_radius_constraint_lets_on_circle_pull_to_new_radius():
    """A point with on_circle on a circle constrained to radius=8 must end on r=8."""
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    center = svc.create_sketch_point("0 mm", "0 mm", "C")
    circle = svc.create_sketch_circle(center, "5 mm", "Circ")  # declared 5 mm
    pt = svc.create_sketch_point("3 mm", "0 mm", "PT")
    svc.create_sketch_constraint("fix", [center])
    # RADIUS API: references=[center_point_id], entity_references=[circle_id], value=radius
    svc.create_sketch_constraint("distance", [center], value="8 mm", entity_references=[circle])
    svc.create_sketch_constraint("on_circle", [pt], entity_references=[circle])
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    x, y = result.positions[pt]
    dist = (x * x + y * y) ** 0.5
    assert abs(dist - 8.0) < 1e-3, f"point at dist {dist} from center"
    assert abs(result.radius_updates[circle] - 8.0) < 1e-3


def test_horizontal_distance_constrains_x_delta():
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("3 mm", "7 mm", "P2")  # initial dx=3
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("horizontal_distance", [p1, p2], value="10 mm")
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    x2, _ = result.positions[p2]
    # |x2 - x1| = 10. p1 is fixed at (0,0), so x2 should be ±10.
    assert abs(abs(x2 - 0.0) - 10.0) < 1e-4


def test_vertical_distance_constrains_y_delta():
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("3 mm", "2 mm", "P2")  # initial dy=2
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("vertical_distance", [p1, p2], value="8 mm")
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    _, y2 = result.positions[p2]
    assert abs(abs(y2 - 0.0) - 8.0) < 1e-4


def test_no_aux_geometry_leaks_into_project():
    """Critical invariant: aux geometry must NOT pollute the QUINO domain."""
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("3 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("horizontal_distance", [p1, p2], value="10 mm")
    point_count_before = len(svc.project.sketch.points())
    entity_count_before = len(svc.project.sketch.entities)
    _make_backend().solve(svc.project)
    assert len(svc.project.sketch.points()) == point_count_before
    assert len(svc.project.sketch.entities) == entity_count_before


def test_locked_points_remain_fixed_during_solve():
    """Locked points must not move while a free point satisfies the constraint.

    Two points are locked; a third free point is constrained to one of the
    locked points. The solver must keep the locked pair in place and move only
    the free point.
    """
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    # Place p1 away from the sketch origin so it is not coincident with it.
    p1 = svc.create_sketch_point("1 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("6 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("3 mm", "0 mm", "P3")  # free point
    # Constrain p3 to be 3 mm from p1; p3 must move, p1 and p2 must not.
    svc.create_sketch_constraint("distance", [p1, p3], value="3 mm")
    result = _make_backend().solve(svc.project, locked_point_ids={p1, p2})
    assert result.success, result.message
    # Locked points unchanged.
    assert abs(result.positions[p1][0] - 1.0) < 1e-6
    assert abs(result.positions[p1][1] - 0.0) < 1e-6
    assert abs(result.positions[p2][0] - 6.0) < 1e-6
    assert abs(result.positions[p2][1] - 0.0) < 1e-6


def test_drag_pattern_moves_only_unlocked_point():
    """Canonical drag: all points fixed except the one being dragged.

    Only a constraint between a locked point and the free point is present —
    a constraint *between two locked points* would over-constrain the dragged
    group and cause solvespace to report INCONSISTENT.
    """
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    # p1 is away from origin to avoid coincidence with the auto-created origin point.
    p1 = svc.create_sketch_point("1 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("6 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("3 mm", "1 mm", "P3")  # off-target, to be dragged
    # Only constrain the free point against a locked anchor; no constraint between
    # the two locked points (that would create an over-constrained dragged group).
    svc.create_sketch_constraint("distance", [p2, p3], value="5 mm")
    # Drag scenario: only p3 is free.
    result = _make_backend().solve(svc.project, locked_point_ids={p1, p2})
    assert result.success, result.message
    # Locked points unchanged.
    assert abs(result.positions[p1][0] - 1.0) < 1e-6
    assert abs(result.positions[p2][0] - 6.0) < 1e-6
    # p3 moved to satisfy distance(p2, p3) = 5.
    x3, y3 = result.positions[p3]
    dist = ((x3 - 6.0) ** 2 + (y3 - 0.0) ** 2) ** 0.5
    assert abs(dist - 5.0) < 1e-4


def test_lock_overrides_fix_constraint_semantics():
    """locked_point_ids and FIX constraints both result in immovable points.

    A point with neither FIX nor locked status is solvable; once FIX or locked
    is applied, the solver must not move it.
    """
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("7 mm", "0 mm", "P2")
    svc.create_sketch_constraint("distance", [p1, p2], value="10 mm")
    # Lock p1 instead of FIX-ing it — same effect.
    result = _make_backend().solve(svc.project, locked_point_ids={p1})
    assert result.success, result.message
    assert abs(result.positions[p1][0] - 0.0) < 1e-6
    # p2 should be at distance 10 from p1.
    x2, y2 = result.positions[p2]
    dist = ((x2 - 0.0) ** 2 + (y2 - 0.0) ** 2) ** 0.5
    assert abs(dist - 10.0) < 1e-4


def test_tangent_line_to_circle_makes_line_touch_circle():
    """Recta tangente a circulo: la distancia del centro a la recta = radio."""
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    # Recta de (0,0) a (10,0), inicialmente alejada del circulo.
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    line = svc.create_sketch_line_segment(p1, p2, "L")
    # Circulo centro (5, 8) radio 3 - separado de la recta por dist=8.
    center = svc.create_sketch_point("5 mm", "8 mm", "C")
    circle = svc.create_sketch_circle(center, "3 mm", "Circ")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    svc.create_sketch_constraint("fix", [center])
    svc.create_sketch_constraint(
        "tangent", [p1, p2], value="1", entity_references=[circle]
    )
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    # El radio del circulo debe haberse ajustado a 8 (distancia del centro a la recta)
    assert circle in result.radius_updates
    assert abs(result.radius_updates[circle] - 8.0) < 1e-3


def test_tangent_circle_to_circle_external():
    """Dos circulos tangentes externos: distancia entre centros = r1 + r2."""
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    c1 = svc.create_sketch_point("0 mm", "0 mm", "C1")
    c2 = svc.create_sketch_point("20 mm", "0 mm", "C2")
    circ1 = svc.create_sketch_circle(c1, "5 mm", "Circ1")
    circ2 = svc.create_sketch_circle(c2, "3 mm", "Circ2")
    svc.create_sketch_constraint("fix", [c1])
    svc.create_sketch_constraint("fix", [c2])
    svc.create_sketch_constraint(
        "tangent", [], value="1", entity_references=[circ1, circ2]
    )
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    r1 = result.radius_updates.get(circ1, 5.0)
    r2 = result.radius_updates.get(circ2, 3.0)
    assert abs((r1 + r2) - 20.0) < 1e-3


def test_tangent_circle_to_circle_internal():
    """Dos circulos tangentes internos: distancia entre centros = |r1 - r2|."""
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    c1 = svc.create_sketch_point("0 mm", "0 mm", "C1")
    c2 = svc.create_sketch_point("5 mm", "0 mm", "C2")
    circ1 = svc.create_sketch_circle(c1, "10 mm", "Circ1")
    circ2 = svc.create_sketch_circle(c2, "3 mm", "Circ2")
    svc.create_sketch_constraint("fix", [c1])
    svc.create_sketch_constraint("fix", [c2])
    svc.create_sketch_constraint(
        "tangent", [], value="-1", entity_references=[circ1, circ2]
    )
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    r1 = result.radius_updates.get(circ1, 10.0)
    r2 = result.radius_updates.get(circ2, 3.0)
    assert abs(abs(r1 - r2) - 5.0) < 1e-3
