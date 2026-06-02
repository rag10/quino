import numpy as np

from quino.domain.workspace import Metric
from quino.services.metric_evaluator import evaluate


def test_eval_returns_float():
    m = Metric(id="m", name="final", value_type="float",
               code="var = data['s1.x']\nreturn var[-1]")
    res = evaluate(m, {"s1.x": np.array([1.0, 2.0, 3.0])}, meta={})
    assert res.status == "ok"
    assert res.value == 3.0


def test_eval_bool_cast():
    m = Metric(id="m", name="thr", value_type="bool",
               code="return data['s1.x'][-1] > 10")
    res = evaluate(m, {"s1.x": np.array([1.0, 12.0])}, meta={})
    assert res.status == "ok"
    assert res.value is True


def test_eval_uses_meta():
    m = Metric(id="m", name="dt", value_type="float", code="return meta['dt']")
    res = evaluate(m, {}, meta={"dt": 0.01})
    assert res.value == 0.01


def test_eval_blocks_import():
    m = Metric(id="m", name="bad", code="import os\nreturn 1")
    res = evaluate(m, {}, meta={})
    assert res.status == "error"


def test_eval_runtime_error_is_captured():
    m = Metric(id="m", name="bad", code="return data['missing'][0]")
    res = evaluate(m, {}, meta={})
    assert res.status == "error"


def test_evaluate_all_marks_no_data_when_empty():
    from quino.domain.workspace import Analysis
    a = Analysis(id="an", name="x", metrics=[Metric(id="m", name="x", code="return 1")])
    from quino.services.metric_evaluator import evaluate_all
    evaluate_all(a, {}, {})
    assert a.metrics[0].result.status == "no_data"
