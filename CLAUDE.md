# QUINO — Guía para Claude

## Qué es
Editor visual de mecanismos planos con simulación (Exudyn) y modo *pose* (cinemática inversa).

## Arquitectura por capas
- `quino/domain/` — dataclasses (Model, Body, Joint, Sketch, Pose, ...). Sin lógica.
- `quino/services/` — servicios stateless (expresiones, unidades, validación, sketch solver, DOF, IDs).
- `quino/application/` — `ApplicationService` (fachada de casos de uso + undo/redo + snapshot).
- `quino/gui/` — PySide6. `MainWindow`, `MechanismCanvas`, paneles, widgets.
- `quino/solver_adapters/` — bindings a Exudyn (dinámica y pose).
- `quino/simulation/` — assembler + runner.
- `quino/pose/` — modelo + cinemática inversa.
- `quino/viewer/` — gráficas de sensores.
- `quino/serialization/` — JSON I/O.

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
- `quino/gui/canvas.py` 5850 LOC
- `quino/gui/main_window.py` 4532 LOC
- `quino/application/service.py` 3258 LOC
- `quino/solver_adapters/exudyn_adapter.py` 1684 LOC

## Comandos
- Tests: `pytest tests/ -q`
- Tests GUI: `pytest tests/test_gui.py -q` (requiere `QT_QPA_PLATFORM=offscreen` en CI)
- Run app: `python -m quino.gui`
