from __future__ import annotations

import re
from dataclasses import dataclass, field

from quino.domain.model import (
    Sketch,
    SketchArc,
    SketchCircle,
    SketchConstraint,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
    SketchSpline,
)

_MATH_BUILTINS: frozenset[str] = frozenset(
    {"sin", "cos", "tan", "abs", "pi", "sqrt", "log", "exp", "asin", "acos", "atan", "atan2"}
)

SketchEntity = SketchPoint | SketchLineSegment | SketchCircle | SketchArc | SketchInfiniteLine | SketchSpline


@dataclass(slots=True)
class SketchDependencyGraph:
    """
    Dependency graph for a Sketch: tracks which parameters each entity and
    constraint depends on, and the reverse mapping (parameter → entities).

    Spec §23: Entity→Parameter, Constraint→Parameter, Expression→Variable.
    """

    _entity_params: dict[str, list[str]] = field(default_factory=dict)
    _constraint_params: dict[str, list[str]] = field(default_factory=dict)
    _param_entities: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, sketch: Sketch) -> SketchDependencyGraph:
        g = cls()
        for entity_id, entity in sketch.entities.items():
            params = cls._params_for_entity(entity_id, entity)
            g._entity_params[entity_id] = params
            for param in params:
                g._param_entities.setdefault(param, []).append(entity_id)
        for constraint_id, constraint in sketch.constraints.items():
            params = cls._params_for_constraint(constraint)
            g._constraint_params[constraint_id] = params
        return g

    def parameters_for(self, entity_id: str) -> list[str]:
        return list(self._entity_params.get(entity_id, []))

    def parameters_for_constraint(self, constraint_id: str) -> list[str]:
        return list(self._constraint_params.get(constraint_id, []))

    def entities_for_parameter(self, param_key: str) -> list[str]:
        return list(self._param_entities.get(param_key, []))

    @staticmethod
    def variables_for_expression(expr_text: str) -> list[str]:
        tokens = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', expr_text)
        return [t for t in tokens if t not in _MATH_BUILTINS]

    @staticmethod
    def _params_for_entity(entity_id: str, entity: SketchEntity) -> list[str]:
        if isinstance(entity, SketchPoint):
            return [f"{entity_id}.x", f"{entity_id}.y"]
        if isinstance(entity, SketchLineSegment):
            return [
                f"{entity.start_point_id}.x", f"{entity.start_point_id}.y",
                f"{entity.end_point_id}.x", f"{entity.end_point_id}.y",
            ]
        if isinstance(entity, SketchCircle):
            return [
                f"{entity.center_point_id}.x", f"{entity.center_point_id}.y",
                f"{entity_id}.radius",
            ]
        if isinstance(entity, SketchArc):
            return [
                f"{entity.center_point_id}.x", f"{entity.center_point_id}.y",
                f"{entity.start_point_id}.x", f"{entity.start_point_id}.y",
                f"{entity.end_point_id}.x", f"{entity.end_point_id}.y",
            ]
        if isinstance(entity, SketchInfiniteLine):
            return [
                f"{entity.point_a_id}.x", f"{entity.point_a_id}.y",
                f"{entity.point_b_id}.x", f"{entity.point_b_id}.y",
            ]
        if isinstance(entity, SketchSpline):
            params: list[str] = []
            for pid in entity.control_point_ids:
                params.extend([f"{pid}.x", f"{pid}.y"])
            return params
        return []

    @staticmethod
    def _params_for_constraint(constraint: SketchConstraint) -> list[str]:
        params: list[str] = []
        for point_id in constraint.references:
            params.extend([f"{point_id}.x", f"{point_id}.y"])
        return params
