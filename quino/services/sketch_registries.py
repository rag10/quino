from __future__ import annotations

from collections.abc import Callable
from typing import Any

from quino.domain.model import SketchConstraint, SketchEntityType
from quino.domain.sketch_evaluated import EvaluatedArc, EvaluatedCircle, EvaluatedLineSegment, EvaluatedPoint


class EntityRegistry:
    """Dynamic registry for sketch entity constructors."""

    def __init__(self) -> None:
        self._factories: dict[SketchEntityType, Callable[..., Any]] = {}

    def register(self, entity_type: SketchEntityType, factory: Callable[..., Any]) -> None:
        self._factories[entity_type] = factory

    def create(self, entity_type: SketchEntityType, **kwargs: Any) -> Any:
        factory = self._factories.get(entity_type)
        if factory is None:
            raise ValueError(f"No factory registered for entity type: {entity_type}")
        return factory(**kwargs)


class ConstraintRegistry:
    """Dynamic registry for sketch constraint constructors."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., SketchConstraint]] = {}

    def register(self, constraint_type: str, factory: Callable[..., SketchConstraint]) -> None:
        self._factories[constraint_type] = factory

    def create(self, constraint_type: str, **kwargs: Any) -> SketchConstraint:
        factory = self._factories.get(constraint_type)
        if factory is None:
            raise ValueError(f"No factory registered for constraint type: {constraint_type}")
        return factory(**kwargs)


class GeometryEvaluatorRegistry:
    """Dynamic registry for geometry evaluators per entity type."""

    def __init__(self) -> None:
        self._evaluators: dict[SketchEntityType, Callable[..., Any]] = {}

    def register(self, entity_type: SketchEntityType, evaluator: Callable[..., Any]) -> None:
        self._evaluators[entity_type] = evaluator

    def evaluate(self, entity_type: SketchEntityType, **kwargs: Any) -> Any:
        evaluator = self._evaluators.get(entity_type)
        if evaluator is None:
            raise ValueError(f"No evaluator registered for entity type: {entity_type}")
        return evaluator(**kwargs)
