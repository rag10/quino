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
