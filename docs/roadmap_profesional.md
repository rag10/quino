# QUINO — Roadmap hacia Software Profesional de Simulación 2D Cinemática y Dinámica

> **Versión:** 1.0-draft  
> **Fecha:** 2026-05-09  
> **Estado:** Propuesta estratégica para revisión  
> **Alcance:** Transformar QUINO desde su estado actual (V1 Beta / sketch-foundation) en una plataforma de ingeniería profesional comparable a ASOM v10, SAM 8.5, GIM, Working Model 2D o Linkage.

---

## Tabla de contenidos

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Diagnóstico del estado actual (Baseline V1)](#2-diagnóstico-del-estado-actual-baseline-v1)
3. [Benchmark competitivo](#3-benchmark-competitivo)
4. [Análisis de brechas (GAP Analysis)](#4-análisis-de-brechas-gap-analysis)
5. [Visión estratégica y principios de evolución](#5-visión-estratégica-y-principios-de-evolución)
6. [Roadmap por versiones](#6-roadmap-por-versiones)
7. [Plan técnico detallado por áreas](#7-plan-técnico-detallado-por-áreas)
8. [Arquitectura evolutiva](#8-arquitectura-evolutiva)
9. [Métricas de éxito y milestones](#9-métricas-de-éxito-y-milestones)
10. [Riesgos y mitigaciones](#10-riesgos-y-mitigaciones)
11. [Apéndice A — Tabla comparativa con competidores](#apéndice-a--tabla-comparativa-con-competidores)
12. [Apéndice B — Glosario de términos del roadmap](#apéndice-b--glosario-de-términos-del-roadmap)

---

## 1. Resumen ejecutivo

QUINO ha alcanzado en su V1 una base técnica sólida: arquitectura `library-first`, dominio puro desacoplado de Qt, sistema paramétrico con unidades, sketch con 15 constraints, GUI en PySide6 con canvas interactivo, viewer de sensores con pyqtgraph, y un primer adapter dinámico vía Exudyn. Los tests cubren ~70 casos y el formato `.quino.json` es versionado y estable.

Sin embargo, la distancia hasta un producto profesional de simulación 2D es considerable. Los competidores maduros ofrecen:

- **Análisis cinemático puro** (solver propio, tiempo real, sin necesidad de dinámica).
- **Análisis de fuerzas y kinetostática** (reacciones en juntas, esfuerzos internos, fricción).
- **Elementos avanzados** (engranajes, correas, resortes, amortiguadores, levas, curvas guía).
- **Síntesis de mecanismos** (generación de función, trayectoria, guiado de cuerpo rígido).
- **Optimización paramétrica** (algoritmos evolutivos + Simplex).
- **Import/export CAD** (DXF/DWG bidireccional).
- **Post-procesamiento profesional** (tablas, gráficos XY múltiples, exportación a Excel/CSV, hodógrafos, reportes).
- **Animación interactiva** (drag manual en cualquier fase, previews de posiciones intermedias, sombras).

Este documento propone un roadmap estructurado en **cuatro grandes versiones** (V2 Profesional, V3 Avanzado, V4 Experto, V5 Industrial) con un horizonte de 18–36 meses, priorizando siempre la estabilidad de la arquitectura existente y la calidad sobre la velocidad de entrega.

---

## 2. Diagnóstico del estado actual (Baseline V1)

### 2.1 Arquitectura y capas

| Capa | Estado | Observaciones |
|------|--------|---------------|
| `domain/` | ✅ Matura | Entidades `slots=True`, `ScalarProperty`, `Project`, `Sketch`, `SimulationResult` |
| `application/` | ✅ Matura | `ApplicationService` (~2300 líneas), undo/redo vía `copy.deepcopy` |
| `services/` | ✅ Matura | `ExpressionService` (AST), `UnitService`, `SketchSolver` (Gauss-Seidel, 15 constraints), `ValidationService` |
| `serialization/` | ✅ Matura | `JsonMapper`, `schema_version="0.1.0"`, roundtrip testeado |
| `simulation/` | ✅ Operativo | `MechanismAssembler`, `SimulationRunner` |
| `solver_adapters/` | ⚠️ Básico | Únicamente `ExudynAdapter`. Sin adapter de cinemática pura. |
| `gui/` | ⚠️ Funcional | PySide6, canvas interactivo, inspector, árbol, toolbar, playback (~4800 líneas en canvas + main_window) |
| `viewer/` | ✅ Refactorizado | `PlotWindow`, `SensorPlotWidget`, crosshair, CSV import, paleta Tableau-10 |
| `tests/` | ✅ Cobertura media | ~70 tests: dominio, GUI offscreen, simulación, roundtrip |

### 2.2 Capacidades implementadas

**Modelado:**
- `Body` (barra, cuerpo poligonal, masa puntual).
- `Marker` (estructural, CoM).
- `Joint` revolute, rigid.
- `Slider` con travel min/max.
- `Driver` rotación y traslación (ley vs tiempo).
- `Sensor` point, distance, angle (horizontal, vertical, vector).
- `Parameter` globales con expresiones y unidades.
- `Sketch` con 5 entidades geométricas y 15 constraints.

**Simulación:**
- Dinámica completa vía Exudyn (rígidos 2D, joints, constraints, integración temporal).
- Post-proceso de velocidades/aceleraciones por diferencias finitas.
- Timeline con playback 25 fps.

**GUI:**
- Canvas 2D con pan, zoom, selección, drag de markers y sketch points.
- Tree view jerárquico con iconos SVG.
- Inspector editable con expresiones.
- Gestor de parámetros.
- Validación informativa (gaps, slider reach, loop reach).

### 2.3 Deuda técnica y limitaciones críticas actuales

1. **No existe solver de cinemática pura.** Toda simulación pasa por dinámica (Exudyn). Esto es lento para exploración conceptual y no permite análisis de grados de libertad ni detección de singularidades cinemáticas.
2. **No hay análisis de fuerzas.** Sin kinetostática ni reacciones en juntas.
3. **No hay elementos de transmisión.** Sin engranajes, correas, levas, resortes, amortiguadores ni fricción.
4. **No hay síntesis.** El usuario debe modelar manualmente; no hay wizards de síntesis de cuatro barras, generación de función, etc.
5. **Sketch y modelo están desconectados.** El sketch resuelve constraints en t=0 pero no hay flujo bidireccional modelo ↔ sketch.
6. **No hay import/export CAD.** Sin DXF, sin interoperabilidad con SolidWorks, AutoCAD, etc.
7. **Undo/redo es memoria-ineficiente.** `copy.deepcopy` del proyecto completo en cada operación escalará mal.
8. **No hay scripting ni API de automatización.** Solo se puede usar via Python importando la librería; no hay consola de script, ni macros, ni bindings C++.
9. **El solver de sketch es Gauss-Seidel puro.** Funciona para constraints simples pero puede divergir en configuraciones sobrerrestrictas o con múltiples soluciones.
10. **No hay análisis de estabilidad ni de DoF.** El usuario no puede saber cuántos grados de libertad tiene su mecanismo antes de simular.

---

## 3. Benchmark competitivo

### 3.1 ASOM v10 (info-key / ASOM Kinematik-Software)

**Fortalezas:**
- UI paramétrica con constraints en tiempo real.
- Visualizadores: trayectorias, centro instantáneo de rotación, sombras de posiciones intermedias, vectores de fuerza en juntas.
- Síntesis: síntesis de carga de retención, síntesis de almacenamiento de energía (muelles de gas).
- Fricción en juntas y contactos (inclinados, levas).
- Export DXF completo.
- Comparación de escenarios de carga alternativos en el mismo proyecto/diagrama.
- Playback con ciclos cerrados y cámara móvil relativa.

**Debilidades:** Licencia de pago, cerrado, sin API de scripting visible.

### 3.2 SAM 8.5 (ARTAS Engineering)

**Fortalezas:**
- Solver basado en elementos finitos para mecanismos (formulación general, lazos abiertos/cerrados, trenes planetarios).
- Librería de elementos: beam, slider, gear, belt, rack-and-pinion, spring, damper, friction (translacional y rotacional), non-linear spring, curved slider.
- Múltiples actuadores simultáneos con perfiles estándar (constante, polinomial, cíclica, splines cúbicos) o desde archivo ASCII.
- Kinetostática completa: torque de accionamiento, fuerzas de reacción, fuerzas internas, potencia.
- Post-proceso: tablas, gráficos XY ilimitados con doble escala, hodógrafos de velocidad, centrodes fijos/móviles, evolutas, documentación ASCII automática.
- Optimización: evolutivo + Simplex para geometría, función o trayectoria.
- Wizards: síntesis de 4 barras, generación de función angular, guía lineal exacta.
- CAD Interface: DXF import/export.
- Colisiones durante animación.

**Debilidades:** Licencia de pago, arquitectura monolítica tradicional, sin API Python moderna.

### 3.3 GIM (UPV/EHU — educational)

**Fortalezas:**
- Módulo de cinemática general (n-GDL plano) con coordenadas naturales.
- Visualización de entidades cinemáticas avanzadas: ICR, polodas fijas/móviles, círculo de inflexión, círculo de retorno, círculo de Bresse, hodógrafo, envolvente de línea.
- Descomposición de aceleraciones (tangencial, normal, de Coriolis, de arrastre).
- Módulo de dinámica directa e inversa (kinetostática) con cargas puntuales y distribuidas.
- Módulo de síntesis de cuatro barras (path generation, rigid body guiding, function generation) con 3–5 precision points en tiempo real.
- Diagramas de esfuerzos internos en barras.
- Mapas de color de esfuerzos en el sistema completo.

**Debilidades:** Uso restringido a educación, GUI anticuada (Java/Swing), sin exportación profesional, sin optimización paramétrica general.

### 3.4 Working Model 2D v10 (Design Simulation Technologies)

**Fortalezas:**
- Simulación física en tiempo real (no solo cinemática).
- Co-simulación con MATLAB/Simulink, Excel, Python (API COM/Python nueva en v10).
- Asistente de IA para construcción por lenguaje natural + MCP.
- Import de geometría desde CAD.
- Gráficos y displays digitales integrados, lenguaje de ecuaciones propio.
- Ideal para sistemas de control mecatrónicos.

**Debilidades:** Enfocado a dinámica general, no a síntesis de mecanismos ni a análisis cinemático puro optimizado.

### 3.5 Linkage 3.16 (David Rector)

**Fortalezas:**
- Gratuito, interfaz modeless (sin selección de herramienta).
- Cadenas, engranajes, splines (cams), curvas guía deslizantes.
- Dimensionado automático en mm/pulgadas.
- Export a video HD, imágenes JPEG/PNG, DXF.
- Trayectorias de puntos, dibujo durante simulación.
- Snap a grid y objetos.

**Debilidades:** Sin análisis de fuerzas, sin optimización, sin síntesis, sin scripting.

---

## 4. Análisis de brechas (GAP Analysis)

| Capacidad | QUINO V1 | ASOM | SAM | GIM | Working Model | Linkage | Prioridad |
|-----------|----------|------|-----|-----|---------------|---------|-----------|
| Cinemática pura (solver propio) | ❌ | ✅ | ✅ | ✅ | ⚠️ | ✅ | **Crítica** |
| Análisis de DoF / redundancias | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | **Crítica** |
| Kinetostática / fuerzas juntas | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | **Alta** |
| Engranajes | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | Alta |
| Correas / cadenas | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | Media |
| Resortes / amortiguadores | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ | Alta |
| Fricción (juntas y contacto) | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ | Media |
| Levas / seguidores | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | Media |
| Síntesis de mecanismos | ❌ | ✅ | ✅ | ✅ (4-bar) | ❌ | ❌ | Alta |
| Optimización paramétrica | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | Media |
| DXF Import/Export | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | Alta |
| Scripting / API externa | ⚠️* | ❌ | ❌ | ❌ | ✅ | ❌ | Media |
| Análisis de estabilidad / singularidades | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | Media |
| Visualización avanzada (ICR, polodas, hodógrafos) | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | Baja-Media |
| Co-simulación / bindings externos | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | Baja |
| Reportes / documentación automática | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | Baja |

\* Solo vía importación de librería Python; no hay consola de script ni macros en GUI.

---

## 5. Visión estratégica y principios de evolución

### 5.1 Visión a 3 años

> **QUINO será la plataforma de referencia open-source para el diseño, análisis, síntesis y optimización de mecanismos planares, utilizada por ingenieros de diseño, docentes universitarios y estudiantes de ingeniería mecánica.**

### 5.2 Principios rectores

1. **Library-first, siempre.** La GUI es una capa opcional. Todo nuevo capability debe ser usable desde Python puro.
2. **Solver-agnostic.** El dominio nunca dependerá de un backend concreto. Se mantendrá el patrón `SolverAdapter`.
3. **Parametrización de primera clase.** Cada propiedad geométrica, física o de control debe ser expresión evaluable.
4. **JSON versionado e inmutable en pasado.** Cada versión del schema debe migrar desde versiones anteriores sin pérdida.
5. **Tests antes de features.** Cada nueva capacidad requiere tests de dominio antes de GUI.
6. **Performance progresiva.** El solver de cinemática pura debe permitir interacción en tiempo real (< 16 ms por frame) para mecanismos de hasta 50 cuerpos.
7. **Interoperabilidad.** DXF import/export es requisito para cualquier versión profesional.
8. **Accesibilidad educativa.** Mantener una curva de aprendizaje baja: wizards, ejemplos incluidos, documentación visual.

### 5.3 Decisiones arquitectónicas clave a largo plazo

- **Solver de cinemática propio:** Implementar un solver de posición basado en coordenadas naturales (Natural Coordinates) o en formulación de elementos finitos planos, resolviendo el problema de posición por Newton-Raphson con Jacobiano simbólico o numérico. Esto permitirá análisis de DoF, detección de singularidades y simulación pura en tiempo real.
- **Solver de dinámica dual:** Mantener Exudyn como backend de dinámica general, pero añadir un solver de kinetostática propio para cálculo de reacciones sin integración temporal.
- **ExpressionService evolutivo:** Migrar de AST de Python a una representación simbólica propia (o SymPy ligero) para permitir derivación automática (Jacobiano, sensibilidades para optimización).
- **Undo/redo eficiente:** Reemplazar `copy.deepcopy` por un sistema de patches o comandos invertibles (Command Pattern completo).
- **Canvas acelerado:** Evaluar migración parcial a `QGraphicsView` + aceleración por GPU, o mantener `QPainter` con técnicas de cacheo agresivo.

---

## 6. Roadmap por versiones

### 6.1 V2 — Profesional (Cinemática pura + Kinetostática + Elementos básicos)
*Horizonte estimado: 6–9 meses*

**Objetivo:** Convertir QUINO en una herramienta de análisis cinemático y kinetostático completo, comparable a la mitad inferior de SAM o a GIM en cinemática.

#### 6.1.1 Solver de cinemática pura (Core)
- [ ] **SC1. Solver de posición propio** basado en coordenadas naturales o loop-closure vectorial.
  - Newton-Raphson espacial con tolerancia configurable.
  - Detección de convergencia, divergencia y singularidades (condición del Jacobiano).
  - Análisis de grados de libertad (DoF) por fórmula de Gruebler y por rango del Jacobiano.
  - Detección de redundancias y bloqueos.
- [ ] **SC2. Simulación cinemática pura** sin integración dinámica.
  - Avance por pasos temporales resolviendo solo posición (velocidad/aceleración por derivación numérica o resolución de sistemas lineales Jacobiano·q̇ = -f_t).
  - Modo "exploración manual": arrastrar un eslabón y ver el mecanismo seguir en tiempo real (drag-and-solve).
- [ ] **SC3. Modo híbrido cinemática/dinámica** seleccionable por el usuario.

#### 6.1.2 Análisis de fuerzas (Kinetostática)
- [ ] **KF1. Cálculo de reacciones en juntas** para mecanismos con movimiento prescrito.
- [ ] **KF2. Fuerzas de inercia** automáticas a partir de masas e inercias.
- [ ] **KF3. Cargas externas** puntuales (fuerzas y torques) aplicables a markers y bodies.
- [ ] **KF4. Diagramas de esfuerzos internos** en barras (axial, cortante, flector).
- [ ] **KF5. Sensores de fuerza/torque** en juntas y entre markers.

#### 6.1.3 Nuevos elementos mecánicos
- [ ] **NE1. Spring** (lineal entre dos markers, con k, longitud libre, amortiguamiento c).
- [ ] **NE2. Damper** (lineal entre dos markers, con c).
- [ ] **NE3. Torsional spring/damper** en juntas revolute.
- [ ] **NE4. Fricción básica** en juntas revolute y sliders (Coulomb + viscoso).

#### 6.1.4 Mejoras de GUI/UX
- [ ] **GU1. Modo de exploración manual** (arrastrar un body y resolver cinemática en tiempo real).
- [ ] **GU2. Visualización de velocidades y aceleraciones** como vectores en el canvas.
- [ ] **GU3. Trayectorias persistentes** (rastro de puntos durante animación).
- [ ] **GU4. Panel de DoF y redundancias** visible tras validación.
- [ ] **GU5. Mejora de undo/redo** (Command Pattern con patches, no deepcopy).

#### 6.1.5 Interoperabilidad
- [ ] **IO1. Export DXF** de la geometría del mecanismo en posición actual (y por frames de animación).

---

### 6.2 V3 — Avanzado (Transmisiones + Síntesis + Post-proceso profesional)
*Horizonte estimado: 9–12 meses adicionales (total ~15–21 meses)*

**Objetivo:** Añadir elementos de transmisión, síntesis clásica de mecanismos y un post-proceso comparable al de SAM.

#### 6.2.1 Transmisiones
- [ ] **TR1. Gear pair** (engranajes circulares externos/internos, con ratio definido por diámetros/dientes).
- [ ] **TR2. Rack-and-pinion** (cremallera-piñón).
- [ ] **TR3. Belt / chain** (transmisión por correa/cadena con relación fija, opcionalmente con deslizamiento).
- [ ] **TR4. Cam-follower** (leva con perfil spline o poligonal y seguidor plano/rodillo).
- [ ] **TR5. Curved slider** (deslizamiento sobre spline).

#### 6.2.2 Síntesis de mecanismos
- [ ] **SY1. Síntesis de cuatro barras**:
  - Generación de función (3 precision points).
  - Guiado de cuerpo rígido (3 poses).
  - Generación de trayectoria (3–4 precision points).
- [ ] **SY2. Síntesis de biela-manivela-corredera** (optimización de carrera, tiempo de retorno).
- [ ] **SY3. Chequeo de Grashof** y clasificación automática de cuatro barras.
- [ ] **SY4. Visualización de soluciones múltiples** (rama abierta/cerrada, cognados).

#### 6.2.3 Post-procesamiento avanzado
- [ ] **PP1. Gráficos XY múltiples** con doble eje Y (escalas independientes).
- [ ] **PP2. Tabla de resultados** tipo hoja de cálculo integrada.
- [ ] **PP3. Hodógrafo de velocidad** de cualquier punto.
- [ ] **PP4. Centrodes fijas y móviles** (ICR a lo largo del tiempo).
- [ ] **PP5. Exportación a Excel** (.xlsx) y MATLAB (.mat).
- [ ] **PP6. Reporte ASCII automático** del proyecto con tabla de resultados.

#### 6.2.4 Import/Export CAD
- [ ] **CAD1. Import DXF** (líneas, círculos, arcos → sketch o modelo).
- [ ] **CAD2. Export DXF animado** (capas por frame).

#### 6.2.5 Sketch evolucionado
- [ ] **SK1. Bidireccionalidad modelo-sketch** (modificar sketch actualiza modelo en t=0; modificar modelo actualiza sketch).
- [ ] **SK2. Constraints de modelo** (longitud de barra, ángulo entre barras) como constraints del sketch.
- [ ] **SK3. Solver de sketch mejorado** (gradient-based o least-squares para robustez en sobrerrestricciones).

---

### 6.3 V4 — Experto (Optimización + Dinámica avanzada + Scripting)
*Horizonte estimado: 9–12 meses adicionales (total ~24–33 meses)*

**Objetivo:** Añadir optimización paramétrica, dinámica con contactos, y una capa de scripting/automatización.

#### 6.3.1 Optimización
- [ ] **OP1. Optimización de trayectoria** (minimizar desviación respecto a trayectoria objetivo).
- [ ] **OP2. Optimización de función** (minimizar error entre ley de salida deseada y obtenida).
- [ ] **OP3. Optimización de fuerza/torque** (minimizar pico de torque de accionamiento).
- [ ] **OP4. Algoritmos**: Simplex + evolutivo (diferential evolution o CMA-ES).
- [ ] **OP5. Variables de diseño**: cualquier parámetro geométrico (longitudes, ángulos, posiciones).
- [ ] **OP6. Constraints de diseño**: Grashof, límites de espacio, evitación de colisiones.

#### 6.3.2 Dinámica avanzada
- [ ] **DA1. Contacto 2D** (colisión entre cuerpos poligonales, restitución, fricción de contacto).
- [ ] **DA2. Perfiles de movimiento avanzados** (polinomios 3-4-5, cicloidal, splines definidos por puntos).
- [ ] **DA3. Múltiples actuadores** con leyes independientes.
- [ ] **DA4. Backlash** en engranajes y juntas.

#### 6.3.3 Scripting y automatización
- [ ] **SC1. Consola Python integrada** en la GUI (REPL).
- [ ] **SC2. Macros por grabación** de operaciones de GUI.
- [ ] **SC3. API de scripting documentada** con ejemplos ("Build a slider-crank with L=100mm").
- [ ] **SC4. Batch simulation** (variar parámetro y generar familia de curvas).

#### 6.3.4 Visualización cinemática avanzada
- [ ] **VI1. Centro instantáneo de rotación (ICR)** visual.
- [ ] **VI2. Círculo de inflexión, círculo de retorno, círculo de Bresse**.
- [ ] **VI3. Aceleración de Coriolis** visual en sliders.
- [ ] **VI4. Sombras / previews** de posiciones intermedias sin simular completo.

---

### 6.4 V5 — Industrial (Co-simulación + Multiphysics + Productización)
*Horizonte estimado: 12–18 meses adicionales (total ~36–48 meses)*

**Objetivo:** Transformar QUINO en una plataforma industrial con capacidades de co-simulación, multiphysics ligero y despliegue profesional.

#### 6.4.1 Co-simulación e interfaces
- [ ] **CS1. API C/C++** del core (vía pybind11 o cffi) para integración en otros software.
- [ ] **CS2. Co-simulación con Python/NumPy** en tiempo real (externo puede leer estados y enviar fuerzas).
- [ ] **CS3. Export a Modelica/FMU** (Functional Mock-up Unit) para integración en plataformas SysML.

#### 6.4.2 Multiphysics ligero
- [ ] **MP1. Acoplamiento hidráulico simple** (cilindro con presión y caudal como actuator).
- [ ] **MP2. Acoplamiento electromecánico simple** (motor DC con par proporcional a corriente).

#### 6.4.3 Productización
- [ ] **PR1. Empaquetado con instalador** (Windows .msi / .exe, macOS .dmg, Linux AppImage).
- [ ] **PR2. Actualizaciones automáticas** (sparkle, electron-updater equivalente).
- [ ] **PR3. Documentación online** (MkDocs o Docusaurus) con tutoriales interactivos.
- [ ] **PR4. Galería de ejemplos** (30+ mecanismos clásicos: Watt, Chebyshev, Klann, Jansen, etc.).
- [ ] **PR5. Licenciamiento dual** (open-source core + plugins/comercialización opcional).

---

## 7. Plan técnico detallado por áreas

### 7.1 Solver y motores de simulación

#### 7.1.1 Solver de cinemática pura (V2)

**Opciones de diseño:**

| Opción | Pros | Contras | Recomendación |
|--------|------|---------|---------------|
| **A. Loop-closure vectorial + Newton-Raphson** | Simple, rápido para lazos cerrados, fácil de derivar Jacobiano. | Difícil generalizar a estructuras abiertas complejas. | **Base inicial** para 4-bars, sliders, etc. |
| **B. Natural Coordinates (coordenadas naturales)** | General, automático, Jacobiano sparse, usado en GIM y muchos solvers académicos. | Más incógnitas, requiere solver sparse eficiente. | **Estrategia final** para generalidad. |
| **C. Formulación FE de SAM** | Muy general, lazos abiertos/cerrados/planetarios iguales. | Complejo de implementar, requiere mucha teoría. | Evaluar en V3 si A/B no cubren planetarios. |

**Propuesta de implementación V2:**
1. Implementar **B (Natural Coordinates)** como solver principal de cinemática.
   - Nodos = puntos del plano (x, y).
   - Elementos = barras (constraint de distancia), juntas revolute (compartir nodo), sliders (constraint de ángulo + distancia a línea).
   - Sistema: posición (NR), velocidad (resolver lineal), aceleración (resolver lineal).
2. Mantener **ExudynAdapter** para dinámica.
3. Crear `KinematicAdapter` (ABC) con implementaciones `NaturalCoordinateSolver`.

**API objetivo:**
```python
class KinematicAdapter(SolverAdapter):
    def solve_position(self, mechanism: AssembledMechanism) -> PositionResult: ...
    def solve_velocity(self, mechanism: AssembledMechanism, q_dot_input: dict) -> VelocityResult: ...
    def solve_acceleration(self, mechanism: AssembledMechanism, q_ddot_input: dict) -> AccelerationResult: ...
    def compute_dofs(self, mechanism: AssembledMechanism) -> DOFAnalysis: ...
```

#### 7.1.2 Solver de kinetostática (V2)

Para mecanismos con movimiento prescrito (todos los actuadores definidos), resolver:
- Ecuaciones de equilibrio dinámico (fuerzas de inercia + externas = reacciones).
- Usar el Jacobiano del solver de posición para proyectar fuerzas.
- Implementar como `KinetostaticAdapter`.

#### 7.1.3 Dinámica avanzada (V4)

- Contacto 2D con detección de colisión GJK/EPA para polígonos.
- Fricción de Coulomb con modelo de regularización (evitar discontinuidades para integradores).

### 7.2 Elementos mecánicos

#### 7.2.1 Resortes y amortiguadores

**Dominio:**
```python
@dataclass(slots=True)
class Spring:
    id: str
    name: str
    marker_a_id: str
    marker_b_id: str
    stiffness: ScalarProperty  # N/m
    free_length: ScalarProperty  # mm or m
    damping: ScalarProperty | None  # N·s/m
```

**Ensamblado:** Traducir a `ObjectConnectorCoordinateSpringDamper` en Exudyn (ya usado para drivers de translación) o a fuerzas directas en solver cinemático/kinetostático.

#### 7.2.2 Engranajes

**Modelo conceptual:**
- `GearPair`: referencia a dos `Joint` revolute (o a dos `Body` con markers de rotación), ratio = -R2/R1.
- Constraint: θ₂ = ratio · θ₁ + offset.
- Implementar como constraint adicional en el solver de cinemática.

#### 7.2.3 Levas

- Perfil definido como `Spline2D` (lista de puntos + interpolación cúbica) o `CamProfile` (función de elevación vs ángulo).
- Seguidor: flat o roller (radio del rodillo).
- Contacto: resolver intersección perfil-círculo del rodillo en cada paso.

### 7.3 Síntesis de mecanismos

#### 7.3.1 Síntesis de cuatro barras

**Matemáticas:**
- **Path generation:** Sistema de ecuaciones de loop closure evaluado en precision points. Resolver por NR con variables = longitudes de eslabones y ángulos de montaje.
- **Rigid body guiding:** Mismo loop closure pero con condiciones de pose (posición + orientación).
- **Function generation:** Relación entrada-salida prescrita.

**UX:**
- Wizard: diálogo paso a paso.
- Canvas interactivo: arrastrar precision points y ver soluciones actualizarse en tiempo real (como GIM).
- Mostrar todas las ramas de solución (open/close branch).
- Chequeo de order error y branch error.

### 7.4 Optimización

**Arquitectura:**
```python
@dataclass
class OptimizationProblem:
    variables: list[str]  # parameter_ids
    objective: ObjectiveType  # PATH_ERROR, FUNCTION_ERROR, MIN_MAX_TORQUE
    target: SimulationResult | TrajectoryTarget
    constraints: list[DesignConstraint]

class Optimizer(ABC):
    def solve(self, problem: OptimizationProblem, project: Project) -> OptimizationResult: ...
```

**Algoritmos:**
1. Nelder-Mead (Simplex) para problemas pequeños (< 10 variables).
2. Differential Evolution (scipy.optimize.differential_evolution) para problemas globales.
3. Evaluar CMA-ES para problemas > 20 variables.

**Performance:** Cada evaluación requiere una simulación completa. Para mecanismos simples y 50–100 evaluaciones, es aceptable. Para > 1000 evaluaciones, considerar paralelización con `multiprocessing`.

### 7.5 GUI/UX

#### 7.5.1 Canvas evolutivo

- **Modo de exploración:** Al arrastrar un body, resolver cinemática pura en tiempo real (sin integración temporal). Esto requiere que el solver de posición sea < 5 ms para mecanismos medianos.
- **Vectores cinemáticos:** Opciones de visualización (velocidad, aceleración, fuerzas) con escalado automático.
- **Trayectorias:** Almacenar trayectoria de un marker durante la animación; opción de mostrarla como spline poligonal o suavizada.
- **Sombras:** Posiciones intermedias del mecanismo en gris semitransparente para visualizar el recorrido completo sin animar.

#### 7.5.2 Inspector y árbol

- **Filtros de visibilidad** por tipo (bodies, joints, sensors, etc.).
- **Búsqueda rápida** (Ctrl+F) por nombre o ID.
- **Templates de propiedades** (guardar conjunto de propiedades como preset).

#### 7.5.3 Gestión de proyectos

- **Múltiples escenarios** dentro del mismo proyecto (como ASOM): comparar variantes de carga/geometry.
- **Versionado interno** del proyecto (snapshot manual con nombre y descripción).

### 7.6 Post-procesamiento

#### 7.6.1 Gráficos profesionales

- **Múltiples ejes Y:** Permitir escalas independientes (izquierda/derecha).
- **Operaciones matemáticas:** Sumar, restar, multiplicar, derivar, integrar canales.
- **Marcadores:** Peak detection, zero-crossing, valores en tiempo específico.

#### 7.6.2 Tablas

- Vista de tabla con todas las variables del sistema en cada frame.
- Filtrado y ordenación.

#### 7.6.3 Exportación

- CSV/TSV (ya existe).
- Excel (.xlsx) vía openpyxl.
- MATLAB (.mat) vía scipy.io.savemat.
- Imágenes de gráficos (PNG/SVG).

### 7.7 Interoperabilidad

#### 7.7.1 DXF

**Import:**
- Leer ENTITIES (LINE, CIRCLE, ARC, LWPOLYLINE, SPLINE).
- Mapear a `Sketch` (recomendado) o directamente a `Body` (si son cierres simples).
- Detectar unidades del DXF (INSUNITS) y convertir.

**Export:**
- Generar DXF con capas: bodies, joints, markers, trajectories.
- Opción de exportar un frame o todos los frames (capas numeradas).

#### 7.7.2 API externa

- **HTTP REST** (opcional, para integración web): Flask/FastAPI ligero que exponga `ApplicationService`.
- **ZeroMQ** para co-simulación en tiempo real (más eficiente que HTTP).

### 7.8 Testing y calidad

#### 7.8.1 Tests de regresión del solver

- Crear suite de mecanismos de referencia (Four-bar, Slider-crank, Stephenson, Watt, etc.) con soluciones analíticas conocidas o validadas contra SAM/GIM.
- Comparar posición, velocidad, aceleración y reacciones frame a frame con tolerancia.

#### 7.8.2 Tests de rendimiento

- Benchmark: tiempo de resolución de posición para mecanismos de 5, 10, 20, 50 cuerpos.
- Objetivo V2: < 5 ms para 10 cuerpos; < 20 ms para 50 cuerpos.

#### 7.8.3 Tests de integración GUI

- Ampliar `test_gui.py` para cubrir wizards, import DXF, optimización, y análisis de fuerzas.

---

## 8. Arquitectura evolutiva

### 8.1 Cambios estructurales propuestos

```text
quino/
  domain/                 # Sin cambios conceptuales; añadir entidades nuevas
  application/            # ApplicationService crece; evaluar división en sub-servicios
  services/
    expressions.py        # Evolucionar a soporte de derivación simbólica
    sketch_solver.py      # Mejorar a least-squares / sparse solver
    units.py              # Sin cambios mayores
    ids.py                # Sin cambios mayores
    validation.py         # Añadir validación de DoF, colisiones, singularidades
    kinematics.py         # ← NUEVO: solver de cinemática pura
    kinetostatics.py      # ← NUEVO: análisis de fuerzas
    optimization.py       # ← NUEVO: motor de optimización
  simulation/
    assembler.py          # Añadir ensamblado de springs, gears, cams
    runner.py             # Soportar selección de solver (kinematic vs dynamic)
  solver_adapters/
    base.py               # Extender con métodos de fuerza/reacción
    exudyn_adapter.py     # Añadir springs, dampers, contactos
    natural_coordinate_solver.py  # ← NUEVO
  gui/
    canvas.py             # Modos de exploración, vectores, trayectorias
    main_window.py        # Wizards, escenarios múltiples
    wizards/              # ← NUEVO: síntesis de 4-bar, etc.
    scripting/            # ← NUEVO: consola Python, macros
  viewer/
    # Extender con tabla, múltiples ejes Y, operaciones matemáticas
  io/
    dxf_io.py             # ← NUEVO: import/export DXF
    excel_exporter.py     # ← NUEVO
    mat_exporter.py       # ← NUEVO
```

### 8.2 Migración del schema JSON

Cada versión mayor requiere `schema_version` bump y un migrador:

```python
# serialization/migrations.py
MIGRATIONS = {
    "0.1.0": "0.2.0",  # V2: añade springs, forces, gear_pairs, cam_profiles
    "0.2.0": "0.3.0",  # V3: añade synthesis_results, optimization_configs
    "0.3.0": "0.4.0",  # V4: añade scripting_macros, contact_configs
}
```

### 8.3 Performance

- **Sparse matrices:** Usar `scipy.sparse` para el solver de coordenadas naturales.
- **NumPy vectorizado:** Post-proceso de sensores ya usa numpy; mantener.
- **Caché del evaluador de expresiones:** El `ExpressionService` actual parsea AST en cada evaluación. Añadir cacheo de AST compilado por expresión.
- **Lazy evaluation del sketch:** Solo re-resolver sketch cuando cambian constraints o puntos bloqueados.

---

## 9. Métricas de éxito y milestones

### 9.1 Métricas técnicas

| Métrica | V1 actual | V2 objetivo | V3 objetivo | V4 objetivo |
|---------|-----------|-------------|-------------|-------------|
| Cobertura de tests | ~70 | > 150 | > 250 | > 400 |
| Tiempo solver posición (10 cuerpos) | N/A (dinámica) | < 5 ms | < 3 ms | < 2 ms |
| Tiempo solver posición (50 cuerpos) | N/A | < 20 ms | < 15 ms | < 10 ms |
| Tipos de joint/elemento | 4 | 10 | 18 | 25 |
| Formatos de import/export | 1 (JSON) | 2 (+DXF) | 4 (+XLSX, MAT) | 5 (+FMU) |
| Wizards de síntesis | 0 | 0 | 3 | 5 |
| Algoritmos de optimización | 0 | 0 | 0 | 2 |

### 9.2 Milestones de producto

| Fecha (relativa) | Milestone |
|------------------|-----------|
| +3 meses | Solver de cinemática pura operativo con 4-bar y slider-crank. DoF analysis. |
| +6 meses | Kinetostática + resortes/amortiguadores/fricción. Export DXF. |
| +9 meses | Release V2 "Profesional". |
| +12 meses | Engranajes, correas, levas. Síntesis de 4-bar. Import DXF. |
| +15 meses | Release V3 "Avanzado". |
| +21 meses | Optimización paramétrica. Contacto 2D. Scripting. |
| +24 meses | Release V4 "Experto". |
| +30 meses | Co-simulación. Multiphysics ligero. Empaquetado multiplataforma. |
| +36 meses | Release V5 "Industrial". |

---

## 10. Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| **Implementar solver de cinemática pura es más complejo de lo previsto** | Alta | Alto | Empezar con loop-closure vectorial (más simple) antes de natural coordinates. Usar GIM como referencia de implementación. |
| **Exudyn no escala o tiene breaking changes** | Media | Alto | Mantener adapter aislado. Evaluar Chrono::Engine como alternativa. |
| **GUI se vuelve monolítica e inmantenible** | Media | Alto | Refactor progresivo: extraer `SceneGraph`, `ToolController`, `InteractionMode`. |
| **Falta de tiempo/recursos para todas las versiones** | Alta | Medio | Priorizar V2 como MVP profesional; posponer V4/V5 si es necesario. |
| **Competidores open-source aparecen** | Baja | Medio | Diferenciación por UX, síntesis en tiempo real, y arquitectura Python extensible. |
| **Performance del solver en Python puro es insuficiente** | Media | Alto | Usar NumPy/SciPy vectorizado. Si es necesario, implementar hot-path en Cython o Rust con pyo3. |

---

## Apéndice A — Tabla comparativa con competidores

| Característica | QUINO V1 | QUINO V2 (prop.) | QUINO V3 (prop.) | SAM 8.5 | ASOM v10 | GIM | Working Model 2D | Linkage 3.16 |
|----------------|----------|------------------|------------------|---------|----------|-----|------------------|--------------|
| **Open Source** | ✅ | ✅ | ✅ | ❌ | ❌ | ❌* | ❌ | ✅ |
| **Precio** | Gratis | Gratis | Gratis | Pago | Pago | Gratis** | Pago | Gratis |
| **Cinemática pura** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ |
| **Dinámica** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Kinetostática** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **DoF Analysis** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| **Resortes** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Amortiguadores** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Engranajes** | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| **Correas/Cadenas** | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| **Levas** | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ❌ | ⚠️ |
| **Fricción** | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Síntesis 4-bar** | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| **Optimización** | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **DXF Import** | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| **DXF Export** | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| **Scripting Python** | ⚠️ | ⚠️ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Visualización ICR** | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ |
| **Trayectorias** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Hodógrafo** | ❌ | ❌ | ⚠️ | ✅ | ✅ | ✅ | ❌ | ❌ |
| **Co-simulación** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |

\* GIM es gratuito para uso educativo con cita.  
\** Uso educativo gratuito; investigación requiere acuerdo.

---

## Apéndice B — Glosario de términos del roadmap

- **Cinemática pura:** Análisis de movimiento sin considerar fuerzas ni masas. Se resuelve a partir de constraints geométricas y leyes de accionamiento.
- **Kinetostática:** Análisis de fuerzas y reacciones en un mecanismo cuyo movimiento ya es conocido (prescrito por cinemática).
- **Coordenadas naturales:** Formulación cinemática donde las variables son coordenadas cartesianas de puntos y vectores del mecanismo, sujeta a constraints de distancia, ángulo, etc.
- **DoF (Degrees of Freedom):** Grados de libertad del mecanismo. Número de coordenadas independientes necesarias para definir su configuración.
- **Síntesis de mecanismos:** Proceso de diseño geométrico para encontrar las dimensiones de un mecanismo que cumpla una tarea específica (trayectoria, función, poses).
- **Kinetostatic sensor field:** Campo de sensores que mide fuerzas/torques en múltiples puntos del mecanismo simultáneamente.
- **Hodógrafo:** Curva que representa la velocidad de un punto en el espacio de velocidades.
- **ICR (Instantaneous Center of Rotation):** Centro instantáneo de rotación de un cuerpo rígido en movimiento plano.
- **Polodas (Centrodes):** Lugares geométricos del ICR: fijo (respecto a ground) y móvil (respecto al cuerpo).
- **Branch error:** Error en síntesis de mecanismos cuando los precision points pertenecen a una rama cinemática diferente (cruzada vs. abierta).
- **Order error:** Error cuando los precision points no se recorren en el orden temporal deseado.

---

> **Nota final:** Este documento es una propuesta viva. Cada fase debe ser validada con prototipos rápidos antes de comprometer la arquitectura completa. La prioridad absoluta es mantener la estabilidad de la base V1 mientras se añaden capabilities de forma incremental y testeada.
