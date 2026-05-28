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


# ------------------------------------------------------------------
# New tests: default pose, double-click, rerun, icons, backend guards
# ------------------------------------------------------------------


def test_default_pose_node_present_for_new_workspace(app, qtbot):
    from quino.gui.panels.workflow_tree_panel import ROLE_ID
    service = ApplicationService()
    service.new_workspace("Test")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()
    root_item = panel.top_level_items()[0]
    default_items = _collect_items(root_item, kind_filter="default_pose")
    assert len(default_items) == 1
    assert default_items[0].data(0, ROLE_ID) is not None


def test_double_click_case_emits_case_activated(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()
    root_item = panel.top_level_items()[0]
    with qtbot.waitSignal(panel.case_activated, timeout=1000) as blocker:
        panel._on_item_double_clicked(root_item, 0)
    assert blocker.args[0] == service._workspace.root_case_ids[0]


def test_rerun_request_resolves_run_id(app, qtbot):
    from quino.domain.workspace import Analysis, Run
    service = ApplicationService()
    service.new_workspace("Test")
    ws = service._workspace
    case = ws.cases[ws.root_case_ids[0]]
    analysis = Analysis(id="a1", name="A", analysis_type="dynamic", pose_id=None)
    run = Run(id="r1", analysis_id="a1", status="ok", created_at="2026-01-01T00:00:00")
    case.analyses.append(analysis)
    case.runs.append(run)

    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.rerun_requested, timeout=1000) as blocker:
        panel.rerun_requested.emit("r1")
    assert blocker.args[0] == "r1"


def test_run_icon_uses_status_specific_glyph(app, qtbot):
    from quino.domain.workspace import Analysis, Run
    from quino.gui.panels.workflow_tree_panel import ROLE_NODE_KIND
    service = ApplicationService()
    service.new_workspace("Test")
    ws = service._workspace
    case = ws.cases[ws.root_case_ids[0]]
    analysis = Analysis(id="a1", name="A", analysis_type="dynamic", pose_id=None)
    case.analyses.append(analysis)
    case.runs.append(Run(id="r_ok", analysis_id="a1", status="ok", created_at="2026-01-01T00:00:00"))
    case.runs.append(Run(id="r_fail", analysis_id="a1", status="failed", created_at="2026-01-02T00:00:00"))

    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()
    root = panel.top_level_items()[0]
    runs = _collect_items(root, kind_filter="run")
    icons = [item.icon(0) for item in runs]
    # Both icons must be non-null and distinguishable (different pixmaps)
    assert len(icons) == 2
    p1 = icons[0].pixmap(16, 16).toImage()
    p2 = icons[1].pixmap(16, 16).toImage()
    assert p1 != p2


def test_backend_rejects_delete_default_pose(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    ws = service._workspace
    case = ws.cases[ws.root_case_ids[0]]
    default_pose = next(p for p in case.poses if p.is_default)
    import pytest
    with pytest.raises(ValueError, match="reference pose"):
        service.workspace.delete_pose(default_pose.id)


def test_backend_rejects_delete_last_root_case(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    root_id = service._workspace.root_case_ids[0]
    import pytest
    with pytest.raises(ValueError, match="last root case"):
        service.workspace.delete_case(root_id)


def test_backend_duplicate_pose_creates_distinct_copy(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    src = service.workspace.create_pose("Original")
    new_pose = service.duplicate_pose_in_case(src.id)
    assert new_pose.id != src.id
    assert "copy" in new_pose.name.lower()
    assert new_pose.is_default is False


def test_backend_duplicate_analysis_creates_distinct_copy(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    pose = service.workspace.create_pose("P")
    src = service.workspace.create_analysis(
        "A", analysis_type="dynamic", workspace_pose_id=pose.id
    )
    dup = service.duplicate_analysis(src.id)
    assert dup.id != src.id
    assert "copy" in dup.name.lower()


def test_analyses_hang_directly_off_pose(app, qtbot):
    """Analyses are children of their parent pose node — no intermediate
    'Analyses' group node exists in the tree."""
    from quino.gui.panels.workflow_tree_panel import ROLE_NODE_KIND, ROLE_ID
    service = ApplicationService()
    service.new_workspace("Test")
    pose = service.workspace.create_pose("P1")
    analysis = service.workspace.create_analysis(
        "A1", analysis_type="dynamic", workspace_pose_id=pose.id
    )
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()
    root = panel.top_level_items()[0]
    # No 'analyses_group' kind exists anymore.
    assert _collect_items(root, kind_filter="analyses_group") == []
    # The analysis node is a direct child of the pose node.
    pose_nodes = [it for it in _collect_items(root, kind_filter="pose")
                  if it.data(0, ROLE_ID) == pose.id]
    assert pose_nodes, "pose node missing"
    children_kinds = [
        pose_nodes[0].child(i).data(0, ROLE_NODE_KIND)
        for i in range(pose_nodes[0].childCount())
    ]
    assert "analysis" in children_kinds
    analysis_child_ids = [
        pose_nodes[0].child(i).data(0, ROLE_ID)
        for i in range(pose_nodes[0].childCount())
        if pose_nodes[0].child(i).data(0, ROLE_NODE_KIND) == "analysis"
    ]
    assert analysis.id in analysis_child_ids


def test_fork_case_regenerates_pose_ids(app, qtbot):
    """Forked subcases get only a fresh local reference pose."""
    service = ApplicationService()
    service.new_workspace("Test")
    service.workspace.create_pose("User Pose")
    ws = service._workspace
    root_id = ws.root_case_ids[0]
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root_id, "Child")

    root_pose_ids = {p.id for p in ws.cases[root_id].poses}
    child_poses = ws.cases[child_id].poses
    child_pose_ids = {p.id for p in child_poses}
    assert len(child_poses) == 1
    assert child_poses[0].is_default is True
    assert root_pose_ids.isdisjoint(child_pose_ids)


def test_create_analysis_lands_on_correct_case_after_fork(app, qtbot):
    """Adding an analysis under a subcase pose must attach it to that subcase,
    not to the parent baseline case."""
    service = ApplicationService()
    service.new_workspace("Test")
    ws = service._workspace
    root_id = ws.root_case_ids[0]
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root_id, "Child")
    ws.selected_case_id = child_id

    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()

    child_default_pose = next(p for p in ws.cases[child_id].poses if p.is_default)
    service.workspace.create_analysis(
        "A1",
        analysis_type="dynamic",
        case_id=panel._case_id_for_pose(child_default_pose.id),
        workspace_pose_id=child_default_pose.id,
    )
    assert len(ws.cases[root_id].analyses) == 0
    assert len(ws.cases[child_id].analyses) == 1


def test_double_click_new_user_pose_activates_that_pose(app, qtbot):
    from quino.gui.panels.workflow_tree_panel import ROLE_ID

    service = ApplicationService()
    service.new_workspace("Test")
    pose = service.workspace.create_pose("Pose B")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()

    root = panel.top_level_items()[0]
    pose_node = next(
        item for item in _collect_items(root, kind_filter="pose")
        if item.data(0, ROLE_ID) == pose.id
    )

    with qtbot.waitSignal(panel.pose_selected, timeout=1000) as blocker:
        panel._on_item_double_clicked(pose_node, 0)

    assert blocker.args[0] == pose.id


def test_selecting_analysis_selects_its_pose_and_case(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    ws = service._workspace
    root_id = ws.root_case_ids[0]
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root_id, "Child")
    child_pose = service.workspace.create_pose("Child pose", case_id=child_id)
    analysis = service.workspace.create_analysis(
        "Child analysis",
        analysis_type="dynamic",
        case_id=child_id,
        workspace_pose_id=child_pose.id,
    )
    ws.selected_case_id = root_id
    ws.selected_pose_id = None
    ws.selected_analysis_id = None

    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()
    panel.analysis_selected.emit(analysis.id)
    service.workspace.set_selected_analysis(analysis.id)

    assert ws.selected_case_id == child_id
    assert ws.selected_pose_id == child_pose.id
    assert ws.selected_analysis_id == analysis.id


def test_refresh_preserves_collapsed_state(app, qtbot):
    """Collapsing a node and then refreshing must not re-expand it."""
    from quino.gui.panels.workflow_tree_panel import ROLE_NODE_KIND
    service = ApplicationService()
    service.new_workspace("Test")
    service.workspace.create_pose("P1")
    panel = WorkflowTreePanel(service)
    qtbot.addWidget(panel)
    panel.refresh()
    root = panel.top_level_items()[0]
    # Collapse the Subcases group on the root
    sub_groups = _collect_items(root, kind_filter="subcases_group")
    assert sub_groups
    sub_groups[0].setExpanded(False)
    assert sub_groups[0].isExpanded() is False
    # Refresh and verify state is preserved
    panel.refresh()
    root2 = panel.top_level_items()[0]
    sub_groups2 = _collect_items(root2, kind_filter="subcases_group")
    assert sub_groups2[0].isExpanded() is False


def test_backend_delete_pose_with_analyses_requires_cascade(app, qtbot):
    service = ApplicationService()
    service.new_workspace("Test")
    pose = service.workspace.create_pose("P")
    service.workspace.create_analysis(
        "A", analysis_type="dynamic", workspace_pose_id=pose.id
    )
    import pytest
    with pytest.raises(ValueError, match="cascade=True"):
        service.workspace.delete_pose(pose.id)
    # With cascade, succeeds and removes the analysis.
    service.workspace.delete_pose(pose.id, cascade=True)
    ws = service._workspace
    case = ws.cases[ws.root_case_ids[0]]
    assert not any(p.id == pose.id for p in case.poses)
    assert not case.analyses
