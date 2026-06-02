import numpy as np

from quino.domain.model import SensorOutput
from quino.services.metric_data import build_metric_data


def test_build_keys_by_sensor_name_and_column():
    out = SensorOutput(
        sensor_id="sen1",
        time=[0.0, 0.1, 0.2],
        columns=["x", "y"],
        data=[[1.0, 0.0], [2.0, 0.0], [3.0, 1.0]],  # rows x columns
    )
    data, meta = build_metric_data(
        {"sen1": out},
        sensor_name_by_id={"sen1": "thigh"},
        analysis_meta={"dt": 0.1},
    )
    assert "thigh.x" in data
    assert np.allclose(data["thigh.x"], [1.0, 2.0, 3.0])
    assert np.allclose(data["thigh.y"], [0.0, 0.0, 1.0])
    assert "t" in data
    assert np.allclose(data["t"], [0.0, 0.1, 0.2])
    assert meta["dt"] == 0.1


def test_empty_outputs_yield_empty_data():
    data, meta = build_metric_data({}, {}, {"dt": 0.01})
    assert data == {} or "t" not in data
    assert meta["dt"] == 0.01
