import numpy as np

from quino.domain.model import SensorOutput
from quino.services.metric_data import build_metric_data, clean_channel_name


def test_clean_channel_name_strips_unit_bracket():
    assert clean_channel_name("x [mm]") == "x"
    assert clean_channel_name("v [mm/s]") == "v"
    assert clean_channel_name("angle [deg]") == "angle"
    assert clean_channel_name("x") == "x"  # already clean


def test_build_keys_use_clean_channel_from_decorated_columns():
    # The solver emits decorated columns like "x [mm]"; metric data must key by
    # the clean channel so data['Point Sensor1.x'] resolves.
    out = SensorOutput(
        sensor_id="sen1",
        time=[0.0, 0.1],
        columns=["x [mm]", "y [mm]", "v [mm/s]"],
        data=[[1.0, 2.0, 9.0], [3.0, 4.0, 8.0]],
    )
    data, _meta = build_metric_data(
        {"sen1": out}, {"sen1": "Point Sensor1"}, {}
    )
    assert "Point Sensor1.x" in data
    assert np.allclose(data["Point Sensor1.x"], [1.0, 3.0])
    assert "Point Sensor1.v" in data
    # the decorated form still resolves too (defensive)
    assert "Point Sensor1.x [mm]" in data


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
