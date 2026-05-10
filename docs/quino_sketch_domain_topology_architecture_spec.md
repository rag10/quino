# QUINO Sketcher — Domain & Topology Architecture

## Objetivo

Definir la arquitectura completa del dominio geométrico y topológico del sketcher paramétrico 2D integrado en QUINO.

Este documento define:

- modelo de dominio
- ownership
- topología
- entidades geométricas
- referencias
- relaciones
- parámetros
- lifecycle
- constraint attachment
- dependency graph
- evaluación geométrica
- serialización
- caches
- mutabilidad
- integración solver

---

# 1. Filosofía fundamental

El sketch NO es una colección de primitivas gráficas.

El sketch es:

```text
un grafo topológico paramétrico
```

La geometría visible es:

```text
una evaluación del estado paramétrico actual
```

---

# 2. Principios arquitectónicos

## 2.1 Separación obligatoria

Separar estrictamente:

```text
Topología
Geometría
Constraints
Solver state
Rendering state
Interaction state
```

---

## 2.2 Regla crítica

Las entidades NO almacenan geometría redundante.

Porque rompe:

- consistencia
- solver
- constraints
- topología
- estabilidad

---

# 3. Arquitectura general

```text
Sketch
    Topology
        Nodes
        Edges

    Geometry
        Curves
        Points

    Constraints

    Variables

    Parameters
```

---

# 4. Entidad raíz

## 4.1 Sketch

```python
@dataclass(slots=True)
class Sketch:
    id: str
    name: str

    entities: dict[str, SketchEntity]
    constraints: dict[str, Constraint]

    variables: dict[str, Variable]

    metadata: SketchMetadata
```

---

## 4.2 Responsabilidades

Sketch:

- ownership global
- indexing
- lifecycle
- dependency registration
- serialization root

---

# 5. IDs y referencias

## 5.1 Regla obligatoria

Toda entidad posee:

```python
id: str
```

persistente.

---

## 5.2 Regla crítica

Las entidades se relacionan:

```text
solo mediante IDs
```

NO mediante referencias directas.

---

## 5.3 Incorrecto

```python
line.start_point = point
```

---

## 5.4 Correcto

```python
line.start_point_id = point.id
```

---

## 5.5 Beneficios

- serialización simple
- graph traversal
- dependency analysis
- undo/redo seguro
- referencias persistentes
- desacoplamiento

---

# 6. Base entity

## 6.1 SketchEntity

```python
@dataclass(slots=True)
class SketchEntity:
    id: str

    name: str

    construction: bool = False
    visible: bool = True
    selectable: bool = True

    metadata: dict[str, Any] = field(default_factory=dict)
```

---

# 7. Topología

## 7.1 Filosofía

La topología define:

```text
cómo se conectan las entidades
```

NO cómo se renderizan.

---

## 7.2 Nodos topológicos

```python
SketchPoint
```

---

## 7.3 Aristas topológicas

```python
SketchLineSegment
SketchArc
SketchSpline
```

---

## 7.4 Beneficio crítico

El sketch se convierte en:

```text
un graph estructural
```

Esto permite:

- solver eficiente
- constraints robustas
- shared geometry
- DOF correctos

---

# 8. SketchPoint

## 8.1 Definición

```python
@dataclass(slots=True)
class SketchPoint(SketchEntity):
    x: Expression
    y: Expression
```

---

## 8.2 Regla importante

Los puntos son:

```text
las entidades fundamentales del solver
```

---

## 8.3 DOF

```text
x
y
```

2 DOF.

---

# 9. SketchLineSegment

## 9.1 Definición

```python
@dataclass(slots=True)
class SketchLineSegment(SketchEntity):
    start_point_id: str
    end_point_id: str
```

---

## 9.2 Regla crítica

La línea NO almacena:

- longitud
- dirección
- ángulo
- coordenadas

Todo se deriva.

---

## 9.3 Beneficio

Evita:

- inconsistencias
- datos duplicados
- solver ambiguo

---

# 10. SketchCircle

## 10.1 Definición

```python
@dataclass(slots=True)
class SketchCircle(SketchEntity):
    center_point_id: str

    radius: Expression
```

---

## 10.2 DOF

```text
center.x
center.y
radius
```

---

# 11. SketchArc

## 11.1 Definición

```python
@dataclass(slots=True)
class SketchArc(SketchEntity):
    center_point_id: str
    start_point_id: str
    end_point_id: str
```

---

## 11.2 Regla crítica

El arco NO almacena:

- radio
- ángulo inicial
- ángulo final

Todo se deriva.

---

# 12. Splines

## 12.1 Fase inicial

NO implementar inicialmente.

---

## 12.2 Arquitectura preparada

```python
@dataclass(slots=True)
class SketchSpline(SketchEntity):
    control_point_ids: list[str]
```

---

# 13. Constraints

## 13.1 Filosofía

Las constraints NO modifican entidades.

Las constraints:

```text
definen ecuaciones
```

---

## 13.2 Base

```python
@dataclass(slots=True)
class Constraint:
    id: str

    enabled: bool = True
    driving: bool = True
```

---

# 14. Constraint attachment

## 14.1 Regla

Las constraints referencian entidades por ID.

---

## 14.2 Ejemplo

```python
@dataclass(slots=True)
class CoincidentConstraint(Constraint):
    point_a_id: str
    point_b_id: str
```

---

# 15. Variables

## 15.1 Definición

```python
@dataclass(slots=True)
class Variable:
    name: str

    expression: str
```

---

## 15.2 Objetivo

Permitir:

```text
width = 100
height = width / 2
```

---

# 16. Expressions

## 16.1 Regla importante

Las entidades NO almacenan floats editables directamente.

Deben almacenar:

```python
Expression
```

---

## 16.2 Beneficios

- parametrización
- variables globales
- fórmulas
- relaciones dinámicas

---

# 17. Parámetros solver

## 17.1 Regla crítica

El solver NO trabaja con entidades.

Trabaja con:

```text
SolverParameters
```

---

## 17.2 Ejemplo

```text
Point.x
Point.y
Circle.radius
```

---

# 18. Parameter mapping

## 18.1 Arquitectura

```python
class ParameterMapper:
    def build(sketch) -> SolverParameterSet
```

---

## 18.2 Responsabilidad

Convertir:

```text
Domain model
→
Solver parameters
```

---

# 19. Evaluación geométrica

## 19.1 Filosofía

La geometría visible:

```text
se evalúa dinámicamente
```

---

## 19.2 Ejemplo línea

```text
start point
end point
→
segment geometry
```

---

## 19.3 Consecuencia importante

Las entidades deben ser:

```text
ligeras y declarativas
```

---

# 20. Geometry evaluation layer

## 20.1 Objetivo

Separar:

```text
Domain entities
≠
Evaluated geometry
```

---

## 20.2 Arquitectura

```python
class GeometryEvaluator:
    def evaluate(entity_id) -> EvaluatedGeometry
```

---

# 21. Evaluated geometry

## 21.1 Ejemplo

```python
@dataclass(slots=True)
class EvaluatedLineSegment:
    start: Vec2
    end: Vec2
```

---

## 21.2 Uso

Utilizado por:

- renderer
- picking
- snapping
- bounding boxes

---

# 22. Bounding boxes

## 22.1 Regla

Toda entidad evaluada debe exponer:

```python
bbox
```

---

## 22.2 Uso

Necesario para:

- picking
- redraw
- spatial indexing
- zoom extents

---

# 23. Dependency graph

## 23.1 Objetivo

Representar:

```text
qué depende de qué
```

---

## 23.2 Tipos de dependencia

```text
Entity → Parameter
Constraint → Parameter
Expression → Variable
```

---

## 23.3 Uso

Permite:

- updates incrementales
- invalidación parcial
- recálculo eficiente

---

# 24. Cache architecture

## 24.1 Problema

Evaluar toda la geometría constantemente es caro.

---

## 24.2 Solución

Caches incrementales.

---

## 24.3 Cache levels

```text
Expression cache
Geometry cache
Bounding box cache
Spatial index cache
```

---

# 25. Invalidation model

## 25.1 Pipeline

```text
parameter change
→ dependency update
→ geometry invalidation
→ bbox invalidation
→ redraw invalidation
```

---

# 26. Mutabilidad

## 26.1 Recomendación

Domain entities:

```text
mutable controlled
```

---

## 26.2 Modificaciones permitidas solo mediante

```text
ApplicationService
Commands
```

---

## 26.3 Canvas NO modifica dominio directamente

Nunca:

```python
point.x = ...
```

---

# 27. Ownership

## 27.1 Regla

Sketch posee:

- entidades
- constraints
- variables

---

## 27.2 Entidades NO poseen otras entidades

Porque complica:

- serialización
- undo
- graph traversal
- lifecycle

---

# 28. Lifecycle

## 28.1 Creación

```text
ApplicationService
→ create entity
→ register
→ update graph
→ solve
```

---

## 28.2 Eliminación

```text
remove entity
→ remove dependent constraints
→ invalidate graph
→ solve
```

---

# 29. Constraint ownership

## 29.1 Regla importante

Las constraints pertenecen:

```text
al sketch
```

NO a las entidades.

---

## 29.2 Beneficio

Permite:

- graph traversal limpio
- serialization simple
- dependency management

---

# 30. Serialization

## 30.1 Filosofía

El modelo debe ser:

```text
JSON serializable directamente
```

---

## 30.2 Formato

```json
{
  "entities": {},
  "constraints": {},
  "variables": {}
}
```

---

## 30.3 Regla crítica

Nunca serializar:

- caches
- geometry evaluation
- render state
- solver state temporal

---

# 31. Solver integration

## 31.1 Flujo

```text
Sketch
→ Parameter mapping
→ Equation building
→ Solve
→ Parameter update
→ Geometry reevaluation
```

---

## 31.2 Regla crítica

El solver NO modifica entidades directamente.

Debe actualizar:

```text
SolverParameters
```

que luego se sincronizan.

---

# 32. Domain events

## 32.1 Recomendación

Agregar:

```text
EntityCreated
EntityModified
ConstraintAdded
ConstraintRemoved
```

---

## 32.2 Uso

Permite:

- invalidación incremental
- cache updates
- redraw eficiente

---

# 33. Spatial indexing

## 33.1 Requisitos

Necesitamos:

```text
entity bbox indexing
```

---

## 33.2 Uso

- hover
- snapping
- selection
- redraw

---

# 34. Analysis model

## 34.1 Estados

```python
enum SketchState:
    UNDER_CONSTRAINED
    FULLY_CONSTRAINED
    OVER_CONSTRAINED
    INCONSISTENT
```

---

## 34.2 Resultado análisis

```python
@dataclass
class SketchAnalysis:
    dof_count: int

    unconstrained_entities: list[str]

    conflicting_constraints: list[str]
```

---

# 35. Extensibilidad

## 35.1 Requisitos

El dominio debe permitir:

```text
nuevas entidades
nuevas constraints
nuevos evaluadores
nuevos backends solver
```

---

## 35.2 Registro dinámico

```python
EntityRegistry
ConstraintRegistry
GeometryEvaluatorRegistry
```

---

# 36. Arquitectura futura

El modelo debe permitir posteriormente:

```text
3D sketching
feature modeling
assembly constraints
history tree
multi-body modeling
```

---

# 37. Recomendaciones críticas

## 37.1 NO almacenar geometría redundante

## 37.2 NO mezclar rendering con dominio

## 37.3 NO usar referencias directas entre entidades

## 37.4 NO acoplar solver al dominio

## 37.5 NO almacenar caches en serialización

---

# 38. Conclusión

La arquitectura correcta del sketch domain requiere:

- topología explícita
- entidades ligeras
- referencias por ID
- evaluación geométrica dinámica
- separación solver/domain
- caches incrementales
- dependency graph
- ownership centralizado
- serialización limpia

El sketch debe comportarse como:

```text
un sistema topológico paramétrico evaluado dinámicamente
```

