"""Tests for Task 5: scalar update_property routes to case overlay when a case is active."""
import pytest
from quino.application.service import ApplicationService
from quino.domain.inputs import PropertyValueInput
from quino.domain.workspace import ScalarValue


@pytest.fixture
def svc_with_case():
    svc = ApplicationService()
    svc.new_project("test")
    body_id = svc.create_punctual_mass("Bar1", x="0 mm", y="0 mm")
    body = next(b for b in svc.project.model.bodies if b.id == body_id)
    baseline = svc.workspace.create_baseline("B1")
    case = svc.workspace.create_case("C1", baseline_id=baseline.id)
    svc.set_working_context(case_id=case.id)
    return svc, body, baseline, case


def test_scalar_edit_with_case_active_writes_to_overlay(svc_with_case):
    svc, body, baseline, case = svc_with_case
    svc.update_property(body.id, "mass", PropertyValueInput(kind="expression", value="3 kg"))
    # Base model should be unchanged (mass should still be None or not "3")
    base_body = next(b for b in svc.project.model.bodies if b.id == body.id)
    assert base_body.mass is None or "3" not in (base_body.mass.expression or "")
    # Case overlay should have the override
    path = f"bodies/{body.id}/mass"
    assert path in case.invariant_values
    assert case.invariant_values[path].value == pytest.approx(3.0)


def test_scalar_edit_without_case_mutates_base_model(svc_with_case):
    svc, body, baseline, case = svc_with_case
    svc.set_working_context()  # clear active case
    svc.update_property(body.id, "mass", PropertyValueInput(kind="expression", value="7 kg"))
    base_body = next(b for b in svc.project.model.bodies if b.id == body.id)
    assert "7" in (base_body.mass.expression or "")


def test_overlay_edit_is_undoable(svc_with_case):
    svc, body, baseline, case = svc_with_case
    path = f"bodies/{body.id}/mass"
    svc.update_property(body.id, "mass", PropertyValueInput(kind="expression", value="3 kg"))
    # Re-fetch the live case object (snapshot is on the project, not the fixture variable)
    live_case = next(c for c in svc.project.workspace.cases if c.id == case.id)
    assert path in live_case.invariant_values
    svc.undo()
    # After undo, re-fetch the case from the restored project
    restored_case = next(c for c in svc.project.workspace.cases if c.id == case.id)
    assert path not in restored_case.invariant_values


def test_display_project_reflects_overlay(svc_with_case):
    svc, body, baseline, case = svc_with_case
    # Set a mass on the base body first so compose_project can resolve it
    svc.set_working_context()
    svc.update_property(body.id, "mass", PropertyValueInput(kind="expression", value="1 kg"))
    svc.set_working_context(case_id=case.id)
    svc.update_property(body.id, "mass", PropertyValueInput(kind="expression", value="9 kg"))
    dp = svc.display_project
    composed_body = next(b for b in dp.model.bodies if b.id == body.id)
    assert "9" in (composed_body.mass.expression or "")
