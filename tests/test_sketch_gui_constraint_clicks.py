# tests/test_sketch_gui_constraint_clicks.py
"""Integration tests for sketch constraint creation via the ApplicationService.

These tests verify the shape of SketchConstraint domain objects produced when
the user creates each constraint type — locking in the contract between the
canvas click handlers and the domain. They also verify end-to-end solve
behavior for the common cases (the tangent line+circle bug originally
reported by the user is the headline regression test here).
"""
from quino import ApplicationService
from quino.domain.types import SketchConstraintType


def _make_app() -> ApplicationService:
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    return svc


def test_tangent_line_circle_creates_constraint_with_two_pt_one_ent_refs():
    """Headline regression: clicking tangent on a line + circle stores the
    right reference shape in the domain (2 point refs + 1 entity ref).
    """
    svc = _make_app()
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    svc.create_sketch_line_segment(p1, p2, "L")
    center = svc.create_sketch_point("5 mm", "8 mm", "C")
    circle = svc.create_sketch_circle(center, "3 mm", "Circ")

    cid = svc.create_sketch_constraint(
        "tangent", [p1, p2], value="1", entity_references=[circle]
    )
    constraint = svc.project.sketch.constraints[cid]
    assert constraint.type is SketchConstraintType.TANGENT
    assert constraint.references == [p1, p2]
    assert constraint.entity_references == [circle]


def test_tangent_circle_circle_creates_constraint_with_zero_pt_two_ent_refs():
    """Tangent between two circles: 0 point refs + 2 entity refs."""
    svc = _make_app()
    c1 = svc.create_sketch_point("0 mm", "0 mm", "C1")
    c2 = svc.create_sketch_point("20 mm", "0 mm", "C2")
    circ1 = svc.create_sketch_circle(c1, "5 mm", "Circ1")
    circ2 = svc.create_sketch_circle(c2, "3 mm", "Circ2")

    cid = svc.create_sketch_constraint(
        "tangent", [], value="1", entity_references=[circ1, circ2]
    )
    constraint = svc.project.sketch.constraints[cid]
    assert constraint.type is SketchConstraintType.TANGENT
    assert constraint.references == []
    assert constraint.entity_references == [circ1, circ2]


def test_parallel_two_segments_creates_constraint_with_four_pt_refs():
    """Parallel: 4 point refs (2 endpoints per line)."""
    svc = _make_app()
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("0 mm", "5 mm", "P3")
    p4 = svc.create_sketch_point("10 mm", "8 mm", "P4")
    cid = svc.create_sketch_constraint("parallel", [p1, p2, p3, p4])
    constraint = svc.project.sketch.constraints[cid]
    assert constraint.type is SketchConstraintType.PARALLEL
    assert constraint.references == [p1, p2, p3, p4]


def test_coincident_point_circle_creates_point_on_curve_constraint():
    """COINCIDENT now covers point-on-circle (ON_CIRCLE was retired in T4).

    Even if the API caller passes 'on_circle' as the type, it must auto-fold
    into COINCIDENT in the stored domain.
    """
    svc = _make_app()
    center = svc.create_sketch_point("0 mm", "0 mm", "C")
    circle = svc.create_sketch_circle(center, "5 mm", "Circ")
    pt = svc.create_sketch_point("3 mm", "3 mm", "PT")

    # Calling with 'coincident' explicitly
    cid_a = svc.create_sketch_constraint(
        "coincident", [pt], entity_references=[circle]
    )
    ca = svc.project.sketch.constraints[cid_a]
    assert ca.type is SketchConstraintType.COINCIDENT
    assert ca.references == [pt]
    assert ca.entity_references == [circle]

    # Calling with 'on_circle' must auto-fold to COINCIDENT.
    pt2 = svc.create_sketch_point("4 mm", "4 mm", "PT2")
    cid_b = svc.create_sketch_constraint(
        "on_circle", [pt2], entity_references=[circle]
    )
    cb = svc.project.sketch.constraints[cid_b]
    assert cb.type is SketchConstraintType.COINCIDENT, (
        f"on_circle should auto-convert to COINCIDENT after T4, "
        f"got {cb.type!r}"
    )


def test_solve_after_tangent_line_circle_succeeds_with_no_bad_constraints():
    """Full integration: tangent line+circle solves without dropping into bad_constraints."""
    svc = _make_app()
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    svc.create_sketch_line_segment(p1, p2, "L")
    center = svc.create_sketch_point("5 mm", "8 mm", "C")
    circle = svc.create_sketch_circle(center, "3 mm", "Circ")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    svc.create_sketch_constraint("fix", [center])
    svc.create_sketch_constraint(
        "tangent", [p1, p2], value="1", entity_references=[circle]
    )
    report = svc.solve_sketch()
    # No constraint should have been rejected
    assert svc.project.sketch.bad_constraint_ids == []
    # Report should contain a "solved" info message
    info_messages = [m.message for m in report.messages if m.level == "info"]
    assert any("solved" in m.lower() for m in info_messages), (
        f"Expected an 'info' 'solved' message, got: {[m.message for m in report.messages]}"
    )
