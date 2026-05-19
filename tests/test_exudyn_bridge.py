"""Integration tests for ExudynBlockBridge (Paso 3.7 / 3.8)."""

import os
import tempfile

import numpy as np
import pytest

import exudyn as exu
from exudyn import itemInterface as item
from exudyn import utilities

from quino.blocks.exudyn_bridge import ExudynBlockBridge
from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec


def _build_free_body(mbs, x=0.0, y=0.0):
    """Add a free 2D rigid body and return (node_number, object_number)."""
    node = mbs.AddNode(
        item.NodeRigidBody2D(
            referenceCoordinates=[x, y, 0.0],
            initialCoordinates=[0.0, 0.0, 0.0],
            initialVelocities=[0.0, 0.0, 0.0],
        )
    )
    obj = mbs.AddObject(
        item.ObjectRigidBody2D(
            nodeNumber=node,
            physicsMass=1.0,
            physicsInertia=0.1,
            physicsCenterOfMass=[0.0, 0.0],
        )
    )
    return node, obj


def _run_trajectory(mbs, duration=1.0, steps=10):
    """Assemble, solve dynamic, and return (time_array, data_array)."""
    mbs.Assemble()
    settings = exu.SimulationSettings()
    settings.timeIntegration.numberOfSteps = steps
    settings.timeIntegration.endTime = duration
    settings.solutionSettings.writeSolutionToFile = True
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "sol.txt")
        settings.solutionSettings.coordinatesSolutionFileName = path
        mbs.SolveDynamic(simulationSettings=settings)
        sol = utilities.LoadSolutionFile(path, verbose=False)
        data = sol["data"]
        if getattr(data, "ndim", 1) == 1:
            data = data.reshape(1, -1)
        return data[:, 0], data  # time column, full data


class TestExudynBridge:
    def test_bridge_sensor_to_actuator(self) -> None:
        """A block-diagram Constant feeds an MBSActuator."""
        sc = exu.SystemContainer()
        mbs = sc.AddSystem()
        mbs.AddObject(item.ObjectGround())
        body_node, body_obj = _build_free_body(mbs, x=0.0, y=1.0)

        diagram = BlockDiagram(
            instances={
                "force": BlockInstance(
                    "force", "Constant",
                    parameters={"value": 5.0},
                    output_ports=[PortSpec("out")],
                ),
                "act": BlockInstance(
                    "act", "MBSActuator",
                    parameters={"body_id": "body1", "direction": [0.0, 1.0, 0.0]},
                    input_ports=[PortSpec("in")],
                    output_ports=[PortSpec("out")],
                ),
            },
            connections=[Connection("force", "out", "act", "in")],
        )

        bridge = ExudynBlockBridge(
            diagram, mbs, item, exu, {"body1": body_node}, {"body1": body_obj}
        )
        bridge.add_actuator_loads()
        bridge.initialize(mbs)
        bridge.pre_step(mbs, 0.1)

        assert np.isclose(bridge._actuator_buffers.get("act", 0.0), 5.0)

    def test_bridge_sensor_reading(self) -> None:
        """MBSSensor reads the Y position of a body."""
        sc = exu.SystemContainer()
        mbs = sc.AddSystem()
        mbs.AddObject(item.ObjectGround())
        body_node, body_obj = _build_free_body(mbs, x=0.0, y=2.5)

        diagram = BlockDiagram(
            instances={
                "sensor": BlockInstance(
                    "sensor", "MBSSensor",
                    parameters={"body_id": "body1", "variable": "Position", "component": "y"},
                    output_ports=[PortSpec("out")],
                ),
            },
            connections=[],
        )

        bridge = ExudynBlockBridge(
            diagram, mbs, item, exu, {"body1": body_node}, {"body1": body_obj}
        )
        mbs.Assemble()
        bridge.initialize(mbs)
        sensor_value = bridge._engine._compiled.source.instances["sensor"].parameters.get("_value", 0.0)
        assert np.isclose(sensor_value, 2.5)

    def test_constant_force_blocks_equals_native(self) -> None:
        """A 10 N force in X applied via blocks must match a native LoadForceVector."""
        # Native simulation
        sc1 = exu.SystemContainer()
        mbs1 = sc1.AddSystem()
        mbs1.AddObject(item.ObjectGround())
        node1, obj1 = _build_free_body(mbs1)
        marker1 = mbs1.AddMarker(item.MarkerBodyPosition(bodyNumber=obj1, localPosition=[0.0, 0.0, 0.0]))
        mbs1.AddLoad(item.LoadForceVector(markerNumber=marker1, loadVector=[10.0, 0.0, 0.0]))
        t1, data1 = _run_trajectory(mbs1, duration=1.0, steps=10)

        # Block-diagram simulation
        sc2 = exu.SystemContainer()
        mbs2 = sc2.AddSystem()
        mbs2.AddObject(item.ObjectGround())
        node2, obj2 = _build_free_body(mbs2)

        diagram = BlockDiagram(
            instances={
                "force": BlockInstance(
                    "force", "Constant",
                    parameters={"value": 10.0},
                    output_ports=[PortSpec("out")],
                ),
                "act": BlockInstance(
                    "act", "MBSActuator",
                    parameters={"body_id": "body1", "direction": [1.0, 0.0, 0.0]},
                    input_ports=[PortSpec("in")],
                    output_ports=[PortSpec("out")],
                ),
            },
            connections=[Connection("force", "out", "act", "in")],
        )
        bridge = ExudynBlockBridge(diagram, mbs2, item, exu, {"body1": node2}, {"body1": obj2})
        bridge.add_actuator_loads()
        mbs2.Assemble()
        bridge.initialize(mbs2)
        mbs2.SetPreStepUserFunction(bridge.pre_step)
        t2, data2 = _run_trajectory(mbs2, duration=1.0, steps=10)

        np.testing.assert_allclose(data1[:, 1], data2[:, 1], rtol=1e-10)
        np.testing.assert_allclose(data1[:, 2], data2[:, 2], rtol=1e-10)

    def test_pid_position_control_converges(self) -> None:
        """PID controlling X position of a free body converges to setpoint."""
        sc = exu.SystemContainer()
        mbs = sc.AddSystem()
        mbs.AddObject(item.ObjectGround())
        node, obj = _build_free_body(mbs)

        diagram = BlockDiagram(
            instances={
                "sensor": BlockInstance(
                    "sensor", "MBSSensor",
                    parameters={"body_id": "body1", "variable": "Position", "component": "x"},
                    output_ports=[PortSpec("out")],
                ),
                "ref": BlockInstance(
                    "ref", "Constant",
                    parameters={"value": 0.5},
                    output_ports=[PortSpec("out")],
                ),
                "err": BlockInstance(
                    "err", "Adder",
                    parameters={"signs": [1, -1]},
                    input_ports=[PortSpec("a"), PortSpec("b")],
                    output_ports=[PortSpec("out")],
                ),
                "pid": BlockInstance(
                    "pid", "PID",
                    parameters={"kp": 50.0, "ki": 5.0, "kd": 10.0},
                    input_ports=[PortSpec("error")],
                    output_ports=[PortSpec("out")],
                ),
                "act": BlockInstance(
                    "act", "MBSActuator",
                    parameters={"body_id": "body1", "direction": [1.0, 0.0, 0.0]},
                    input_ports=[PortSpec("in")],
                    output_ports=[PortSpec("out")],
                ),
            },
            connections=[
                Connection("ref", "out", "err", "a"),
                Connection("sensor", "out", "err", "b"),
                Connection("err", "out", "pid", "error"),
                Connection("pid", "out", "act", "in"),
            ],
        )
        bridge = ExudynBlockBridge(diagram, mbs, item, exu, {"body1": node}, {"body1": obj})
        bridge.add_actuator_loads()
        mbs.Assemble()
        bridge.initialize(mbs)
        mbs.SetPreStepUserFunction(bridge.pre_step)
        t, data = _run_trajectory(mbs, duration=2.0, steps=200)

        # Position X should converge close to 0.5
        final_x = data[-1, 1]
        assert abs(final_x - 0.5) < 0.05, f"Final X {final_x} not close to setpoint 0.5"

    def test_empty_diagram_does_not_affect_simulation(self) -> None:
        """A diagram with only a sensor (no actuators) must not alter the simulation."""
        # Native simulation (body falling under gravity)
        sc1 = exu.SystemContainer()
        mbs1 = sc1.AddSystem()
        mbs1.AddObject(item.ObjectGround())
        node1, obj1 = _build_free_body(mbs1, x=0.0, y=1.0)
        grav1 = mbs1.AddMarker(item.MarkerBodyPosition(bodyNumber=obj1, localPosition=[0.0, 0.0, 0.0]))
        mbs1.AddLoad(item.LoadForceVector(markerNumber=grav1, loadVector=[0.0, -9.81, 0.0]))
        t1, data1 = _run_trajectory(mbs1, duration=1.0, steps=10)

        # With sensor-only diagram
        sc2 = exu.SystemContainer()
        mbs2 = sc2.AddSystem()
        mbs2.AddObject(item.ObjectGround())
        node2, obj2 = _build_free_body(mbs2, x=0.0, y=1.0)
        grav2 = mbs2.AddMarker(item.MarkerBodyPosition(bodyNumber=obj2, localPosition=[0.0, 0.0, 0.0]))
        mbs2.AddLoad(item.LoadForceVector(markerNumber=grav2, loadVector=[0.0, -9.81, 0.0]))

        diagram = BlockDiagram(
            instances={
                "sensor": BlockInstance(
                    "sensor", "MBSSensor",
                    parameters={"body_id": "body1", "variable": "Position", "component": "y"},
                    output_ports=[PortSpec("out")],
                ),
            },
            connections=[],
        )
        bridge = ExudynBlockBridge(diagram, mbs2, item, exu, {"body1": node2}, {"body1": obj2})
        mbs2.Assemble()
        bridge.initialize(mbs2)
        mbs2.SetPreStepUserFunction(bridge.pre_step)
        t2, data2 = _run_trajectory(mbs2, duration=1.0, steps=10)

        np.testing.assert_allclose(data1[:, 2], data2[:, 2], rtol=1e-10)
