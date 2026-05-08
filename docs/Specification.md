# Specification

## 1. Vision del producto

La aplicacion sera una herramienta de ingenieria para crear y simular mecanismos 2D, inspirada en productos como ASOM Kinematics, SAM o PMKS+.

La base tecnologica prevista es:

- Python
- PySide6 o PyQt

Decision de arranque para V1:

- La implementacion de GUI arrancara con `PySide6` como toolkit por defecto.
- La posible compatibilidad con `PyQt` queda fuera del arranque inicial y podra evaluarse mas adelante.

El objetivo a largo plazo es construir una plataforma de ingenieria extensible, con una GUI profesional y una arquitectura capaz de apoyarse en distintos solvers.

## 2. Principios del proyecto

- El desarrollo se hara poco a poco y con mucho cuidado.
- El sistema debe ser extensible.
- Todo el modelo debe ser serializable a JSON.
- La parametrizacion sera una capacidad de primera clase desde el inicio.
- La GUI debe ser user-friendly.
- La aplicacion debe concebirse desde el principio como una libreria usable sin GUI.
- La GUI sera una capa opcional sobre esa libreria.
- La filosofia general es eliminar complejidad innecesaria antes de anadir nuevas capas.

## 3. Arquitectura de alto nivel

La arquitectura objetivo es una capa de alto nivel sobre uno o varios solvers:

```text
Usuario / GUI opcional
  ->
Modelo mecanico propio
  ->
Validador + ensamblador abstracto
  ->
Traductor de backend
  ->
Solver
```

Solvers posibles a futuro:

- Exudyn
- Chrono
- Solver nativo
- Otros backends

La interfaz grafica servira para especificar flujos de uso y ergonomia, pero no definira el nucleo de la aplicacion.

## 4. Alcance acordado para V1

La primera version estara enfocada exclusivamente en cinematica 2D.

La V1 debera permitir construir y simular mecanismos 2D de forma generalista, sin limitarse a ejemplos concretos.

Como referencia de validacion inicial, la V1 debera cubrir al menos estos dos casos:

- mecanismo de cuatro barras
- mecanismo biela-manivela con corredera

En esta fase no habra sketch. El trabajo sera directamente sobre el modelo mecanico en el canvas.

La V1 incluira parametrizacion desde el principio.

## 5. Modelo conceptual de V1

### 5.1 Entidades base

- Body
- Marker
- Joint
- Slider

### 5.2 Criterios de modelado

- `Body` sera la entidad estructural principal.
- `Bar` no sera una entidad distinta a nivel conceptual profundo, sino un caso particular de `Body`.
- Un `Body` podra tener desde 1 marker en adelante.
- Un `Bar` sera un `Body` con exactamente 2 markers.
- Un `Body` general podra tener 1 o mas markers.
- Los `markers` viviran dentro de cada `Body`.

### 5.3 Creacion de elementos

- Para crear un `Body`, el usuario ira pinchando en el canvas para posicionar sus markers.
- Despues, los markers podran editarse.
- La creacion de `Body` podra finalizarse tanto con `Enter` como con doble clic.
- Para crear un `Bar`, la herramienta generara exactamente 2 markers.
- Un `Body` con un unico marker se interpretara como una masa puntual.
- Un `Body` con un unico marker podra evolucionar despues a un cuerpo con varios markers mediante `Add Marker to Body`.
- Si un `bar` recibe markers adicionales, pasara automaticamente a convertirse en `body`.
- Al crear un `Body`, se generara automaticamente un marker `com`.
- En un `Body` general, el marker `com` se inicializara en el centro definido por la media de las coordenadas `x` e `y` de sus markers estructurales.
- En un `Bar`, el marker `com` se inicializara en el centro de la barra.
- Ese calculo automatico del `com` solo se aplicara en la creacion inicial del elemento.

### 5.4 Representacion visual inicial

En V1, los cuerpos se representaran con:

- markers
- aristas

El relleno poligonal y representaciones visuales mas avanzadas se dejan para fases posteriores.

Regla visual inicial adicional:

- Las masas puntuales, es decir, `Body` con un solo marker, se visualizaran con un circulo algo mayor que el marker para poder identificarlas con claridad.

### 5.5 Propiedades base de las entidades

#### Body

Propiedades base propuestas para `Body`:

- `id`
- `name`
- `type`
- `markers`
- `edge_order`
- `closed_shape`
- `mass`
- `inertia`
- `style`
- `metadata`

Reglas iniciales:

- `id` sera un identificador interno estable.
- `name` sera visible para el usuario y debera ser unico entre bodies del mismo modelo.
- `type` podra ser al menos `bar` o `body`.
- `markers` contendra los markers propios del cuerpo.
- `edge_order` definira el orden de conexion visual entre markers.
- Por defecto, `edge_order` seguira el orden de creacion de los markers.
- `edge_order` sera editable desde el `Inspector`.
- El marker `com` formara parte de `markers`, pero no de `edge_order`.
- `closed_shape` sera normalmente `false` para `bar` y `true` para `body`.
- Un `Body` creado con la herramienta general se considerara cerrado por defecto.
- Un `bar` se considerara abierto por defecto.
- `mass` e `inertia` quedaran preparados desde V1 aunque la primera version se centre en cinematica.
- Siempre que sea posible sin complicar en exceso la implementacion, estas propiedades podran exponerse ya en la libreria y en el inspector.
- `mass` e `inertia` podran ser editados manualmente.
- En el futuro, y cuando tenga sentido, algunos de estos valores tambien podran calcularse automaticamente.
- La posicion del `CoM` no se almacenara duplicada como propiedad separada del `Body`; su unica representacion geometrica sera el marker `com`.
- La posicion del marker `com` se expresara en coordenadas locales relativas al `Body`.
- El sistema local del `Body` tendra, por defecto, su origen en el primer marker.
- Cuando existan dos o mas markers, la orientacion local del `Body` se derivara por defecto del primer y segundo marker.
- Si un `Body` tiene exactamente un marker estructural, podra materializarse automaticamente como `point_mass`.

#### Marker

Propiedades base propuestas para `Marker`:

- `id`
- `name`
- `type`
- `x`
- `y`
- `style`
- `metadata`

Reglas iniciales:

- `id` sera un identificador interno estable.
- `name` sera visible para el usuario y debera ser unico dentro de su `Body`.
- `Marker` tendra un `type` para permitir distinguir distintos roles dentro del `Body`.
- Entre los tipos previstos podra existir al menos un marker de tipo `com`.
- Solo podra existir un marker `com` por cada `Body`.
- El marker `com` tendra, en general, las mismas capacidades que otros markers.
- Sobre el marker `com` se podran definir uniones, cargas y otras operaciones del modelo cuando corresponda.
- El marker `com` debera identificarse visualmente de forma distinta al resto.
- El marker `com` se creara inicialmente oculto.
- La masa asociada al `Body` se inicializara por defecto a `0`.
- El marker `com` pasara a ser visible cuando el usuario lo active manualmente o cuando la masa del `Body` tome un valor distinto de `0`.
- Si la masa del `Body` vuelve a `0`, el marker `com` se ocultara automaticamente.
- Despues de la creacion inicial, el marker `com` podra moverse manualmente en coordenadas locales del `Body`.

#### Slider

Propiedades base propuestas para `Slider`:

- `id`
- `name`
- `origin_x`
- `origin_y`
- `angle`
- `travel_min`
- `travel_max`
- `style`
- `metadata`

Reglas iniciales:

- `id` sera un identificador interno estable.
- `name` sera visible para el usuario y debera ser unico entre sliders del mismo modelo.
- Un `slider` se definira por `origen + angulo`.
- `travel_min` y `travel_max` definiran el recorrido permitido a lo largo de su eje.
- `travel_min` y `travel_max` podran dejarse sin definir para representar recorrido no acotado.
- Su representacion visual exacta podra evolucionar mas adelante sin cambiar este modelo base.
- `name`, `style` y `metadata` seran editables desde V1.
- La creacion inicial de un `slider` se hara dibujandolo en el canvas y refinando despues sus propiedades en el `Inspector`.
- La herramienta `Create Slider` utilizara 2 clics para definir una direccion visual inicial.
- El `slider` tendra un marcador visual de referencia situado en el centro de la carrera.

#### Joint

Propiedades base propuestas para `Joint`:

- `id`
- `name`
- `type`
- `endpoint_a`
- `endpoint_b`
- `style`
- `metadata`

Estructura base de cada `endpoint`:

- `kind`
- `body_id` cuando aplique
- `marker_id` cuando aplique
- `slider_id` cuando aplique

Reglas iniciales:

- `id` sera un identificador interno estable.
- `name` sera visible para el usuario y debera ser unico entre joints del mismo modelo.
- `kind` podra ser `marker`, `ground` o `slider`.
- Si `kind` es `marker`, el extremo referenciara `body_id` y `marker_id`.
- Si `kind` es `slider`, el extremo referenciara `slider_id`.
- Si `kind` es `ground`, no necesitara mas datos.
- `Joint` no almacenara una posicion propia independiente; su localizacion se deducira de los elementos que conecta.
- En V1, `type` podra ser al menos `revolute` o `rigid`.
- Se permitira tanto `revolute` como `rigid` entre `marker` y `ground`.
- No sera necesario un estado `enabled/disabled` para `Joint` en V1; si una union deja de ser necesaria, se eliminara.
- La creacion de `Create Revolute Joint` y `Create Rigid Joint` se hara seleccionando dos extremos de forma secuencial.
- Si dos markers que van a unirse no estan en la misma posicion, por defecto el primer extremo seleccionado se movera a la posicion del segundo.
- La creacion de estas juntas podra mostrar un preview visual antes de confirmar la operacion.
- Antes de confirmar la creacion de estas juntas, aparecera tambien un dialogo para definir al menos el nombre.
- `Connect Marker to Ground` se aplicara seleccionando un marker.
- `Connect Marker to Slider` se aplicara seleccionando primero un marker y despues un slider.
- Tanto en `Connect Marker to Ground` como en `Connect Marker to Slider` aparecera antes de confirmar un dialogo para escoger el tipo de union.
- En ese dialogo, la opcion seleccionada por defecto sera `revolute`, y tambien podra elegirse `rigid`.
- Ese dialogo incluira tambien el nombre de la junta, autogenerado por defecto y validado para que no coincida con otra junta existente.
- En estas operaciones se seguira la misma regla general de adaptacion espacial: si es necesario recolocar, el primer elemento seleccionado se adaptara al segundo.
- No se permitira crear una junta duplicada entre los mismos extremos si ya existe otra equivalente.
- Un mismo marker podra participar en varias juntas.
- Un mismo marker podra conectarse simultaneamente a `ground`, `slider` u otros `Body` si el modelo asi lo requiere.
- Estas combinaciones se permitiran a nivel de edicion y sera el validador o el solver quien detecte configuraciones imposibles o inconsistentes.
- La restriccion principal en V1 sera no duplicar juntas equivalentes entre los mismos markers.

## 6. Juntas y relaciones minimas en V1

La primera version debe incluir como minimo:

- revolute joint
- rigid joint
- fijacion a ground
- union a slider

Estas capacidades deben ser suficientes para construir los mecanismos objetivo de V1.

### 6.1 Regla general de joints

- Un `Joint` unira siempre dos extremos.
- En la mayoria de casos, esos extremos seran dos `markers` de `Body` distintos.
- Un caso tipico sera `Body1.marker3 <-> Body2.marker7`.
- Cuando dos markers queden unidos mediante un joint, compartiran la misma posicion espacial.

### 6.2 Extremos permitidos en un joint

Cada extremo de un `Joint` podra apuntar a:

- un `marker` de un `Body`
- `ground`
- un `slider`

### 6.3 Tipos iniciales de joint

- `revolute`: impone misma posicion y permite rotacion relativa
- `rigid`: impone misma posicion y misma orientacion relativa

En el caso de union con `slider`, el sistema permitira desplazamiento segun el eje del slider, pero no rotacion.

### 6.4 Ground y slider

- `ground` se tratara inicialmente como un elemento especial del modelo, no como un `Body` convencional.
- `slider` se tratara como una entidad propia del modelo.
- A nivel conceptual, es preferible que el `slider` no sea un tipo de `Joint`, sino una entidad a la que un `Joint` puede conectarse.

## 7. Serializacion JSON base

El modelo debera ser serializable de forma clara, estable y extensible.

Principios iniciales para la estructura JSON:

- El proyecto se almacenara en un unico archivo JSON.
- La extension recomendada para archivos de proyecto sera `.quino.json`.
- Existira una coleccion de `parameters` a nivel de proyecto o modelo.
- Cada parametro tendra valor, unidad y metadatos basicos.
- Los `markers` viviran anidados dentro de cada `Body`.
- El `CoM` se serializara como un `Marker` normal de tipo `com`, no como un bloque separado del `Body`.
- Los `joints` referenciaran sus extremos mediante identificadores.
- Cada `Joint` tendra dos extremos, por ejemplo `endpoint_a` y `endpoint_b`.
- Un extremo podra ser de tipo `marker`, `ground` o `slider`.
- `Bar` podra existir como tipo practico de creacion y serializacion, aunque internamente siga la logica de `Body`.
- Las propiedades geometricas y cinematicas podran definirse mediante valores directos o referencias a parametros compatibles en unidades.
- El archivo podra incluir tanto el modelo como estado de vista o GUI cuando resulte util.
- Ese estado podra incluir, entre otros, `zoom`, `pan` y distintas opciones de visibilidad.
- Al abrir un proyecto se recuperara ese estado visual guardado.
- La seleccion actual no formara parte del estado persistido.
- La estructura debera poder crecer en el futuro con `drivers`, `parameters`, `constraints`, estilos y metadatos sin romper compatibilidad.

### 7.1 Reglas de parametrizacion

- Los parametros tendran unidades, por ejemplo `mm`, `deg` o `ul`.
- La libreria debera validar compatibilidad dimensional al asignar parametros a propiedades.
- Las propiedades podran definirse mediante valor literal, referencia a parametro o expresion.
- Las expresiones admitiran operadores basicos, al menos `+`, `-`, `*`, `/` y parentesis.
- Las expresiones podran incluir un conjunto inicial de funciones matematicas y de conversion de unidades.
- No se permitira usar un parametro angular para definir una coordenada lineal en el inspector.
- Del mismo modo, no se permitiran asignaciones incompatibles entre magnitudes.
- La GUI y la libreria deberan compartir estas mismas reglas de validacion.
- El `Inspector` permitira editar directamente la expresion original, no solo el valor evaluado.
- El `Inspector` mostrara tambien el valor evaluado de la expresion cuando sea posible.
- Los errores de expresion o incompatibilidad dimensional se mostraran inline en el `Inspector`.

## 8. Flujo de trabajo previsto

Flujo base de uso:

1. Crear proyecto.
2. Crear cuerpos directamente en el canvas.
3. Definir markers y relaciones entre cuerpos.
4. Crear juntas y fijaciones a ground.
5. Editar propiedades desde el inspector.
6. Ejecutar simulacion cinematica.
7. Visualizar animacion y resultados basicos.

## 9. GUI prevista para V1

Las piezas de interfaz consideradas esenciales para la primera version son:

- canvas de edicion
- arbol del modelo
- gestion de parametros
- panel de propiedades / inspector
- acciones de proyecto
- undo / redo
- animacion basica de la simulacion

### 9.1 Herramientas principales de V1

- `New Project`
- `Open Project`
- `Save Project`
- `Undo`
- `Redo`
- `Select`
- `Fit View`
- `Create Bar`
- `Create Body`
- `Add Marker to Body`
- `Create Revolute Joint`
- `Create Rigid Joint`
- `Create Slider`
- `Connect Marker to Ground`
- `Connect Marker to Slider`
- `Manage Parameters`
- `Delete`
- `Edit Properties`
- `Run Kinematic Simulation`
- `Stop Simulation`
- `Play/Pause Animation`
- `Simulation Timeline`

### 9.2 Reglas de edicion y borrado

- La accion `Delete` aplicara sobre `Body`, `Marker`, `Joint` y `Slider`.
- La libreria y la GUI deberan aplicar validaciones para no dejar referencias rotas en el modelo.
- Al borrar un `Body`, se eliminaran automaticamente los `Joint` que dependan de sus markers.
- Al borrar un `Marker`, se eliminaran automaticamente los `Joint` que dependan de ese marker.
- Al borrar un `Slider`, se eliminaran automaticamente los `Joint` que dependan de ese slider.
- Los nombres visibles de `Body`, `Marker`, `Joint` y `Slider` se autogeneraran por defecto.
- La GUI validara en tiempo real los renombrados para evitar nombres repetidos dentro del alcance correspondiente.

### 9.3 Validacion y simulacion

- `Run Kinematic Simulation` no bloqueara la simulacion por validaciones previas del modelo.
- Antes de simular, la aplicacion podra mostrar warnings informativos sobre posibles problemas del modelo.
- Si el solver falla, la aplicacion mostrara un mensaje capturando e informando el error.
- Existira un panel o lista de validacion con finalidad informativa.
- Se permitira guardar un modelo aunque tenga warnings o errores de validacion.
- No habra autoguardado en V1.

### 9.4 Gestion de parametros

- `Manage Parameters` se presentara como una ventana o panel con tabla.
- La tabla incluira al menos las columnas `name`, `expression/value`, `unit` y `description`.
- Cada parametro tendra un `id` interno estable.
- El `name` de parametro debera ser unico en todo el proyecto.
- Las unidades permitidas en V1 perteneceran a un conjunto inicial acotado y bien definido.
- Ese conjunto inicial incluira al menos `mm`, `m`, `deg`, `rad`, `kg`, `s` y `unitless`.
- Existira conversion automatica entre unidades compatibles, por ejemplo entre `mm` y `m`, o entre `deg` y `rad`.
- La unidad de cada parametro sera visible y editable explicitamente en la tabla.
- Un parametro podra depender de otros parametros si puede verificarse de forma sencilla y robusta que no existen bucles de calculo.
- Si esa verificacion introduce demasiada complejidad para V1, las dependencias entre parametros no seran una prioridad inicial.

## 10. Elementos fuera de V1 por ahora

Quedan fuera por el momento, salvo nueva decision:

- sketch parametrico y restricciones geometricas
- dinamica
- sensores completos
- actuadores avanzados
- friccion
- multiples modelos o casos
- scripting de alto nivel desde GUI
- visualizacion poligonal avanzada

## 11. Direccion futura

Mas adelante la aplicacion podria evolucionar hacia:

- sketch opcional como capa de apoyo
- varios backends de solver
- cuerpos mas ricos
- actuadores, cargas y sensores
- analisis de resultados mas avanzados
- bloques de control y otras disciplinas acopladas

## 12. Arquitectura interna propuesta

La arquitectura interna se plantea con enfoque `library-first`, dejando la GUI como capa opcional.

### 12.1 Capas

- `domain`: entidades puras del modelo
- `application`: comandos y casos de uso
- `services`: expresiones, unidades, ids, nombres, validacion
- `serialization`: lectura, escritura y migracion de JSON
- `simulation`: ensamblado, traduccion y ejecucion
- `solver_adapters`: adaptadores a solvers concretos
- `gui`: capa opcional sobre la libreria

### 12.2 Estructura de modulos

```text
quino/
  domain/
  application/
  services/
  serialization/
  simulation/
  solver_adapters/
  gui/
```

### 12.3 Entidades principales

- `Project`
- `Model`
- `Body`
- `Marker`
- `Joint`
- `JointEndpoint`
- `Slider`
- `Parameter`

### 12.4 Objetos de apoyo

- `ScalarProperty`
- `ViewState`
- `Style`
- `Metadata`

### 12.5 Reglas de modelado interno

- `point_mass` existira como `type` explicito, aunque siga siendo conceptualmente un `Body` con un solo marker.
- `Style` y `Metadata` seran clases reutilizables, no solo diccionarios sueltos.
- `ScalarProperty` sera una clase formal desde el principio.
- Las propiedades geometricas y fisicas evaluables se modelaran mediante `ScalarProperty`.

### 12.6 Responsabilidades resumidas

- `Project`: raiz serializable del proyecto
- `Model`: contenedor del modelo mecanico
- `Body`: cuerpo con 1 o mas markers
- `Marker`: punto local del body
- `Joint`: union entre dos extremos
- `JointEndpoint`: descriptor de extremo de junta
- `Slider`: guia de deslizamiento
- `Parameter`: valor parametrico reutilizable
- `ScalarProperty`: expresion, unidad y estado evaluado

### 12.7 Capa de aplicacion

La logica operativa principal vivira en comandos o casos de uso, por ejemplo:

- `create_body`
- `create_bar`
- `add_marker_to_body`
- `create_joint`
- `connect_marker_to_ground`
- `connect_marker_to_slider`
- `update_property`
- `delete_entity`
- `run_simulation`

### 12.8 Regla de desacoplo

- El dominio no dependera de Qt.
- La GUI no modificara el dominio directamente.
- Menus, botones y context menus invocaran la misma API de aplicacion.

## 13. JSON schema conceptual

Se propone una estructura JSON estable, versionada y orientada a evolucion futura.

### 13.1 Estructura superior

```json
{
  "schema_version": "0.1.0",
  "project": {},
  "parameters": [],
  "model": {},
  "view_state": {}
}
```

### 13.2 Bloques principales

- `schema_version`: version del esquema serializado
- `project`: metadatos generales del proyecto
- `parameters`: coleccion global de parametros
- `model`: modelo mecanico
- `view_state`: estado visual persistente

### 13.3 Proyecto

```json
{
  "id": "proj_001",
  "name": "Example Project",
  "metadata": {
    "description": "",
    "author": "",
    "created_at": null,
    "updated_at": null
  }
}
```

### 13.4 Parametro

```json
{
  "id": "param_001",
  "name": "L1",
  "expression": "120 mm",
  "unit": "mm",
  "description": "Longitud principal"
}
```

### 13.5 ScalarProperty

```json
{
  "expression": "L1/2",
  "unit": "mm",
  "expected_dimension": "length"
}
```

### 13.6 Marker

```json
{
  "id": "marker_001",
  "name": "A",
  "type": "structural",
  "x": {
    "expression": "0 mm",
    "unit": "mm",
    "expected_dimension": "length"
  },
  "y": {
    "expression": "0 mm",
    "unit": "mm",
    "expected_dimension": "length"
  },
  "visible": true
}
```

Reglas:

- `type` podra ser al menos `structural` o `com`.
- El `CoM` se guardara como marker normal de tipo `com`.

### 13.7 Body

```json
{
  "id": "body_001",
  "name": "Crank",
  "type": "bar",
  "markers": [],
  "edge_order": ["marker_001", "marker_002"],
  "closed_shape": false,
  "mass": null,
  "inertia": null
}
```

Reglas:

- `type` podra ser al menos `bar`, `body` o `point_mass`.
- `mass` e `inertia` seran `null` cuando no esten definidos.

### 13.8 Slider

```json
{
  "id": "slider_001",
  "name": "Slider1",
  "origin_x": {
    "expression": "200 mm",
    "unit": "mm",
    "expected_dimension": "length"
  },
  "origin_y": {
    "expression": "0 mm",
    "unit": "mm",
    "expected_dimension": "length"
  },
  "angle": {
    "expression": "0 deg",
    "unit": "deg",
    "expected_dimension": "angle"
  },
  "travel_min": null,
  "travel_max": null
}
```

### 13.9 JointEndpoint y Joint

```json
{
  "kind": "marker",
  "body_id": "body_001",
  "marker_id": "marker_001"
}
```

```json
{
  "id": "joint_001",
  "name": "Ground_A",
  "type": "revolute",
  "endpoint_a": {
    "kind": "marker",
    "body_id": "body_001",
    "marker_id": "marker_001"
  },
  "endpoint_b": {
    "kind": "ground"
  }
}
```

Reglas:

- `kind` podra ser `marker`, `ground` o `slider`.
- `Joint` no almacenara posicion propia.

### 13.10 Modelo

```json
{
  "bodies": [],
  "sliders": [],
  "joints": []
}
```

### 13.11 ViewState

```json
{
  "zoom": 1.0,
  "pan_x": 0.0,
  "pan_y": 0.0,
  "show_grid": true,
  "show_markers": true,
  "show_com": false,
  "show_sliders": true
}
```

### 13.12 Vocabularios cerrados iniciales

Para evitar ambiguedades en la implementacion inicial, se fijan estos valores permitidos en V1:

- `Body.type`: `body`, `bar`, `point_mass`
- `Marker.type`: `structural`, `com`
- `Joint.type`: `revolute`, `rigid`
- `JointEndpoint.kind`: `marker`, `ground`, `slider`
- `ScalarProperty.expected_dimension`: `length`, `angle`, `mass`, `inertia`, `time`, `unitless`

## 14. API publica propuesta

La API publica debe servir tanto a la GUI como a scripts o integraciones externas.

### 14.1 Fachada principal

Se propone una fachada de alto nivel, por ejemplo `ApplicationService`.

Responsabilidades:

- crear y cargar proyectos
- ejecutar operaciones de edicion
- actualizar propiedades
- serializar
- lanzar simulaciones

La API se organizara en dos niveles:

- `core API`: pequena, generica y estable
- `convenience API`: atajos ergonomicos para GUI y scripting

### 14.2 Core API propuesta

Proyecto:

- `new_project(name: str) -> Project`
- `load_project(path: str) -> Project`
- `save_project(path: str) -> None`

Parametros:

- `create_parameter(name: str, expression: str, unit: str, description: str = "") -> str`
- `update_parameter(parameter_id: str, *, expression: str | None = None, unit: str | None = None, description: str | None = None) -> None`
- `delete_parameter(parameter_id: str) -> None`

Modelo:

- `create_body(name: str, markers: list[MarkerInput], body_type: str = "body") -> str`
- `add_marker_to_body(body_id: str, marker: MarkerInput) -> str`
- `create_slider(name: str, slider: SliderInput) -> str`
- `create_joint(name: str, joint_type: str, endpoint_a: JointEndpointInput, endpoint_b: JointEndpointInput) -> str`

Edicion:

- `rename_entity(entity_id: str, new_name: str) -> None`
- `update_property(entity_id: str, property_path: str, value) -> None`
- `delete_entity(entity_id: str) -> None`

Analisis y simulacion:

- `validate_model() -> ValidationReport`
- `run_kinematic_simulation() -> SimulationResult`

Historial:

- `undo() -> bool`
- `redo() -> bool`

### 14.3 Convenience API propuesta

Atajos recomendados sobre la `core API`:

- `create_bar(name: str, start: MarkerInput, end: MarkerInput) -> str`
- `connect_marker_to_ground(marker_id: str, joint_type: str = "revolute", name: str | None = None) -> str`
- `connect_marker_to_slider(marker_id: str, slider_id: str, joint_type: str = "revolute", name: str | None = None) -> str`

Estos metodos existen por ergonomia, pero internamente deberian delegar en operaciones mas genericas de la `core API`.

### 14.4 Tipos de entrada recomendados

Para evitar una API demasiado debil o ambigua, se recomiendan objetos de entrada explicitos:

- `MarkerInput`
- `SliderInput`
- `JointEndpointInput`

Definiciones propuestas:

`MarkerInput`

- `name: str | None`
- `x: str`
- `y: str`
- `marker_type: str = "structural"`
- `visible: bool = True`

Reglas:

- `x` e `y` se expresaran como literales, parametros o expresiones compatibles con magnitud de longitud.
- `marker_type` podra ser al menos `structural` o `com`.
- En operaciones ordinarias de creacion de geometria, el tipo esperado sera `structural`.

`SliderInput`

- `origin_x: str`
- `origin_y: str`
- `angle: str`
- `travel_min: str | None = None`
- `travel_max: str | None = None`

Reglas:

- `origin_x` y `origin_y` seran expresiones de longitud.
- `angle` sera una expresion angular.
- `travel_min` y `travel_max` podran omitirse.

`JointEndpointInput`

- `kind: str`
- `body_id: str | None = None`
- `marker_id: str | None = None`
- `slider_id: str | None = None`

Reglas:

- `kind` podra ser `marker`, `ground` o `slider`.
- Si `kind == "marker"`, se requeriran `body_id` y `marker_id`.
- Si `kind == "slider"`, se requerira `slider_id`.
- Si `kind == "ground"`, no se requeriran ids adicionales.

Tipos de apoyo recomendados:

- `PropertyValueInput`
- `RenameInput`

`PropertyValueInput` podra representar:

- valor literal
- expresion
- referencia parametrica

Y servira especialmente para `update_property(...)`.

Definicion inicial recomendada:

- `kind: str`
- `value: str | bool | None`

Valores previstos para `kind`:

- `expression`
- `boolean`
- `null`

Reglas:

- `expression` sera la forma estandar para propiedades escalares evaluables.
- `boolean` se usara para propiedades como `visible` o `closed_shape`.
- `null` se usara solo en propiedades que admitan ausencia explicita de valor, como `mass`, `inertia`, `travel_min` o `travel_max`.

Ejemplos conceptuales:

```python
MarkerInput(
    name="A",
    x="0 mm",
    y="0 mm",
    marker_type="structural"
)
```

```python
SliderInput(
    origin_x="200 mm",
    origin_y="0 mm",
    angle="0 deg",
    travel_min=None,
    travel_max=None
)
```

```python
JointEndpointInput(
    kind="marker",
    body_id="body_001",
    marker_id="marker_001"
)
```

### 14.5 Reglas de API

- La GUI no modificara entidades directamente.
- Las operaciones publicas pasaran por la capa de aplicacion.
- La API aceptara expresiones como texto en las propiedades evaluables.
- Los ids internos seran la referencia principal para operaciones programaticas.
- Se evitara exponer `dict`, `tuple` o `**changes` genericos como interfaz principal cuando existan DTOs mas claros.
- `update_property()` sera la operacion generica preferida para cambios de propiedades, evitando proliferacion de metodos demasiado especificos.

### 14.6 Operacion `update_property(...)`

Se propone como firma base:

- `update_property(entity_id: str, property_path: str, value: PropertyValueInput) -> None`

Objetivo:

- ofrecer una unica operacion generica para cambios de propiedades simples o evaluables
- reutilizar la misma API desde GUI, scripting y comandos internos

Reglas:

- `entity_id` identificara la entidad destino principal.
- `property_path` apuntara al campo concreto a modificar dentro de la entidad.
- `value` podra representar un literal, una expresion, una referencia parametrica, un booleano o `null` cuando tenga sentido.
- La operacion aplicara validacion de tipos, dimensiones y compatibilidad antes de confirmar el cambio.
- Si el cambio es invalido, la operacion devolvera error de aplicacion y no dejara el modelo en estado intermedio.

Rutas de propiedad previstas inicialmente:

- `name`
- `visible`
- `closed_shape`
- `mass`
- `inertia`
- `x`
- `y`
- `origin_x`
- `origin_y`
- `angle`
- `travel_min`
- `travel_max`

Rutas compuestas previstas:

- `style.color`
- `style.visible`
- `style.line_width`
- `style.marker_size`

Criterio de alcance:

- En V1, `update_property(...)` se orientara sobre todo a propiedades escalares o booleanas.
- Cambios estructurales como anadir markers, borrar entidades o crear joints no se resolveran con esta operacion, sino con comandos especificos.

Valores especiales:

- `mass` e `inertia` podran tomar `null` para indicar que no estan definidas.
- `travel_min` y `travel_max` podran tomar `null` para indicar recorrido no acotado.

Validaciones esperadas:

- No permitir una expresion angular en una propiedad lineal.
- No permitir un nombre repetido cuando la propiedad modificada sea `name` y exista restriccion de unicidad.
- No permitir rutas inexistentes o no editables desde la API publica.

Casos de uso recomendados:

```python
update_property(
    entity_id="marker_001",
    property_path="x",
    value=PropertyValueInput(kind="expression", value="L1/2")
)
```

```python
update_property(
    entity_id="body_001",
    property_path="closed_shape",
    value=PropertyValueInput(kind="boolean", value=True)
)
```

```python
update_property(
    entity_id="body_001",
    property_path="mass",
    value=PropertyValueInput(kind="null", value=None)
)
```

### 14.7 Tipos auxiliares recomendados

- `ValidationReport`
- `ValidationMessage`
- `SimulationResult`
- `CommandResult`

## 15. Roadmap tecnico propuesto

El roadmap se plantea por fases cortas, priorizando nucleo estable antes que interfaz rica.

### 15.1 Fase 0. Fundacion del repositorio

Objetivo:

- preparar la base del proyecto

Entregables:

- estructura de paquetes
- configuracion de entorno
- tests basicos
- convenciones de estilo y versionado

### 15.2 Fase 1. Dominio y serializacion

Objetivo:

- modelar entidades y guardado/carga JSON

Entregables:

- `Project`, `Model`, `Body`, `Marker`, `Joint`, `Slider`, `Parameter`
- `ScalarProperty`, `ViewState`, `Style`, `Metadata`
- lector y escritor JSON
- `schema_version`

### 15.3 Fase 2. Parametros, unidades y expresiones

Objetivo:

- hacer operativo el sistema parametrico

Entregables:

- parser de expresiones
- unidades y conversiones
- validacion dimensional
- evaluacion de parametros
- deteccion de errores basicos

### 15.4 Fase 3. Capa de aplicacion y comandos

Objetivo:

- encapsular toda la edicion en casos de uso

Entregables:

- comandos de creacion, edicion y borrado
- `undo/redo`
- politicas de nombres unicos
- borrado cascada controlado

### 15.5 Fase 4. Validacion y ensamblado

Objetivo:

- preparar el modelo para simulacion

Entregables:

- validacion informativa
- deteccion de joints duplicados
- comprobacion de referencias
- ensamblador intermedio de simulacion

### 15.6 Fase 5. Primer adapter de solver

Objetivo:

- ejecutar cinematica real sobre un backend

Entregables:

- interfaz base de adapter
- primer adapter funcional
- captura de errores del solver
- `SimulationResult`

### 15.7 Fase 6. GUI minima usable

Objetivo:

- exponer el nucleo mediante una GUI simple pero util

Entregables:

- canvas
- inspector
- arbol del modelo
- gestor de parametros
- timeline y controles de simulacion

### 15.8 Fase 7. Casos de validacion objetivo

Objetivo:

- verificar que la V1 ya resuelve los casos de referencia

Entregables:

- ejemplo de cuatro barras
- ejemplo de biela-manivela con corredera
- pruebas de guardado/carga
- pruebas de comandos y simulacion

### 15.9 Prioridad transversal

Durante todas las fases:

- mantener desacoplo GUI-libreria
- no introducir dependencias de solver en el dominio
- mantener JSON versionado
- escribir tests antes de ampliar alcance funcional

## 16. Decisiones tecnicas de arranque

Estas decisiones quedan fijadas para iniciar implementacion sin mas debate previo:

- Estructura de codigo bajo `src/quino/`
- Python objetivo: `3.12`
- Toolkit GUI inicial: `PySide6`
- Modelado de dominio con `dataclasses` y `Enum`
- Tipado estatico con `typing` moderno
- Tests con `pytest`
- Lint y formato con `ruff`
- Serializacion JSON mediante mapeadores propios, sin acoplar el dominio a librerias de serializacion pesadas
- El dominio no dependera de Qt ni de un solver concreto
- La primera entrega funcional de codigo puede arrancar sin GUI completa, priorizando libreria y tests

## 17. Criterios de preparacion para empezar a codificar

La especificacion se considera suficientemente cerrada para empezar a implementar si se sigue este orden:

1. Crear estructura base del paquete y toolchain.
2. Implementar entidades y value objects del dominio.
3. Implementar serializacion JSON y roundtrip de proyecto.
4. Implementar unidades, expresiones y validacion dimensional.
5. Implementar `ApplicationService` y comandos base.
6. Implementar `undo/redo`.
7. Implementar validacion informativa.
8. Implementar primer adapter de simulacion.
9. Montar GUI minima sobre la API existente.

## 18. Definition of Done del primer hito de codigo

El primer hito tecnico se considerara completado cuando existan, al menos:

- creacion de `Project` desde libreria
- guardado y carga en `.quino.json`
- creacion programatica de `Body`, `Bar`, `Marker`, `Slider` y `Joint`
- soporte basico de `Parameter` y `ScalarProperty`
- validacion dimensional minima
- `update_property(...)` operativo
- `delete_entity(...)` con borrado en cascada
- `undo/redo` en operaciones base
- tests de roundtrip JSON
- tests de nombres unicos
- tests de joints duplicados
- tests de expresiones y unidades

## 19. Asunciones cerradas para implementacion

Salvo que se reabra explicitamente una decision en el futuro, el desarrollo arrancara asumiendo:

- `CoM` como marker `com` y no como bloque separado
- `mass` e `inertia` nulos cuando no esten definidos
- `point_mass` como tipo explicito derivable de un body con un solo marker estructural
- API publica dividida en `core` y `convenience`
- `update_property(...)` como mecanismo generico de actualizacion
- persistencia de `view_state` en el mismo archivo de proyecto
