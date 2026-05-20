"""Bridge between BlockEngine and Exudyn MBS.

Provides PreStepUserFunction that reads MBS sensors, runs the block diagram,
and writes actuator values back into Exudyn loads.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from quino.blocks.engine import BlockEngine
from quino.domain.model import Project, Sensor
from quino.domain.blocks import BlockDiagram
from quino.domain.types import SensorType
from quino.simulation.sensor_expressions import marker_world_position, marker_world_velocity


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
        project: Project | None = None,
        assembled: Any | None = None,
    ) -> None:
        self._mbs = mbs
        self._item_interface = item_interface
        self._exu = exu
        self._node_numbers = node_numbers
        self._body_objects = body_objects
        self._project = project
        self._assembled = assembled

        self._engine = BlockEngine.from_diagram(diagram, context=self)
        self._sensor_instances: dict[str, dict[str, Any]] = {}
        self._actuator_instances: dict[str, dict[str, Any]] = {}

        sensor_types = {"MBSSensor", "ModelSensor"}
        actuator_types = {"MBSActuator", "LoadCommand", "SpringCommand", "DriverCommand"}
        for inst_id, inst in diagram.instances.items():
            if inst.block_type in sensor_types:
                self._sensor_instances[inst_id] = inst.parameters
            elif inst.block_type in actuator_types:
                self._actuator_instances[inst_id] = inst.parameters

        self._actuator_buffers: dict[str, float] = {}
        self._last_t: float = 0.0

    def initialize(self, mbs: Any) -> None:
        """Run a pre-step at t=0 to populate actuator buffers before assembly."""
        self.pre_step(mbs, 0.0)

    def add_actuator_loads(self) -> None:
        """Create Exudyn LoadForceVector objects for each MBSActuator block."""
        for inst_id, spec in self._actuator_instances.items():
            load_binding = self._resolve_actuator_binding(inst_id, spec)
            if load_binding is None:
                continue

            marker = self._mbs.AddMarker(
                self._item_interface.MarkerBodyPosition(
                    bodyNumber=load_binding["body_obj"],
                    localPosition=load_binding["local_position"],
                )
            )

            # Buffer key used by the user function
            buf_key = load_binding["target_id"]
            direction = load_binding["direction"]

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
            target_id = self._resolve_target_id(inst_id, spec)
            out = self._engine.output(inst_id, "out")
            self._actuator_buffers[target_id] = float(out[0])

        return True

    def _read_sensor(self, spec: dict[str, Any]) -> float:
        sensor_id = spec.get("sensor_id")
        if isinstance(sensor_id, str) and sensor_id:
            return self._read_model_sensor(sensor_id, spec.get("channel"))

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

    def _resolve_actuator_binding(self, inst_id: str, spec: dict[str, Any]) -> dict[str, Any] | None:
        load_id = spec.get("load_id")
        if isinstance(load_id, str) and load_id and self._project is not None and self._assembled is not None:
            model_load = next((load for load in self._project.model.loads if load.id == load_id), None)
            if model_load is None:
                return None
            assembled_body = self._find_body_for_marker(model_load.target_marker_id)
            if assembled_body is None:
                return None
            assembled_marker = assembled_body.markers.get(model_load.target_marker_id)
            if assembled_marker is None:
                return None
            body_obj = self._body_objects.get(assembled_body.body_id)
            if body_obj is None:
                return None
            component = str(spec.get("component", "fx")).lower()
            if component == "fy":
                direction = [0.0, 1.0, 0.0]
            else:
                direction = [1.0, 0.0, 0.0]
            return {
                "body_obj": body_obj,
                "local_position": [
                    float(assembled_marker.local_x),
                    float(assembled_marker.local_y),
                    0.0,
                ],
                "direction": spec.get("direction", direction),
                "target_id": self._resolve_target_id(inst_id, spec),
            }

        body_id = spec.get("body_id")
        body_obj = self._body_objects.get(body_id)
        if body_obj is None:
            return None
        return {
            "body_obj": body_obj,
            "local_position": spec.get("local_position", [0.0, 0.0, 0.0]),
            "direction": spec.get("direction", [0.0, 1.0, 0.0]),
            "target_id": self._resolve_target_id(inst_id, spec),
        }

    def _resolve_target_id(self, inst_id: str, spec: dict[str, Any]) -> str:
        explicit = spec.get("target_id")
        if isinstance(explicit, str) and explicit:
            return explicit
        for key in ("load_id", "spring_id", "driver_id"):
            value = spec.get(key)
            if isinstance(value, str) and value:
                return value
        return inst_id

    def command_value(self, target_id: str) -> float | None:
        value = self._actuator_buffers.get(target_id)
        if value is None:
            return None
        return float(value)

    def _read_model_sensor(self, sensor_id: str, channel: Any) -> float:
        if self._project is None or self._assembled is None:
            return 0.0
        sensor = next((item for item in self._project.model.sensors if item.id == sensor_id), None)
        if sensor is None:
            return 0.0
        frame = self._current_frame()
        channel_name = str(channel or self._default_sensor_channel(sensor))
        return self._sensor_channel_value(sensor, frame, channel_name)

    def _current_frame(self) -> dict[str, float]:
        if self._assembled is None:
            return {}
        frame: dict[str, float] = {}
        for body_id, node_number in self._node_numbers.items():
            coordinates = self._mbs.GetNodeOutput(node_number, self._exu.OutputVariableType.Coordinates)
            body = self._assembled.bodies[body_id]
            com_ref_x, com_ref_y = self._body_com_global_mm(body)
            cur_angle = body.angle + (float(coordinates[2]) if len(coordinates) > 2 else 0.0)
            cos_a = math.cos(cur_angle)
            sin_a = math.sin(cur_angle)
            cur_com_x = com_ref_x + float(coordinates[0]) * 1e3
            cur_com_y = com_ref_y + float(coordinates[1]) * 1e3
            frame[f"{body_id}.x"] = cur_com_x - cos_a * body.com_local_x + sin_a * body.com_local_y
            frame[f"{body_id}.y"] = cur_com_y - sin_a * body.com_local_x - cos_a * body.com_local_y
            frame[f"{body_id}.angle"] = cur_angle
            try:
                vel = self._mbs.GetNodeOutput(node_number, self._exu.OutputVariableType.Velocity)
                frame[f"{body_id}.vx"] = float(vel[0]) * 1e3
                frame[f"{body_id}.vy"] = float(vel[1]) * 1e3
                frame[f"{body_id}.omega"] = float(vel[2]) if len(vel) > 2 else 0.0
            except Exception:
                pass
        return frame

    def _sensor_channel_value(self, sensor: Sensor, frame: dict[str, float], channel: str) -> float:
        body_by_marker = self._body_by_marker()
        if sensor.type is SensorType.POINT and len(sensor.marker_ids) == 1:
            marker_id = sensor.marker_ids[0]
            body_id = body_by_marker.get(marker_id)
            if body_id is None:
                return 0.0
            x, y = marker_world_position(self._assembled, frame, body_id, marker_id)
            vx, vy = marker_world_velocity(self._assembled, frame, body_id, marker_id)
            if channel == "x":
                return float(x)
            if channel == "y":
                return float(y)
            if channel == "vx":
                return float(vx)
            if channel == "vy":
                return float(vy)
            if channel == "v":
                return float(np.hypot(vx, vy))
            return 0.0
        if sensor.type is SensorType.DISTANCE and len(sensor.marker_ids) == 2:
            marker_a, marker_b = sensor.marker_ids
            body_a = body_by_marker.get(marker_a)
            body_b = body_by_marker.get(marker_b)
            if body_a is None or body_b is None:
                return 0.0
            xa, ya = marker_world_position(self._assembled, frame, body_a, marker_a)
            xb, yb = marker_world_position(self._assembled, frame, body_b, marker_b)
            return float(np.hypot(xb - xa, yb - ya))
        if sensor.type in {SensorType.ANGLE_HORIZONTAL, SensorType.ANGLE_VERTICAL} and len(sensor.marker_ids) == 2:
            marker_a, marker_b = sensor.marker_ids
            body_a = body_by_marker.get(marker_a)
            body_b = body_by_marker.get(marker_b)
            if body_a is None or body_b is None:
                return 0.0
            xa, ya = marker_world_position(self._assembled, frame, body_a, marker_a)
            xb, yb = marker_world_position(self._assembled, frame, body_b, marker_b)
            dx = xb - xa
            dy = yb - ya
            angle_rad = math.atan2(dy, dx) if sensor.type is SensorType.ANGLE_HORIZONTAL else math.atan2(dx, dy)
            return float(np.degrees(angle_rad))
        return 0.0

    def _default_sensor_channel(self, sensor: Sensor) -> str:
        if sensor.type is SensorType.POINT:
            return "y"
        if sensor.type is SensorType.DISTANCE:
            return "d"
        return "angle"

    def _body_by_marker(self) -> dict[str, str]:
        result: dict[str, str] = {}
        if self._assembled is None:
            return result
        for body_id, body in self._assembled.bodies.items():
            for marker_id in body.markers:
                result[marker_id] = body_id
        return result

    def _find_body_for_marker(self, marker_id: str) -> Any | None:
        if self._assembled is None:
            return None
        for body in self._assembled.bodies.values():
            if marker_id in body.markers:
                return body
        return None

    def _body_com_global_mm(self, body: Any) -> tuple[float, float]:
        cos_a = math.cos(body.angle)
        sin_a = math.sin(body.angle)
        return (
            body.origin_x + cos_a * body.com_local_x - sin_a * body.com_local_y,
            body.origin_y + sin_a * body.com_local_x + cos_a * body.com_local_y,
        )
