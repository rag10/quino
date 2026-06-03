import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore

from quino.application.service import ApplicationService
from quino.domain.workspace import Analysis, ResultRef
from quino.gui.dialogs.run_comparison_dialog import RunComparisonDialog


def test_compare_dialog_lists_runs_from_all_cases(qtbot, tmp_path) -> None:
    svc = ApplicationService()
    svc.new_workspace("t")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    analysis_bump = Analysis(id="a1", name="Bump", analysis_type="dynamic", status="ok")
    analysis_smooth = Analysis(id="a2", name="Smooth road", analysis_type="dynamic", status="ok")
    case.analyses.extend([analysis_bump, analysis_smooth])
    svc.current_project_path = tmp_path

    def add_result(analysis: Analysis) -> None:
        # Run state is flattened onto the Analysis: an analysis with a
        # result_ref IS a comparable run.
        artifact_dir = tmp_path / "artifacts" / f"run_{analysis.id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "result.json"
        artifact_path.write_text(
            json.dumps({"type": "dynamic", "frames": [{"sensor:s:y": 1.0}], "time": [0.0]}),
            encoding="utf-8",
        )
        analysis.result_ref = ResultRef(
            run_entry_id=analysis.id,
            artifact_path=str(artifact_path.relative_to(tmp_path)),
            checksum="sha256:test",
        )

    add_result(analysis_bump)
    add_result(analysis_smooth)

    dialog = RunComparisonDialog(svc)
    qtbot.addWidget(dialog)
    bump_item = dialog._find_run_item("Bump", analysis_bump.id)
    assert bump_item is not None
    bump_item.setCheckState(0, QtCore.Qt.CheckState.Checked)
    smooth_item = dialog._find_run_item("Smooth road", analysis_smooth.id)
    assert smooth_item is not None
    assert smooth_item.isDisabled()
