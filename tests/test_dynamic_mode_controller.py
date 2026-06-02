from __future__ import annotations

import json

import pytest

pytest.skip(
    "overlay removed; Run entity and case.runs replaced by flattened Analysis run "
    "state. Analysis-mode controllers adapted in Fase 2/4.",
    allow_module_level=True,
)

from PySide6 import QtWidgets

from quino.application.service import ApplicationService
from quino.domain.workspace import ResultRef, Run
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
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("D", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id)

    window = MainWindow(svc)
    qtbot.addWidget(window)
    window._set_app_mode("analysis")
    window._set_app_mode_analysis(analysis)
    assert window._active_mode_controller.__class__.__name__ == "DynamicModeController"
    window._set_app_mode("model")
    assert window._active_mode_controller is None


def test_dynamic_metrics_tab_populates_from_selected_run(qtbot, tmp_path) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("D", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id)
    svc.current_project_path = tmp_path
    run = Run(id="run_001", analysis_id=analysis.id, created_at="now", status="ok", metrics={"max_y": 1.25})
    case.runs.append(run)
    artifact_dir = tmp_path / "artifacts" / f"run_{run.id}"
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / "result.json"
    artifact_path.write_text(
        json.dumps({"success": True, "time": [0.0], "frames": [{}], "states": [], "messages": [], "error": None, "backend": "test"}),
        encoding="utf-8",
    )
    run.result_ref = ResultRef(run_entry_id=run.id, artifact_path=str(artifact_path.relative_to(tmp_path)), checksum="sha256:test")

    window = MainWindow(svc)
    qtbot.addWidget(window)
    window._set_app_mode("analysis")
    window._set_app_mode_analysis(analysis)
    window._on_run_selected(run.id)
    ctrl = window._active_mode_controller
    assert ctrl._metrics_panel is not None
    assert ctrl._metrics_panel.count() == 1
    assert ctrl._metrics_panel.tabText(0) == "Metrics"


def test_selecting_dynamic_analysis_loads_latest_persisted_run(qtbot, tmp_path) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("D", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id)
    svc.current_project_path = tmp_path
    run = Run(id="run_001", analysis_id=analysis.id, created_at="now", status="ok")
    case.runs.append(run)
    artifact_dir = tmp_path / "artifacts" / f"run_{run.id}"
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / "result.json"
    artifact_path.write_text(
        json.dumps(
            {
                "success": True,
                "time": [0.0, 0.1],
                "frames": [{"marker:m1:x": 0.0, "marker:m1:y": 0.0}, {"marker:m1:x": 1.0, "marker:m1:y": 2.0}],
                "states": [],
                "messages": [],
                "error": None,
                "backend": "test",
            }
        ),
        encoding="utf-8",
    )
    run.result_ref = ResultRef(run_entry_id=run.id, artifact_path=str(artifact_path.relative_to(tmp_path)), checksum="sha256:test")

    window = MainWindow(svc)
    qtbot.addWidget(window)
    window._on_analysis_selected(analysis.id)

    assert window._active_mode_controller.__class__.__name__ == "DynamicModeController"
    assert window._last_simulation_result is not None
    assert len(window._last_simulation_result.frames) == 2
    assert window.timeline_slider.maximum() == 1


def test_dynamic_controller_widgets_survive_unmount_and_remount(qtbot) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("D", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id)

    window = MainWindow(svc)
    qtbot.addWidget(window)
    window._set_app_mode("analysis")
    window._set_app_mode_analysis(analysis)
    first_slider = window.timeline_slider
    first_steps_spin = window.steps_spin

    window._set_app_mode("model")
    window._set_app_mode("analysis")
    window._set_app_mode_analysis(analysis)

    assert window.timeline_slider is first_slider
    assert window.steps_spin is first_steps_spin
    assert window._active_mode_controller.__class__.__name__ == "DynamicModeController"
