# Plan de Desarrollo — Kinematics Software
**Versión:** Sin plan de versiones, todo en fase inicial
**Filosofía:** *Eliminar antes de añadir.* Limpiar código muerto y redundante para que el núcleo sea robusto. 

---

## Visión del producto

El objetivo final es una **plataforma de ingeniería** para:

- Crear mecanismos 2D desde una interfaz gráfica profesional.
- Añadir cuerpos, barras, juntas, sliders, restricciones, actuadores, muelles, amortiguadores, cargas, fricción y transmisiones mecánicas.
- Simular **mecanismos generales**, no solo topologías predefinidas.
- Visualizar animaciones, trayectorias, velocidades, aceleraciones, fuerzas, pares y señales.
- Permitir **scripting Python** como primera clase.
- Permitir la creación de sketch simples como base al modelo cinemático (opcional para el usuario)
- Permitir en fases futuras: bloques tipo Simulink, hidráulica, electrónica, control, etc. que retroalimenten la simulación.

El desarrollo será muy cuidadoso y poco a poco a poco.

La arquitectura debe ser una **capa de alto nivel sobre uno o varios solvers**:

```text
Usuario / GUI
  ↓
Modelo mecánico propio (MechanismModel)
  ↓
Validador + Ensamblador abstracto (agnóstico al solver)
  ↓
Traductor de backend
  ↓
Exudyn (hoy) / Chrono (futuro) / Solver nativo (futuro) / IDA (futuro)
```