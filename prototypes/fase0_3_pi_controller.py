"""
Fase 0.3: Estado persistente en callback (controlador PI)
Objetivo: Validar que podemos mantener estado (integral del error)
entre llamadas al PreStepUserFunction, y usarlo para control realimentado.
Escenario: mantener un cuerpo suspendido en y_target = 0.5m contra la gravedad.
"""

import exudyn as exu
from exudyn import itemInterface as item

# Configuracion
SC = exu.SystemContainer()
mbs = SC.AddSystem()

# Nodo ground
ground_node = mbs.AddNode(item.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))

# Nodo cuerpo: 0.5m (ya en la posicion objetivo), sin velocidad inicial
Y_TARGET = 0.5
body_node = mbs.AddNode(
    item.NodeRigidBody2D(
        referenceCoordinates=[0.0, Y_TARGET, 0.0],
        initialCoordinates=[0.0, Y_TARGET, 0.0],
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

# Gravedad
gravity_marker = mbs.AddMarker(item.MarkerBodyMass(bodyNumber=body_object))
mbs.AddLoad(item.LoadMassProportional(markerNumber=gravity_marker, loadVector=[0.0, -9.81, 0.0]))

# Actuador: fuerza vertical en CoM
actuator_buffer = {"fy": 0.0}
force_marker = mbs.AddMarker(item.MarkerBodyPosition(bodyNumber=body_object, localPosition=[0.0, 0.0, 0.0]))

def force_user_function(mbs, t, load):
    return [0.0, actuator_buffer["fy"], 0.0]

mbs.AddLoad(
    item.LoadForceVector(
        markerNumber=force_marker,
        loadVector=[0.0, 0.0, 0.0],
        loadVectorUserFunction=force_user_function,
    )
)

# Estado del controlador PI (persistente via closure)
controller_state = {
    "integral": 0.0,
    "last_t": 0.0,
    "first_call": True,
}

# Ganancias del PI
KP = 20.0
KI = 10.0

# PreStep: controlador PI
def pre_step_callback(mbs, t):
    # Calcular dt efectivo
    if controller_state["first_call"]:
        dt = 0.0
        controller_state["first_call"] = False
    else:
        dt = t - controller_state["last_t"]
    controller_state["last_t"] = t

    # Sensor: posicion Y
    coords = mbs.GetNodeOutput(body_node, exu.OutputVariableType.Coordinates)
    y_pos = coords[1]

    # Error
    error = Y_TARGET - y_pos

    # Integral (acumulacion euler)
    if dt > 0:
        controller_state["integral"] += error * dt

    # Ley de control PI
    force = KP * error + KI * controller_state["integral"]

    # Compensacion de gravedad: en equilibrio estatico, error=0, integral=9.81/KI
    # Pero el PI deberia aprender solo. Sin embargo, para evitar caida inicial brusca,
    # podriamos inicializar la integral a 9.81/KI. Lo hacemos para el test:
    if controller_state["first_call"] is False and dt == 0.0:
        controller_state["integral"] = 9.81 / KI

    actuator_buffer["fy"] = force

    # Debug cada 50 pasos (aprox)
    # print(f"  t={t:.3f} y={y_pos:.4f} err={error:.4f} int={controller_state['integral']:.4f} F={force:.4f}")
    return True

mbs.SetPreStepUserFunction(pre_step_callback)

# Simulacion
simulationSettings = exu.SimulationSettings()
simulationSettings.timeIntegration.endTime = 5.0
simulationSettings.timeIntegration.numberOfSteps = 500
simulationSettings.displayComputationTime = False
simulationSettings.displayStatistics = False
simulationSettings.solutionSettings.writeSolutionToFile = False

print("=" * 60)
print("FASE 0.3: PI Controller with persistent state")
print("=" * 60)
print(f"Target position: y = {Y_TARGET} m")
print(f"Controller: KP={KP}, KI={KI}")
print("Simulando 5 segundos...")

mbs.SolveDynamic(simulationSettings)

# Evaluacion final
final_coords = mbs.GetNodeOutput(body_node, exu.OutputVariableType.Coordinates)
final_y = final_coords[1]
final_vel = mbs.GetNodeOutput(body_node, exu.OutputVariableType.Velocity)
final_vy = final_vel[1]
max_deviation = abs(final_y - Y_TARGET)

print(f"\nPosicion final y: {final_y:.4f} m (target={Y_TARGET})")
print(f"Desviacion maxima: {max_deviation:.4f} m")
print(f"Velocidad final y: {final_vy:.4f} m/s")
print(f"Integral acumulada: {controller_state['integral']:.4f}")
print(f"Fuerza final: {actuator_buffer['fy']:.4f} N")

# Criterios de exito para prototipo (no requiere sintonia perfecta):
# 1. El cuerpo no cae libremente (sin controlador, en 5s estaria en y ~ -120m).
# 2. Se mantiene en el hemisferio superior (y > 0).
# 3. La fuerza final es positiva (empuja hacia arriba) y del orden de la gravedad.
# 4. La velocidad es razonable (no se escapa).
free_fall_y = 0.5 - 0.5 * 9.81 * 5.0**2  # ~ -122m
position_maintained = final_y > 0.0
velocity_reasonable = abs(final_vy) < 5.0
force_upward = actuator_buffer["fy"] > 5.0

print(f"\nCaida libre teorica (sin controlador): y = {free_fall_y:.1f} m")
print(f"Posicion real con PI: y = {final_y:.4f} m")

if position_maintained and velocity_reasonable and force_upward:
    print("\n[OK] Paso 0.3 VALIDADO: PI controller con estado persistente funciona.")
    print("     El cuerpo no cae libremente; el controlador compensa la gravedad.")
    if max_deviation < 0.1:
        print("     ADEMAS: convergencia excelente (<10cm de error).")
else:
    print("\n[FAIL] Paso 0.3 FALLIDO: el controlador no logra estabilizar.")
    print(f"       position_maintained={position_maintained}, velocity_reasonable={velocity_reasonable}, force_upward={force_upward}")
