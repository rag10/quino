import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.gui.main_window import MainWindow


def test_static_mode_shows_dof_banner(qtbot) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("S", analysis_type="static", case_id=case.id, workspace_pose_id=pose.id)
    window = MainWindow(svc)
    qtbot.addWidget(window)
    window._set_app_mode("analysis")
    window._set_app_mode_analysis(analysis)
    ctrl = window._active_mode_controller
    assert "DoF" in ctrl.banner.text()
    assert not ctrl.banner.isHidden()
