# Workspace sin overlays — rediseño de casos, runs y métricas

**Fecha**: 2026-06-02
**Estado**: Borrador para revisión
**Rama**: `redesign/case-as-model`
**Schema**: `0.3.0` → `0.4.0` (cambio incompatible, sin autoupgrade)
**Reemplaza/ajusta**: `docs/superpowers/specs/2026-05-26-case-as-model-redesign-design.md`
(la base case-as-model se mantiene; se **eliminan los overlays** que aquella spec introducía).

---

## 1. Motivación

El rediseño *case-as-model* ya está implementado: cada `Case` contiene un `Model`
completo y las lecturas son O(1) sin recomposición. Sobre esa base se construyó una
capa de **overlays** (`CaseOverlay` / `EntityOverlay`) que registra, por entidad y
propiedad, si está *linked* o *unlinked* respecto al padre, más un sistema de
*divergence warnings* y un *Divergences dock*.

Esa capa de overlays añade complejidad que no necesitamos: el modelo del hijo ya
contiene todos los valores, así que la decisión de cascadear puede tomarse
**comparando valores directamente** en el momento de la modificación, sin estructura
paralela que mantener sincronizada. El servicio `case_diff.py` ya demuestra que la
comparación directa padre↔hijo por valores funciona y es suficiente para mostrar
diferencias.

Además queremos:

1. **Unificar Run y Analysis** en una sola entidad (1 analysis ⇒ 1 run). El estado de
   ejecución se aplana dentro de `Analysis`.
2. **Conservación de datos en re-run**: si un run previo terminó en `ok` y el nuevo
   acaba en `partial`, avisar y preguntar antes de sobrescribir. Mientras se
   re-ejecuta, los datos buenos previos no se pierden si el nuevo run falla.
3. **Métricas como funciones Python** definidas por el usuario, que cuelgan de un
   analysis y se evalúan sobre los datos de sus sensores.
4. **Correcciones y mejoras de GUI** (combobox sin flecha, expansión de árboles,
   resaltado del caso activo, reestructuración del árbol del workspace).

## 2. Principios de diseño

- **El modelo del caso es la única fuente de verdad.** No hay estructura paralela
  (overlay) que mantener consistente.
- **El cascadeo se decide por comparación de valores en el momento de la edición.**
  Un hijo recibe el cambio del padre **salvo** que ya tuviera un valor distinto
  (override). La base de comparación es el **valor que el padre tenía antes** de la
  edición.
- **Poses, analyses y métricas son locales a cada caso.** Solo el modelo cascadea.
  En el fork se copian como punto de partida y luego son independientes.
- **Sin estado de conflicto persistente.** Las diferencias padre↔hijo se ven bajo
  demanda con el widget de diffs (`case_diff.py`), no como warnings almacenadas.

---

## 3. Modelo de datos

### 3.1 Case (sin overlay)

```python
@dataclass(slots=True)
class Case:
    id: str
    name: str
    description: str = ""
    parent_case_id: str | None = None        # None ⇒ caso raíz
    model: Model = field(default_factory=Model)
    poses: list[Pose] = field(default_factory=list)        # default primero
    analyses: list[Analysis] = field(default_factory=list) # run + métricas embebidos
    sensor_outputs: dict[str, SensorOutput] = field(default_factory=dict)
    reaction_outputs: dict[str, ReactionOutput] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
```

**Eliminados de `Case`**: `overlay`, `runs` (lista), `tolerances`, `metrics`.

### 3.2 Analysis (run aplanado + métricas)

```python
@dataclass(slots=True)
class Analysis:
    id: str
    name: str
    analysis_type: str = "dynamic"           # dynamic|kinematic|static|equilibrium
    pose_id: str | None = None               # pose local = estado inicial
    config: AnalysisConfig = None            # DynamicConfig | Kinematic | Static | Equilibrium
    metrics: list[Metric] = field(default_factory=list)

    # --- estado de ejecución aplanado (antes en Run) ---
    status: str = "to_be_run"                # to_be_run|queued|running|ok|partial|failed|stale
    created_at: str | None = None
    finished_at: str | None = None
    result_ref: ResultRef | None = None
    artifacts: list[ArtifactRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_message: str = ""
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
```

- `config.metrics` (las viejas plantillas `MetricDef`) **desaparece**. `config.plots`
  se mantiene (los plots no entran en este rediseño).
- `Run` deja de existir como dataclass de lista. `ResultRef` y `ArtifactRef` se
  conservan como tipos auxiliares.

### 3.3 Metric (función Python)

```python
@dataclass(slots=True)
class Metric:
    id: str
    name: str
    description: str = ""
    value_type: str = "float"                # float|bool|int|str
    code: str = ""                           # cuerpo de eval(data, meta), debe hacer return
    result: MetricResult | None = None

@dataclass(slots=True)
class MetricResult:
    value: Any                               # float/bool/int/str
    status: str                              # "ok" | "error" | "no_data"
    error: str = ""
    evaluated_at: str | None = None
```

### 3.4 Pose (sin cambios estructurales)

`Pose` se mantiene como en `domain/workspace.py`. Reglas:

- Cada caso tiene siempre una pose **default** (`is_default=True`), no editable ni
  borrable. No almacena `body_poses`: **refleja el modelo** en su configuración de
  referencia (se resuelve con `create_reference_pose`). Editar el modelo actualiza la
  default automáticamente porque no guarda estado propio.
- Las poses no-default son editables y sirven de estado inicial para los analyses que
  cuelgan de ellas.

### 3.5 Workspace

`Workspace` se mantiene salvo por la limpieza derivada: sigue conteniendo
`cases: dict[str, Case]`, `root_case_ids`, estado compartido (sketch, parameters,
view_state, gravity_default) y selección (`selected_case_id`, `selected_pose_id`,
`selected_analysis_id`).

### 3.6 Entidades eliminadas del dominio

`CaseOverlay`, `EntityOverlay`, `Run` (entidad de lista), `MetricDefinition`,
`Tolerance`, y el viejo `MetricDef` como contenido de los configs de análisis.

---

## 4. Motor de cascadeo sin overlays

`quino/services/case_cascading.py` se reescribe. Todas las mutaciones de modelo pasan
por el motor. La decisión de cascadear se toma comparando el **valor actual del hijo**
contra el **valor anterior del padre** (`old_value`), capturado antes de mutar.

### 4.1 `edit_property(case_id, entity_id, prop, new_value)`

1. `old_value = get(entity, prop)` en el caso editado, **antes** de mutar.
2. Aplicar `new_value` en el caso editado.
3. Para cada descendiente `H` (recursivo, hijos directos primero):
   - Si `H` no tiene la entidad → parar esa rama.
   - `child_value = get(H_entity, prop)`.
   - Si `child_value == old_value` → el hijo seguía al padre: aplicar `new_value` en
     `H` y **recursar** a sus hijos con el mismo `old_value`.
   - Si `child_value != old_value` → override propio del hijo: **no tocar** y **no
     recursar** (ese override es el techo del cascadeo en esa rama).

### 4.2 `add_entity(case_id, entity, domain)`

1. Añadir la entidad al modelo del caso.
2. Cascadear a descendientes: si el descendiente **no** tiene esa id y sus
   dependencias están presentes, clonar y añadir; si ya la tiene, parar esa rama.

La creación **siempre** se cascadea (salvo colisión de id local en el hijo).

### 4.3 `remove_entity(case_id, entity_id)`

1. Calcular cierre de dependientes (joints, drivers, loads, sensors, springs que
   referencian la entidad o sus markers) y eliminarlos en el caso.
2. Cascadear: en cada descendiente donde la entidad sea **value-idéntica** a la del
   padre (sin diferencias en ninguna propiedad) → eliminar también (con su cierre);
   si el hijo tenía override sobre ella → conservarla en el hijo (pasa a ser entidad
   local) y parar esa rama.

La eliminación **siempre** se cascadea salvo override.

### 4.4 Conexiones del grafo de bloques

`add_connection` / `remove_connection` siguen la misma filosofía por **existencia** de
la conexión (clave 4-tupla `src_instance, src_port, dst_instance, dst_port`) en el
modelo del hijo: se cascadea salvo que el hijo ya difiera (conexión ausente cuando se
añade, o presente como local cuando se elimina).

### 4.5 `fork_case(parent_case_id, name) -> new_case_id`

1. Nuevo `Case` con `parent_case_id = parent`.
2. `model` ← copia profunda del padre (ids preservados: son la base del cascadeo).
3. `poses` ← copia profunda (ids de pose regenerados; la default se mantiene como
   default).
4. `analyses` ← copia profunda con ids regenerados, **sin** estado de run
   (`status="to_be_run"`, sin artifacts/result), métricas copiadas con `result=None`.
5. `sensor_outputs` / `reaction_outputs` vacíos.

Tras fork el hijo es estructuralmente idéntico al padre. La GUI fija
`selected_case_id` al hijo.

### 4.6 `duplicate_case` / `reparent_case`

- `duplicate_case`: como el actual pero sin overlay; regenera ids de pose/analysis.
- `reparent_case`: disponible internamente (no expuesto en GUI v1). Al cambiar de
  padre no hay overlay que reconstruir; el modelo del caso no cambia, solo su
  `parent_case_id`. Marca el caso y descendientes como stale.

### 4.7 Resultado del motor

`OperationResult` reporta `modified_case_ids` y `stale_case_ids` (para invalidar el
estado de run de los analyses afectados vía `mark_runs_stale_for_case`, adaptado a
`Analysis`). **No** hay `conflicts` persistentes ni `divergence_warnings`.

### 4.8 Igualdad de valores y propiedades excluidas

- Igualdad por `==` de dataclass (`ScalarProperty`, `Expression`, primitivos, dicts de
  `metadata.values`, `Style`, endpoints, `CoMAnchor`). Para `Expression`/`ScalarProperty`
  el `==` compara la expresión string, que es lo correcto.
- Propiedades de **identidad / topología** excluidas del cascadeo de propiedades:
  `id`, `Body.markers`, `Body.edge_order` (los markers cascadean como entidades
  propias). Se reutiliza la lista `_SKIP_FIELDS` de `case_diff.py` como única fuente de
  verdad (extraída a un módulo común si hace falta).

### 4.9 Limitación conocida

Sin overlay no se distingue "override deliberado con valor casualmente igual al del
padre" de "valor heredado sin tocar". Si un hijo tiene el mismo valor que el padre y
el padre cambia, el hijo recibe el cambio. Es predecible y aceptable; coincide con la
limitación ya documentada para `rebuild_overlay` en la spec anterior.

---

## 5. Ejecución unificada (run en analysis)

`quino/services/run_executor.py` se adapta para operar sobre `Analysis` en vez de
crear `Run` en `case.runs`.

### 5.1 Ciclo

1. **Lanzar**: capturar `prev = snapshot(analysis)` (status, result_ref, artifacts,
   finished_at, métricas) en memoria. `analysis.status = "running"` **conservando** los
   artifacts previos referenciados (no se borran).
2. **Buffer temporal**: el runner escribe en `artifacts/<analysis_id>/_staging/`, no
   sobre los datos buenos.
3. **Al terminar**:
   - `failed` o cancelado → descartar staging; restaurar `prev`. Si no había datos
     previos, status `failed` / `to_be_run`.
   - `ok` → **promoción atómica**: el staging reemplaza los artifacts buenos (rename
     de directorio), se actualiza `result_ref` y `status="ok"`, se borran los viejos.
   - `partial`:
     - si `prev.status == "ok"` → **warning + prompt**: "el nuevo resultado es parcial
       y el anterior era OK; ¿sobrescribir?". Aceptar → promociona; rechazar →
       descarta staging, conserva el OK previo.
     - en otro caso → promociona directo.

El prompt OK→Partial **bloquea la promoción** hasta la decisión del usuario. El
executor emite una señal con el resultado pendiente; `MainWindow` pregunta y confirma o
descarta. Mientras, los datos buenos previos permanecen intactos.

### 5.2 Evaluación de métricas

`quino/services/metric_evaluator.py` (nuevo):

- `evaluate(metric, data, meta) -> MetricResult`.
- `data`: dict `{"<sensor_name>.<channel>": np.ndarray, ..., "t": np.ndarray}`
  construido desde los `sensor_outputs` del analysis terminado. Clave por **nombre de
  sensor + canal** (como en los ejemplos del usuario). Renombrar un sensor invalida las
  métricas que lo referencian → la GUI avisa al renombrar.
- `meta`: dict con metadata del analysis (`dt`, `t_final`, `analysis_type`, `steps`…).
- **Exec restringido**: el código del usuario es el cuerpo de
  `def evaluate(data, meta): <code>`. Se ejecuta con `__builtins__` reducido (sin
  `import`, `open`, `eval`, dunders), exponiendo `np` y helpers. Excepciones capturadas;
  timeout por watchdog (thread). El resultado se castea/valida contra `value_type`;
  fallo de cast → `status="error"`.
- `evaluate_all(analysis)`: recorre `analysis.metrics` y rellena `metric.result`.

**Cuándo**: automáticamente al terminar un run en `ok`/`partial` (tras promoción). Sin
datos OK/Partial → `result.status="no_data"`. Botón **Recalcular** en GUI para
reevaluar sin re-runear.

### 5.3 Invalidación

Cuando el cascadeo marca un analysis como `stale`, sus métricas conservan el último
`result` pero el analysis se muestra desactualizado. Al re-runear se recalculan.

---

## 6. Serialización 0.4.0

- `schema_version` → `"0.4.0"`. `JsonMapper.load()` lanza `UnsupportedSchemaError`
  para `< 0.4.0` con mensaje claro. Sin autoupgrade.
- **Quitar**: `Run` como lista, `CaseOverlay`/`EntityOverlay`, `Case.overlay`/`runs`/
  `tolerances`/`metrics`, `MetricDef` en configs.
- **Añadir**: campos de run aplanados en `Analysis`; `Analysis.metrics: list[Metric]`
  con `MetricResult`.
- `Metric.code` como string multilínea; `result` como objeto (`value`, `status`,
  `error`, `evaluated_at`). `value` se serializa según su tipo primitivo.
- **Regenerar** `examples/*.quino.json` con los scripts `build_*`; escribir los que
  falten.

---

## 7. GUI

### 7.1 Árbol del workspace (`workflow_tree_panel.py`)

- **Quitar el grupo "Poses"**: la pose default y las poses cuelgan directamente del
  nodo del caso.
- **Grupo "Subcases" con icono de carpeta.**
- **Run ya no es nodo independiente**: el estado del run se muestra en el propio nodo
  del analysis (badge de estado ok/partial/failed/stale con icono de color). Sin nodos
  hijos de "run".
- **Resaltado del caso activo**: al activar, el nodo se **expande** y se pinta fondo
  **azul claro** en sus poses, analyses y su estado — **excluyendo subcasos**. El nodo
  del caso mantiene su pill azul oscuro.
- **Eliminar** los badges de overlay (`★`) y de divergencias (`⚠ N`).

### 7.2 Comportamiento de árboles (global)

En `apply_browser_tree_style` (afecta a **todos** los árboles):

- Expandir/contraer **solo con el triángulo**: `setExpandsOnDoubleClick(False)` +
  interceptar el toggle por clic en la fila (no expandir al hacer clic/doble clic sobre
  el contenido).

### 7.3 Theme — combobox

- `QComboBox::down-arrow { image: url(<chevron-down>); }` en `theme.py` para que
  **todos** los desplegables muestren la flecha. Auditar diálogos que pisen el theme
  con `setStyleSheet` local y unificarlos.

### 7.4 Ventana editor de métricas (`metric_editor_dialog.py`, reescrito)

- Campos: nombre, descripción, tipo (combo float/bool/int/str), editor de **código**
  (cuerpo de `eval(data, meta)` con `return`).
- Panel lateral de **canales disponibles** (`data['sensor.x']`, `data['t']`,
  `meta['dt']`, `meta['t_final']`…) clicables para insertar.
- Botón **Probar**: evalúa contra el último run del analysis y muestra resultado o
  error.
- `metrics_manager_dialog.py`: lista `analysis.metrics` (columnas nombre/tipo/
  resultado), add/edit/delete, botón **Recalcular todas**.

### 7.5 Eliminar el Divergences dock

Quitar el dock y referencias a overlay en `main_window.py`, canvas y paneles. El widget
"Compare with parent" (`case_diff`) se mantiene para ver diferencias bajo demanda.

### 7.6 Adaptación de paneles

`run_status_widget`, `report_panel`, `run_comparison_dialog`, `plot_window` y
`viewer/dataset` pasan a leer estado/artifacts desde `Analysis` en vez de `Run`.

---

## 8. Auditoría QA end-to-end

Fase explícita del plan: smoke-test del flujo completo de workspace y tests de
regresión por cada bug detectado.

Flujo a auditar:

1. Crear workspace → caso raíz con pose default.
2. Fork → editar modelo en padre → verificar cascadeo a hijo y override respetado.
3. Añadir poses no-default, analyses bajo poses, métricas Python.
4. Runear: casos `ok`, `partial`, `failed`; verificar conservación de datos previos y
   prompt OK→Partial.
5. Evaluación automática de métricas + recalcular.
6. Guardar → recargar (round-trip 0.4.0) → re-runear.
7. Selección de caso/pose/analysis persistente y consistente con el canvas.

---

## 9. Orden de ejecución (Opción A — por capas)

1. **Dominio + motor de cascadeo** sin overlays. Reescribir `Workspace`/`Case`/
   `Analysis`/`Metric`; borrar `CaseOverlay`/`EntityOverlay`/`case_overlay_validator`/
   `cascade_property_registry`; reescribir `case_cascading.py`. Tests unitarios del
   motor.
2. **Ejecución + métricas**: run aplanado en analysis, buffer temporal + promoción
   atómica + prompt OK→Partial, `metric_evaluator.py` (exec restringido), auto-eval.
3. **Serialización 0.4.0** + regeneración de ejemplos.
4. **GUI**: árbol, combobox, expansión, resaltado activo, editor de métricas, quitar
   Divergences dock, adaptar paneles.
5. **Auditoría QA** end-to-end + tests de regresión.

Cada paso entrega tests verdes antes del siguiente.

---

## 10. Qué se elimina (resumen)

| Objetivo | Acción |
|---|---|
| `quino/services/case_overlay_validator.py` | Eliminar (`_entity_lookup` se reubica) |
| `quino/services/cascade_property_registry.py` | Eliminar |
| `CaseOverlay`, `EntityOverlay`, `Case.overlay` | Eliminar |
| `Run` (entidad de lista), `Case.runs` | Eliminar (estado aplanado en `Analysis`) |
| `Case.tolerances`, `Case.metrics`, `MetricDefinition`, `Tolerance` | Eliminar |
| `MetricDef` en `config.metrics` | Eliminar (sustituido por `Analysis.metrics`) |
| Divergence warnings + Divergences dock | Eliminar |
| Badges overlay (`★`) y divergencias (`⚠ N`) en el árbol | Eliminar |

## 11. Qué se crea

| Objetivo | Propósito |
|---|---|
| `Metric`, `MetricResult` (dominio) | Métricas Python por analysis |
| `quino/services/metric_evaluator.py` | Evaluación con exec restringido |
| Buffer temporal + promoción atómica en `run_executor.py` | Conservación de datos en re-run |
| Editor de métricas reescrito | Ventana de código + canales + Probar |

## 12. Fuera de alcance

- Refactor de `canvas.py` y `main_window.py` más allá de lo que el rediseño exige.
- Plots (se mantienen como están).
- Sketch solver (Solvespace) y Exudyn intactos.
- Sandbox real de métricas (subproceso/aislamiento fuerte): el exec restringido en
  proceso es suficiente para una app de escritorio local monousuario.
- Reparenting y root-cloning en la GUI.

## 13. Criterios de aceptación

1. Todos los `examples/*.quino.json` abren, renderizan y runean a schema `0.4.0`.
2. Fork + editar propiedades en padre e hijo → cascadeo correcto y override respetado,
   sin overlays en el código.
3. `CaseOverlay`/`EntityOverlay`/`case_overlay_validator.py`/`cascade_property_registry.py`
   eliminados del codebase.
4. Un analysis tiene como mucho un estado de run; re-run con `partial` sobre `ok`
   dispara el prompt; un run fallido no destruye los datos previos buenos.
5. Métricas Python: crear, probar, evaluar al runear y recalcular funcionan
   end-to-end por la GUI.
6. GUI: todos los combobox muestran flecha; árboles expanden solo con el triángulo;
   caso activo se expande y resalta sus poses/analyses (no subcasos).
7. Todos los tests pasan; los tests de overlay eliminados se retiran limpiamente.
