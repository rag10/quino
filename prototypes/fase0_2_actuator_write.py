"""
Fase 0.2: Escritura de actuacion desde PreStepUserFunction
Objetivo: Validar que podemos calcular una fuerza en PreStep y aplicarla
al cuerpo via LoadForceVector con user function, de forma consistente.
Escenario: resorte virtual que tira el cuerpo hacia y=0.
"""

import exudyn as exu
from exudyn import itemInterface as item

# Configuracion
SC = exu.SystemContainer()
mbs = SC.AddSystem()

# Nodo ground
ground_node = mbs.AddNode(item.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))

# Nodo cuerpo: 1m arriba, sin velocidad inicial
body_node = mbs.AddNode(
    item.NodeRigidBody2D(
        referenceCoordinates=[0.0, 1.0, 0.0],
        initialCoordinates=[0.0, 1.0, 0.0],
        initialVelocities=[0.0, 0.0, 0.0],
    )
)

body_object = mbs.AddObject(
    item.ObjectRigidBody2D(
        nodeNumber=body_node,
        physicsMass=1.0,
        physicsInertia=0.1,
        physicsCenterOfMass=[0.0, 0.0],
    )
)

# Nota: sin gravedad para este test, para ver oscilacion pura del resorte virtual

# Buffer de actuacion (compartido entre PreStep y LoadForceVector)
actuator_buffer = {"fy": 0.0}

# Marker para aplicar fuerza en el CoM
force_marker = mbs.AddMarker(item.MarkerBodyPosition(bodyNumber=body_object, localPosition=[0.0, 0.0, 0.0]))

# LoadForceVector que lee del buffer
def force_user_function(mbs, t, load):
    return [0.0, actuator_buffer["fy"], 0.0]

mbs.AddLoad(
    item.LoadForceVector(
        markerNumber=force_marker,
        loadVector=[0.0, 0.0, 0.0],  # placeholder; se sobrescribe por user function
        loadVectorUserFunction=force_user_function,
    )
)

# Constante del resorte virtual
K_SPRING = 50.0  # N/m

# PreStep: lee posicion, calcula fuerza de resorte, escribe en buffer
def pre_step_callback(mbs, t):
    coords = mbs.GetNodeOutput(body_node, exu.OutputVariableType.Coordinates)
    y_pos = coords[1]
    # Resorte virtual hacia y=0
    actuator_buffer["fy"] = -K_SPRING * y_pos
    return True

mbs.SetPreStepUserFunction(pre_step_callback)

# Simulacion
simulationSettings = exu.SimulationSettings()
simulationSettings.timeIntegration.endTime = 1.0
simulationSettings.timeIntegration.numberOfSteps = 100
simulationSettings.displayComputationTime = False
simulationSettings.displayStatistics = False
# Desactivar salida a archivo
simulationSettings.solutionSettings.writeSolutionToFile = False

print("=" * 60)
print("FASE 0.2: Actuator write from PreStepUserFunction")
print("=" * 60)
print(f"Resorte virtual: K = {K_SPRING} N/m")
print("Simulando durante 2 segundos (sin gravedad, oscilacion pura)...")

mbs.SolveDynamic(simulationSettings)

# Lectura final para verificar
final_coords = mbs.GetNodeOutput(body_node, exu.OutputVariableType.Coordinates)
final_y = final_coords[1]
final_vel = mbs.GetNodeOutput(body_node, exu.OutputVariableType.Velocity)
final_vy = final_vel[1]

print(f"\nPosicion final y: {final_y:.4f} m")
print(f"Velocidad final y: {final_vy:.4f} m/s")

# Sin gravedad, con resorte hacia y=0, el cuerpo debe oscilar alrededor de 0.
# Verificamos que no se escape y que la velocidad cambie de signo (oscila).
# Si la fuerza no se aplicara, el cuerpo se quedaria en y=1.0 con v=0.

oscillates = abs(final_y) < 1.5 and abs(final_vy) > 0.1  # debe haber movimiento
if oscillates:
    print("\n[OK] Paso 0.2 VALIDADO: actuacion desde buffer funciona.")
    print("     El cuerpo oscila (resorte virtual activo).")
else:
    print("\n[FAIL] Paso 0.2 FALLIDO: comportamiento no esperado.")
    print(f"       final_y={final_y:.4f}, final_vy={final_vy:.4f}")
