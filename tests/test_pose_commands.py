"""Regression tests for the extracted PoseCommands command-service.

All tests exercise the new collaborator via the public ApplicationService API
to guarantee delegation preserves existing behavior.
"""
from __future__ import annotations

import pytest

from quino.application.commands.pose_commands import PoseCommands
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput


def _make_app() -> ApplicationService:
    app = ApplicationService()
    app.new_project("Pose Commands Test")
    app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    return app


def test_poses_attribute_is_pose_commands_instance() -> None:
    app = _make_app()
    assert isinstance(app.poses, PoseCommands)


def test_create_and_list_poses() -> None:
    app = _make_app()
    assert app.list_poses() == []
    pose_a = app.create_pose("First")
    pose_b = app.create_pose("Second")
    assert [p.id for p in app.list_poses()] == [pose_a.id, pose_b.id]


def test_current_pose_tracking() -> None:
    app = _make_app()
    assert app.get_current_pose_id() is None
    pose = app.create_pose("Working")
    assert app.get_current_pose_id() == pose.id
    assert app.get_current_pose().id == pose.id

    app.set_current_pose_id(None)
    assert app.get_current_pose_id() is None
    assert app.get_current_pose() is None

    app.set_current_pose_id(pose.id)
    assert app.get_current_pose_id() == pose.id

    with pytest.raises(ValueError):
        app.set_current_pose_id("nonexistent-id")


def test_duplicate_pose_creates_independent_copy() -> None:
    app = _make_app()
    source = app.create_pose("Original")
    # mutate source body_pose to ensure deep copy
    body_id = next(iter(source.body_poses))
    source.body_poses[body_id].x = 42.0

    clone = app.duplicate_pose(source.id)
    assert clone.id != source.id
    assert clone.name == "Original copy"
    assert clone.body_poses[body_id].x == 42.0

    # mutating clone shouldn't affect source
    clone.body_poses[body_id].x = 99.0
    assert source.body_poses[body_id].x == 42.0

    assert app.get_current_pose_id() == clone.id


def test_rename_pose_validates_input() -> None:
    app = _make_app()
    pose = app.create_pose("First")
    app.rename_pose(pose.id, "Renamed")
    assert app.get_pose(pose.id).name == "Renamed"

    with pytest.raises(ValueError):
        app.rename_pose(pose.id, "   ")
    with pytest.raises(ValueError):
        app.rename_pose("missing-id", "Whatever")


def test_delete_pose_clears_current_and_simulation_refs() -> None:
    app = _make_app()
    pose1 = app.create_pose("One")
    pose2 = app.create_pose("Two")
    app.set_current_pose_id(pose2.id)
    app.set_simulation_initial_pose(pose2.id)

    app.delete_pose(pose2.id)
    assert app.get_simulation_initial_pose_id() is None
    # current pose falls back to remaining pose
    assert app.get_current_pose_id() == pose1.id

    # deleting an unknown id is a no-op
    app.delete_pose("missing-id")


def test_set_and_clear_simulation_initial_pose() -> None:
    app = _make_app()
    pose = app.create_pose("Start")

    app.set_simulation_initial_pose(pose.id)
    assert app.get_simulation_initial_pose_id() == pose.id
    assert app.get_simulation_initial_pose().id == pose.id

    app.clear_initial_pose()
    assert app.get_simulation_initial_pose_id() is None
    assert app.get_simulation_initial_pose() is None

    with pytest.raises(ValueError):
        app.set_simulation_initial_pose("missing-id")


def test_set_initial_pose_from_current_requires_selection() -> None:
    app = _make_app()
    with pytest.raises(ValueError):
        app.set_initial_pose_from_current()

    pose = app.create_pose("Selected")
    app.set_initial_pose_from_current()
    assert app.get_simulation_initial_pose_id() == pose.id


def test_driver_initial_velocity_round_trip() -> None:
    app = _make_app()
    body_id = next(b.id for b in app.project.model.bodies if b.name == "Arm")
    marker_a = next(m.id for m in app._find_body(body_id).markers if m.name == "A")
    ground_a = app.connect_marker_to_ground(marker_a)
    driver_id = app.create_driver("Drive", "rotation", ground_a, "0 deg", "deg")

    pose = app.create_pose("With velocities")
    app.set_current_pose_id(pose.id)
    assert app.get_driver_initial_velocity(driver_id) is None

    app.set_driver_initial_velocity(driver_id, 2.5)
    assert app.get_driver_initial_velocity(driver_id) == pytest.approx(2.5)

    app.set_driver_initial_velocity(driver_id, None)
    assert app.get_driver_initial_velocity(driver_id) is None

    with pytest.raises(ValueError):
        app.set_driver_initial_velocity("missing-driver", 1.0)


def test_driver_initial_velocity_requires_current_pose() -> None:
    app = _make_app()
    body_id = next(b.id for b in app.project.model.bodies if b.name == "Arm")
    marker_a = next(m.id for m in app._find_body(body_id).markers if m.name == "A")
    ground_a = app.connect_marker_to_ground(marker_a)
    driver_id = app.create_driver("Drive", "rotation", ground_a, "0 deg", "deg")

    # no current pose selected
    with pytest.raises(ValueError):
        app.set_driver_initial_velocity(driver_id, 1.0)
    assert app.get_driver_initial_velocity(driver_id) is None


def test_reset_current_pose_to_reference_creates_when_missing() -> None:
    app = _make_app()
    assert app.get_current_pose_id() is None
    reference = app.reset_current_pose_to_reference()
    assert app.get_current_pose_id() == reference.id
    assert app.list_poses() == [reference]


def test_new_project_clears_current_pose_selection() -> None:
    app = _make_app()
    app.create_pose("Temp")
    assert app.get_current_pose_id() is not None

    app.new_project("Fresh")
    assert app.get_current_pose_id() is None
    assert app.list_poses() == []


def test_complete_pose_backcompat_helper_still_works() -> None:
    app = _make_app()
    pose = app.create_pose("Check")
    completed = app._complete_pose(pose)
    assert completed.id == pose.id
    assert completed.body_poses  # has body entries from reference build


def test_marking_simulation_initial_does_not_flip_is_default_flag() -> None:
    """Regression: marking a user pose as simulation initial used to set
    pose.is_default=True, which then caused get_current_pose_id() to filter
    it out — so selecting it from the workflow tree silently activated
    Reference instead."""
    app = _make_app()
    p2 = app.create_pose("Pose 2")
    app.set_simulation_initial_pose(p2.id)
    assert p2.is_default is False
    app.set_selected_pose(p2.id)
    assert app.get_current_pose_id() == p2.id
    current = app.get_current_pose()
    assert current is not None
    assert current.id == p2.id


def test_simulation_initial_pose_survives_save_load(tmp_path) -> None:
    app = _make_app()
    p2 = app.create_pose("Pose 2")
    app.set_simulation_initial_pose(p2.id)
    path = tmp_path / "ws.quino.json"
    app.save_workspace(path)

    reloaded = ApplicationService()
    reloaded.load_workspace(path)
    assert reloaded.get_simulation_initial_pose_id() == p2.id
    # And the migration left the user pose's flag clean.
    case = reloaded.current_case()
    p2_reloaded = next(p for p in case.poses if p.id == p2.id)
    assert p2_reloaded.is_default is False


def test_id_service_observes_pose_ids_on_load(tmp_path) -> None:
    """Regression: id_service did not observe pose IDs after load, so new
    poses collided with existing ones."""
    app = _make_app()
    p_a = app.create_pose("Pose A")
    p_b = app.create_pose("Pose B")
    existing = {p.id for case in app._workspace.cases.values() for p in case.poses}
    path = tmp_path / "ws.quino.json"
    app.save_workspace(path)

    reloaded = ApplicationService()
    reloaded.load_workspace(path)
    new_pose = reloaded.create_pose("Pose C")
    assert new_pose.id not in existing


def test_selecting_pose_resolves_via_active_case_first() -> None:
    """Regression: if two cases happen to own poses with the same id (legacy
    bug: id_service did not observe pose ids on load), workspace_commands
    .set_selected_pose used to switch to whichever case appeared first in
    iteration order. With the fix it should prefer the currently active case
    when it already owns the pose."""
    app = _make_app()
    ws = app._workspace
    root_id = ws.root_case_ids[0]
    # Manually clone into a second case with a colliding pose id (simulating
    # a legacy-loaded workspace).
    import copy as _copy
    from quino.domain.workspace import Case
    second_id = "case_clone"
    second = _copy.deepcopy(ws.cases[root_id])
    second.id = second_id
    ws.cases[second_id] = second
    ws.root_case_ids.append(second_id)
    # Both cases now have Reference with the same id.
    ref_id = ws.cases[root_id].poses[0].id
    assert any(p.id == ref_id for p in ws.cases[second_id].poses)

    # Active case = second; selecting the pose by id should resolve to second.
    ws.selected_case_id = second_id
    app.set_selected_pose(ref_id)
    assert ws.selected_case_id == second_id


def test_load_dedupes_colliding_pose_ids_across_cases(tmp_path) -> None:
    """Regression: legacy workspaces (saved before id_service observed pose
    IDs) could end up with the same pose ID in two cases — typically a
    user-created pose colliding with another case's Reference. Any code that
    searched "the case owning pose X" would hit the Reference first and
    refuse to delete / rename / select it as if it were the reference."""
    import json
    from quino.application.service import ApplicationService
    from quino.domain.inputs import MarkerInput

    # Build a workspace with two cases manually with colliding pose IDs.
    app = ApplicationService()
    app.new_workspace("collision")
    app.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    ws = app._workspace
    root = ws.cases[ws.root_case_ids[0]]
    # Manually clone the root into a child case to mimic the legacy duplication.
    import copy as _copy
    child = _copy.deepcopy(root)
    child.id = "case_child"
    child.parent_case_id = root.id
    # Add a user pose in the child whose id collides with the root's Reference.
    from quino.domain.workspace import Pose
    from quino.domain.model import BodyPose
    ref_id = root.poses[0].id  # 'pose_001'
    body_id = root.model.bodies[0].id
    child.poses = [
        child.poses[0],  # child's own Reference
        Pose(
            id=ref_id,  # collides with root's Reference
            name="Pose2",
            body_poses={body_id: BodyPose(body_id=body_id, x=0.0, y=0.0, angle=0.0)},
        ),
    ]
    ws.cases[child.id] = child

    path = tmp_path / "ws.quino.json"
    app.save_workspace(path)

    reloaded = ApplicationService()
    reloaded.load_workspace(path)
    rws = reloaded._workspace
    rchild = rws.cases["case_child"]
    rroot = rws.cases[rws.root_case_ids[0]]
    # The colliding Pose2 must have been renamed; root Reference must keep its id.
    assert rroot.poses[0].id == ref_id
    pose2 = next(p for p in rchild.poses if p.name == "Pose2")
    assert pose2.id != ref_id
    assert pose2.is_default is False

    # And deleting Pose2 from the child case must succeed (used to refuse with
    # "Cannot delete the reference pose").
    rws.selected_case_id = rchild.id
    reloaded.workspace.delete_pose(pose2.id)
    assert not any(p.id == pose2.id for p in rchild.poses)
