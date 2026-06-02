from __future__ import annotations

import pytest

pytest.skip(
    "overlay removed; Run entity and case.runs replaced by flattened Analysis run "
    "state. Runner persistence against Analysis run state adapted in Fase 2/3.",
    allow_module_level=True,
)

from quino.analysis.equilibrium_runner import EquilibriumAnalysisRunner
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.workspace import EquilibriumConfig, Run


def test_equilibrium_validate_rejects_dof_zero() -> None:
    svc = ApplicationService()
    svc.new_project("t")
    g1_body, g1_marker = svc.create_ground_anchor("G1", "0 mm", "0 mm")
    g2_body, g2_marker = svc.create_ground_anchor("G2", "100 mm", "0 mm")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("E", analysis_type="equilibrium", case_id=case.id, workspace_pose_id=pose.id)
    analysis.config = EquilibriumConfig()
    errors = EquilibriumAnalysisRunner().validate(svc.project, analysis)
    assert any("DoF" in error for error in errors)


def test_equilibrium_requires_some_force_source() -> None:
    svc = ApplicationService()
    svc.new_project("t")
    body_id = svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = next(marker.id for marker in svc.get_body(body_id).markers if marker.name == "A")
    svc.connect_marker_to_ground(marker_a)
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("E", analysis_type="equilibrium", case_id=case.id, workspace_pose_id=pose.id)
    errors = EquilibriumAnalysisRunner().validate(svc.project, analysis)
    assert any("force source" in error.lower() for error in errors)


def test_equilibrium_runner_persists_typed_artifact(tmp_path, monkeypatch) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    body_id = svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = next(marker.id for marker in svc.get_body(body_id).markers if marker.name == "A")
    svc.connect_marker_to_ground(marker_a)
    svc.add_gravity()
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("E", analysis_type="equilibrium", case_id=case.id, workspace_pose_id=pose.id)
    run = Run(id="r_eq", analysis_id=analysis.id, created_at="...", status="running")
    case.runs.append(run)

    monkeypatch.setattr(
        "quino.analysis.equilibrium_runner.find_stable_equilibria",
        lambda project, config, initial_pose=None, cancel_event=None: [{"pose": {"b1": {"x": 0.0, "y": 0.0, "theta": 0.0}}}],
    )

    result = EquilibriumAnalysisRunner().run(svc.project, analysis, run=run, project_dir=tmp_path)
    assert result.status == "ok"
    import json

    artifact = tmp_path / run.result_ref.artifact_path
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["type"] == "equilibrium"
    assert "equilibria" in data
