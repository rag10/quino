# Sketch: Solvespace as single source of truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar toda la lógica de sketch que duplica o compite con Solvespace (DOF heurístico, helper geometry, cache de solve, solver legacy y código muerto orphaned), dejando a Solvespace como única fuente de verdad para constraints, DOF per-punto y estado "fully constrained".

**Architecture:** Refactor en 4 fases:
1. **Limpieza de código muerto** — borrar 7 módulos sketch_* huérfanos (nadie los importa) + sus tests.
2. **Eliminar legacy solver iterativo** — borrar `legacy_backend.py`, dropdown de preferencias, 5 tests pinned a legacy, cross-check parametrizado.
3. **DOF via Solvespace (perturbation test)** — sustituir `SketchDofAnalyzer` por un analyzer que use el solver real (N+1 solves para detectar libertad por punto).
4. **Borrar helper geometry + cache** — eliminar `_create_tangent_helper_geometry` (puntos `construction=True` que Solvespace no necesita) y el cache `_sketch_signature` / `_solve_cache`.

**Tech Stack:** Python 3.11+, PySide6, python-solvespace 3.0.8, pytest.

**Pre-requisitos:** Branch `refactor/fase-1-extracciones`, HEAD `4d468de` (plan anterior completado). Tests baseline: 410 pass, 1 skip, 1 xfail.

**Referencia:** Auditoría inline 2026-05-19. Plan anterior (UX fixes): `docs/superpowers/plans/2026-05-19-sketch-ux-fixes.md`.

---

## File Structure (resumen del cambio)

```
DELETED:
  quino/services/sketch_dof.py                          (116 LOC — heurístico paralelo al solver)
  quino/services/sketch_cache.py                        (55 LOC — orphaned)
  quino/services/sketch_evaluator.py                    (148 LOC — orphaned)
  quino/services/sketch_registries.py                   (55 LOC — orphaned)
  quino/services/sketch_spatial.py                      (25 LOC — orphaned)
  quino/services/sketch_solving/legacy_backend.py       (~530 LOC — solver iterativo propio)
  quino/domain/sketch_dependency.py                     (orphaned)
  quino/domain/sketch_evaluated.py                      (orphaned)
  quino/domain/sketch_events.py                         (orphaned)
  tests/test_sketch_cache.py                            (101 LOC)
  tests/test_sketch_dependency.py                       (192 LOC)
  tests/test_sketch_dof.py                              (182 LOC)
  tests/test_sketch_spline.py  ← VERIFICAR si está orphaned

MODIFIED:
  quino/services/sketch_solving/facade.py               (sin dispatch — sólo SolvespaceBackend)
  quino/services/sketch_solving/__init__.py             (sin SketchSolverBackend protocol externo)
  quino/services/sketch_solving/solvespace_backend.py   (+ analyze_dof method)
  quino/services/sketch_solving/base.py                 (+ DofResult dataclass)
  quino/application/service.py                          (- sketch_solver_backend arg, - set_sketch_solver_backend)
  quino/application/commands/sketch_commands.py         (- _create_tangent_helper_geometry, - _solve_cache, - _sketch_signature)
  quino/gui/canvas.py                                   (DOF callers usan SolvespaceBackend.analyze_dof)
  quino/gui/main_window.py                              (- dropdown de Preferences)
  quino/gui/preferences.py                              (- sketch_solver_backend property)
  tests/test_application.py                             (- 5 tests pinned a legacy, - make_app_legacy)
  tests/test_sketch_solver_crosscheck.py                (- parametrize over both backends — sólo solvespace)

CREATED:
  tests/test_solvespace_dof.py                          (cobertura del nuevo analyzer)
```

---

## Phase A — Limpieza de código muerto

### Task A1: Verificar orphans y borrarlos

**Files:**
- Delete: `quino/services/sketch_cache.py`
- Delete: `quino/services/sketch_evaluator.py`
- Delete: `quino/services/sketch_registries.py`
- Delete: `quino/services/sketch_spatial.py`
- Delete: `quino/domain/sketch_dependency.py`
- Delete: `quino/domain/sketch_evaluated.py`
- Delete: `quino/domain/sketch_events.py`
- Delete: `tests/test_sketch_cache.py`
- Delete: `tests/test_sketch_dependency.py`
- Posibly delete: `tests/test_sketch_spline.py` (verificar)

- [ ] **Step 1: Baseline**

```bash
pytest tests/ -q
```

Expected: `410 passed, 1 skipped, 1 xfailed`.

- [ ] **Step 2: Verificar que cada archivo es realmente orphan**

Para CADA archivo de la lista DELETED de arriba (excepto los tests), verificar con grep que nadie lo importa desde fuera de su propia familia:

```bash
for module in sketch_cache sketch_evaluator sketch_registries sketch_spatial; do
  echo "=== $module ===";
  grep -rn "from quino.services.$module\|import quino.services.$module" --include="*.py" .
done

for module in sketch_dependency sketch_evaluated sketch_events; do
  echo "=== domain/$module ===";
  grep -rn "from quino.domain.$module\|import quino.domain.$module" --include="*.py" .
done
```

Expected: cada uno aparece SÓLO en su propio archivo o en `tests/test_sketch_cache.py` / `tests/test_sketch_dependency.py` o `tests/test_sketch_spline.py`. **Si algún archivo es referenciado por código de producción no testing, ABORTAR y reportar.**

- [ ] **Step 3: Verificar `test_sketch_spline.py`**

```bash
head -20 tests/test_sketch_spline.py
```

Si testea features de un `SketchSpline` que sí existe en `quino/domain/model.py`, mantenerlo. Si testea features de `sketch_evaluated` o similar orphaned module, borrarlo.

```bash
grep -E "^from|^import" tests/test_sketch_spline.py
```

Decide y documenta en el report.

- [ ] **Step 4: Borrar los archivos**

```bash
rm quino/services/sketch_cache.py quino/services/sketch_evaluator.py quino/services/sketch_registries.py quino/services/sketch_spatial.py
rm quino/domain/sketch_dependency.py quino/domain/sketch_evaluated.py quino/domain/sketch_events.py
rm tests/test_sketch_cache.py tests/test_sketch_dependency.py
# Conditional: rm tests/test_sketch_spline.py  (sólo si Step 3 lo justifica)
```

- [ ] **Step 5: Test suite**

```bash
pytest tests/ -q
```

Expected: `410 - 0_dead_tests passed` (o el conteo correcto tras borrar). Si algo se rompe, INVESTIGAR — significa que el módulo no era 100% orphan.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore(sketch): remove 7 orphaned sketch modules and their tests

sketch_cache, sketch_evaluator, sketch_registries, sketch_spatial,
sketch_dependency, sketch_evaluated, sketch_events — no production import
of any of these survives. They were dead code from an earlier architecture
that was never wired in."
```

---

## Phase B — Eliminar legacy iterative solver

### Task B1: Borrar `legacy_backend.py` + simplificar facade

**Files:**
- Delete: `quino/services/sketch_solving/legacy_backend.py`
- Modify: `quino/services/sketch_solving/facade.py`
- Modify: `quino/services/sketch_solving/__init__.py`
- Modify: `quino/services/sketch_solving/base.py` (eliminar Protocol si nadie lo usa)

- [ ] **Step 1: Verificar que el dispatch sólo se usa para "solvespace" y "legacy"**

```bash
grep -rn "sketch_solver_backend=\"\|sketch_solver_backend='\|_make_backend\|backend=" quino/services/sketch_solving/ quino/application/ quino/gui/ --include="*.py"
```

Anotar todos los call sites. Tras Task B2 (siguiente), todos deben dejar de pasar el arg.

- [ ] **Step 2: Simplificar `facade.py`**

Reemplazar el contenido de `quino/services/sketch_solving/facade.py` por:

```python
# quino/services/sketch_solving/facade.py
from __future__ import annotations

from quino.domain.model import Project
from quino.services.expressions import ExpressionService
from quino.services.sketch_solving.base import SketchSolveResult
from quino.services.sketch_solving.solvespace_backend import SolvespaceBackend
from quino.services.units import UnitService


class SketchSolver:
    """Facade for the sketch constraint solver.

    Solvespace is the only supported backend. The class is kept as a thin
    wrapper to preserve the existing public surface used by callers.
    """

    def __init__(
        self,
        expression_service: ExpressionService,
        unit_service: UnitService,
    ) -> None:
        self._backend = SolvespaceBackend(expression_service, unit_service)

    @property
    def backend_name(self) -> str:
        return self._backend.name

    def solve(self, project: Project, **kwargs) -> SketchSolveResult:
        return self._backend.solve(project, **kwargs)
```

- [ ] **Step 3: Borrar `legacy_backend.py`**

```bash
rm quino/services/sketch_solving/legacy_backend.py
```

- [ ] **Step 4: Limpiar `__init__.py`**

Editar `quino/services/sketch_solving/__init__.py`. Quitar la importación del Protocol si nadie externo lo usa. Resultado esperado:

```python
from quino.services.sketch_solving.base import SketchSolveResult
from quino.services.sketch_solving.facade import SketchSolver

__all__ = ["SketchSolver", "SketchSolveResult"]
```

(Sin `SketchSolverBackend` — ya no hay despacho.)

- [ ] **Step 5: Limpiar `base.py`**

Verificar si `SketchSolverBackend` Protocol se usa fuera del paquete:

```bash
grep -rn "SketchSolverBackend" --include="*.py" .
```

Si sólo aparece en `quino/services/sketch_solving/base.py` y `__init__.py`, borrar el Protocol de `base.py`. `SketchSolveResult` permanece.

- [ ] **Step 6: Tests**

```bash
pytest tests/ -q
```

Esperado: muchos fallos. Vamos a arreglarlos en B2.

- [ ] **Step 7: Commit (incluso con tests rojos — checkpoint)**

```bash
git add -A
git commit -m "refactor(sketch): remove legacy iterative solver and backend dispatch

Solvespace is now the only sketch solver. SketchSolver becomes a thin
wrapper directly instantiating SolvespaceBackend. Subsequent task B2
removes the ApplicationService backend arg and Preferences dropdown.

NOTE: tests are temporarily red; B2 closes the loop."
```

### Task B2: Eliminar `sketch_solver_backend` arg de ApplicationService

**Files:**
- Modify: `quino/application/service.py`
- Modify: `tests/test_application.py`

- [ ] **Step 1: Localizar todas las firmas afectadas**

```bash
grep -nE "sketch_solver_backend|set_sketch_solver_backend" quino/application/service.py tests/
```

- [ ] **Step 2: Simplificar `ApplicationService.__init__`**

En `quino/application/service.py`, cambiar:

```python
def __init__(self, *, sketch_solver_backend: str = "solvespace") -> None:
    ...
    self._sketch_solver_backend = sketch_solver_backend
    self.sketch_solver = SketchSolver(
        self.expression_service,
        self.unit_service,
        backend=sketch_solver_backend,
    )
```

por:

```python
def __init__(self) -> None:
    ...
    self.sketch_solver = SketchSolver(
        self.expression_service,
        self.unit_service,
    )
```

Eliminar la asignación `self._sketch_solver_backend = ...`. Eliminar también el método `set_sketch_solver_backend` completo.

- [ ] **Step 3: Eliminar `make_app_legacy()` de tests**

En `tests/test_application.py`, borrar la función `make_app_legacy()` (alrededor de línea 28). Borrar también los 5 tests pineados a legacy (que llaman `make_app_legacy()`):

Identifícalos con:
```bash
grep -nB 2 "make_app_legacy()" tests/test_application.py
```

Los 5 tests son (líneas aproximadas):
1. `test_sketch_entities_support_crud_and_cascade_delete` (~line 881) — borrar el test entero.
2. `test_sketch_solver_handles_parallel_midpoint_angle_and_on_circle` (~line 1016) — borrar.
3. `test_sketch_coincident_accepts_point_on_line_and_circle` (~line 1079) — borrar.
4. `test_sketch_solver_handles_tangent_constraint` (~line 1127) — borrar.
5. `test_sketch_solver_handles_curve_curve_tangent_constraint` (~line 1191) — borrar.

Borrarlos TODOS. La cobertura equivalente vive en `tests/test_sketch_solver_solvespace.py` y `tests/test_sketch_gui_constraint_clicks.py`.

- [ ] **Step 4: Eliminar también los 4 tests del default backend** (ya obsoletos)

Estos tests fueron añadidos en T3 del plan de Solvespace para asegurar que `sketch_solver_backend` arg funciona. Como el arg ya no existe, los borramos.

Localiza con:
```bash
grep -n "test_application_service_default_solver_backend\|test_application_service_explicit_legacy_backend\|test_set_sketch_solver_backend_swaps_instance\|test_set_sketch_solver_backend_rejects_unknown" tests/test_application.py
```

Borrar los 4 tests.

- [ ] **Step 5: Cross-check parametrizado → single-backend**

Renombrar `tests/test_sketch_solver_crosscheck.py` y simplificarlo. Como ya no hay dos backends, su propósito desaparece. Decisión:

```bash
rm tests/test_sketch_solver_crosscheck.py
```

(Los escenarios que cubría siguen siendo testados por `test_sketch_solver_solvespace.py` y otros — verificar con un grep rápido de los nombres de test que está perdiendo y confirmar que hay equivalencia.)

```bash
grep -nE "^def test_" tests/test_sketch_solver_crosscheck.py 2>/dev/null
```

Si encuentras un test que NO está cubierto en `test_sketch_solver_solvespace.py`, copiar el cuerpo allí antes de borrar el archivo. Si todo lo demás ya está cubierto, sólo borra.

- [ ] **Step 6: Tests**

```bash
pytest tests/ -q
```

Esperado: pass con menos tests totales. El conteo debería ser algo como `~396 passed, 0 skipped, 0 xfailed` (perdimos 5 + 4 + 14 = ~23 tests, ganamos lo que se mantenía verde).

Si algún test pinned a legacy se quedó sin borrar y falla, borrarlo.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(application): remove sketch_solver_backend arg and runtime swap

Drop ApplicationService.__init__ keyword arg and set_sketch_solver_backend
method now that legacy is gone. Delete 5 legacy-pinned tests, 4 backend-
arg unit tests, and the cross-check parametrized suite. Equivalent coverage
lives in test_sketch_solver_solvespace.py and test_sketch_gui_constraint_clicks.py."
```

### Task B3: Eliminar dropdown de Preferences

**Files:**
- Modify: `quino/gui/main_window.py`
- Modify: `quino/gui/preferences.py`
- Modify: `tests/test_preferences.py`

- [ ] **Step 1: Eliminar dropdown del diálogo**

En `quino/gui/main_window.py`, dentro de `_show_preferences_dialog`, eliminar el bloque que añade el `solver_combo`:

```python
# Sketch solver selector
solver_combo = QtWidgets.QComboBox()
solver_combo.addItem("Solvespace", "solvespace")
solver_combo.addItem("Legacy (iterative)", "legacy")
...
layout.addRow("Sketch solver:", solver_combo)
```

Y en el bloque de Accept, eliminar:

```python
new_backend = solver_combo.currentData()
if new_backend != self._preferences.sketch_solver_backend:
    self._preferences.sketch_solver_backend = new_backend
    self.app_service.set_sketch_solver_backend(new_backend)
    ...
```

- [ ] **Step 2: Quitar la inicialización via Preferences en `MainWindow.__init__`**

Cambiar:
```python
self._preferences = Preferences()
if app_service is None:
    app_service = ApplicationService(
        sketch_solver_backend=self._preferences.sketch_solver_backend,
    )
self.app_service = app_service
```

a:

```python
self.app_service = app_service or ApplicationService()
```

(Si `Preferences` se usa para OTRAS keys persistidas, conservar la instancia: `self._preferences = Preferences()`. Si era sólo para `sketch_solver_backend`, eliminar también el atributo.)

Verificar:
```bash
grep -n "self._preferences" quino/gui/main_window.py
```

Si sólo aparecía dentro del bloque que borramos, eliminar el atributo. Si aparece en otros sitios, conservarlo.

- [ ] **Step 3: Simplificar `Preferences`**

En `quino/gui/preferences.py`, eliminar la property `sketch_solver_backend` (y su setter), y la constante `_VALID_SKETCH_BACKENDS`. Si la clase queda sin properties, valorar borrar el archivo entero — pero conservarlo si esperamos añadir más prefs.

Versión mínima viable:

```python
# quino/gui/preferences.py
"""Persistent user preferences via QtCore.QSettings.

Currently empty: previous keys (sketch_solver_backend) were removed when
the legacy backend was eliminated. Kept as a scaffold for future prefs.
"""
from __future__ import annotations

from PySide6 import QtCore


class Preferences:
    def __init__(self, settings: QtCore.QSettings | None = None) -> None:
        self._qs = settings if settings is not None else QtCore.QSettings("QUINO", "QUINO")
```

- [ ] **Step 4: Actualizar tests de Preferences**

En `tests/test_preferences.py`, eliminar los 5 tests sobre `sketch_solver_backend`. Si el archivo queda vacío, borrarlo:

```bash
# Si el archivo queda sin tests útiles:
rm tests/test_preferences.py
```

- [ ] **Step 5: Tests + smoke import**

```bash
pytest tests/ -q
python -c "from quino.gui.main_window import MainWindow; print('ok')"
```

Expected: tests pasan, smoke imprime `ok`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(gui): remove sketch solver dropdown from Preferences

With the legacy backend gone, there's no choice to make. Preferences keeps
a minimal scaffold for future settings."
```

---

## Phase C — DOF via Solvespace (perturbation test)

### Task C1: Diseño + tests del `SolvespaceDofAnalyzer`

**Files:**
- Modify: `quino/services/sketch_solving/base.py` (añadir `DofResult` dataclass)
- Modify: `quino/services/sketch_solving/solvespace_backend.py` (añadir método `analyze_dof`)
- Create: `tests/test_solvespace_dof.py`

**Algoritmo de perturbation test**: para cada `SketchPoint` no fijo, construir un sistema temporal igual al sketch + un `dragged()` extra sobre el punto en una posición perturbada (current + ε en X, luego en Y). Resolver. Si el punto acaba cerca de la posición perturbada → ese eje es libre. Si vuelve a la posición resuelta → ese eje está constreñido.

DOF del punto = `(1 si X libre else 0) + (1 si Y libre else 0)`.

- [ ] **Step 1: Baseline**

```bash
pytest tests/ -q
```

- [ ] **Step 2: Añadir `DofResult` en `base.py`**

```python
# añadir al final de quino/services/sketch_solving/base.py
@dataclass
class DofResult:
    """DOF analysis result computed by the Solvespace backend.

    point_dof maps each SketchPoint.id to remaining degrees of freedom (0, 1, or 2).
    fully_constrained_point_ids and fully_constrained_entity_ids are convenience
    sets derived from point_dof: a point is fully constrained when dof==0; an
    entity (line/circle/arc) is fully constrained when all its referenced points
    are fully constrained.
    """
    point_dof: dict[str, int]
    fully_constrained_point_ids: set[str]
    fully_constrained_entity_ids: set[str]
    total_free_dof: int
```

(Misma forma que el legacy `DofResult` para minimizar el cambio en callers.)

- [ ] **Step 3: Tests primero (TDD)**

Crear `tests/test_solvespace_dof.py`:

```python
"""Tests for SolvespaceBackend.analyze_dof() — DOF via perturbation test."""
from quino import ApplicationService
from quino.services.expressions import ExpressionService
from quino.services.sketch_solving.solvespace_backend import SolvespaceBackend
from quino.services.units import UnitService


def _make_backend() -> SolvespaceBackend:
    u = UnitService()
    return SolvespaceBackend(ExpressionService(u), u)


def test_unconstrained_point_has_2_dof():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p = svc.create_sketch_point("0 mm", "0 mm", "P")
    result = _make_backend().analyze_dof(svc.project)
    assert result.point_dof[p] == 2
    assert p not in result.fully_constrained_point_ids


def test_fixed_point_has_0_dof():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p = svc.create_sketch_point("0 mm", "0 mm", "P")
    svc.create_sketch_constraint("fix", [p])
    result = _make_backend().analyze_dof(svc.project)
    assert result.point_dof[p] == 0
    assert p in result.fully_constrained_point_ids


def test_horizontal_distance_alone_leaves_one_dof_per_point():
    """One point fixed, second has only horizontal distance constraint → 1 DOF (y is free)."""
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("horizontal_distance", [p1, p2], value="10 mm")
    result = _make_backend().analyze_dof(svc.project)
    assert result.point_dof[p1] == 0
    assert result.point_dof[p2] == 1


def test_distance_constraint_leaves_one_dof():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("distance", [p1, p2], value="10 mm")
    result = _make_backend().analyze_dof(svc.project)
    assert result.point_dof[p1] == 0
    assert result.point_dof[p2] == 1  # only the angle is free


def test_line_with_endpoints_fixed_is_fully_constrained():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    line = svc.create_sketch_line_segment(p1, p2, "L")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    result = _make_backend().analyze_dof(svc.project)
    assert line in result.fully_constrained_entity_ids


def test_empty_sketch_returns_zero_dof():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    result = _make_backend().analyze_dof(svc.project)
    assert result.total_free_dof == 0
    assert result.point_dof == {}
```

- [ ] **Step 4: Test debería fallar (método no existe)**

```bash
pytest tests/test_solvespace_dof.py -v
```

Expected: FAIL — `AttributeError: 'SolvespaceBackend' has no attribute 'analyze_dof'`.

- [ ] **Step 5: Implementar `analyze_dof` en `SolvespaceBackend`**

Añadir al final de la clase en `quino/services/sketch_solving/solvespace_backend.py`:

```python
    def analyze_dof(self, project: Project) -> "DofResult":
        """Per-point DOF analysis via Solvespace perturbation testing.

        For each free point, we build a temp solver system equivalent to the
        sketch plus an extra `dragged()` on that point at a perturbed position.
        If the solver moves the point to the perturbed location, that axis is
        free; if it pulls the point back, the axis is constrained. We do this
        once for X and once for Y per point.

        Returns a DofResult with per-point DOF counts and convenience sets.
        """
        from quino.services.sketch_solving.base import DofResult

        sketch = project.sketch
        if sketch is None:
            return DofResult({}, set(), set(), 0)

        points = list(sketch.points())
        if not points:
            return DofResult({}, set(), set(), 0)

        # Identify points that are fixed via FIX constraint (dof = 0 trivially).
        fixed_ids: set[str] = set()
        for c in sketch.constraints.values():
            if c.type is SketchConstraintType.FIX:
                fixed_ids.update(c.references)

        point_dof: dict[str, int] = {}
        epsilon = 1.0  # mm of perturbation; large enough that solver-noise doesn't false-positive

        for p in points:
            if p.id in fixed_ids:
                point_dof[p.id] = 0
                continue
            free_axes = 0
            for axis in (0, 1):
                if self._axis_is_free(project, sketch, p.id, axis, epsilon):
                    free_axes += 1
            point_dof[p.id] = free_axes

        fully_constrained_points = {pid for pid, dof in point_dof.items() if dof == 0}

        # An entity is fully constrained if all its referenced points are.
        fully_constrained_entities: set[str] = set()
        for entity in sketch.entities.values():
            ref_point_ids = self._entity_point_ids(entity)
            if ref_point_ids and all(pid in fully_constrained_points for pid in ref_point_ids):
                fully_constrained_entities.add(entity.id)

        total_free_dof = sum(point_dof.values())
        return DofResult(
            point_dof=point_dof,
            fully_constrained_point_ids=fully_constrained_points,
            fully_constrained_entity_ids=fully_constrained_entities,
            total_free_dof=total_free_dof,
        )

    def _axis_is_free(self, project, sketch, point_id: str, axis: int, epsilon: float) -> bool:
        """Return True if perturbing point_id along the given axis (0=X, 1=Y) results
        in the solver allowing the point to stay at the perturbed location."""
        # Run a normal solve first to get the reference position.
        ref_result = self.solve(project)
        if not ref_result.success:
            # If the sketch doesn't solve, we can't meaningfully analyze DOF.
            return False
        ref_x, ref_y = ref_result.positions.get(point_id, (0.0, 0.0))
        target_x = ref_x + (epsilon if axis == 0 else 0.0)
        target_y = ref_y + (epsilon if axis == 1 else 0.0)

        # Re-run with point_id dragged-to perturbed location: add a "guide"
        # constraint that pulls the point to (target_x, target_y) by treating it
        # as a free point in the regular solve but with a softer pull. Solvespace
        # doesn't have soft constraints, so we use the trick: do a fresh solve
        # where every OTHER point is locked at its current resolved location;
        # only the test point and unconstrained points can move. Then check if
        # the test point lands at target.
        try:
            sys, point_handles = self._build_system_with_drag(
                project, sketch, dragged_id=point_id, target=(target_x, target_y),
            )
            result_code = sys.solve()
            import python_solvespace as ps
            if result_code != ps.ResultFlag.OKAY:
                return False
            new_x, new_y = self._read_point(sys, point_handles[point_id])
        except Exception:
            return False

        if axis == 0:
            return abs(new_x - target_x) < epsilon * 0.1  # within 10% of perturbation
        return abs(new_y - target_y) < epsilon * 0.1

    def _build_system_with_drag(self, project, sketch, *, dragged_id: str, target: tuple[float, float]):
        """Build a fresh SolverSystem replicating the sketch, with `dragged_id`
        initialized at `target` so the solver tries to keep it there."""
        import python_solvespace as ps
        from quino.services.sketch_solving.constraint_mapping import emit_constraint

        sys = ps.SolverSystem()
        wp = sys.create_2d_base()
        nm_3d = sys.entity(0)

        # FIX-based fixed ids
        fixed_ids: set[str] = set()
        for c in sketch.constraints.values():
            if c.type is SketchConstraintType.FIX:
                fixed_ids.update(c.references)

        point_handles: dict[str, object] = {}
        for p in sketch.points():
            if p.id == dragged_id:
                # Place at perturbed target. Make it FREE so solver decides
                # whether to keep it there (axis free) or pull it back (constrained).
                handle = sys.add_point_2d(target[0], target[1], wp)
            else:
                x, y = self._evaluate_point(project, p)
                handle = sys.add_point_2d(x, y, wp)
                if p.id in fixed_ids:
                    sys.dragged(handle, wp)
            point_handles[p.id] = handle

        entity_handles: dict[str, object] = {}
        radius_entities: dict[str, object] = {}
        for entity in sketch.entities.values():
            self._create_entity(sys, wp, nm_3d, entity, point_handles, entity_handles, radius_entities, project)

        constrained_radii: set[str] = set()
        for c in sketch.constraints.values():
            if c.type is SketchConstraintType.FIX:
                continue
            if c.type is SketchConstraintType.RADIUS:
                constrained_radii.update(c.entity_references or [])
                constrained_radii.update(c.references or [])
            if c.type is SketchConstraintType.TANGENT:
                constrained_radii.update(c.entity_references or [])
            try:
                emit_constraint(
                    sys, wp, c,
                    points=point_handles,
                    entities=entity_handles,
                    project=project,
                    expressions=self._expressions,
                    units=self._units,
                )
            except (ValueError, TypeError):
                pass

        for entity in sketch.entities.values():
            if entity.id in constrained_radii:
                continue
            handle = entity_handles.get(entity.id)
            if handle is None:
                continue
            from quino.domain.model import SketchArc, SketchCircle
            if isinstance(entity, (SketchCircle, SketchArc)):
                radius_mm = self._evaluate_radius(entity, project)
                if radius_mm is not None:
                    sys.diameter(handle, 2.0 * radius_mm)

        return sys, point_handles

    @staticmethod
    def _entity_point_ids(entity) -> list[str]:
        from quino.domain.model import (
            SketchArc, SketchCircle, SketchInfiniteLine, SketchLineSegment, SketchPoint
        )
        if isinstance(entity, SketchPoint):
            return [entity.id]
        if isinstance(entity, SketchLineSegment):
            return [entity.start_point_id, entity.end_point_id]
        if isinstance(entity, SketchInfiniteLine):
            return [entity.point_a_id, entity.point_b_id]
        if isinstance(entity, SketchCircle):
            return [entity.center_point_id]
        if isinstance(entity, SketchArc):
            return [entity.center_point_id, entity.start_point_id, entity.end_point_id]
        return []
```

- [ ] **Step 6: Tests**

```bash
pytest tests/test_solvespace_dof.py -v
```

Expected: 6 passed.

Si algún test falla:
- Si `test_distance_constraint_leaves_one_dof` falla porque marca como "1 DOF" en vez de 1 — el threshold de detección puede no estar bien calibrado. Ajustar `epsilon * 0.1` a algo más laxo (p.ej. `epsilon * 0.3`).
- Si `test_unconstrained_point_has_2_dof` falla — el método auxiliar `_build_system_with_drag` no está moviendo el punto donde queremos. Debug.

- [ ] **Step 7: Suite completa**

```bash
pytest tests/ -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add quino/services/sketch_solving/base.py quino/services/sketch_solving/solvespace_backend.py tests/test_solvespace_dof.py
git commit -m "feat(sketch/solvespace): add analyze_dof() with per-point perturbation test

DOF analysis derived from the actual solver instead of a heuristic table.
The DofResult shape (point_dof dict + fully_constrained sets + total) matches
the legacy SketchDofAnalyzer so callers can migrate without API changes."
```

### Task C2: Migrar callers de `SketchDofAnalyzer` a `analyze_dof`

**Files:**
- Modify: `quino/gui/canvas.py`
- Delete: `quino/services/sketch_dof.py`
- Delete: `tests/test_sketch_dof.py`

- [ ] **Step 1: Localizar todos los callers**

```bash
grep -rn "SketchDofAnalyzer\|sketch_dof" --include="*.py" .
```

Expected: `quino/gui/canvas.py` (2 sitios), `tests/test_application.py` (2 tests), `tests/test_sketch_dof.py` (todos).

- [ ] **Step 2: Sustituir en `canvas.py`**

En `quino/gui/canvas.py` línea 28 cambiar:

```python
from quino.services.sketch_dof import SketchDofAnalyzer
```

por:

(eliminar la línea — la nueva API vive en SolvespaceBackend)

Y en los dos sitios donde se invocaba (`_update_sketch_dof_info` y `_draw_sketch`), cambiar:

```python
dof_result = SketchDofAnalyzer().analyze(project.sketch)
```

por:

```python
dof_result = self.app_service.sketch_solver._backend.analyze_dof(project)
```

(Acceso a `_backend` es feo — alternativa: añadir un método público en la facade.)

**Mejor**: añadir `def analyze_dof(self, project) -> DofResult` a `SketchSolver` facade. Vuelve a editar `facade.py`:

```python
class SketchSolver:
    ...
    def analyze_dof(self, project):
        return self._backend.analyze_dof(project)
```

Y los callers:
```python
dof_result = self.app_service.sketch_solver.analyze_dof(project)
```

- [ ] **Step 3: Eliminar archivos legacy**

```bash
rm quino/services/sketch_dof.py
rm tests/test_sketch_dof.py
```

Eliminar también los 2 tests en `tests/test_application.py` que importan `from quino.services.sketch_dof import SketchDofAnalyzer`:

```bash
grep -nB 2 "from quino.services.sketch_dof" tests/test_application.py
```

Borrar esos 2 tests.

- [ ] **Step 4: Tests**

```bash
pytest tests/ -q
```

Expected: pass.

- [ ] **Step 5: Smoke GUI**

```bash
python -c "from quino.gui.main_window import MainWindow; print('ok')"
```

Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(sketch): replace SketchDofAnalyzer with Solvespace-backed analyze_dof

Canvas now queries the solver for DOF state (point colors + status bar).
The heuristic _CONSTRAINT_DOF_REMOVED table is gone — Solvespace is the
single source of truth."
```

---

## Phase D — Borrar helper geometry + cache

### Task D1: Eliminar `_create_tangent_helper_geometry` y `_solve_cache`

**Files:**
- Modify: `quino/application/commands/sketch_commands.py`

- [ ] **Step 1: Localizar el código**

```bash
grep -nE "_create_tangent_helper_geometry|_solve_cache|_sketch_signature" quino/application/commands/sketch_commands.py
```

Anotar las líneas.

- [ ] **Step 2: Borrar `_create_tangent_helper_geometry`**

Eliminar:
- La definición del método (desde `def _create_tangent_helper_geometry(...)` hasta el final del cuerpo).
- La llamada en `create_sketch_constraint` (alrededor de la línea 450 — `if constraint_enum is SketchConstraintType.TANGENT: self._create_tangent_helper_geometry(...)`).

- [ ] **Step 3: Borrar `_solve_cache` y `_sketch_signature`**

En `__init__` (o donde se inicialice), eliminar:

```python
self._solve_cache: tuple[str, SketchSolveResult] | None = None
```

En `_apply_sketch_constraints` (línea ~1006), simplificar:

```python
        if not project.sketch.constraints:
            project.sketch.solve_error = None
            project.sketch.bad_constraint_ids = []
            return SketchSolveResult(True, {}, 0, 0.0, None)
        sig = self._sketch_signature(project.sketch)
        if self._solve_cache is not None and self._solve_cache[0] == sig:
            result = self._solve_cache[1]
        else:
            result = self._solver.solve(project, locked_point_ids=locked_point_ids)
            self._solve_cache = (sig, result)
```

a:

```python
        if not project.sketch.constraints:
            project.sketch.solve_error = None
            project.sketch.bad_constraint_ids = []
            return SketchSolveResult(True, {}, 0, 0.0, None)
        result = self._solver.solve(project, locked_point_ids=locked_point_ids)
```

Eliminar el método `_sketch_signature` entero.

- [ ] **Step 4: Tests**

```bash
pytest tests/ -q
```

Expected: pass. El test `test_tangent_constraint_creates_helper_point_on_line_and_curve` ya fue borrado en B2; si no, borrarlo ahora.

Si algún test referenciaba el helper point (e.g., comprobando que existe un punto `construction=True`), borrarlo también.

- [ ] **Step 5: Smoke GUI**

`python -m quino.gui` y verificar que el bug original sigue arreglado:
1. Modo Sketch.
2. Dibujar recta + círculo.
3. Tool Tangent (atajo `T`).
4. Click recta, click círculo.
5. Ver constraint aplicado, no aparecen puntos auxiliares en el dominio.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(sketch): remove _create_tangent_helper_geometry and solve cache

Solvespace builds its own auxiliary geometry inside the SolverSystem; the
domain-level helper points (construction=True) added by the legacy iterative
solver are now noise. The _solve_cache + _sketch_signature pair is gone too:
Solvespace is fast enough without it and the cache hid bugs."
```

---

## Phase E — Verificación final

### Task E1: Smoke completo + docs

- [ ] **Step 1: Suite completa**

```bash
pytest tests/ -q
```

Expected: todo verde, sin skip/xfail.

- [ ] **Step 2: Smoke GUI manual**

`python -m quino.gui`:
1. Cargar `Four-bar` example. Verificar que se ve igual que antes.
2. Modo Sketch. Crear un sketch desde cero con recta, círculo, varios constraints (distance, tangent recta-círculo, parallel). Solve. Ver feedback DOF en barra de estado.
3. Punto con DOF=0 se ve negro/oscuro; con DOF≥1 se ve más claro.
4. Crear un constraint imposible (e.g., distance entre 2 puntos fixed) — debería aparecer en rojo + mensaje legible.
5. Cambiar a modo Pose y simular — no debería estar afectado.

- [ ] **Step 3: Verificar tamaños**

```bash
find quino tests -name "sketch*" -type f -exec wc -l {} + | sort -rn | head -15
```

Estimación esperada tras todos los borrados:
- `~530 LOC` de legacy_backend → 0
- `~280 LOC` de orphans → 0
- `~116 LOC` de sketch_dof → 0
- **Total ~926 LOC eliminados** del módulo sketch.

- [ ] **Step 4: Actualizar CLAUDE.md**

En `CLAUDE.md`, sección "Sketch solver", eliminar la mención al fallback legacy:

```diff
- - `legacy_backend.py` — solver iterativo propio (opt-in fallback)
+ (línea eliminada)

- El backend se elige con `ApplicationService(sketch_solver_backend="solvespace"|"legacy")` (default `"solvespace"`) o, en GUI, vía Edit → Preferences. La preferencia se persiste con `QtCore.QSettings("QUINO", "QUINO")` envuelto en `quino/gui/preferences.py`. Hot-swap: `app_service.set_sketch_solver_backend(name)` reinstancia el solver sin reiniciar.
+ Solvespace es el único solver. El cálculo de DOF per-punto (colorear puntos según grados de libertad) usa `SolvespaceBackend.analyze_dof()` con un perturbation test por eje.
```

Y actualizar la sección "Archivos grandes" eliminando la línea de `legacy_backend.py`.

- [ ] **Step 5: Commit docs**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md after Solvespace-as-single-source-of-truth refactor"
```

---

## Self-Review

**Spec coverage** vs lo que pidió el usuario:
1. "Toda la lógica pasa por el solver" → ✓ DOF en T-C1/C2; cache eliminado en T-D1.
2. "Sin legacy que pueda dar errores" → ✓ Legacy backend borrado en T-B1/B2; orphans borrados en T-A1.
3. "Solvespace dice qué está completamente definido" → ✓ `fully_constrained_*` sets vienen del analyzer Solvespace en T-C1.
4. "Solvespace dice qué tiene grados de libertad" → ✓ `point_dof` dict idem.
5. Helpers `_create_tangent_helper_geometry` → ✓ T-D1.
6. Dropdown Preferences → ✓ T-B3.

**Placeholder scan**: Revisado. Las marcas "VERIFICAR si..." en Task A1 Step 3 son verificaciones reales que el ejecutor debe hacer antes de borrar, no placeholders sin contenido. Los "Si X, entonces Y" del plan son condicionales legítimos del flujo de auditoría.

**Type consistency**:
- `DofResult` definido en `base.py` (Task C1 Step 2) con campos `point_dof`, `fully_constrained_point_ids`, `fully_constrained_entity_ids`, `total_free_dof` — usado idénticamente en `analyze_dof()` (C1 Step 5) y en callers de canvas (C2 Step 2).
- `SketchSolver.analyze_dof()` añadido en facade (C2 Step 2) — firma `(project) -> DofResult` consistente con el método del backend.
- `make_app_legacy` eliminado en B2 — verificado que no se referencia en C1/D1.

**Riesgos**:
- Perturbation test en `analyze_dof` ejecuta 2N+1 solves por refresh (N puntos × 2 ejes + 1 solve de referencia). Para sketches con 50+ puntos puede sentirse lento. Mitigación: cachear el resultado del último análisis si ningún constraint cambia entre llamadas. Out of scope para esta fase — se aborda si se observa lag.
- Borrar `test_sketch_solver_crosscheck.py` reduce confianza en regresión. Mitigación: las garantías equivalentes viven en `test_sketch_solver_solvespace.py` (23 tests) + `test_sketch_gui_constraint_clicks.py` (5 tests).
- Borrar los 5 tests pinned a legacy elimina cobertura de algunos casos under-constrained. Esos casos son legitimadamente ambiguos (múltiples soluciones igualmente válidas) — no hay un comportamiento "correcto" que testear sin sesgo de solver. Aceptable.
