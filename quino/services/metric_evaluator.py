from __future__ import annotations

import math

from quino.domain.plotting import MetricDef


def evaluate_metric(metric: MetricDef, artifact: dict) -> float | None:
    kind = metric.kind
    parts = metric.target.split(":")
    sensor_id = parts[0] if parts else ""
    channel = parts[1] if len(parts) > 1 else ""
    if kind in {"max", "min", "rms"}:
        values = _series(artifact, sensor_id, channel)
        if not values:
            return None
        if kind == "max":
            return max(values)
        if kind == "min":
            return min(values)
        return math.sqrt(sum(value * value for value in values) / len(values))
    if kind == "value_at_t":
        return _value_at_t(artifact, sensor_id, channel, float(metric.params.get("t", 0.0)))
    if kind == "value_at_sweep":
        return _value_at_sweep_indices(artifact, sensor_id, channel, list(metric.params.get("indices", [])))
    if kind == "spring_energy":
        return float(artifact.get("total_energy_in_springs", 0.0))
    return None


def evaluate_metrics(metrics: list[MetricDef], artifact: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for metric in metrics:
        value = evaluate_metric(metric, artifact)
        if value is not None and not math.isnan(value):
            out[metric.key] = float(value)
    return out


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
