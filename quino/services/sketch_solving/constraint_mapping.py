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
from quino.services.sketch_solving._auxiliary_geometry import (
    add_horizontal_distance_aux_line,
    add_vertical_distance_aux_line,
)
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
    # Two valid shapes:
    #  - >=2 point references (regular point coincidence).
    #  - 1 point + 1 entity reference (point-on-curve / point-on-line; the
    #    validator accepts this form — see SketchCommands._validate_sketch_constraint_references).
    if len(c.references) == 1 and len(c.entity_references) == 1:
        point = points.get(c.references[0])
        entity = entities.get(c.entity_references[0])
        if point is None:
            raise ValueError(f"coincident: unknown point {c.references[0]!r}")
        if entity is None:
            raise ValueError(f"coincident: unknown entity {c.entity_references[0]!r}")
        sys.coincident(point, entity, wp)
        return
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


def _emit_collinear(sys, wp, c, points, entities, project, expressions, units):
    """N+ points collinear: build a line from the first two, constrain the rest."""
    # QUINO stores 4 point refs minimum; first two anchor the line, rest lie on it.
    if len(c.references) < 3:
        raise ValueError(f"collinear expects >=3 point references, got {c.references}")
    anchor_a = points.get(c.references[0])
    anchor_b = points.get(c.references[1])
    if anchor_a is None or anchor_b is None:
        raise ValueError(f"collinear: unknown anchor point in {c.references}")
    aux_line = sys.add_line_2d(anchor_a, anchor_b, wp)
    for pid in c.references[2:]:
        p = points.get(pid)
        if p is None:
            raise ValueError(f"collinear: unknown point {pid}")
        sys.coincident(p, aux_line, wp)


def _emit_symmetric(sys, wp, c, points, entities, project, expressions, units):
    """Two points symmetric about an axis line defined by two other points.

    QUINO stores 4 point refs: [p1, p2, axis_point_a, axis_point_b].
    """
    if len(c.references) != 4:
        raise ValueError(f"symmetric expects 4 point refs, got {c.references}")
    p1 = points.get(c.references[0])
    p2 = points.get(c.references[1])
    line_a = points.get(c.references[2])
    line_b = points.get(c.references[3])
    if any(x is None for x in (p1, p2, line_a, line_b)):
        raise ValueError(f"symmetric: unknown reference in {c.references}")
    aux_line = sys.add_line_2d(line_a, line_b, wp)
    sys.symmetric(p1, p2, aux_line, wp)


def _emit_on_circle(sys, wp, c, points, entities, project, expressions, units):
    """A point must lie on a circle or arc circumference.

    QUINO stores: references=[point_id], entity_references=[circle_entity_id].
    """
    if len(c.references) != 1 or len(c.entity_references) != 1:
        raise ValueError(
            f"on_circle expects 1 point ref + 1 entity ref, "
            f"got refs={c.references} entity_refs={c.entity_references}"
        )
    point = points.get(c.references[0])
    curve = entities.get(c.entity_references[0])
    if point is None:
        raise ValueError(f"on_circle: unknown point {c.references[0]!r}")
    if curve is None:
        raise ValueError(f"on_circle: unknown curve entity {c.entity_references[0]!r}")
    sys.coincident(point, curve, wp)


def _emit_tangent(sys, wp, c, points, entities, project, expressions, units):
    """Tangency between line+curve or curve+curve.

    python-solvespace's sys.tangent() only accepts arc/cubic entities (not
    circles). We sidestep the gap with an auxiliary point that lies on both
    target entities at the tangent point:

    - line + circle/arc: aux point on the line, on the curve, with the segment
      center->aux perpendicular to the line. This enforces aux as the foot of
      perpendicular from the curve's center to the line; PT_ON_CIRCLE then
      forces distance(center, line) = radius, which is tangency.
    - curve + curve: aux point on both circles. Solvespace will pick external
      or internal tangency based on the initial geometry (the closer solution).

    QUINO stores tangent constraints as:
      - references=[line_p1, line_p2], entity_references=[curve_entity_id]
      - references=[], entity_references=[curve1_id, curve2_id]

    The auxiliary geometry lives only inside the SolverSystem; it never enters
    the QUINO domain.
    """
    import python_solvespace as _ps
    from quino.domain.model import SketchArc, SketchCircle

    sketch = project.sketch
    n_refs = len(c.references)
    n_ents = len(c.entity_references)

    def _curve_handles(entity_id: str):
        """Return (center_handle, curve_handle, center_xy) for a circle/arc."""
        ent = sketch.entities.get(entity_id) if sketch is not None else None
        if not isinstance(ent, (SketchCircle, SketchArc)):
            raise ValueError(f"tangent: entity {entity_id!r} is not a circle/arc")
        center_handle = points.get(ent.center_point_id)
        if center_handle is None:
            raise ValueError(f"tangent: center point of {entity_id!r} missing in handle map")
        curve_handle = entities.get(entity_id)
        if curve_handle is None:
            raise ValueError(f"tangent: entity {entity_id!r} not built in solver")
        center_pt = next(p for p in sketch.points() if p.id == ent.center_point_id)
        cx_q = expressions.evaluate_expression(center_pt.x.text, project.parameters)
        cy_q = expressions.evaluate_expression(center_pt.y.text, project.parameters)
        cx = float(units.convert(cx_q, center_pt.x.unit))
        cy = float(units.convert(cy_q, center_pt.y.unit))
        return center_handle, curve_handle, (cx, cy)

    def _point_xy(point_id: str) -> tuple[float, float]:
        pt = next(p for p in sketch.points() if p.id == point_id)
        xq = expressions.evaluate_expression(pt.x.text, project.parameters)
        yq = expressions.evaluate_expression(pt.y.text, project.parameters)
        return (
            float(units.convert(xq, pt.x.unit)),
            float(units.convert(yq, pt.y.unit)),
        )

    if n_refs == 2 and n_ents == 1:
        # Line tangent to circle/arc.
        line_p1 = points.get(c.references[0])
        line_p2 = points.get(c.references[1])
        if line_p1 is None or line_p2 is None:
            raise ValueError(f"tangent: unknown line point in {c.references}")
        line = sys.add_line_2d(line_p1, line_p2, wp)
        center_handle, curve_handle, (cx, cy) = _curve_handles(c.entity_references[0])
        # Auxiliary point at foot of perpendicular from center to line (initial guess).
        ax, ay = _point_xy(c.references[0])
        bx, by = _point_xy(c.references[1])
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            init_x, init_y = cx, cy
        else:
            t = ((cx - ax) * dx + (cy - ay) * dy) / denom
            init_x = ax + t * dx
            init_y = ay + t * dy
        aux = sys.add_point_2d(init_x, init_y, wp)
        none_e = _ps.Entity()
        sys.add_constraint(
            _ps.Constraint.PT_ON_LINE, wp, 0.0,
            aux, none_e, line, none_e, none_e, none_e, 0, 0,
        )
        aux_line = sys.add_line_2d(aux, center_handle, wp)
        sys.perpendicular(aux_line, line, wp, False)
        sys.add_constraint(
            _ps.Constraint.PT_ON_CIRCLE, wp, 0.0,
            aux, none_e, curve_handle, none_e, none_e, none_e, 0, 0,
        )
        return

    if n_refs == 0 and n_ents == 2:
        # Curve-curve tangency: aux point on both circles. Initial aux position
        # biases Solvespace toward external (between centers) or internal
        # (beyond the second center) — the value field carries the sign.
        c1_center, curve1, (c1x, c1y) = _curve_handles(c.entity_references[0])
        c2_center, curve2, (c2x, c2y) = _curve_handles(c.entity_references[1])
        sign = 1.0
        if c.value is not None:
            try:
                raw = expressions.evaluate_expression(c.value.expression, project.parameters)
                sign_val = float(units.convert(raw, c.value.unit))
                sign = -1.0 if sign_val < 0 else 1.0
            except Exception:
                sign = 1.0
        dx = c2x - c1x
        dy = c2y - c1y
        norm = (dx * dx + dy * dy) ** 0.5
        if norm <= 1e-12:
            ux, uy = 1.0, 0.0
        else:
            ux, uy = dx / norm, dy / norm
        if sign > 0:
            # External: aux between centers.
            init_ax = 0.5 * (c1x + c2x)
            init_ay = 0.5 * (c1y + c2y)
        else:
            # Internal: aux beyond c2 in the c1->c2 direction (forces both circles
            # to touch on the far side of c2, which is the internal tangent topology).
            init_ax = c2x + ux * max(norm, 1.0)
            init_ay = c2y + uy * max(norm, 1.0)
        aux = sys.add_point_2d(init_ax, init_ay, wp)
        none_e = _ps.Entity()
        sys.add_constraint(
            _ps.Constraint.PT_ON_CIRCLE, wp, 0.0,
            aux, none_e, curve1, none_e, none_e, none_e, 0, 0,
        )
        sys.add_constraint(
            _ps.Constraint.PT_ON_CIRCLE, wp, 0.0,
            aux, none_e, curve2, none_e, none_e, none_e, 0, 0,
        )
        return

    raise ValueError(
        f"tangent expects (2 pt refs + 1 entity ref) or (0 pt refs + 2 entity refs), "
        f"got refs={c.references} entity_refs={c.entity_references}"
    )


def _emit_horizontal_distance(sys, wp, c, points, entities, project, expressions, units):
    """Constrain |p1.x - p2.x| = value (mm) via an auxiliary horizontal line."""
    if len(c.references) != 2:
        raise ValueError(f"horizontal_distance expects 2 points, got {c.references}")
    p1 = points.get(c.references[0])
    p2 = points.get(c.references[1])
    if p1 is None or p2 is None:
        raise ValueError(f"horizontal_distance: unknown point in {c.references}")
    if c.value is None:
        raise ValueError(f"horizontal_distance constraint {c.id} requires a value")
    quantity = expressions.evaluate_expression(c.value.expression, project.parameters)
    distance_mm = float(units.convert(quantity, "mm"))
    aux_line = add_horizontal_distance_aux_line(sys, wp, p1)
    sys.distance(p2, aux_line, distance_mm, wp)


def _emit_vertical_distance(sys, wp, c, points, entities, project, expressions, units):
    """Constrain |p1.y - p2.y| = value (mm) via an auxiliary horizontal line."""
    if len(c.references) != 2:
        raise ValueError(f"vertical_distance expects 2 points, got {c.references}")
    p1 = points.get(c.references[0])
    p2 = points.get(c.references[1])
    if p1 is None or p2 is None:
        raise ValueError(f"vertical_distance: unknown point in {c.references}")
    if c.value is None:
        raise ValueError(f"vertical_distance constraint {c.id} requires a value")
    quantity = expressions.evaluate_expression(c.value.expression, project.parameters)
    distance_mm = float(units.convert(quantity, "mm"))
    aux_line = add_vertical_distance_aux_line(sys, wp, p1)
    sys.distance(p2, aux_line, distance_mm, wp)


def _emit_radius(sys, wp, c, points, entities, project, expressions, units):
    """Constrain a circle or arc radius to a target value (mm).

    Solvespace uses diameter natively; we convert: diameter = 2 * radius.

    QUINO stores: references=[], entity_references=[circle_or_arc_id].
    """
    ent_ids = list(c.entity_references) if c.entity_references else list(c.references)
    if len(ent_ids) != 1:
        raise ValueError(
            f"radius expects exactly 1 entity ref, got refs={c.references} entity_refs={c.entity_references}"
        )
    curve = entities.get(ent_ids[0])
    if curve is None:
        raise ValueError(f"radius: unknown entity {ent_ids[0]!r}")
    if c.value is None:
        raise ValueError(f"radius constraint {c.id} requires a value")
    quantity = expressions.evaluate_expression(c.value.expression, project.parameters)
    radius_mm = float(units.convert(quantity, "mm"))
    sys.diameter(curve, 2.0 * radius_mm)


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
    SketchConstraintType.COLLINEAR: _emit_collinear,
    SketchConstraintType.SYMMETRIC: _emit_symmetric,
    SketchConstraintType.ON_CIRCLE: _emit_on_circle,
    SketchConstraintType.TANGENT: _emit_tangent,
    SketchConstraintType.RADIUS: _emit_radius,
    SketchConstraintType.HORIZONTAL_DISTANCE: _emit_horizontal_distance,
    SketchConstraintType.VERTICAL_DISTANCE: _emit_vertical_distance,
}
