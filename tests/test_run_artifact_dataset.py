"""RunArtifactDataset bridges persisted run artifacts to the plot widget."""
from __future__ import annotations

import numpy as np
import pytest

from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.viewer.dataset import RunArtifactDataset


def _project_with_point_sensor():
    svc = ApplicationService()
    svc.new_workspace("plot")
    bid = svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = svc.get_body(bid)
    marker_b = next(m for m in body.markers if m.name == "B")
    sensor_id = svc.create_sensor("PosB", "point", [marker_b.id])
    return svc.project, sensor_id


def test_kinematic_artifact_exposes_sensor_matrix() -> None:
    project, sensor_id = _project_with_point_sensor()
    # Mock a 5-point sweep producing a point-sensor row per cell.
    # point channels: x, y, vx, vy, ax, ay → 6 columns.
    n = 5
    sensor_values = []
    for i in range(n):
        sensor_values.extend([float(i), 0.0, 0.0, 0.0, 0.0, 0.0])
    artifact = {
        "type": "kinematic",
        "sweep_axes": [{"id": "sw1", "label": "marker B.x", "values": [0.0, 1.0, 2.0, 3.0, 4.0]}],
        "shape": [n],
        "sensors": {
            sensor_id: {
                "channels": ["x", "y", "vx", "vy", "ax", "ay"],
                "values": sensor_values,
            }
        },
    }
    dataset = RunArtifactDataset(project, artifact)
    assert dataset.has_data()
    assert dataset.get_matrix_names() == ["PosB"]
    matrix, headers = dataset.get_matrix("PosB")
    # Header: x_label + channels
    assert headers == ["marker B.x", "x", "y", "vx", "vy", "ax", "ay"]
    # 5 rows, 7 columns
    assert matrix.shape == (n, 7)
    # First column = sweep axis values
    np.testing.assert_array_equal(matrix[:, 0], [0.0, 1.0, 2.0, 3.0, 4.0])
    # 'x' channel column (col 1) = sensor's first channel
    np.testing.assert_array_equal(matrix[:, 1], [0.0, 1.0, 2.0, 3.0, 4.0])


def test_kinematic_artifact_handles_partial_runs() -> None:
    project, sensor_id = _project_with_point_sensor()
    # Sweep produced 3 cells; failure leaves NaNs but RunArtifactDataset
    # should still produce a valid matrix of the right shape.
    artifact = {
        "type": "kinematic",
        "sweep_axes": [{"id": "sw1", "label": "x", "values": [0.0, 1.0, 2.0]}],
        "shape": [3],
        "sensors": {
            sensor_id: {
                "channels": ["x", "y", "vx", "vy", "ax", "ay"],
                "values": [
                    0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                    float("nan"), float("nan"), 0.0, 0.0, 0.0, 0.0,
                    2.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                ],
            }
        },
    }
    dataset = RunArtifactDataset(project, artifact)
    matrix, headers = dataset.get_matrix("PosB")
    assert matrix.shape == (3, 7)
    assert np.isnan(matrix[1, 1])


def test_empty_or_unknown_artifact_yields_no_data() -> None:
    project, _ = _project_with_point_sensor()
    assert not RunArtifactDataset(project, {}).has_data()
    assert not RunArtifactDataset(project, {"type": "unknown"}).has_data()


def test_kinematic_artifact_skips_sensor_with_mismatched_values() -> None:
    project, sensor_id = _project_with_point_sensor()
    # 5 cells expected but only 12 floats for 6 channels (= 2 cells worth) →
    # reshape would still succeed at (2, 6) but len mismatch with x_values is
    # handled gracefully; in practice an artifact whose values don't divide
    # by channel count should be skipped without raising.
    artifact = {
        "type": "kinematic",
        "sweep_axes": [{"id": "sw1", "label": "x", "values": [0.0, 1.0, 2.0, 3.0, 4.0]}],
        "shape": [5],
        "sensors": {
            sensor_id: {
                "channels": ["x", "y", "vx", "vy", "ax", "ay"],
                "values": [0.0] * 13,  # not divisible by 6
            }
        },
    }
    dataset = RunArtifactDataset(project, artifact)
    # The matrix with bad shape is skipped, leaving no plottable data.
    assert not dataset.has_data()
