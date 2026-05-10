# Next Development Plan After Stabilization

Este plan define los siguientes pasos de desarrollo de QUINO una vez ejecutado el pulido descrito en `docs/Implementation_review_plan.md`.

El objetivo no es acelerar a toda costa, sino consolidar una aplicacion fiable, extensible y agradable de usar. Cada fase debe cerrar con tests, revision manual de workflow y documentacion minima antes de avanzar.

## 1. Principios de avance

- Priorizar estabilidad sobre amplitud funcional.
- Mantener el enfoque `library-first`: toda funcionalidad importante debe vivir en la API antes que en la GUI.
- Evitar grandes redisenos si una mejora incremental resuelve el problema.
- No introducir nuevos subsistemas sin tests de roundtrip JSON, undo/redo y flujo GUI basico.
- Mantener ejemplos oficiales pequenos, claros y reproducibles.
- Separar siempre estado editable del modelo, estado de simulacion y estado visual.

## 2. Hito 1. Cierre de una V1 estable

**Objetivo**

Convertir el estado actual en una V1 tecnicamente fiable: crear, editar, guardar, cargar, simular y reproducir mecanismos sencillos sin errores de workflow.

**Trabajo incluido**

- Ejecutar completo el plan de estabilizacion actual.
- Limpiar llamadas privadas desde GUI hacia `ApplicationService`.
- Asegurar que cada accion de usuario equivale a una operacion atomica de API.
- Revisar severidades de validacion.
- Revisar mensajes de error del solver y del inspector.
- Congelar el formato JSON de V1 con una nota de compatibilidad.

**Criterio de cierre**

- `pytest` verde.
- Four-bar y slider-crank funcionan desde API y GUI.
- La edicion tras simular no corrompe estado.
- Undo/redo es predecible en operaciones principales.
- El usuario entiende por que falla una simulacion cuando falla.

## 3. Hito 2. Calidad de interaccion del canvas

**Objetivo**

Hacer que el canvas sea una herramienta comoda y no solo funcional.

**Trabajo incluido**

- Mejorar seleccion de bodies, bars, sliders, joints, drivers y sketch.
- Mejorar hit-testing en zonas densas.
- Anadir hints contextuales por herramienta.
- Unificar preview visual de creacion.
- Mejorar feedback de snap sin hacerlo visualmente ruidoso.
- Revisar menu contextual para que contenga solo acciones validas para la seleccion.
- Mejorar visualizacion de joints, ground, slider, drivers y restricciones.

**Fuera de alcance**

- Multiseleccion avanzada.
- Edicion tipo CAD completa.
- Constraints cinematicas nuevas.

**Criterio de cierre**

- Crear un mecanismo sencillo no requiere recordar pasos ocultos.
- Cada herramienta comunica claramente que espera del usuario.
- No hay acciones disponibles que fallen por contexto invalido evitable.

## 4. Hito 3. Sketch V1 maduro, pero simple

**Objetivo**

Cerrar Sketch como una capa auxiliar robusta, sin intentar convertirlo todavia en un CAD parametricamente completo.

**Trabajo incluido**

- Cerrar el contrato de constraints soportadas.
- Decidir representacion canonica de arcs.
- Mejorar diagnostico del solver de sketch.
- Evitar degradacion de expresiones parametricas.
- Completar tests de constraints basicas y avanzadas ya existentes.
- Mejorar inspector de sketch con valores evaluados, errores y estado solved/unsolved.

**Fuera de alcance**

- Solver CAD completo.
- Constraints geometricas 3D.
- Dependencia persistente marker-sketch.

**Criterio de cierre**

- El sketch es opcional e independiente.
- Sirve de ayuda fiable para snap.
- Si una constraint no puede resolverse, se explica sin romper el sketch.

## 5. Hito 4. Simulacion V1 robusta y diagnostica

**Objetivo**

Hacer que la simulacion sea suficientemente fiable para mecanismos planos sencillos y que sus fallos sean accionables.

**Trabajo incluido**

- Revisar transformaciones entre coordenadas locales, globales y frames temporales.
- Crear tests visuales/numericos de no desacople de barras y sliders.
- Separar claramente:
  - validacion previa,
  - ensamblado,
  - ejecucion del solver,
  - postproceso,
  - playback.
- Mejorar captura de frames parciales si Exudyn falla.
- Mejorar mensajes: topologia, geometria, singularidad, limite de slider, fallo numerico.
- Documentar limitaciones reales del adapter de Exudyn.

**Fuera de alcance**

- Dinamica avanzada.
- Contactos.
- Flexibilidad.
- Multiples backends visibles en GUI.

**Criterio de cierre**

- El usuario puede distinguir entre “modelo mal definido” y “solver no converge”.
- Si hay frames parciales, se pueden inspeccionar.
- El playback representa movimiento real, no overlays ambiguos.

## 6. Hito 5. Sensores y medidas basicas

**Objetivo**

Convertir los sensores en una funcionalidad practica para analizar mecanismos, sin entrar todavia en postproceso avanzado.

**Trabajo incluido**

- Revisar modelo de sensores y su persistencia.
- Definir sensores V1 oficiales:
  - posicion de marker,
  - distancia entre markers,
  - angulo entre bodies o markers,
  - velocidad derivada si existe timeline suficiente.
- Mostrar resultados en tabla sencilla.
- Permitir exportar resultados a CSV.
- Mantener graficas como visor simple, no como entorno de analisis avanzado.

**Fuera de alcance**

- FFT, filtrado avanzado o informes automaticos.
- Optimizacion de mecanismos.

**Criterio de cierre**

- Un usuario puede simular y obtener medidas utiles sin tocar codigo.
- Los resultados no se guardan como parte permanente del modelo salvo decision explicita.

## 7. Hito 6. Parametrizacion usable

**Objetivo**

Hacer que los parametros sean una herramienta central y segura, no solo una caracteristica tecnica.

**Trabajo incluido**

- Mejorar gestor de parametros.
- Mostrar dependencias entre parametros y propiedades.
- Avisar antes de borrar parametros usados.
- Mejorar deteccion de ciclos.
- Mostrar valor evaluado y unidad convertida.
- Permitir localizar donde se usa un parametro.

**Fuera de alcance**

- Optimizador parametrico.
- Barridos automaticos complejos.

**Criterio de cierre**

- El usuario puede editar parametros sin miedo a romper silenciosamente el modelo.
- Los errores dimensionales son claros.

## 8. Hito 7. Documentacion y ejemplos oficiales

**Objetivo**

Tener una base de documentacion pequena pero mantenible.

**Trabajo incluido**

- README de arranque.
- Guia corta: crear primer mecanismo.
- Guia corta: usar sketch y snap.
- Guia corta: parametros y unidades.
- Guia corta: simular y leer resultados.
- Mantener ejemplos oficiales:
  - four-bar,
  - slider-crank,
  - mecanismo con sketch auxiliar,
  - mecanismo parametrizado sencillo.

**Criterio de cierre**

- Una persona nueva puede abrir la app, seguir una guia y reproducir un ejemplo.
- Los ejemplos son tambien tests o fixtures reutilizables.

## 9. Hito 8. Preparacion para empaquetado

**Objetivo**

Preparar QUINO para distribuirse de forma basica sin convertir el empaquetado en el foco principal.

**Trabajo incluido**

- Revisar comandos de entrada.
- Revisar dependencias opcionales: GUI, Exudyn, tests.
- Definir extras en `pyproject`, si conviene.
- Probar instalacion limpia en entorno virtual.
- Generar smoke tests de arranque GUI.
- Preparar instrucciones de instalacion para Windows.

**Fuera de alcance**

- Instalador profesional.
- Firma de binarios.
- Auto-update.

**Criterio de cierre**

- Se puede instalar y arrancar en una maquina limpia siguiendo pasos claros.

## 10. Orden recomendado

1. Cerrar estabilizacion actual.
2. Cerrar V1 estable.
3. Pulir canvas e interaccion.
4. Madurar sketch.
5. Madurar simulacion.
6. Anadir sensores/medidas basicas.
7. Mejorar parametrizacion.
8. Documentar ejemplos oficiales.
9. Preparar empaquetado basico.

## 11. Regla de decision para nuevas ideas

Antes de aceptar una nueva funcionalidad, debe pasar tres preguntas:

- Puede implementarse sin saltarse la API publica?
- Puede probarse con unit tests o GUI smoke tests razonables?
- Mejora el uso real de mecanismos 2D sencillos sin abrir un rediseño grande?

Si alguna respuesta es no, la idea se aparca hasta que el nucleo afectado este mas maduro.

## 12. Recomendacion practica

Despues del pulido actual, el siguiente paso mas sano es cerrar una V1 estable y muy probada, no ampliar todavia el alcance. QUINO ya tiene muchas piezas potentes; ahora conviene que cada una sea aburridamente fiable antes de crecer.

## 13. Plan tecnico concreto por codigo

Esta seccion baja el roadmap a clases, funciones y archivos concretos. La intencion es que cada bloque pueda convertirse en una PR pequena y revisable.

### 13.1 Estabilizacion de ApplicationService

**Editar**

- `quino/application/service.py`
  - `ApplicationService.move_marker(...)`
  - `ApplicationService._translate_direct_joint_counterparts(...)`
  - `ApplicationService._move_slider_origin(...)`
  - `ApplicationService._rotate_slider(...)`
  - `ApplicationService._set_slider_travel(...)`
  - `ApplicationService._validate_endpoint_input(...)`
  - `ApplicationService._sync_id_service(...)`
  - `ApplicationService.delete_sketch_entity(...)`
  - `ApplicationService.update_sketch_constraint(...)`
  - `ApplicationService._apply_sketch_constraints(...)`

**Crear**

- `ApplicationService.update_slider_geometry(slider_id, origin_x, origin_y, angle, travel_min, travel_max) -> None`
- `ApplicationService.update_parameter_definition(parameter_id, name, expression, unit, description) -> None`
- `ApplicationService.set_sketch_visible(visible: bool) -> None`
- `ApplicationService.update_driver_law(driver_id, expression, unit | None = None) -> None`
- `ApplicationService.get_entity(entity_id: str) -> object`
- `ApplicationService.get_body_by_marker(marker_id: str) -> Body`
- `ApplicationService.evaluate_scalar_as(property: ScalarProperty, unit: str) -> float`

**Cambios esperados**

- El movimiento de markers con juntas debe ser directo, no transitivo.
- La edicion de sliders debe ser atomica.
- La creacion de joints debe rechazar referencias inexistentes.
- El borrado de sketch debe limpiar constraints colgantes.
- La GUI no debe llamar a metodos privados para mutar estado.

**Tests**

- `tests/test_application.py`
  - `test_move_marker_only_moves_direct_joint_counterparts`
  - `test_update_slider_geometry_is_single_undo_step`
  - `test_create_joint_rejects_unknown_marker_body_or_slider`
  - `test_delete_sketch_curve_removes_dependent_constraints`
  - `test_update_parameter_definition_is_atomic`
  - `test_sync_id_service_includes_sensors`

### 13.2 API publica de lectura para la GUI

**Editar**

- `quino/application/service.py`
- `quino/gui/main_window.py`
- `quino/gui/canvas.py`

**Crear**

- Opcionalmente, nuevo modulo `quino/application/queries.py`
  - `EntityLookup`
  - `BodyMarkerLookup`
  - `EvaluatedProperty`

**Cambios esperados**

- Sustituir usos GUI de:
  - `_find_entity(...)`
  - `_find_body(...)`
  - `_find_body_by_marker(...)`
  - `_find_parameter(...)`
  - `_evaluate_scalar_as(...)`
  - `_snapshot()`
- La GUI debe consultar mediante API publica y mutar solo mediante comandos publicos.

**Tests**

- `tests/test_gui.py`
  - Mantener tests existentes.
  - Anadir smoke test de seleccion/inspector sin llamadas privadas si es razonable.

### 13.3 Slider y joints en canvas

**Editar**

- `quino/gui/canvas.py`
  - `MechanismCanvas.mouseReleaseEvent(...)`
  - `MechanismCanvas.mouseMoveEvent(...)`
  - `MechanismCanvas._slider_preview_for_handle(...)`
  - `MechanismCanvas._draw_slider(...)`
  - `MechanismCanvas._draw_joints(...)`
  - `MechanismCanvas._require_editing(...)`

**Crear**

- Si ayuda a simplificar, crear helpers internos:
  - `MechanismCanvas._commit_slider_preview(...)`
  - `MechanismCanvas._clear_drag_state(...)`
  - `MechanismCanvas._draw_joint_symbol(...)`
  - `MechanismCanvas._draw_driver_symbol(...)`

**Cambios esperados**

- El drag de slider debe llamar a `ApplicationService.update_slider_geometry(...)`.
- La visualizacion debe distinguir:
  - rotula,
  - encastre,
  - joint a ground,
  - joint a slider,
  - driver rotacional,
  - driver traslacional.
- El canvas debe cancelar estados intermedios con `Esc` de forma uniforme.

**Tests**

- `tests/test_gui.py`
  - `test_canvas_drag_slider_commits_single_operation`
  - `test_escape_clears_current_tool_state`
  - `test_joint_and_driver_symbols_render_without_crash`

### 13.4 Sketch constraints y solver

**Editar**

- `quino/domain/sketch_constraints.py`
  - `ConstraintSpec`
  - `CONSTRAINT_SPECS`
- `quino/services/sketch_solver.py`
  - `SketchSolver.solve(...)`
  - `SketchSolver._apply_constraint(...)`
  - `SketchSolver._apply_perpendicular(...)`
  - `SketchSolver._apply_on_circle(...)`
  - `SketchSolver._apply_tangent(...)`
- `quino/services/validation.py`
  - `ValidationService._validate_sketch(...)`
  - `ValidationService._validate_sketch_constraint(...)`
- `quino/application/service.py`
  - `ApplicationService.create_sketch_constraint(...)`
  - `ApplicationService._validate_sketch_constraint_references(...)`

**Crear**

- En `quino/domain/sketch_constraints.py`:
  - `SketchConstraintValueKind`
  - Campos nuevos en `ConstraintSpec`: `value_kind`, `allowed_entity_types`
- Opcionalmente:
  - `SketchConstraintDiagnostic`
  - `SketchSolveDiagnostics`

**Cambios esperados**

- `TANGENT` debe usar signo `unitless`, no longitud.
- `entity_references` debe validarse al crear constraints.
- Si una constraint esta mal formada, el solver no debe devolver exito silencioso.
- Decidir soporte real de arcs:
  - O bloquear arcs en constraints de curva con mensaje claro.
  - O implementar calculo de centro/radio para arcs.

**Tests**

- `tests/test_application.py`
  - `test_tangent_constraint_accepts_only_valid_sign`
  - `test_constraint_rejects_wrong_entity_reference_type`
  - `test_solver_reports_invalid_constraint_instead_of_silent_success`
  - `test_arc_curve_constraints_are_supported_or_rejected_explicitly`

### 13.5 Inspector, parametros y edicion segura

**Editar**

- `quino/gui/main_window.py`
  - `MainWindow._apply_property_update(...)`
  - `MainWindow._on_parameter_item_changed(...)`
  - `MainWindow._prepare_for_model_edit(...)`
  - `MainWindow.solve_sketch(...)`
  - `MainWindow._toggle_sketch_visible(...)`
  - `MainWindow._populate_properties(...)`

**Crear**

- `MainWindow._prepare_for_sketch_edit(...)`
- `MainWindow._update_parameter_row(...)`
- `MainWindow._show_property_error(...)`
- Opcionalmente, un helper local:
  - `PropertyEditorBinding`

**Cambios esperados**

- Editar sketch no debe borrar simulacion si no toca el modelo.
- Editar parametros debe ser atomico.
- Booleanos deben seguir editandose con desplegable.
- El inspector debe mostrar valor evaluado y error de dimension cuando aplique.

**Tests**

- `tests/test_gui.py`
  - `test_sketch_edit_does_not_discard_simulation`
  - `test_marker_edit_after_simulation_requires_discard_confirmation`
  - `test_parameter_edit_failure_does_not_leave_partial_rename`
  - `test_boolean_properties_use_combo_box`

### 13.6 Simulacion y Exudyn

**Editar**

- `quino/solver_adapters/exudyn_adapter.py`
  - `ExudynAdapter._create_joint(...)`
  - `ExudynAdapter._collect_final_state(...)`
  - `ExudynAdapter._load_solution_frames(...)`
  - `ExudynAdapter._record_sensor_data(...)`
  - `ExudynAdapter._add_slider_limit_stops(...)`
- `quino/simulation/assembler.py`
  - `MechanismAssembler.assemble(...)`
  - transformaciones body/marker/local/global
- `quino/simulation/runner.py`
  - `SimulationRunner.run(...)`
- `quino/domain/model.py`
  - `SimulationResult`

**Crear**

- Opcionalmente:
  - `quino/simulation/diagnostics.py`
    - `SimulationPhase`
    - `SimulationDiagnostic`
  - `quino/simulation/transforms.py`
    - helpers puros para local/global/frame

**Cambios esperados**

- El adapter no debe mutar el dominio.
- Los frames deben representar cuerpos y markers sin desacople visual.
- Si falla Exudyn, conservar frames parciales si existen.
- Separar mensajes por fase:
  - preflight,
  - assembly,
  - dynamic solve,
  - fallback,
  - postprocess.

**Tests**

- `tests/test_simulation.py`
  - `test_exudyn_adapter_does_not_mutate_joint_endpoints_on_failure`
  - `test_frames_keep_revolute_joint_markers_coincident`
  - `test_slider_marker_stays_on_slider_line_in_frames`
  - `test_partial_frames_are_returned_when_dynamic_solve_terminates`

### 13.7 Sensores y resultados

**Editar**

- `quino/domain/model.py`
  - `Sensor`
  - `SensorOutput`
  - `Project.sensor_outputs`
- `quino/domain/inputs.py`
  - `SensorInput`
- `quino/application/service.py`
  - `ApplicationService.create_sensor(...)`
  - `ApplicationService.delete_entity(...)`
  - `ApplicationService.run_kinematic_simulation(...)`
- `quino/solver_adapters/exudyn_adapter.py`
  - metodos `_record_*_sensor(...)`
- `quino/viewer/dataset.py`
- `quino/viewer/plot_window.py`
- `quino/viewer/exporter.py`

**Crear**

- `ApplicationService.create_sensor_from_input(input: SensorInput) -> str`
- `ApplicationService.clear_simulation_outputs() -> None`
- `ApplicationService.export_sensor_outputs_csv(path: str) -> None`

**Cambios esperados**

- Usar `SensorInput` de forma consistente.
- Decidir si `sensor_outputs` vive solo como runtime o se serializa.
- Permitir exportacion sencilla a CSV.

**Tests**

- `tests/test_application.py`
  - `test_create_sensor_from_input`
  - `test_delete_marker_cascades_sensor_or_reports_dependency`
- `tests/test_simulation.py`
  - `test_sensor_outputs_are_generated_from_frames`
- Nuevo `tests/test_viewer.py`
  - `test_export_sensor_outputs_csv`

### 13.8 JSON y compatibilidad

**Editar**

- `quino/serialization/json_io.py`
  - `JsonMapper.dump(...)`
  - `JsonMapper.load(...)`
  - `_model_to_dict(...)`
  - `_model_from_dict(...)`
  - `_sketch_to_dict(...)`
  - `_sketch_from_dict(...)`
  - helpers de sensors/drivers si procede
- `quino/domain/model.py`
  - `Project.schema_version`

**Crear**

- Si hay cambios incompatibles:
  - `quino/serialization/migrations.py`
  - `JsonMigration`
  - `migrate_project_data(data: dict) -> dict`

**Cambios esperados**

- Mantener carga de proyectos sin sketch.
- Mantener carga de proyectos anteriores.
- Documentar que campos runtime no se guardan, si esa es la decision.

**Tests**

- `tests/test_roundtrip.py`
  - `test_roundtrip_v1_project_with_sketch_constraints_drivers_sensors`
  - `test_load_project_without_sketch_block`
  - `test_load_older_schema_if_migration_exists`

### 13.9 Documentacion y ejemplos

**Editar**

- `quino/application/examples.py`
  - `build_four_bar_example(...)`
  - `build_slider_crank_example(...)`
- `docs/Specification.md`
- `docs/Sketch_spec.md`
- `docs/Viewer_spec_roadmap.md`

**Crear**

- `docs/User_guide_first_mechanism.md`
- `docs/User_guide_sketch_snap.md`
- `docs/User_guide_parameters.md`
- `docs/User_guide_simulation.md`
- Opcionalmente:
  - `quino/application/example_projects.py`

**Cambios esperados**

- Los ejemplos oficiales deben ser pequenos, estables y usables como tests.
- La documentacion debe reflejar el producto real, no aspiracional.

**Tests**

- `tests/test_examples.py`
  - ejemplos cargan,
  - validan,
  - simulan si backend disponible,
  - roundtrip JSON.

## 14. Secuencia de implementacion recomendada a nivel de PR

1. PR pequena: `ApplicationService` invariantes y endpoints.
2. PR pequena: movimiento direct-only de markers con joints.
3. PR pequena: `update_slider_geometry(...)` y canvas usando esa API.
4. PR pequena: eliminar mutacion de joints en `ExudynAdapter`.
5. PR pequena: API publica de consultas para GUI.
6. PR mediana: separar edicion de modelo y sketch en GUI.
7. PR mediana: contrato unico de sketch constraints.
8. PR mediana: diagnostico del sketch solver.
9. PR mediana: robustez frames/simulacion.
10. PR pequena: sensores y CSV basico.
11. PR pequena: documentacion de usuario y ejemplos.

Cada PR deberia dejar `pytest` verde y contener tests de regresion del comportamiento que toca. Si una PR empieza a tocar mas de tres areas grandes, conviene partirla.
