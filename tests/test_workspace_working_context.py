import pytest
from quino.application.service import ApplicationService
from quino.domain.workspace import ScalarValue
from quino.domain.inputs import PropertyValueInput


@pytest.fixture
def svc_with_workspace():
    svc = ApplicationService()
    svc.new_project("test")
    baseline = svc.workspace.create_baseline("Baseline 1")
    case = svc.workspace.create_case("Case 1", baseline_id=baseline.id)
    return svc, baseline, case


def test_set_working_context_case(svc_with_workspace):
    svc, baseline, case = svc_with_workspace
    svc.set_working_context(case_id=case.id)
    ws = svc.project.workspace
    assert ws.active_case_id == case.id
    assert ws.active_baseline_id is None


def test_set_working_context_baseline(svc_with_workspace):
    svc, baseline, case = svc_with_workspace
    svc.set_working_context(case_id=case.id)
    svc.set_working_context(baseline_id=baseline.id)
    ws = svc.project.workspace
    assert ws.active_case_id is None
    assert ws.active_baseline_id == baseline.id


def test_set_working_context_clears_invalid_pose(svc_with_workspace):
    svc, baseline, case = svc_with_workspace
    pose_b = svc.workspace.create_pose("PoseB", baseline_id=baseline.id)
    svc.workspace.set_selected_pose(pose_b.id)
    # Switch to case — pose belongs to baseline, should be cleared
    svc.set_working_context(case_id=case.id)
    ws = svc.project.workspace
    assert ws.selected_pose_id is None


def test_set_working_context_clears_invalid_analysis(svc_with_workspace):
    svc, baseline, case = svc_with_workspace
    analysis_b = svc.workspace.create_analysis("AnalysisB", baseline_id=baseline.id)
    svc.workspace.set_selected_analysis(analysis_b.id)
    svc.set_working_context(case_id=case.id)
    ws = svc.project.workspace
    assert ws.selected_analysis_id is None


def test_set_working_context_is_undoable(svc_with_workspace):
    svc, baseline, case = svc_with_workspace
    svc.set_working_context(case_id=case.id)
    svc.undo()
    ws = svc.project.workspace
    assert ws.active_case_id is None


def test_set_selected_pose(svc_with_workspace):
    svc, baseline, case = svc_with_workspace
    pose = svc.workspace.create_pose("P1", case_id=case.id)
    svc.workspace.set_selected_pose(pose.id)
    assert svc.project.workspace.selected_pose_id == pose.id


def test_set_selected_analysis(svc_with_workspace):
    svc, baseline, case = svc_with_workspace
    analysis = svc.workspace.create_analysis("A1", case_id=case.id)
    svc.workspace.set_selected_analysis(analysis.id)
    assert svc.project.workspace.selected_analysis_id == analysis.id


def test_display_project_no_case_returns_base(svc_with_workspace):
    svc, baseline, case = svc_with_workspace
    assert svc.display_project is svc.project


def test_display_project_with_case_composes_override(svc_with_workspace):
    svc, baseline, case = svc_with_workspace
    # Add a punctual mass body and set its mass to 1 kg (so it has a ScalarProperty)
    body_id = svc.create_punctual_mass("PM1", x="50 mm", y="50 mm")
    svc.update_property(body_id, "mass", PropertyValueInput(kind="expression", value="1 kg"))
    body = svc.get_body(body_id)
    # Give the case an override for the body's mass
    case.invariant_values[f"bodies/{body.id}/mass"] = ScalarValue(value=5.0, unit="kg")
    svc.set_working_context(case_id=case.id)
    composed = svc.display_project
    composed_body = next(b for b in composed.model.bodies if b.id == body.id)
    # composed body's mass expression should reflect 5 kg
    assert "5" in composed_body.mass.expression
    # Base project should be unchanged
    base_body = next(b for b in svc.project.model.bodies if b.id == body.id)
    assert "5" not in base_body.mass.expression


def test_display_project_no_active_workspace_returns_base():
    svc = ApplicationService()
    svc.new_project("p")
    assert svc.display_project is svc.project
