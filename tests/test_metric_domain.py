from quino.domain.workspace import Metric, MetricResult


def test_metric_defaults():
    m = Metric(id="mt1", name="Final pos")
    assert m.value_type == "float"
    assert m.code == ""
    assert m.result is None


def test_metric_result_fields():
    r = MetricResult(value=12.3, status="ok")
    assert r.value == 12.3
    assert r.status == "ok"
    assert r.error == ""
    assert r.evaluated_at is None
