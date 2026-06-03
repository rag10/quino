from __future__ import annotations

from quino.analysis.static_runner import StaticAnalysisRunner
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.workspace import Analysis
from quino.services.workspace_runner import _CaseAsProject


def _setup():
    svc = ApplicationService()
    svc.new_workspace("t")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    analysis = Analysis(id="a1", name="S", analysis_type="static")
    case.analyses.append(analysis)
    return svc, case, analysis


def test_static_validate_rejects_dof_nonzero() -> None:
    svc, case, analysis = _setup()
    svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    project = _CaseAsProject.from_case(case, svc._workspace)
    errors = StaticAnalysisRunner().validate(project, analysis)
    assert errors
    assert "DoF" in errors[0]


def test_static_validate_warns_when_model_is_trivial() -> None:
    svc, case, analysis = _setup()
    svc.create_ground_anchor("G1", "0 mm", "0 mm")
    svc.create_ground_anchor("G2", "100 mm", "0 mm")
    project = _CaseAsProject.from_case(case, svc._workspace)
    errors = StaticAnalysisRunner().validate(project, analysis)
    assert any("WARNING" in error for error in errors)


def test_static_artifact_is_typed(tmp_path, monkeypatch) -> None:
    svc, case, analysis = _setup()
    analysis.status = "running"

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

    project = _CaseAsProject.from_case(case, svc._workspace)
    result = StaticAnalysisRunner().run(project, analysis, run=analysis, project_dir=tmp_path)
    assert result.status == "ok"
    import json

    artifact = tmp_path / analysis.result_ref.artifact_path
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["type"] == "static"
    assert "applied_loads" in data
    assert "reactions" in data
