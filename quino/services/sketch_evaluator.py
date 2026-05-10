from __future__ import annotations

import math
from dataclasses import dataclass, field

from quino.domain.model import (
    Expression,
    Project,
    Sketch,
    SketchArc,
    SketchCircle,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
)
from quino.domain.sketch_evaluated import (
    BBox,
    EvaluatedArc,
    EvaluatedCircle,
    EvaluatedLineSegment,
    EvaluatedPoint,
    Vec2,
)
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService


@dataclass(slots=True)
class SolverParameterSet:
    """Flat parameter set fed to the solver."""

    parameters: dict[str, float] = field(default_factory=dict)


class ParameterMapper:
    """Maps a Sketch domain model into a flat SolverParameterSet."""

    def __init__(self, expression_service: ExpressionService, unit_service: UnitService) -> None:
        self.expression_service = expression_service
        self.unit_service = unit_service

    def build(self, sketch: Sketch, project: Project) -> SolverParameterSet:
        result: dict[str, float] = {}
        for point in sketch.points():
            result[f"{point.id}.x"] = self._eval(point.x, project)
            result[f"{point.id}.y"] = self._eval(point.y, project)
        for entity in sketch.entities.values():
            if isinstance(entity, SketchCircle):
                result[f"{entity.id}.radius"] = self._eval(entity.radius, project)
        return SolverParameterSet(parameters=result)

    def _eval(self, expression: Expression, project: Project) -> float:
        quantity = self.expression_service.evaluate_expression(expression.text, project.parameters)
        return self.unit_service.convert(quantity, expression.unit)


class GeometryEvaluator:
    """Evaluates sketch entities into concrete geometry."""

    def __init__(self, expression_service: ExpressionService, unit_service: UnitService) -> None:
        self.expression_service = expression_service
        self.unit_service = unit_service

    def evaluate(self, entity_id: str, sketch: Sketch, project: Project) -> EvaluatedPoint | EvaluatedLineSegment | EvaluatedCircle | EvaluatedArc | None:
        entity = sketch.entities.get(entity_id)
        if entity is None:
            return None
        if isinstance(entity, SketchPoint):
            return self._eval_point(entity, project)
        if isinstance(entity, SketchLineSegment):
            return self._eval_line(entity, sketch, project)
        if isinstance(entity, SketchCircle):
            return self._eval_circle(entity, sketch, project)
        if isinstance(entity, SketchArc):
            return self._eval_arc(entity, sketch, project)
        return None

    def _eval_expr(self, expression: Expression, project: Project) -> float:
        quantity = self.expression_service.evaluate_expression(expression.text, project.parameters)
        return self.unit_service.convert(quantity, expression.unit)

    def _point_pos(self, point_id: str, sketch: Sketch, project: Project) -> Vec2:
        point = sketch.entities.get(point_id)
        if not isinstance(point, SketchPoint):
            return Vec2(0.0, 0.0)
        return Vec2(self._eval_expr(point.x, project), self._eval_expr(point.y, project))

    def _eval_point(self, point: SketchPoint, project: Project) -> EvaluatedPoint:
        pos = Vec2(self._eval_expr(point.x, project), self._eval_expr(point.y, project))
        return EvaluatedPoint(
            position=pos,
            bbox=BBox(pos.x, pos.y, pos.x, pos.y),
        )

    def _eval_line(self, line: SketchLineSegment, sketch: Sketch, project: Project) -> EvaluatedLineSegment:
        a = self._point_pos(line.start_point_id, sketch, project)
        b = self._point_pos(line.end_point_id, sketch, project)
        return EvaluatedLineSegment(
            start=a,
            end=b,
            bbox=BBox(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y)),
        )

    def _eval_circle(self, circle: SketchCircle, sketch: Sketch, project: Project) -> EvaluatedCircle:
        c = self._point_pos(circle.center_point_id, sketch, project)
        r = self._eval_expr(circle.radius, project)
        return EvaluatedCircle(
            center=c,
            radius=r,
            bbox=BBox(c.x - r, c.y - r, c.x + r, c.y + r),
        )

    def _eval_arc(self, arc: SketchArc, sketch: Sketch, project: Project) -> EvaluatedArc:
        c = self._point_pos(arc.center_point_id, sketch, project)
        s = self._point_pos(arc.start_point_id, sketch, project)
        e = self._point_pos(arc.end_point_id, sketch, project)
        r = math.hypot(s.x - c.x, s.y - c.y)
        start_angle = math.atan2(s.y - c.y, s.x - c.x)
        end_angle = math.atan2(e.y - c.y, e.x - c.x)
        # Simple bbox: include center, start, end and extreme angles
        pts = [s, e]
        for angle in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2):
            if self._angle_between(start_angle, end_angle, angle):
                pts.append(Vec2(c.x + r * math.cos(angle), c.y + r * math.sin(angle)))
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        return EvaluatedArc(
            center=c,
            radius=r,
            start_angle=start_angle,
            end_angle=end_angle,
            bbox=BBox(min(xs), min(ys), max(xs), max(ys)),
        )

    @staticmethod
    def _angle_between(a1: float, a2: float, target: float) -> bool:
        # Normalize to positive range
        def norm(a: float) -> float:
            while a < 0:
                a += 2 * math.pi
            while a >= 2 * math.pi:
                a -= 2 * math.pi
            return a

        a1, a2, target = norm(a1), norm(a2), norm(target)
        if a1 <= a2:
            return a1 <= target <= a2
        return target >= a1 or target <= a2
