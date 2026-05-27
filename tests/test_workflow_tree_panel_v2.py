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


def _collect_items(root, kind_filter=None):
    """Recursively collect all QTreeWidgetItems with optional node-kind filter."""
    from quino.gui.panels.workflow_tree_panel import ROLE_NODE_KIND
    results = []
    def walk(item):
        if kind_filter is None or item.data(0, ROLE_NODE_KIND) == kind_filter:
            results.append(item)
        for i in range(item.childCount()):
            walk(item.child(i))
    walk(root)
    return results


def test_panel_shows_root_case(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()
    items = panel.top_level_items()
    assert len(items) == 1
    # The case name "Root" should appear somewhere in the label text
    assert "Root" in items[0].text(0)


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
    # Child cases are nested anywhere under root with node kind "case"
    child_cases = _collect_items(root_item, kind_filter="case")
    child_labels = [i.text(0) for i in child_cases]
    assert any("Child A" in lbl for lbl in child_labels)


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
