"""Active-case highlight: poses/analyses of the active case get a soft-blue
background and the case auto-expands; subcases are NOT tinted."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from quino.application.service import ApplicationService
from quino.gui.panels.workflow_tree_panel import (
    ROLE_ACTIVE_TINT,
    ROLE_NODE_KIND,
    WorkflowTreePanel,
)
from quino.services.case_cascading import CascadingEngine


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _children_of_kind(item, kind):
    out = []
    for i in range(item.childCount()):
        child = item.child(i)
        if child.data(0, ROLE_NODE_KIND) == kind:
            out.append(child)
    return out


def test_active_case_tints_default_pose_and_expands():
    _app()
    svc = ApplicationService()
    svc.new_workspace("W")
    ws = svc._workspace
    root_id = ws.root_case_ids[0]
    ws.selected_case_id = root_id

    panel = WorkflowTreePanel(svc)
    panel.refresh()
    root_item = panel.top_level_items()[0]

    assert root_item.isExpanded() is True
    default_poses = _children_of_kind(root_item, "default_pose")
    assert default_poses
    # The active-scope tint is carried by the ROLE_ACTIVE_TINT flag (painted by
    # the delegate; the QSS forces item backgrounds transparent).
    assert default_poses[0].data(0, ROLE_ACTIVE_TINT) is True


def test_inactive_case_pose_not_tinted():
    _app()
    svc = ApplicationService()
    svc.new_workspace("W")
    ws = svc._workspace
    root_id = ws.root_case_ids[0]
    # Activate a forked child, so the ROOT case is inactive.
    child_id = CascadingEngine(ws).fork_case(root_id, "Child")
    ws.selected_case_id = child_id

    panel = WorkflowTreePanel(svc)
    panel.refresh()
    root_item = panel.top_level_items()[0]

    default_poses = _children_of_kind(root_item, "default_pose")
    assert default_poses
    assert not default_poses[0].data(0, ROLE_ACTIVE_TINT)


def test_active_case_does_not_tint_subcases_group():
    _app()
    svc = ApplicationService()
    svc.new_workspace("W")
    ws = svc._workspace
    root_id = ws.root_case_ids[0]
    CascadingEngine(ws).fork_case(root_id, "Child")
    ws.selected_case_id = root_id

    panel = WorkflowTreePanel(svc)
    panel.refresh()
    root_item = panel.top_level_items()[0]

    sub_groups = _children_of_kind(root_item, "subcases_group")
    assert sub_groups
    assert not sub_groups[0].data(0, ROLE_ACTIVE_TINT)
