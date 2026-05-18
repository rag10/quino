# QUINO — Guía para Claude

## Qué es
Editor visual de mecanismos planos con simulación (Exudyn) y modo *pose* (cinemática inversa).

## Arquitectura por capas
- `quino/domain/` — dataclasses (Model, Body, Joint, Sketch, Pose, ...). Sin lógica.
- `quino/services/` — servicios stateless (expresiones, unidades, validación, sketch solver, kinematic validation, DOF, IDs).
- `quino/application/` — fachada `ApplicationService` + command-services (ver sección abajo).
- `quino/gui/` — PySide6. `MainWindow`, `MechanismCanvas`, `gui/panels/`, `gui/widgets/`.
- `quino/solver_adapters/` — bindings a Exudyn (dinámica y pose).
- `quino/simulation/` — assembler + runner.
- `quino/pose/` — modelo + cinemática inversa.
- `quino/viewer/` — gráficas de sensores.
- `quino/serialization/` — JSON I/O.

## ApplicationService — fachada de comandos
La fachada `quino.application.service.ApplicationService` mantiene proyecto, undo/redo, snapshot e IO (new/load/save/validate/export/simulate). Delega operaciones de dominio a 7 command-services en `quino/application/commands/`:
- `parameters` — `ParameterCommands`
- `sketch` — `SketchCommands`
- `bodies` — `BodyCommands`
- `joints` — `JointCommands`
- `poses` — `PoseCommands`
- `forces` — `ForceCommands` (sensores, loads, springs)
- `entities` — `EntityCommands` (rename/delete/update_property genéricos + gravity)

Reglas:
- Cada command-service recibe un `ServiceContext` (`quino/application/_context.py`) con `project_provider`, `operation`, `snapshot` y servicios compartidos.
- Las mutaciones se envuelven en `with ctx.operation():` para registrar snapshot de undo.
- `EntityCommands` recibe referencias directas a los otros command-services (DI) porque `update_property` y `delete_entity` despachan a todos.
- La fachada conserva los métodos públicos originales como delegaciones de 1 línea (compatibilidad con GUI y tests).

## Sketch solver
El motor del modo Sketch vive en `quino/services/sketch_solving/`:
- `facade.py` — `SketchSolver` (despacha al backend según preferencia)
- `solvespace_backend.py` — adapter sobre `python-solvespace` (default)
- `legacy_backend.py` — solver iterativo propio (opt-in fallback)
- `constraint_mapping.py` — traduce cada `SketchConstraintType` al constraint nativo
- `_auxiliary_geometry.py` — emite líneas H/V invisibles para `HORIZONTAL_DISTANCE`/`VERTICAL_DISTANCE`

El backend se elige con `ApplicationService(sketch_solver_backend="solvespace"|"legacy")` (default `"solvespace"`) o, en GUI, vía Edit → Preferences. La preferencia se persiste con `QtCore.QSettings("QUINO", "QUINO")` envuelto en `quino/gui/preferences.py`. Hot-swap: `app_service.set_sketch_solver_backend(name)` reinstancia el solver sin reiniciar.

Notas:
- `quino/services/sketch_solver.py` queda como re-export shim (compat).
- Solvespace mantiene radios de circles/arcs locked vía `sys.diameter()` salvo cuando un constraint RADIUS user los gobierna.
- 6 tests en `tests/test_application.py` están pineados al backend legacy: 3 por divergencia de bias en sketches under-constrained, 3 por gaps de tangencia en el binding `python-solvespace` (ver `sketch_solver_backend="legacy"` inline en esos tests).

## Glosario de dominio
- **Body**: rígido (bar, point_mass, ground_anchor).
- **Marker**: punto material anclado a un body (incluye COM y end-effectors).
- **Joint**: revolute/translational entre dos endpoints (marker/marker, marker/ground, marker/slider).
- **Slider**: prismatic guide (eje).
- **Driver**: ley temporal sobre un joint.
- **Pose**: configuración estática del mecanismo; se resuelve con IK.
- **Sketch**: capa 2D paramétrica con constraints, se "compila" a markers/bodies.

## Convenciones
- Expresiones: strings con unidades (`"50 mm"`, `"90 deg * t / 1 s"`). Las evalúa `ExpressionService`.
- IDs: generados por `IdService` (UUID-ish, persistidos en JSON).
- Estado mutable: sólo dentro de `ApplicationService._operation()` (context manager que hace snapshot para undo).
- Tests: pytest. Los tests de GUI requieren `QT_QPA_PLATFORM=offscreen` en CI.

## Archivos grandes (en refactor — ver docs/superpowers/plans/2026-05-18-fase-*)
- `quino/gui/canvas.py` 5850 LOC (Fase 3 pendiente)
- `quino/gui/main_window.py` 4532 LOC (Fase 4 pendiente)
- `quino/solver_adapters/exudyn_adapter.py` 1684 LOC (Fase 4 pendiente)
- `quino/application/service.py` 863 LOC (Fase 2 ✓ — antes 3258)
- `quino/services/sketch_solving/legacy_backend.py` ~530 LOC (movido desde sketch_solver.py al migrar a Solvespace)

## Comandos
- Tests: `pytest tests/ -q`
- Tests GUI: `pytest tests/test_gui.py -q` (requiere `QT_QPA_PLATFORM=offscreen` en CI)
- Run app: `python -m quino.gui`
