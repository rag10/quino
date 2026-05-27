import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtWidgets

from quino.application.service import ApplicationService
from quino.gui.panels.workflow_tree_panel import WorkflowTreePanel
from quino.services.case_cascading import CascadingEngine


@pytest.fixture
def app(qtbot):
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_panel_shows_root_case(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()
    items = panel.top_level_items()
    assert len(items) == 1
    assert items[0].text(0) == "Root"


def test_panel_shows_child_case_under_parent(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    ws = service._workspace
    engine = CascadingEngine(ws)
    root_id = ws.root_case_ids[0]
    engine.fork_case(root_id, "Child A")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()
    root_item = panel.top_level_items()[0]
    # Find the "children_group" node
    children_group = None
    for i in range(root_item.childCount()):
        child = root_item.child(i)
        if child.data(0, 0x0100) == "children_group":
            children_group = child
            break
    assert children_group is not None
    child_names = [children_group.child(i).text(0) for i in range(children_group.childCount())
                   if children_group.child(i).data(0, 0x0100) == "case"]
    assert "Child A" in child_names


def test_fork_via_panel(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()

    root_id = service._workspace.root_case_ids[0]
    panel.fork_case(root_id, "Variant 1")
    panel.refresh()

    assert len(service._workspace.cases) == 2
    assert service._workspace.selected_case_id != root_id


def test_rename_case(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)

    root_id = service._workspace.root_case_ids[0]
    panel.rename_case(root_id, "Renamed Root")
    assert service._workspace.cases[root_id].name == "Renamed Root"


def test_delete_child_case(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    ws = service._workspace
    engine = CascadingEngine(ws)
    root_id = ws.root_case_ids[0]
    child_id = engine.fork_case(root_id, "Child")
    assert len(ws.cases) == 2

    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.delete_case(child_id)
    assert len(ws.cases) == 1
    assert child_id not in ws.cases
