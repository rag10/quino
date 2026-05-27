from __future__ import annotations

from quino import ApplicationService, MarkerInput
from quino.serialization.json_io import JsonMapper


def test_end_to_end_new_workspace_roundtrips(tmp_path) -> None:
    app = ApplicationService()
    app.new_workspace("Test")
    app.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))

    path = tmp_path / "ws.quino.json"
    app.save_workspace(str(path))

    mapper = JsonMapper()
    ws = mapper.load(str(path))

    assert ws is not None
    assert len(ws.cases) >= 1
    case = ws.cases[ws.root_case_ids[0]]
    assert len(case.model.bodies) >= 1
