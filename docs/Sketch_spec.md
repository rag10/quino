# Sketch Specification

## 1. Objetivo

El `Sketch` sera una capa opcional del proyecto que servira como andamio geometrico para construir el modelo mecanico en `t=0`.

No sustituye al modelo mecanico. Lo complementa.

## 2. Rol dentro de QUINO

- El `Sketch` convivira con el modelo dentro del mismo proyecto.
- El usuario podra trabajar con proyecto que tengan:
  - solo modelo
  - solo sketch
  - sketch + modelo
- El `Sketch` servira para:
  - definir geometria base
  - acotar relaciones geometricas
  - apoyar el posicionamiento inicial del modelo
- Las restricciones del `Sketch` solo aplicaran a la configuracion de diseno en `t=0`.
- Durante la simulacion cinematica, el solver del modelo no seguira las restricciones del sketch salvo que se traduzcan explicitamente a entidades del modelo.

## 3. Principios

- Debe seguir el enfoque `library-first`.
- Debe ser serializable a JSON.
- Debe ser opcional.
- Debe convivir con el canvas actual sin romper el flujo del modelo.
- Debe poder existir con o sin solver de sketch.

## 4. Alcance propuesto por fases

### Fase S1. Fundacion

- estructura de dominio de sketch
- persistencia JSON
- capa visual basica en canvas
- seleccion y edicion basica

### Fase S2. Geometria editable manual

- creacion de `Point`
- creacion de `LineSegment`
- creacion de `Circle`
- creacion de `Arc`
- creacion de `InfiniteLine`
- mover puntos
- editar coordenadas y propiedades desde inspector
- snap visual basico al modelo
- snap interno basico entre entidades del sketch
- flujo de creacion interactivo por clics sucesivos
- finalizacion y cancelacion consistentes con `Enter` y `Esc`

### Fase S3. Restricciones basicas

Incluida en la implementacion actual con un primer solver numerico local.

Restricciones soportadas en este primer corte:

- `fix`
- `horizontal`
- `vertical`
- `distance`
- `coincident`

### Fase S4. Integracion con modelo

- snap de markers del modelo a entidades del sketch en `t=0`
- herramientas para crear entidades del modelo a partir del sketch
- visibilidad atenuada sketch/model

### Fase S5. Restricciones y resolucion

- solver de sketch
- restricciones geometricas
- restricciones dimensionales
- otras restricciones segun prioridad

## 5. Decision de arranque pendiente

La primera decision importante ya queda cerrada.

Alcance geometrico inicial acordado:

- `Point`
- `LineSegment`
- `Circle`
- `Arc`
- `InfiniteLine`

## 6. Comportamiento con y sin solver de sketch

### Sin solver de sketch

- el usuario podra crear entidades geometricas
- el usuario podra moverlas manualmente
- el usuario podra editar sus propiedades numericas
- no se permitira crear restricciones resolubles automaticamente
- al mover entidades del sketch solo se modificara el sketch
- el sketch no movera ni actualizara automaticamente markers, bodies, joints ni sliders del modelo mecanico

### Con solver de sketch

- el usuario podra anadir restricciones geometricas y dimensionales
- el sistema intentara resolver el sketch
- el sketch pasara a tener grados de libertad geometricos controlados
- en el estado actual se resuelven restricciones basicas entre `SketchPoint`

## 7. Entidades conceptuales iniciales

### Sketch

Contenedor raiz del subsistema sketch.

Propiedades minimas propuestas:

- `id`
- `name`
- `entities`
- `constraints`
- `metadata`
- `style`
- `visible`

Regla acordada:

- el `Sketch` siempre sera opcional desde el punto de vista del usuario
- las entidades de sketch tendran nombres autogenerados por tipo, editables por el usuario
- en la primera fase habra un unico `Sketch` por proyecto

### SketchPoint

Propiedades minimas propuestas:

- `id`
- `name`
- `visible`
- `construction`
- `x`
- `y`
- `fixed`
- `style`
- `metadata`

### SketchLineSegment

Propiedades minimas propuestas:

- `id`
- `name`
- `visible`
- `start_point_id`
- `end_point_id`
- `construction`
- `style`
- `metadata`

### SketchCircle

Propiedades incluidas desde el alcance inicial:

- `id`
- `name`
- `visible`
- `center_point_id`
- `radius`
- `construction`
- `style`
- `metadata`

Regla de creacion acordada:

- `Circle = centro + punto de radio`

### SketchArc

Propiedades incluidas desde el alcance inicial:

- `id`
- `name`
- `visible`
- `center_point_id`
- `start_point_id`
- `end_point_id`
- `style`
- `metadata`

Regla de creacion acordada:

- `Arc = 3 puntos`
- en esta primera fase tambien se almacenara internamente como entidad definida por `3 puntos`

### SketchInfiniteLine

Propiedades minimas propuestas:

- `id`
- `name`
- `visible`
- `point_a_id`
- `point_b_id`
- `construction`
- `style`
- `metadata`

Regla de creacion acordada:

- `InfiniteLine = 2 puntos`

## 8. Restricciones conceptuales

Las restricciones viviran como entidades explicitas, no como flags sueltos.

Propiedades minimas propuestas:

- `id`
- `name`
- `type`
- `references`
- `value`
- `driving`
- `metadata`

Tipos previstos:

- `distance`
- `angle`
- `horizontal`
- `vertical`
- `parallel`
- `perpendicular`
- `equal_length`
- `equal_radius`
- `point_on_point`
- `point_on_line`
- `point_on_circle`
- `midpoint`
- `tangent`
- `symmetric`

Tipos implementados ahora:

- `fix`
- `horizontal`
- `vertical`
- `distance`
- `coincident`

## 9. Parametrizacion

- El `Sketch` compartira el sistema global de parametros del proyecto.
- Las cotas podran usar expresiones y unidades compatibles.
- Las coordenadas y dimensiones del sketch se editaran con el mismo sistema de expresiones ya existente.
- El inspector debera mostrar expresion y valor evaluado.

## 10. Integracion con el canvas

El canvas seguira siendo unico, pero con dos capas logicas:

- capa `Sketch`
- capa `Model`

Comportamiento previsto:

- al editar sketch, el modelo se podra mostrar atenuado
- al editar modelo, el sketch se podra mostrar atenuado
- el usuario podra mostrar u ocultar cada capa
- seleccionar en canvas o en arbol debera ser equivalente
- el sketch tendra herramientas explicitas propias en la toolbar desde la primera iteracion
- el snap del modelo podra hacerse contra todas las entidades geometricas iniciales del sketch
- el propio sketch tendra snap interno basico, al menos sobre puntos y referencias geometricas obvias
- el control de visibilidad inicial sera un toggle global de `Sketch visible`
- cuando el sketch este visible, su representacion debera ser sutil, con linea fina y colores poco llamativos
- se podran seleccionar en canvas todas las entidades iniciales del sketch
- la edicion geometrica directa en canvas se hara mediante puntos de control

Herramientas iniciales acordadas:

- `Sketch Point`
- `Sketch LineSegment`
- `Sketch Circle`
- `Sketch Arc`
- `Sketch InfiniteLine`

Reglas iniciales de interaccion acordadas:

- las herramientas de sketch seguiran un flujo de clics sucesivos
- `Enter` permitira finalizar la operacion cuando aplique
- `Esc` permitira cancelar la operacion actual
- la seleccion multiple queda fuera de la primera fase para simplificar

## 11. Integracion con el arbol del proyecto

Decision acordada:

- el sketch tendra su propia pestana o rama especifica desde la primera iteracion

Estructura propuesta:

- `Sketch`
  - `Points`
  - `LineSegments`
  - `Circles`
  - `Arcs`
  - `InfiniteLines`
  - restricciones

Y mantener `Parameters` como espacio comun.

## 12. Integracion con el inspector

El inspector debera permitir al menos:

- renombrar entidades de sketch
- editar coordenadas
- editar cotas y expresiones
- cambiar visibilidad
- marcar entidades como construction cuando aplique
- editar las propiedades geometricas especificas de cada tipo de entidad

Regla acordada:

- todas las entidades geometricas iniciales podran marcarse como `construction`

## 13. Integracion con el modelo mecanico

Capacidades objetivo:

- usar puntos del sketch como referencia para crear markers
- usar lineas del sketch como referencia para barras o sliders
- hacer snap del modelo al sketch en `t=0`

Regla clave:

- el sketch no impone por si mismo restricciones a la simulacion del modelo
- solo define y apoya la configuracion inicial
- si el sketch se modifica despues, por ahora no actualiza el modelo ya creado
- el snap en canvas tendra ayuda visual durante el arrastre y ajuste geometrico exacto al soltar

## 14. JSON propuesto

Se propone ampliar el proyecto con un nuevo bloque:

```json
{
  "schema_version": "0.1.0",
  "project": {},
  "parameters": [],
  "sketch": {},
  "model": {},
  "view_state": {}
}
```

Estructura conceptual del sketch:

```json
{
  "id": "sketch_001",
  "name": "Main Sketch",
  "visible": true,
  "style": {},
  "entities": [],
  "constraints": []
}
```

Decision acordada:

- en esta primera fase se persistira el estado visual basico del sketch, al menos su visibilidad y estilo base

## 15. API orientativa

Posibles operaciones iniciales:

- `create_sketch(name: str) -> str`
- `create_sketch_point(...) -> str`
- `create_sketch_line_segment(...) -> str`
- `update_sketch_entity(...) -> None`
- `create_sketch_constraint(...) -> str`
- `delete_sketch_entity(...) -> None`
- `delete_sketch_constraint(...) -> None`
- `cancel_sketch_tool() -> None`

## 16. Primer roadmap tecnico

### Paso 1

Definir alcance funcional minimo del sketch.

### Paso 2

Cerrar modelo de datos:

- entidades
- restricciones
- reglas de persistencia

### Paso 3

Definir integracion GUI:

- toolbar
- canvas
- arbol
- inspector

### Paso 4

Implementar capa base sin solver:

- `Point`
- `LineSegment`
- seleccion
- move
- JSON

### Paso 5

Anadir GUI del sketch sobre la API ya creada:

- toolbar propia
- canvas
- arbol
- inspector
- toggle global de visibilidad

### Paso 6

Integrar persistencia y flujo de edicion completo:

- guardar proyecto con sketch
- cargar proyecto con sketch
- `undo/redo` de operaciones de sketch
- uso del sketch dentro de ejemplos mecanicos existentes

### Paso 7

Completar la primera entrega funcional:

- soporte completo para `Point`, `LineSegment`, `Circle`, `Arc` e `InfiniteLine`
- inspector de sketch util desde el primer corte
- indicadores visuales de snap desde el inicio

### Paso 8

Decidir solver de sketch y restriccion minima resoluble.

## 18. Roadmap de implementacion propuesto

### Fase K1. Dominio y contratos

Objetivo:

- introducir el subsistema `Sketch` en la libreria sin tocar aun la GUI

Entregables:

- entidad raiz `Sketch`
- entidades `SketchPoint`, `SketchLineSegment`, `SketchCircle`, `SketchArc`, `SketchInfiniteLine`
- ids, nombres autogenerados y propiedades comunes
- reglas de borrado en cascada
- validaciones basicas internas

Criterio de cierre:

- el dominio puede crear, editar, borrar y listar entidades de sketch de forma consistente

### Fase K2. JSON y persistencia

Objetivo:

- integrar sketch en el archivo de proyecto sin romper compatibilidad

Entregables:

- bloque `sketch` en `.quino.json`
- serializacion y deserializacion completas
- persistencia de visibilidad y estilo base
- roundtrip estable con proyectos que tengan o no sketch

Criterio de cierre:

- un proyecto con sketch se puede guardar y cargar sin perdida funcional

### Fase K3. API de aplicacion

Objetivo:

- exponer sketch a traves de `ApplicationService`

Entregables:

- operaciones para crear sketch
- operaciones para crear las 5 entidades geometricas
- operaciones para editar propiedades
- operaciones para borrar entidades
- soporte para `undo/redo`
- cancelacion de herramienta activa de sketch

Criterio de cierre:

- toda mutacion de sketch pasa por la API y entra en historial reversible

### Fase K4. Canvas y herramientas

Objetivo:

- habilitar una primera experiencia de sketch usable en GUI

Entregables:

- herramientas `Sketch Point`, `Sketch LineSegment`, `Sketch Circle`, `Sketch Arc`, `Sketch InfiniteLine`
- flujo por clics sucesivos
- `Enter` para finalizar cuando aplique
- `Esc` para cancelar
- seleccion en canvas de todas las entidades
- puntos de control para edicion geometrica directa
- visualizacion sutil del sketch
- toggle global `Sketch visible`

Criterio de cierre:

- el usuario puede dibujar y editar manualmente las 5 entidades desde el canvas

### Fase K5. Arbol e inspector

Objetivo:

- hacer navegable y editable el sketch fuera del canvas

Entregables:

- pestana o rama propia `Sketch`
- agrupacion por tipos
- seleccion sincronizada arbol/canvas
- inspector con nombre, visible, construction y propiedades geometricas
- expresion y valor evaluado donde aplique

Criterio de cierre:

- cualquier entidad de sketch se puede localizar y editar desde inspector y arbol

### Fase K6. Snap

Objetivo:

- conectar el sketch con la edicion del modelo sin acoplarlos

Entregables:

- snap interno basico del sketch
- snap del modelo hacia todas las entidades geometricas del sketch en `t=0`
- indicadores visuales de snap
- ajuste exacto al soltar

Regla de control:

- mover sketch no modifica el modelo ya creado
- mover modelo no modifica el sketch

Criterio de cierre:

- el sketch ayuda al posicionamiento, pero sigue siendo independiente del modelo mecanico

### Fase K7. Flujo completo de proyecto

Objetivo:

- cerrar la primera entrega funcional de sketch

Entregables:

- crear proyecto con o sin sketch
- guardar y cargar proyecto con sketch
- `undo/redo` estable de operaciones de sketch
- uso del sketch dentro de ejemplos mecanicos existentes

Criterio de cierre:

- el usuario puede usar sketch de principio a fin dentro del flujo normal de QUINO

### Fase K8. Validacion y pulido

Objetivo:

- endurecer robustez e interaccion antes de pasar a restricciones

Entregables:

- tests de dominio
- tests de roundtrip JSON
- tests de API
- tests GUI basicos
- revision fina de snap, seleccion, borrado y cancelacion

Criterio de cierre:

- la primera fase de sketch queda estable sin solver

## 19. Orden tecnico recomendado

Orden propuesto:

1. dominio
2. JSON
3. API
4. arbol e inspector minimo
5. canvas y herramientas
6. snap
7. undo/redo y flujo completo
8. pulido y tests

Motivo:

- primero se fija la base reutilizable de libreria
- despues se monta la GUI como cliente de esa base
- el snap y el pulido se dejan para cuando la geometria ya existe de forma estable

## 20. Primer corte implementable recomendado

Primer corte recomendado:

- Fase K1
- Fase K2
- Fase K3
- Fase K4
- Fase K5

Con ese corte ya tendriamos:

- sketch persistente
- API usable
- GUI de dibujo manual
- arbol
- inspector

Y dejariamos para el corte siguiente:

- snap avanzado
- endurecimiento de `undo/redo`
- integracion fina con ejemplos
- pulido final de interaccion

## 17. Puntos a decidir contigo

### Bloque A. Alcance inicial

Decisiones ya acordadas:

- arrancar con `Point + LineSegment + Circle + Arc + InfiniteLine`
- primera iteracion sin solver de restricciones

### Bloque B. Integracion

- el sketch es opcional para el usuario
- el sketch sera una capa inferior
- el modelo podra hacer `snap` al sketch al editarse en `t=0`
- si el sketch cambia, por ahora no modifica el modelo ya existente

### Bloque C. Solver

Estado actual:

- primera iteracion de solver ya implementada para restricciones basicas entre puntos

### Bloque D. Edicion y borrado

Decisiones ya acordadas:

- flujo de creacion de sketch con clics sucesivos
- `Enter` y `Esc` como finalizacion o cancelacion cuando aplique
- seleccion multiple fuera de la primera fase
- si se borra un `Point`, el borrado sera en cascada sobre las entidades de sketch que dependan de el

### Bloque E. Snap y arbol

Decisiones ya acordadas:

- habra snap interno basico entre entidades del sketch
- todas las entidades geometricas iniciales podran marcarse como `construction`
- el arbol de sketch se organizara agrupado por tipo

### Bloque F. Persistencia y primera entrega

Decisiones ya acordadas:

- en la primera fase habra un unico `Sketch` por proyecto
- se persistira el estado visual basico del sketch
- la primera entrega incluira base de libreria, API, JSON y GUI de sketch manual
- el guardado y la carga con sketch entran desde el primer dia de esa fase
- `undo/redo` de sketch entra en la primera fase
- no hace falta un ejemplo exclusivo de sketch; se integrara en los ejemplos mecanicos existentes
- la primera entrega incluira las cinco entidades geometricas iniciales completas
- el inspector de sketch sera util desde el primer corte
- la GUI mostrara indicadores visuales de snap desde el inicio
