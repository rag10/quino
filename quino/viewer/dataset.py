from __future__ import annotations

from pathlib import Path

import numpy as np
from quino.domain.model import ReactionOutput, SensorOutput


class SensorDataset:
    """Converts SensorOutput and ReactionOutput objects into plottable matrices."""

    def __init__(self, project):
        self.project = project
        self._matrices: dict[str, dict] = {}
        self._load_sensor_outputs()
        self._load_reaction_outputs()

    def _load_sensor_outputs(self) -> None:
        """Load sensor outputs recorded during the last simulation run."""
        for sensor_id, output in self.project.sensor_outputs.items():
            sensor = next((s for s in self.project.model.sensors if s.id == sensor_id), None)
            if not sensor or not output.data:
                continue
            data = np.array(output.data)
            self._matrices[sensor.name] = {
                "sensor_id": sensor_id,
                "sensor_type": sensor.type.value,
                "time": np.array(output.time),
                "columns": output.columns,
                "data": data,
            }

    def _load_reaction_outputs(self) -> None:
        """Load reaction outputs recorded during the last simulation run."""
        for rxn in self.project.reaction_outputs.values():
            if not rxn.data:
                continue
            name = f"[R] {rxn.joint_name}"
            self._matrices[name] = {
                "sensor_id": f"__reaction__{rxn.joint_id}",
                "sensor_type": "reaction",
                "time": np.array(rxn.time),
                "columns": rxn.columns,
                "data": np.array(rxn.data),
            }

    def get_matrix_names(self) -> list[str]:
        """Return list of available sensor matrix names."""
        return list(self._matrices.keys())

    def get_matrix(self, name: str) -> tuple[np.ndarray, list[str]] | None:
        """Get matrix data and headers by sensor name. First column is always time."""
        if name not in self._matrices:
            return None
        matrix = self._matrices[name]
        time_col = matrix["time"].reshape(-1, 1)
        data = np.hstack([time_col, matrix["data"]])
        headers = ["time [s]"] + list(matrix["columns"])
        return data, headers

    def get_sensor_metadata(self, name: str) -> dict | None:
        """Get sensor metadata (type, marker_ids, etc)."""
        if name not in self._matrices:
            return None
        sensor = next((s for s in self.project.model.sensors if s.name == name), None)
        if not sensor:
            return None
        return {
            "id": sensor.id,
            "type": sensor.type.value,
            "marker_ids": sensor.marker_ids,
            "name": sensor.name,
        }

    def has_data(self) -> bool:
        """Check if any sensor outputs are available."""
        return len(self._matrices) > 0


class RunArtifactDataset:
    """SensorDataset-shaped view over a persisted analysis run artifact.

    Lets PlotWindow consume kinematic / dynamic / static / equilibrium artifacts
    via the same get_matrix_names / get_matrix interface it uses for live
    simulation outputs.
    """

    def __init__(self, project, artifact: dict) -> None:
        self.project = project
        self._artifact = artifact or {}
        self._matrices: dict[str, dict] = {}
        self._build()

    def _build(self) -> None:
        kind = self._artifact.get("type")
        if kind == "kinematic":
            self._build_kinematic()
        elif kind == "static":
            self._build_static()
        elif kind == "equilibrium":
            self._build_equilibrium()

    def _build_kinematic(self) -> None:
        sweep_axes = self._artifact.get("sweep_axes") or []
        sensors_blob = self._artifact.get("sensors") or {}
        if not sweep_axes:
            return
        # For a 1-D sweep the values length matches shape[0]. For N-D sweeps
        # we use the first axis as X and the values are stored in snake order
        # (see KinematicAnalysisRunner._snake_iter); we plot against the index
        # if the unflattening would be ambiguous.
        shape = self._artifact.get("shape") or [len(sweep_axes[0].get("values", []))]
        is_one_d = len(shape) == 1
        primary_axis = sweep_axes[0]
        x_values = np.array(primary_axis.get("values", []), dtype=float)
        x_label = primary_axis.get("label") or "sweep"
        for sensor_id, blob in sensors_blob.items():
            sensor = next((s for s in self.project.model.sensors if s.id == sensor_id), None)
            sensor_name = sensor.name if sensor is not None else sensor_id
            channels = list(blob.get("channels") or [])
            values = list(blob.get("values") or [])
            if not channels or not values:
                continue
            n_channels = len(channels)
            # Values are flat row-major: one row per cell, n_channels columns.
            try:
                arr = np.array(values, dtype=float).reshape(-1, n_channels)
            except ValueError:
                continue
            if is_one_d:
                # Align lengths defensively (failed cells still emit NaN rows).
                rows = min(len(x_values), arr.shape[0])
                if rows == 0:
                    continue
                matrix_x = x_values[:rows]
                matrix_data = arr[:rows, :]
            else:
                matrix_x = np.arange(arr.shape[0], dtype=float)
                matrix_data = arr
            self._matrices[sensor_name] = {
                "sensor_id": sensor_id,
                "sensor_type": "kinematic",
                "time": matrix_x,
                "columns": channels,
                "data": matrix_data,
                "x_label": x_label,
            }

    def _build_static(self) -> None:
        # Static analyses report per-marker / per-joint scalar fields. Expose
        # them as 1-row matrices so the user can at least inspect the values
        # alongside other runs in the plot widget.
        reactions = self._artifact.get("reactions") or []
        if reactions:
            columns: list[str] = []
            row: list[float] = []
            for entry in reactions:
                joint = entry.get("joint_name") or entry.get("joint_id") or "joint"
                for key, value in entry.items():
                    if key in {"joint_name", "joint_id"}:
                        continue
                    if isinstance(value, (int, float)):
                        columns.append(f"{joint}.{key}")
                        row.append(float(value))
            if columns:
                self._matrices["Reactions"] = {
                    "sensor_id": "__static_reactions__",
                    "sensor_type": "static",
                    "time": np.array([0.0]),
                    "columns": columns,
                    "data": np.array([row]),
                    "x_label": "index",
                }

    def _build_equilibrium(self) -> None:
        equilibria = self._artifact.get("equilibria") or []
        if not equilibria:
            return
        # Each equilibrium is a dict; collect numeric scalars across them and
        # plot them indexed by equilibrium number.
        all_keys: list[str] = []
        seen: set[str] = set()
        for eq in equilibria:
            for key, value in eq.items():
                if isinstance(value, (int, float)) and key not in seen:
                    all_keys.append(key)
                    seen.add(key)
        if not all_keys:
            return
        data = np.array(
            [[float(eq.get(k, np.nan)) for k in all_keys] for eq in equilibria],
            dtype=float,
        )
        self._matrices["Equilibria"] = {
            "sensor_id": "__equilibria__",
            "sensor_type": "equilibrium",
            "time": np.arange(len(equilibria), dtype=float),
            "columns": all_keys,
            "data": data,
            "x_label": "equilibrium index",
        }

    def get_matrix_names(self) -> list[str]:
        return list(self._matrices.keys())

    def get_matrix(self, name: str) -> tuple[np.ndarray, list[str]] | None:
        if name not in self._matrices:
            return None
        matrix = self._matrices[name]
        time_col = matrix["time"].reshape(-1, 1)
        data = np.hstack([time_col, matrix["data"]])
        x_label = matrix.get("x_label", "x")
        headers = [x_label] + list(matrix["columns"])
        return data, headers

    def get_sensor_metadata(self, name: str) -> dict | None:
        matrix = self._matrices.get(name)
        if matrix is None:
            return None
        return {
            "id": matrix.get("sensor_id"),
            "type": matrix.get("sensor_type"),
            "name": name,
        }

    def has_data(self) -> bool:
        return len(self._matrices) > 0


def load_from_csv(path: Path) -> tuple[np.ndarray, list[str], str]:
    """Load a CSV or TSV file and return (data_matrix, headers, name).

    First row is assumed to be column headers. If parsing fails or headers
    look numeric, integer column indices are used instead. The returned name
    is the file stem.
    """
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"Empty file: {path}")

    # Detect delimiter
    first = lines[0]
    delimiter = "\t" if first.count("\t") >= first.count(",") else ","

    # Try to parse header row
    candidate_headers = [h.strip() for h in first.split(delimiter)]
    try:
        [float(h) for h in candidate_headers]
        # All values look numeric → no header row, use indices
        headers: list[str] = [str(i) for i in range(len(candidate_headers))]
        data_lines = lines
    except ValueError:
        headers = candidate_headers
        data_lines = lines[1:]

    if not data_lines:
        raise ValueError(f"No data rows in file: {path}")

    rows: list[list[float]] = []
    for line in data_lines:
        parts = [p.strip() for p in line.split(delimiter)]
        try:
            rows.append([float(p) for p in parts])
        except ValueError:
            continue  # Skip non-numeric rows (e.g. trailing comments)

    if not rows:
        raise ValueError(f"No numeric data found in file: {path}")

    data = np.array(rows)
    # Pad headers if column count grew
    while len(headers) < data.shape[1]:
        headers.append(str(len(headers)))

    return data, headers[: data.shape[1]], path.stem
