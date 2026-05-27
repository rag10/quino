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
Solvespace (`python-solvespace`) es el único solver. El motor vive en `quino/services/sketch_solving/`:
- `facade.py` — `SketchSolver` (wrapper fino sobre `SolvespaceBackend`)
- `solvespace_backend.py` — adapter sobre `python-solvespace`, incluye `solve()` y `analyze_dof()`
- `constraint_mapping.py` — traduce cada `SketchConstraintType` al constraint nativo
- `_auxiliary_geometry.py` — emite líneas invisibles para `HORIZONTAL_DISTANCE`/`VERTICAL_DISTANCE`

**Solvespace es fuente única de verdad** para constraints, DOF per-punto y "fully constrained". El cálculo de DOF usa `SolvespaceBackend.analyze_dof()` que ejecuta un perturbation test por eje (2N+1 solves donde N es número de puntos no fijos).

Notas:
- `quino/services/sketch_solver.py` queda como re-export shim (compat).
- Solvespace mantiene radios de circles/arcs locked vía `sys.diameter()` salvo cuando hay constraint RADIUS o TANGENT que los gobierna.
- TANGENT line+curve y curve+curve se reducen a equivalencias con `PT_ON_CIRCLE` + punto auxiliar, no usa `sys.tangent()` (que no acepta circles en python-solvespace 3.0.8).

## Dominio: Workspace / Case

**Case-as-Model (schema 0.3.0)**: Cada `Case` contiene un `Model` completo (bodies, joints, drivers…). No hay composición diferencial. Las lecturas son O(1).

- `app_service._workspace` → `Workspace` (dominio)
- `app_service.workspace` → `WorkspaceCommands` (command-service)
- `app_service.project` → `_WorkspaceProjectProxy` (shim back-compat, `.workspace` devuelve `None`)
- `ws.cases[ws.root_case_ids[0]]` → caso raíz de la workspace activa
- `Case.poses` / `Case.analyses` / `Case.runs` → listas propias del caso
- `Pose` vive en `quino.domain.workspace`, **no** en `quino.domain.model`
- `simulation_initial_pose_id` se persiste mediante `pose.is_default = True`
- Después de `new_workspace()` y `load_workspace()` hay que actualizar `_service_context.ids = self.id_service`

## Glosario de dominio
- **Body**: rígido (bar, point_mass, ground_anchor).
- **Marker**: punto material anclado a un body (incluye COM y end-effectors).
- **Joint**: revolute/translational entre dos endpoints (marker/marker, marker/ground, marker/slider).
- **Slider**: prismatic guide (eje).
- **Driver**: ley temporal sobre un joint.
- **Pose**: configuración estática del mecanismo; se resuelve con IK. Vive en `Case.poses`.
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
