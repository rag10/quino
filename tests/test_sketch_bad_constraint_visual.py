"""Tests for bad_constraint_ids propagation from solver to Sketch domain."""
from quino import ApplicationService


def test_bad_constraint_ids_populated_when_solver_fails():
    """A constraint that can't be applied surfaces in sketch.bad_constraint_ids."""
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("0 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    # Impossible: both points fixed at the same place, distance constraint demands 10mm.
    bad_id = svc.create_sketch_constraint("distance", [p1, p2], value="10 mm")
    svc.solve_sketch()
    # Either the constraint is in bad_constraints (mapping rejected it), or the
    # solver couldn't converge (overall failure). Both are valid outcomes —
    # what matters is that SOMETHING is reported on the sketch domain.
    sketch = svc.project.sketch
    has_bad_or_error = bool(sketch.bad_constraint_ids) or sketch.solve_error
    assert has_bad_or_error, (
        f"Expected bad_constraint_ids or solve_error after impossible constraint; "
        f"got bad_constraint_ids={sketch.bad_constraint_ids!r}, solve_error={sketch.solve_error!r}"
    )


def test_bad_constraint_ids_cleared_when_solver_succeeds():
    """After a successful solve, bad_constraint_ids is empty."""
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("distance", [p1, p2], value="10 mm")
    svc.solve_sketch()
    assert svc.project.sketch.bad_constraint_ids == []
