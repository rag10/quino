import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore

from quino.application.service import ApplicationService
from quino.domain.workspace import ResultRef, Run
from quino.gui.dialogs.run_comparison_dialog import RunComparisonDialog


def test_compare_dialog_disables_runs_of_other_analysis_names(qtbot, tmp_path) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis_bump = svc.workspace.create_analysis("Bump", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id)
    analysis_smooth = svc.workspace.create_analysis("Smooth road", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id)
    svc.current_project_path = tmp_path

    def add_run(run_id: str, analysis_id: str) -> None:
        run = Run(id=run_id, analysis_id=analysis_id, created_at="now", status="ok")
        svc.project.workspace.runs.append(run)
        artifact_dir = tmp_path / "artifacts" / f"run_{run.id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "result.json"
        artifact_path.write_text(json.dumps({"type": "dynamic", "frames": [{"sensor:s:y": 1.0}], "time": [0.0]}), encoding="utf-8")
        run.result_ref = ResultRef(run_entry_id=run.id, artifact_path=str(artifact_path.relative_to(tmp_path)), checksum="sha256:test")

    add_run("run_b1", analysis_bump.id)
    add_run("run_s1", analysis_smooth.id)

    dialog = RunComparisonDialog(svc)
    qtbot.addWidget(dialog)
    bump_item = dialog._find_run_item("Bump", "run_b1")
    assert bump_item is not None
    bump_item.setCheckState(0, QtCore.Qt.CheckState.Checked)
    smooth_item = dialog._find_run_item("Smooth road", "run_s1")
    assert smooth_item is not None
    assert smooth_item.isDisabled()
