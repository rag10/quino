from __future__ import annotations

import pytest

from quino.application.service import ApplicationService
from quino.domain.inputs import JointEndpointInput, MarkerInput, PropertyValueInput, SliderInput
from quino.domain.types import JointEndpointKind


@pytest.fixture
def svc_with_case_chain() -> tuple[ApplicationService, str, str, str]:
    svc = ApplicationService()
    svc.new_project("scope parity")
    body_id = svc.create_bar(
        "BaseBar",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("100 mm", "0 mm", "B"),
    )
    baseline = svc.project.workspace.baselines[0]
    parent = svc.workspace.create_case("Parent", baseline_id=baseline.id)
    child = svc.workspace.create_case("Child", parent_case_id=parent.id)
    return svc, body_id, parent.id, child.id


def _body_marker_id(svc: ApplicationService, body_id: str, index: int = 0) -> str:
    body = svc.get_body(body_id)
    assert body is not None
    return body.structural_markers()[index].id


def _case(svc: ApplicationService, case_id: str):
    return next(c for c in svc.project.workspace.cases if c.id == case_id)


def test_subcase_can_create_driver_on_joint_inherited_from_parent_case(
    svc_with_case_chain,
) -> None:
    svc, body_id, parent_id, child_id = svc_with_case_chain
    marker_id = _body_marker_id(svc, body_id)

    svc.set_working_context(case_id=parent_id)
    joint_id = svc.connect_marker_to_ground(marker_id, joint_type="revolute", name="ParentGroundJoint")

    svc.set_working_context(case_id=child_id)
    driver_id = svc.create_driver("ChildDriver", "rotation", joint_id, "10 deg * t / 1 s", "deg")

    child = _case(svc, child_id)
    assert any(item["id"] == driver_id for item in child.added_entities.get("drivers", []))
    assert not any(driver.id == driver_id for driver in svc.project.model.drivers)
    assert any(driver.id == driver_id for driver in svc.display_project.model.drivers)


def test_subcase_can_connect_marker_to_slider_inherited_from_parent_case(
    svc_with_case_chain,
) -> None:
    svc, body_id, parent_id, child_id = svc_with_case_chain
    marker_id = _body_marker_id(svc, body_id)

    svc.set_working_context(case_id=parent_id)
    slider_id = svc.create_slider(
        "ParentSlider",
        SliderInput("0 mm", "0 mm", "0 deg", "-100 mm", "100 mm"),
    )

    svc.set_working_context(case_id=child_id)
    joint_id = svc.connect_marker_to_slider(
        marker_id,
        slider_id,
        joint_type="revolute",
        name="ChildSliderJoint",
        align="none",
    )

    child = _case(svc, child_id)
    assert any(item["id"] == joint_id for item in child.added_entities.get("joints", []))
    assert not any(joint.id == joint_id for joint in svc.project.model.joints)
    assert any(joint.id == joint_id for joint in svc.display_project.model.joints)


def test_subcase_can_create_joint_to_ground_anchor_inherited_from_parent_case(
    svc_with_case_chain,
) -> None:
    svc, body_id, parent_id, child_id = svc_with_case_chain
    marker_id = _body_marker_id(svc, body_id, index=1)

    svc.set_working_context(case_id=parent_id)
    ground_body_id, ground_marker_id = svc.create_ground_anchor("ParentGround", "200 mm", "0 mm")

    svc.set_working_context(case_id=child_id)
    joint_id = svc.create_joint(
        "ChildToParentGround",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_id, marker_id=marker_id),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=ground_body_id, marker_id=ground_marker_id),
    )

    child = _case(svc, child_id)
    assert any(item["id"] == joint_id for item in child.added_entities.get("joints", []))
    assert not any(joint.id == joint_id for joint in svc.project.model.joints)
    assert any(joint.id == joint_id for joint in svc.display_project.model.joints)


def test_case_can_add_gravity_without_mutating_baseline(svc_with_case_chain) -> None:
    svc, _body_id, parent_id, _child_id = svc_with_case_chain

    svc.set_working_context(case_id=parent_id)
    svc.add_gravity()

    parent = _case(svc, parent_id)
    assert svc.project.model.gravity is None
    assert parent.reference_overrides["__gravity__"]["enabled"] is True
    assert svc.display_project.model.gravity is not None


def test_subcase_can_override_inherited_gravity_without_mutating_parent(
    svc_with_case_chain,
) -> None:
    svc, _body_id, parent_id, child_id = svc_with_case_chain

    svc.set_working_context(case_id=parent_id)
    svc.add_gravity()
    svc.update_property("__gravity__", "magnitude", PropertyValueInput("expression", "4.0"))

    svc.set_working_context(case_id=child_id)
    svc.update_property("__gravity__", "magnitude", PropertyValueInput("expression", "2.5"))

    parent = _case(svc, parent_id)
    child = _case(svc, child_id)
    assert parent.invariant_values["gravity/magnitude"].value == pytest.approx(4.0)
    assert child.invariant_values["gravity/magnitude"].value == pytest.approx(2.5)
    assert svc.project.model.gravity is None
    assert svc.display_project.model.gravity.magnitude == pytest.approx(2.5)


def test_subcase_can_disable_inherited_gravity_without_mutating_parent(
    svc_with_case_chain,
) -> None:
    svc, _body_id, parent_id, child_id = svc_with_case_chain

    svc.set_working_context(case_id=parent_id)
    svc.add_gravity()

    svc.set_working_context(case_id=child_id)
    svc.delete_gravity()

    parent = _case(svc, parent_id)
    child = _case(svc, child_id)
    assert parent.reference_overrides["__gravity__"]["enabled"] is True
    assert child.reference_overrides["__gravity__"]["enabled"] is False
    assert svc.project.model.gravity is None
    assert svc.display_project.model.gravity is None
