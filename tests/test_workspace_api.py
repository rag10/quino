from quino import ApplicationService
from quino.domain.workspace import Case, Workspace
from quino.services.case_cascading import CascadingEngine


def test_new_workspace_creates_root_case():
    app = ApplicationService()
    ws = app.new_workspace("Test")
    assert isinstance(ws, Workspace)
    assert len(ws.root_case_ids) == 1
    root_id = ws.root_case_ids[0]
    assert isinstance(ws.cases[root_id], Case)
    assert ws.selected_case_id == root_id


def test_fork_case_adds_child():
    app = ApplicationService()
    ws = app.new_workspace("Test")
    root_id = ws.root_case_ids[0]
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root_id, "Child")
    assert child_id in ws.cases
    assert ws.cases[child_id].parent_case_id == root_id
