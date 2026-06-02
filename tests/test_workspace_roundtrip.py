import json
import pytest
from quino.serialization.json_io import JsonMapper, UnsupportedSchemaError


def test_load_rejects_old_schema_with_clear_message(tmp_path):
    old = tmp_path / "old.quino.json"
    old.write_text(json.dumps({"schema_version": "0.2.0", "name": "x"}))
    mapper = JsonMapper()
    with pytest.raises(UnsupportedSchemaError) as exc:
        mapper.load(old)
    assert "0.4.0" in str(exc.value)


def test_load_rejects_0_3_0(tmp_path):
    p = tmp_path / "old.quino.json"
    p.write_text(json.dumps({"schema_version": "0.3.0", "id": "w", "name": "x",
                             "root_case_ids": [], "cases": {}}))
    with pytest.raises(UnsupportedSchemaError):
        JsonMapper().load(p)


from quino.domain.model import Body, Marker, Model, ScalarProperty
from quino.domain.types import BodyType, Dimension, MarkerType
from quino.domain.workspace import Case, Workspace
from quino.services.case_cascading import CascadingEngine


def _build_two_case_workspace() -> Workspace:
    marker_a = Marker(id="m1", name="A", type=MarkerType.STRUCTURAL,
                      x=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
                      y=ScalarProperty("0 mm", "mm", Dimension.LENGTH))
    marker_b = Marker(id="m2", name="B", type=MarkerType.STRUCTURAL,
                      x=ScalarProperty("100 mm", "mm", Dimension.LENGTH),
                      y=ScalarProperty("0 mm", "mm", Dimension.LENGTH))
    body = Body(id="b1", name="bar", type=BodyType.BAR, markers=[marker_a, marker_b],
                edge_order=["m1", "m2"], closed_shape=False,
                mass=ScalarProperty("2 kg", "kg", Dimension.MASS))
    root = Case(id="P", name="Root", model=Model(bodies=[body]))
    ws = Workspace(id="w", name="Test", schema_version="0.4.0",
                   root_case_ids=["P"], cases={"P": root})
    engine = CascadingEngine(ws)
    engine.fork_case("P", "Child")
    return ws


def test_workspace_roundtrip_preserves_structure(tmp_path):
    ws = _build_two_case_workspace()
    mapper = JsonMapper()
    path = tmp_path / "w.quino.json"
    mapper.save(ws, path)
    loaded = mapper.load(path)

    assert loaded.id == ws.id
    assert loaded.schema_version == "0.4.0"
    assert set(loaded.cases.keys()) == set(ws.cases.keys())
    parent = loaded.cases["P"]
    assert parent.parent_case_id is None
    child_id = next(cid for cid in loaded.cases if cid != "P")
    child = loaded.cases[child_id]
    assert child.parent_case_id == "P"


def test_roundtrip_preserves_analysis_runstate_and_metrics(tmp_path):
    from quino.domain.model import Model as _Model
    from quino.domain.workspace import Analysis, Case, Metric, MetricResult, Workspace
    a = Analysis(
        id="an1", name="Dyn", analysis_type="dynamic", status="ok",
        created_at="2026-06-02T00:00:00+00:00", finished_at="2026-06-02T00:01:00+00:00",
        error_message="", warnings=["w1"],
        metrics=[Metric(id="m1", name="final", description="d", value_type="float",
                        code="return data['s.x'][-1]",
                        result=MetricResult(value=3.0, status="ok",
                                            evaluated_at="2026-06-02T00:01:00+00:00"))],
    )
    case = Case(id="c", name="root", model=_Model(), analyses=[a])
    ws = Workspace(id="w", name="w", schema_version="0.4.0", root_case_ids=["c"], cases={"c": case})
    p = tmp_path / "ws.quino.json"
    JsonMapper().save(ws, p)
    loaded = JsonMapper().load(p)
    la = loaded.cases["c"].analyses[0]
    assert la.status == "ok"
    assert la.created_at == "2026-06-02T00:00:00+00:00"
    assert la.warnings == ["w1"]
    assert la.metrics[0].code == "return data['s.x'][-1]"
    assert la.metrics[0].value_type == "float"
    assert la.metrics[0].result is not None
    assert la.metrics[0].result.value == 3.0
    assert la.metrics[0].result.status == "ok"


def test_roundtrip_has_no_overlay_or_runs(tmp_path):
    from quino.domain.model import Model as _Model
    from quino.domain.workspace import Case, Workspace
    ws = Workspace(id="w", name="w", schema_version="0.4.0", root_case_ids=["c"],
                   cases={"c": Case(id="c", name="root", model=_Model())})
    p = tmp_path / "ws.quino.json"
    JsonMapper().save(ws, p)
    blob = p.read_text(encoding="utf-8")
    assert "overlay" not in blob
    assert '"runs"' not in blob
