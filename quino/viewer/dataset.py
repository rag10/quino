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
