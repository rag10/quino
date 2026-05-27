from quino.domain.workspace import Workspace


def test_workspace_default_is_empty():
    ws = Workspace(id="w", name="x", schema_version="0.3.0")
    assert ws.cases == {}
    assert ws.root_case_ids == []
