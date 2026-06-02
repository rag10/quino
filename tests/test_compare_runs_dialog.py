import json
import os

import pytest

pytest.skip(
    "overlay removed; Run entity and case.runs replaced by flattened Analysis run "
    "state. Run-machinery and run-comparison GUI adapted in Fase 2/4.",
    allow_module_level=True,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore

from quino.application.service import ApplicationService
from quino.domain.workspace import Analysis, ResultRef, Run
from quino.gui.dialogs.run_comparison_dialog import RunComparisonDialog


def test_compare_dialog_lists_runs_from_all_cases(qtbot, tmp_path) -> None:
    svc = ApplicationService()
    svc.new_workspace("t")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    analysis_bump = Analysis(id="a1", name="Bump", analysis_type="dynamic")
    analysis_smooth = Analysis(id="a2", name="Smooth road", analysis_type="dynamic")
    case.analyses.extend([analysis_bump, analysis_smooth])
    svc.current_workspace_path = tmp_path

    def add_run(run_id: str, analysis_id: str) -> None:
        run = Run(id=run_id, analysis_id=analysis_id, created_at="now", status="ok")
        case.runs.append(run)
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
