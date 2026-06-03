from __future__ import annotations

from quino.analysis.equilibrium_runner import EquilibriumAnalysisRunner
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.workspace import Analysis, EquilibriumConfig
from quino.services.workspace_runner import _CaseAsProject


def _setup():
    svc = ApplicationService()
    svc.new_workspace("t")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    return svc, ws, case


def _add_analysis(case, *, analysis_type="equilibrium"):
    analysis = Analysis(id="a_eq", name="E", analysis_type=analysis_type)
    case.analyses.append(analysis)
    return analysis


def test_equilibrium_validate_rejects_dof_zero() -> None:
    svc, ws, case = _setup()
    svc.create_ground_anchor("G1", "0 mm", "0 mm")
    svc.create_ground_anchor("G2", "100 mm", "0 mm")
    analysis = _add_analysis(case)
    analysis.config = EquilibriumConfig()
    project = _CaseAsProject.from_case(case, ws)
    errors = EquilibriumAnalysisRunner().validate(project, analysis)
    assert any("DoF" in error for error in errors)


def test_equilibrium_requires_some_force_source() -> None:
    svc, ws, case = _setup()
    body_id = svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = next(marker.id for marker in svc.get_body(body_id).markers if marker.name == "A")
    svc.connect_marker_to_ground(marker_a)
    analysis = _add_analysis(case)
    project = _CaseAsProject.from_case(case, ws)
    errors = EquilibriumAnalysisRunner().validate(project, analysis)
    assert any("force source" in error.lower() for error in errors)


def test_equilibrium_runner_persists_typed_artifact(tmp_path, monkeypatch) -> None:
    svc, ws, case = _setup()
    body_id = svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = next(marker.id for marker in svc.get_body(body_id).markers if marker.name == "A")
    svc.connect_marker_to_ground(marker_a)
    svc.add_gravity()
    analysis = _add_analysis(case)
    analysis.status = "running"

    monkeypatch.setattr(
        "quino.analysis.equilibrium_runner.find_stable_equilibria",
        lambda project, config, initial_pose=None, cancel_event=None: [
            {"pose": {"b1": {"x": 0.0, "y": 0.0, "theta": 0.0}}}
        ],
    )

    project = _CaseAsProject.from_case(case, ws)
    result = EquilibriumAnalysisRunner().run(project, analysis, run=analysis, project_dir=tmp_path)
    assert result.status == "ok"
    import json

    artifact = tmp_path / analysis.result_ref.artifact_path
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["type"] == "equilibrium"
    assert "equilibria" in data
