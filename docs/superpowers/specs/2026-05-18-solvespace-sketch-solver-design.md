# Solvespace as default sketch solver — Design Spec

**Date**: 2026-05-18
**Status**: approved — awaiting implementation plan

## Goal

Sustituir el solver iterativo propio (`quino/services/sketch_solver.py`, 947 LOC) por **Solvespace** como motor por defecto del modo Sketch, manteniendo el solver actual como fallback opt-in seleccionable por el usuario.

## Motivación

1. **Robustez de convergencia**: el solver iterativo propio converge mal en configuraciones casi-singulares, ciclos cerrados y geometrías sub-restringidas. Solvespace usa Newton-Raphson sobre el sistema completo y converge donde el actual oscila o falla.
2. **Compatibilidad CAD y constraints avanzados**: Solvespace cubre nativamente más casos (`arc_line_tangent`, `curve_curve_tangent`, `symmetric` con eje, `dragged` group para drag interactivo) que serían costosos de implementar en el solver propio.

No son motivos primarios: rendimiento (no es bloqueante hoy) ni reducir LOC (el legacy se mantiene como fallback, no se borra).

## Decisiones tomadas

| # | Decisión | Valor |
|---|---|---|
| D1 | Estrategia de coexistencia | Solvespace por defecto; legacy como fallback opt-in |
| D2 | Toggle | Preferencia global de usuario persistida |
| D3 | Mecanismo de persistencia | `QtCore.QSettings("QUINO", "QUINO")` |
| D4 | Paquete Python | `python-solvespace` (PyPI, wrapper Cython sobre libslvs) |
| D5 | Constraints faltantes (HORIZONTAL_DISTANCE, VERTICAL_DISTANCE) | Mapear con geometría auxiliar invisible creada por solve |
| D6 | Drag interactivo en canvas | Solvespace también (grupo "dragged" nativo) |
| D7 | Tests existentes | Conservar resultados finales, relajar asertos sobre internos (iterations, max_error exacto, orden de bad_constraints) |

## Arquitectura

### Estructura de archivos

```
quino/services/sketch_solving/
├── __init__.py                 # re-export SketchSolver, SketchSolveResult, SketchSolverBackend
├── base.py                     # SketchSolverBackend Protocol + SketchSolveResult dataclass
├── facade.py                   # SketchSolver: dispatcher que delega al backend elegido
├── legacy_backend.py           # solver iterativo actual (movido íntegro desde sketch_solver.py)
├── solvespace_backend.py       # nuevo adapter sobre python-solvespace
├── constraint_mapping.py       # tabla QUINO ↔ Solvespace
└── _auxiliary_geometry.py      # helpers que sintetizan geom auxiliar (líneas H/V invisibles)
```

`quino/services/sketch_solver.py` se mantiene como **shim** que re-exporta `SketchSolver` y `SketchSolveResult` desde el paquete, para no romper imports en `service.py`, `sketch_commands.py`, `canvas.py` ni tests.

### Interfaz

```python
# quino/services/sketch_solving/base.py
from typing import Protocol

class SketchSolverBackend(Protocol):
    name: str  # "solvespace" | "legacy"

    def solve(
        self,
        project: Project,
        *,
        locked_point_ids: set[str] | None = None,
        max_iterations: int = 200,
        tolerance: float = 1e-6,
    ) -> SketchSolveResult: ...
```

`SketchSolveResult` se conserva **idéntico** al actual:

```python
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
```

Ningún caller necesita cambios.

### Facade

```python
# quino/services/sketch_solving/facade.py
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


def _make_backend(name: str, expr, units) -> SketchSolverBackend:
    if name == "solvespace":
        from quino.services.sketch_solving.solvespace_backend import SolvespaceBackend
        return SolvespaceBackend(expr, units)
    if name == "legacy":
        from quino.services.sketch_solving.legacy_backend import LegacyIterativeBackend
        return LegacyIterativeBackend(expr, units)
    raise ValueError(f"Unknown sketch solver backend: {name!r}")
```

### Wire-up del toggle

- `ApplicationService.__init__` recibe `sketch_solver_backend: str = "solvespace"` como nuevo argumento opcional.
- Guarda el valor; instancia `self.sketch_solver = SketchSolver(..., backend=self._sketch_solver_backend)`.
- Cambiar el backend tras la construcción: `app_service.set_sketch_solver_backend("legacy")` reinstancia `self.sketch_solver`. La preferencia GUI llama este método tras aceptar el diálogo.
- Los tests pueden instanciar `ApplicationService(sketch_solver_backend="legacy")` sin tocar `QSettings`.

### Preferences

Nuevo módulo `quino/gui/preferences.py`:

```python
from PySide6 import QtCore

class Preferences:
    _SKETCH_SOLVER_KEY = "sketch/solver_backend"

    def __init__(self) -> None:
        self._qs = QtCore.QSettings("QUINO", "QUINO")

    @property
    def sketch_solver_backend(self) -> str:
        return self._qs.value(self._SKETCH_SOLVER_KEY, "solvespace", type=str)

    @sketch_solver_backend.setter
    def sketch_solver_backend(self, value: str) -> None:
        assert value in ("solvespace", "legacy")
        self._qs.setValue(self._SKETCH_SOLVER_KEY, value)
```

`MainWindow.__init__` lee la preferencia al arrancar y pasa el valor a `ApplicationService(sketch_solver_backend=...)`. `_show_preferences_dialog` añade un dropdown:

```
[Sketch solver]  ( Solvespace ▼ )
[tooltip: "Solvespace es más robusto. Legacy es el solver iterativo propio."]
```

Al aceptar el diálogo:
1. `Preferences().sketch_solver_backend = nuevo_valor`
2. `self.app_service.set_sketch_solver_backend(nuevo_valor)`
3. Trigger refresh del canvas si fuera necesario.

QSettings persistencia: Windows registro `HKCU\Software\QUINO\QUINO`; Linux `~/.config/QUINO/QUINO.conf`; macOS plist.

## Mapping de constraints

Tabla de traducción `SketchConstraintType` → API de `python-solvespace`.

**Nota sobre los nombres de API**: los ejemplos de método (`Constraint.horizontal(line)`, `system.add_point_2d(...)`, etc.) son **ilustrativos del modelo conceptual de libslvs**. Los nombres exactos del binding `python-solvespace` se verifican en la Tarea 1 del plan de implementación y esta tabla se actualiza si difieren. La forma del mapeo (qué constraint nativo se usa para cada `SketchConstraintType`) es la decisión vinculante; los identificadores son sustituibles.

| QUINO | Solvespace | Notas |
|---|---|---|
| `FIX` | Punto en grupo 1 (fijo) | Solvespace permite separar entidades en grupos: grupo 1 = constantes, grupo 2 = libres. `FIX` mete los puntos referenciados en el grupo 1. |
| `HORIZONTAL` | `Constraint.horizontal(line)` | Directo. |
| `VERTICAL` | `Constraint.vertical(line)` | Directo. |
| `DISTANCE` (pt-pt) | `Constraint.distance(p1, p2, d)` | Directo. |
| `DISTANCE` (pt-line) | `Constraint.distance(point, line, d)` | Solvespace lo distingue por tipo de operando. |
| `HORIZONTAL_DISTANCE` | **Auxiliar**: línea horizontal por p1 + `distance` p2 → línea | Requiere geom auxiliar (ver abajo). |
| `VERTICAL_DISTANCE` | **Auxiliar**: línea vertical por p1 + `distance` p2 → línea | Idem. |
| `RADIUS` | `Constraint.diameter(circle/arc, 2*r)` | Solvespace usa diámetro; conversión `d = 2*r`. |
| `COINCIDENT` (pt-pt) | `Constraint.coincident(p1, p2)` | Directo. |
| `COINCIDENT` (pt-entidad) | `Constraint.coincident(point, entity)` | Polimórfico en Solvespace. |
| `PARALLEL` | `Constraint.parallel(l1, l2)` | Directo. |
| `PERPENDICULAR` | `Constraint.perpendicular(l1, l2)` | Directo. |
| `EQUAL_LENGTH` | `Constraint.equal(l1, l2)` | Directo. |
| `ANGLE` | `Constraint.angle(l1, l2, deg)` | Solvespace usa grados; QUINO ya almacena en grados. |
| `MIDPOINT` | `Constraint.midpoint(point, line)` | Directo. |
| `COLLINEAR` (3+ puntos) | Descomponer en N-2 `coincident(point, line(p_i, p_j))` | Emisión múltiple. |
| `SYMMETRIC` | `Constraint.symmetric(p1, p2, line)` | Directo. |
| `ON_CIRCLE` | `Constraint.coincident(point, circle/arc)` | Directo. |
| `TANGENT` (línea-arco) | `Constraint.arc_line_tangent(arc, line)` | Directo. |
| `TANGENT` (arco-arco) | `Constraint.curve_curve_tangent(c1, c2)` | Directo. |

**Verificación previa obligatoria**: la primera tarea del plan de implementación verificará la API exacta de `python-solvespace` (los nombres concretos de `Constraint` pueden variar). Si algún mapping debe ajustarse, esta tabla se actualiza antes de continuar.

### Geometría auxiliar

Sólo HORIZONTAL_DISTANCE y VERTICAL_DISTANCE la requieren:

```python
def emit_horizontal_distance(system, workplane, p1, p2, distance):
    """Crea una línea horizontal aux por p1, restringe p2 a estar a `distance` de ella."""
    aux_x = p1.x + 1.0  # arbitrario, sólo define dirección
    aux_point = system.add_point_2d(aux_x, p1.y, workplane, group=2)
    aux_line = system.add_line_2d(p1, aux_point, workplane, group=2)
    system.add_constraint_horizontal(aux_line, workplane)
    system.add_constraint_distance(p2, aux_line, distance, workplane)
```

**Invariante crítico**: la geometría auxiliar vive **sólo dentro de `SolvespaceBackend.solve()`**. No entra al `Project`/dominio. Se descarta junto con el `System` al terminar el solve. Cada solve la regenera. Beneficio: el dominio sigue siendo la fuente única de verdad y no contiene basura del backend.

## Adapter — pipeline de solve

```
1. Construir System() limpio (sin estado entre llamadas).
2. Crear workplane 2D estándar (origen + ejes X/Y nominales en grupo 1).
3. Para cada SketchPoint:
   - Evaluar x, y vía ExpressionService.
   - Grupo 1 (fijo) si id ∈ locked_point_ids o tiene constraint FIX.
   - Grupo 2 (libre) en caso contrario.
   - Crear Point2d. Guardar mapeo id → handle.
4. Para cada entidad (LineSegment, InfiniteLine, Circle, Arc):
   - Crear entidad Solvespace usando los handles de puntos.
   - Guardar id → handle.
5. Para cada SketchConstraint:
   - Lookup en constraint_mapping.
   - Si requiere aux: emitir aux + constraint compuesto.
   - Si no: emitir directo.
6. system.solve().
7. Lectura post-solve:
   - positions = {pid: (handle.x, handle.y) for pid, handle in points}
   - radius_updates = {circle/arc_id: handle.distance/2 for ...}
8. Mapear código nativo a SketchSolveResult:
   - success = code ∈ {OK, REDUNDANT_OKAY}
   - iterations = system.iter_count (si la API lo expone; si no, 0)
   - max_error = 0.0 si success, else tolerance reportada
   - bad_constraints = system.failed_constraints() → mapeo inverso a constraint_id
   - constraint_errors = vacío en happy path; lleno tras re-evaluar residuales en fallo
   - message = descripción del código
9. return SketchSolveResult(...)
```

### Drag preview

El caller pasa `locked_point_ids = todos_excepto_el_arrastrado`. Solvespace pone el dragado en grupo 2 (libre) y el resto en grupo 1 (fijo). Es el patrón nativo de Solvespace, diseñado exactamente para esto. Sin ramas especiales en el código.

### Sin estado entre llamadas

Cada `solve()` reconstruye el `System` desde cero. **No reusamos** estado entre invocaciones, aunque Solvespace lo permitiría. Razón: dominio = fuente única de verdad. Coste: re-emisión de entidades cada solve. Beneficio: cero clases de bugs por estado stale.

Si en el futuro el rendimiento en sketches muy grandes se vuelve problema, se optimiza con cache de System por hash del sketch (fuera de scope).

### Errores de mapping

Excepciones durante la traducción (constraint con referencias inconsistentes, geometría inválida) se capturan en el adapter y se devuelven como `SketchSolveResult(success=False, message="Mapping error: ...", bad_constraints=[constraint_id])`. Equivalente al comportamiento del legacy ante datos inválidos.

## Tests

### A) Tests existentes — relajación de asertos

Auditoría inicial en la primera tarea del plan. En `tests/test_sketch_*.py` y `tests/test_application.py`:

- `.iterations == N` → eliminar o relajar a `>= 0`.
- `.max_error == X` con valor float exacto → relajar a `< tolerance` o eliminar.
- `.bad_constraints == [...]` con orden concreto → comparar como `set`.
- Asertos sobre **posiciones finales** (`pytest.approx(..., abs=1e-6)` y similares): **conservar tal cual**.

Estos tests siguen ejecutándose contra el backend por defecto (Solvespace) y son la garantía de equivalencia end-to-end.

### B) Cross-check parametrizado — nuevo

`tests/test_sketch_solver_crosscheck.py`:

```python
@pytest.fixture(params=["solvespace", "legacy"])
def app_service(request):
    return ApplicationService(sketch_solver_backend=request.param)
```

~10-15 escenarios cubriendo cada familia de constraint:
- `test_simple_distance_constraint_converges`
- `test_four_bar_geometry_solves`
- `test_horizontal_distance_with_aux_geometry`
- `test_vertical_distance_with_aux_geometry`
- `test_radius_updates_propagated`
- `test_drag_preview_holds_locked_points`
- `test_overconstrained_returns_failure`
- `test_underconstrained_solves_in_reasonable_position`
- `test_tangent_line_arc_converges`
- `test_collinear_three_points`
- `test_symmetric_about_line`
- `test_perpendicular_lines`
- `test_parallel_lines`
- `test_equal_length_lines`
- `test_midpoint_constraint`

Cada test corre dos veces (una por backend) y verifica:
- `result.success` igual entre backends.
- Posiciones finales coinciden dentro de tolerancia laxa (1e-4 mm — los dos solvers convergen numéricamente distinto).

### C) Solvespace-specific — nuevo

`tests/test_sketch_solver_solvespace.py` para casos que sólo Solvespace maneja correctamente:
- Detección de redundancia (`REDUNDANT_OKAY`)
- Detección de inconsistencia con lista culpable
- Tangencia arco-arco
- Sketches sub-restringidos sin desplazamiento parásito

### D) Preferencias y toggle

`tests/test_preferences.py`:
- `Preferences().sketch_solver_backend` default = `"solvespace"`.
- Set/get round-trip via QSettings (con `QSettings.IniFormat` apuntando a temp dir para aislamiento).
- `ApplicationService(sketch_solver_backend="legacy")` instancia el backend correcto.
- `app_service.set_sketch_solver_backend(nuevo)` reinstancia el solver.

## Dependencias

Añadir a `pyproject.toml`:

```toml
dependencies = [
    "python-solvespace>=3.0",
]
```

Mover de optional a default: Solvespace es el solver por defecto, no es opcional. Se documenta en README/CLAUDE.md el cambio.

**Riesgo previo verificable**: confirmar que `python-solvespace` provee wheels para Windows + Python 3.11/3.12. Si no, la primera tarea del plan resuelve esto (instalación manual, build, o paquete alternativo).

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| `python-solvespace` no tiene wheel para Windows | Tarea 1 del plan verifica instalación. Si falla, evaluar `py-slvs` o build desde fuente antes de seguir. |
| API real difiere de la tabla de mapping documentada | Tarea 1 incluye smoke de cada `Constraint.X` antes de redactar `solvespace_backend.py`. |
| Geometría auxiliar leaks al dominio | Invariante explícito + test `test_no_aux_geometry_in_project_after_solve`. |
| Cross-check falla por diferencia numérica > 1e-4 | Si afecta a un caso documentado, el test usa tolerancia más laxa con razón documentada. Si afecta a un caso real, es bug de mapping → investigar. |
| Tests viejos pierden cobertura tras relajación de asertos | Auditoría completa antes de relajar, lista de cada cambio en el commit. |
| QSettings persiste valores corruptos | Si el valor no es `solvespace`/`legacy`, fallback silencioso a `solvespace` con warning en log. |

## Out of scope

- Mover otras lógicas (validación, kinemáticas) a Solvespace.
- Importar/exportar archivos `.slvs`.
- Reescribir tests desde cero.
- Optimización con cache de `System` entre solves.
- UI avanzada (lista de constraints redundantes con highlight visual, etc.).
- Soporte 3D.

## Aceptación

La fase está completa cuando:
1. `pytest tests/ -q` pasa con Solvespace como backend por defecto (todos los tests sketch existentes verdes tras relajación).
2. `pytest tests/ -q` pasa con `ApplicationService(sketch_solver_backend="legacy")` forzado (cross-check verifica equivalencia).
3. El diálogo Preferences muestra el selector de solver y persiste el cambio.
4. El cambio en caliente (cambiar preferencia → siguiente solve usa el nuevo backend) funciona sin reiniciar.
5. Mecanismos de drag preview y solve final usan Solvespace por defecto sin diferencia perceptible al usuario.
6. `quino/services/sketch_solver.py` queda como shim de 5-10 líneas.
7. README/CLAUDE.md mencionan la nueva dependencia.
