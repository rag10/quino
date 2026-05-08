from __future__ import annotations

import numpy as np
from quino.domain.model import Project, SensorOutput


class SensorDataset:
    """Converts SensorOutput objects into plottable matrices (numpy arrays + headers)."""

    def __init__(self, project: Project):
        self.project = project
        self._matrices: dict[str, dict] = {}
        self._load_sensor_outputs()

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

    def get_matrix_names(self) -> list[str]:
        """Return list of available sensor matrix names."""
        return list(self._matrices.keys())

    def get_matrix(self, name: str) -> tuple[np.ndarray, list[str]] | None:
        """Get matrix data and headers by sensor name."""
        if name not in self._matrices:
            return None
        matrix = self._matrices[name]
        return matrix["data"], matrix["columns"]

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
