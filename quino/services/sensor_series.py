# quino/services/sensor_series.py
"""Sensor series extraction from a result artifact dict (used by plot_renderer).

Moved out of metric_evaluator.py when that module was rewritten to host the
new user-Python metric system.
"""
from __future__ import annotations

import math


def _series(artifact: dict, sensor_id: str, channel: str) -> list[float]:
    frames = artifact.get("frames")
    if frames is not None:
        keys = [f"sensor:{sensor_id}:{channel}", f"{sensor_id}:{channel}", f"marker:{sensor_id}:{channel}"]
        values: list[float] = []
        for frame in frames:
            for key in keys:
                if key in frame:
                    value = frame[key]
                    if value is not None:
                        values.append(value)
                    break
        return values
    sensors = artifact.get("sensors", {})
    blob = sensors.get(sensor_id)
    if not blob or channel not in blob.get("channels", []):
        return []
    stride = len(blob["channels"])
    idx = blob["channels"].index(channel)
    data = blob["values"]
    return [data[i] for i in range(idx, len(data), stride) if not math.isnan(data[i])]


def _value_at_t(artifact: dict, sensor_id: str, channel: str, t: float) -> float | None:
    times = artifact.get("time", [])
    frames = artifact.get("frames", [])
    if not times or not frames:
        return None
    closest = min(range(len(times)), key=lambda idx: abs(times[idx] - t))
    keys = [f"sensor:{sensor_id}:{channel}", f"{sensor_id}:{channel}", f"marker:{sensor_id}:{channel}"]
    if closest >= len(frames):
        return None
    for key in keys:
        if key in frames[closest]:
            return frames[closest][key]
    return None


def _value_at_sweep_indices(artifact: dict, sensor_id: str, channel: str, indices: list[int]) -> float | None:
    sensors = artifact.get("sensors", {})
    blob = sensors.get(sensor_id)
    if not blob or channel not in blob.get("channels", []):
        return None
    shape = artifact.get("shape", [])
    if len(indices) != len(shape):
        return None
    cell = 0
    stride = 1
    for axis in reversed(range(len(shape))):
        cell += indices[axis] * stride
        stride *= shape[axis]
    chan_idx = blob["channels"].index(channel)
    pos = cell * len(blob["channels"]) + chan_idx
    if pos >= len(blob["values"]):
        return None
    value = blob["values"][pos]
    return None if math.isnan(value) else value
