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
- mover puntos
- editar coordenadas y propiedades desde inspector
- snap visual basico al modelo

### Fase S3. Restricciones basicas

- `horizontal`
- `vertical`
- `distance`
- `angle`
- `point_on_point`
- `point_on_line`

### Fase S4. Integracion con modelo

- snap de markers del modelo a entidades del sketch en `t=0`
- herramientas para crear entidades del modelo a partir del sketch
- visibilidad atenuada sketch/model

### Fase S5. Geometria ampliada

- `Circle`
- `Arc`
- `InfiniteLine`
- otras restricciones segun prioridad

## 5. Decision de arranque pendiente

La primera decision importante es el alcance geometrico inicial.

Opciones razonables:

- Minimo: `Point + LineSegment`
- Medio: `Point + LineSegment + Circle`
- Amplio: `Point + LineSegment + Circle + Arc + InfiniteLine`

## 6. Comportamiento con y sin solver de sketch

### Sin solver de sketch

- el usuario podra crear entidades geometricas
- el usuario podra moverlas manualmente
- el usuario podra editar sus propiedades numericas
- no se permitira crear restricciones resolubles automaticamente

### Con solver de sketch

- el usuario podra anadir restricciones geometricas y dimensionales
- el sistema intentara resolver el sketch
- el sketch pasara a tener grados de libertad geometricos controlados

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

### SketchPoint

Propiedades minimas propuestas:

- `id`
- `name`
- `x`
- `y`
- `fixed`
- `style`
- `metadata`

### SketchLineSegment

Propiedades minimas propuestas:

- `id`
- `name`
- `start_point_id`
- `end_point_id`
- `construction`
- `style`
- `metadata`

### SketchCircle

Propiedades previstas para fases posteriores:

- `id`
- `name`
- `center_point_id`
- `radius`
- `construction`
- `style`
- `metadata`

### SketchArc

Propiedades previstas para fases posteriores:

- `id`
- `name`
- `center_point_id`
- `start_point_id`
- `end_point_id`
- `style`
- `metadata`

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

## 11. Integracion con el arbol del proyecto

Se propone anadir una pestana o rama especifica para sketch:

- `Sketch`
  - entidades
  - restricciones

Y mantener `Parameters` como espacio comun.

## 12. Integracion con el inspector

El inspector debera permitir al menos:

- renombrar entidades de sketch
- editar coordenadas
- editar cotas y expresiones
- cambiar visibilidad
- marcar entidades como construction cuando aplique

## 13. Integracion con el modelo mecanico

Capacidades objetivo:

- usar puntos del sketch como referencia para crear markers
- usar lineas del sketch como referencia para barras o sliders
- hacer snap del modelo al sketch en `t=0`

Regla clave:

- el sketch no impone por si mismo restricciones a la simulacion del modelo
- solo define y apoya la configuracion inicial

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
  "entities": [],
  "constraints": []
}
```

## 15. API orientativa

Posibles operaciones iniciales:

- `create_sketch(name: str) -> str`
- `create_sketch_point(...) -> str`
- `create_sketch_line_segment(...) -> str`
- `update_sketch_entity(...) -> None`
- `create_sketch_constraint(...) -> str`
- `delete_sketch_entity(...) -> None`
- `delete_sketch_constraint(...) -> None`

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

Decidir solver de sketch y restriccion minima resoluble.

## 17. Puntos a decidir contigo

### Bloque A. Alcance inicial

- si arrancamos con `Point + LineSegment` o anadimos `Circle`
- si las restricciones entran desde la primera iteracion o en una segunda

### Bloque B. Integracion

- si el sketch debe existir siempre en el proyecto o solo cuando el usuario lo cree
- si quieres una herramienta explicita para convertir sketch -> modelo

### Bloque C. Solver

- si en la primera iteracion aceptamos `sketch` sin solver
- o si prefieres que no exista sketch util hasta tener solver de restricciones
