"""
Fase 0.1: Lectura de sensor desde PreStepUserFunction
Objetivo: Validar que podemos leer la posicion de un nodo Exudyn
desde un callback Python en cada paso de integracion.
"""

import exudyn as exu
from exudyn import itemInterface as item

# Configuracion
SC = exu.SystemContainer()
mbs = SC.AddSystem()

# Nodo ground
ground_node = mbs.AddNode(item.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))

# Nodo cuerpo 2D: 1 metro arriba del origen, sin velocidad inicial
body_node = mbs.AddNode(
    item.NodeRigidBody2D(
        referenceCoordinates=[0.0, 1.0, 0.0],  # [x, y, angle]
        initialCoordinates=[0.0, 1.0, 0.0],  # [dx, dy, d_angle] respecto a referencia
        initialVelocities=[0.0, 0.0, 0.0],
    )
)

# Objeto cuerpo
body_object = mbs.AddObject(
    item.ObjectRigidBody2D(
        nodeNumber=body_node,
        physicsMass=1.0,
        physicsInertia=0.1,
        physicsCenterOfMass=[0.0, 0.0],
    )
)

# Gravedad
gravity_marker = mbs.AddMarker(item.MarkerBodyMass(bodyNumber=body_object))
mbs.AddLoad(item.LoadMassProportional(markerNumber=gravity_marker, loadVector=[0.0, -9.81, 0.0]))

# Sensor: leer posicion Y en cada paso via PreStepUserFunction
readings = []

def pre_step_callback(mbs, t):
    # Leer coordenadas del nodo: [x, y, angle, vx, vy, omega]
    coords = mbs.GetNodeOutput(body_node, exu.OutputVariableType.Coordinates)
    y_pos = coords[1]
    readings.append((t, y_pos))
    print(f"  [PreStep] t={t:.4f}s  y={y_pos:.4f}m")
    return True  # True = continuar simulacion

mbs.SetPreStepUserFunction(pre_step_callback)

# Settings de simulacion
simulationSettings = exu.SimulationSettings()
simulationSettings.timeIntegration.endTime = 1.0
simulationSettings.timeIntegration.numberOfSteps = 100
simulationSettings.displayComputationTime = False
simulationSettings.displayStatistics = False

print("=" * 50)
print("FASE 0.1: Sensor read from PreStepUserFunction")
print("=" * 50)
print("Simulando cuerpo en caida libre durante 1 segundo...")

mbs.SolveDynamic(simulationSettings)

print("=" * 50)
print(f"Total lecturas: {len(readings)}")
print(f"Posicion inicial y: {readings[0][1]:.4f} m")
print(f"Posicion final y:   {readings[-1][1]:.4f} m")
print(f"Tiempo final:       {readings[-1][0]:.4f} s")

# Validacion basica: un cuerpo en caida libre desde 1m durante 1s
# y = y0 + v0*t + 0.5*g*t^2 = 1.0 - 0.5*9.81*1.0 = -3.905m (sin considerar que Exudyn puede usar mm internamente)
# En realidad, como usamos metros y masa=1, deberia ser aproximadamente:
expected_y = 1.0 - 0.5 * 9.81 * 1.0**2
actual_y = readings[-1][1]
error = abs(actual_y - expected_y)

print(f"Posicion esperada (teorica): {expected_y:.4f} m")
print(f"Error absoluto: {error:.4f} m")

if error < 0.5:  # tolerancia generosa por paso fijo
    print("\n[OK] Paso 0.1 VALIDADO: lectura de sensor funciona correctamente.")
else:
    print("\n[FAIL] Paso 0.1 FALLIDO: la lectura no coincide con la fisica esperada.")
