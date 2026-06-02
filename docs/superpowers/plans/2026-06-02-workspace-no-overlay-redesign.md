# Workspace sin overlays — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar los overlays del case-as-model (cascadeo por comparación directa de valores), unificar Run dentro de Analysis, introducir métricas como funciones Python, y adaptar la GUI; schema 0.4.0.

**Architecture:** El modelo de cada `Case` es la única fuente de verdad. El motor de cascadeo (`case_cascading.py`) decide propagar una edición al hijo comparando el valor actual del hijo contra el valor previo del padre. `Analysis` absorbe el estado de ejecución (run aplanado) y una lista de `Metric` (código Python evaluado con exec restringido). La GUI se adapta: árbol reestructurado, combobox con flecha, expansión solo por triángulo, resaltado del caso activo.

**Tech Stack:** Python 3.11+ (dataclasses slots), PySide6, pytest, numpy. Solver Solvespace y Exudyn intactos.

**Spec:** `docs/superpowers/specs/2026-06-02-workspace-no-overlay-redesign-design.md`

---

## Convenciones de este plan

- Tests: `pytest tests/ -q`. GUI: requiere `QT_QPA_PLATFORM=offscreen` (en Windows PowerShell: `$env:QT_QPA_PLATFORM='offscreen'; pytest ...`).
- Cada tarea termina en commit. Mensajes en español, terminando con la línea Co-Authored-By estándar del repo.
- Rama de trabajo: `redesign/case-as-model` (ya activa). No hace falta crear rama.
- Reutilizar `_entity_lookup` (hoy en `case_overlay_validator.py`) reubicándolo en un módulo nuevo `quino/services/case_entities.py` antes de borrar el validador.

---

# FASE 1 — Dominio + motor de cascadeo sin overlays

## Task 1.1: Reubicar `_entity_lookup` a un módulo propio

`case_diff.py` y `case_cascading.py` importan `_entity_lookup` desde `case_overlay_validator`, que vamos a borrar. Lo movemos primero a `quino/services/case_entities.py` para no romper imports.

**Files:**
- Create: `quino/services/case_entities.py`
- Test: `tests/test_case_entities.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_case_entities.py
from quino.domain.model import Body, Marker, Model
from quino.domain.types import BodyType, MarkerType
from quino.domain.workspace import Case
from quino.services.case_entities import entity_lookup


def _case_with_body() -> Case:
    marker = Marker(id="mk1", name="tip", type=MarkerType.STRUCTURAL, x=1.0, y=0.0)
    body = Body(id="b1", name="bar", type=BodyType.BAR, markers=[marker])
    model = Model(bodies=[body])
    return Case(id="c1", name="root", model=model)


def test_entity_lookup_includes_body_and_structural_marker():
    case = _case_with_body()
    lookup = entity_lookup(case)
    assert "b1" in lookup
    assert "mk1" in lookup
    assert lookup["b1"][1] is Body
    assert lookup["mk1"][1] is Marker
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_case_entities.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quino.services.case_entities'`

- [ ] **Step 3: Write the implementation**

```python
# quino/services/case_entities.py
"""Single source of truth for enumerating the entities of a case's model.

Maps entity id -> (entity, class) for bodies, structural markers, joints,
sliders, drivers, loads, sensors, springs and block instances. Replaces the
copy that used to live in case_overlay_validator (now deleted).
"""
from __future__ import annotations

from quino.domain.types import MarkerType
from quino.domain.workspace import Case


def entity_lookup(case: Case) -> dict[str, tuple[object, type]]:
    """Map id -> (entity, cls) for everything in the case's model."""
    out: dict[str, tuple[object, type]] = {}
    m = case.model
    for body in m.bodies:
        out[body.id] = (body, type(body))
        for marker in body.markers:
            if marker.type is MarkerType.STRUCTURAL:
                out[marker.id] = (marker, type(marker))
    for joint in m.joints:
        out[joint.id] = (joint, type(joint))
    for slider in m.sliders:
        out[slider.id] = (slider, type(slider))
    for driver in m.drivers:
        out[driver.id] = (driver, type(driver))
    for load in m.loads:
        out[load.id] = (load, type(load))
    for sensor in m.sensors:
        out[sensor.id] = (sensor, type(sensor))
    for spring in m.springs:
        out[spring.id] = (spring, type(spring))
    if getattr(m, "control_graph", None) is not None:
        for inst in m.control_graph.instances.values():
            out[inst.instance_id] = (inst, type(inst))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_case_entities.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/services/case_entities.py tests/test_case_entities.py
git commit -m "refactor: extraer entity_lookup a case_entities (antes en overlay validator)"
```

---

## Task 1.2: Redirigir `case_diff.py` al nuevo `entity_lookup`

**Files:**
- Modify: `quino/services/case_diff.py:27`

- [ ] **Step 1: Update the import**

En `quino/services/case_diff.py`, reemplazar:

```python
from quino.services.case_overlay_validator import _entity_lookup
```

por:

```python
from quino.services.case_entities import entity_lookup as _entity_lookup
```

- [ ] **Step 2: Run the existing diff tests**

Run: `pytest tests/test_case_diff.py -q`
Expected: PASS (sin cambios de comportamiento)

- [ ] **Step 3: Commit**

```bash
git add quino/services/case_diff.py
git commit -m "refactor: case_diff usa entity_lookup de case_entities"
```

---

## Task 1.3: Nuevo dominio `Metric` / `MetricResult`

**Files:**
- Modify: `quino/domain/workspace.py` (añadir dataclasses tras `MetricDefinition`; no borrar nada todavía)
- Test: `tests/test_metric_domain.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metric_domain.py
from quino.domain.workspace import Metric, MetricResult


def test_metric_defaults():
    m = Metric(id="mt1", name="Final pos")
    assert m.value_type == "float"
    assert m.code == ""
    assert m.result is None


def test_metric_result_fields():
    r = MetricResult(value=12.3, status="ok")
    assert r.value == 12.3
    assert r.status == "ok"
    assert r.error == ""
    assert r.evaluated_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_metric_domain.py -v`
Expected: FAIL with `ImportError: cannot import name 'Metric'`

- [ ] **Step 3: Add the dataclasses**

En `quino/domain/workspace.py`, tras la clase `MetricDefinition`, añadir:

```python
@dataclass(slots=True)
class MetricResult:
    value: Any
    status: str  # "ok" | "error" | "no_data"
    error: str = ""
    evaluated_at: str | None = None


@dataclass(slots=True)
class Metric:
    id: str
    name: str
    description: str = ""
    value_type: str = "float"  # "float" | "bool" | "int" | "str"
    code: str = ""             # body of eval(data, meta), must `return`
    result: MetricResult | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_metric_domain.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/domain/workspace.py tests/test_metric_domain.py
git commit -m "feat(domain): Metric y MetricResult (métricas Python)"
```

---

## Task 1.4: `Analysis` con estado de run aplanado y `metrics`

Aplanamos los campos de `Run` dentro de `Analysis` y le añadimos `metrics: list[Metric]`. `Run` y `Case.runs` siguen existiendo temporalmente para no romper todo a la vez; se borran en Task 1.10.

**Files:**
- Modify: `quino/domain/workspace.py` (clase `Analysis`)
- Test: `tests/test_analysis_runstate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analysis_runstate.py
from quino.domain.workspace import Analysis, Metric


def test_analysis_has_flattened_run_state():
    a = Analysis(id="an1", name="Dyn", analysis_type="dynamic")
    assert a.status == "to_be_run"
    assert a.finished_at is None
    assert a.artifacts == []
    assert a.warnings == []
    assert a.error_message == ""
    assert a.metrics == []


def test_analysis_accepts_metrics():
    a = Analysis(id="an1", name="Dyn", metrics=[Metric(id="m", name="x")])
    assert a.metrics[0].id == "m"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_runstate.py -v`
Expected: FAIL with `AttributeError` / `TypeError` (campos inexistentes)

- [ ] **Step 3: Extend the `Analysis` dataclass**

En `quino/domain/workspace.py`, reemplazar la clase `Analysis` por:

```python
@dataclass(slots=True)
class Analysis:
    id: str
    name: str
    analysis_type: str = "dynamic"
    pose_id: str | None = None
    config: AnalysisConfig = field(default=None)  # type: ignore[assignment]
    metrics: list[Metric] = field(default_factory=list)

    # --- run state (flattened; formerly the Run entity) ---
    status: str = "to_be_run"  # to_be_run|queued|running|ok|partial|failed|stale
    created_at: str | None = None
    finished_at: str | None = None
    result_ref: "ResultRef | None" = None
    artifacts: list["ArtifactRef"] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_message: str = ""
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.config is None:
            ctor = _DEFAULT_ANALYSIS_CONFIG.get(self.analysis_type)
            if ctor is None:
                raise ValueError(f"Unknown analysis_type {self.analysis_type!r}")
            self.config = ctor()
        if self.status not in _RUN_STATUSES:
            raise ValueError(f"Analysis status {self.status!r} is not allowed")
```

**Nota:** `Analysis` ahora referencia `ResultRef`, `ArtifactRef` y `_RUN_STATUSES`, que están definidos MÁS ABAJO en el archivo (sección "Run artifacts"). Mover el bloque `ResultRef` / `ArtifactRef` / `_RUN_STATUSES` para que quede ANTES de la clase `Analysis`. Las anotaciones usan string forward-ref por seguridad, pero el orden debe permitir la resolución en runtime de `_RUN_STATUSES` y `_DEFAULT_ANALYSIS_CONFIG`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_runstate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/domain/workspace.py tests/test_analysis_runstate.py
git commit -m "feat(domain): Analysis con estado de run aplanado y lista de metrics"
```

---

## Task 1.5: Función pura de cascadeo de propiedad por valor previo

Antes de reescribir el motor entero, escribimos y testeamos la decisión núcleo como función pura: dado `old_parent_value` y `child_value`, ¿se cascadea?

**Files:**
- Create: `quino/services/cascade_rules.py`
- Test: `tests/test_cascade_rules.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cascade_rules.py
from quino.services.cascade_rules import should_cascade_value


def test_cascades_when_child_matches_old_parent():
    assert should_cascade_value(old_parent=5, child=5) is True


def test_does_not_cascade_when_child_diverges():
    assert should_cascade_value(old_parent=5, child=2) is False


def test_cascades_for_equal_expression_objects():
    class Expr:
        def __init__(self, e): self.e = e
        def __eq__(self, other): return isinstance(other, Expr) and self.e == other.e
    assert should_cascade_value(old_parent=Expr("9.81"), child=Expr("9.81")) is True
    assert should_cascade_value(old_parent=Expr("9.81"), child=Expr("0")) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cascade_rules.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# quino/services/cascade_rules.py
"""Pure decision rules for value-based cascading (no overlays).

A parent edit cascades to a child only when the child still held the value the
parent had *before* the edit — i.e. the child was tracking the parent. If the
child already diverged, it owns a local override and is left untouched.
"""
from __future__ import annotations


def should_cascade_value(*, old_parent: object, child: object) -> bool:
    """True if the child was tracking the parent (child == old parent value)."""
    try:
        return bool(child == old_parent)
    except Exception:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cascade_rules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/services/cascade_rules.py tests/test_cascade_rules.py
git commit -m "feat(cascade): regla pura should_cascade_value (valor previo del padre)"
```

---

## Task 1.6: Reescribir `CascadingEngine.edit_property` sin overlay

**Files:**
- Modify: `quino/services/case_cascading.py` (reescritura — esta tarea solo `edit_property` + helpers de modelo)
- Test: `tests/test_cascading_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cascading_edit.py
import copy

from quino.domain.model import Body, Model, ScalarProperty
from quino.domain.types import BodyType
from quino.domain.workspace import Case, Workspace
from quino.services.case_cascading import CascadingEngine


def _ws_with_parent_child():
    body = Body(id="b1", name="bar", type=BodyType.BAR, mass=ScalarProperty("5 kg"))
    parent = Case(id="p", name="parent", model=Model(bodies=[copy.deepcopy(body)]))
    child = Case(id="c", name="child", parent_case_id="p",
                 model=Model(bodies=[copy.deepcopy(body)]))
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   root_case_ids=["p"], cases={"p": parent, "c": child})
    return ws


def test_edit_cascades_to_tracking_child():
    ws = _ws_with_parent_child()
    engine = CascadingEngine(ws)
    engine.edit_property("p", "b1", "mass", ScalarProperty("8 kg"))
    assert ws.cases["c"].model.bodies[0].mass == ScalarProperty("8 kg")


def test_edit_does_not_cascade_to_diverged_child():
    ws = _ws_with_parent_child()
    # child diverges first
    ws.cases["c"].model.bodies[0].mass = ScalarProperty("2 kg")
    engine = CascadingEngine(ws)
    engine.edit_property("p", "b1", "mass", ScalarProperty("8 kg"))
    assert ws.cases["c"].model.bodies[0].mass == ScalarProperty("2 kg")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cascading_edit.py -v`
Expected: FAIL (la firma actual usa overlays / comportamiento distinto)

- [ ] **Step 3: Rewrite `case_cascading.py` (edit + model helpers)**

Reemplazar el contenido de `quino/services/case_cascading.py` por la base sin overlay. (Las operaciones add/remove/connection se completan en tareas 1.7–1.8; aquí dejamos sus métodos como stubs que se rellenan luego, pero `edit_property` ya funciona.)

```python
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field

from quino.domain.blocks import BlockDiagram, Connection
from quino.domain.workspace import Analysis, Case, Workspace, create_default_pose
from quino.services.case_entities import entity_lookup
from quino.services.cascade_property_category import is_model_affecting
from quino.services.cascade_rules import should_cascade_value
from quino.services.run_invalidation import mark_runs_stale_for_case

_DOMAIN_LIST_ACCESSORS = {
    "bodies": lambda m: m.bodies,
    "joints": lambda m: m.joints,
    "sliders": lambda m: m.sliders,
    "drivers": lambda m: m.drivers,
    "loads": lambda m: m.loads,
    "sensors": lambda m: m.sensors,
    "springs": lambda m: m.springs,
}

# Topology / identity fields never flow through edit_property.
_SKIP_PROPS = {"id", "markers", "edge_order"}

ConnectionKey = tuple[str, str, str, str]


@dataclass(slots=True)
class OperationResult:
    modified_case_ids: set[str] = field(default_factory=set)
    stale_case_ids: set[str] = field(default_factory=set)
    applied_changes: list[str] = field(default_factory=list)

    def merge(self, other: "OperationResult") -> None:
        self.modified_case_ids.update(other.modified_case_ids)
        self.stale_case_ids.update(other.stale_case_ids)
        self.applied_changes.extend(other.applied_changes)


def _new_case_id() -> str:
    return f"case-{uuid.uuid4().hex[:8]}"


def _new_pose_id() -> str:
    return f"pose-{uuid.uuid4().hex[:8]}"


def _new_analysis_id() -> str:
    return f"analysis-{uuid.uuid4().hex[:8]}"


def _entity_id(entity: object) -> str:
    ent_id = getattr(entity, "id", None) or getattr(entity, "instance_id", None)
    if ent_id is None:
        raise ValueError(f"Entity {entity!r} has no stable id")
    return str(ent_id)


def _connection_key(conn: Connection) -> ConnectionKey:
    return (conn.src_instance, conn.src_port, conn.dst_instance, conn.dst_port)


class CascadingEngine:
    """Value-based cascading engine. No overlays.

    Mutations to a case model flow to descendants that still track the parent
    value (child == old parent value). Diverged children keep their override.
    """

    def __init__(self, workspace: Workspace) -> None:
        self._ws = workspace

    # ------------------------------------------------------------- properties

    def edit_property(self, case_id: str, entity_id: str, prop: str, new_value: object) -> OperationResult:
        if prop in _SKIP_PROPS:
            raise ValueError(f"Property {prop!r} is structural and cannot be edited via cascade")
        result = OperationResult()
        case = self._ws.cases[case_id]
        entity = self._find_entity(case, entity_id)
        if entity is None:
            raise KeyError(f"Entity {entity_id!r} not found in case {case_id!r}")

        old_value = copy.deepcopy(self._get_property(entity, prop))
        self._set_property(entity, prop, copy.deepcopy(new_value))
        self._mark_modified(result, case_id, model_affecting=is_model_affecting(prop))
        result.applied_changes.append(f"{case_id}:{entity_id}/{prop}")

        for child_id in self._direct_children(case_id):
            self._propagate_edit(child_id, entity_id, prop, old_value, new_value, result)

        self._apply_staleness(result, f"model property changed: {entity_id}/{prop}")
        return result

    def _propagate_edit(self, case_id, entity_id, prop, old_value, new_value, result) -> None:
        case = self._ws.cases[case_id]
        entity = self._find_entity(case, entity_id)
        if entity is None:
            return  # entity deleted in this branch; stop
        child_value = self._get_property(entity, prop)
        if not should_cascade_value(old_parent=old_value, child=child_value):
            return  # override here is the ceiling for this branch
        self._set_property(entity, prop, copy.deepcopy(new_value))
        self._mark_modified(result, case_id, model_affecting=is_model_affecting(prop))
        result.applied_changes.append(f"{case_id}:{entity_id}/{prop}")
        for gc_id in self._direct_children(case_id):
            self._propagate_edit(gc_id, entity_id, prop, old_value, new_value, result)

    # ---------------------------------------------------------------- helpers

    def _find_entity(self, case: Case, entity_id: str) -> object | None:
        entry = entity_lookup(case).get(entity_id)
        return entry[0] if entry is not None else None

    def _direct_children(self, case_id: str) -> list[str]:
        return [c.id for c in self._ws.cases.values() if c.parent_case_id == case_id]

    def _all_descendants(self, case_id: str) -> set[str]:
        out: set[str] = set()
        frontier = list(self._direct_children(case_id))
        while frontier:
            current = frontier.pop()
            if current in out:
                continue
            out.add(current)
            frontier.extend(self._direct_children(current))
        return out

    def _get_property(self, entity: object, path: str) -> object:
        target: object = entity
        for part in path.split("."):
            target = target.get(part) if isinstance(target, dict) else getattr(target, part)
        return target

    def _set_property(self, entity: object, path: str, value: object) -> None:
        parts = path.split(".")
        if len(parts) == 1:
            setattr(entity, path, value)
            return
        target: object = entity
        for part in parts[:-1]:
            target = target.setdefault(part, {}) if isinstance(target, dict) else getattr(target, part)
        leaf = parts[-1]
        if isinstance(target, dict):
            target[leaf] = value
        else:
            setattr(target, leaf, value)

    def _mark_modified(self, result: OperationResult, case_id: str, *, model_affecting: bool) -> None:
        result.modified_case_ids.add(case_id)
        if model_affecting:
            result.stale_case_ids.add(case_id)

    def _apply_staleness(self, result: OperationResult, reason: str) -> None:
        for case_id in result.stale_case_ids:
            case = self._ws.cases.get(case_id)
            if case is not None:
                mark_runs_stale_for_case(case, reason=reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cascading_edit.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/services/case_cascading.py tests/test_cascading_edit.py
git commit -m "feat(cascade): edit_property por comparación de valor previo (sin overlay)"
```

---

## Task 1.7: `add_entity` y `remove_entity` por valor

**Files:**
- Modify: `quino/services/case_cascading.py` (añadir métodos)
- Test: `tests/test_cascading_add_remove.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cascading_add_remove.py
import copy

from quino.domain.model import Body, Model
from quino.domain.types import BodyType
from quino.domain.workspace import Case, Workspace
from quino.services.case_cascading import CascadingEngine


def _ws():
    parent = Case(id="p", name="parent", model=Model())
    child = Case(id="c", name="child", parent_case_id="p", model=Model())
    gchild = Case(id="g", name="g", parent_case_id="c", model=Model())
    return Workspace(id="w", name="w", schema_version="0.4.0",
                     root_case_ids=["p"], cases={"p": parent, "c": child, "g": gchild})


def test_add_entity_cascades_to_all_descendants():
    ws = _ws()
    engine = CascadingEngine(ws)
    body = Body(id="b1", name="bar", type=BodyType.BAR)
    engine.add_entity("p", body, "bodies")
    assert any(b.id == "b1" for b in ws.cases["c"].model.bodies)
    assert any(b.id == "b1" for b in ws.cases["g"].model.bodies)


def test_remove_entity_cascades_when_value_identical():
    ws = _ws()
    body = Body(id="b1", name="bar", type=BodyType.BAR)
    for cid in ("p", "c", "g"):
        ws.cases[cid].model.bodies.append(copy.deepcopy(body))
    engine = CascadingEngine(ws)
    engine.remove_entity("p", "b1")
    assert all(not c.model.bodies for c in ws.cases.values())


def test_remove_entity_keeps_diverged_child():
    ws = _ws()
    body = Body(id="b1", name="bar", type=BodyType.BAR)
    for cid in ("p", "c"):
        ws.cases[cid].model.bodies.append(copy.deepcopy(body))
    # child diverges
    ws.cases["c"].model.bodies[0].name = "renamed"
    engine = CascadingEngine(ws)
    engine.remove_entity("p", "b1")
    assert not ws.cases["p"].model.bodies
    assert ws.cases["c"].model.bodies and ws.cases["c"].model.bodies[0].name == "renamed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cascading_add_remove.py -v`
Expected: FAIL with `AttributeError: 'CascadingEngine' object has no attribute 'add_entity'`

- [ ] **Step 3: Add the methods to `CascadingEngine`**

Añadir dentro de la clase `CascadingEngine` (en `case_cascading.py`):

```python
    # --------------------------------------------------------------- entities

    def add_entity(self, case_id: str, entity: object, domain: str) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        self._append_entity_to_model(case, entity, domain)
        ent_id = _entity_id(entity)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:add:{domain}/{ent_id}")
        for child_id in self._direct_children(case_id):
            self._propagate_add(child_id, entity, domain, result)
        self._apply_staleness(result, f"model entity added: {domain}/{ent_id}")
        return result

    def _propagate_add(self, case_id: str, entity: object, domain: str, result: OperationResult) -> None:
        case = self._ws.cases[case_id]
        ent_id = _entity_id(entity)
        if self._find_entity(case, ent_id) is not None:
            # already present (added independently); stop this branch
            return
        if self._missing_dependencies(entity, case):
            return  # cannot place entity without its referenced ids
        cloned = copy.deepcopy(entity)
        self._append_entity_to_model(case, cloned, domain)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:add:{domain}/{ent_id}")
        for gc_id in self._direct_children(case_id):
            self._propagate_add(gc_id, entity, domain, result)

    def remove_entity(self, case_id: str, entity_id: str) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        if self._find_entity(case, entity_id) is None:
            return result
        closure = self._collect_removal_closure(case, {entity_id})
        snapshot = {rid: copy.deepcopy(self._find_entity(case, rid)) for rid in closure
                    if self._find_entity(case, rid) is not None}
        for rid in closure:
            self._remove_entity_from_model(case, rid)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:remove:{','.join(sorted(closure))}")
        for child_id in self._direct_children(case_id):
            self._propagate_remove(child_id, snapshot, result)
        self._apply_staleness(result, f"model entity removed: {entity_id}")
        return result

    def _propagate_remove(self, case_id: str, snapshot: dict[str, object], result: OperationResult) -> None:
        case = self._ws.cases[case_id]
        removable: set[str] = set()
        for rid, parent_ent in snapshot.items():
            child_ent = self._find_entity(case, rid)
            if child_ent is None:
                continue
            if child_ent == parent_ent:
                removable.add(rid)
            # else: child diverged -> keep it, stop cascading this id
        if not removable:
            return
        closure = self._collect_removal_closure(case, removable)
        for rid in closure:
            self._remove_entity_from_model(case, rid)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:remove:{','.join(sorted(closure))}")
        for gc_id in self._direct_children(case_id):
            self._propagate_remove(gc_id, snapshot, result)

    def _append_entity_to_model(self, case: Case, entity: object, domain: str) -> None:
        if domain == "blocks":
            self._ensure_diagram(case).instances[_entity_id(entity)] = entity  # type: ignore[assignment]
            return
        accessor = _DOMAIN_LIST_ACCESSORS.get(domain)
        if accessor is None:
            raise ValueError(f"Unknown domain {domain!r}")
        accessor(case.model).append(entity)

    def _ensure_diagram(self, case: Case) -> BlockDiagram:
        if case.model.control_graph is None:
            case.model.control_graph = BlockDiagram()
        return case.model.control_graph

    def _collect_removal_closure(self, case: Case, initial_ids: set[str]) -> set[str]:
        pending = set(initial_ids)
        result = set(initial_ids)
        while pending:
            current = pending.pop()
            new = self._dependent_ids(case, current) - result
            result.update(new)
            pending.update(new)
        return result

    def _dependent_ids(self, case: Case, entity_id: str) -> set[str]:
        m = case.model
        ids = {entity_id}
        for body in m.bodies:
            if body.id == entity_id:
                ids.update(marker.id for marker in body.markers)
        out: set[str] = set()
        for joint in m.joints:
            if any(ep.body_id in ids or ep.marker_id in ids or ep.slider_id in ids
                   for ep in (joint.endpoint_a, joint.endpoint_b)):
                out.add(joint.id)
        for driver in m.drivers:
            if driver.target_joint_id in ids:
                out.add(driver.id)
        for load in m.loads:
            if load.target_marker_id in ids:
                out.add(load.id)
        for sensor in m.sensors:
            if any(mid in ids for mid in sensor.marker_ids):
                out.add(sensor.id)
        for spring in m.springs:
            if any(ep.body_id in ids or ep.marker_id in ids
                   for ep in (spring.endpoint_a, spring.endpoint_b)):
                out.add(spring.id)
        return out

    def _remove_entity_from_model(self, case: Case, entity_id: str) -> None:
        m = case.model
        m.bodies[:] = [b for b in m.bodies if b.id != entity_id]
        for body in m.bodies:
            body.markers[:] = [mk for mk in body.markers if mk.id != entity_id]
            body.edge_order[:] = [mid for mid in body.edge_order if mid != entity_id]
        m.joints[:] = [j for j in m.joints if j.id != entity_id]
        m.sliders[:] = [s for s in m.sliders if s.id != entity_id]
        m.drivers[:] = [d for d in m.drivers if d.id != entity_id]
        m.loads[:] = [l for l in m.loads if l.id != entity_id]
        m.sensors[:] = [s for s in m.sensors if s.id != entity_id]
        m.springs[:] = [sp for sp in m.springs if sp.id != entity_id]
        if m.control_graph is not None:
            m.control_graph.instances.pop(entity_id, None)
            object.__setattr__(m.control_graph, "connections",
                               [c for c in m.control_graph.connections
                                if c.src_instance != entity_id and c.dst_instance != entity_id])

    def _missing_dependencies(self, entity: object, case: Case) -> set[str]:
        ids = set(entity_lookup(case).keys())
        missing: set[str] = set()
        if hasattr(entity, "endpoint_a") and hasattr(entity, "endpoint_b"):
            for ep in (entity.endpoint_a, entity.endpoint_b):
                for attr in ("body_id", "marker_id", "slider_id"):
                    ref = getattr(ep, attr, None)
                    if ref is not None and ref not in ids:
                        missing.add(ref)
        if hasattr(entity, "target_joint_id") and entity.target_joint_id not in ids:
            missing.add(entity.target_joint_id)
        if hasattr(entity, "target_marker_id") and entity.target_marker_id not in ids:
            missing.add(entity.target_marker_id)
        if hasattr(entity, "marker_ids"):
            missing.update(ref for ref in entity.marker_ids if ref not in ids)
        return missing
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cascading_add_remove.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/services/case_cascading.py tests/test_cascading_add_remove.py
git commit -m "feat(cascade): add_entity/remove_entity por valor (sin overlay)"
```

---

## Task 1.8: Conexiones de bloques y `fork_case` / `duplicate_case` sin overlay

**Files:**
- Modify: `quino/services/case_cascading.py`
- Test: `tests/test_cascading_fork_connections.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cascading_fork_connections.py
from quino.domain.model import Body, Model
from quino.domain.types import BodyType
from quino.domain.workspace import Analysis, Case, Workspace, create_default_pose
from quino.services.case_cascading import CascadingEngine


def _ws_single_root():
    body = Body(id="b1", name="bar", type=BodyType.BAR)
    root = Case(id="p", name="root", model=Model(bodies=[body]),
                poses=[create_default_pose("pose-def")],
                analyses=[Analysis(id="an1", name="Dyn", pose_id="pose-def")])
    return Workspace(id="w", name="w", schema_version="0.4.0",
                     root_case_ids=["p"], cases={"p": root})


def test_fork_copies_model_and_poses_without_run_state():
    ws = _ws_single_root()
    # give the parent analysis a fake completed state
    ws.cases["p"].analyses[0].status = "ok"
    engine = CascadingEngine(ws)
    new_id = engine.fork_case("p", "child")
    child = ws.cases[new_id]
    assert child.parent_case_id == "p"
    assert [b.id for b in child.model.bodies] == ["b1"]
    # analyses copied but run state reset
    assert child.analyses and child.analyses[0].status == "to_be_run"
    # ids regenerated
    assert child.analyses[0].id != "an1"
    assert not hasattr(child, "overlay") or child.__dict__.get("overlay", None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cascading_fork_connections.py -v`
Expected: FAIL (fork_case con firma vieja crea overlay)

- [ ] **Step 3: Add fork/duplicate/connection methods**

Añadir dentro de `CascadingEngine`:

```python
    # ------------------------------------------------------------------ cases

    def fork_case(self, parent_case_id: str, name: str) -> str:
        if parent_case_id not in self._ws.cases:
            raise KeyError(f"Parent case {parent_case_id!r} not found")
        parent = self._ws.cases[parent_case_id]
        new_id = _new_case_id()
        child = Case(
            id=new_id,
            name=name,
            parent_case_id=parent_case_id,
            model=copy.deepcopy(parent.model),
            poses=self._clone_poses(parent),
            analyses=self._clone_analyses_reset(parent),
            sensor_outputs={},
            reaction_outputs={},
        )
        self._ws.cases[new_id] = child
        return new_id

    def duplicate_case(self, source_case_id: str, name: str | None = None) -> str:
        if source_case_id not in self._ws.cases:
            raise KeyError(f"Case {source_case_id!r} not found")
        source = self._ws.cases[source_case_id]
        new_id = _new_case_id()
        duplicate = Case(
            id=new_id,
            name=name or f"{source.name} copy",
            description=source.description,
            parent_case_id=source.parent_case_id,
            model=copy.deepcopy(source.model),
            poses=self._clone_poses(source),
            analyses=self._clone_analyses_reset(source),
            sensor_outputs={},
            reaction_outputs={},
            metadata=copy.deepcopy(source.metadata),
        )
        self._ws.cases[new_id] = duplicate
        if duplicate.parent_case_id is None and new_id not in self._ws.root_case_ids:
            self._ws.root_case_ids.append(new_id)
        return new_id

    def _clone_poses(self, source: Case):
        cloned = copy.deepcopy(source.poses)
        for pose in cloned:
            pose.id = _new_pose_id()
        if not any(p.is_default for p in cloned):
            cloned.insert(0, create_default_pose(_new_pose_id()))
        return cloned

    def _clone_analyses_reset(self, source: Case) -> list[Analysis]:
        cloned: list[Analysis] = copy.deepcopy(source.analyses)
        for analysis in cloned:
            analysis.id = _new_analysis_id()
            analysis.pose_id = None  # poses got new ids; reattach is a user action
            analysis.status = "to_be_run"
            analysis.created_at = None
            analysis.finished_at = None
            analysis.result_ref = None
            analysis.artifacts = []
            analysis.warnings = []
            analysis.error_message = ""
            analysis.config_snapshot = {}
            for metric in analysis.metrics:
                metric.result = None
        return cloned

    def reparent_case(self, case_id: str, new_parent_case_id: str | None) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        if new_parent_case_id is not None and self._would_form_cycle(case_id, new_parent_case_id):
            raise ValueError(f"Reparenting {case_id!r} under {new_parent_case_id!r} would form a cycle")
        old_parent = case.parent_case_id
        case.parent_case_id = new_parent_case_id
        if old_parent is None and case_id in self._ws.root_case_ids:
            self._ws.root_case_ids.remove(case_id)
        if new_parent_case_id is None and case_id not in self._ws.root_case_ids:
            self._ws.root_case_ids.append(case_id)
        for cid in {case_id, *self._all_descendants(case_id)}:
            self._mark_modified(result, cid, model_affecting=True)
        self._apply_staleness(result, "case reparented")
        return result

    def _would_form_cycle(self, case_id: str, candidate_parent_id: str) -> bool:
        current: str | None = candidate_parent_id
        seen: set[str] = set()
        while current is not None:
            if current == case_id or current in seen:
                return True
            seen.add(current)
            current = self._ws.cases[current].parent_case_id
        return False

    # --------------------------------------------------------------- blocks

    def add_connection(self, case_id: str, connection: Connection) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        self._ensure_diagram(case).connections.append(connection)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:add_connection:{_connection_key(connection)}")
        for child_id in self._direct_children(case_id):
            self._propagate_connection_add(child_id, connection, result)
        self._apply_staleness(result, "block connection added")
        return result

    def remove_connection(self, case_id: str, key: ConnectionKey) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        diagram = case.model.control_graph
        if diagram is None:
            return result
        object.__setattr__(diagram, "connections",
                           [c for c in diagram.connections if _connection_key(c) != key])
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:remove_connection:{key}")
        for child_id in self._direct_children(case_id):
            self._propagate_connection_remove(child_id, key, result)
        self._apply_staleness(result, "block connection removed")
        return result

    def _propagate_connection_add(self, case_id, connection, result) -> None:
        case = self._ws.cases[case_id]
        diagram = case.model.control_graph
        if diagram is None or connection.src_instance not in diagram.instances or \
                connection.dst_instance not in diagram.instances:
            return
        key = _connection_key(connection)
        if key not in {_connection_key(c) for c in diagram.connections}:
            diagram.connections.append(copy.deepcopy(connection))
            self._mark_modified(result, case_id, model_affecting=True)
        for gc_id in self._direct_children(case_id):
            self._propagate_connection_add(gc_id, connection, result)

    def _propagate_connection_remove(self, case_id, key, result) -> None:
        case = self._ws.cases[case_id]
        diagram = case.model.control_graph
        if diagram is None:
            return
        if key not in {_connection_key(c) for c in diagram.connections}:
            return  # already absent (diverged); stop
        object.__setattr__(diagram, "connections",
                           [c for c in diagram.connections if _connection_key(c) != key])
        self._mark_modified(result, case_id, model_affecting=True)
        for gc_id in self._direct_children(case_id):
            self._propagate_connection_remove(gc_id, key, result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cascading_fork_connections.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/services/case_cascading.py tests/test_cascading_fork_connections.py
git commit -m "feat(cascade): fork/duplicate/reparent y conexiones sin overlay"
```

---

## Task 1.9: Adaptar `run_invalidation.py` a Analysis (sin Case.runs)

`mark_runs_stale_for_case` itera `case.runs`. Ahora el estado vive en `analysis`.

**Files:**
- Modify: `quino/services/run_invalidation.py`
- Test: `tests/test_run_invalidation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_invalidation.py
from quino.domain.model import Model
from quino.domain.workspace import Analysis, Case, Workspace
from quino.services.run_invalidation import mark_runs_stale_for_case, mark_all_runs_stale


def _case_with_ok_analysis():
    a = Analysis(id="an1", name="Dyn", status="ok")
    return Case(id="c", name="c", model=Model(), analyses=[a])


def test_mark_stale_flips_ok_analysis():
    case = _case_with_ok_analysis()
    n = mark_runs_stale_for_case(case, reason="edit")
    assert n == 1
    assert case.analyses[0].status == "stale"


def test_mark_stale_skips_to_be_run():
    case = Case(id="c", name="c", model=Model(), analyses=[Analysis(id="a", name="x")])
    assert mark_runs_stale_for_case(case, reason="edit") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_invalidation.py -v`
Expected: FAIL (`case.runs` ya no es el campo correcto / aún itera runs)

- [ ] **Step 3: Rewrite `run_invalidation.py`**

Reemplazar el contenido por la versión basada en `analysis`:

```python
from __future__ import annotations

from datetime import datetime, timezone
import dataclasses
import re

from quino.domain.workspace import Analysis, Case, Workspace


def _stale_analyses(case: Case, analysis_ids: set[str] | None, reason: str) -> int:
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    affected = 0
    for analysis in case.analyses:
        if analysis_ids is not None and analysis.id not in analysis_ids:
            continue
        if analysis.status not in {"ok", "partial"}:
            continue
        analysis.status = "stale"
        analysis.warnings.append(f"[{timestamp}] {reason}")
        affected += 1
    return affected


def mark_runs_stale_for_case(case: Case, *, reason: str) -> int:
    return _stale_analyses(case, None, reason)


def mark_all_runs_stale(workspace: Workspace, *, reason: str) -> int:
    return sum(mark_runs_stale_for_case(case, reason=reason) for case in workspace.cases.values())


def mark_runs_stale_for_parameter(workspace: Workspace, parameter_name: str, *, reason: str) -> int:
    total = 0
    for case in workspace.cases.values():
        if _case_uses_parameter(case, parameter_name):
            total += mark_runs_stale_for_case(case, reason=reason)
    return total


def mark_runs_stale_for_pose(workspace: Workspace, pose_id: str, *, reason: str) -> int:
    total = 0
    for case in workspace.cases.values():
        ids = {a.id for a in case.analyses if a.pose_id == pose_id}
        total += _stale_analyses(case, ids, reason)
    return total


def _case_uses_parameter(case: Case, parameter_name: str) -> bool:
    token = re.compile(rf"\b{re.escape(parameter_name)}\b")
    return _contains_parameter_token(case.model, token)


def _contains_parameter_token(value, token: re.Pattern[str]) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(token.search(value))
    if isinstance(value, (int, float, bool)):
        return False
    expression = getattr(value, "expression", None)
    if isinstance(expression, str) and token.search(expression):
        return True
    if isinstance(value, dict):
        return any(_contains_parameter_token(item, token) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_parameter_token(item, token) for item in value)
    if dataclasses.is_dataclass(value):
        return any(_contains_parameter_token(getattr(value, f.name), token)
                   for f in dataclasses.fields(value))
    return False


def delete_run(workspace: Workspace, project_dir, analysis_id: str) -> bool:
    """Reset the run state of an analysis and unlink its on-disk artifact."""
    from pathlib import Path
    for case in workspace.cases.values():
        target = next((a for a in case.analyses if a.id == analysis_id), None)
        if target is None:
            continue
        if project_dir is not None and target.result_ref is not None:
            artifact = Path(project_dir) / target.result_ref.artifact_path
            try:
                artifact.unlink(missing_ok=True)
            except OSError:
                pass
        target.status = "to_be_run"
        target.result_ref = None
        target.artifacts = []
        target.finished_at = None
        return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_invalidation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/services/run_invalidation.py tests/test_run_invalidation.py
git commit -m "refactor(invalidation): staleness sobre Analysis, no Case.runs"
```

---

## Task 1.10: Borrar overlays del dominio y servicios muertos

**Files:**
- Delete: `quino/services/case_overlay_validator.py`
- Delete: `quino/services/cascade_property_registry.py`
- Modify: `quino/domain/workspace.py` (borrar `CaseOverlay`, `EntityOverlay`, `Run`, `Case.overlay`, `Case.runs`, `Case.tolerances`, `Case.metrics`, `MetricDefinition`, `Tolerance`)
- Delete tests: `tests/test_case_overlay_editing.py`, `tests/test_cascade_property_registry.py`, `tests/test_case_overlay_validator.py` (los que existan)

- [ ] **Step 1: Identify dependents**

Run: `git grep -l "CaseOverlay\|EntityOverlay\|cascade_property_registry\|case_overlay_validator\|\.overlay\|case\.runs\|Case.runs"`
Expected: lista de archivos que aún referencian overlays. Anotarlos.

- [ ] **Step 2: Remove overlay fields from `Case` and delete dead classes**

En `quino/domain/workspace.py`:
- Borrar las dataclasses `EntityOverlay`, `CaseOverlay`, `Run`, `MetricDefinition`, `Tolerance`, `ResultRef`/`ArtifactRef` **NO** (esos se quedan, los usa Analysis).
- En `Case`, dejar exactamente los campos de la spec §3.1 (sin `overlay`, `runs`, `tolerances`, `metrics`).

`Case` final:

```python
@dataclass(slots=True)
class Case:
    id: str
    name: str
    description: str = ""
    parent_case_id: str | None = None
    model: Model = field(default_factory=Model)
    poses: list[Pose] = field(default_factory=list)
    analyses: list[Analysis] = field(default_factory=list)
    sensor_outputs: dict[str, SensorOutput] = field(default_factory=dict)
    reaction_outputs: dict[str, ReactionOutput] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 3: Delete dead service modules and their tests**

```bash
git rm quino/services/case_overlay_validator.py quino/services/cascade_property_registry.py
git rm tests/test_case_overlay_editing.py tests/test_cascade_property_registry.py 2>$null
```

(usar `Remove-Item` si `git rm` falla por archivo inexistente; borrar solo los que existan.)

- [ ] **Step 4: Run the whole suite to find breakage**

Run: `pytest tests/ -q`
Expected: fallos en módulos que aún importan overlays. Arreglar imports/usos uno a uno hasta verde. Los grandes consumidores (command-services, GUI tree) se tratan en sus fases; aquí solo asegurar que el dominio y servicios núcleo compilan. Si un test de GUI depende de overlay y su fix corresponde a Fase 4, márcalo con `pytest.mark.skip(reason="overlay removed; GUI adapted in Fase 4")` y anótalo.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(domain): eliminar overlays, Run, tolerances y metrics de Case"
```

---

# FASE 2 — Ejecución unificada y métricas

## Task 2.1: Servicio de evaluación de métricas (exec restringido)

**Files:**
- Create: `quino/services/metric_evaluator.py`
- Test: `tests/test_metric_evaluator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metric_evaluator.py
import numpy as np

from quino.domain.workspace import Metric
from quino.services.metric_evaluator import evaluate


def test_eval_returns_float():
    m = Metric(id="m", name="final", value_type="float",
               code="var = data['s1.x']\nreturn var[-1]")
    data = {"s1.x": np.array([1.0, 2.0, 3.0])}
    res = evaluate(m, data, meta={})
    assert res.status == "ok"
    assert res.value == 3.0


def test_eval_bool_cast():
    m = Metric(id="m", name="thr", value_type="bool",
               code="return data['s1.x'][-1] > 10")
    res = evaluate(m, {"s1.x": np.array([1.0, 12.0])}, meta={})
    assert res.status == "ok"
    assert res.value is True


def test_eval_uses_meta():
    m = Metric(id="m", name="dt", value_type="float", code="return meta['dt']")
    res = evaluate(m, {}, meta={"dt": 0.01})
    assert res.value == 0.01


def test_eval_blocks_import():
    m = Metric(id="m", name="bad", code="import os\nreturn 1")
    res = evaluate(m, {}, meta={})
    assert res.status == "error"
    assert "import" in res.error.lower() or "not defined" in res.error.lower()


def test_eval_runtime_error_is_captured():
    m = Metric(id="m", name="bad", code="return data['missing'][0]")
    res = evaluate(m, {}, meta={})
    assert res.status == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_metric_evaluator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# quino/services/metric_evaluator.py
"""Evaluate user-defined Python metrics with a restricted exec namespace.

The user writes the *body* of `def evaluate(data, meta):` (with a `return`).
We wrap it, compile it, and run it with a reduced builtins set (no import,
open, eval, exec, dunder access) plus numpy exposed as `np`. Errors and
timeouts are captured into MetricResult.
"""
from __future__ import annotations

import textwrap
import threading
from datetime import datetime, timezone
from typing import Any

import numpy as np

from quino.domain.workspace import Metric, MetricResult

_SAFE_BUILTINS = {
    "abs": abs, "min": min, "max": max, "sum": sum, "len": len,
    "range": range, "enumerate": enumerate, "zip": zip, "map": map,
    "filter": filter, "sorted": sorted, "round": round, "float": float,
    "int": int, "bool": bool, "str": str, "list": list, "tuple": tuple,
    "dict": dict, "set": set, "any": any, "all": all,
}

_TIMEOUT_S = 5.0


def _cast(value: Any, value_type: str) -> Any:
    if value_type == "float":
        return float(value)
    if value_type == "int":
        return int(value)
    if value_type == "bool":
        return bool(value)
    if value_type == "str":
        return str(value)
    return value


def _build_callable(code: str):
    body = textwrap.indent(code if code.strip() else "return None", "    ")
    source = f"def _evaluate(data, meta):\n{body}\n"
    globals_ns = {"__builtins__": _SAFE_BUILTINS, "np": np}
    compiled = compile(source, "<metric>", "exec")
    exec(compiled, globals_ns)  # noqa: S102 - restricted namespace
    return globals_ns["_evaluate"]


def evaluate(metric: Metric, data: dict[str, Any], meta: dict[str, Any]) -> MetricResult:
    now = datetime.now(tz=timezone.utc).isoformat()
    holder: dict[str, Any] = {}

    def _target() -> None:
        try:
            fn = _build_callable(metric.code)
            raw = fn(data, meta)
            holder["value"] = _cast(raw, metric.value_type)
        except Exception as exc:  # noqa: BLE001 - report any user error
            holder["error"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    worker.join(timeout=_TIMEOUT_S)
    if worker.is_alive():
        return MetricResult(value=None, status="error",
                            error=f"evaluation exceeded {_TIMEOUT_S}s", evaluated_at=now)
    if "error" in holder:
        return MetricResult(value=None, status="error", error=holder["error"], evaluated_at=now)
    return MetricResult(value=holder.get("value"), status="ok", evaluated_at=now)


def evaluate_all(analysis, data: dict[str, Any], meta: dict[str, Any]) -> None:
    """Evaluate every metric of an analysis in place."""
    for metric in analysis.metrics:
        if not data:
            metric.result = MetricResult(value=None, status="no_data",
                                         evaluated_at=datetime.now(tz=timezone.utc).isoformat())
        else:
            metric.result = evaluate(metric, data, meta)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_metric_evaluator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/services/metric_evaluator.py tests/test_metric_evaluator.py
git commit -m "feat(metrics): evaluador de métricas Python con exec restringido"
```

---

## Task 2.2: Construcción de `data`/`meta` desde `sensor_outputs`

**Files:**
- Create: `quino/services/metric_data.py`
- Test: `tests/test_metric_data.py`

- [ ] **Step 1: Inspect SensorOutput shape**

Run: `git grep -n "class SensorOutput" quino/domain/model.py` y leer la dataclass para conocer sus campos (series por canal, tiempos). Ajustar el builder a esos campos reales. El test asume `SensorOutput` con un mapping de canal→serie y un eje de tiempo; **adaptar nombres a los reales** tras leer la clase.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_metric_data.py
import numpy as np

from quino.services.metric_data import build_metric_data


def test_build_keys_by_sensor_name_and_channel():
    # Minimal fakes matching the SensorOutput contract used by build_metric_data.
    class FakeOut:
        def __init__(self):
            self.channels = {"x": [1.0, 2.0, 3.0], "y": [0.0, 0.0, 1.0]}
            self.time = [0.0, 0.1, 0.2]
    sensor_name_by_id = {"sen1": "thigh"}
    outputs = {"sen1": FakeOut()}
    data, meta = build_metric_data(outputs, sensor_name_by_id, analysis_meta={"dt": 0.1})
    assert "thigh.x" in data
    assert np.allclose(data["thigh.x"], [1.0, 2.0, 3.0])
    assert "t" in data
    assert meta["dt"] == 0.1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_metric_data.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write the implementation**

```python
# quino/services/metric_data.py
"""Build the `data`/`meta` inputs for metric evaluation from sensor outputs.

Keys are `"<sensor_name>.<channel>"` (per the user-facing convention) plus a
shared `"t"` time axis. `meta` carries analysis-level metadata (dt, t_final...).
"""
from __future__ import annotations

from typing import Any

import numpy as np


def build_metric_data(
    sensor_outputs: dict[str, Any],
    sensor_name_by_id: dict[str, str],
    analysis_meta: dict[str, Any],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    data: dict[str, np.ndarray] = {}
    time_axis: list[float] | None = None
    for sensor_id, out in sensor_outputs.items():
        name = sensor_name_by_id.get(sensor_id, sensor_id)
        channels = getattr(out, "channels", {}) or {}
        for channel, series in channels.items():
            data[f"{name}.{channel}"] = np.asarray(series, dtype=float)
        if time_axis is None:
            t = getattr(out, "time", None)
            if t is not None:
                time_axis = list(t)
    if time_axis is not None:
        data["t"] = np.asarray(time_axis, dtype=float)
    return data, dict(analysis_meta)
```

**Nota:** ajustar `getattr(out, "channels"/"time")` a los nombres reales de `SensorOutput` descubiertos en el Step 1.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_metric_data.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quino/services/metric_data.py tests/test_metric_data.py
git commit -m "feat(metrics): builder de data/meta desde sensor_outputs"
```

---

## Task 2.3: Promoción atómica de artefactos (buffer temporal)

**Files:**
- Create: `quino/services/run_artifacts.py`
- Test: `tests/test_run_artifacts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_artifacts.py
from pathlib import Path

from quino.services.run_artifacts import staging_dir, good_dir, promote_staging, discard_staging


def test_promote_replaces_good_dir(tmp_path):
    base = tmp_path / "artifacts"
    good = good_dir(base, "an1")
    good.mkdir(parents=True)
    (good / "old.txt").write_text("old")
    staging = staging_dir(base, "an1")
    staging.mkdir(parents=True)
    (staging / "new.txt").write_text("new")

    promote_staging(base, "an1")

    assert (good_dir(base, "an1") / "new.txt").exists()
    assert not (good_dir(base, "an1") / "old.txt").exists()
    assert not staging_dir(base, "an1").exists()


def test_discard_removes_staging_keeps_good(tmp_path):
    base = tmp_path / "artifacts"
    good = good_dir(base, "an1")
    good.mkdir(parents=True)
    (good / "keep.txt").write_text("keep")
    staging = staging_dir(base, "an1")
    staging.mkdir(parents=True)
    (staging / "tmp.txt").write_text("tmp")

    discard_staging(base, "an1")

    assert (good_dir(base, "an1") / "keep.txt").exists()
    assert not staging_dir(base, "an1").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_artifacts.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# quino/services/run_artifacts.py
"""Atomic promotion of analysis artifacts via a staging directory.

`good_dir` holds the last successful results; `staging_dir` is where a new run
writes. On OK/Partial we promote staging over good; on failure we discard
staging, leaving good intact.
"""
from __future__ import annotations

import shutil
from pathlib import Path


def good_dir(base: Path, analysis_id: str) -> Path:
    return Path(base) / analysis_id


def staging_dir(base: Path, analysis_id: str) -> Path:
    return Path(base) / analysis_id / "_staging"


def promote_staging(base: Path, analysis_id: str) -> None:
    good = good_dir(base, analysis_id)
    staging = staging_dir(base, analysis_id)
    if not staging.exists():
        return
    # Move staging aside, wipe good's direct contents (except staging), move in.
    tmp = Path(base) / f"{analysis_id}__promote_tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.move(str(staging), str(tmp))
    if good.exists():
        for child in good.iterdir():
            if child.name == "_staging":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    good.mkdir(parents=True, exist_ok=True)
    for child in tmp.iterdir():
        shutil.move(str(child), str(good / child.name))
    shutil.rmtree(tmp)


def discard_staging(base: Path, analysis_id: str) -> None:
    staging = staging_dir(base, analysis_id)
    if staging.exists():
        shutil.rmtree(staging)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_artifacts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/services/run_artifacts.py tests/test_run_artifacts.py
git commit -m "feat(run): promoción atómica de artefactos con staging"
```

---

## Task 2.4: Adaptar `run_executor` a Analysis + buffer + auto-métricas

`run_executor.py` deja de crear `Run` en `case.runs`; opera sobre `Analysis`, escribe en staging, promociona (o descarta), evalúa métricas, y emite señal para el prompt OK→Partial.

**Files:**
- Modify: `quino/services/run_executor.py`
- Test: `tests/test_run_executor.py` (reescribir las partes que asumen `case.runs`)

- [ ] **Step 1: Read current runner contract**

Run: leer `quino/services/workspace_runner.py` (`_CaseAsProject`, `_next_run_id`) y `quino/analysis/registry.py` para confirmar la firma de `runner.run(...)` y de dónde sale `status`. Anotar.

- [ ] **Step 2: Write/adjust the failing test**

```python
# tests/test_run_executor.py  (añadir/ajustar)
from quino.domain.workspace import Analysis


def test_run_state_lives_on_analysis(monkeypatch, ...):
    # Build an app_service with one case + one analysis (use existing test fixtures
    # in this file; replace any `case.runs` assertions with `analysis.status`).
    # After a successful enqueue+execute, assert:
    #   analysis.status == "ok"
    #   analysis.result_ref is not None
    #   analysis.finished_at is not None
    ...
```

(Reescribir el cuerpo según las fixtures ya presentes en `tests/test_run_executor.py`; el punto clave: las aserciones pasan de `case.runs[-1].status` a `analysis.status`.)

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_run_executor.py -v`
Expected: FAIL (sigue mirando `case.runs`)

- [ ] **Step 4: Rewrite `run_executor.py`**

Cambios clave (mantener el patrón de cola/thread):
- `enqueue(analysis_id)`: ya no crea `Run`; toma el `Analysis`, captura `prev` snapshot (status, result_ref, artifacts, finished_at, y copia de métricas), pone `analysis.status="queued"` conservando artifacts viejos, y encola un `_QueuedJob(case_id, analysis_id, ...)`.
- `_run_one(job)`: pone `status="running"`; el runner escribe en `staging_dir(base, analysis_id)`; al terminar:
  - cancel/`to_be_run` o excepción → `discard_staging`; restaurar `prev`.
  - `ok` → `promote_staging`; set `status/result_ref/finished_at`; construir data/meta y `evaluate_all`.
  - `partial`:
    - si `prev.status == "ok"`: **no promociona**; emite `run_needs_confirmation.emit(analysis_id)` con el resultado pendiente guardado en `self.pending_partial[analysis_id] = (prev, staging_result)`. La GUI decide y llama `confirm_partial(analysis_id, overwrite: bool)`.
    - si no: `promote_staging` + métricas como en ok.

Añadir señal y método:

```python
    run_needs_confirmation = QtCore.Signal(str)  # analysis_id (partial over ok)

    def confirm_partial(self, analysis_id: str, overwrite: bool) -> None:
        pending = self.pending_partial.pop(analysis_id, None)
        if pending is None:
            return
        prev, result, case_id = pending
        base = self._artifacts_base()
        with self.app_service.workspace_lock:
            analysis = self._find_analysis(case_id, analysis_id)
            if analysis is None:
                return
            if overwrite:
                promote_staging(base, analysis_id)
                self._apply_result(analysis, result, status="partial")
                self._evaluate_metrics(case_id, analysis)
            else:
                discard_staging(base, analysis_id)
                self._restore_prev(analysis, prev)
        self.run_finished.emit(analysis_id, analysis.status)
```

Donde `_apply_result`, `_restore_prev`, `_evaluate_metrics`, `_artifacts_base`, `_find_analysis` son helpers privados (escribir su código completo siguiendo los campos de `Analysis`). `_evaluate_metrics` usa `build_metric_data` + `evaluate_all`, con `sensor_name_by_id` derivado de `case.model.sensors` y `analysis_meta` desde `analysis.config` (dt, t_final/duration, steps).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_run_executor.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quino/services/run_executor.py tests/test_run_executor.py
git commit -m "feat(run): estado de run en Analysis, staging+promoción, prompt OK→Partial, auto-métricas"
```

---

## Task 2.5: Adaptar command-services y fachada a Analysis (sin Run/overlay)

Los command-services (`workspace_commands.py`, etc.) y `service.py` referencian `case.runs`, `delete_run(run_id)`, y mutaciones que antes tocaban overlay. Adaptarlos al modelo nuevo.

**Files:**
- Modify: `quino/application/commands/workspace_commands.py`
- Modify: `quino/application/service.py`
- Modify: `quino/application/_context.py` (si referencia overlay)
- Test: `tests/test_pose_commands.py`, `tests/test_run_artifact_dataset.py` (ya tocados en working set) y cualquier test de comandos roto

- [ ] **Step 1: Find call sites**

Run: `git grep -n "\.runs\|delete_run\|create_analysis\|rename_analysis\|delete_analysis\|overlay" quino/application/`
Expected: lista de métodos a adaptar.

- [ ] **Step 2: Run the relevant suites to see failures**

Run: `pytest tests/test_pose_commands.py tests/test_run_executor.py -q`
Expected: fallos por API vieja.

- [ ] **Step 3: Adapt the command-services**

- `delete_run(run_id)` → `delete_run(analysis_id)` resetea el estado del analysis (usa `run_invalidation.delete_run`, ya adaptado).
- `create_analysis(...)` crea `Analysis` y lo añade a `case.analyses` (sin tocar runs).
- `rename_analysis` / `delete_analysis`: operar sobre `case.analyses`.
- Eliminar cualquier paso que construyera/validara overlay (`validate_overlay`, `rebuild_overlay`).
- Las mutaciones de modelo (add/remove/edit body, joint, etc.) que deban cascadear pasan por `CascadingEngine`.

(Aplicar edits concretos según lo encontrado en Step 1; cada método con su código.)

- [ ] **Step 4: Run suites to verify they pass**

Run: `pytest tests/test_pose_commands.py tests/test_run_executor.py tests/test_run_artifact_dataset.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/application tests/test_pose_commands.py tests/test_run_artifact_dataset.py
git commit -m "refactor(application): comandos sobre Analysis (run aplanado), sin overlay"
```

---

# FASE 3 — Serialización 0.4.0

## Task 3.1: Bump de schema y rechazo de versiones antiguas

**Files:**
- Modify: `quino/serialization/json_io.py`
- Test: `tests/test_schema_version.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema_version.py
import pytest

from quino.serialization.json_io import JsonMapper, UnsupportedSchemaError


def test_load_rejects_old_schema():
    mapper = JsonMapper()
    with pytest.raises(UnsupportedSchemaError):
        mapper.load_dict({"schema_version": "0.3.0", "id": "w", "name": "w", "cases": {}})


def test_current_schema_constant_is_0_4_0():
    assert JsonMapper.CURRENT_SCHEMA == "0.4.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schema_version.py -v`
Expected: FAIL (constante aún 0.3.0 / no rechaza)

- [ ] **Step 3: Update json_io**

En `quino/serialization/json_io.py`: subir `CURRENT_SCHEMA = "0.4.0"`, y en `load`/`load_dict` rechazar `< 0.4.0` con `UnsupportedSchemaError`. (Si no existe `load_dict`, exponer un helper que valide solo la versión, o ajustar el test al método real de carga desde dict.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schema_version.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/serialization/json_io.py tests/test_schema_version.py
git commit -m "feat(serial): schema 0.4.0, rechazo de versiones anteriores"
```

---

## Task 3.2: (De)serializar Analysis aplanado + Metric, sin overlay/Run

**Files:**
- Modify: `quino/serialization/json_io.py`
- Test: `tests/test_workspace_roundtrip.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workspace_roundtrip.py
from quino.domain.model import Body, Model
from quino.domain.types import BodyType
from quino.domain.workspace import Analysis, Case, Metric, MetricResult, Workspace
from quino.serialization.json_io import JsonMapper


def _workspace():
    a = Analysis(id="an1", name="Dyn", analysis_type="dynamic", status="ok",
                 metrics=[Metric(id="m1", name="final", value_type="float",
                                 code="return data['s.x'][-1]",
                                 result=MetricResult(value=3.0, status="ok"))])
    case = Case(id="c", name="root",
                model=Model(bodies=[Body(id="b1", name="bar", type=BodyType.BAR)]),
                analyses=[a])
    return Workspace(id="w", name="w", schema_version="0.4.0",
                     root_case_ids=["c"], cases={"c": case})


def test_roundtrip_preserves_analysis_state_and_metric():
    mapper = JsonMapper()
    ws = _workspace()
    blob = mapper.dumps(ws)
    loaded = mapper.loads(blob)
    a = loaded.cases["c"].analyses[0]
    assert a.status == "ok"
    assert a.metrics[0].code == "return data['s.x'][-1]"
    assert a.metrics[0].result.value == 3.0


def test_roundtrip_has_no_overlay_or_runs():
    mapper = JsonMapper()
    blob = mapper.dumps(_workspace())
    assert "overlay" not in blob
    assert '"runs"' not in blob
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workspace_roundtrip.py -v`
Expected: FAIL (serializa overlay/runs o no serializa metrics)

- [ ] **Step 3: Update json_io mappers**

- Quitar (de)serialización de `overlay`, `runs`, `tolerances`, `metrics`(dict viejo) en `Case`.
- Serializar los campos de run aplanados de `Analysis` y la lista `metrics` (`Metric` + `MetricResult`).
- `MetricResult.value` se serializa según su tipo primitivo (float/bool/int/str).
- Confirmar que los nombres de métodos (`dumps`/`loads` vs `save`/`load`) coinciden con los reales; ajustar el test si la API es `save_to_path`/`load`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace_roundtrip.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/serialization/json_io.py tests/test_workspace_roundtrip.py
git commit -m "feat(serial): Analysis aplanado + Metric; sin overlay/runs en JSON"
```

---

## Task 3.3: Regenerar ejemplos a 0.4.0

**Files:**
- Modify: `scripts/build_*.py` (los que existan)
- Regenerate: `examples/*.quino.json`
- Test: `tests/test_examples_load.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_examples_load.py
from pathlib import Path

import pytest

from quino.serialization.json_io import JsonMapper

EXAMPLES = sorted(Path("examples").glob("*.quino.json"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_loads_at_0_4_0(path):
    ws = JsonMapper().load(path)
    assert ws.schema_version == "0.4.0"
    assert ws.cases
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_examples_load.py -q`
Expected: FAIL (ejemplos aún 0.3.0 / con overlay)

- [ ] **Step 3: Regenerate examples**

Para cada `scripts/build_*.py`: ejecutar y verificar que produce un `.quino.json` 0.4.0. Para ejemplos sin script (Double_Pendulum variants, Spring_Oscillator, Torsional_Spring_Pendulum), escribir el script `build_*` correspondiente que construya el workspace con la API nueva y lo guarde.

Run (PowerShell): por cada script, `python scripts/build_<name>.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_examples_load.py -q`
Expected: PASS para todos los ejemplos.

- [ ] **Step 5: Commit**

```bash
git add scripts examples tests/test_examples_load.py
git commit -m "chore(examples): regenerar a schema 0.4.0"
```

---

# FASE 4 — GUI

## Task 4.1: Flecha en todos los combobox (theme)

**Files:**
- Modify: `quino/gui/theme.py` (regla `QComboBox::down-arrow`)
- Test: `tests/test_theme_combobox.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_theme_combobox.py
from quino.gui.theme import build_stylesheet  # ajustar al símbolo real que arma el QSS


def test_combobox_has_down_arrow_image():
    qss = build_stylesheet()
    assert "QComboBox::down-arrow" in qss
    assert "image:" in qss.split("QComboBox::down-arrow", 1)[1][:200]
```

(Si el QSS no se construye con una función sino con una constante de módulo, importar esa constante en su lugar.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_theme_combobox.py -v`
Expected: FAIL (no hay regla down-arrow con image)

- [ ] **Step 3: Add the arrow rule**

En `quino/gui/theme.py`, tras `QComboBox::drop-down`, añadir una regla `QComboBox::down-arrow` con una imagen de chevron. Reutilizar el icono existente (`get_icon("chevron-down", ...)`) exportándolo como recurso, o un SVG embebido vía `url(...)`. Asegurar que apunta a una ruta válida del paquete de iconos.

```css
QComboBox::down-arrow {
    image: url(<ruta al chevron-down del paquete de iconos>);
    width: 12px;
    height: 12px;
}
```

- [ ] **Step 4: Run test to verify it passes + smoke**

Run: `$env:QT_QPA_PLATFORM='offscreen'; pytest tests/test_theme_combobox.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/gui/theme.py tests/test_theme_combobox.py
git commit -m "fix(theme): flecha visible en todos los QComboBox"
```

---

## Task 4.2: Árboles — expandir solo con el triángulo (global)

**Files:**
- Modify: `quino/gui/theme.py` (`apply_browser_tree_style`)
- Test: `tests/test_tree_expand_behavior.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tree_expand_behavior.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from quino.gui.theme import apply_browser_tree_style


def test_double_click_does_not_expand(qtbot=None):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tree = QtWidgets.QTreeWidget()
    parent = QtWidgets.QTreeWidgetItem(["p"])
    parent.addChild(QtWidgets.QTreeWidgetItem(["c"]))
    tree.addTopLevelItem(parent)
    apply_browser_tree_style(tree)
    assert tree.expandsOnDoubleClick() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tree_expand_behavior.py -v`
Expected: FAIL si `apply_browser_tree_style` no fija `setExpandsOnDoubleClick(False)` globalmente (hoy se hace por-árbol en el panel).

- [ ] **Step 3: Centralize the behavior**

En `apply_browser_tree_style` añadir `tree.setExpandsOnDoubleClick(False)`. Para desactivar también el toggle por clic simple sobre el contenido, instalar el comportamiento: conectar nada que togglee, y asegurar que `setItemsExpandable(True)` mantiene el triángulo operativo. (El branch indicator del stylesheet ya dibuja el triángulo; el clic sobre él sigue expandiendo porque es manejado por la vista, no por `itemClicked`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:QT_QPA_PLATFORM='offscreen'; pytest tests/test_tree_expand_behavior.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/gui/theme.py tests/test_tree_expand_behavior.py
git commit -m "fix(gui): expandir árboles solo con el triángulo (global)"
```

---

## Task 4.3: Árbol del workspace — poses directas, carpeta Subcases, sin badges overlay

**Files:**
- Modify: `quino/gui/panels/workflow_tree_panel.py`
- Test: `tests/test_workflow_tree.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workflow_tree.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from quino.application.service import ApplicationService
from quino.gui.panels.workflow_tree_panel import WorkflowTreePanel, ROLE_NODE_KIND


def _panel_with_root():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    svc = ApplicationService()
    svc.new_workspace("W")  # ajustar al método real de creación
    panel = WorkflowTreePanel(svc)
    panel.refresh()
    return panel


def test_no_poses_group_node():
    panel = _panel_with_root()
    root = panel.top_level_items()[0]
    kinds = [root.child(i).data(0, ROLE_NODE_KIND) for i in range(root.childCount())]
    assert "poses_group" not in kinds  # poses cuelgan directas


def test_subcases_group_present():
    panel = _panel_with_root()
    root = panel.top_level_items()[0]
    kinds = [root.child(i).data(0, ROLE_NODE_KIND) for i in range(root.childCount())]
    assert "subcases_group" in kinds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow_tree.py -v`
Expected: FAIL (aún existe `poses_group`)

- [ ] **Step 3: Restructure `_build_case_item`**

- Eliminar el nodo `poses_group`: añadir la pose default y las poses **directamente** como hijos del nodo del caso (mantener `default_pose`/`pose` kinds).
- Mantener `subcases_group` pero con **icono de carpeta** (`get_icon("folder", ...)` o el icono de carpeta disponible).
- El estado del run se muestra en el nodo del **analysis** (badge de estado), ya no como nodos `run` hijos: en `_build_analysis_item`, en vez de añadir hijos `run`, poner el icono/sufijo de estado desde `analysis.status` y `_RUN_STATUS_ICONS`.
- Eliminar `_overlay_has_unlinked_props` y `_case_badges` (badges `★`/`⚠`).

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:QT_QPA_PLATFORM='offscreen'; pytest tests/test_workflow_tree.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/gui/panels/workflow_tree_panel.py tests/test_workflow_tree.py
git commit -m "feat(gui): árbol con poses directas, carpeta Subcases, estado en analysis"
```

---

## Task 4.4: Resaltado y expansión del caso activo

**Files:**
- Modify: `quino/gui/panels/workflow_tree_panel.py`
- Test: `tests/test_workflow_tree_active.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workflow_tree_active.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtGui, QtWidgets
from quino.application.service import ApplicationService
from quino.gui.panels.workflow_tree_panel import WorkflowTreePanel, ROLE_NODE_KIND
from quino.gui.theme import BLUE_SOFT


def _panel():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    svc = ApplicationService()
    svc.new_workspace("W")
    panel = WorkflowTreePanel(svc)
    return svc, panel


def test_active_case_children_highlighted():
    svc, panel = _panel()
    ws = svc._workspace
    active = ws.root_case_ids[0]
    ws.selected_case_id = active
    panel.refresh()
    root = panel.top_level_items()[0]
    # the default pose under the active case should carry the BLUE_SOFT background
    pose_items = [root.child(i) for i in range(root.childCount())
                  if root.child(i).data(0, ROLE_NODE_KIND) in ("default_pose", "pose")]
    assert pose_items
    bg = pose_items[0].background(0).color().name().lower()
    assert bg == QtGui.QColor(BLUE_SOFT).name().lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow_tree_active.py -v`
Expected: FAIL (no se pinta el fondo de los hijos)

- [ ] **Step 3: Implement active highlight + expand**

En `_build_case_item`, cuando `is_active`:
- pintar `BLUE_SOFT` de fondo en la pose default, poses y analyses (y su nodo de estado), **no** en `subcases_group` ni sus hijos.
- expandir el nodo del caso (`item.setExpanded(True)`).

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:QT_QPA_PLATFORM='offscreen'; pytest tests/test_workflow_tree_active.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/gui/panels/workflow_tree_panel.py tests/test_workflow_tree_active.py
git commit -m "feat(gui): caso activo se expande y resalta sus poses/analyses"
```

---

## Task 4.5: Ventana editor de métricas Python

**Files:**
- Modify: `quino/gui/dialogs/metric_editor_dialog.py` (reescritura completa)
- Modify: `quino/gui/dialogs/metrics_manager_dialog.py`
- Test: `tests/test_gui_metric_dialogs.py` (reescribir)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gui_metric_dialogs.py  (reescribir)
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from quino.domain.workspace import Analysis, Metric
from quino.gui.dialogs.metric_editor_dialog import MetricEditorDialog


def test_editor_builds_metric_from_fields():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    analysis = Analysis(id="an1", name="Dyn")
    dlg = MetricEditorDialog(analysis, available_channels=["s1.x", "t"])
    dlg.name_edit.setText("final pos")
    dlg.type_combo.setCurrentText("float")
    dlg.code_edit.setPlainText("return data['s1.x'][-1]")
    dlg._accept()
    assert dlg.result_metric is not None
    assert dlg.result_metric.value_type == "float"
    assert "return data['s1.x'][-1]" in dlg.result_metric.code
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_metric_dialogs.py -v`
Expected: FAIL (la firma actual recibe `project`/`MetricDef`)

- [ ] **Step 3: Rewrite the dialogs**

`MetricEditorDialog(analysis, metric=None, available_channels=None, runner=None, parent=None)`:
- Campos: `name_edit`, `description_edit`, `type_combo` (float/bool/int/str), `code_edit` (`QPlainTextEdit`).
- Panel lateral con la lista de `available_channels` (`data['...']`, `meta['dt']`, `meta['t_final']`); doble clic inserta el token en el cursor del editor.
- Botón **Probar**: si hay un callable de evaluación inyectado (o datos del último run del analysis), llama `evaluate(metric_temp, data, meta)` y muestra el resultado/error en un label.
- `_accept()` arma `Metric(id=..., name, description, value_type, code)` en `self.result_metric`.

`MetricsManagerDialog(analysis, available_channels, parent=None)`:
- Tabla con columnas Nombre / Tipo / Resultado (lee `analysis.metrics` y `metric.result`).
- Add/Edit/Delete sobre `analysis.metrics`.
- Botón **Recalcular todas**: invoca el evaluador con los datos disponibles del analysis.

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:QT_QPA_PLATFORM='offscreen'; pytest tests/test_gui_metric_dialogs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/gui/dialogs/metric_editor_dialog.py quino/gui/dialogs/metrics_manager_dialog.py tests/test_gui_metric_dialogs.py
git commit -m "feat(gui): editor de métricas Python (código + canales + Probar)"
```

---

## Task 4.6: Quitar Divergences dock y referencias a overlay/Run en GUI

**Files:**
- Modify: `quino/gui/main_window.py`
- Modify: `quino/gui/canvas.py` (si referencia overlay/diff overlay)
- Modify: `quino/gui/widgets/run_status_widget.py`
- Modify: `quino/gui/widgets/case_diffs_widget.py` (mantener "Compare with parent" vía case_diff)
- Modify: `quino/gui/dialogs/run_comparison_dialog.py`
- Modify: `quino/viewer/dataset.py`, `quino/viewer/plot_window.py`
- Test: `tests/test_gui.py`

- [ ] **Step 1: Find references**

Run: `git grep -n "Divergence\|divergence\|overlay\|\.runs\|Run(" quino/gui quino/viewer`
Expected: lista de puntos a limpiar.

- [ ] **Step 2: Run the GUI suite to see failures**

Run: `$env:QT_QPA_PLATFORM='offscreen'; pytest tests/test_gui.py -q`
Expected: fallos por símbolos eliminados.

- [ ] **Step 3: Remove dock and adapt readers**

- Quitar la creación del Divergences dock y su tab en `main_window.py`.
- `run_status_widget`, `run_comparison_dialog`, `viewer/dataset`, `plot_window`: leer estado/artifacts desde `Analysis` (no `Run`). Filtrar por `selected_case_id`.
- `case_diffs_widget`: sigue usando `case_diff.diff_case_against` (sin cambios de fondo).
- Reactivar (quitar skips) los tests de GUI marcados en Task 1.10.

- [ ] **Step 4: Run the GUI suite to verify it passes**

Run: `$env:QT_QPA_PLATFORM='offscreen'; pytest tests/test_gui.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/gui quino/viewer tests/test_gui.py
git commit -m "refactor(gui): quitar Divergences dock; paneles leen estado desde Analysis"
```

---

## Task 4.7: Prompt OK→Partial en MainWindow

**Files:**
- Modify: `quino/gui/main_window.py`
- Test: `tests/test_partial_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_partial_prompt.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
# Drive the executor's run_needs_confirmation signal and assert MainWindow
# calls confirm_partial(analysis_id, overwrite) based on the user's choice.
# Use monkeypatch on QtWidgets.QMessageBox.question to return Yes/No.


def test_partial_over_ok_asks_and_overwrites(monkeypatch):
    # Build MainWindow with a stub RunExecutor exposing confirm_partial(spy).
    # Emit run_needs_confirmation("an1"); patch QMessageBox.question -> Yes.
    # Assert confirm_partial called with ("an1", True).
    ...
```

(Completar con las fixtures de `tests/test_gui.py`; el punto: conectar la señal `run_needs_confirmation` a un handler que pregunte y llame `confirm_partial`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_partial_prompt.py -v`
Expected: FAIL (no hay handler conectado)

- [ ] **Step 3: Wire the prompt**

En `main_window.py`, conectar `run_executor.run_needs_confirmation` a un slot que muestre `QMessageBox.question` ("El nuevo resultado es parcial y el anterior era OK. ¿Sobrescribir los datos?") y llame `run_executor.confirm_partial(analysis_id, overwrite=...)` con la respuesta. Refrescar el árbol al terminar.

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:QT_QPA_PLATFORM='offscreen'; pytest tests/test_partial_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quino/gui/main_window.py tests/test_partial_prompt.py
git commit -m "feat(gui): prompt de confirmación OK→Partial al re-runear"
```

---

# FASE 5 — Auditoría QA end-to-end

## Task 5.1: Smoke-test end-to-end del flujo de workspace

**Files:**
- Test: `tests/test_workspace_e2e.py`

- [ ] **Step 1: Write the end-to-end test**

```python
# tests/test_workspace_e2e.py
from quino.application.service import ApplicationService
from quino.domain.workspace import Analysis


def test_full_workspace_flow(tmp_path):
    svc = ApplicationService()
    svc.new_workspace("E2E")
    ws = svc._workspace
    root_id = ws.root_case_ids[0]

    # 1. Add a body to the root via the cascading path used by the GUI.
    # (Use the real command-service method that adds a body.)
    # ... add body "b1" with mass "5 kg" ...

    # 2. Fork.
    from quino.services.case_cascading import CascadingEngine
    child_id = CascadingEngine(ws).fork_case(root_id, "child")

    # 3. Edit the parent mass -> cascades to the tracking child.
    CascadingEngine(ws).edit_property(root_id, "b1", "mass", _scalar("8 kg"))
    assert _body(ws, child_id, "b1").mass == _scalar("8 kg")

    # 4. Diverge child, then edit parent again -> child keeps override.
    _body(ws, child_id, "b1").mass = _scalar("2 kg")
    CascadingEngine(ws).edit_property(root_id, "b1", "mass", _scalar("9 kg"))
    assert _body(ws, child_id, "b1").mass == _scalar("2 kg")

    # 5. Save + reload round-trips at 0.4.0.
    path = tmp_path / "e2e.quino.json"
    svc.save_workspace(path)            # ajustar al método real
    svc.load_workspace(path)
    assert svc._workspace.schema_version == "0.4.0"
```

(Definir helpers `_scalar`, `_body`; usar los métodos reales de `ApplicationService` para crear/guardar/cargar. Reemplazar comentarios por código concreto al implementar.)

- [ ] **Step 2: Run test to verify it fails (or reveals bugs)**

Run: `pytest tests/test_workspace_e2e.py -v`
Expected: FAIL inicialmente; cada fallo es un bug del flujo a corregir.

- [ ] **Step 3: Fix the bugs surfaced**

Para cada fallo, aplicar systematic-debugging: localizar causa raíz, corregir en el módulo responsable, añadir/ajustar test de regresión en el archivo correspondiente.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace_e2e.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_workspace_e2e.py quino/
git commit -m "test(e2e): flujo completo de workspace (fork/cascade/override/roundtrip)"
```

---

## Task 5.2: Suite completa verde y limpieza

**Files:**
- (varios, según fallos residuales)

- [ ] **Step 1: Run the full suite**

Run: `$env:QT_QPA_PLATFORM='offscreen'; pytest tests/ -q`
Expected: idealmente todo verde. Listar fallos restantes.

- [ ] **Step 2: Fix residuals**

Corregir tests obsoletos (referencias a overlay/Run/MetricDef que queden), eliminar los que prueban comportamiento retirado, y quitar cualquier `skip` temporal añadido en Task 1.10.

- [ ] **Step 3: Verify clean removal of overlays**

Run: `git grep -n "CaseOverlay\|EntityOverlay\|cascade_property_registry\|case_overlay_validator\|divergence_warnings"`
Expected: sin resultados (o solo en docs/specs).

- [ ] **Step 4: Run full suite once more**

Run: `$env:QT_QPA_PLATFORM='offscreen'; pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: suite verde; eliminar restos de overlays y runs"
```

---

## Self-review checklist (para el ejecutor al terminar)

- [ ] Todos los `examples/*.quino.json` cargan a 0.4.0 (`tests/test_examples_load.py`).
- [ ] Fork + edición padre/hijo: cascadeo correcto y override respetado (`tests/test_cascading_edit.py`, `tests/test_workspace_e2e.py`).
- [ ] `CaseOverlay`/`EntityOverlay`/`case_overlay_validator.py`/`cascade_property_registry.py` eliminados (git grep vacío).
- [ ] Un analysis tiene un único estado de run; partial sobre ok dispara prompt; fallo no destruye datos previos (`tests/test_run_executor.py`, `tests/test_partial_prompt.py`, `tests/test_run_artifacts.py`).
- [ ] Métricas Python: crear/probar/evaluar/recalcular (`tests/test_metric_evaluator.py`, `tests/test_gui_metric_dialogs.py`).
- [ ] GUI: combobox con flecha; árboles expanden solo con triángulo; caso activo expandido y resaltado (`tests/test_theme_combobox.py`, `tests/test_tree_expand_behavior.py`, `tests/test_workflow_tree*.py`).
- [ ] Suite completa verde.
