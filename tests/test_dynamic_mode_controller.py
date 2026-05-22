from __future__ import annotations

from PySide6 import QtWidgets

from quino.application.service import ApplicationService
from quino.gui.analysis_modes import mode_controller_for
from quino.gui.analysis_modes._base import AnalysisModeController
from quino.gui.main_window import MainWindow


def test_dynamic_controller_is_registered() -> None:
    cls = mode_controller_for("dynamic")
    assert issubclass(cls, AnalysisModeController)


def test_dynamic_controller_install_unmount(qtbot) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("D", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id)

    window = MainWindow(svc)
    qtbot.addWidget(window)
    window._set_app_mode("analysis")
    window._set_app_mode_analysis(analysis)
    assert window._active_mode_controller.__class__.__name__ == "DynamicModeController"
    window._set_app_mode("model")
    assert window._active_mode_controller is None
