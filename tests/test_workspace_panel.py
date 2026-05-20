from __future__ import annotations

from unittest.mock import patch

from PySide6 import QtWidgets

from quino import ApplicationService
from quino.gui.panels.workspace_panel import WorkspacePanel


def _make_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_panel_shows_roots_when_empty() -> None:
    _make_app()
    app = ApplicationService()
    app.new_project("Test")
    panel = WorkspacePanel(app)
    panel.refresh()
    assert panel._tree.topLevelItemCount() == 4
    names = {panel._tree.topLevelItem(i).text(0) for i in range(4)}
    assert names == {"Baselines", "Cases", "Case Groups", "Studies"}


def test_panel_new_baseline_via_root() -> None:
    _make_app()
    app = ApplicationService()
    app.new_project("Test")
    panel = WorkspacePanel(app)
    panel.refresh()
    root = panel._tree.topLevelItem(0)
    panel._tree.setCurrentItem(root)

    with patch.object(QtWidgets.QInputDialog, "getItem", return_value=("Baseline", True)):
        with patch.object(QtWidgets.QInputDialog, "getText", return_value=("MyBaseline", True)):
            panel._on_new()

    assert len(app.project.workspace.baselines) == 1
    assert app.project.workspace.baselines[0].name == "MyBaseline"


def test_panel_new_case_via_root() -> None:
    _make_app()
    app = ApplicationService()
    app.new_project("Test")
    panel = WorkspacePanel(app)
    panel.refresh()
    root = panel._tree.topLevelItem(1)
    panel._tree.setCurrentItem(root)

    with patch.object(QtWidgets.QInputDialog, "getItem", return_value=("Case", True)):
        with patch.object(QtWidgets.QInputDialog, "getText", return_value=("MyCase", True)):
            panel._on_new()

    assert len(app.project.workspace.cases) == 1


def test_panel_new_study_via_root() -> None:
    _make_app()
    app = ApplicationService()
    app.new_project("Test")
    panel = WorkspacePanel(app)
    panel.refresh()
    root = panel._tree.topLevelItem(3)
    panel._tree.setCurrentItem(root)

    with patch.object(QtWidgets.QInputDialog, "getItem", return_value=("Study", True)):
        with patch.object(QtWidgets.QInputDialog, "getText", return_value=("MyStudy", True)):
            panel._on_new()

    # "Study" maps to "studies" in the dialog logic
    assert len(app.project.workspace.studies) == 1


def test_panel_run_button_enabled_on_study() -> None:
    _make_app()
    app = ApplicationService()
    app.new_project("Test")
    panel = WorkspacePanel(app)
    app.workspace.create_study("Dynamic")
    panel.refresh()
    study_item = panel._tree.topLevelItem(3).child(0)
    panel._tree.setCurrentItem(study_item)
    assert panel._run_btn.isEnabled()


def test_panel_rename_baseline() -> None:
    _make_app()
    app = ApplicationService()
    app.new_project("Test")
    panel = WorkspacePanel(app)
    baseline = app.workspace.create_baseline("OldName")
    panel.refresh()
    item = panel._item_map[baseline.id]
    panel._tree.setCurrentItem(item)

    with patch.object(QtWidgets.QInputDialog, "getText", return_value=("NewName", True)):
        panel._on_rename()

    assert app.project.workspace.baselines[0].name == "NewName"


def test_panel_delete_case() -> None:
    _make_app()
    app = ApplicationService()
    app.new_project("Test")
    panel = WorkspacePanel(app)
    case = app.workspace.create_case("ToDelete")
    panel.refresh()
    item = panel._item_map[case.id]
    panel._tree.setCurrentItem(item)

    with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Yes):
        panel._on_delete()

    assert len(app.project.workspace.cases) == 0


def test_panel_toolbar_disabled_when_nothing_selected() -> None:
    _make_app()
    app = ApplicationService()
    app.new_project("Test")
    panel = WorkspacePanel(app)
    panel.refresh()
    panel._tree.setCurrentItem(None)
    assert not panel._new_btn.isEnabled()
    assert not panel._rename_btn.isEnabled()
    assert not panel._delete_btn.isEnabled()
    assert not panel._run_btn.isEnabled()


def test_panel_refresh_keeps_roots_after_adding_item() -> None:
    _make_app()
    app = ApplicationService()
    app.new_project("Test")
    panel = WorkspacePanel(app)
    panel.refresh()
    assert panel._tree.topLevelItemCount() == 4

    app.workspace.create_baseline("B1")
    panel.refresh()
    assert panel._tree.topLevelItemCount() == 4
    baseline_root = panel._tree.topLevelItem(0)
    assert baseline_root.childCount() == 1
    assert baseline_root.child(0).text(0) == "B1"
