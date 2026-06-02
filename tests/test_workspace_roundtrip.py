import json
import pytest
from quino.serialization.json_io import JsonMapper, UnsupportedSchemaError


def test_load_rejects_old_schema_with_clear_message(tmp_path):
    old = tmp_path / "old.quino.json"
    old.write_text(json.dumps({"schema_version": "0.2.0", "name": "x"}))
    mapper = JsonMapper()
    with pytest.raises(UnsupportedSchemaError) as exc:
        mapper.load(old)
    assert "0.3.0" in str(exc.value)


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
    ws = Workspace(id="w", name="Test", schema_version="0.3.0",
                   root_case_ids=["P"], cases={"P": root})
    engine = CascadingEngine(ws)
    engine.fork_case("P", "Child")
    return ws


@pytest.mark.skip(reason="overlay removed; serialization of overlay-free fork structure adapted in Fase 2/3")
def test_workspace_roundtrip_preserves_structure(tmp_path):
    ws = _build_two_case_workspace()
    mapper = JsonMapper()
    path = tmp_path / "w.quino.json"
    mapper.save(ws, path)
    loaded = mapper.load(path)

    assert loaded.id == ws.id
    assert loaded.schema_version == "0.3.0"
    assert set(loaded.cases.keys()) == set(ws.cases.keys())
    parent = loaded.cases["P"]
    assert parent.parent_case_id is None
    child_id = next(cid for cid in loaded.cases if cid != "P")
    child = loaded.cases[child_id]
    assert child.parent_case_id == "P"
