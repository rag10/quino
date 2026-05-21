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


def test_create_pose_allocates_backing_project_pose() -> None:
    """A non-default WorkspacePose must allocate a backing project Pose
    automatically so the canvas/IK solver can mutate it."""
    svc = ApplicationService()
    svc.new_project("test")
    case = svc.workspace.create_case("C1")
    wp = svc.workspace.create_pose("PA", case_id=case.id)
    assert wp.project_pose_id is not None
    assert any(p.id == wp.project_pose_id for p in svc.project.poses)


def test_set_selected_pose_syncs_current_pose() -> None:
    """Selecting a WorkspacePose must update project.current_pose_id so the
    canvas displays the right geometry."""
    svc = ApplicationService()
    svc.new_project("test")
    case = svc.workspace.create_case("C1")
    p1 = svc.workspace.create_pose("PA", case_id=case.id)
    p2 = svc.workspace.create_pose("PB", case_id=case.id)
    svc.set_selected_pose(p1.id)
    assert svc.get_current_pose_id() == p1.project_pose_id
    svc.set_selected_pose(p2.id)
    assert svc.get_current_pose_id() == p2.project_pose_id


def test_delete_pose_clears_selection_and_backing() -> None:
    svc = ApplicationService()
    svc.new_project("test")
    case = svc.workspace.create_case("C1")
    wp = svc.workspace.create_pose("PA", case_id=case.id)
    svc.set_selected_pose(wp.id)
    assert svc.get_current_pose_id() == wp.project_pose_id

    svc.workspace.delete_pose(wp.id)

    assert svc.project.workspace.selected_pose_id is None
    assert svc.get_current_pose_id() is None
    assert all(p.id != wp.project_pose_id for p in svc.project.poses)


def test_multiple_analyses_per_pose() -> None:
    """A single pose may host several analyses; they all live under it
    in workspace.analyses."""
    svc = ApplicationService()
    svc.new_project("test")
    case = svc.workspace.create_case("C1")
    wp = svc.workspace.create_pose("PA", case_id=case.id)
    a1 = svc.workspace.create_analysis("A1", case_id=case.id, workspace_pose_id=wp.id)
    a2 = svc.workspace.create_analysis("A2", case_id=case.id, workspace_pose_id=wp.id)
    a3 = svc.workspace.create_analysis("A3", case_id=case.id, workspace_pose_id=wp.id)
    attached = [a.id for a in svc.project.workspace.analyses if a.workspace_pose_id == wp.id]
    assert attached == [a1.id, a2.id, a3.id]


def test_move_marker_in_case_keeps_rigid_joint_assembled(svc_with_case_chain) -> None:
    """A rigid joint connecting two markers must stay coincident when one
    of the markers is dragged in case mode. The case must emit overrides
    for BOTH endpoints, not just the dragged one."""
    svc, body_id, parent_id, child_id = svc_with_case_chain
    body = svc.get_body(body_id)
    marker_b = next(m for m in body.markers if m.name == "B")
    b2 = svc.create_bar(
        "B2",
        MarkerInput("100 mm", "0 mm", "C"),
        MarkerInput("200 mm", "0 mm", "D"),
    )
    body2 = svc.get_body(b2)
    marker_c = next(m for m in body2.markers if m.name == "C")
    svc.create_joint(
        "J_BC",
        "rigid",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_id, marker_id=marker_b.id),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=b2, marker_id=marker_c.id),
    )

    svc.set_working_context(case_id=parent_id)
    svc.move_marker(marker_b.id, "150 mm", "0 mm")

    parent = _case(svc, parent_id)
    # Both markers must have overrides.
    assert f"markers/{marker_b.id}/x" in parent.invariant_values
    assert f"markers/{marker_c.id}/x" in parent.invariant_values
    assert parent.invariant_values[f"markers/{marker_b.id}/x"].value == pytest.approx(150.0)
    assert parent.invariant_values[f"markers/{marker_c.id}/x"].value == pytest.approx(150.0)
    # Composed view: both endpoints coincident again.
    dp = svc.display_project
    mb = next(m for m in next(b for b in dp.model.bodies if b.id == body_id).markers if m.id == marker_b.id)
    mc = next(m for m in next(b for b in dp.model.bodies if b.id == b2).markers if m.id == marker_c.id)
    assert "150" in mb.x.expression
    assert "150" in mc.x.expression


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


def test_subcase_creating_block_does_not_touch_parent_or_baseline(
    svc_with_case_chain,
) -> None:
    svc, _body, parent_id, child_id = svc_with_case_chain

    svc.set_working_context(case_id=parent_id)
    pblock = svc.add_block(block_type="Constant", name="ParentSrc", position=(0.0, 0.0))

    svc.set_working_context(case_id=child_id)
    cblock = svc.add_block(block_type="Gain", name="ChildGain", position=(50.0, 0.0))

    parent = _case(svc, parent_id)
    child = _case(svc, child_id)
    # Parent only has its own added block; child has only its own.
    assert any(b["id"] == pblock for b in parent.added_entities.get("blocks", []))
    assert not any(b["id"] == cblock for b in parent.added_entities.get("blocks", []))
    assert any(b["id"] == cblock for b in child.added_entities.get("blocks", []))
    assert not any(b["id"] == pblock for b in child.added_entities.get("blocks", []))
    # Baseline diagram remains empty.
    cg = svc.project.model.control_graph
    assert cg is None or len(cg.instances) == 0
    # Both blocks visible in display_project once we're in the child.
    composed_cg = svc.display_project.model.control_graph
    assert pblock in composed_cg.instances
    assert cblock in composed_cg.instances


def test_subcase_can_connect_inherited_block_to_local_block(
    svc_with_case_chain,
) -> None:
    svc, _body, parent_id, child_id = svc_with_case_chain

    svc.set_working_context(case_id=parent_id)
    pblock = svc.add_block(block_type="Constant", name="ParentSrc", position=(0.0, 0.0))

    svc.set_working_context(case_id=child_id)
    cblock = svc.add_block(block_type="Gain", name="ChildGain", position=(50.0, 0.0))

    svc.add_connection(src_instance=pblock, src_port="out", dst_instance=cblock, dst_port="in")

    parent = _case(svc, parent_id)
    child = _case(svc, child_id)
    # Connection lives only in the child (it doesn't exist in parent's view).
    assert any(
        c.get("src_instance") == pblock and c.get("dst_instance") == cblock
        for c in child.added_entities.get("connections", [])
    )
    assert not any(
        c.get("src_instance") == pblock and c.get("dst_instance") == cblock
        for c in parent.added_entities.get("connections", [])
    )
    # Composed view sees both blocks and the connection.
    cg = svc.display_project.model.control_graph
    assert any(
        c.src_instance == pblock and c.dst_instance == cblock for c in cg.connections
    )


def test_subcase_overriding_block_param_does_not_mutate_parent_or_baseline(
    svc_with_case_chain,
) -> None:
    svc, _body, parent_id, child_id = svc_with_case_chain

    svc.set_working_context(case_id=parent_id)
    pblock = svc.add_block(
        block_type="Gain", name="ParentGain", position=(0.0, 0.0),
        parameters={"k": 1.0},
    )

    svc.set_working_context(case_id=child_id)
    svc.set_block_parameter(pblock, "k", 7.5)

    parent = _case(svc, parent_id)
    child = _case(svc, child_id)
    # Override is on the child only.
    override_path = f"model/control_graph/instances/{pblock}/parameters/k"
    assert override_path in child.invariant_values
    assert override_path not in parent.invariant_values
    # Composed value reflects the override.
    composed_block = svc.display_project.model.control_graph.instances[pblock]
    assert float(composed_block.parameters["k"]) == 7.5


def test_removing_inherited_block_in_subcase_also_hides_its_connections(
    svc_with_case_chain,
) -> None:
    svc, _body, parent_id, child_id = svc_with_case_chain

    svc.set_working_context(case_id=parent_id)
    src = svc.add_block(block_type="Constant", name="Src", position=(0.0, 0.0))
    sink = svc.add_block(block_type="Gain", name="Sink", position=(50.0, 0.0))
    svc.add_connection(src_instance=src, src_port="out", dst_instance=sink, dst_port="in")

    svc.set_working_context(case_id=child_id)
    svc.remove_block(src)  # block inherited from parent

    parent = _case(svc, parent_id)
    child = _case(svc, child_id)
    # Parent still has both blocks and the connection.
    assert any(b["id"] == src for b in parent.added_entities.get("blocks", []))
    assert any(
        c.get("src_instance") == src and c.get("dst_instance") == sink
        for c in parent.added_entities.get("connections", [])
    )
    # Child records the removal; the composed view drops the block AND the
    # dangling connection that referenced it.
    assert src in child.removed_entity_ids
    composed_cg = svc.display_project.model.control_graph
    assert src not in composed_cg.instances
    assert not any(
        c.src_instance == src and c.dst_instance == sink for c in composed_cg.connections
    )


def test_subcase_can_remove_inherited_block_without_mutating_parent(
    svc_with_case_chain,
) -> None:
    svc, _body, parent_id, child_id = svc_with_case_chain

    svc.set_working_context(case_id=parent_id)
    pblock = svc.add_block(block_type="Constant", name="ParentSrc", position=(0.0, 0.0))

    svc.set_working_context(case_id=child_id)
    svc.remove_block(pblock)

    parent = _case(svc, parent_id)
    child = _case(svc, child_id)
    # Parent still owns the added block.
    assert any(b["id"] == pblock for b in parent.added_entities.get("blocks", []))
    # Child records the removal.
    assert pblock in child.removed_entity_ids
    # Composed view (child) no longer shows the block.
    composed_cg = svc.display_project.model.control_graph
    assert pblock not in composed_cg.instances


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
