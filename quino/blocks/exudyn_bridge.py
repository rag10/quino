"""Bridge between BlockEngine and Exudyn MBS.

Provides PreStepUserFunction that reads MBS sensors, runs the block diagram,
and writes actuator values back into Exudyn loads.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from quino.blocks.engine import BlockEngine
from quino.domain.blocks import BlockDiagram


class ExudynBlockBridge:
    """Synchronises a BlockDiagram with an Exudyn MBS during simulation."""

    def __init__(
        self,
        diagram: BlockDiagram,
        mbs: Any,
        item_interface: Any,
        exu: Any,
        node_numbers: dict[str, int],
        body_objects: dict[str, int],
    ) -> None:
        self._mbs = mbs
        self._item_interface = item_interface
        self._exu = exu
        self._node_numbers = node_numbers
        self._body_objects = body_objects

        self._engine = BlockEngine.from_diagram(diagram, context=self)
        self._sensor_instances: dict[str, dict[str, Any]] = {}
        self._actuator_instances: dict[str, dict[str, Any]] = {}

        for inst_id, inst in diagram.instances.items():
            if inst.block_type == "MBSSensor":
                self._sensor_instances[inst_id] = inst.parameters
            elif inst.block_type == "MBSActuator":
                self._actuator_instances[inst_id] = inst.parameters

        self._actuator_buffers: dict[str, float] = {}
        self._last_t: float = 0.0

    def initialize(self, mbs: Any) -> None:
        """Run a pre-step at t=0 to populate actuator buffers before assembly."""
        self.pre_step(mbs, 0.0)

    def add_actuator_loads(self) -> None:
        """Create Exudyn LoadForceVector objects for each MBSActuator block."""
        for inst_id, spec in self._actuator_instances.items():
            body_id = spec.get("body_id")
            local_pos = spec.get("local_position", [0.0, 0.0, 0.0])
            direction = spec.get("direction", [0.0, 1.0, 0.0])  # default Y axis
            target_id = spec.get("target_id", inst_id)

            body_obj = self._body_objects.get(body_id)
            if body_obj is None:
                continue

            marker = self._mbs.AddMarker(
                self._item_interface.MarkerBodyPosition(
                    bodyNumber=body_obj,
                    localPosition=local_pos,
                )
            )

            # Buffer key used by the user function
            buf_key = target_id

            def make_uf(key: str):
                def uf(mbs_ref, t, load):
                    force = self._actuator_buffers.get(key, 0.0)
                    return [
                        direction[0] * force,
                        direction[1] * force,
                        direction[2] * force,
                    ]
                return uf

            self._mbs.AddLoad(
                self._item_interface.LoadForceVector(
                    markerNumber=marker,
                    loadVector=[0.0, 0.0, 0.0],
                    loadVectorUserFunction=make_uf(buf_key),
                )
            )

    def pre_step(self, mbs: Any, t: float) -> bool:
        """Called by Exudyn PreStepUserFunction.

        Returns True to continue simulation.
        """
        # 1. Read MBS sensors and inject into sensor block parameters
        for inst_id, spec in self._sensor_instances.items():
            value = self._read_sensor(spec)
            self._engine._compiled.source.instances[inst_id].parameters["_value"] = value

        # 2. Run block engine
        dt = t - self._last_t
        self._last_t = t
        self._engine.step(t, dt)

        # 3. Write actuator outputs to buffers
        for inst_id, spec in self._actuator_instances.items():
            target_id = spec.get("target_id", inst_id)
            out = self._engine.output(inst_id, "out")
            self._actuator_buffers[target_id] = float(out[0])

        return True

    def _read_sensor(self, spec: dict[str, Any]) -> float:
        body_id = spec.get("body_id")
        variable = spec.get("variable", "Position")
        component = spec.get("component", "y")

        node = self._node_numbers.get(body_id)
        if node is None:
            return 0.0

        var = getattr(self._exu.OutputVariableType, variable)
        coords = self._mbs.GetNodeOutput(node, var)

        idx = {"x": 0, "y": 1, "z": 2, "angle": 2}.get(component, 1)
        return float(coords[idx])
