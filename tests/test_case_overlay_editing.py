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
    return svc, body, baseline, case


def test_scalar_edit_with_case_active_writes_to_overlay(svc_with_case):
    svc, body, baseline, case = svc_with_case
    svc.set_working_context(case_id=case.id)
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
    svc.set_working_context(case_id=case.id)
    svc.set_working_context()  # clear active case
    svc.update_property(body.id, "mass", PropertyValueInput(kind="expression", value="7 kg"))
    base_body = next(b for b in svc.project.model.bodies if b.id == body.id)
    assert "7" in (base_body.mass.expression or "")


def test_overlay_edit_is_undoable(svc_with_case):
    svc, body, baseline, case = svc_with_case
    svc.set_working_context(case_id=case.id)
    path = f"bodies/{body.id}/mass"
    svc.update_property(body.id, "mass", PropertyValueInput(kind="expression", value="3 kg"))
    # Re-fetch the live case object (snapshot is on the project, not the fixture variable)
    live_case = next(c for c in svc.project.workspace.cases if c.id == case.id)
    assert path in live_case.invariant_values
    svc.undo()
    # After undo, re-fetch the case from the restored project
    restored_case = next(c for c in svc.project.workspace.cases if c.id == case.id)
    assert path not in restored_case.invariant_values


def test_driver_law_edit_with_case_active_writes_to_overlay(svc_with_case):
    svc, body, baseline, case = svc_with_case
    # Connect a marker of the body to ground as a revolute joint, then create a driver
    marker = body.markers[0]
    joint_id = svc.connect_marker_to_ground(marker.id, joint_type="revolute", name="J1")
    driver_id = svc.create_driver("D1", "rotation", joint_id, "0 deg", "deg")
    driver = next(d for d in svc.project.model.drivers if d.id == driver_id)

    # While case is active, editing the driver law should write to the overlay
    svc.set_working_context(case_id=case.id)
    svc.update_property(driver.id, "law", PropertyValueInput(kind="expression", value="45 deg"))

    # Base model driver law should be unchanged ("0 deg")
    base_driver = next(d for d in svc.project.model.drivers if d.id == driver_id)
    assert "0" in base_driver.law.expression

    # Case overlay should have the new law value evaluated at t=0
    path = f"drivers/{driver_id}/law"
    assert path in case.invariant_values
    assert case.invariant_values[path].value == pytest.approx(45.0)
    assert case.invariant_values[path].unit == "deg"


def test_display_project_reflects_overlay(svc_with_case):
    svc, body, baseline, case = svc_with_case
    # Set a mass on the base body first so compose_project can resolve it
    svc.update_property(body.id, "mass", PropertyValueInput(kind="expression", value="1 kg"))
    svc.set_working_context(case_id=case.id)
    svc.update_property(body.id, "mass", PropertyValueInput(kind="expression", value="9 kg"))
    dp = svc.display_project
    composed_body = next(b for b in dp.model.bodies if b.id == body.id)
    assert "9" in (composed_body.mass.expression or "")


def test_structural_case_warning_flag_starts_false():
    svc = ApplicationService()
    svc.new_project("test")
    assert svc.structural_case_warning_acknowledged is False


def test_structural_case_warning_can_be_acknowledged():
    svc = ApplicationService()
    svc.new_project("test")
    svc.acknowledge_structural_case_warning()
    assert svc.structural_case_warning_acknowledged is True


def test_new_project_resets_structural_warning():
    svc = ApplicationService()
    svc.new_project("test")
    svc.acknowledge_structural_case_warning()
    svc.new_project("second")
    assert svc.structural_case_warning_acknowledged is False


# ----------------------------------------------------------------------
# Baseline-immutability regression tests for F1 routing fixes
# ----------------------------------------------------------------------

@pytest.fixture
def svc_with_bar():
    from quino.domain.inputs import MarkerInput
    svc = ApplicationService()
    svc.new_project("test")
    bar_id = svc.create_bar(
        "Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B")
    )
    bar = next(b for b in svc.project.model.bodies if b.id == bar_id)
    baseline = svc.workspace.create_baseline("B1")
    case = svc.workspace.create_case("C1", baseline_id=baseline.id)
    return svc, bar, baseline, case


def test_marker_move_in_case_does_not_mutate_baseline(svc_with_bar):
    svc, bar, baseline, case = svc_with_bar
    marker = bar.markers[1]  # B
    baseline_x_before = marker.x.expression
    svc.set_working_context(case_id=case.id)
    svc.update_property(
        marker.id, "x",
        PropertyValueInput(kind="expression", value="250 mm"),
    )
    # Baseline marker must not change
    base_bar = next(b for b in svc.project.model.bodies if b.id == bar.id)
    base_marker = next(m for m in base_bar.markers if m.id == marker.id)
    assert base_marker.x.expression == baseline_x_before
    # Overlay must record the new value
    assert f"markers/{marker.id}/x" in case.invariant_values
    assert case.invariant_values[f"markers/{marker.id}/x"].value == pytest.approx(250.0)


def test_marker_overlay_visible_in_display_project(svc_with_bar):
    svc, bar, baseline, case = svc_with_bar
    marker = bar.markers[1]
    svc.set_working_context(case_id=case.id)
    svc.update_property(
        marker.id, "x",
        PropertyValueInput(kind="expression", value="200 mm"),
    )
    dp = svc.display_project
    composed_bar = next(b for b in dp.model.bodies if b.id == bar.id)
    composed_marker = next(m for m in composed_bar.markers if m.id == marker.id)
    assert "200" in composed_marker.x.expression


def test_sketch_edits_blocked_in_case_mode(svc_with_case):
    svc, body, baseline, case = svc_with_case
    svc.set_working_context(case_id=case.id)
    with pytest.raises(RuntimeError, match="Sketch editing is disabled"):
        svc.create_sketch_point("0 mm", "0 mm")


def test_sketch_edits_allowed_in_baseline_mode(svc_with_case):
    svc, body, baseline, case = svc_with_case
    # No active case
    pid = svc.create_sketch_point("10 mm", "10 mm")
    assert pid is not None


def test_entity_index_does_not_mutate_baseline_after_overlay_lookup(svc_with_case):
    """Regression: entering a case with mass override used to mutate baseline body.mass."""
    svc, body, baseline, case = svc_with_case
    svc.update_property(body.id, "mass", PropertyValueInput(kind="expression", value="1 kg"))
    base_expr_before = body.mass.expression
    svc.set_working_context(case_id=case.id)
    svc.update_property(body.id, "mass", PropertyValueInput(kind="expression", value="9 kg"))
    # Force _build_entity_index to run (find_entity triggers it)
    svc.get_entity(body.id)
    base_body = next(b for b in svc.project.model.bodies if b.id == body.id)
    assert base_body.mass.expression == base_expr_before
