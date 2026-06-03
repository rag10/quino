"""OK->Partial confirmation prompt: when the executor signals
run_needs_confirmation, MainWindow asks the user and calls confirm_partial
with the chosen overwrite decision."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from quino.application.service import ApplicationService
from quino.gui.main_window import MainWindow


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _make_window():
    _app()
    svc = ApplicationService()
    svc.new_project("t")
    win = MainWindow(svc)
    case = svc.current_case()
    analysis = svc.workspace.create_analysis(
        "D", case_id=case.id, workspace_pose_id=None
    )
    return win, svc, analysis.id


def test_prompt_yes_calls_confirm_partial_overwrite(monkeypatch):
    win, svc, analysis_id = _make_window()
    calls = []
    monkeypatch.setattr(
        svc.executor, "confirm_partial",
        lambda aid, overwrite: calls.append((aid, overwrite)),
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes,
    )
    win._on_executor_run_needs_confirmation(analysis_id)
    assert calls == [(analysis_id, True)]


def test_prompt_no_calls_confirm_partial_keep(monkeypatch):
    win, svc, analysis_id = _make_window()
    calls = []
    monkeypatch.setattr(
        svc.executor, "confirm_partial",
        lambda aid, overwrite: calls.append((aid, overwrite)),
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.No,
    )
    win._on_executor_run_needs_confirmation(analysis_id)
    assert calls == [(analysis_id, False)]
