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


_HANDLERS: dict[SketchConstraintType, Callable] = {
    SketchConstraintType.DISTANCE: _emit_distance,
    SketchConstraintType.COINCIDENT: _emit_coincident,
    SketchConstraintType.HORIZONTAL: _emit_horizontal,
    SketchConstraintType.VERTICAL: _emit_vertical,
}
