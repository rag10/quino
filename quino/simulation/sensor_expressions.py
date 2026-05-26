from __future__ import annotations

import math
from typing import TYPE_CHECKING

from quino.domain.model import Sensor
from quino.domain.types import Dimension, SensorType
from quino.services.units import Quantity, UnitService

_MM_S_TO_SI = 0.001
_VELOCITY_DIMS = {Dimension.LENGTH: 1, Dimension.TIME: -1}

if TYPE_CHECKING:
    from quino.simulation.assembler import AssembledMechanism


def safe_sensor_var(name: str) -> str:
    safe = name.replace("-", "_").replace(" ", "_").replace(".", "_")
    if safe and safe[0].isdigit():
        safe = "_" + safe
    return safe


def sensor_channel_keys(sensor: Sensor) -> list[tuple[str, str]]:
    """Return (channel_suffix, unit_label) pairs for a sensor type.

    The full expression key is ``{safe_sensor_var(sensor.name)}.{channel_suffix}``.
    """
    if sensor.type is SensorType.POINT:
        return [
            ("x", "mm"),
            ("y", "mm"),
            ("vx", "mm/s"),
            ("vy", "mm/s"),
            ("v", "mm/s"),
        ]
    if sensor.type is SensorType.DISTANCE:
        return [("d", "mm")]
    if sensor.type in {SensorType.ANGLE_HORIZONTAL, SensorType.ANGLE_VERTICAL, SensorType.ANGLE_VECTOR}:
        return [("angle", "deg")]
    return []


def marker_world_position(
    assembled: AssembledMechanism,
    frame: dict[str, float],
    body_id: str,
    marker_id: str,
) -> tuple[float, float]:
    body = assembled.bodies[body_id]
    marker = body.markers[marker_id]
    x = frame.get(f"{body_id}.x", body.origin_x)
    y = frame.get(f"{body_id}.y", body.origin_y)
    angle = frame.get(f"{body_id}.angle", body.angle)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return (
        x + cos_a * marker.local_x - sin_a * marker.local_y,
        y + sin_a * marker.local_x + cos_a * marker.local_y,
    )


def marker_world_velocity(
    assembled: AssembledMechanism,
    frame: dict[str, float],
    body_id: str,
    marker_id: str,
) -> tuple[float, float]:
    """Return marker velocity in mm/s using body velocity stored in frame."""
    body = assembled.bodies[body_id]
    marker = body.markers[marker_id]
    vx_com = frame.get(f"{body_id}.vx", 0.0)
    vy_com = frame.get(f"{body_id}.vy", 0.0)
    omega = frame.get(f"{body_id}.omega", 0.0)
    angle = frame.get(f"{body_id}.angle", body.angle)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    lx = marker.local_x
    ly = marker.local_y
    vx = vx_com + omega * (-sin_a * lx - cos_a * ly)
    vy = vy_com + omega * (cos_a * lx - sin_a * ly)
    return vx, vy


def sensor_expression_variables(
    project,
    assembled: AssembledMechanism,
    frame: dict[str, float],
    unit_service: UnitService,
) -> dict[str, object]:
    body_by_marker: dict[str, str] = {}
    for body_id, body in assembled.bodies.items():
        for marker_id in body.markers:
            body_by_marker[marker_id] = body_id

    variables: dict[str, object] = {}
    for sensor in project.model.sensors:
        safe = safe_sensor_var(sensor.name)
        if sensor.type is SensorType.POINT and len(sensor.marker_ids) == 1:
            marker_id = sensor.marker_ids[0]
            body_id = body_by_marker.get(marker_id)
            if body_id is None:
                continue
            x, y = marker_world_position(assembled, frame, body_id, marker_id)
            vx, vy = marker_world_velocity(assembled, frame, body_id, marker_id)
            v = math.sqrt(vx ** 2 + vy ** 2)
            variables[f"{safe}.x"] = unit_service.quantity(x, "mm")
            variables[f"{safe}.y"] = unit_service.quantity(y, "mm")
            variables[f"{safe}.vx"] = Quantity(vx * _MM_S_TO_SI, _VELOCITY_DIMS)
            variables[f"{safe}.vy"] = Quantity(vy * _MM_S_TO_SI, _VELOCITY_DIMS)
            variables[f"{safe}.v"] = Quantity(v * _MM_S_TO_SI, _VELOCITY_DIMS)
            continue
        if sensor.type is SensorType.DISTANCE and len(sensor.marker_ids) == 2:
            marker_id_a, marker_id_b = sensor.marker_ids
            body_id_a = body_by_marker.get(marker_id_a)
            body_id_b = body_by_marker.get(marker_id_b)
            if body_id_a is None or body_id_b is None:
                continue
            xa, ya = marker_world_position(assembled, frame, body_id_a, marker_id_a)
            xb, yb = marker_world_position(assembled, frame, body_id_b, marker_id_b)
            variables[f"{safe}.d"] = unit_service.quantity(math.hypot(xb - xa, yb - ya), "mm")
            continue
        if sensor.type in {SensorType.ANGLE_HORIZONTAL, SensorType.ANGLE_VERTICAL} and len(sensor.marker_ids) == 2:
            marker_id_a, marker_id_b = sensor.marker_ids
            body_id_a = body_by_marker.get(marker_id_a)
            body_id_b = body_by_marker.get(marker_id_b)
            if body_id_a is None or body_id_b is None:
                continue
            xa, ya = marker_world_position(assembled, frame, body_id_a, marker_id_a)
            xb, yb = marker_world_position(assembled, frame, body_id_b, marker_id_b)
            dx = xb - xa
            dy = yb - ya
            angle_rad = math.atan2(dy, dx) if sensor.type is SensorType.ANGLE_HORIZONTAL else math.atan2(dx, dy)
            variables[f"{safe}.angle"] = unit_service.quantity(math.degrees(angle_rad), "deg")
            continue
        if sensor.type is SensorType.ANGLE_VECTOR and len(sensor.marker_ids) == 4:
            m_a, m_b, m_c, m_d = sensor.marker_ids
            body_a = body_by_marker.get(m_a)
            body_b = body_by_marker.get(m_b)
            body_c = body_by_marker.get(m_c)
            body_d = body_by_marker.get(m_d)
            if not all([body_a, body_b, body_c, body_d]):
                continue
            xa, ya = marker_world_position(assembled, frame, body_a, m_a)
            xb, yb = marker_world_position(assembled, frame, body_b, m_b)
            xc, yc = marker_world_position(assembled, frame, body_c, m_c)
            xd, yd = marker_world_position(assembled, frame, body_d, m_d)
            angle1 = math.atan2(yb - ya, xb - xa)
            angle2 = math.atan2(yd - yc, xd - xc)
            diff = angle2 - angle1
            while diff <= -math.pi:
                diff += 2 * math.pi
            while diff > math.pi:
                diff -= 2 * math.pi
            variables[f"{safe}.angle"] = unit_service.quantity(math.degrees(diff), "deg")
    return variables
