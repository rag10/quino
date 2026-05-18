"""Translate QUINO SketchConstraints to python-solvespace native constraints.

Each handler receives:
- sys: SolverSystem instance
- wp: workplane Entity
- constraint: the QUINO SketchConstraint being emitted
- points: dict[str, Entity] mapping SketchPoint.id → Solvespace point handle
- entities: dict[str, Entity] mapping SketchEntity.id → Solvespace geometric entity
- project: the full Project (for parameter lookup when evaluating expressions)
- expressions: ExpressionService
- units: UnitService (unused for now; evaluate_property already converts)

Each handler mutates `sys` by adding the appropriate native constraint, or
raises ValueError with a descriptive message when the constraint is malformed
or references unknown ids.
"""
from __future__ import annotations

from typing import Callable

from quino.domain.model import Project, SketchConstraint
from quino.domain.types import SketchConstraintType
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService


def emit_constraint(
    sys,
    wp,
    constraint: SketchConstraint,
    *,
    points: dict[str, object],
    entities: dict[str, object],
    project: Project,
    expressions: ExpressionService,
    units: UnitService,
) -> None:
    """Emit a native Solvespace constraint for the given QUINO constraint.

    Raises ValueError if the constraint type is not yet supported or the
    constraint is malformed.  The caller catches this and adds the constraint
    id to bad_constraints.
    """
    handler = _HANDLERS.get(constraint.type)
    if handler is None:
        raise ValueError(f"Unsupported sketch constraint type: {constraint.type}")
    handler(sys, wp, constraint, points, entities, project, expressions, units)


def _evaluate_value_mm(
    c: SketchConstraint,
    project: Project,
    expressions: ExpressionService,
) -> float:
    """Evaluate the constraint's ScalarProperty value and return the numeric result.

    The value is already converted to the property's own unit (typically mm)
    by evaluate_property, so we return it directly.
    """
    if c.value is None:
        raise ValueError(f"Constraint {c.id!r} requires a value but has none")
    result = expressions.evaluate_property(c.value, project.parameters)
    return float(result.value)


def _emit_distance(sys, wp, c, points, entities, project, expressions, units):
    if len(c.references) != 2:
        raise ValueError(f"distance expects 2 references, got {c.references!r}")
    ref_a, ref_b = c.references
    a = points.get(ref_a) or entities.get(ref_a)
    b = points.get(ref_b) or entities.get(ref_b)
    if a is None:
        raise ValueError(f"distance: unknown id {ref_a!r}")
    if b is None:
        raise ValueError(f"distance: unknown id {ref_b!r}")
    value_mm = _evaluate_value_mm(c, project, expressions)
    sys.distance(a, b, value_mm, wp)


def _emit_coincident(sys, wp, c, points, entities, project, expressions, units):
    if len(c.references) < 2:
        raise ValueError(f"coincident expects >=2 references, got {c.references!r}")
    refs = list(c.references)
    primary = points.get(refs[0]) or entities.get(refs[0])
    if primary is None:
        raise ValueError(f"coincident: unknown id {refs[0]!r}")
    for other_id in refs[1:]:
        other = points.get(other_id) or entities.get(other_id)
        if other is None:
            raise ValueError(f"coincident: unknown id {other_id!r}")
        sys.coincident(primary, other, wp)


def _emit_horizontal(sys, wp, c, points, entities, project, expressions, units):
    if not c.references:
        raise ValueError("horizontal expects at least one reference")
    ref = c.references[0]
    # Case 1: reference is a line entity id.
    line = entities.get(ref)
    if line is not None:
        sys.horizontal(line, wp)
        return
    # Case 2: two point ids — build an implicit line for the constraint.
    if len(c.references) >= 2:
        pa = points.get(ref)
        pb = points.get(c.references[1])
        if pa is not None and pb is not None:
            implicit_line = sys.add_line_2d(pa, pb, wp)
            sys.horizontal(implicit_line, wp)
            return
    raise ValueError(
        f"horizontal: could not resolve reference {ref!r} as entity or point pair"
    )


def _emit_vertical(sys, wp, c, points, entities, project, expressions, units):
    if not c.references:
        raise ValueError("vertical expects at least one reference")
    ref = c.references[0]
    # Case 1: reference is a line entity id.
    line = entities.get(ref)
    if line is not None:
        sys.vertical(line, wp)
        return
    # Case 2: two point ids — build an implicit line for the constraint.
    if len(c.references) >= 2:
        pa = points.get(ref)
        pb = points.get(c.references[1])
        if pa is not None and pb is not None:
            implicit_line = sys.add_line_2d(pa, pb, wp)
            sys.vertical(implicit_line, wp)
            return
    raise ValueError(
        f"vertical: could not resolve reference {ref!r} as entity or point pair"
    )


def _emit_parallel(sys, wp, c, points, entities, project, expressions, units):
    # QUINO stores 4 point refs: [line1_start, line1_end, line2_start, line2_end]
    if len(c.references) != 4:
        raise ValueError(f"parallel expects 4 point refs (2 lines), got {c.references}")
    pa, pb, pc, pd = c.references
    p1a = points.get(pa)
    p1b = points.get(pb)
    p2a = points.get(pc)
    p2b = points.get(pd)
    if p1a is None or p1b is None or p2a is None or p2b is None:
        raise ValueError(f"parallel: unknown point reference in {c.references}")
    l1 = sys.add_line_2d(p1a, p1b, wp)
    l2 = sys.add_line_2d(p2a, p2b, wp)
    sys.parallel(l1, l2, wp)


def _emit_perpendicular(sys, wp, c, points, entities, project, expressions, units):
    # QUINO stores 4 point refs: [line1_start, line1_end, line2_start, line2_end]
    if len(c.references) != 4:
        raise ValueError(f"perpendicular expects 4 point refs (2 lines), got {c.references}")
    pa, pb, pc, pd = c.references
    p1a = points.get(pa)
    p1b = points.get(pb)
    p2a = points.get(pc)
    p2b = points.get(pd)
    if p1a is None or p1b is None or p2a is None or p2b is None:
        raise ValueError(f"perpendicular: unknown point reference in {c.references}")
    l1 = sys.add_line_2d(p1a, p1b, wp)
    l2 = sys.add_line_2d(p2a, p2b, wp)
    sys.perpendicular(l1, l2, wp, False)


def _emit_equal_length(sys, wp, c, points, entities, project, expressions, units):
    # QUINO stores 4 point refs: [line1_start, line1_end, line2_start, line2_end]
    if len(c.references) != 4:
        raise ValueError(f"equal_length expects 4 point refs (2 lines), got {c.references}")
    pa, pb, pc, pd = c.references
    p1a = points.get(pa)
    p1b = points.get(pb)
    p2a = points.get(pc)
    p2b = points.get(pd)
    if p1a is None or p1b is None or p2a is None or p2b is None:
        raise ValueError(f"equal_length: unknown point reference in {c.references}")
    l1 = sys.add_line_2d(p1a, p1b, wp)
    l2 = sys.add_line_2d(p2a, p2b, wp)
    sys.equal(l1, l2, wp)


def _emit_angle(sys, wp, c, points, entities, project, expressions, units):
    # QUINO stores 3 point refs: [vertex, arm1_point, arm2_point]
    if len(c.references) != 3:
        raise ValueError(f"angle expects 3 point refs (vertex + 2 arms), got {c.references}")
    if c.value is None:
        raise ValueError(f"angle constraint {c.id} requires a value")
    p_vertex = points.get(c.references[0])
    p_arm1 = points.get(c.references[1])
    p_arm2 = points.get(c.references[2])
    if p_vertex is None or p_arm1 is None or p_arm2 is None:
        raise ValueError(f"angle: unknown point reference in {c.references}")
    l1 = sys.add_line_2d(p_vertex, p_arm1, wp)
    l2 = sys.add_line_2d(p_vertex, p_arm2, wp)
    # evaluate_expression returns a Quantity; convert to degrees for Solvespace.
    quantity = expressions.evaluate_expression(c.value.expression, project.parameters)
    deg = float(units.convert(quantity, "deg"))
    sys.angle(l1, l2, deg, wp, False)


def _emit_midpoint(sys, wp, c, points, entities, project, expressions, units):
    # QUINO stores 3 point refs: [midpoint, end1, end2]
    if len(c.references) != 3:
        raise ValueError(f"midpoint expects 3 point refs (mid, end1, end2), got {c.references}")
    p_mid = points.get(c.references[0])
    p_end1 = points.get(c.references[1])
    p_end2 = points.get(c.references[2])
    if p_mid is None or p_end1 is None or p_end2 is None:
        raise ValueError(f"midpoint: unknown point reference in {c.references}")
    line = sys.add_line_2d(p_end1, p_end2, wp)
    sys.midpoint(p_mid, line, wp)


_HANDLERS: dict[SketchConstraintType, Callable] = {
    SketchConstraintType.DISTANCE: _emit_distance,
    SketchConstraintType.COINCIDENT: _emit_coincident,
    SketchConstraintType.HORIZONTAL: _emit_horizontal,
    SketchConstraintType.VERTICAL: _emit_vertical,
    SketchConstraintType.PARALLEL: _emit_parallel,
    SketchConstraintType.PERPENDICULAR: _emit_perpendicular,
    SketchConstraintType.EQUAL_LENGTH: _emit_equal_length,
    SketchConstraintType.ANGLE: _emit_angle,
    SketchConstraintType.MIDPOINT: _emit_midpoint,
}
