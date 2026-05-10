# Independent Implementation Review Plan

Este documento es una revision independiente del estado actual de QUINO. No usa ni modifica `docs/Revision_findings.md`.

## 1. Alcance revisado

Se ha revisado el flujo de uso esperado y la implementacion actual de:

- Generacion y edicion de sketch.
- Restricciones y solver de sketch.
- Generacion y edicion del modelo cinematico/dinamico.
- Canvas, inspector, arbol, toolbar y flujo de seleccion.
- Simulacion, resultados temporales y adapter de Exudyn.
- Serializacion JSON, validacion, undo/redo y servicios de aplicacion.

La conclusion general es buena: QUINO ya tiene una base amplia y bastante funcional. El principal riesgo no es que falten piezas grandes, sino que varias acciones de usuario se resuelven con mutaciones parciales, llamadas privadas y reglas duplicadas. Eso explica bugs de workflow como elementos que se mueven de mas, simulaciones invalidadas en momentos no esperados, undo/redo demasiado granular o fallos del solver dificiles de diagnosticar.

## 2. Prioridad Alta

### 2.1 Movimiento de markers con juntas asociadas

**Problema detectado**

`ApplicationService.move_marker(...)` acaba llamando a `_translate_direct_joint_counterparts(...)`, pero esta funcion hace una busqueda BFS sobre toda la red de juntas. Aunque el nombre dice `direct`, el comportamiento real es transitivo: puede mover markers y sliders conectados a traves de otros joints.

Referencia: `quino/application/service.py:747`, `quino/application/service.py:1489`.

**Riesgo**

Esto contradice el workflow definido: al mover un marker solo deben moverse el marker seleccionado y los elementos directamente enlazados por sus juntas inmediatas. No deben propagarse desplazamientos por toda la cadena salvo que exista una herramienta explicita para mover un subconjunto conectado.

**Modificacion propuesta**

- Cambiar `_translate_direct_joint_counterparts(...)` para que sea realmente directa.
- Si un marker tiene varias juntas directas, mover todos sus contrapuntos directos.
- No recorrer juntas de los contrapuntos.
- Mantener el movimiento de slider/ground asociado a esa junta directa.
- Anadir tests con cadena `A-B-C` donde mover `B` mueve `A` y `C` solo si ambos estan directamente unidos a `B`, pero mover `A` no arrastra `C` a traves de `B`.
- Decidir si `ground` debe seguir siendo implicito o si conviene crear una entidad/anchor visual de ground para que la junta tenga una posicion propia editable.

### 2.2 Edicion de sliders no atomica

**Problema detectado**

Al arrastrar un slider desde el canvas se hacen cinco llamadas seguidas a `update_property(...)`: `origin_x`, `origin_y`, `angle`, `travel_min`, `travel_max`.

Referencia: `quino/gui/canvas.py:906`.

**Riesgo**

Una sola accion del usuario produce varias entradas de undo, varias validaciones y varias propagaciones de markers enlazados. Esto puede dejar estados intermedios incoherentes y explica parte de los errores al editar mecanismos con joints asociados a sliders.

**Modificacion propuesta**

- Crear una operacion atomica en `ApplicationService`, por ejemplo `update_slider_geometry(...)`.
- Aplicar origen, angulo y carrera dentro de una unica operacion con un unico snapshot.
- Propagar markers conectados una sola vez usando la transformacion completa del slider.
- Cambiar el canvas para llamar a esa API en lugar de encadenar `update_property(...)`.
- Anadir test de undo: un drag de slider debe deshacerse con un solo `undo()`.

### 2.3 GUI demasiado acoplada a metodos privados

**Problema detectado**

La GUI usa metodos privados de `ApplicationService` como `_find_entity`, `_find_body`, `_find_body_by_marker`, `_evaluate_scalar_as`, `_snapshot`, y tambien accede/muta directamente partes del dominio.

Referencias: `quino/gui/main_window.py:1722`, `quino/gui/canvas.py:906`, `quino/gui/canvas.py:3006`.

**Riesgo**

Esto rompe el enfoque `library-first`: la GUI puede saltarse invariantes de la API, crear snapshots manuales, invalidar simulaciones aunque no haga falta o modificar estado sin pasar por comandos claros.

**Modificacion propuesta**

- Crear una capa publica de consultas de solo lectura: `get_entity`, `get_body_by_marker`, `evaluate_property_as`, `list_entities`, etc.
- Crear APIs publicas para mutaciones que hoy hace la GUI directamente: `set_sketch_visible(...)`, `update_driver_law(...)`, `update_slider_geometry(...)`.
- Prohibir que la GUI llame a `_snapshot()` o cambie campos del dominio directamente.
- Mantener los metodos privados solo como detalle interno de `ApplicationService`.

### 2.4 ExudynAdapter muta joints del dominio

**Problema detectado**

`ExudynAdapter._create_joint(...)` invierte endpoints asignando sobre el propio objeto `joint` cuando recibe `ground-marker` o `slider-marker`.

Referencia: `quino/solver_adapters/exudyn_adapter.py:231`, `quino/solver_adapters/exudyn_adapter.py:244`.

**Riesgo**

El adapter de solver no deberia mutar el dominio. Si hay una excepcion entre el swap y la restauracion, el proyecto queda corrupto. Aunque no falle, es una fuente de bugs dificil de rastrear.

**Modificacion propuesta**

- Reemplazar el swap destructivo por variables locales o una copia temporal.
- Anadir test que fuerce una excepcion durante la creacion de una junta invertida y verifique que el `Project` no cambia.

### 2.5 Creacion de joints valida forma, pero no existencia real

**Problema detectado**

`create_joint(...)` comprueba que el endpoint tenga campos obligatorios, pero no verifica que `body_id`, `marker_id` y `slider_id` existan ni que el marker pertenezca al body indicado.

Referencia: `quino/application/service.py:646`, `quino/application/service.py:1419`.

**Riesgo**

La API programatica puede crear mecanismos con referencias rotas. La validacion lo avisa despues, pero la capa de aplicacion deberia impedir estados imposibles cuando se usan operaciones publicas.

**Modificacion propuesta**

- En `_validate_endpoint_input(...)`, resolver la referencia real.
- Para marker endpoint, comprobar body existente, marker existente y pertenencia marker-body.
- Para slider endpoint, comprobar slider existente.
- Mantener la validacion informativa como red de seguridad para archivos cargados o datos externos.

## 3. Prioridad Media

### 3.1 Restricciones de sketch: contrato disperso e inconsistente

**Problema detectado**

Existe `CONSTRAINT_SPECS`, pero parte de la logica sigue duplicada en canvas, servicios y solver. Ademas, `TANGENT` esta declarada con `Dimension.LENGTH`, mientras que la aplicacion la usa como signo `unitless`.

Referencias: `quino/domain/sketch_constraints.py:16`, `quino/domain/sketch_constraints.py:30`, `quino/application/service.py:340`, `quino/gui/canvas.py:112`.

**Riesgo**

Al anadir o corregir restricciones, es facil que toolbar, validacion, inspector y solver se desalineen. El caso `TANGENT` ya muestra una divergencia real.

**Modificacion propuesta**

- Extender `ConstraintSpec` con `value_kind`, por ejemplo `none`, `length`, `angle`, `sign`.
- Hacer que canvas, dialogs, validacion, inspector y solver lean el mismo spec.
- Corregir `TANGENT` para que use `sign`/`unitless`.
- Validar que el signo de tangencia sea solo `+1` o `-1`.

### 3.2 Borrado en cascada de sketch incompleto para constraints

**Problema detectado**

Al borrar un `SketchPoint`, se borran entidades dependientes, pero las constraints se filtran principalmente por referencias directas al punto. Constraints que referencien una entidad eliminada mediante `entity_references` pueden quedar colgando. Al borrar directamente una curva, tambien pueden quedar constraints que la referencian.

Referencia: `quino/application/service.py:480`.

**Riesgo**

El sketch puede quedar con constraints invisiblemente rotas, lo que afecta al solver y a la validacion.

**Modificacion propuesta**

- Calcular `deleted_entity_ids` para cualquier borrado.
- Eliminar constraints si contienen cualquier id borrado en `references` o `entity_references`.
- Anadir tests para borrar circle/arc/line usado por `on_circle`, `tangent` o `concentric`.

### 3.3 Solver de sketch modifica expresiones de usuario

**Problema detectado**

Cuando el solver mueve un punto con expresion no literal, `_apply_sketch_constraints(...)` sustituye la expresion por una version con offset: `(<expr>) +/- delta mm`.

Referencia: `quino/application/service.py:1354`.

**Riesgo**

Las expresiones pueden acumular offsets anidados y perder legibilidad. Tambien mezcla dos conceptos distintos: definicion parametricamente editable y resultado calculado por el solver.

**Modificacion propuesta**

- Para V1, elegir una politica clara:
  - O bloquear solve sobre puntos con expresiones no literales salvo que sean driving/locked.
  - O guardar posicion resuelta separada de la expresion original.
  - O normalizar offsets para no anidarlos.
- Mostrar en inspector cuando una coordenada fue ajustada por el solver.
- Anadir tests donde una constraint afecta a un punto definido como `L/2`.

### 3.4 Arc tiene dos modelos conceptuales

**Problema detectado**

`SketchArc` se define como tres puntos, pero tambien tiene `arc_center_mode`. La GUI permite `Arc` por tres puntos y `Arc (center)`. Algunas constraints tratan arcs como curvas, pero `on_circle`/`tangent` realmente solo funcionan con entidades que tienen `center_point_id` y `radius`, es decir, circles.

Referencias: `quino/domain/model.py:195`, `quino/services/sketch_solver.py:491`, `quino/services/sketch_solver.py:526`.

**Riesgo**

El usuario puede esperar que un arc funcione como curva para tangencia o punto sobre circulo, pero la implementacion lo ignora o devuelve error cero silencioso.

**Modificacion propuesta**

- Definir una representacion canonica de arc.
- O bien limitar constraints de curva a `SketchCircle` por ahora y bloquear arcs con mensaje claro.
- O bien calcular centro/radio del arc en el solver y soportarlo de verdad.
- Ajustar inspector y serializacion segun la decision.

### 3.5 Edicion de parametros no atomica

**Problema detectado**

Al editar una fila de parametros, la GUI llama primero a `rename_entity(...)` y luego a `update_parameter(...)`.

Referencia: `quino/gui/main_window.py:1664`.

**Riesgo**

Si el rename funciona y el update falla, queda una edicion parcial. Tambien genera multiples snapshots para una sola accion conceptual.

**Modificacion propuesta**

- Crear `update_parameter_definition(parameter_id, name, expression, unit, description)` atomico.
- Validar todo antes de mutar.
- Hacer un unico snapshot.
- Reutilizarlo desde GUI e API.

### 3.6 Edicion de sketch invalida simulaciones aunque no afecte al modelo

**Problema detectado**

`_apply_property_update(...)`, `solve_sketch(...)` y otras acciones pasan por `_prepare_for_model_edit(...)`, que descarta la simulacion si existe.

Referencias: `quino/gui/main_window.py:895`, `quino/gui/main_window.py:1664`.

**Riesgo**

Segun la especificacion, el sketch es independiente del modelo cinematico y modificarlo no debe alterar markers, bodies, joints ni sliders. Por tanto, no siempre deberia eliminar la simulacion.

**Modificacion propuesta**

- Separar guardas: `_prepare_for_model_edit(...)` y `_prepare_for_sketch_edit(...)`.
- Mantener bloqueo de edicion fuera de `t=0` si se decide como politica global de UI, pero no borrar simulacion por cambios de sketch que no afectan al modelo.
- Si se edita un marker usando snap al sketch, eso si es edicion del modelo y debe invalidar la simulacion.

### 3.7 IdService no sincroniza sensores

**Problema detectado**

`_sync_id_service(...)` observa parametros, sketch, bodies, markers, sliders, joints y drivers, pero no sensores.

Referencia: `quino/application/service.py:1449`.

**Riesgo**

Despues de cargar un proyecto con sensores, crear un sensor nuevo puede reutilizar un id existente.

**Modificacion propuesta**

- Incluir `project.model.sensors` en `_sync_id_service(...)`.
- Anadir test de load/create sensor sin colision.

## 4. Prioridad Baja

### 4.1 `new_project(...)` no reinicia contadores de ids

**Problema detectado**

El servicio mantiene el mismo `IdService` al crear proyectos nuevos.

Referencia: `quino/application/service.py:66`.

**Riesgo**

No rompe funcionalidad, pero resulta poco limpio: un proyecto nuevo puede empezar en `proj_004`, `body_017`, etc. dentro de la misma sesion.

**Modificacion propuesta**

- Reiniciar `IdService` en `new_project(...)`, salvo que queramos ids globales por sesion.
- Documentar la decision.

### 4.2 Validacion usa casi todo como warning

**Problema detectado**

`ValidationReport.has_errors` existe, pero muchas situaciones estructuralmente invalidas se reportan como warning.

Referencia: `quino/domain/model.py:288`, `quino/services/validation.py:44`.

**Riesgo**

La UI no puede distinguir bien entre informacion, advertencia recuperable y error que impide resolver.

**Modificacion propuesta**

- Definir severidades: `info`, `warning`, `error`.
- Usar `error` para referencias rotas, ids inexistentes y geometria imposible.
- Mantener el solver no bloqueante, pero mostrar claramente que el modelo no esta listo.

### 4.3 Edicion de `style.*` demasiado permisiva

**Problema detectado**

`update_property(...)` y `update_sketch_entity(...)` aceptan rutas `style.*` usando `setattr` sin validar campo ni tipo.

Referencias: `quino/application/service.py:435`, `quino/application/service.py:824`.

**Riesgo**

Se pueden introducir atributos no previstos o tipos incorrectos en `Style`.

**Modificacion propuesta**

- Crear lista blanca de campos editables de `Style`.
- Convertir tipos segun campo.
- Rechazar rutas desconocidas.

### 4.4 Unidad/dimension de inercia poco cerrada

**Problema detectado**

`inertia` se valida como `Dimension.INERTIA`, pero el set de unidades publico no incluye una unidad fisica de inercia.

Referencia: `quino/application/service.py:1128`.

**Riesgo**

Editar inercia desde inspector/API puede ser confuso o fallar segun expresion usada.

**Modificacion propuesta**

- O definir una unidad inicial para inercia, por ejemplo `kg*mm^2`/`kg*m^2`.
- O tratar inercia como magnitud simplificada `unitless` en V1 y documentarlo.

### 4.5 Feedback visual incompleto en modos avanzados de sketch

**Problema detectado**

La toolbar incluye constraints avanzadas, pero el feedback de preview/snap parece mas completo para entidades basicas y constraints simples que para todas las avanzadas.

Referencias: `quino/gui/main_window.py:347`, `quino/gui/canvas.py:809`.

**Riesgo**

El usuario puede activar una herramienta que funciona, pero no entender que debe clicar o que referencia falta.

**Modificacion propuesta**

- Centralizar hint/estado por `ConstraintSpec`.
- Mostrar contador de referencias: `2/4 points`, `1/1 curve`, etc.
- Usar cursor o overlay ligero por modo.

## 5. Plan de actualizacion propuesto

### Fase 1. Estabilizar invariantes y mutaciones atomicas

- Corregir movimiento de markers con joints a direct-only.
- Anadir `update_slider_geometry(...)`.
- Validar existencia real de endpoints al crear joints.
- Eliminar mutacion de joints dentro de `ExudynAdapter`.
- Corregir `_sync_id_service(...)` para sensores.
- Crear tests de regresion para cada caso.

### Fase 2. Separar API publica de detalles internos

- Crear metodos publicos de consulta para la GUI.
- Crear `set_sketch_visible(...)`, `update_parameter_definition(...)`, `update_driver_law(...)`.
- Eliminar llamadas GUI a `_snapshot()` y mutaciones directas del dominio.
- Separar guardas de edicion de modelo y sketch.

### Fase 3. Cerrar contrato de constraints de sketch

- Ampliar `ConstraintSpec` para cubrir tipo de valor y entidades permitidas.
- Corregir `TANGENT`.
- Validar `entity_references` en creacion, no solo en validacion posterior.
- Corregir borrado en cascada de constraints.
- Decidir soporte real de arcs en constraints de curva.

### Fase 4. Mejorar robustez del solver de sketch

- Evitar que el solver degrade expresiones parametricas con offsets acumulativos.
- Devolver diagnostico mas claro: convergencia, residual maximo, constraints conflictivas.
- No devolver exito silencioso cuando una constraint esta mal formada.
- Anadir tests de no convergencia y conflictos.

### Fase 5. Pulido de workflow GUI

- Unificar reset/cancelacion de herramientas con `Esc`.
- Mejorar feedback de herramientas avanzadas.
- Asegurar que una accion de usuario equivale a un unico undo siempre que sea conceptual.
- Optimizar seleccion en arbol con mapa `entity_id -> item` si el proyecto crece.

### Fase 6. Simulacion y diagnostico

- Mantener resultados parciales cuando Exudyn falla.
- Revisar transformacion frame -> posicion global con tests de no desacople de barras y slider.
- Separar estado runtime de sensores/simulacion del proyecto persistente o documentar claramente que es estado transitorio.
- Mejorar severidad de validacion para que el panel indique si el fallo es topologico, geometrico o del solver.

## 6. Tests de aceptacion recomendados

- Mover marker con joint directo a marker: ambos quedan coincidentes y no se mueve un tercer marker conectado transitivamente.
- Mover marker con joint a slider: el marker y el slider/joint directo quedan coherentes sin arrastrar elementos no directos.
- Arrastrar slider completo: un solo undo revierte origen, angulo, carrera y markers directos.
- Crear joint con ids inexistentes falla antes de mutar el proyecto.
- ExudynAdapter no cambia endpoints aunque falle el ensamblado.
- Borrar circle/arc/line con constraints elimina tambien constraints dependientes.
- Editar parametro con nombre valido y expresion invalida no deja rename parcial.
- Editar sketch no borra simulacion salvo que se edite el modelo usando snap.
- `TANGENT` acepta solo signo valido y se serializa/carga coherentemente.
- Cargar proyecto con sensores y crear otro sensor no produce ids duplicados.

## 7. Recomendacion final

Antes de anadir mas funcionalidad, conviene ejecutar las fases 1 a 3. Son correcciones pequenas o medianas, pero cambian la estabilidad percibida de toda la app. En especial, la combinacion de movimiento direct-only, operaciones atomicas de slider y eliminacion de mutaciones privadas desde GUI deberia reducir mucho los errores que aparecen despues de simular o al editar mecanismos con juntas.
