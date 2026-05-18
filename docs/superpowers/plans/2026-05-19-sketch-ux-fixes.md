# Sketch UX fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Arreglar los problemas críticos de UX en el modo Sketch detectados en la auditoría de 2026-05-19: tangencia recta-círculo silenciosamente rota, mensajes de error ininteligibles, fallos de constraint invisibles, y de-duplicar herramientas redundantes.

**Architecture:** El núcleo de los fixes está en 3 lugares: (1) `quino/services/sketch_solving/constraint_mapping.py` — reescribir `_emit_tangent` evitando la `sys.tangent()` rota de python-solvespace, usando equivalentes basados en `distance`. (2) `quino/application/commands/sketch_commands.py` — `solve_sketch()` debe traducir `bad_constraints` (ids UUID) a mensajes humanos describiendo cada constraint fallido. (3) `quino/gui/canvas.py` — propagar `bad_constraint_ids` desde el último solve y dibujar esos constraints en rojo. Las mejoras UX restantes (atajos de teclado, dedupe ON_CIRCLE) son cambios localizados.

**Tech Stack:** Python 3.11+, PySide6, python-solvespace 3.0.8, pytest.

**Pre-requisitos:** Migración Solvespace completada (rama `refactor/fase-1-extracciones`, HEAD = `8838a78`). Tests baseline: 398 pass, 1 skip, 1 xfail.

**Referencia:** Auditoría inline en la conversación de 2026-05-19. Los 6 tests pineados a legacy actualmente en `tests/test_application.py` por el gap de `sys.tangent(line, circle)` deben volver al backend default tras esta fase.

---

## File Structure

```
quino/services/sketch_solving/
├── constraint_mapping.py        ← reescribir _emit_tangent (Task 1)
└── solvespace_backend.py        ← exponer bad-constraint info más rica (Task 2 si necesario)

quino/application/commands/
└── sketch_commands.py           ← solve_sketch() traduce ids a mensajes (Task 2)

quino/domain/
└── model.py                     ← Sketch.bad_constraint_ids: list[str] (Task 3)

quino/gui/
├── canvas.py                    ← _draw_sketch_constraints respeta bad_constraint_ids per-constraint (Task 3); eliminar ON_CIRCLE tool (Task 4); atajos (Task 5)
└── main_window.py               ← atajos (Task 5); cleanup toolbar (Task 7)

tests/
├── test_sketch_solver_solvespace.py   ← tests para nuevo _emit_tangent
├── test_sketch_solver_crosscheck.py   ← des-xfail/des-skip los 3 tests pineados a legacy por tangent
├── test_application.py                ← des-pinear los 6 tests legacy de tangent
├── test_sketch_solve_messages.py      ← NUEVO (Task 2): mensajes de error humanos
├── test_sketch_bad_constraint_visual.py  ← NUEVO (Task 3): bad_constraint_ids propagation
└── test_sketch_gui_constraint_clicks.py  ← NUEVO (Task 6): secuencias de clicks
```

---

## Task 1: Re-implementar TANGENT line+curve y curve-curve

**Files:**
- Modify: `quino/services/sketch_solving/constraint_mapping.py:275-309`
- Modify: `tests/test_sketch_solver_solvespace.py` (añadir tests específicos)
- Modify: `tests/test_application.py` (despineado de los 3 tests legacy de tangent)
- Modify: `tests/test_sketch_solver_crosscheck.py` (despineado de los xfails de tangent si los hubiera)

**Estrategia**: en lugar de llamar `sys.tangent(line, circle)` (que falla), usar identidades geométricas:
- **Tangent recta–círculo**: distancia perpendicular del centro a la recta = radio.
- **Tangent recta–arco**: igual (arco tiene centro y radio).
- **Tangent círculo–círculo**: distancia entre centros = |r1 ± r2| según sign (externa = `r1 + r2`, interna = `|r1 - r2|`).
- **Tangent arco–arco**: igual.
- **Tangent recta–arco** ya funciona con `sys.tangent()` si el arco se ha creado como `add_arc()` — verificar y dejar como fallback.

El campo `constraint.value` ya almacena `"1"` (externa) o `"-1"` (interna), preguntado por el diálogo del canvas. Lo usamos para el signo en el caso curve-curve.

- [ ] **Step 1: Baseline tests**

```bash
pytest tests/ -q
```

Expected: `398 passed, 1 skipped, 1 xfailed` (ver `docs/superpowers/plans/2026-05-18-solvespace-sketch-solver.md` para contexto).

- [ ] **Step 2: Localizar los 6 tests pineados a legacy y los xfails**

```bash
grep -nE "sketch_solver_backend=\"legacy\"" tests/test_application.py
grep -nE "xfail|@pytest.mark.skip" tests/test_sketch_solver_crosscheck.py tests/test_sketch_solver_solvespace.py
```

Anotar los nombres exactos de los tests legacy-pinned por tangent (deben ser 3 de los 6 pineados; los otros 3 son por bias divergence, esos siguen pineados).

- [ ] **Step 3: Añadir test fallido para tangent line-circle**

En `tests/test_sketch_solver_solvespace.py`, añadir AL FINAL:

```python
def test_tangent_line_to_circle_makes_line_touch_circle():
    """Recta tangente a círculo: la distancia del centro a la recta = radio."""
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    # Recta de (0,0) a (10,0), inicialmente alejada del círculo.
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    line = svc.create_sketch_line_segment(p1, p2, "L")
    # Círculo centro (5, 8) radio 3 — separado de la recta por dist=8.
    center = svc.create_sketch_point("5 mm", "8 mm", "C")
    circle = svc.create_sketch_circle(center, "3 mm", "Circ")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    svc.create_sketch_constraint("fix", [center])
    svc.create_sketch_constraint(
        "tangent", [p1, p2], value="1", entity_references=[circle]
    )
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    # El radio del círculo debe haberse ajustado a 8 (distancia del centro a la recta = 8)
    assert circle in result.radius_updates
    assert abs(result.radius_updates[circle] - 8.0) < 1e-3


def test_tangent_circle_to_circle_external():
    """Dos círculos tangentes externos: distancia entre centros = r1 + r2."""
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    c1 = svc.create_sketch_point("0 mm", "0 mm", "C1")
    c2 = svc.create_sketch_point("20 mm", "0 mm", "C2")
    circ1 = svc.create_sketch_circle(c1, "5 mm", "Circ1")
    circ2 = svc.create_sketch_circle(c2, "3 mm", "Circ2")
    svc.create_sketch_constraint("fix", [c1])
    svc.create_sketch_constraint("fix", [c2])
    svc.create_sketch_constraint(
        "tangent", [], value="1", entity_references=[circ1, circ2]
    )
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    # distancia centros = 20; r1+r2 debería ser 20 (uno se ajusta)
    r1 = result.radius_updates.get(circ1, 5.0)
    r2 = result.radius_updates.get(circ2, 3.0)
    assert abs((r1 + r2) - 20.0) < 1e-3


def test_tangent_circle_to_circle_internal():
    """Dos círculos tangentes internos: distancia entre centros = |r1 - r2|."""
    svc = ApplicationService(sketch_solver_backend="solvespace")
    svc.new_project("T")
    svc.create_sketch("S")
    c1 = svc.create_sketch_point("0 mm", "0 mm", "C1")
    c2 = svc.create_sketch_point("5 mm", "0 mm", "C2")
    circ1 = svc.create_sketch_circle(c1, "10 mm", "Circ1")
    circ2 = svc.create_sketch_circle(c2, "3 mm", "Circ2")
    svc.create_sketch_constraint("fix", [c1])
    svc.create_sketch_constraint("fix", [c2])
    svc.create_sketch_constraint(
        "tangent", [], value="-1", entity_references=[circ1, circ2]
    )
    result = _make_backend().solve(svc.project)
    assert result.success, result.message
    r1 = result.radius_updates.get(circ1, 10.0)
    r2 = result.radius_updates.get(circ2, 3.0)
    # |r1 - r2| = 5 (distancia entre centros)
    assert abs(abs(r1 - r2) - 5.0) < 1e-3
```

- [ ] **Step 4: Ejecutar el test, debe fallar**

```bash
pytest tests/test_sketch_solver_solvespace.py::test_tangent_line_to_circle_makes_line_touch_circle -v
```

Expected: FAIL — el constraint queda en `bad_constraints` porque `sys.tangent(line, circle)` rechaza la combinación.

- [ ] **Step 5: Reescribir `_emit_tangent`**

Reemplazar todo el contenido del método `_emit_tangent` (líneas ~275-309 de `quino/services/sketch_solving/constraint_mapping.py`) con:

```python
def _emit_tangent(sys, wp, c, points, entities, project, expressions, units):
    """Tangency between line+curve or curve+curve.

    python-solvespace's sys.tangent() only accepts arc/cubic entities (not
    circles), and doesn't handle line+curve cleanly. We sidestep both issues
    by reducing tangency to distance equalities:

    - line + circle/arc → distance(center, line) == radius
    - circle + circle (or arc+arc, mixed) → distance(center1, center2) == r1 ± r2,
      where ± is controlled by `constraint.value` ("1" external = +, "-1" internal = -)

    QUINO stores either:
      - references=[line_p1, line_p2], entity_references=[curve_entity_id]
      - references=[], entity_references=[curve1_id, curve2_id]
    """
    from quino.domain.model import SketchArc, SketchCircle

    sketch = project.sketch
    n_refs = len(c.references)
    n_ents = len(c.entity_references)

    def _curve_center_and_radius(entity_id: str):
        ent = sketch.entities.get(entity_id) if sketch is not None else None
        if not isinstance(ent, (SketchCircle, SketchArc)):
            raise ValueError(f"tangent: entity {entity_id!r} is not a circle/arc")
        center_handle = points.get(ent.center_point_id)
        if center_handle is None:
            raise ValueError(f"tangent: center point of {entity_id!r} missing in handle map")
        curve_handle = entities.get(entity_id)
        if curve_handle is None:
            raise ValueError(f"tangent: entity {entity_id!r} not built in solver")
        if isinstance(ent, SketchCircle):
            radius_mm = float(units.convert(
                expressions.evaluate_expression(ent.radius.text, project.parameters),
                ent.radius.unit,
            ))
        else:  # SketchArc — radius from center to start point
            from_pt = next(
                p for p in sketch.points() if p.id == ent.start_point_id
            )
            cx = float(units.convert(
                expressions.evaluate_expression(ent.center_point_id_x_unused if False else (
                    next(p for p in sketch.points() if p.id == ent.center_point_id)
                ).x.text, project.parameters),
                "mm",
            ))
            # Simpler readback: trust solver's stored distance entity if available
            radius_mm = 0.0  # falls through to fixed-radius constraint below
        return center_handle, curve_handle, radius_mm

    if n_refs == 2 and n_ents == 1:
        # Line tangent to circle/arc → distance(center, line) = radius
        line_p1 = points.get(c.references[0])
        line_p2 = points.get(c.references[1])
        if line_p1 is None or line_p2 is None:
            raise ValueError(f"tangent: unknown line point in {c.references}")
        line = sys.add_line_2d(line_p1, line_p2, wp)
        center_handle, curve_handle, radius_mm = _curve_center_and_radius(c.entity_references[0])
        sys.distance(center_handle, line, radius_mm, wp)
        return

    if n_refs == 0 and n_ents == 2:
        # Curve-curve tangency: distance(c1, c2) = r1 ± r2
        c1_center, _, r1 = _curve_center_and_radius(c.entity_references[0])
        c2_center, _, r2 = _curve_center_and_radius(c.entity_references[1])
        sign = 1.0
        if c.value is not None:
            try:
                raw = expressions.evaluate_expression(c.value.expression, project.parameters)
                sign_val = float(units.convert(raw, c.value.unit))
                sign = -1.0 if sign_val < 0 else 1.0
            except Exception:
                sign = 1.0
        target_distance = abs(r1 + sign * r2)
        sys.distance(c1_center, c2_center, target_distance, wp)
        return

    raise ValueError(
        f"tangent expects (2 pt refs + 1 entity ref) or (0 pt refs + 2 entity refs), "
        f"got refs={c.references} entity_refs={c.entity_references}"
    )
```

NOTA sobre arcs: el código de arriba tiene una simplificación para arcs (devuelve `radius_mm = 0.0` y deja la distancia mal). El plan asume primero validación con circles. Para arcs, hay que extender `_curve_center_and_radius` así (sustitúyelo en su lugar real):

```python
def _curve_center_and_radius(entity_id: str):
    ent = sketch.entities.get(entity_id) if sketch is not None else None
    if not isinstance(ent, (SketchCircle, SketchArc)):
        raise ValueError(f"tangent: entity {entity_id!r} is not a circle/arc")
    center_handle = points.get(ent.center_point_id)
    if center_handle is None:
        raise ValueError(f"tangent: center point of {entity_id!r} missing in handle map")
    curve_handle = entities.get(entity_id)
    if curve_handle is None:
        raise ValueError(f"tangent: entity {entity_id!r} not built in solver")
    if isinstance(ent, SketchCircle):
        quantity = expressions.evaluate_expression(ent.radius.text, project.parameters)
        radius_mm = float(units.convert(quantity, ent.radius.unit))
    else:
        # Arc: radius = distance from center to start point
        center_pt = next(p for p in sketch.points() if p.id == ent.center_point_id)
        start_pt = next(p for p in sketch.points() if p.id == ent.start_point_id)
        cx_q = expressions.evaluate_expression(center_pt.x.text, project.parameters)
        cy_q = expressions.evaluate_expression(center_pt.y.text, project.parameters)
        sx_q = expressions.evaluate_expression(start_pt.x.text, project.parameters)
        sy_q = expressions.evaluate_expression(start_pt.y.text, project.parameters)
        cx = float(units.convert(cx_q, center_pt.x.unit))
        cy = float(units.convert(cy_q, center_pt.y.unit))
        sx = float(units.convert(sx_q, start_pt.x.unit))
        sy = float(units.convert(sy_q, start_pt.y.unit))
        radius_mm = ((sx - cx) ** 2 + (sy - cy) ** 2) ** 0.5
    return center_handle, curve_handle, radius_mm
```

- [ ] **Step 6: Ejecutar los 3 tests nuevos**

```bash
pytest tests/test_sketch_solver_solvespace.py::test_tangent_line_to_circle_makes_line_touch_circle tests/test_sketch_solver_solvespace.py::test_tangent_circle_to_circle_external tests/test_sketch_solver_solvespace.py::test_tangent_circle_to_circle_internal -v
```

Expected: 3 passed.

- [ ] **Step 7: Desbloquear los tests pineados a legacy por tangent**

Localizar en `tests/test_application.py` los tests que usan `ApplicationService(sketch_solver_backend="legacy")` con un comentario que menciona tangent/python-solvespace gap. Por cada uno:
1. Quitar el argumento explícito `sketch_solver_backend="legacy"` (o sustituir por `make_app()` en lugar de `make_app_legacy()`).
2. Borrar el comentario que explica por qué está pineado.

Hacer lo mismo en `tests/test_sketch_solver_crosscheck.py` si hay xfails específicos de tangent.

- [ ] **Step 8: Suite completa**

```bash
pytest tests/ -q
```

Expected: `401 passed, 1 skipped, 1 xfailed` (398 baseline + 3 tangent nuevos; los des-pineos no añaden tests, sólo cambian qué backend usan).

Si fallan los tests des-pineados: investigar. Posibles causas:
- Bias divergence en sketches under-constrained (las 3 que siguen pineadas por OTRA razón) — re-pinearlos.
- Otro corner case de tangent (e.g. arc+arc) — añadir caso en `_curve_center_and_radius`.

- [ ] **Step 9: Commit**

```bash
git add quino/services/sketch_solving/constraint_mapping.py tests/test_sketch_solver_solvespace.py tests/test_application.py tests/test_sketch_solver_crosscheck.py
git commit -m "fix(sketch/solvespace): implement tangent via distance equalities (workaround python-solvespace gap)"
```

---

## Task 2: Mensajes de error humanos para constraints fallidos

**Files:**
- Modify: `quino/services/sketch_solving/solvespace_backend.py` (añadir `bad_constraint_messages` al SketchSolveResult.message)
- Modify: `quino/services/sketch_solving/base.py` (extender SketchSolveResult con `bad_constraint_details: dict[str, str]`)
- Modify: `quino/services/sketch_solving/legacy_backend.py` (paridad con backend nuevo — devolver `bad_constraint_details={}` por defecto)
- Modify: `quino/application/commands/sketch_commands.py:524-538` (`solve_sketch()` traduce ids a mensajes humanos)
- Create: `tests/test_sketch_solve_messages.py`

- [ ] **Step 1: Extender SketchSolveResult**

En `quino/services/sketch_solving/base.py`, dentro del `@dataclass class SketchSolveResult`, añadir un campo después de `bad_constraints`:

```python
bad_constraint_details: dict[str, str] = field(default_factory=dict)
"""Map from constraint id to human-readable failure description."""
```

- [ ] **Step 2: Capturar el motivo en `solvespace_backend.py`**

Modificar el bucle de emisión en `_solve_with_system` (líneas ~109-131). Reemplazar:

```python
            try:
                emit_constraint(...)
            except (ValueError, TypeError):
                bad_constraints.append(c.id)
```

por:

```python
            try:
                emit_constraint(
                    sys, wp, c,
                    points=point_handles,
                    entities=entity_handles,
                    project=project,
                    expressions=self._expressions,
                    units=self._units,
                )
            except (ValueError, TypeError) as exc:
                bad_constraints.append(c.id)
                bad_constraint_details[c.id] = str(exc)
```

Antes del bucle, inicializar:

```python
bad_constraint_details: dict[str, str] = {}
```

Pasar al resultado al final:

```python
return SketchSolveResult(
    success=success,
    positions=positions,
    iterations=0,
    max_error=0.0 if success else math.inf,
    message=None if success else f"Solver did not converge ({len(bad_constraints)} bad constraints)",
    bad_constraints=bad_constraints,
    radius_updates=radius_updates,
    bad_constraint_details=bad_constraint_details,
)
```

(El `message` ya no necesita meter los UUIDs — eso lo hará la fachada con nombres humanos.)

- [ ] **Step 3: Paridad en legacy_backend**

Buscar en `quino/services/sketch_solving/legacy_backend.py` cualquier sitio donde se construya un `SketchSolveResult`. Para cada uno, asegurar que el nuevo campo se pasa por defecto (vacío). Como añadimos un campo opcional con `default_factory=dict`, los call sites existentes seguirán funcionando, pero verifica que no hay un caso donde `SketchSolveResult(success, positions, iterations, max_error, message, constraint_errors, bad_constraints, radius_updates)` se invoque posicionalmente — si lo hay, los positional args quedarían desalineados.

```bash
grep -n "SketchSolveResult(" quino/services/sketch_solving/legacy_backend.py
```

Si encuentras llamadas posicionales con 8 argumentos, conviértelas a keyword args.

- [ ] **Step 4: Traducir UUIDs a mensajes en `solve_sketch()`**

En `quino/application/commands/sketch_commands.py:524-538`, sustituir el método `solve_sketch` por:

```python
    def solve_sketch(self) -> ValidationReport:
        report = ValidationReport()
        result = self._apply_sketch_constraints(set(), strict=True)
        if result.success:
            report.messages.append(ValidationMessage("info", "sketch_solved", "Sketch solved", None))
            return report

        # Translate UUID-based bad_constraints into human descriptions.
        sketch = self._project.sketch
        if sketch is not None and result.bad_constraints:
            for cid in result.bad_constraints:
                constraint = sketch.constraints.get(cid)
                if constraint is None:
                    continue
                detail = result.bad_constraint_details.get(cid, "constraint could not be applied")
                label = constraint.name or constraint.type.value
                report.messages.append(
                    ValidationMessage(
                        "warning",
                        "sketch_constraint_failed",
                        f"{label}: {detail}",
                        None,
                    )
                )
        else:
            report.messages.append(
                ValidationMessage(
                    "warning",
                    "sketch_not_solved",
                    result.message or "Sketch solver did not converge",
                    None,
                )
            )
        return report
```

- [ ] **Step 5: Test de mensajes humanos**

Crear `tests/test_sketch_solve_messages.py`:

```python
"""Tests for human-readable failure messages from solve_sketch()."""
from quino import ApplicationService


def test_failed_constraint_message_includes_constraint_name():
    """An impossible distance constraint surfaces with its name, not a UUID."""
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("0 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    # Impossible: both points fixed at the same place but with distance = 10
    svc.create_sketch_constraint("distance", [p1, p2], value="10 mm", name="my_dist")
    report = svc.solve_sketch()
    messages = [m.message for m in report.messages]
    assert any("my_dist" in m for m in messages), f"Expected 'my_dist' in messages, got: {messages}"
    # And NOT a raw UUID anywhere in the output
    for m in messages:
        # UUIDs in QUINO look like "constraint_<hex>" — not exposed to user
        assert "constraint_" not in m, f"Raw constraint id leaked in message: {m}"


def test_success_message_unchanged():
    """When the sketch solves, the existing 'Sketch solved' message is preserved."""
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("distance", [p1, p2], value="10 mm")
    report = svc.solve_sketch()
    messages = [m.message for m in report.messages]
    assert any("solved" in m.lower() for m in messages), f"Expected 'solved' message, got: {messages}"
```

- [ ] **Step 6: Run**

```bash
pytest tests/test_sketch_solve_messages.py -v
```

Expected: 2 passed.

- [ ] **Step 7: Suite completa**

```bash
pytest tests/ -q
```

Expected: `403 passed, 1 skipped, 1 xfailed`.

- [ ] **Step 8: Commit**

```bash
git add quino/services/sketch_solving/base.py quino/services/sketch_solving/solvespace_backend.py quino/services/sketch_solving/legacy_backend.py quino/application/commands/sketch_commands.py tests/test_sketch_solve_messages.py
git commit -m "feat(sketch): translate bad-constraint UUIDs to human messages in solve_sketch"
```

---

## Task 3: Highlight visual de constraints fallidos en canvas

**Files:**
- Modify: `quino/domain/model.py` (extender `Sketch` con `bad_constraint_ids: list[str]`)
- Modify: `quino/application/commands/sketch_commands.py:980-1028` (persistir bad_ids tras solve)
- Modify: `quino/gui/canvas.py:2863-2880` (color rojo por-constraint)
- Create: `tests/test_sketch_bad_constraint_visual.py`

- [ ] **Step 1: Añadir campo en `Sketch`**

En `quino/domain/model.py`, dentro del dataclass `Sketch` (línea ~321-339 aprox, donde está `solve_error`):

```python
bad_constraint_ids: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Persistir tras solve**

En `quino/application/commands/sketch_commands.py:980-1028`, en `_apply_sketch_constraints`, después de `result = self._solver.solve(...)` y antes de `if result.success:`:

```python
        # Persist bad_constraint_ids regardless of success — empty list on full success.
        project.sketch.bad_constraint_ids = list(result.bad_constraints)
```

(Esto sobrescribe la lista cada vez, lo cual es correcto.)

- [ ] **Step 3: Test de propagación**

Crear `tests/test_sketch_bad_constraint_visual.py`:

```python
"""Tests for bad_constraint_ids propagation from solver to Sketch domain."""
from quino import ApplicationService


def test_bad_constraint_ids_populated_when_solver_fails():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("0 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    bad_id = svc.create_sketch_constraint("distance", [p1, p2], value="10 mm")
    svc.solve_sketch()
    assert bad_id in svc.project.sketch.bad_constraint_ids


def test_bad_constraint_ids_cleared_when_solver_succeeds():
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("distance", [p1, p2], value="10 mm")
    svc.solve_sketch()
    assert svc.project.sketch.bad_constraint_ids == []
```

- [ ] **Step 4: Run**

```bash
pytest tests/test_sketch_bad_constraint_visual.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Color rojo por constraint en canvas**

En `quino/gui/canvas.py:2863-2880`, modificar el inicio de `_draw_sketch_constraints`. Cambiar la línea:

```python
color = QtGui.QColor("#b84840" if invalid else "#7f8c8d")
```

por:

```python
is_bad = constraint.id in (project.sketch.bad_constraint_ids or [])
if is_bad:
    color = QtGui.QColor("#e74c3c")  # solid red for actively bad
elif invalid:
    color = QtGui.QColor("#b84840")  # legacy "whole sketch invalid" rust
else:
    color = QtGui.QColor("#7f8c8d")  # normal grey
```

Lo mismo si la entidad del constraint está seleccionada — preservar el branch `if self._selected_entity_id == constraint.id: color = QtGui.QColor("#c75b12")` DESPUÉS, para que la selección prevalezca sobre el rojo (afordance: el usuario puede seleccionar para editar/borrar).

Resultado: el bloque queda así:

```python
            is_bad = constraint.id in (project.sketch.bad_constraint_ids or [])
            if is_bad:
                color = QtGui.QColor("#e74c3c")
            elif invalid:
                color = QtGui.QColor("#b84840")
            else:
                color = QtGui.QColor("#7f8c8d")
            if self._selected_entity_id == constraint.id:
                color = QtGui.QColor("#c75b12")
            painter.setPen(QtGui.QPen(color, 1.1, QtCore.Qt.PenStyle.DashLine))
```

- [ ] **Step 6: Smoke GUI test**

```bash
pytest tests/test_gui.py -q
```

Expected: GUI tests pass (no regresiones). El cambio es sólo de color, no afecta lógica.

- [ ] **Step 7: Suite completa**

```bash
pytest tests/ -q
```

Expected: `405 passed, 1 skipped, 1 xfailed`.

- [ ] **Step 8: Commit**

```bash
git add quino/domain/model.py quino/application/commands/sketch_commands.py quino/gui/canvas.py tests/test_sketch_bad_constraint_visual.py
git commit -m "feat(sketch): visual highlight of failed constraints in canvas (red)"
```

---

## Task 4: De-duplicar ON_CIRCLE y COINCIDENT+entity

**Files:**
- Modify: `quino/gui/canvas.py` (eliminar `CanvasMode.CREATE_SKETCH_ON_CIRCLE` del dispatcher, dejar sólo COINCIDENT)
- Modify: `quino/gui/main_window.py` (eliminar `action_sketch_on_circle_tool` del toolbar)
- Modify: `quino/application/commands/sketch_commands.py` (auto-convertir ON_CIRCLE → COINCIDENT en `create_sketch_constraint` por si algún proyecto guardado lo tiene)

**Decisión**: COINCIDENT ya cubre point+line, point+circle, point+arc. ON_CIRCLE es redundante. Eliminamos el tool de UI; mantenemos el enum value para compat al cargar proyectos viejos.

- [ ] **Step 1: Localizar todos los lugares que referencian ON_CIRCLE**

```bash
grep -rn "ON_CIRCLE\|on_circle\|action_sketch_on_circle_tool" --include="*.py"
```

Anotar la lista. Sospechosos: `canvas.py` (action + dispatcher), `main_window.py` (toolbar wiring), `sketch_commands.py` (validation), `types.py` (enum), `constraint_mapping.py` (handler).

- [ ] **Step 2: Eliminar el action y su uso en toolbar**

En `quino/gui/canvas.py:506`:

```python
        self.action_sketch_on_circle_tool = self._tool_action(...)
```

Borrar esta línea entera.

En `quino/gui/main_window.py`, buscar `action_sketch_on_circle_tool` y borrar las apariciones (probablemente en `_build_sketch_toolbar`).

- [ ] **Step 3: Eliminar mapeo ON_CIRCLE en `_CONSTRAINT_MODE_TO_TYPE` y tablas afines**

En `quino/gui/canvas.py:169`:

```python
    CanvasMode.CREATE_SKETCH_ON_CIRCLE:     SketchConstraintType.ON_CIRCLE,
```

Borrar esta línea. Lo mismo en `_SKETCH_CONSTRAINT_TYPE_STR` (línea ~219). NO borrar el enum `SketchConstraintType.ON_CIRCLE` ni el handler en `constraint_mapping.py` — pueden seguir cargándose desde proyectos viejos.

- [ ] **Step 4: Eliminar `CanvasMode.CREATE_SKETCH_ON_CIRCLE`**

Si ya no se usa en ningún sitio (verificar con grep), eliminar la entrada del enum/diccionario `CanvasMode` en `canvas.py:148-ish`. Si todavía se referencia desde algún elif en `_handle_constraint_input_click`, ELIMINAR esa rama también.

- [ ] **Step 5: Auto-convertir ON_CIRCLE → COINCIDENT al cargar proyectos viejos**

En `quino/application/commands/sketch_commands.py`, dentro de `create_sketch_constraint`, justo después de validar el tipo (alrededor de línea 360 donde aparece `ON_CIRCLE` en el if), añadir:

```python
        # ON_CIRCLE is deprecated as a separate type; auto-fold into COINCIDENT
        # which already covers point-on-entity semantics.
        if ctype is SketchConstraintType.ON_CIRCLE:
            ctype = SketchConstraintType.COINCIDENT
            constraint_type = SketchConstraintType.COINCIDENT.value
```

(Buscar el nombre exacto de la variable que tiene el `ctype` — puede ser `constraint_enum` o similar. Ajustar.)

- [ ] **Step 6: Verificar UI**

```bash
pytest tests/test_gui.py -q
```

Si algún test referencia el botón eliminado, eliminar la referencia (no skip — fíjate primero que el test no testea algo importante).

- [ ] **Step 7: Suite completa**

```bash
pytest tests/ -q
```

Expected: `405 passed, 1 skipped, 1 xfailed` (los 2 tests añadidos de Task 3 ya están; nada se rompe aquí porque COINCIDENT cubría el caso).

- [ ] **Step 8: Commit**

```bash
git add quino/gui/canvas.py quino/gui/main_window.py quino/application/commands/sketch_commands.py
git commit -m "refactor(sketch/gui): remove redundant ON_CIRCLE tool (COINCIDENT already covers point-on-curve)"
```

---

## Task 5: Atajos de teclado para los 10 tools más usados

**Files:**
- Modify: `quino/gui/canvas.py:486-509` (añadir `setShortcut` a cada action elegido)

Atajos elegidos (siguiendo convenciones CAD):

| Tool | Shortcut |
|---|---|
| Point | `P` |
| Line segment | `L` |
| Circle | `C` |
| Arc | `A` |
| Rectangle | `R` |
| Fix | `F` |
| Coincident | `Shift+C` |
| Distance | `D` |
| Horizontal | `H` |
| Vertical | `V` |
| Parallel | `Shift+P` |
| Perpendicular | `Shift+R` |
| Tangent | `T` |
| Solve sketch | `Ctrl+Return` |

- [ ] **Step 1: Aplicar shortcuts**

En `quino/gui/canvas.py`, después de cada definición `self.action_sketch_X_tool = self._tool_action(...)`, añadir `self.action_sketch_X_tool.setShortcut(QtGui.QKeySequence("..."))`.

Concretamente (insertar justo después de la línea de creación de cada action):

```python
        self.action_sketch_point_tool.setShortcut(QtGui.QKeySequence("P"))
        self.action_sketch_line_tool.setShortcut(QtGui.QKeySequence("L"))
        self.action_sketch_rectangle_tool.setShortcut(QtGui.QKeySequence("R"))
        self.action_sketch_circle_tool.setShortcut(QtGui.QKeySequence("C"))
        self.action_sketch_arc_tool.setShortcut(QtGui.QKeySequence("A"))
        self.action_sketch_fix_tool.setShortcut(QtGui.QKeySequence("F"))
        self.action_sketch_horizontal_tool.setShortcut(QtGui.QKeySequence("H"))
        self.action_sketch_vertical_tool.setShortcut(QtGui.QKeySequence("V"))
        self.action_sketch_distance_tool.setShortcut(QtGui.QKeySequence("D"))
        self.action_sketch_coincident_tool.setShortcut(QtGui.QKeySequence("Shift+C"))
        self.action_sketch_parallel_tool.setShortcut(QtGui.QKeySequence("Shift+P"))
        self.action_sketch_perpendicular_tool.setShortcut(QtGui.QKeySequence("Shift+R"))
        self.action_sketch_tangent_tool.setShortcut(QtGui.QKeySequence("T"))
```

Para solve_sketch, en `quino/gui/main_window.py` donde se define `self.action_solve_sketch`:

```python
        self.action_solve_sketch.setShortcut(QtGui.QKeySequence("Ctrl+Return"))
```

- [ ] **Step 2: Verificar GUI tests**

```bash
pytest tests/test_gui.py -q
```

Expected: pass.

- [ ] **Step 3: Suite completa**

```bash
pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add quino/gui/canvas.py quino/gui/main_window.py
git commit -m "feat(gui): keyboard shortcuts for sketch tools (P/L/C/A/R/F/H/V/D/T/Shift+...)"
```

---

## Task 6: Tests de integración GUI para secuencias de clicks

**Files:**
- Create: `tests/test_sketch_gui_constraint_clicks.py`

Verifica que las secuencias de clicks del usuario producen los constraints correctos. Cobertura mínima: tangent line+circle (regression del bug original), parallel 2 segments, on_curve coincident.

- [ ] **Step 1: Crear test**

```python
"""Integration tests for sketch constraint creation via simulated canvas clicks.

These tests verify that the click sequences a user performs in each constraint
mode produce a correctly-shaped constraint in the domain (and that the solver
then converges).
"""
import pytest

pytest.importorskip("PySide6")  # skip in headless CI without Qt

from quino import ApplicationService
from quino.domain.types import SketchConstraintType


def _make_app() -> ApplicationService:
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    return svc


def test_tangent_line_circle_creates_constraint_with_two_pt_one_ent_refs():
    svc = _make_app()
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    line = svc.create_sketch_line_segment(p1, p2, "L")
    center = svc.create_sketch_point("5 mm", "8 mm", "C")
    circle = svc.create_sketch_circle(center, "3 mm", "Circ")

    cid = svc.create_sketch_constraint(
        "tangent", [p1, p2], value="1", entity_references=[circle]
    )
    constraint = svc.project.sketch.constraints[cid]
    assert constraint.type is SketchConstraintType.TANGENT
    assert constraint.references == [p1, p2]
    assert constraint.entity_references == [circle]


def test_tangent_circle_circle_creates_constraint_with_zero_pt_two_ent_refs():
    svc = _make_app()
    c1 = svc.create_sketch_point("0 mm", "0 mm", "C1")
    c2 = svc.create_sketch_point("20 mm", "0 mm", "C2")
    circ1 = svc.create_sketch_circle(c1, "5 mm", "Circ1")
    circ2 = svc.create_sketch_circle(c2, "3 mm", "Circ2")

    cid = svc.create_sketch_constraint(
        "tangent", [], value="1", entity_references=[circ1, circ2]
    )
    constraint = svc.project.sketch.constraints[cid]
    assert constraint.type is SketchConstraintType.TANGENT
    assert constraint.references == []
    assert constraint.entity_references == [circ1, circ2]


def test_parallel_two_segments_creates_constraint_with_four_pt_refs():
    svc = _make_app()
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    p3 = svc.create_sketch_point("0 mm", "5 mm", "P3")
    p4 = svc.create_sketch_point("10 mm", "8 mm", "P4")
    cid = svc.create_sketch_constraint("parallel", [p1, p2, p3, p4])
    constraint = svc.project.sketch.constraints[cid]
    assert constraint.type is SketchConstraintType.PARALLEL
    assert constraint.references == [p1, p2, p3, p4]


def test_coincident_point_circle_creates_point_on_curve_constraint():
    """COINCIDENT now covers point-on-circle (ON_CIRCLE deprecated in Task 4)."""
    svc = _make_app()
    center = svc.create_sketch_point("0 mm", "0 mm", "C")
    circle = svc.create_sketch_circle(center, "5 mm", "Circ")
    pt = svc.create_sketch_point("3 mm", "3 mm", "PT")
    cid = svc.create_sketch_constraint(
        "coincident", [pt], entity_references=[circle]
    )
    constraint = svc.project.sketch.constraints[cid]
    assert constraint.type is SketchConstraintType.COINCIDENT
    assert constraint.references == [pt]
    assert constraint.entity_references == [circle]


def test_solve_after_tangent_line_circle_succeeds_with_no_bad_constraints():
    """Full integration: create tangent line+circle, solve, verify no bad_constraints."""
    svc = _make_app()
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("10 mm", "0 mm", "P2")
    svc.create_sketch_line_segment(p1, p2, "L")
    center = svc.create_sketch_point("5 mm", "8 mm", "C")
    circle = svc.create_sketch_circle(center, "3 mm", "Circ")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    svc.create_sketch_constraint("fix", [center])
    svc.create_sketch_constraint("tangent", [p1, p2], value="1", entity_references=[circle])
    report = svc.solve_sketch()
    assert svc.project.sketch.bad_constraint_ids == []
    # Report should have a "solved" message
    assert any("solved" in m.message.lower() for m in report.messages)
```

- [ ] **Step 2: Run**

```bash
pytest tests/test_sketch_gui_constraint_clicks.py -v
```

Expected: 5 passed.

- [ ] **Step 3: Full suite**

```bash
pytest tests/ -q
```

Expected: `410 passed, 1 skipped, 1 xfailed`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_sketch_gui_constraint_clicks.py
git commit -m "test(sketch): integration tests for constraint creation reference shapes"
```

---

## Task 7: Cosméticos (toolbar separators + cleanup tangent dialog)

**Files:**
- Modify: `quino/gui/main_window.py` (separator entre geometría y constraints en sketch toolbar)
- Modify: `quino/gui/canvas.py:4633-4641` (no preguntar External/Internal cuando es line+curve)

- [ ] **Step 1: Toolbar separator**

Localizar `_build_sketch_toolbar` (en `main_window.py`). Después del último botón de geometría (probablemente `action_sketch_arc_tool` o `action_sketch_infinite_line_tool`), añadir:

```python
        self._sketch_toolbar.addSeparator()
```

- [ ] **Step 2: Eliminar diálogo tangent external/internal cuando aplica a line+curve**

En `quino/gui/canvas.py:4633-4641`, sustituir el bloque:

```python
        elif self._mode == CanvasMode.CREATE_SKETCH_TANGENT:
            items = ["External (+1)", "Internal (-1)"]
            item, ok = QtWidgets.QInputDialog.getItem(...)
            ...
            value_str = "1" if item == items[0] else "-1"
```

por:

```python
        elif self._mode == CanvasMode.CREATE_SKETCH_TANGENT:
            # The External/Internal distinction only matters for curve-curve tangency.
            # For line+curve (2 point refs + 1 entity ref) the sign has no meaning.
            if not point_ids:
                # curve-curve case
                items = ["External (+1)", "Internal (-1)"]
                item, ok = QtWidgets.QInputDialog.getItem(
                    self, "Tangent Constraint", "Tangency type:", items, 0, False
                )
                if not ok:
                    self.set_mode(CanvasMode.SELECT)
                    return
                value_str = "1" if item == items[0] else "-1"
            else:
                # line+curve case — no dialog
                value_str = "1"
```

- [ ] **Step 3: Run**

```bash
pytest tests/ -q
```

Expected: still passing.

- [ ] **Step 4: Smoke GUI (manual, opcional)**

`python -m quino.gui` y verificar:
- Toolbar de sketch tiene un separador visual entre geometría y constraints.
- Crear tangent line+circle no abre diálogo.
- Crear tangent circle+circle SÍ abre diálogo External/Internal.

- [ ] **Step 5: Commit**

```bash
git add quino/gui/main_window.py quino/gui/canvas.py
git commit -m "refactor(sketch/gui): toolbar separator + skip external/internal dialog for line+curve tangent"
```

---

## Verificación final de la fase

- [ ] **Step 1: Suite completa**

```bash
pytest tests/ -q
```

Expected: `410+ passed, 1 skipped, 1 xfailed` (398 baseline + ~12 nuevos a lo largo de las 7 tasks; el conteo exacto depende del orden de ejecución).

- [ ] **Step 2: Smoke manual del bug original**

`python -m quino.gui`:
1. Crear nuevo proyecto, modo Sketch.
2. Dibujar una recta.
3. Dibujar un círculo.
4. Click en tool "Tangent" (o pulsar `T`).
5. Click en la recta, click en el círculo.
6. Pulsar `Ctrl+Return` (Solve Sketch).
7. **Verificar**: la recta queda tangente al círculo. No hay mensaje de error en la barra de estado.

- [ ] **Step 3: Smoke del path roto antes (overconstrained)**

`python -m quino.gui`:
1. Crear dos puntos.
2. Fijarlos a (0,0) y (5,0).
3. Aplicar constraint Distance entre ellos con valor "10 mm".
4. Solve Sketch.
5. **Verificar**: el constraint Distance se dibuja en rojo. La barra de estado dice algo legible como `"distance: ..."` o el nombre del constraint, NO un UUID.

---

## Self-Review

**Spec coverage** (referencia: auditoría 2026-05-19):
- Crítico 1 (TANGENT silencioso) → Task 1 (re-implementación) + Task 7 (eliminar diálogo confuso).
- Crítico 2 (mensajes ininteligibles) → Task 2.
- Crítico 3 (sin indicador visual) → Task 3.
- Mayor 4 (COINCIDENT vs ON_CIRCLE) → Task 4.
- Mayor 5 (sin atajos) → Task 5.
- Mayor 6 (refactor de `_handle_constraint_input_click`) → **OUT OF SCOPE**, requiere plan propio.
- Menor 7 (CONCENTRIC persiste como COINCIDENT) → **OUT OF SCOPE**, cosmético; podría incluirse en Task 7 si el reviewer lo pide.
- Menor 8 (toolbar sin agrupación) → Task 7.
- Menor 9 (sin tests de clicks GUI) → Task 6.
- Menor 10 (CONCENTRIC asume `point_ids[0]`) → **OUT OF SCOPE**, defensive coding.
- Architectural 11-13 → **OUT OF SCOPE**.

**Placeholder scan**: revisado, sin "TBD"/"TODO"/"implement later".

**Type consistency**:
- `SketchSolveResult.bad_constraint_details: dict[str, str]` — usado consistentemente en Task 2.
- `Sketch.bad_constraint_ids: list[str]` — añadido en Task 3 y consumido por canvas.
- `CanvasMode.CREATE_SKETCH_ON_CIRCLE` — eliminado en Task 4; el enum `SketchConstraintType.ON_CIRCLE` se conserva para compat al cargar proyectos antiguos.
- Las firmas de `_emit_tangent` y `_curve_center_and_radius` (helper local) coherentes en Task 1.

**Riesgos identificados**:
- Task 1 step 5 introduce un helper local `_curve_center_and_radius` con una rama para arcs que evalúa expresiones — podría fallar si los puntos del arco son no-literales. Mitigación: el bloque está dentro de `try/except (ValueError, TypeError)` del bucle de emisión, así que un fallo se convierte en bad_constraint con mensaje. No bloquea.
- Task 4 step 5 (auto-convertir ON_CIRCLE → COINCIDENT) podría romper proyectos guardados que asuman que ON_CIRCLE sigue siendo válido. Mitigación: el enum sigue existiendo; sólo se cambia la conversión al crearse desde UI. JSON load preserva el tipo, pero el handler ON_CIRCLE en `constraint_mapping.py` sigue trabajando.
