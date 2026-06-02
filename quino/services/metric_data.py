"""Build the `data`/`meta` inputs for metric evaluation from sensor outputs.

SensorOutput stores `columns` (channel names) and `data` as rows×columns. We
transpose to per-channel series keyed `"<sensor_name>.<column>"`, plus a shared
`"t"` time axis. `meta` carries analysis-level metadata (dt, t_final...).
"""
from __future__ import annotations

from typing import Any

import numpy as np


def build_metric_data(
    sensor_outputs: dict[str, Any],
    sensor_name_by_id: dict[str, str],
    analysis_meta: dict[str, Any],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    data: dict[str, np.ndarray] = {}
    time_axis: list[float] | None = None
    for sensor_id, out in sensor_outputs.items():
        name = sensor_name_by_id.get(sensor_id, sensor_id)
        columns = list(getattr(out, "columns", []) or [])
        rows = getattr(out, "data", []) or []
        if columns and rows:
            matrix = np.asarray(rows, dtype=float)  # (n_rows, n_cols)
            if matrix.ndim == 2 and matrix.shape[1] == len(columns):
                for col_index, column in enumerate(columns):
                    data[f"{name}.{column}"] = matrix[:, col_index]
        if time_axis is None:
            t = getattr(out, "time", None)
            if t:
                time_axis = list(t)
    if time_axis is not None:
        data["t"] = np.asarray(time_axis, dtype=float)
    return data, dict(analysis_meta)
