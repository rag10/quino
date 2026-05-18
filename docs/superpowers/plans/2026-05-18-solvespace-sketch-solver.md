# Solvespace sketch solver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el solver iterativo propio del sketch por Solvespace como backend por defecto, manteniendo el actual como fallback opt-in seleccionable desde Preferences.

**Architecture:** Strategy + facade. El paquete `quino/services/sketch_solving/` define un `SketchSolverBackend` Protocol; el `SketchSolver` facade despacha al backend (`solvespace` por defecto, `legacy` opt-in). `ApplicationService.__init__` acepta `sketch_solver_backend` arg. La preferencia GUI se persiste con `QtCore.QSettings` y se aplica en caliente. El adapter de Solvespace traduce cada `SketchConstraintType` al constraint nativo, generando geometría auxiliar invisible cuando hace falta (HORIZONTAL_DISTANCE / VERTICAL_DISTANCE).

**Tech Stack:** Python 3.11+, `python-solvespace` (PyPI), PySide6 (`QtCore.QSettings`), pytest.

**Pre-requisitos:** Fases 1 y 2 del refactor completadas (ramo `refactor/fase-1-extracciones`, HEAD = ba47edf). Tests baseline = 343.

**Referencia:** `docs/superpowers/specs/2026-05-18-solvespace-sketch-solver-design.md` (spec aprobada).

---

## File Structure

```
quino/services/sketch_solving/           ← nuevo paquete
├── __init__.py                          ← re-exports
├── base.py                              ← Protocol + SketchSolveResult (movido)
├── facade.py                            ← SketchSolver (selector de backend)
├── legacy_backend.py                    ← solver iterativo actual (movido íntegro)
├── solvespace_backend.py                ← adapter nuevo
├── constraint_mapping.py                ← tabla + traducción de cada SketchConstraintType
└── _auxiliary_geometry.py               ← líneas H/V invisibles para *_DISTANCE

quino/services/sketch_solver.py          ← shim re-export (compatibilidad)
quino/gui/preferences.py                 ← Preferences wrapper QSettings (nuevo)
quino/application/service.py             ← acepta sketch_solver_backend, set_sketch_solver_backend(...)
quino/gui/main_window.py                 ← lee Preferences en __init__, dropdown en preferences dialog
tests/test_sketch_solver_solvespace.py   ← tests específicos del adapter (nuevo)
tests/test_sketch_solver_crosscheck.py   ← tests parametrizados ambos backends (nuevo)
tests/test_preferences.py                ← tests del wrapper QSettings (nuevo)
pyproject.toml                           ← añade python-solvespace
CLAUDE.md                                ← documenta el cambio
```

---

## Task 1: Verificar instalación y API real de `python-solvespace` (GATE)

**Files:**
- Modify: `pyproject.toml`
- Create: `scratch/solvespace_smoke.py` (eliminado al final)

Esta tarea es un **gate**: si `python-solvespace` no instala en el entorno actual o su API difiere drásticamente de la tabla del spec, paramos y replanteamos.

- [ ] **Step 1: Intentar instalación**

```bash
pip install python-solvespace
```

Expected: instala una wheel para Python 3.11 / 3.12 en Windows. Si falla con "no matching distribution", REPORTAR BLOQUEADO — la fase no puede continuar sin el paquete.

- [ ] **Step 2: Importar y enumerar la API pública**

```bash
python -c "import python_solvespace as ps; print([s for s in dir(ps) if not s.startswith('_')])"
```

Anotar la lista. Esperar nombres como `SolverSystem`, `Constraint`, `Entity`, `make_workplane`, `make_point`, `make_line`, etc. — pero los exactos pueden variar.

- [ ] **Step 3: Smoke con un sistema mínimo**

Crear `scratch/solvespace_smoke.py`:

```python
"""Smoke: resolver un cuadrilátero rígido (4 puntos + 4 distancias).

Si esto pasa, el paquete funciona y la API básica es identificable.
"""
import python_solvespace as ps

# Adaptar los nombres concretos a la API real tras Step 2.
# El siguiente código asume la API documentada en el README de python-solvespace:
sys = ps.SolverSystem()
wp = sys.create_2d_base()  # nombre real puede ser create_workplane / make_workplane

g = sys.create_param  # función para crear parámetros — verificar
# Crear 4 puntos: (0,0), (10,0), (10,10), (0,10)
p1 = sys.add_point_2d(0.0, 0.0, wp)
p2 = sys.add_point_2d(10.0, 0.0, wp)
p3 = sys.add_point_2d(10.0, 10.0, wp)
p4 = sys.add_point_2d(0.0, 10.0, wp)

# Constrain p1 fixed; p2..p4 free
sys.dragged(p1, wp)  # marca p1 como fijo (grupo 1)
# 4 distancias = 10:
sys.distance(p1, p2, 10.0, wp)
sys.distance(p2, p3, 10.0, wp)
sys.distance(p3, p4, 10.0, wp)
sys.distance(p4, p1, 10.0, wp)

result = sys.solve()
print("solve result:", result)
print("p2:", sys.params(p2.params))
print("p3:", sys.params(p3.params))
print("p4:", sys.params(p4.params))
```

Run: `python scratch/solvespace_smoke.py`

Expected: imprime un código de éxito y posiciones razonables (alrededor del cuadrado original).

Si los nombres reales difieren, ajustar hasta que el smoke pase. **Documentar la API real en un comentario al final del script.**

- [ ] **Step 4: Verificar tipos de constraint disponibles**

```python
# añadir al final del smoke:
print("\n--- Constraint methods ---")
print([m for m in dir(sys) if not m.startswith('_') and callable(getattr(sys, m))])
```

Confirmar que existen métodos (o equivalentes) para cada constraint de la tabla del spec: `horizontal`, `vertical`, `distance`, `coincident`, `parallel`, `perpendicular`, `equal`/`equal_length`, `angle`, `midpoint`, `symmetric`, `tangent`, `dragged`, `diameter`.

Si algún nombre difiere o falta, ANOTAR. La tabla del spec se actualiza en `constraint_mapping.py` con los nombres reales en Task 7.

- [ ] **Step 5: Añadir `python-solvespace` como dependencia**

Editar `pyproject.toml`. Sección `[project]`:

```toml
dependencies = [
    "python-solvespace>=3.0",
]
```

Si la última versión disponible es menor (`2.x`), usar `>=` con la versión instalada.

- [ ] **Step 6: Limpiar y commit**

```bash
rm scratch/solvespace_smoke.py
rmdir scratch  # si quedó vacío
git add pyproject.toml
git commit -m "feat: add python-solvespace dependency (sketch solver backend)"
```

**Report**: en el reporte, incluir la lista de constraint methods reales encontrados, para que las tareas siguientes los usen.

---

## Task 2: Crear paquete sketch_solving y mover legacy

**Files:**
- Create: `quino/services/sketch_solving/__init__.py`
- Create: `quino/services/sketch_solving/legacy_backend.py`
- Create: `quino/services/sketch_solving/base.py`
- Create: `quino/services/sketch_solving/facade.py`
- Modify: `quino/services/sketch_solver.py` (reduce a shim)

Movimiento mecánico. Tras esta tarea el comportamiento es idéntico al actual: el solver iterativo es el único backend, pero ya despachado a través de la nueva facade.

- [ ] **Step 1: Baseline**

```bash
pytest tests/ -q
```

Expected: 343 passed.

- [ ] **Step 2: Leer la estructura actual de `quino/services/sketch_solver.py`**

Tomar nota de las clases/dataclasses exportadas: `SketchSolver`, `SketchSolveResult`.

- [ ] **Step 3: Crear `base.py`**

Contenido (mover `SketchSolveResult` desde `sketch_solver.py`):

```python
# quino/services/sketch_solving/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from quino.domain.model import Project


@dataclass
class SketchSolveResult:
    success: bool
    positions: dict[str, tuple[float, float]]
    iterations: int
    max_error: float
    message: str | None = None
    constraint_errors: dict[str, float] = field(default_factory=dict)
    bad_constraints: list[str] = field(default_factory=list)
    radius_updates: dict[str, float] = field(default_factory=dict)


class SketchSolverBackend(Protocol):
    name: str

    def solve(
        self,
        project: Project,
        *,
        locked_point_ids: set[str] | None = None,
        max_iterations: int = 200,
        tolerance: float = 1e-6,
    ) -> SketchSolveResult: ...
```

- [ ] **Step 4: Crear `legacy_backend.py`**

Mover el contenido de la clase `SketchSolver` actual (de `sketch_solver.py`) a una clase nueva `LegacyIterativeBackend` en este archivo. Cambios mecánicos:

1. La clase se renombra: `class SketchSolver` → `class LegacyIterativeBackend`.
2. Añadir `name = "legacy"` como atributo de clase.
3. Importar `SketchSolveResult` desde `quino.services.sketch_solving.base` (no de `sketch_solver.py`).
4. Mantener TODA la lógica intacta. No tocar la matemática.

Header:

```python
# quino/services/sketch_solving/legacy_backend.py
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from quino.domain.model import Expression, Project, Sketch, SketchArc, SketchCircle, SketchConstraint, SketchInfiniteLine, SketchLineSegment, SketchPoint
from quino.domain.sketch_constraints import CONSTRAINT_SPECS
from quino.domain.types import SketchConstraintType
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService
from quino.services.sketch_solving.base import SketchSolveResult


class LegacyIterativeBackend:
    name = "legacy"

    def __init__(self, expression_service: ExpressionService, unit_service: UnitService) -> None:
        # ... (cuerpo idéntico al __init__ original de SketchSolver)
```

- [ ] **Step 5: Crear `facade.py`**

```python
# quino/services/sketch_solving/facade.py
from __future__ import annotations

from quino.domain.model import Project
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService
from quino.services.sketch_solving.base import SketchSolveResult, SketchSolverBackend


class SketchSolver:
    def __init__(
        self,
        expression_service: ExpressionService,
        unit_service: UnitService,
        *,
        backend: str = "solvespace",
    ) -> None:
        self._backend: SketchSolverBackend = _make_backend(
            backend, expression_service, unit_service
        )

    @property
    def backend_name(self) -> str:
        return self._backend.name

    def solve(self, project: Project, **kwargs) -> SketchSolveResult:
        return self._backend.solve(project, **kwargs)


def _make_backend(
    name: str,
    expr: ExpressionService,
    units: UnitService,
) -> SketchSolverBackend:
    if name == "solvespace":
        from quino.services.sketch_solving.solvespace_backend import SolvespaceBackend
        return SolvespaceBackend(expr, units)
    if name == "legacy":
        from quino.services.sketch_solving.legacy_backend import LegacyIterativeBackend
        return LegacyIterativeBackend(expr, units)
    raise ValueError(f"Unknown sketch solver backend: {name!r}")
```

- [ ] **Step 6: Crear `__init__.py`**

```python
# quino/services/sketch_solving/__init__.py
from quino.services.sketch_solving.base import SketchSolveResult, SketchSolverBackend
from quino.services.sketch_solving.facade import SketchSolver

__all__ = ["SketchSolver", "SketchSolveResult", "SketchSolverBackend"]
```

- [ ] **Step 7: Reducir `quino/services/sketch_solver.py` a shim**

Reemplazar todo el contenido por:

```python
# quino/services/sketch_solver.py
"""Backwards-compat shim. The implementation lives in quino.services.sketch_solving."""
from quino.services.sketch_solving import SketchSolveResult, SketchSolver

__all__ = ["SketchSolver", "SketchSolveResult"]
```

- [ ] **Step 8: Cambiar default temporal a `"legacy"` (para no romper nada todavía)**

En `quino/services/sketch_solving/facade.py`, cambiar el default temporalmente:

```python
backend: str = "legacy",  # default temporal — pasa a "solvespace" en Task 12
```

Razón: aún no existe `solvespace_backend.py`. El siguiente test debe seguir verde.

- [ ] **Step 9: Verificar tests**

```bash
pytest tests/ -q
```

Expected: 343 passed (idéntico al baseline).

- [ ] **Step 10: Commit**

```bash
git add quino/services/sketch_solving/ quino/services/sketch_solver.py
git commit -m "refactor(sketch): scaffold sketch_solving package, move legacy backend"
```

---

## Task 3: Wire `sketch_solver_backend` en `ApplicationService`

**Files:**
- Modify: `quino/application/service.py`

- [ ] **Step 1: Localizar la construcción actual de `SketchSolver` en `ApplicationService.__init__`**

```bash
grep -nE "SketchSolver\(" quino/application/service.py
```

Anotar la línea exacta.

- [ ] **Step 2: Añadir el argumento al `__init__`**

Modificar la firma:

```python
def __init__(self, *, sketch_solver_backend: str = "legacy") -> None:
    ...
    self._sketch_solver_backend = sketch_solver_backend
    self.sketch_solver = SketchSolver(
        self.expression_service,
        self.unit_service,
        backend=sketch_solver_backend,
    )
```

Nota: usar `"legacy"` como default temporal — pasa a `"solvespace"` en Task 12.

- [ ] **Step 3: Añadir método `set_sketch_solver_backend`**

Al final de la clase (antes de los helpers privados):

```python
def set_sketch_solver_backend(self, name: str) -> None:
    """Switch the sketch solver backend at runtime (e.g. from Preferences dialog)."""
    if name not in ("solvespace", "legacy"):
        raise ValueError(f"Unknown sketch solver backend: {name!r}")
    self._sketch_solver_backend = name
    self.sketch_solver = SketchSolver(
        self.expression_service,
        self.unit_service,
        backend=name,
    )
```

- [ ] **Step 4: Tests existentes deben seguir pasando**

```bash
pytest tests/ -q
```

Expected: 343 passed.

- [ ] **Step 5: Test de regresión del argumento**

Añadir a `tests/test_application.py` (al final, sin tocar tests existentes):

```python
def test_application_service_default_solver_backend():
    svc = ApplicationService()
    assert svc.sketch_solver.backend_name == "legacy"  # cambiará en Task 12


def test_application_service_explicit_legacy_backend():
    svc = ApplicationService(sketch_solver_backend="legacy")
    assert svc.sketch_solver.backend_name == "legacy"


def test_set_sketch_solver_backend_swaps_instance():
    svc = ApplicationService(sketch_solver_backend="legacy")
    old = svc.sketch_solver
    svc.set_sketch_solver_backend("legacy")  # re-set, still legacy
    assert svc.sketch_solver is not old
    assert svc.sketch_solver.backend_name == "legacy"


def test_set_sketch_solver_backend_rejects_unknown():
    import pytest
    svc = ApplicationService()
    with pytest.raises(ValueError, match="Unknown sketch solver backend"):
        svc.set_sketch_solver_backend("xyz")
```

Run: `pytest tests/test_application.py -k "solver_backend" -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add quino/application/service.py tests/test_application.py
git commit -m "feat(application): add sketch_solver_backend arg and runtime swap"
```

---

## Task 4: SolvespaceBackend skeleton (entidades, sin constraints)

**Files:**
- Create: `quino/services/sketch_solving/solvespace_backend.py`
- Create: `tests/test_sketch_solver_solvespace.py`

Esta tarea crea la armazón del adapter: traduce puntos y entidades geométricas a Solvespace, resuelve un sistema vacío (sin constraints) y devuelve las posiciones iniciales. **No** procesa constraints todavía.

- [ ] **Step 1: Crear `solvespace_backend.py` con la armazón**

```python
# quino/services/sketch_solving/solvespace_backend.py
from __future__ import annotations

import math

import python_solvespace as ps

from quino.domain.model import (
    Project,
    Sketch,
    SketchArc,
    SketchCircle,
    SketchConstraint,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
)
from quino.domain.types import SketchConstraintType
from quino.services.expressions import ExpressionService
from quino.services.sketch_solving.base import SketchSolveResult
from quino.services.units import UnitService


class SolvespaceBackend:
    name = "solvespace"

    def __init__(self, expression_service: ExpressionService, unit_service: UnitService) -> None:
        self._expressions = expression_service
        self._units = unit_service

    def solve(
        self,
        project: Project,
        *,
        locked_point_ids: set[str] | None = None,
        max_iterations: int = 200,
        tolerance: float = 1e-6,
    ) -> SketchSolveResult:
        sketch = project.sketch
        if sketch is None:
            return SketchSolveResult(True, {}, 0, 0.0, None)

        point_map = {p.id: p for p in sketch.points()}
        if not sketch.constraints:
            # Sin constraints: devolver las posiciones evaluadas tal cual.
            positions = {
                pid: self._evaluate_point(project, p) for pid, p in point_map.items()
            }
            return SketchSolveResult(True, positions, 0, 0.0, None)

        try:
            return self._solve_with_system(project, sketch, locked_point_ids or set())
        except Exception as exc:  # pragma: no cover - paranoid mapping guard
            return SketchSolveResult(
                False,
                {pid: self._evaluate_point(project, p) for pid, p in point_map.items()},
                0,
                math.inf,
                f"Mapping error: {exc}",
            )

    def _solve_with_system(
        self,
        project: Project,
        sketch: Sketch,
        locked: set[str],
    ) -> SketchSolveResult:
        sys = ps.SolverSystem()
        wp = sys.create_2d_base()  # AJUSTAR si Task 1 reportó otro nombre

        # 1. Identificar puntos fijos: locked + referencias de FIX
        fixed_ids = set(locked)
        for c in sketch.constraints.values():
            if c.type is SketchConstraintType.FIX:
                fixed_ids.update(c.references)

        # 2. Crear handles de puntos
        point_handles: dict[str, object] = {}
        for pid, p in {p.id: p for p in sketch.points()}.items():
            x, y = self._evaluate_point(project, p)
            handle = sys.add_point_2d(x, y, wp)  # AJUSTAR si Task 1 reportó otro nombre
            if pid in fixed_ids:
                sys.dragged(handle, wp)  # AJUSTAR si Task 1 reportó otro nombre
            point_handles[pid] = handle

        # 3. Crear handles de entidades geométricas (línea/círculo/arco)
        entity_handles: dict[str, object] = {}
        for entity in sketch.entities():
            handle = self._create_entity(sys, wp, entity, point_handles)
            if handle is not None:
                entity_handles[entity.id] = handle

        # 4. Constraints — Task 6 en adelante. Por ahora, no emitir nada.

        # 5. Resolver
        result_code = sys.solve()

        # 6. Lectura
        positions = {
            pid: self._read_point(sys, handle) for pid, handle in point_handles.items()
        }
        success = self._is_success(result_code)
        return SketchSolveResult(
            success=success,
            positions=positions,
            iterations=0,
            max_error=0.0 if success else math.inf,
            message=None if success else f"Solvespace result code: {result_code}",
        )

    def _evaluate_point(self, project: Project, point: SketchPoint) -> tuple[float, float]:
        x = self._expressions.evaluate_property(point.x, project.parameters).value
        y = self._expressions.evaluate_property(point.y, project.parameters).value
        return (x, y)

    def _create_entity(self, sys, wp, entity, points: dict[str, object]):
        if isinstance(entity, SketchLineSegment):
            return sys.add_line_2d(points[entity.start_id], points[entity.end_id], wp)
        if isinstance(entity, SketchInfiniteLine):
            return sys.add_line_2d(points[entity.point_a_id], points[entity.point_b_id], wp)
        if isinstance(entity, SketchCircle):
            return sys.add_circle(points[entity.center_id], entity.radius_mm, wp)
        if isinstance(entity, SketchArc):
            return sys.add_arc(
                points[entity.center_id],
                points[entity.start_id],
                points[entity.end_id],
                wp,
            )
        return None

    def _read_point(self, sys, handle) -> tuple[float, float]:
        # AJUSTAR según API real de python-solvespace para extraer x,y de un punto resuelto.
        # Pattern típico: sys.params(handle.params) devuelve (x, y).
        params = sys.params(handle.params)
        return (float(params[0]), float(params[1]))

    @staticmethod
    def _is_success(code) -> bool:
        # AJUSTAR según el enum real de result codes.
        # Tras Task 1: anotar los códigos OK / REDUNDANT_OKAY.
        return code == 0  # placeholder — sustituir con constante real
```

**NOTA**: este código asume nombres de API que Task 1 confirma. Si Task 1 reportó nombres distintos (p.ej. `make_workplane` en vez de `create_2d_base`), aplicar los reales aquí antes de seguir.

- [ ] **Step 2: Crear test smoke**

`tests/test_sketch_solver_solvespace.py`:

```python
"""Tests específicos del SolvespaceBackend (no parametrizados — sólo este backend)."""
from quino import ApplicationService
from quino.services.sketch_solving.solvespace_backend import SolvespaceBackend
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService


def _make_backend() -> SolvespaceBackend:
    return SolvespaceBackend(ExpressionService(), UnitService())


def test_solve_empty_sketch_returns_success():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success is True
    assert result.positions == {}


def test_solve_sketch_with_only_points_returns_positions():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("10 mm", "20 mm", "P1")
    p2 = svc.create_sketch_point("30 mm", "40 mm", "P2")
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success is True
    assert result.positions[p1] == (10.0, 20.0)
    assert result.positions[p2] == (30.0, 40.0)
```

- [ ] **Step 3: Run smoke**

```bash
pytest tests/test_sketch_solver_solvespace.py -v
```

Expected: 2 passed. Si la API real de python-solvespace difiere de lo asumido, las pruebas fallan con errores de import / atributo concretos — ajustar `solvespace_backend.py` con los nombres reales reportados en Task 1.

- [ ] **Step 4: Verificar suite completa**

```bash
pytest tests/ -q
```

Expected: 347+ passed (343 baseline + 4 nuevos en Task 3 + 2 nuevos aquí — los conteos exactos dependen de la suma acumulada de tasks).

- [ ] **Step 5: Commit**

```bash
git add quino/services/sketch_solving/solvespace_backend.py tests/test_sketch_solver_solvespace.py
git commit -m "feat(sketch): SolvespaceBackend skeleton (entities, no constraints yet)"
```

---

## Task 5: Constraint mapping — distancias y coincidencias

**Files:**
- Create: `quino/services/sketch_solving/constraint_mapping.py`
- Modify: `quino/services/sketch_solving/solvespace_backend.py`
- Modify: `tests/test_sketch_solver_solvespace.py`

Primera tanda de constraints: las más comunes y simples.

- [ ] **Step 1: Crear `constraint_mapping.py`** con esqueleto y los primeros mappings

```python
# quino/services/sketch_solving/constraint_mapping.py
from __future__ import annotations

from quino.domain.model import Project, Sketch, SketchConstraint
from quino.domain.types import SketchConstraintType


def emit_constraint(
    sys,
    wp,
    constraint: SketchConstraint,
    *,
    points: dict[str, object],
    entities: dict[str, object],
    project: Project,
) -> None:
    """Emit a native Solvespace constraint for the given QUINO constraint.

    Mutates `sys` by adding the appropriate constraint. Raises if `constraint`
    references unknown points/entities or if its type is not yet supported.
    """
    t = constraint.type
    handler = _HANDLERS.get(t)
    if handler is None:
        raise ValueError(f"Unsupported sketch constraint type: {t}")
    handler(sys, wp, constraint, points, entities, project)


def _emit_distance(sys, wp, c, points, entities, project):
    if len(c.references) != 2:
        raise ValueError(f"distance expects 2 references, got {c.references}")
    ref_a, ref_b = c.references
    value_mm = float(c.value or 0.0)
    a = points.get(ref_a) or entities.get(ref_a)
    b = points.get(ref_b) or entities.get(ref_b)
    if a is None or b is None:
        raise ValueError(f"distance constraint refers to unknown ids: {c.references}")
    sys.distance(a, b, value_mm, wp)


def _emit_coincident(sys, wp, c, points, entities, project):
    if len(c.references) < 2:
        raise ValueError(f"coincident expects ≥2 references, got {c.references}")
    refs = list(c.references)
    primary = points.get(refs[0]) or entities.get(refs[0])
    for other_id in refs[1:]:
        other = points.get(other_id) or entities.get(other_id)
        if other is None or primary is None:
            raise ValueError(f"coincident refers to unknown id: {other_id}")
        sys.coincident(primary, other, wp)


def _emit_horizontal(sys, wp, c, points, entities, project):
    if not c.references:
        raise ValueError("horizontal expects a line reference")
    line = entities.get(c.references[0])
    if line is None:
        raise ValueError(f"horizontal refers to unknown entity: {c.references[0]}")
    sys.horizontal(line, wp)


def _emit_vertical(sys, wp, c, points, entities, project):
    if not c.references:
        raise ValueError("vertical expects a line reference")
    line = entities.get(c.references[0])
    if line is None:
        raise ValueError(f"vertical refers to unknown entity: {c.references[0]}")
    sys.vertical(line, wp)


_HANDLERS = {
    SketchConstraintType.DISTANCE: _emit_distance,
    SketchConstraintType.COINCIDENT: _emit_coincident,
    SketchConstraintType.HORIZONTAL: _emit_horizontal,
    SketchConstraintType.VERTICAL: _emit_vertical,
}
```

**AJUSTAR** los nombres `sys.distance`, `sys.coincident`, `sys.horizontal`, `sys.vertical` si Task 1 reportó otros (por ejemplo `sys.add_constraint_distance`).

- [ ] **Step 2: Integrar `emit_constraint` en el backend**

En `solvespace_backend.py`, dentro de `_solve_with_system`, después de crear las entidades:

```python
# 4. Emit constraints (skip FIX — those just marked points as dragged earlier)
from quino.services.sketch_solving.constraint_mapping import emit_constraint
unsupported: list[str] = []
for c in sketch.constraints.values():
    if c.type is SketchConstraintType.FIX:
        continue
    try:
        emit_constraint(
            sys, wp, c,
            points=point_handles,
            entities=entity_handles,
            project=project,
        )
    except ValueError as e:
        unsupported.append(c.id)
```

Y al final, si `unsupported` no está vacío, incluirlo en `bad_constraints` del resultado.

Concretamente, sustituir el `return SketchSolveResult(...)` al final por:

```python
result_code = sys.solve()
positions = {
    pid: self._read_point(sys, handle) for pid, handle in point_handles.items()
}
success = self._is_success(result_code) and not unsupported
return SketchSolveResult(
    success=success,
    positions=positions,
    iterations=0,
    max_error=0.0 if success else math.inf,
    message=None if success else f"Solvespace code: {result_code}; unsupported: {unsupported}",
    bad_constraints=unsupported,
)
```

- [ ] **Step 3: Tests**

Añadir a `tests/test_sketch_solver_solvespace.py`:

```python
def test_distance_constraint_pulls_points_to_target_length():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    # fijar p1, restringir distancia p1-p2 = 10 mm
    svc.create_sketch_constraint("c_fix", "fix", [p1], None, None)
    svc.create_sketch_constraint("c_dist", "distance", [p1, p2], "10 mm", None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    x2, y2 = result.positions[p2]
    assert abs(((x2 - 0.0)**2 + (y2 - 0.0)**2)**0.5 - 10.0) < 1e-4


def test_horizontal_constraint_aligns_line():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "3 mm", "P2")
    line = svc.create_sketch_line_segment("L1", p1, p2)
    svc.create_sketch_constraint("c_fix", "fix", [p1], None, None)
    svc.create_sketch_constraint("c_h", "horizontal", [line], None, None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    _, y2 = result.positions[p2]
    assert abs(y2 - 0.0) < 1e-4


def test_coincident_points_collapse_to_same_position():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "10 mm", "P2")
    svc.create_sketch_constraint("c_fix", "fix", [p1], None, None)
    svc.create_sketch_constraint("c_co", "coincident", [p1, p2], None, None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    assert abs(result.positions[p2][0] - 0.0) < 1e-4
    assert abs(result.positions[p2][1] - 0.0) < 1e-4
```

NOTA: las firmas exactas de `create_sketch_constraint` están en `quino/application/commands/sketch_commands.py`. Ajustar argumentos a la firma real (probablemente `create_sketch_constraint(name, constraint_type, references, value, position)`).

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_sketch_solver_solvespace.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add quino/services/sketch_solving/constraint_mapping.py quino/services/sketch_solving/solvespace_backend.py tests/test_sketch_solver_solvespace.py
git commit -m "feat(sketch/solvespace): distance, coincident, horizontal, vertical constraints"
```

---

## Task 6: Constraints geométricos — parallel, perpendicular, equal_length, angle, midpoint

**Files:**
- Modify: `quino/services/sketch_solving/constraint_mapping.py`
- Modify: `tests/test_sketch_solver_solvespace.py`

- [ ] **Step 1: Añadir handlers**

En `constraint_mapping.py`, antes de `_HANDLERS`:

```python
def _emit_parallel(sys, wp, c, points, entities, project):
    if len(c.references) != 2:
        raise ValueError(f"parallel expects 2 lines, got {c.references}")
    l1 = entities.get(c.references[0])
    l2 = entities.get(c.references[1])
    if l1 is None or l2 is None:
        raise ValueError("parallel: unknown line reference")
    sys.parallel(l1, l2, wp)


def _emit_perpendicular(sys, wp, c, points, entities, project):
    if len(c.references) != 2:
        raise ValueError(f"perpendicular expects 2 lines, got {c.references}")
    l1 = entities.get(c.references[0])
    l2 = entities.get(c.references[1])
    if l1 is None or l2 is None:
        raise ValueError("perpendicular: unknown line reference")
    sys.perpendicular(l1, l2, wp)


def _emit_equal_length(sys, wp, c, points, entities, project):
    if len(c.references) != 2:
        raise ValueError(f"equal_length expects 2 lines, got {c.references}")
    l1 = entities.get(c.references[0])
    l2 = entities.get(c.references[1])
    if l1 is None or l2 is None:
        raise ValueError("equal_length: unknown line reference")
    sys.equal(l1, l2, wp)


def _emit_angle(sys, wp, c, points, entities, project):
    if len(c.references) != 2:
        raise ValueError(f"angle expects 2 lines, got {c.references}")
    l1 = entities.get(c.references[0])
    l2 = entities.get(c.references[1])
    deg = float(c.value or 0.0)
    if l1 is None or l2 is None:
        raise ValueError("angle: unknown line reference")
    sys.angle(l1, l2, deg, wp)


def _emit_midpoint(sys, wp, c, points, entities, project):
    if len(c.references) != 2:
        raise ValueError(f"midpoint expects point and line refs, got {c.references}")
    point = points.get(c.references[0])
    line = entities.get(c.references[1])
    if point is None or line is None:
        raise ValueError("midpoint: unknown point or line")
    sys.midpoint(point, line, wp)
```

Actualizar `_HANDLERS`:

```python
_HANDLERS = {
    SketchConstraintType.DISTANCE: _emit_distance,
    SketchConstraintType.COINCIDENT: _emit_coincident,
    SketchConstraintType.HORIZONTAL: _emit_horizontal,
    SketchConstraintType.VERTICAL: _emit_vertical,
    SketchConstraintType.PARALLEL: _emit_parallel,
    SketchConstraintType.PERPENDICULAR: _emit_perpendicular,
    SketchConstraintType.EQUAL_LENGTH: _emit_equal_length,
    SketchConstraintType.ANGLE: _emit_angle,
    SketchConstraintType.MIDPOINT: _emit_midpoint,
}
```

**AJUSTAR** nombres de métodos `sys.parallel`, `sys.perpendicular`, etc., si Task 1 los reportó distintos.

- [ ] **Step 2: Tests**

Añadir a `tests/test_sketch_solver_solvespace.py`:

```python
def test_parallel_lines():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("0 mm", "5 mm", "P3")
    p4 = svc.create_sketch_point("10 mm", "8 mm", "P4")
    l1 = svc.create_sketch_line_segment("L1", p1, p2)
    l2 = svc.create_sketch_line_segment("L2", p3, p4)
    svc.create_sketch_constraint("c_fix1", "fix", [p1], None, None)
    svc.create_sketch_constraint("c_fix2", "fix", [p2], None, None)
    svc.create_sketch_constraint("c_fix3", "fix", [p3], None, None)
    svc.create_sketch_constraint("c_par", "parallel", [l1, l2], None, None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    # L1 es horizontal (p1→p2 a lo largo de y=0); L2 paralela → p4.y = p3.y = 5
    assert abs(result.positions[p4][1] - 5.0) < 1e-4


def test_perpendicular_lines():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("0 mm", "0 mm", "P3")
    p4 = svc.create_sketch_point("5 mm", "5 mm", "P4")
    l1 = svc.create_sketch_line_segment("L1", p1, p2)
    l2 = svc.create_sketch_line_segment("L2", p3, p4)
    svc.create_sketch_constraint("c_fix1", "fix", [p1, p2, p3], None, None)
    svc.create_sketch_constraint("c_perp", "perpendicular", [l1, l2], None, None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    # L1 a lo largo de x; L2 perpendicular → p4.x ≈ p3.x = 0
    assert abs(result.positions[p4][0] - 0.0) < 1e-4


def test_equal_length_lines():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("0 mm", "5 mm", "P3")
    p4 = svc.create_sketch_point("3 mm", "5 mm", "P4")
    l1 = svc.create_sketch_line_segment("L1", p1, p2)
    l2 = svc.create_sketch_line_segment("L2", p3, p4)
    svc.create_sketch_constraint("c_fix1", "fix", [p1, p2, p3], None, None)
    svc.create_sketch_constraint("c_eq", "equal_length", [l1, l2], None, None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    x4, y4 = result.positions[p4]
    length = ((x4 - 0.0)**2 + (y4 - 5.0)**2)**0.5
    assert abs(length - 10.0) < 1e-4


def test_angle_between_lines():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("0 mm", "0 mm", "P3")
    p4 = svc.create_sketch_point("10 mm", "5 mm", "P4")
    l1 = svc.create_sketch_line_segment("L1", p1, p2)
    l2 = svc.create_sketch_line_segment("L2", p3, p4)
    svc.create_sketch_constraint("c_fix1", "fix", [p1, p2, p3], None, None)
    svc.create_sketch_constraint("c_ang", "angle", [l1, l2], "45 deg", None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    # L1 a lo largo del eje x; L2 a 45° → p4 sobre la línea y = x
    x4, y4 = result.positions[p4]
    assert abs(x4 - y4) < 1e-3


def test_midpoint_constraint():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p_a = svc.create_sketch_point("0 mm", "0 mm", "PA")
    p_b = svc.create_sketch_point("10 mm", "0 mm", "PB")
    p_mid = svc.create_sketch_point("3 mm", "1 mm", "PM")
    line = svc.create_sketch_line_segment("L", p_a, p_b)
    svc.create_sketch_constraint("c_fix", "fix", [p_a, p_b], None, None)
    svc.create_sketch_constraint("c_mid", "midpoint", [p_mid, line], None, None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    assert abs(result.positions[p_mid][0] - 5.0) < 1e-4
    assert abs(result.positions[p_mid][1] - 0.0) < 1e-4
```

- [ ] **Step 3: Run**

```bash
pytest tests/test_sketch_solver_solvespace.py -v
```

Expected: 10 passed.

- [ ] **Step 4: Commit**

```bash
git add quino/services/sketch_solving/constraint_mapping.py tests/test_sketch_solver_solvespace.py
git commit -m "feat(sketch/solvespace): parallel, perpendicular, equal_length, angle, midpoint"
```

---

## Task 7: Constraints — collinear, symmetric, on_circle, tangent

**Files:**
- Modify: `quino/services/sketch_solving/constraint_mapping.py`
- Modify: `tests/test_sketch_solver_solvespace.py`

- [ ] **Step 1: Añadir handlers**

```python
def _emit_collinear(sys, wp, c, points, entities, project):
    """N+ points collinear: pick first two as anchor line; constrain rest on it."""
    if len(c.references) < 3:
        raise ValueError(f"collinear expects ≥3 point references, got {c.references}")
    anchor_a = points.get(c.references[0])
    anchor_b = points.get(c.references[1])
    if anchor_a is None or anchor_b is None:
        raise ValueError("collinear: anchor points unknown")
    # Sintetizar una línea auxiliar entre los dos primeros
    aux_line = sys.add_line_2d(anchor_a, anchor_b, wp)
    for pid in c.references[2:]:
        p = points.get(pid)
        if p is None:
            raise ValueError(f"collinear: unknown point {pid}")
        sys.coincident(p, aux_line, wp)


def _emit_symmetric(sys, wp, c, points, entities, project):
    if len(c.references) != 3:
        raise ValueError(f"symmetric expects (p1, p2, line), got {c.references}")
    p1 = points.get(c.references[0])
    p2 = points.get(c.references[1])
    line = entities.get(c.references[2])
    if p1 is None or p2 is None or line is None:
        raise ValueError("symmetric: unknown reference")
    sys.symmetric(p1, p2, line, wp)


def _emit_on_circle(sys, wp, c, points, entities, project):
    if len(c.references) != 2:
        raise ValueError(f"on_circle expects (point, circle/arc), got {c.references}")
    point = points.get(c.references[0])
    curve = entities.get(c.references[1])
    if point is None or curve is None:
        raise ValueError("on_circle: unknown reference")
    sys.coincident(point, curve, wp)


def _emit_tangent(sys, wp, c, points, entities, project):
    if len(c.references) != 2:
        raise ValueError(f"tangent expects 2 entity refs, got {c.references}")
    e1 = entities.get(c.references[0])
    e2 = entities.get(c.references[1])
    if e1 is None or e2 is None:
        raise ValueError("tangent: unknown entity reference")
    # Solvespace distingue arc-line vs curve-curve.
    # Identificar por tipo del primer/segundo arg en el proyecto.
    sketch = project.sketch
    e1_obj = sketch.entity_by_id(c.references[0]) if sketch else None
    e2_obj = sketch.entity_by_id(c.references[1]) if sketch else None
    from quino.domain.model import SketchArc, SketchCircle, SketchLineSegment, SketchInfiniteLine
    line_types = (SketchLineSegment, SketchInfiniteLine)
    curve_types = (SketchArc, SketchCircle)
    if isinstance(e1_obj, line_types) and isinstance(e2_obj, curve_types):
        sys.arc_line_tangent(e2, e1, wp)
    elif isinstance(e1_obj, curve_types) and isinstance(e2_obj, line_types):
        sys.arc_line_tangent(e1, e2, wp)
    else:
        sys.curve_curve_tangent(e1, e2, wp)
```

Actualizar `_HANDLERS`:

```python
_HANDLERS = {
    ...  # los anteriores
    SketchConstraintType.COLLINEAR: _emit_collinear,
    SketchConstraintType.SYMMETRIC: _emit_symmetric,
    SketchConstraintType.ON_CIRCLE: _emit_on_circle,
    SketchConstraintType.TANGENT: _emit_tangent,
}
```

**NOTA**: `sketch.entity_by_id(...)` puede no existir. Verificar con grep en `quino/domain/model.py`. Si no existe, sustituir por un mini-helper o expone `entity_by_id` en `Sketch` con un `dict` lookup.

- [ ] **Step 2: Tests**

Añadir:

```python
def test_collinear_three_points():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("5 mm", "3 mm", "P3")
    svc.create_sketch_constraint("c_fix", "fix", [p1, p2], None, None)
    svc.create_sketch_constraint("c_col", "collinear", [p1, p2, p3], None, None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    assert abs(result.positions[p3][1] - 0.0) < 1e-4


def test_on_circle_pulls_point_to_circumference():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    center = svc.create_sketch_point("0 mm", "0 mm", "C")
    circle = svc.create_sketch_circle("Circ", center, "10 mm")
    pt = svc.create_sketch_point("5 mm", "5 mm", "PT")
    svc.create_sketch_constraint("c_fix", "fix", [center], None, None)
    svc.create_sketch_constraint("c_on", "on_circle", [pt, circle], None, None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    x, y = result.positions[pt]
    radius = (x*x + y*y) ** 0.5
    assert abs(radius - 10.0) < 1e-3
```

NOTA: la firma exacta de `create_sketch_circle` en el codebase puede ser `(name, center_point_id, radius_expression)`. Ajustar.

- [ ] **Step 3: Run**

```bash
pytest tests/test_sketch_solver_solvespace.py -v
```

Expected: 12 passed.

- [ ] **Step 4: Commit**

```bash
git add quino/services/sketch_solving/constraint_mapping.py tests/test_sketch_solver_solvespace.py
git commit -m "feat(sketch/solvespace): collinear, symmetric, on_circle, tangent"
```

---

## Task 8: Constraint RADIUS (diámetro) + radius_updates

**Files:**
- Modify: `quino/services/sketch_solving/constraint_mapping.py`
- Modify: `quino/services/sketch_solving/solvespace_backend.py`
- Modify: `tests/test_sketch_solver_solvespace.py`

Solvespace usa diámetro; QUINO usa radio. Conversión y readback.

- [ ] **Step 1: Handler radius**

```python
def _emit_radius(sys, wp, c, points, entities, project):
    if len(c.references) != 1:
        raise ValueError(f"radius expects 1 entity ref, got {c.references}")
    curve = entities.get(c.references[0])
    if curve is None:
        raise ValueError("radius: unknown entity")
    radius_mm = float(c.value or 0.0)
    sys.diameter(curve, 2.0 * radius_mm, wp)
```

Actualizar `_HANDLERS`:

```python
SketchConstraintType.RADIUS: _emit_radius,
```

- [ ] **Step 2: Readback de radios en `solvespace_backend.py`**

Después del solve, leer el radio actual de circles/arcs y construir `radius_updates`:

```python
radius_updates: dict[str, float] = {}
for entity in sketch.entities():
    handle = entity_handles.get(entity.id)
    if handle is None:
        continue
    from quino.domain.model import SketchArc, SketchCircle
    if isinstance(entity, (SketchArc, SketchCircle)):
        # AJUSTAR según API real: probablemente sys.params(handle.distance) o
        # un campo handle.radius accesible.
        new_radius = self._read_radius(sys, handle)
        if new_radius is not None:
            radius_updates[entity.id] = new_radius
```

Y método helper:

```python
def _read_radius(self, sys, handle) -> float | None:
    """Read post-solve radius of a circle/arc. Returns None if unknown."""
    try:
        # AJUSTAR según API real
        return float(sys.params(handle.distance)[0])
    except Exception:
        return None
```

Pasar `radius_updates` al resultado final:

```python
return SketchSolveResult(
    success=success,
    positions=positions,
    iterations=0,
    max_error=0.0 if success else math.inf,
    message=...,
    bad_constraints=unsupported,
    radius_updates=radius_updates,
)
```

- [ ] **Step 3: Test**

```python
def test_radius_constraint_updates_circle_radius():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    center = svc.create_sketch_point("0 mm", "0 mm", "C")
    circle = svc.create_sketch_circle("Circ", center, "5 mm")
    svc.create_sketch_constraint("c_fix", "fix", [center], None, None)
    svc.create_sketch_constraint("c_r", "radius", [circle], "12 mm", None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    assert circle in result.radius_updates
    assert abs(result.radius_updates[circle] - 12.0) < 1e-4
```

- [ ] **Step 4: Run**

```bash
pytest tests/test_sketch_solver_solvespace.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add quino/services/sketch_solving/constraint_mapping.py quino/services/sketch_solving/solvespace_backend.py tests/test_sketch_solver_solvespace.py
git commit -m "feat(sketch/solvespace): RADIUS constraint + radius_updates readback"
```

---

## Task 9: HORIZONTAL_DISTANCE / VERTICAL_DISTANCE con geometría auxiliar

**Files:**
- Create: `quino/services/sketch_solving/_auxiliary_geometry.py`
- Modify: `quino/services/sketch_solving/constraint_mapping.py`
- Modify: `tests/test_sketch_solver_solvespace.py`

- [ ] **Step 1: Crear `_auxiliary_geometry.py`**

```python
# quino/services/sketch_solving/_auxiliary_geometry.py
"""Helpers que sintetizan geometría auxiliar invisible para el solve.

La geometría auxiliar vive sólo dentro del System de Solvespace; jamás entra
al dominio (Project). Se descarta junto con el System al terminar el solve.
"""
from __future__ import annotations


def add_horizontal_aux_line(sys, wp, anchor_point):
    """Crea una línea horizontal auxiliar que pasa por `anchor_point`.

    Returns the line handle. The auxiliary second-point handle is internal —
    not exposed; the line itself is what callers use for distance constraints.
    """
    aux_pt = sys.add_point_2d(0.0, 0.0, wp)  # posición inicial arbitraria
    aux_line = sys.add_line_2d(anchor_point, aux_pt, wp)
    sys.horizontal(aux_line, wp)
    return aux_line


def add_vertical_aux_line(sys, wp, anchor_point):
    """Crea una línea vertical auxiliar que pasa por `anchor_point`."""
    aux_pt = sys.add_point_2d(0.0, 0.0, wp)
    aux_line = sys.add_line_2d(anchor_point, aux_pt, wp)
    sys.vertical(aux_line, wp)
    return aux_line
```

**AJUSTAR** nombres según API real.

- [ ] **Step 2: Handlers en constraint_mapping**

```python
from quino.services.sketch_solving._auxiliary_geometry import (
    add_horizontal_aux_line,
    add_vertical_aux_line,
)


def _emit_horizontal_distance(sys, wp, c, points, entities, project):
    if len(c.references) != 2:
        raise ValueError(f"horizontal_distance expects 2 points, got {c.references}")
    p1 = points.get(c.references[0])
    p2 = points.get(c.references[1])
    if p1 is None or p2 is None:
        raise ValueError("horizontal_distance: unknown point")
    distance_mm = float(c.value or 0.0)
    aux_line = add_horizontal_aux_line(sys, wp, p1)
    sys.distance(p2, aux_line, distance_mm, wp)


def _emit_vertical_distance(sys, wp, c, points, entities, project):
    if len(c.references) != 2:
        raise ValueError(f"vertical_distance expects 2 points, got {c.references}")
    p1 = points.get(c.references[0])
    p2 = points.get(c.references[1])
    if p1 is None or p2 is None:
        raise ValueError("vertical_distance: unknown point")
    distance_mm = float(c.value or 0.0)
    aux_line = add_vertical_aux_line(sys, wp, p1)
    sys.distance(p2, aux_line, distance_mm, wp)
```

Actualizar `_HANDLERS`:

```python
SketchConstraintType.HORIZONTAL_DISTANCE: _emit_horizontal_distance,
SketchConstraintType.VERTICAL_DISTANCE: _emit_vertical_distance,
```

- [ ] **Step 3: Tests**

```python
def test_horizontal_distance_constrains_x_delta():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("3 mm", "7 mm", "P2")
    svc.create_sketch_constraint("c_fix", "fix", [p1], None, None)
    svc.create_sketch_constraint("c_hd", "horizontal_distance", [p1, p2], "10 mm", None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    x2, _ = result.positions[p2]
    assert abs(abs(x2 - 0.0) - 10.0) < 1e-4  # |dx| = 10


def test_vertical_distance_constrains_y_delta():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("3 mm", "2 mm", "P2")
    svc.create_sketch_constraint("c_fix", "fix", [p1], None, None)
    svc.create_sketch_constraint("c_vd", "vertical_distance", [p1, p2], "8 mm", None)
    backend = _make_backend()
    result = backend.solve(svc.project)
    assert result.success, result.message
    _, y2 = result.positions[p2]
    assert abs(abs(y2 - 0.0) - 8.0) < 1e-4


def test_no_aux_geometry_in_project_after_solve():
    """Garantiza el invariante: la geom auxiliar no entra al Project."""
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("3 mm", "0 mm", "P2")
    svc.create_sketch_constraint("c_fix", "fix", [p1], None, None)
    svc.create_sketch_constraint("c_hd", "horizontal_distance", [p1, p2], "10 mm", None)
    point_count_before = len(svc.project.sketch.points())
    entity_count_before = len(list(svc.project.sketch.entities()))
    backend = _make_backend()
    backend.solve(svc.project)
    assert len(svc.project.sketch.points()) == point_count_before
    assert len(list(svc.project.sketch.entities())) == entity_count_before
```

- [ ] **Step 4: Run**

```bash
pytest tests/test_sketch_solver_solvespace.py -v
```

Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add quino/services/sketch_solving/_auxiliary_geometry.py quino/services/sketch_solving/constraint_mapping.py tests/test_sketch_solver_solvespace.py
git commit -m "feat(sketch/solvespace): horizontal_distance / vertical_distance via auxiliary lines"
```

---

## Task 10: Drag preview con `locked_point_ids`

**Files:**
- Modify: `tests/test_sketch_solver_solvespace.py`

`locked_point_ids` ya se procesan en `_solve_with_system` (Task 4). Esta tarea es **sólo añadir tests**.

- [ ] **Step 1: Tests**

```python
def test_locked_points_remain_fixed_during_solve():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    svc.create_sketch_constraint("c_d", "distance", [p1, p2], "10 mm", None)
    backend = _make_backend()
    # bloquear p1 y p2: ambos puntos fijos, la distancia es incompatible (5 ≠ 10).
    # Solvespace debería reportar fallo.
    result = backend.solve(svc.project, locked_point_ids={p1, p2})
    # p1, p2 no se mueven:
    assert abs(result.positions[p1][0] - 0.0) < 1e-6
    assert abs(result.positions[p2][0] - 5.0) < 1e-6


def test_drag_pattern_moves_only_dragged_point():
    """Patrón típico de drag: todos fijos excepto el arrastrado."""
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("0 mm", "0 mm", "P3")
    svc.create_sketch_constraint("c_d1", "distance", [p1, p2], "5 mm", None)
    svc.create_sketch_constraint("c_d2", "distance", [p2, p3], "5 mm", None)
    backend = _make_backend()
    # arrastramos p3: bloqueamos p1 y p2
    result = backend.solve(svc.project, locked_point_ids={p1, p2})
    assert result.success, result.message
    # p1, p2 no se movieron
    assert abs(result.positions[p1][0] - 0.0) < 1e-6
    assert abs(result.positions[p2][0] - 5.0) < 1e-6
    # p3 sí — debe estar a distancia 5 de p2
    x3, y3 = result.positions[p3]
    dist = ((x3 - 5.0)**2 + (y3 - 0.0)**2) ** 0.5
    assert abs(dist - 5.0) < 1e-4
```

- [ ] **Step 2: Run**

```bash
pytest tests/test_sketch_solver_solvespace.py -v
```

Expected: 18 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_sketch_solver_solvespace.py
git commit -m "test(sketch/solvespace): verify locked_point_ids drag pattern"
```

---

## Task 11: Cross-check entre backends

**Files:**
- Create: `tests/test_sketch_solver_crosscheck.py`

Suite parametrizada sobre `backend ∈ {solvespace, legacy}`. Garantía de equivalencia end-to-end.

- [ ] **Step 1: Crear test**

```python
# tests/test_sketch_solver_crosscheck.py
"""Tests parametrizados sobre ambos backends — garantía de equivalencia."""
import pytest

from quino import ApplicationService


BACKENDS = ["solvespace", "legacy"]


@pytest.fixture(params=BACKENDS)
def svc(request):
    return ApplicationService(sketch_solver_backend=request.param)


def test_simple_distance(svc):
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    svc.create_sketch_constraint("c_fix", "fix", [p1], None, None)
    svc.create_sketch_constraint("c_d", "distance", [p1, p2], "10 mm", None)
    result = svc.solve_sketch()
    assert result.success, result.message


def test_horizontal_line_constraint(svc):
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "3 mm", "P2")
    line = svc.create_sketch_line_segment("L", p1, p2)
    svc.create_sketch_constraint("c_fix", "fix", [p1], None, None)
    svc.create_sketch_constraint("c_h", "horizontal", [line], None, None)
    result = svc.solve_sketch()
    assert result.success


def test_four_bar_geometry(svc):
    """Cuadrilátero con 4 puntos y 4 distancias — caso canónico."""
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("12 mm", "8 mm", "P3")
    p4 = svc.create_sketch_point("2 mm", "8 mm", "P4")
    svc.create_sketch_constraint("c_fix1", "fix", [p1], None, None)
    svc.create_sketch_constraint("c_fix2", "fix", [p2], None, None)
    svc.create_sketch_constraint("c_d23", "distance", [p2, p3], "9 mm", None)
    svc.create_sketch_constraint("c_d34", "distance", [p3, p4], "10 mm", None)
    svc.create_sketch_constraint("c_d41", "distance", [p4, p1], "9 mm", None)
    result = svc.solve_sketch()
    assert result.success


def test_radius_propagates(svc):
    svc.new_project("T")
    svc.create_sketch("S")
    center = svc.create_sketch_point("0 mm", "0 mm", "C")
    circle = svc.create_sketch_circle("Circ", center, "5 mm")
    svc.create_sketch_constraint("c_fix", "fix", [center], None, None)
    svc.create_sketch_constraint("c_r", "radius", [circle], "12 mm", None)
    result = svc.solve_sketch()
    assert result.success
    # Verifica que el radius_updates contiene el nuevo radio
    assert circle in result.radius_updates
    assert abs(result.radius_updates[circle] - 12.0) < 1e-3
```

- [ ] **Step 2: Run**

```bash
pytest tests/test_sketch_solver_crosscheck.py -v
```

Expected: 8 passed (4 tests × 2 backends).

- [ ] **Step 3: Commit**

```bash
git add tests/test_sketch_solver_crosscheck.py
git commit -m "test(sketch): cross-check suite parametrized over both backends"
```

---

## Task 12: Switch default backend a `solvespace` + auditoría de tests

**Files:**
- Modify: `quino/application/service.py` (default arg)
- Modify: `quino/services/sketch_solving/facade.py` (default arg)
- Modify: `tests/test_application.py` (test del default backend)
- Modify: tests existentes en `tests/test_sketch_*.py` y `tests/test_application.py` que asuman internals del solver

- [ ] **Step 1: Cambiar defaults**

En `quino/services/sketch_solving/facade.py`:
```python
backend: str = "solvespace",  # antes "legacy"
```

En `quino/application/service.py`:
```python
def __init__(self, *, sketch_solver_backend: str = "solvespace") -> None:
```

- [ ] **Step 2: Actualizar el test del default**

En `tests/test_application.py`, el test escrito en Task 3:
```python
def test_application_service_default_solver_backend():
    svc = ApplicationService()
    assert svc.sketch_solver.backend_name == "solvespace"
```

- [ ] **Step 3: Ejecutar tests para identificar fallos**

```bash
pytest tests/ -q
```

Expected: probablemente fallarán tests que comparan `iterations`, `max_error` exacto, u orden de `bad_constraints`. Anotar TODOS los fallos.

- [ ] **Step 4: Auditar y relajar asertos sobre internos**

Para cada test fallido, aplicar una de estas relajaciones:

| Aserto rígido | Relajación |
|---|---|
| `result.iterations == N` | eliminar el aserto o cambiar a `>= 0` |
| `result.max_error == 0.123` (valor float exacto) | `result.max_error < tolerance` |
| `result.bad_constraints == [a, b, c]` (orden) | `set(result.bad_constraints) == {a, b, c}` |
| `result.constraint_errors[id] == X` (valor exacto) | `id in result.constraint_errors` o eliminar |

**NO** relajar asertos sobre `result.positions` (posición final) ni `result.success`. Esos son comportamiento.

- [ ] **Step 5: Re-run hasta verde**

```bash
pytest tests/ -q
```

Iterar relajaciones hasta que pase. Expected: todo verde con Solvespace como default.

- [ ] **Step 6: Verificar que legacy también pasa**

```bash
QUINO_TEST_SOLVER=legacy pytest tests/ -q  # si tu setup soporta env var
```

O — más simple — usar la suite cross-check (Task 11) como verificación con legacy. Si está verde, listo.

- [ ] **Step 7: Commit**

```bash
git add quino/services/sketch_solving/facade.py quino/application/service.py tests/
git commit -m "feat(sketch): switch default backend to solvespace; relax solver-internal asserts"
```

---

## Task 13: Preferences module + QSettings

**Files:**
- Create: `quino/gui/preferences.py`
- Create: `tests/test_preferences.py`

- [ ] **Step 1: Crear `preferences.py`**

```python
# quino/gui/preferences.py
"""Persistent user preferences via QtCore.QSettings.

The QSettings instance maps to:
- Windows: HKCU\\Software\\QUINO\\QUINO
- Linux:   ~/.config/QUINO/QUINO.conf
- macOS:   ~/Library/Preferences/com.QUINO.QUINO.plist
"""
from __future__ import annotations

from PySide6 import QtCore


_VALID_BACKENDS = ("solvespace", "legacy")


class Preferences:
    _SKETCH_SOLVER_KEY = "sketch/solver_backend"

    def __init__(self, settings: QtCore.QSettings | None = None) -> None:
        self._qs = settings if settings is not None else QtCore.QSettings("QUINO", "QUINO")

    @property
    def sketch_solver_backend(self) -> str:
        value = self._qs.value(self._SKETCH_SOLVER_KEY, "solvespace", type=str)
        if value not in _VALID_BACKENDS:
            return "solvespace"  # corrupt fallback
        return value

    @sketch_solver_backend.setter
    def sketch_solver_backend(self, value: str) -> None:
        if value not in _VALID_BACKENDS:
            raise ValueError(f"Invalid sketch solver backend: {value!r}")
        self._qs.setValue(self._SKETCH_SOLVER_KEY, value)
```

- [ ] **Step 2: Crear tests**

```python
# tests/test_preferences.py
import pytest
from PySide6 import QtCore

from quino.gui.preferences import Preferences


@pytest.fixture
def isolated_settings(tmp_path):
    """Un QSettings con backend INI en un tmp path — aislado de la config real del usuario."""
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
    qs = QtCore.QSettings(str(tmp_path / "prefs.ini"), QtCore.QSettings.IniFormat)
    return qs


def test_default_sketch_solver_backend_is_solvespace(isolated_settings):
    p = Preferences(isolated_settings)
    assert p.sketch_solver_backend == "solvespace"


def test_set_and_get_legacy(isolated_settings):
    p = Preferences(isolated_settings)
    p.sketch_solver_backend = "legacy"
    assert p.sketch_solver_backend == "legacy"


def test_set_invalid_raises(isolated_settings):
    p = Preferences(isolated_settings)
    with pytest.raises(ValueError):
        p.sketch_solver_backend = "xyz"


def test_corrupt_value_falls_back_to_solvespace(isolated_settings):
    isolated_settings.setValue("sketch/solver_backend", "garbage")
    p = Preferences(isolated_settings)
    assert p.sketch_solver_backend == "solvespace"


def test_persists_across_instances(isolated_settings):
    p1 = Preferences(isolated_settings)
    p1.sketch_solver_backend = "legacy"
    p1._qs.sync()
    p2 = Preferences(isolated_settings)
    assert p2.sketch_solver_backend == "legacy"
```

- [ ] **Step 3: Run**

```bash
pytest tests/test_preferences.py -v
```

Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add quino/gui/preferences.py tests/test_preferences.py
git commit -m "feat(gui): add Preferences wrapper over QSettings for solver backend"
```

---

## Task 14: UI dropdown en preferences dialog + hot swap

**Files:**
- Modify: `quino/gui/main_window.py` (lectura inicial + `_show_preferences_dialog`)

- [ ] **Step 1: Leer preferencia al arrancar**

En `MainWindow.__init__`, después de crear `self.app_service` (o antes si app_service viene como arg), reemplazar la creación de ApplicationService:

```python
from quino.gui.preferences import Preferences
# ...
prefs = Preferences()
self._preferences = prefs
self.app_service = app_service or ApplicationService(sketch_solver_backend=prefs.sketch_solver_backend)
```

NOTA: cuando `app_service` viene del exterior (tests), no se respeta la preferencia. Eso es deliberado y correcto.

- [ ] **Step 2: Dropdown en preferences dialog**

En `_show_preferences_dialog`, antes del bloque de botones (Ok/Cancel), añadir:

```python
# Sketch solver selector
solver_layout = QtWidgets.QHBoxLayout()
solver_combo = QtWidgets.QComboBox()
solver_combo.addItem("Solvespace", "solvespace")
solver_combo.addItem("Legacy (iterative)", "legacy")
current_backend = self._preferences.sketch_solver_backend
index = solver_combo.findData(current_backend)
if index >= 0:
    solver_combo.setCurrentIndex(index)
solver_combo.setToolTip(
    "Solvespace es más robusto. Legacy es el solver iterativo propio."
)
solver_layout.addWidget(solver_combo)
solver_layout.addStretch()
layout.addRow("Sketch solver:", solver_layout)
```

- [ ] **Step 3: Aplicar en accept**

Al final del `if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:` block, añadir:

```python
new_backend = solver_combo.currentData()
if new_backend != self._preferences.sketch_solver_backend:
    self._preferences.sketch_solver_backend = new_backend
    self.app_service.set_sketch_solver_backend(new_backend)
    self._append_message(f"Sketch solver backend cambiado a {new_backend}.")
```

- [ ] **Step 4: Verify smoke**

```bash
pytest tests/test_gui.py -q
```

Expected: 65 passed (sin regresiones).

Manualmente (no automatizable):
```bash
python -m quino.gui
```
Abrir Edit → Preferences, ver el dropdown, cambiar a Legacy, OK, abrir un sketch y verificar que solve funciona. Cambiar de vuelta a Solvespace.

- [ ] **Step 5: Commit**

```bash
git add quino/gui/main_window.py
git commit -m "feat(gui): sketch solver selector in Preferences dialog with hot swap"
```

---

## Task 15: Documentar en CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Añadir sección**

Editar `CLAUDE.md`. Después de la sección de command-services añadida en Fase 2, insertar:

```markdown
## Sketch solver
El motor del modo Sketch vive en `quino/services/sketch_solving/`:
- `facade.py` — `SketchSolver` (despacha al backend según preferencia)
- `solvespace_backend.py` — adapter sobre `python-solvespace` (default)
- `legacy_backend.py` — solver iterativo propio (opt-in)
- `constraint_mapping.py` — traduce cada `SketchConstraintType` al constraint nativo
- `_auxiliary_geometry.py` — emite líneas H/V invisibles para `HORIZONTAL_DISTANCE`/`VERTICAL_DISTANCE`

El backend se elige con `ApplicationService(sketch_solver_backend="solvespace"|"legacy")` o, en GUI, via Edit → Preferences. La preferencia se persiste con `QtCore.QSettings("QUINO", "QUINO")`.

`quino/services/sketch_solver.py` se conserva como re-export shim.
```

Actualizar también la sección "Archivos grandes":

```markdown
## Archivos grandes (en refactor — ver docs/superpowers/plans/2026-05-18-fase-*)
- `quino/gui/canvas.py` 5850 LOC (Fase 3 pendiente)
- `quino/gui/main_window.py` ~4550 LOC (Fase 4 pendiente)
- `quino/solver_adapters/exudyn_adapter.py` 1684 LOC (Fase 4 pendiente)
- `quino/application/service.py` 863 LOC (Fase 2 ✓)
- `quino/services/sketch_solving/legacy_backend.py` ~947 LOC (movido desde sketch_solver.py en migración a Solvespace)
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document Solvespace sketch solver and backend toggle"
```

---

## Verificación final de la fase

- [ ] **Step 1: Suite completa con default (solvespace)**

```bash
pytest tests/ -q
```

Expected: todo verde.

- [ ] **Step 2: Cross-check verifica ambos backends**

```bash
pytest tests/test_sketch_solver_crosscheck.py -v
```

Expected: todas las parametrizaciones pasan.

- [ ] **Step 3: Smoke GUI manual**

`python -m quino.gui`:
- Cargar four-bar example. Activar modo Sketch. Crear puntos + constraints. "Solve Sketch" funciona.
- Preferences: cambiar a Legacy. Volver a sketch, hacer una operación. Funciona.
- Preferences: volver a Solvespace.
- Drag de un punto en sketch funciona suave (sin lag perceptible).

- [ ] **Step 4: Tamaño de `service.py` sin cambios**

```bash
wc -l quino/application/service.py
```

Expected: ~870-880 LOC (los cambios de esta fase son mínimos en service.py).

- [ ] **Step 5: Nuevos archivos**

```bash
wc -l quino/services/sketch_solving/*.py quino/gui/preferences.py
```

Expected: ~1500 LOC total (la mayoría en legacy_backend.py movido).

---

## Self-Review

**Spec coverage**:
- D1 (Solvespace por defecto + legacy opt-in) — Tasks 4-12 (default switch en T12).
- D2 (toggle preferencia) — Tasks 13-14.
- D3 (QSettings) — Task 13.
- D4 (python-solvespace) — Task 1.
- D5 (constraints faltantes con aux geom) — Task 9.
- D6 (drag con Solvespace) — Tasks 4, 10.
- D7 (relajar tests existentes) — Task 12.
- Riesgo "API real difiere" — Task 1 gate.
- Riesgo "aux geom leaks" — Task 9 incluye test del invariante.
- Riesgo "wheel no disponible Windows" — Task 1 gate.
- Aceptación 1-7 — verificada en bloque "Verificación final".

**Placeholder scan**:
- Hay marcas "AJUSTAR según API real" en Tasks 4, 5, 6, 7, 8, 9. Estos NO son placeholders sin contenido: indican el nombre exacto a verificar tras Task 1, donde el código asume nombres canónicos de libslvs y la primera tarea confirma cuáles aplican. Los snippets de código completos están provistos.
- No hay TBD, TODO, "implement later" sin contenido.
- Cada test viene con cuerpo completo.
- Cada commit tiene mensaje exacto.

**Type consistency**:
- `SketchSolveResult` se define en Task 2 (`base.py`) y se usa idéntico en todas las tareas siguientes (mismos 8 campos).
- `SketchSolverBackend` protocol con `name: str` y `solve(...)` — `LegacyIterativeBackend` y `SolvespaceBackend` ambos exponen `name = "..."` como atributo de clase.
- `_make_backend("solvespace"|"legacy")` consistente en Task 2 y referenciado en Task 12.
- `sketch_solver_backend` arg consistente en `ApplicationService.__init__` (Task 3) y `set_sketch_solver_backend(...)` (Task 3).
- `Preferences.sketch_solver_backend` property en Task 13, consumida en Task 14.
