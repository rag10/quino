import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.application.service import ApplicationService
from quino.domain.workspace import Analysis, ResultRef, SweepDef
from quino.gui.main_window import MainWindow
from quino.services.kinematic_cache import KinematicCache


def _marker_id(service: ApplicationService) -> str:
    return service.project.model.bodies[0].markers[0].id


def test_kinematic_controller_lists_existing_sweeps(qtbot) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    pose = svc.workspace.create_pose("P", case_id=case.id)
    marker_id = _marker_id(svc)
    analysis = svc.workspace.create_analysis("Kin", analysis_type="kinematic", case_id=case.id, workspace_pose_id=pose.id)
    analysis.config.sweeps.append(
        SweepDef(id="sw1", variable_kind="marker_x", target_ids=[marker_id], mode="linear", start=0, end=10, steps=11, label="m.x")
    )
    analysis.config.sweeps.append(
        SweepDef(id="sw2", variable_kind="marker_y", target_ids=[marker_id], mode="linear", start=-5, end=5, steps=11, label="m.y")
    )
    window = MainWindow(svc)
    qtbot.addWidget(window)
    window._set_app_mode("analysis")
    window._set_app_mode_analysis(analysis)
    ctrl = window._active_mode_controller
    assert ctrl.__class__.__name__ == "KinematicModeController"
    assert len(ctrl._rows) == 2


def test_kinematic_cache_loads_fake_artifact(tmp_path) -> None:
    analysis = Analysis(id="run_001", name="Kin", analysis_type="kinematic", status="ok")
    artifact_dir = tmp_path / "artifacts" / "run_run_001"
    artifact_dir.mkdir(parents=True)
    path = artifact_dir / "result.json"
    path.write_text(
        json.dumps(
            {
                "type": "kinematic",
                "sweep_axes": [{"id": "sw1", "label": "x", "values": [0.0, 1.0]}],
                "shape": [2],
                "sensors": {"s1": {"channels": ["x", "y"], "values": [0.0, 1.0, 2.0, 3.0]}},
                "poses": [{"b1": {"x": 0.0, "y": 0.0, "theta": 0.0}}, {"b1": {"x": 2.0, "y": 3.0, "theta": 0.1}}],
                "failed_mask": [False, False],
            }
        ),
        encoding="utf-8",
    )
    analysis.result_ref = ResultRef(run_entry_id=analysis.id, artifact_path=str(path.relative_to(tmp_path)), checksum="sha256:test")
    cache = KinematicCache.load(tmp_path, analysis)
    assert cache is not None
    assert cache.pose_at([1])["b1"]["x"] == 2.0
    assert cache.point_cloud() == [(0.0, 1.0), (2.0, 3.0)]


def test_kinematic_run_selection_loads_canvas_pose(qtbot, tmp_path) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    pose = svc.workspace.create_pose("P", case_id=case.id)
    marker_id = _marker_id(svc)
    analysis = svc.workspace.create_analysis("Kin", analysis_type="kinematic", case_id=case.id, workspace_pose_id=pose.id)
    analysis.config.sweeps.append(
        SweepDef(id="sw1", variable_kind="marker_x", target_ids=[marker_id], mode="linear", start=0, end=1, steps=2, label="m.x")
    )
    svc.current_project_path = tmp_path
    analysis.status = "ok"
    artifact_dir = tmp_path / "artifacts" / f"run_{analysis.id}"
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / "result.json"
    artifact_path.write_text(
        json.dumps(
            {
                "type": "kinematic",
                "sweep_axes": [{"id": "sw1", "label": "x", "values": [0.0, 1.0]}],
                "shape": [2],
                "sensors": {"s1": {"channels": ["x", "y"], "values": [0.0, 0.0, 1.0, 0.0]}},
                "poses": [{"body_1": {"x": 0.0, "y": 0.0, "theta": 0.0}}, {"body_1": {"x": 1.0, "y": 0.0, "theta": 0.0}}],
                "failed_mask": [False, False],
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
    assert window.canvas._kinematic_cloud == [(0.0, 0.0), (1.0, 0.0)]
