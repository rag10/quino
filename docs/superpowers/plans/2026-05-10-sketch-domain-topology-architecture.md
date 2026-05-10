# Sketch Domain Topology Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the three architectural gaps in the sketch domain: `SketchSpline` stub (spec §12), `SketchDependencyGraph` (spec §23), and `SketchGeometryCache` + `SketchInvalidationController` (spec §24-25).

**Architecture:** The domain already has Sketch, all entity types, constraints, expressions, variables, ParameterMapper, GeometryEvaluator, EvaluatedGeometry, SpatialIndex, domain events, and registries. This plan adds only the three missing pieces: a Spline stub for topology completeness, a dependency graph for incremental recalculation, and a cache layer with invalidation pipeline.

**Tech Stack:** Python 3.11+, dataclasses with `slots=True`, `re` for expression variable parsing, pytest for tests.

---

## File Structure

**New files:**
- `quino/domain/sketch_dependency.py` — `SketchDependencyGraph`: tracks Entity→Parameter and Expression→Variable dependencies
- `quino/services/sketch_cache.py` — `SketchGeometryCache` + `SketchInvalidationController`
- `tests/test_sketch_spline.py` — SketchSpline stub tests
- `tests/test_sketch_dependency.py` — DependencyGraph tests
- `tests/test_sketch_cache.py` — Cache + invalidation tests

**Modified files:**
- `quino/domain/types.py:55-61` — add `SPLINE = "spline"` to `SketchEntityType`
- `quino/domain/model.py:219-231` — add `SketchSpline` dataclass after `SketchInfiniteLine`; widen `Sketch.entities` union to include `SketchSpline`
- `quino/domain/inputs.py:69-74` — add `SketchSplineInput` after `SketchInfiniteLineInput`
- `quino/__init__.py` — export `SketchSpline` and `SketchSplineInput`

---

## Task 1: SketchSpline stub

**Files:**
- Modify: `quino/domain/types.py:55-61`
- Modify: `quino/domain/model.py:219-262`
- Modify: `quino/domain/inputs.py:69-74`
- Modify: `quino/__init__.py`
- Create: `tests/test_sketch_spline.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sketch_spline.py`:

```python
from __future__ import annotations

from quino.domain.inputs import SketchSplineInput
from quino.domain.model import Sketch, SketchSpline
from quino.domain.types import SketchEntityType


def test_sketch_spline_can_be_created() -> None:
    spline = SketchSpline(
        id="s1",
        name="Spline 1",
        type=SketchEntityType.SPLINE,
        control_point_ids=["p1", "p2", "p3"],
    )
    assert spline.id == "s1"
    assert spline.name == "Spline 1"
    assert spline.control_point_ids == ["p1", "p2", "p3"]
    assert spline.construction is False
    assert spline.visible is True
    assert spline.selectable is True


def test_sketch_spline_stored_in_sketch_entities() -> None:
    spline = SketchSpline(
        id="s1",
        name="Spline 1",
        type=SketchEntityType.SPLINE,
        control_point_ids=["p1", "p2"],
    )
    sketch = Sketch(id="sk1", name="Test")
    sketch.entities["s1"] = spline
    assert "s1" in sketch.entities
    assert isinstance(sketch.entities["s1"], SketchSpline)


def test_sketch_spline_input_has_control_point_ids() -> None:
    inp = SketchSplineInput(control_point_ids=["p1", "p2", "p3"])
    assert inp.control_point_ids == ["p1", "p2", "p3"]
    assert inp.name is None


def test_sketch_entity_type_has_spline() -> None:
    assert SketchEntityType.SPLINE == "spline"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_sketch_spline.py -v
```

Expected: FAIL with `ImportError` or `AttributeError` (SketchSpline not defined).

- [ ] **Step 3: Add `SPLINE` to `SketchEntityType` in `quino/domain/types.py`**

In `quino/domain/types.py`, change:

```python
class SketchEntityType(StrEnum):
    POINT = "point"
    LINE_SEGMENT = "line_segment"
    CIRCLE = "circle"
    ARC = "arc"
    INFINITE_LINE = "infinite_line"
```

to:

```python
class SketchEntityType(StrEnum):
    POINT = "point"
    LINE_SEGMENT = "line_segment"
    CIRCLE = "circle"
    ARC = "arc"
    INFINITE_LINE = "infinite_line"
    SPLINE = "spline"
```

- [ ] **Step 4: Add `SketchSpline` dataclass and update `Sketch.entities` union in `quino/domain/model.py`**

After the `SketchInfiniteLine` class (line 230), add:

```python
@dataclass(slots=True)
class SketchSpline:
    id: str
    name: str
    type: SketchEntityType
    control_point_ids: list[str]
    visible: bool = True
    construction: bool = False
    selectable: bool = True
    style: Style = field(default_factory=Style)
    metadata: Metadata = field(default_factory=Metadata)
```

In the `Sketch` class, change `entities` field type from:

```python
    entities: dict[
        str, SketchPoint | SketchLineSegment | SketchCircle | SketchArc | SketchInfiniteLine
    ] = field(default_factory=dict)
```

to:

```python
    entities: dict[
        str, SketchPoint | SketchLineSegment | SketchCircle | SketchArc | SketchInfiniteLine | SketchSpline
    ] = field(default_factory=dict)
```

- [ ] **Step 5: Add `SketchSplineInput` to `quino/domain/inputs.py`**

After the `SketchInfiniteLineInput` class (line 73), add:

```python
@dataclass(slots=True)
class SketchSplineInput:
    control_point_ids: list[str]
    name: str | None = None
```

- [ ] **Step 6: Export `SketchSpline` and `SketchSplineInput` in `quino/__init__.py`**

Add to the `from quino.domain.model import (...)` block:

```python
    SketchSpline,
```

Add to the `from quino.domain.inputs import (...)` block:

```python
    SketchSplineInput,
```

Add both to `__all__`:

```python
    "SketchSpline",
    "SketchSplineInput",
```

- [ ] **Step 7: Run tests to verify they pass**

```
pytest tests/test_sketch_spline.py -v
```

Expected: 4 PASSED.

- [ ] **Step 8: Run full suite to verify no regressions**

```
pytest tests/ -v --tb=short
```

Expected: all existing tests pass.

- [ ] **Step 9: Commit**

```bash
git add quino/domain/types.py quino/domain/model.py quino/domain/inputs.py quino/__init__.py tests/test_sketch_spline.py
git commit -m "feat: add SketchSpline stub (spec §12) — control_point_ids, SPLINE entity type"
```

---

## Task 2: SketchDependencyGraph

**Files:**
- Create: `quino/domain/sketch_dependency.py`
- Create: `tests/test_sketch_dependency.py`

The dependency graph tracks three kinds of edges from the spec (§23):
- `Entity → Parameter` (e.g., a point owns `point_id.x` and `point_id.y`; a line depends on its two points' parameters)
- `Constraint → Parameter` (a constraint depends on parameters of its reference points)
- `Expression → Variable` (an expression string that references named variables)

- [ ] **Step 1: Write failing tests**

Create `tests/test_sketch_dependency.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_sketch_dependency.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'quino.domain.sketch_dependency'`.

- [ ] **Step 3: Implement `SketchDependencyGraph` in `quino/domain/sketch_dependency.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_sketch_dependency.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Run full suite to verify no regressions**

```
pytest tests/ -v --tb=short
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add quino/domain/sketch_dependency.py tests/test_sketch_dependency.py
git commit -m "feat: add SketchDependencyGraph (spec §23) — entity/constraint→parameter, expression→variable"
```

---

## Task 3: SketchGeometryCache + SketchInvalidationController

**Files:**
- Create: `quino/services/sketch_cache.py`
- Create: `tests/test_sketch_cache.py`

The cache implements spec §24 (4 conceptual cache levels collapsed into one practical class: geometry + bbox are co-located in EvaluatedGeometry; spatial index already exists as `SpatialIndex`; expression cache is internal to `ExpressionService`). The controller implements the spec §25 invalidation pipeline: `parameter change → dependency update → geometry invalidation`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_sketch_cache.py`:

```python
from __future__ import annotations

from quino.domain.model import Expression, Sketch, SketchLineSegment, SketchPoint
from quino.domain.sketch_evaluated import BBox, EvaluatedArc, EvaluatedCircle, EvaluatedLineSegment, EvaluatedPoint, Vec2
from quino.domain.types import SketchEntityType
from quino.services.sketch_cache import SketchGeometryCache, SketchInvalidationController


def _ep(x: float = 0.0, y: float = 0.0) -> EvaluatedPoint:
    return EvaluatedPoint(position=Vec2(x, y), bbox=BBox(x, y, x, y))


def _pt(pid: str, x: str = "0", y: str = "0") -> SketchPoint:
    return SketchPoint(id=pid, name=pid, type=SketchEntityType.POINT,
                       x=Expression(x), y=Expression(y))


def _line(lid: str, s: str, e: str) -> SketchLineSegment:
    return SketchLineSegment(id=lid, name=lid, type=SketchEntityType.LINE_SEGMENT,
                             start_point_id=s, end_point_id=e)


# --- SketchGeometryCache ---

def test_cache_miss_returns_none() -> None:
    cache = SketchGeometryCache()
    assert cache.get("p1") is None


def test_cache_hit_returns_stored_geometry() -> None:
    cache = SketchGeometryCache()
    ep = _ep(1.0, 2.0)
    cache.put("p1", ep)
    assert cache.get("p1") is ep


def test_cache_invalidate_removes_single_entry() -> None:
    cache = SketchGeometryCache()
    cache.put("p1", _ep())
    cache.put("p2", _ep())
    cache.invalidate("p1")
    assert cache.get("p1") is None
    assert cache.get("p2") is not None


def test_cache_invalidate_all_clears_every_entry() -> None:
    cache = SketchGeometryCache()
    cache.put("p1", _ep())
    cache.put("p2", _ep())
    cache.invalidate_all()
    assert cache.get("p1") is None
    assert cache.get("p2") is None


def test_cache_overwrite_updates_stored_value() -> None:
    cache = SketchGeometryCache()
    ep1 = _ep(0.0, 0.0)
    ep2 = _ep(5.0, 5.0)
    cache.put("p1", ep1)
    cache.put("p1", ep2)
    assert cache.get("p1") is ep2


# --- SketchInvalidationController ---

def test_controller_invalidates_point_on_parameter_change() -> None:
    cache = SketchGeometryCache()
    sketch = Sketch(id="sk", name="T", entities={"p1": _pt("p1")})
    controller = SketchInvalidationController(cache)
    controller.rebuild(sketch)

    cache.put("p1", _ep())
    controller.on_parameter_changed("p1.x")

    assert cache.get("p1") is None


def test_controller_invalidates_line_when_endpoint_changes() -> None:
    cache = SketchGeometryCache()
    p1, p2 = _pt("p1"), _pt("p2")
    line = _line("l1", "p1", "p2")
    sketch = Sketch(id="sk", name="T", entities={"p1": p1, "p2": p2, "l1": line})
    controller = SketchInvalidationController(cache)
    controller.rebuild(sketch)

    cache.put("p1", _ep())
    cache.put("l1", EvaluatedLineSegment(start=Vec2(0, 0), end=Vec2(10, 0), bbox=BBox(0, 0, 10, 0)))
    controller.on_parameter_changed("p1.y")

    assert cache.get("p1") is None
    assert cache.get("l1") is None


def test_controller_without_rebuild_invalidates_all() -> None:
    cache = SketchGeometryCache()
    cache.put("p1", _ep())
    cache.put("p2", _ep())
    controller = SketchInvalidationController(cache)
    controller.on_parameter_changed("p1.x")
    assert cache.get("p1") is None
    assert cache.get("p2") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_sketch_cache.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'quino.services.sketch_cache'`.

- [ ] **Step 3: Implement `SketchGeometryCache` and `SketchInvalidationController` in `quino/services/sketch_cache.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_sketch_cache.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Run full suite to verify no regressions**

```
pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add quino/services/sketch_cache.py tests/test_sketch_cache.py
git commit -m "feat: add SketchGeometryCache + SketchInvalidationController (spec §24-25)"
```

---

## Self-Review Checklist

**Spec coverage:**
- §4 Sketch root entity — ✅ already in model.py
- §6 SketchEntity base fields — ✅ fields present in each entity (slots prevents inheritance; pattern is correct per Python constraints)
- §8 SketchPoint with Expression x, y — ✅ already in model.py
- §9 SketchLineSegment with start/end_point_id — ✅ already in model.py
- §10 SketchCircle with center_point_id, radius — ✅ already in model.py
- §11 SketchArc with center/start/end_point_id — ✅ already in model.py
- §12 SketchSpline stub — ✅ Task 1
- §13-14 Constraints with ID references — ✅ already in model.py
- §15 Variables — ✅ already in model.py
- §16 Expressions — ✅ already in model.py
- §17-18 ParameterMapper — ✅ already in sketch_evaluator.py
- §19-21 GeometryEvaluator + EvaluatedGeometry — ✅ already in sketch_evaluator.py + sketch_evaluated.py
- §22 BBox on evaluated geometry — ✅ already in sketch_evaluated.py
- §23 Dependency graph — ✅ Task 2
- §24-25 Cache + invalidation — ✅ Task 3
- §27 Ownership (Sketch owns all) — ✅ architectural pattern enforced by ApplicationService
- §28 Lifecycle via ApplicationService — ✅ already in application/service.py
- §30 Serialization (JSON, no caches) — ✅ cache lives only in services, not in model
- §31 Solver integration — ✅ already in sketch_solver.py
- §32 Domain events — ✅ already in sketch_events.py
- §33 Spatial indexing — ✅ already in sketch_spatial.py
- §34 SketchAnalysis + SketchState — ✅ already in model.py + types.py
- §35 Registries — ✅ already in sketch_registries.py

**No placeholders found.**

**Type consistency:** `SketchSpline` used in `sketch_dependency.py` (Task 2) matches definition from Task 1. `SketchDependencyGraph` imported in `sketch_cache.py` (Task 3) matches definition from Task 2. All parameter keys follow `"{entity_id}.x"` / `"{entity_id}.y"` / `"{entity_id}.radius"` convention consistent with `ParameterMapper.build()` in `sketch_evaluator.py`.
