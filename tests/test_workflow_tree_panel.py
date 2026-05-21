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
    assert panel._tree.columnCount() == 1


def test_badge_shows_working(panel_with_workspace):
    panel, svc, baseline, case = panel_with_workspace
    svc.set_working_context(baseline_id=baseline.id)
    panel._update_badge()
    assert panel._badge.text() == "Working: Baseline 1"


def test_tree_has_baseline_node(panel_with_workspace):
    panel, svc, baseline, case = panel_with_workspace
    tree = panel._tree
    baseline_items = [
        tree.topLevelItem(i)
        for i in range(tree.topLevelItemCount())
        if "Baseline 1" in tree.topLevelItem(i).text(0)
    ]
    assert len(baseline_items) == 1


def test_tree_has_case_under_baseline(panel_with_workspace):
    panel, svc, baseline, case = panel_with_workspace
    tree = panel._tree
    baseline_item = next(
        tree.topLevelItem(i)
        for i in range(tree.topLevelItemCount())
        if "Baseline 1" in tree.topLevelItem(i).text(0)
    )
    # Cases live directly under the baseline (subgroups don't contain cases).
    found_case = False
    def _walk(item):
        nonlocal found_case
        for i in range(item.childCount()):
            child = item.child(i)
            if "Case 1" in child.text(0):
                found_case = True
                return
            _walk(child)
    _walk(baseline_item)
    assert found_case


def test_working_context_changed_signal_on_double_click(panel_with_workspace):
    panel, svc, baseline, case = panel_with_workspace
    fired = []
    panel.working_context_changed.connect(lambda: fired.append(True))
    case_item = panel._item_map[case.id]
    panel._on_item_double_clicked(case_item, 0)
    assert fired
    assert svc.project.workspace.active_case_id == case.id


# ----------------------------------------------------------------------
# Fase 4: subgroups, badges, duplicate
# ----------------------------------------------------------------------

def test_case_node_shows_poses_subgroup(panel_with_workspace):
    panel, svc, baseline, case = panel_with_workspace
    case_item = panel._item_map[case.id]
    labels = [case_item.child(i).text(0) for i in range(case_item.childCount())]
    assert any("Poses" in l for l in labels)


def test_case_node_shows_analyses_subgroup(panel_with_workspace):
    panel, svc, baseline, case = panel_with_workspace
    case_item = panel._item_map[case.id]
    labels = [case_item.child(i).text(0) for i in range(case_item.childCount())]
    assert any("Analyses" in l for l in labels)


def test_case_with_diffs_shows_diffs_subgroup_with_counts():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from quino.domain.workspace import ScalarValue
    from quino.domain.inputs import MarkerInput
    svc = ApplicationService()
    svc.new_project("test")
    body_id = svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    baseline = svc.workspace.create_baseline("BL")
    case = svc.workspace.create_case("C1", baseline_id=baseline.id)
    case.invariant_values[f"bodies/{body_id}/mass"] = ScalarValue(value=2.0, unit="kg")
    svc.set_working_context(case_id=case.id)
    svc.add_block(block_type="Constant", name="src", position=(0.0, 0.0))
    panel = WorkflowTreePanel(svc)
    panel.refresh()

    case_item = panel._item_map[case.id]
    diffs_labels = [
        case_item.child(i).text(0)
        for i in range(case_item.childCount())
        if "Diffs" in case_item.child(i).text(0)
    ]
    assert diffs_labels, "Case with diffs should show a Diffs subgroup"
    label = diffs_labels[0]
    assert "+1" in label  # one added block
    assert "~1" in label  # one invariant override


def test_case_node_label_carries_delta_badges():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from quino.domain.workspace import ScalarValue
    svc = ApplicationService()
    svc.new_project("test")
    body_id = svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    baseline = svc.workspace.create_baseline("BL")
    case = svc.workspace.create_case("C1", baseline_id=baseline.id)
    case.invariant_values[f"bodies/{body_id}/mass"] = ScalarValue(value=2.0, unit="kg")
    panel = WorkflowTreePanel(svc)
    panel.refresh()

    case_item = panel._item_map[case.id]
    label = case_item.text(0)
    assert "~1" in label, f"Expected ~1 badge in case label, got: {label!r}"


def test_duplicate_case_copies_diffs():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from quino.domain.workspace import ScalarValue
    svc = ApplicationService()
    svc.new_project("test")
    body_id = svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    baseline = svc.workspace.create_baseline("BL")
    case = svc.workspace.create_case("Source", baseline_id=baseline.id)
    case.invariant_values[f"bodies/{body_id}/mass"] = ScalarValue(value=4.0, unit="kg")

    dup = svc.workspace.duplicate_case(case.id)

    assert dup.id != case.id
    assert dup.parent_case_id == case.parent_case_id
    assert dup.baseline_id == case.baseline_id
    assert f"bodies/{body_id}/mass" in dup.invariant_values
    # Editing the duplicate does NOT touch the source.
    dup.invariant_values[f"bodies/{body_id}/mass"] = ScalarValue(value=9.0, unit="kg")
    assert case.invariant_values[f"bodies/{body_id}/mass"].value == 4.0


def test_breadcrumb_shows_subcase_chain():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    svc = ApplicationService()
    svc.new_project("test")
    baseline = svc.workspace.create_baseline("BL")
    parent = svc.workspace.create_case("Parent", baseline_id=baseline.id)
    child = svc.workspace.create_case("Child", parent_case_id=parent.id)
    svc.set_working_context(case_id=child.id)

    panel = WorkflowTreePanel(svc)
    panel.refresh()
    panel._update_badge()

    text = panel._badge.text()
    assert "BL" in text and "Parent" in text and "Child" in text
