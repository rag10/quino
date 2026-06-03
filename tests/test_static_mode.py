import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.workspace import Analysis, ResultRef
from quino.gui.main_window import MainWindow


def _setup_svc():
    svc = ApplicationService()
    svc.new_workspace("t")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    analysis = Analysis(id="a1", name="S", analysis_type="static")
    case.analyses.append(analysis)
    return svc, case, analysis


def test_static_mode_shows_dof_banner(qtbot) -> None:
    svc, case, analysis = _setup_svc()
    svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    window = MainWindow(svc)
    qtbot.addWidget(window)
    window._set_app_mode("analysis")
    window._set_app_mode_analysis(analysis)
    ctrl = window._active_mode_controller
    assert "DoF" in ctrl.banner.text()
    assert not ctrl.banner.isHidden()


def test_static_mode_metrics_tab_populates(qtbot, tmp_path) -> None:
    svc, case, analysis = _setup_svc()
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    svc.current_project_path = tmp_path
    analysis.status = "ok"
    artifact_dir = tmp_path / "artifacts" / f"run_{analysis.id}"
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / "result.json"
    artifact_path.write_text(
        json.dumps(
            {
                "type": "static",
                "applied_loads": [],
                "reactions": [],
                "spring_forces": [],
                "total_energy_in_springs": 0.75,
                "pose": {},
            }
        ),
        encoding="utf-8",
    )
    analysis.result_ref = ResultRef(
        run_entry_id=analysis.id,
        artifact_path=str(artifact_path.relative_to(tmp_path)),
        checksum="sha256:test",
    )
    window = MainWindow(svc)
    qtbot.addWidget(window)
    window._set_app_mode("analysis")
    window._set_app_mode_analysis(analysis)
    window._on_run_selected(analysis.id)
    ctrl = window._active_mode_controller
    tabs = [ctrl.report.tabText(i) for i in range(ctrl.report.count())]
    assert "Metrics" in tabs
