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
    pose = svc.workspace.create_pose("Pose A", case_id=case.id)
    svc.workspace.create_analysis(
        "Dyn", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id,
    )
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


def test_case_node_does_not_show_standalone_analyses_subgroup(panel_with_workspace):
    """Analyses no longer have a top-level subgroup under the case; they
    appear under the pose they were created against."""
    panel, svc, baseline, case = panel_with_workspace
    case_item = panel._item_map[case.id]
    labels = [case_item.child(i).text(0) for i in range(case_item.childCount())]
    assert not any(l.startswith("Analyses ") for l in labels)


def test_analysis_hangs_off_its_pose(panel_with_workspace):
    panel, svc, baseline, case = panel_with_workspace
    pose = next(p for p in svc.project.workspace.poses if p.case_id == case.id and not p.is_default)
    pose_item = panel._item_map[pose.id]
    labels = [pose_item.child(i).text(0) for i in range(pose_item.childCount())]
    assert any("Dyn" in l for l in labels)


def test_create_analysis_without_pose_raises():
    svc = ApplicationService()
    svc.new_project("test")
    case = svc.workspace.create_case("C1")
    with pytest.raises(ValueError, match="workspace_pose_id"):
        svc.workspace.create_analysis("BadAnalysis", case_id=case.id)


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


def test_case_node_label_is_plain_name():
    """Cases use plain names in the workflow tree — counters live in the
    Diffs subgroup, not in the node label."""
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
    assert case_item.text(0) == "C1"


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


def test_rename_dialog_uses_undecorated_logical_name():
    """The rename popup must prefill with the bare case/baseline name, not
    with the decorated tree label (glyphs, "Case · ", counts). Otherwise
    repeated renames accumulate the prefix in the persisted name."""
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    svc = ApplicationService()
    svc.new_project("test")
    case = svc.workspace.create_case("MyCase")
    panel = WorkflowTreePanel(svc)
    panel.refresh()
    item = panel._item_map[case.id]
    # Display label is now plain — no glyph or "Case · " prefix.
    assert item.text(0) == "MyCase"
    # The logical-name helper must also return "MyCase" (no decorations).
    assert panel._logical_name("case", case.id) == "MyCase"


def test_tree_items_carry_type_icons():
    """Workflow tree items must have a non-null icon so the type is
    recognisable at a glance (Inventor-style browser)."""
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    svc = ApplicationService()
    svc.new_project("test")
    baseline = svc.project.workspace.baselines[0]
    case = svc.workspace.create_case("C1", baseline_id=baseline.id)
    pose = svc.workspace.create_pose("PoseA", case_id=case.id)
    svc.workspace.create_analysis("AnalysisA", case_id=case.id, workspace_pose_id=pose.id)
    panel = WorkflowTreePanel(svc)
    panel.refresh()

    assert not panel._item_map[baseline.id].icon(0).isNull()
    assert not panel._item_map[case.id].icon(0).isNull()


def test_subcase_uses_distinct_icon_from_top_case():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    svc = ApplicationService()
    svc.new_project("test")
    baseline = svc.project.workspace.baselines[0]
    parent = svc.workspace.create_case("Parent", baseline_id=baseline.id)
    child = svc.workspace.create_case("Child", parent_case_id=parent.id)
    panel = WorkflowTreePanel(svc)
    panel.refresh()

    parent_icon = panel._item_map[parent.id].icon(0)
    child_icon = panel._item_map[child.id].icon(0)
    assert not parent_icon.isNull()
    assert not child_icon.isNull()
    # Subcase pixmap should differ from top-level case pixmap.
    parent_pix = parent_icon.pixmap(16, 16).toImage()
    child_pix = child_icon.pixmap(16, 16).toImage()
    assert parent_pix != child_pix


def test_delete_run_context_action_removes_run(monkeypatch):
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from quino.domain.workspace import Run
    svc = ApplicationService()
    svc.new_project("t")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    a = svc.workspace.create_analysis("Bump", case_id=case.id, workspace_pose_id=pose.id)
    svc.project.workspace.runs.append(
        Run(id="r1", analysis_id=a.id, created_at="...", status="ok")
    )
    panel = WorkflowTreePanel(svc)
    panel.refresh()
    # Auto-accept confirmation dialog.
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    panel._delete_item("run", "r1", "Run …")
    assert not any(r.id == "r1" for r in svc.project.workspace.runs)


def test_runs_appear_under_their_analysis_newest_first():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from quino.domain.workspace import Run
    svc = ApplicationService()
    svc.new_project("t")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    a = svc.workspace.create_analysis("Bump", case_id=case.id, workspace_pose_id=pose.id)
    svc.project.workspace.runs.extend([
        Run(id="r1", analysis_id=a.id, created_at="2026-05-22T10:00:00Z", status="ok"),
        Run(id="r2", analysis_id=a.id, created_at="2026-05-22T10:05:00Z", status="failed"),
        Run(id="r3", analysis_id=a.id, created_at="2026-05-22T10:10:00Z", status="stale"),
    ])
    panel = WorkflowTreePanel(svc)
    panel.refresh()
    analysis_item = panel._item_map[a.id]
    run_labels = [analysis_item.child(i).text(0)
                  for i in range(analysis_item.childCount())]
    # Newest-first order
    assert run_labels[0].endswith("stale") or "stale" in run_labels[0]
    assert "ok" in run_labels[-1]
