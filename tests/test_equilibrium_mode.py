import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.application.service import ApplicationService
from quino.domain.workspace import ResultRef
from quino.gui.main_window import MainWindow


def test_equilibrium_mode_lists_found_equilibria(qtbot, tmp_path) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("Eq", analysis_type="equilibrium", case_id=case.id, workspace_pose_id=pose.id)
    svc.current_project_path = tmp_path
    analysis.status = "ok"
    artifact_dir = tmp_path / "artifacts" / f"run_{analysis.id}"
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / "result.json"
    artifact_path.write_text(
        json.dumps(
            {
                "type": "equilibrium",
                "equilibria": [{"pose": {"b1": {"x": 0.0, "y": 0.0, "theta": 0.0}}, "perturbation": 0.05}],
            }
        ),
        encoding="utf-8",
    )
    analysis.result_ref = ResultRef(run_entry_id=analysis.id, artifact_path=str(artifact_path.relative_to(tmp_path)), checksum="sha256:test")
    window = MainWindow(svc)
    qtbot.addWidget(window)
    window._set_app_mode("analysis")
    window._set_app_mode_analysis(analysis)
    window._on_run_selected(analysis.id)
    ctrl = window._active_mode_controller
    assert ctrl.list_widget.count() == 1
    tabs = [ctrl.report.tabText(i) for i in range(ctrl.report.count())]
    assert "Metrics" in tabs
