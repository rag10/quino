from __future__ import annotations

from quino.domain.model import (
    Expression,
    Sketch,
    SketchArc,
    SketchCircle,
    SketchConstraint,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
)
from quino.domain.sketch_dependency import SketchDependencyGraph
from quino.domain.types import SketchConstraintType, SketchEntityType


def _pt(pid: str, x: str = "0", y: str = "0") -> SketchPoint:
    return SketchPoint(
        id=pid, name=pid, type=SketchEntityType.POINT,
        x=Expression(x), y=Expression(y),
    )


def _line(lid: str, s: str, e: str) -> SketchLineSegment:
    return SketchLineSegment(
        id=lid, name=lid, type=SketchEntityType.LINE_SEGMENT,
        start_point_id=s, end_point_id=e,
    )


def _circle(cid: str, center_id: str) -> SketchCircle:
    return SketchCircle(
        id=cid, name=cid, type=SketchEntityType.CIRCLE,
        center_point_id=center_id, radius=Expression("10"),
    )


def _arc(aid: str, center_id: str, s: str, e: str) -> SketchArc:
    return SketchArc(
        id=aid, name=aid, type=SketchEntityType.ARC,
        center_point_id=center_id, start_point_id=s, end_point_id=e,
    )


def _inf_line(lid: str, a: str, b: str) -> SketchInfiniteLine:
    return SketchInfiniteLine(
        id=lid, name=lid, type=SketchEntityType.INFINITE_LINE,
        point_a_id=a, point_b_id=b,
    )


# --- Entity → Parameter ---

def test_point_owns_x_and_y_parameters() -> None:
    sketch = Sketch(id="sk", name="T", entities={"p1": _pt("p1")})
    g = SketchDependencyGraph.build(sketch)
    params = g.parameters_for("p1")
    assert "p1.x" in params
    assert "p1.y" in params


def test_line_depends_on_both_endpoint_parameters() -> None:
    sketch = Sketch(
        id="sk", name="T",
        entities={"p1": _pt("p1"), "p2": _pt("p2"), "l1": _line("l1", "p1", "p2")},
    )
    g = SketchDependencyGraph.build(sketch)
    params = g.parameters_for("l1")
    assert "p1.x" in params
    assert "p1.y" in params
    assert "p2.x" in params
    assert "p2.y" in params


def test_circle_depends_on_center_and_radius() -> None:
    sketch = Sketch(
        id="sk", name="T",
        entities={"c1": _pt("c1"), "circ1": _circle("circ1", "c1")},
    )
    g = SketchDependencyGraph.build(sketch)
    params = g.parameters_for("circ1")
    assert "c1.x" in params
    assert "c1.y" in params
    assert "circ1.radius" in params


def test_arc_depends_on_center_start_end_parameters() -> None:
    sketch = Sketch(
        id="sk", name="T",
        entities={
            "c": _pt("c"), "s": _pt("s"), "e": _pt("e"),
            "arc1": _arc("arc1", "c", "s", "e"),
        },
    )
    g = SketchDependencyGraph.build(sketch)
    params = g.parameters_for("arc1")
    assert "c.x" in params
    assert "s.x" in params
    assert "e.y" in params


def test_infinite_line_depends_on_both_points() -> None:
    sketch = Sketch(
        id="sk", name="T",
        entities={"a": _pt("a"), "b": _pt("b"), "il1": _inf_line("il1", "a", "b")},
    )
    g = SketchDependencyGraph.build(sketch)
    params = g.parameters_for("il1")
    assert "a.x" in params
    assert "b.y" in params


# --- Reverse index: Parameter → Entities ---

def test_reverse_index_parameter_affects_line() -> None:
    sketch = Sketch(
        id="sk", name="T",
        entities={"p1": _pt("p1"), "p2": _pt("p2"), "l1": _line("l1", "p1", "p2")},
    )
    g = SketchDependencyGraph.build(sketch)
    affected = g.entities_for_parameter("p1.x")
    assert "p1" in affected
    assert "l1" in affected


def test_reverse_index_circle_radius() -> None:
    sketch = Sketch(
        id="sk", name="T",
        entities={"c1": _pt("c1"), "circ1": _circle("circ1", "c1")},
    )
    g = SketchDependencyGraph.build(sketch)
    affected = g.entities_for_parameter("circ1.radius")
    assert "circ1" in affected


# --- Constraint → Parameter ---

def test_constraint_dependencies_include_reference_point_params() -> None:
    p1 = _pt("p1")
    p2 = _pt("p2")
    constraint = SketchConstraint(
        id="c1", name="Fix", type=SketchConstraintType.FIX,
        references=["p1"], entity_references=[],
    )
    sketch = Sketch(
        id="sk", name="T",
        entities={"p1": p1, "p2": p2},
        constraints={"c1": constraint},
    )
    g = SketchDependencyGraph.build(sketch)
    params = g.parameters_for_constraint("c1")
    assert "p1.x" in params
    assert "p1.y" in params


# --- Expression → Variable ---

def test_variables_for_simple_expression() -> None:
    deps = SketchDependencyGraph.variables_for_expression("width / 2")
    assert "width" in deps


def test_variables_for_expression_filters_math_builtins() -> None:
    deps = SketchDependencyGraph.variables_for_expression("sin(angle) + pi")
    assert "angle" in deps
    assert "sin" not in deps
    assert "pi" not in deps


def test_variables_for_literal_expression() -> None:
    deps = SketchDependencyGraph.variables_for_expression("100")
    assert deps == []
