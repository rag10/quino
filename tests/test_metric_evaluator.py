from quino.domain.plotting import MetricDef
from quino.services.metric_evaluator import evaluate_metric


def test_metric_max_over_dynamic_run() -> None:
    artifact = {
        "type": "dynamic",
        "time": [0.0, 0.5, 1.0],
        "frames": [
            {"sensor:s_hub:y": 0.0},
            {"sensor:s_hub:y": 0.3},
            {"sensor:s_hub:y": 0.2},
        ],
    }
    metric = MetricDef(id="m", key="max_y", name="Max y", kind="max", target="s_hub:y")
    assert evaluate_metric(metric, artifact) == 0.3


def test_metric_value_at_t() -> None:
    artifact = {
        "time": [0.0, 0.5, 1.0],
        "frames": [
            {"sensor:s_hub:y": 0.0},
            {"sensor:s_hub:y": 0.3},
            {"sensor:s_hub:y": 0.2},
        ],
    }
    metric = MetricDef(id="m", key="y_at_0_5", name="...", kind="value_at_t", target="s_hub:y", params={"t": 0.5})
    assert evaluate_metric(metric, artifact) == 0.3


def test_metric_value_at_sweep() -> None:
    artifact = {
        "type": "kinematic",
        "shape": [2],
        "sensors": {"s_hub": {"channels": ["x", "y"], "values": [0.0, 1.0, 2.0, 3.0]}},
    }
    metric = MetricDef(
        id="m",
        key="y_at_1",
        name="...",
        kind="value_at_sweep",
        target="s_hub:y",
        params={"indices": [1]},
    )
    assert evaluate_metric(metric, artifact) == 3.0
