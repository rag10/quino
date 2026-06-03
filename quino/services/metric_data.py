"""Build the `data`/`meta` inputs for metric evaluation from sensor outputs.

SensorOutput stores `columns` (channel labels, e.g. ``"x [mm]"``) and `data` as
rows×columns. We transpose to per-channel series keyed
``"<sensor_name>.<channel>"`` where ``<channel>`` is the CLEAN channel name
(``"x"``, ``"vx"`` …) with the unit bracket stripped, so it matches what the
metric editor's channel palette advertises and what users type
(``data['Point Sensor1.x']``). A shared ``"t"`` time axis is also provided.
`meta` carries analysis-level metadata (dt, t_final...).
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np

# Matches a trailing unit bracket, e.g. "x [mm]" -> "x", "v [mm/s]" -> "v".
_UNIT_SUFFIX_RE = re.compile(r"\s*\[[^\]]*\]\s*$")


def clean_channel_name(column: str) -> str:
    """Strip the unit bracket from a sensor column label.

    ``"x [mm]"`` -> ``"x"``; ``"angle [deg]"`` -> ``"angle"``; an already-clean
    name is returned unchanged.
    """
    return _UNIT_SUFFIX_RE.sub("", str(column)).strip()


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
                    channel = clean_channel_name(column)
                    series = matrix[:, col_index]
                    data[f"{name}.{channel}"] = series
                    # Also expose the raw decorated label, so a user who typed
                    # the full "x [mm]" form still resolves.
                    if channel != str(column):
                        data[f"{name}.{column}"] = series
        if time_axis is None:
            t = getattr(out, "time", None)
            if t:
                time_axis = list(t)
    if time_axis is not None:
        data["t"] = np.asarray(time_axis, dtype=float)
    return data, dict(analysis_meta)
