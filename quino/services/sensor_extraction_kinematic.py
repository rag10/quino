from __future__ import annotations

import math

from quino.domain.workspace import Pose
from quino.pose.geometry import marker_world_position


def extract_sensors_from_pose(project, pose: Pose | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sensor in project.model.sensors:
        kind = sensor.type.value
        if kind == "point" and sensor.marker_ids:
            x, y = marker_world_position(project, sensor.marker_ids[0], pose)
            out[sensor.id] = {
                "channels": ["x", "y", "vx", "vy", "ax", "ay"],
                "values": [x, y, math.nan, math.nan, math.nan, math.nan],
            }
            continue
        if kind == "distance" and len(sensor.marker_ids) >= 2:
            x1, y1 = marker_world_position(project, sensor.marker_ids[0], pose)
            x2, y2 = marker_world_position(project, sensor.marker_ids[1], pose)
            out[sensor.id] = {
                "channels": ["d"],
                "values": [math.hypot(x2 - x1, y2 - y1)],
            }
            continue
        if kind in {"angle_horizontal", "angle_vertical"} and len(sensor.marker_ids) >= 2:
            x1, y1 = marker_world_position(project, sensor.marker_ids[0], pose)
            x2, y2 = marker_world_position(project, sensor.marker_ids[1], pose)
            theta = math.degrees(math.atan2(y2 - y1, x2 - x1))
            if kind == "angle_vertical":
                theta = 90.0 - theta
            out[sensor.id] = {"channels": ["theta"], "values": [theta]}
            continue
        if kind == "angle_vector" and len(sensor.marker_ids) >= 4:
            x1, y1 = marker_world_position(project, sensor.marker_ids[0], pose)
            x2, y2 = marker_world_position(project, sensor.marker_ids[1], pose)
            x3, y3 = marker_world_position(project, sensor.marker_ids[2], pose)
            x4, y4 = marker_world_position(project, sensor.marker_ids[3], pose)
            a1 = math.atan2(y2 - y1, x2 - x1)
            a2 = math.atan2(y4 - y3, x4 - x3)
            diff = math.degrees(a2 - a1)
            while diff > 180.0:
                diff -= 360.0
            while diff < -180.0:
                diff += 360.0
            out[sensor.id] = {"channels": ["theta"], "values": [diff]}
    return out
