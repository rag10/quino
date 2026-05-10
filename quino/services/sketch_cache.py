from __future__ import annotations

from quino.domain.model import Sketch
from quino.domain.sketch_dependency import SketchDependencyGraph
from quino.domain.sketch_evaluated import EvaluatedArc, EvaluatedCircle, EvaluatedLineSegment, EvaluatedPoint

EvaluatedGeometry = EvaluatedPoint | EvaluatedLineSegment | EvaluatedCircle | EvaluatedArc


class SketchGeometryCache:
    """
    Geometry cache level from spec §24. Stores EvaluatedGeometry (which
    already embeds BBox) keyed by entity_id. Thread-unsafe by design —
    the sketch domain is single-threaded.
    """

    def __init__(self) -> None:
        self._store: dict[str, EvaluatedGeometry] = {}

    def get(self, entity_id: str) -> EvaluatedGeometry | None:
        return self._store.get(entity_id)

    def put(self, entity_id: str, geometry: EvaluatedGeometry) -> None:
        self._store[entity_id] = geometry

    def invalidate(self, entity_id: str) -> None:
        self._store.pop(entity_id, None)

    def invalidate_all(self) -> None:
        self._store.clear()


class SketchInvalidationController:
    """
    Implements the spec §25 invalidation pipeline:
      parameter change → dependency lookup → geometry cache invalidation.

    Call rebuild(sketch) after every structural change to the sketch.
    Call on_parameter_changed(param_key) when a solver or UI mutates a
    parameter value (e.g. "p1.x", "circ1.radius").
    """

    def __init__(self, cache: SketchGeometryCache) -> None:
        self._cache = cache
        self._dep_graph: SketchDependencyGraph | None = None

    def rebuild(self, sketch: Sketch) -> None:
        self._dep_graph = SketchDependencyGraph.build(sketch)

    def on_parameter_changed(self, param_key: str) -> None:
        if self._dep_graph is None:
            self._cache.invalidate_all()
            return
        for entity_id in self._dep_graph.entities_for_parameter(param_key):
            self._cache.invalidate(entity_id)
