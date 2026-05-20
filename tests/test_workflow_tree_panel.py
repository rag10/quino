import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from quino.application.service import ApplicationService
from quino.gui.panels.workflow_tree_panel import WorkflowTreePanel


@pytest.fixture
def panel_with_workspace():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    svc = ApplicationService()
    svc.new_project("test")
    baseline = svc.workspace.create_baseline("Baseline 1")
    case = svc.workspace.create_case("Case 1", baseline_id=baseline.id)
    svc.workspace.create_pose("Pose A", case_id=case.id)
    svc.workspace.create_analysis("Dyn", analysis_type="dynamic", case_id=case.id)
    panel = WorkflowTreePanel(svc)
    panel.refresh()
    return panel, svc, baseline, case


def test_panel_creates(panel_with_workspace):
    panel, *_ = panel_with_workspace
    assert panel is not None


def test_badge_shows_working(panel_with_workspace):
    panel, svc, baseline, case = panel_with_workspace
    assert "Working" in panel._badge.text()


def test_tree_has_baseline_node(panel_with_workspace):
    panel, svc, baseline, case = panel_with_workspace
    tree = panel._tree
    baseline_items = [
        tree.topLevelItem(i)
        for i in range(tree.topLevelItemCount())
        if tree.topLevelItem(i).text(0) == "Baseline 1"
    ]
    assert len(baseline_items) == 1


def test_tree_has_case_under_baseline(panel_with_workspace):
    panel, svc, baseline, case = panel_with_workspace
    tree = panel._tree
    baseline_item = next(
        tree.topLevelItem(i)
        for i in range(tree.topLevelItemCount())
        if tree.topLevelItem(i).text(0) == "Baseline 1"
    )
    child_texts = [baseline_item.child(i).text(0) for i in range(baseline_item.childCount())]
    assert any("Case 1" in t for t in child_texts)


def test_working_context_changed_signal_on_double_click(panel_with_workspace):
    panel, svc, baseline, case = panel_with_workspace
    fired = []
    panel.working_context_changed.connect(lambda: fired.append(True))
    tree = panel._tree
    baseline_item = next(
        tree.topLevelItem(i)
        for i in range(tree.topLevelItemCount())
        if tree.topLevelItem(i).text(0) == "Baseline 1"
    )
    case_item = next(
        baseline_item.child(i)
        for i in range(baseline_item.childCount())
        if "Case 1" in baseline_item.child(i).text(0)
    )
    panel._on_item_double_clicked(case_item, 0)
    assert fired
    assert svc.project.workspace.active_case_id == case.id
