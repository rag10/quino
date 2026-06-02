from quino.domain.workspace import Analysis, Metric


def test_analysis_has_flattened_run_state():
    a = Analysis(id="an1", name="Dyn", analysis_type="dynamic")
    assert a.status == "to_be_run"
    assert a.finished_at is None
    assert a.artifacts == []
    assert a.warnings == []
    assert a.error_message == ""
    assert a.metrics == []


def test_analysis_accepts_metrics():
    a = Analysis(id="an1", name="Dyn", metrics=[Metric(id="m", name="x")])
    assert a.metrics[0].id == "m"


def test_analysis_rejects_bad_status():
    import pytest
    with pytest.raises(ValueError):
        Analysis(id="an1", name="Dyn", status="bogus")
