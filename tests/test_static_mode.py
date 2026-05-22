import os
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.workspace import ResultRef, Run
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


def test_static_mode_metrics_tab_populates(qtbot, tmp_path) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("S", analysis_type="static", case_id=case.id, workspace_pose_id=pose.id)
    svc.current_project_path = tmp_path
    run = Run(id="run_001", analysis_id=analysis.id, created_at="now", status="ok", metrics={"spring_energy": 0.75})
    svc.project.workspace.runs.append(run)
    artifact_dir = tmp_path / "artifacts" / f"run_{run.id}"
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / "result.json"
    artifact_path.write_text(
        json.dumps({"type": "static", "applied_loads": [], "reactions": [], "spring_forces": [], "total_energy_in_springs": 0.75, "pose": {}}),
        encoding="utf-8",
    )
    run.result_ref = ResultRef(run_entry_id=run.id, artifact_path=str(artifact_path.relative_to(tmp_path)), checksum="sha256:test")
    window = MainWindow(svc)
    qtbot.addWidget(window)
    window._set_app_mode("analysis")
    window._set_app_mode_analysis(analysis)
    window._on_run_selected(run.id)
    ctrl = window._active_mode_controller
    tabs = [ctrl.report.tabText(i) for i in range(ctrl.report.count())]
    assert "Metrics" in tabs
