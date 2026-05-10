# Revisión de la implementación actual — Sketch + Modelo + Simulación

Documento de hallazgos sobre el estado actual (rama `sketch-foundation`).
**Sin nuevas funcionalidades.** Sólo errores reales, defectos de diseño y
mejoras simples de usabilidad.

Cada punto incluye: *qué pasa hoy*, *por qué es problema*, y *cómo se debería
modificar*.

---

## 1. Críticos — corregir antes que cualquier otra cosa

### 1.1. `_apply_perpendicular` está duplicado en `sketch_solver.py`

- **Hoy:** [sketch_solver.py:251-288](../quino/services/sketch_solver.py#L251-L288)
  define una primera versión, y [sketch_solver.py:679-707](../quino/services/sketch_solver.py#L679-L707)
  define otra distinta. La segunda gana por orden de definición de clase, así
  que la primera (más cuidada — proyecta sobre el normal y reescala) es código
  muerto. La que se ejecuta usa `error = abs(math.cos(delta))` pero rota
  basándose en `correction = delta − target` con un cálculo de `target` que no
  cubre los cuatro signos posibles correctamente.
- **Por qué es problema:** la restricción `perpendicular` puede no converger o
  converger al cuadrante equivocado, y el código de la versión "buena" induce a
  pensar que sí funciona.
- **Cómo cambiarlo:**
  1. Borrar la segunda definición (líneas 679-707).
  2. Dejar como única la implementación basada en proyección (la primera).
  3. Añadir test en `tests/test_sketch_solver.py` con dos segmentos a 30° / 95° /
     150° / 200° y verificar `|dot/(|d1||d2|)| < tol` tras solver.

### 1.2. `update_sketch_constraint("driving", …)` no respeta el contrato

- **Hoy:** [service.py:368-373](../quino/application/service.py#L368-L373)
  acepta `kind == "boolean"` para `driving`, pero el inspector emite
  `PropertyValueInput` con `kind="boolean"` y la validación cruzada con
  `value: …` está en otro nodo. El path `value` exige que `constraint.type ∈
  {DISTANCE, ANGLE}`, lo cual está bien, pero al final del método **no se
  valida** que un constraint NO `DISTANCE`/`ANGLE` reciba `driving`. El campo
  `driving` queda guardado en restricciones donde no tiene semántica.
- **Por qué es problema:** estado guardado que ningún solver mira; confunde al
  usuario y crece como ruido en el JSON.
- **Cómo cambiarlo:** en el handler de `property_path == "driving"` rechazar
  con `ValueError` si `constraint.type` no es `DISTANCE` ni `ANGLE`, o
  bien eliminar el flag del modelo si no se usa en ningún sitio.
  > Comprobar primero con `grep` que `driving` se lea en algún sitio aparte de
  > la persistencia. Si no se lee, **borrarlo** del dominio (más simple).

### 1.3. `_apply_sketch_constraints` machaca expresiones del usuario

- **Hoy:** [service.py:1338-1341](../quino/application/service.py#L1338-L1341)
  tras solver, sustituye `point.x` y `point.y` por
  `ScalarProperty(self._mm_expression(x), "mm", LENGTH)`, es decir un literal
  numérico.
- **Por qué es problema:** si el usuario escribió en el inspector
  `x = a + 5 mm` con `a` un parámetro, **mover otro punto y disparar el solver
  borra esa expresión** y la reemplaza por un número. El sistema de parámetros
  queda inutilizable en cuanto haya restricciones.
- **Cómo cambiarlo:**
  - Sólo escribir literal cuando el solver realmente movió ese punto.
  - Mejor: reemplazar `point.x.expression` únicamente si el delta supera la
    tolerancia, **y** sólo cuando el punto no es destino de ninguna referencia
    paramétrica detectable (heurística mínima: la expresión es ya un literal
    `<num> mm` o `<num>`).
  - Si la expresión contiene un identificador (parámetro), preservarla y dejar
    el desplazamiento como `(<expr>) + dx mm` igual que ya se hace en
    `_offset_expression` ([service.py:1657-1661](../quino/application/service.py#L1657-L1661)).

### 1.4. Snapshots de `_snapshot()` se hacen demasiado tarde

- **Hoy:** Varios métodos validan **después** de llamar `_snapshot()` y otros
  validan antes. Ejemplos:
  - [service.py:155-170 `create_sketch_point`](../quino/application/service.py#L155-L170): valida → snapshot → append. ✔️ correcto.
  - [service.py:184-205 `create_sketch_line_segment`](../quino/application/service.py#L184-L205): valida → snapshot → append. ✔️
  - [service.py:257-282 `create_sketch_arc_by_center`](../quino/application/service.py#L257-L282):
    `snapshot()` se hace **antes** de crear los 3 puntos vía
    `create_sketch_point`, que a su vez vuelve a hacer `snapshot()`. Cada
    operación hace **4 snapshots** y `undo` deja un estado intermedio extraño
    (arco creado pero falta el último punto).
- **Por qué es problema:** `undo` se vuelve impredecible para el usuario:
  un solo "deshacer" puede revertir solo media operación.
- **Cómo cambiarlo:** introducir un context manager
  `with self._operation():` que abra UN snapshot al entrar y que las llamadas
  internas (`create_sketch_point`, etc.) detecten que están dentro de una
  operación y no añadan más snapshots. Aplicarlo a:
  - `create_sketch_arc_by_center`
  - `create_body` (que llama `_make_marker`/`_make_com_marker` y luego
    `append`)
  - `move_marker` cuando arrastra joints encadenados.

### 1.5. `_snapshot()` después de validación condicional en
`update_sketch_entity`

- **Hoy:** [service.py:418-476](../quino/application/service.py#L418-L476):
  algunos paths llaman `_snapshot()` y luego pueden lanzar `ValueError` (por
  ejemplo `Circle.radius` con valor cero). El undo stack queda contaminado con
  un estado idéntico y `redo` deja de funcionar lógicamente.
- **Cómo cambiarlo:** mover `_snapshot()` siempre **después** de que toda la
  validación haya pasado.

---

## 2. Importantes — defectos de diseño/extensibilidad

### 2.1. Duplicación del mapa de aridades de constraint

- **Hoy:** la tabla "constraint → nº de puntos / nº de entidades" aparece en:
  - [service.py:1253-1280 `_validate_sketch_constraint_references`](../quino/application/service.py#L1253-L1280)
  - [validation.py:212-249 `_validate_sketch_constraint`](../quino/services/validation.py#L212-L249)
  - [sketch_solver.py:96-149 `_apply_constraint`](../quino/services/sketch_solver.py#L96-L149)
    (chequea `len(refs) == N` inline en cada rama).
  - canvas.py — según el sub-informe, hay un `_CONSTRAINT_SPEC` con la misma
    información hardcoded.
- **Por qué es problema:** añadir una restricción nueva exige tocar 4 sitios y
  los tres se desincronizan en silencio (ya pasa con `driving` y entity refs).
- **Cómo cambiarlo:** centralizar en un único módulo
  `quino/domain/sketch_constraints.py`:
  ```python
  @dataclass(frozen=True)
  class ConstraintSpec:
      points: int
      entities: int
      value_dim: Dimension | None
      label: str

  CONSTRAINT_SPECS: dict[SketchConstraintType, ConstraintSpec] = { … }
  ```
  Importar desde `validation.py`, `service.py`, `sketch_solver.py` y
  `canvas.py`.

### 2.2. `_apply_constraint` (solver) — cadena de `if-elif`

- **Hoy:** [sketch_solver.py:84-150](../quino/services/sketch_solver.py#L84-L150)
  encadena 14 `if t is X and len(refs) == N`. Cada rama mezcla conversión de
  unidades, validación de refs y dispatch.
- **Cómo cambiarlo:** registry de handlers por tipo:
  ```python
  self._handlers: dict[SketchConstraintType, Callable[..., float]] = {
      SketchConstraintType.COINCIDENT: self._apply_coincident,
      …
  }
  ```
  El método `_apply_constraint` queda en una línea (`return
  self._handlers[t](…)`) y la validación de aridad se hace **una vez** desde
  el spec central de 2.1.

### 2.3. `update_property` y `update_sketch_entity` — dispatcher en cadena

- **Hoy:** [service.py:775-855](../quino/application/service.py#L775-L855)
  y [service.py:418-476](../quino/application/service.py#L418-L476) son
  dispatchers gigantes basados en `isinstance(entity, X) and property_path ==
  Y`. Cada vez que se añade un campo nuevo (ej.: el nuevo `arc_center_mode`)
  hay que recordar que pase por aquí.
- **Cómo cambiarlo:** tabla declarativa por tipo de entidad:
  ```python
  _PROPERTY_HANDLERS: dict[type, dict[str, PropertyHandler]] = {
      Marker: {"x": _update_marker_x, "y": _update_marker_y, …},
      Slider: {…},
      SketchPoint: {…},
      …
  }
  ```
  Sin lógica condicional dispersa: si la clave no existe → error claro
  `Unsupported property "{path}" on {type.__name__}`.

### 2.4. El método dual `arc_center_mode`

- **Hoy:** [model.py:185-198 `SketchArc`](../quino/domain/model.py#L185-L198)
  acepta `arc_center_mode: bool`. Pero ningún método del solver, validation o
  serialización GUI actúa diferente según ese flag. El comentario del spec dice
  *"Arc = 3 puntos"* siempre.
- **Por qué es problema:** dos representaciones para el mismo objeto sin
  contrato de cuál es la "verdadera". Si el usuario edita `point_a_id` de un
  arco creado por centro, se pierde la semántica.
- **Cómo cambiarlo:** elegir UNA representación canónica:
  - Opción A (recomendada, ya está implícita): los 3 puntos siempre son
    `[a, b, c]` del arco; eliminar `arc_center_mode`. Si el usuario crea por
    centro, calcular los 3 puntos del arco y dejarlos como tales.
  - Opción B: si se mantiene el modo, validar que con `arc_center_mode=True`
    los nombres en el dominio sean `center_id`, `start_id`, `end_id` y
    propagarlo al solver / GUI.
  > Vista la implementación actual de `create_sketch_arc_by_center`, opción A
  > es la que menos tocaría.

### 2.5. `delete_sketch_entity` no rompe restricciones rotas

- **Hoy:** [service.py:478-514](../quino/application/service.py#L478-L514)
  borra punto + entidades dependientes + restricciones que referencian el
  punto. Pero **no** borra restricciones cuyas `entity_references` apuntan a
  un círculo/arco que se acaba de borrar.
- **Cómo cambiarlo:** al borrar `SketchCircle` o `SketchArc`, recorrer
  `sketch.constraints` y eliminar las que tengan `entity.id` en
  `entity_references`. Test: crear circle + on_circle, borrar circle, listar
  constraints → debe estar vacío.

### 2.6. `_validate_sketch` en `validation.py` — expresión confusa

- **Hoy:** [validation.py:150-153](../quino/services/validation.py#L150-L153):
  ```python
  if isinstance(entity, SketchLineSegment | SketchInfiniteLine):
      if entity.start_point_id == entity.end_point_id if isinstance(...) else entity.point_a_id == entity.point_b_id:
  ```
  El operador ternario **dentro** de un `if` se evalúa
  `(entity.start_point_id == entity.end_point_id) if isinstance(...) else
  (entity.point_a_id == entity.point_b_id)` — es legible solo de milagro y se
  duplica más abajo (líneas 167-171 vuelven a comprobarlo para infinite
  lines).
- **Cómo cambiarlo:** dos `if` separados, uno por tipo, eliminando la
  comprobación duplicada del bloque `_validate_point_refs`.

### 2.7. `_find_entity` recorre todo cuatro veces

- **Hoy:** [service.py:1069-1095](../quino/application/service.py#L1069-L1095)
  hace un barrido O(N+M+K) por proyecto cada vez que se accede a una entidad
  por id. El inspector lo llama por cada keystroke.
- **Cómo cambiarlo:** mantener un índice `dict[str, object]` invalidado por
  `_snapshot()` y mutaciones explícitas. No afecta a la API pública.

### 2.8. `validate_model` corre el solver de sketch dos veces

- **Hoy:** [service.py:945-952](../quino/application/service.py#L945-L952)
  valida → llama `_validate_sketch_solve` → este hace `solve(deepcopy(project))`.
  Pero ya antes, `update_sketch_entity` y `move_sketch_point` han llamado
  `_apply_sketch_constraints({…})` que también ejecuta el solver. Cada edición
  + simulación hace 2-3 solves del mismo sketch.
- **Cómo cambiarlo:** cachear el último resultado de solver con la firma
  `(hash(sketch.entities), hash(sketch.constraints))` y reutilizar mientras no
  cambie nada. Invalidar en `_snapshot()`.

### 2.9. `JsonMapper` — campos opcionales no documentados

- **Hoy:** `Sketch.solve_error` está en el dominio
  ([model.py:236](../quino/domain/model.py#L236)) pero **no** se persiste
  ([json_io.py:304-315](../quino/serialization/json_io.py#L304-L315)). Si el
  usuario guarda un sketch con error de solver y vuelve a abrir, el banner
  rojo desaparece — silencio engañoso.
- **Cómo cambiarlo:** o bien marcar `solve_error` como puramente runtime y
  resetearlo a `None` al cargar (documentarlo en el dataclass), o bien
  persistirlo. Recomendado: **runtime-only**, recalcularlo en `load_project`
  llamando `_apply_sketch_constraints(set())`.

### 2.10. `Sensor.type` accedido como `.type` y como `.sensor_type`

- **Hoy:** [inputs.py:42](../quino/domain/inputs.py#L42) define `SensorInput`
  con campo `sensor_type` pero el modelo usa `Sensor.type`
  ([model.py:131](../quino/domain/model.py#L131)).
  En `create_sensor` ([service.py:2298-2311](../quino/application/service.py#L2298-L2311))
  se usa string suelto, no el dataclass `SensorInput`.
  Resultado: `SensorInput` está definido pero **no se usa** en ningún sitio
  del flujo nuevo.
- **Cómo cambiarlo:** o consumir `SensorInput` en `create_sensor`
  consistente con el resto de inputs (`MarkerInput`, etc.), o eliminarlo del
  dominio.

---

## 3. Pulido — usabilidad y limpieza

### 3.1. GUI: limpieza de estado de herramienta duplicada

`canvas.set_mode()` y `keyPressEvent(Escape)` limpian (casi) los mismos
~15 atributos en dos lugares. Extraer un método `_reset_tool_state()` que
ambos llamen. Cualquier campo nuevo de tool entrará en un único sitio.

### 3.2. GUI: cursor no cambia con el modo

El canvas no llama `setCursor()` en ningún momento. En modo crear-punto,
crear-línea, mover-marker, restricción, debería cambiar a `CrossCursor`,
`OpenHandCursor`, etc. Una sola tabla `_CURSOR_BY_MODE` resuelve esto.

### 3.3. GUI: snap visual presente en algunos modos sí, otros no

En `mouseMoveEvent` (canvas), `_snap_preview_world` solo se calcula en
modos `CREATE_SKETCH_HORIZONTAL`, `…VERTICAL`, etc., pero no en
`CREATE_SKETCH_POINT` ni `CREATE_SKETCH_CIRCLE`. El snap **funciona**
funcionalmente al hacer click, pero el usuario no ve el indicador hasta que
suelta. Unificar la lista de modos que muestran preview.

### 3.4. GUI: cancelación silenciosa al cambiar tool

Si el usuario está a medio constraint (1/2 clicks) y cambia de herramienta
desde la toolbar, el estado se limpia pero no hay feedback. Mostrar un
mensaje de barra de estado *"Constraint cancelado: cambio de herramienta"* o
similar.

### 3.5. GUI: árbol — búsqueda de item por entity id es O(n)

`main_window._select_entity_by_id` recorre todo el árbol con `findItems` por
cada selección. Mantener `dict[str, QTreeWidgetItem]` actualizado en los
mismos puntos donde se pueblan los items.

### 3.6. `IdService.observe` no detecta colisiones

Si se cargan dos proyectos seguidos, los contadores siguen creciendo. La
función [ids.py:12-18](../quino/services/ids.py#L12-L18) hace `max(...)` pero
el state persiste en el `ApplicationService`. En `new_project()` se debería
**resetear** el `id_service` (`self.id_service = IdService()`).

### 3.7. `expressions.py` accede a un atributo privado

[expressions.py:62](../quino/services/expressions.py#L62)
itera `self.unit_service._UNITS` directamente. Exponer un método público
`UnitService.known_units() -> Iterable[str]`.

### 3.8. `_make_com_marker` con expresiones como string concatenado

[service.py:1010-1025](../quino/application/service.py#L1010-L1025) construye
expresiones como `(x1+x2+x3)/3`. Si los markers tienen unidades distintas
(`mm` y `m`), el parser falla en silencio en una validación posterior. Hoy
todos los markers son mm, así que funciona, pero está pendiente: convertir a
mm explícitamente o calcular el valor numérico y emitir literal `<n> mm`.

### 3.9. Tests faltantes en sub-áreas críticas

- No hay tests dedicados a `sketch_solver.py` (sólo a través de la API).
  Añadir `tests/test_sketch_solver.py` con casos por restricción.
- No hay test que verifique que `undo` tras `create_sketch_arc_by_center`
  deja el sketch tal y como estaba antes (relacionado con 1.4).
- No hay test que verifique persistencia ↔ deserialización de
  `SketchConstraint.entity_references` y `arc_center_mode`.

### 3.10. Documentación menor

- `docs/Sketch_spec.md` tiene secciones numeradas como `## 17`, `## 18`,
  `## 19`, `## 20` antes que `## 17. Puntos a decidir contigo` (al final).
  Reordenar.
- `Spec_part003md` (sin `.`) debería ser `Spec_part003.md`.

---

## Orden recomendado de ataque

1. **1.1** (5 min, cambio mecánico).
2. **1.3** (riesgo alto: rompe expresiones de usuario).
3. **1.4 + 1.5** (snapshots) — junto a un context manager `_operation()`.
4. **2.1** (centralizar specs) — desbloquea 2.2 y 2.3.
5. **2.2** (registry de handlers de solver).
6. **2.5** (cascade delete de constraints en entity refs).
7. **3.1 + 3.2 + 3.3 + 3.4** (paquete pequeño de UX en canvas, una sesión).
8. **2.7 + 2.8** (caches), sólo si hay perf observable.
9. **2.4** (decisión sobre `arc_center_mode`).
10. **2.6, 2.9, 2.10** y resto del **3.x**.

Cada paso es independiente y puede entrar como PR separado.
