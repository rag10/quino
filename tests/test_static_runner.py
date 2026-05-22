from __future__ import annotations

from quino.analysis.runner import AnalysisResult
from quino.analysis.static_runner import StaticAnalysisRunner
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.workspace import Run


def test_static_validate_rejects_dof_nonzero() -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("S", analysis_type="static", case_id=case.id, workspace_pose_id=pose.id)
    errors = StaticAnalysisRunner().validate(svc.project, analysis)
    assert errors
    assert "DoF" in errors[0]


def test_static_validate_warns_when_model_is_trivial() -> None:
    svc = ApplicationService()
    svc.new_project("t")
    g1_body, g1_marker = svc.create_ground_anchor("G1", "0 mm", "0 mm")
    g2_body, g2_marker = svc.create_ground_anchor("G2", "100 mm", "0 mm")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("S", analysis_type="static", case_id=case.id, workspace_pose_id=pose.id)
    errors = StaticAnalysisRunner().validate(svc.project, analysis)
    assert any("WARNING" in error for error in errors)


def test_static_artifact_is_typed(tmp_path, monkeypatch) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("S", analysis_type="static", case_id=case.id, workspace_pose_id=pose.id)
    run = Run(id="r_static", analysis_id=analysis.id, created_at="...", status="running")
    svc.project.workspace.runs.append(run)

    monkeypatch.setattr(
        "quino.analysis.static_runner.solve_static",
        lambda project, config: {
            "pose": {},
            "applied_loads": [{"source": "gravity"}],
            "spring_forces": [],
            "actuator_forces": [],
            "reactions": [{"fy": 1.0}],
            "total_energy_in_springs": 0.0,
        },
    )

    result = StaticAnalysisRunner().run(svc.project, analysis, run=run, project_dir=tmp_path)
    assert result.status == "ok"
    import json

    artifact = tmp_path / run.result_ref.artifact_path
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["type"] == "static"
    assert "applied_loads" in data
    assert "reactions" in data
