from __future__ import annotations

import pytest

from quino.domain.model import (
    Expression,
    Sketch,
    SketchConstraint,
    SketchLineSegment,
    SketchPoint,
)
from quino.domain.types import (
    Dimension,
    SketchConstraintType,
    SketchEntityType,
)
from quino.services.sketch_dof import SketchDofAnalyzer


def _expr(expression: str, unit: str = "mm") -> Expression:
    return Expression(text=expression, unit=unit)


def _make_sketch(
    points: list[SketchPoint],
    constraints: list[SketchConstraint],
    entities: list | None = None,
) -> Sketch:
    all_entities = {pt.id: pt for pt in points}
    if entities:
        for entity in entities:
            all_entities[entity.id] = entity
    return Sketch(
        id="sk1",
        name="S",
        visible=True,
        entities=all_entities,
        constraints={c.id: c for c in constraints},
    )


def test_no_constraints_all_free() -> None:
    pt = SketchPoint(
        id="p1",
        name="P1",
        type=SketchEntityType.POINT,
        x=_expr("0"),
        y=_expr("0"),
    )
    sketch = _make_sketch([pt], [])
    result = SketchDofAnalyzer().analyze(sketch)
    assert result.point_dof["p1"] == 2


def test_fix_removes_both_dof() -> None:
    pt = SketchPoint(
        id="p1",
        name="P1",
        type=SketchEntityType.POINT,
        x=_expr("0"),
        y=_expr("0"),
    )
    c = SketchConstraint(
        id="c1",
        name="Fix1",
        type=SketchConstraintType.FIX,
        references=["p1"],
        entity_references=[],
        value=None,
    )
    sketch = _make_sketch([pt], [c])
    result = SketchDofAnalyzer().analyze(sketch)
    assert result.point_dof["p1"] == 0
    assert result.fully_constrained_point_ids == {"p1"}


def test_horizontal_removes_one_dof() -> None:
    p1 = SketchPoint(
        id="p1",
        name="P1",
        type=SketchEntityType.POINT,
        x=_expr("0"),
        y=_expr("0"),
    )
    p2 = SketchPoint(
        id="p2",
        name="P2",
        type=SketchEntityType.POINT,
        x=_expr("10"),
        y=_expr("5"),
    )
    c = SketchConstraint(
        id="c1",
        name="H1",
        type=SketchConstraintType.HORIZONTAL,
        references=["p1", "p2"],
        entity_references=[],
        value=None,
    )
    sketch = _make_sketch([p1, p2], [c])
    result = SketchDofAnalyzer().analyze(sketch)
    assert result.total_free_dof == 3


def test_line_fully_constrained() -> None:
    p1 = SketchPoint(
        id="p1",
        name="P1",
        type=SketchEntityType.POINT,
        x=_expr("0"),
        y=_expr("0"),
    )
    p2 = SketchPoint(
        id="p2",
        name="P2",
        type=SketchEntityType.POINT,
        x=_expr("10"),
        y=_expr("0"),
    )
    fix1 = SketchConstraint(
        id="c1",
        name="Fix1",
        type=SketchConstraintType.FIX,
        references=["p1"],
        entity_references=[],
        value=None,
    )
    fix2 = SketchConstraint(
        id="c2",
        name="Fix2",
        type=SketchConstraintType.FIX,
        references=["p2"],
        entity_references=[],
        value=None,
    )
    sketch = _make_sketch([p1, p2], [fix1, fix2])
    result = SketchDofAnalyzer().analyze(sketch)
    assert result.total_free_dof == 0
    assert result.fully_constrained_point_ids == {"p1", "p2"}


def test_line_entity_fully_constrained_when_both_points_are() -> None:
    p1 = SketchPoint(
        id="p1",
        name="P1",
        type=SketchEntityType.POINT,
        x=_expr("0"),
        y=_expr("0"),
    )
    p2 = SketchPoint(
        id="p2",
        name="P2",
        type=SketchEntityType.POINT,
        x=_expr("10"),
        y=_expr("0"),
    )
    line = SketchLineSegment(
        id="l1",
        name="L1",
        type=SketchEntityType.LINE_SEGMENT,
        start_point_id="p1",
        end_point_id="p2",
    )
    fix1 = SketchConstraint(
        id="c1",
        name="Fix1",
        type=SketchConstraintType.FIX,
        references=["p1"],
        entity_references=[],
        value=None,
    )
    fix2 = SketchConstraint(
        id="c2",
        name="Fix2",
        type=SketchConstraintType.FIX,
        references=["p2"],
        entity_references=[],
        value=None,
    )
    sketch = _make_sketch([p1, p2], [fix1, fix2], entities=[line])
    result = SketchDofAnalyzer().analyze(sketch)
    assert "l1" in result.fully_constrained_entity_ids
