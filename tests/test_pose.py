from __future__ import annotations

import json
import math

import pytest

from quino.application.service import ApplicationService
from quino.domain.inputs import JointEndpointInput, MarkerInput
from quino.domain.types import JointEndpointKind
from quino.pose.geometry import marker_world_position
from quino.pose.model import PoseConstraint


def make_pose_app() -> ApplicationService:
    app = ApplicationService()
    app.new_project("Pose Demo")
    return app


def _find_marker_id(app: ApplicationService, body_id: str, name: str) -> str:
    return next(marker.id for marker in app._find_body(body_id).markers if marker.name == name)


def _body_pose(app: ApplicationService, body_id: str):
    pose = app.get_current_pose()
    assert pose is not None
    return pose.body_poses[body_id]


def test_initial_pose_roundtrip_and_backwards_compat(tmp_path) -> None:
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    app.reset_current_pose_to_reference()
    app.set_initial_pose_from_current()

    path = tmp_path / "pose.quino.json"
    app.save_project(str(path))

    loaded = ApplicationService()
    loaded.load_project(str(path))
    sim_pose = loaded.get_simulation_initial_pose()
    assert sim_pose is not None
    assert body_id in sim_pose.body_poses

    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("poses", None)
    data.pop("simulation_initial_pose_id", None)
    data.pop("initial_pose", None)
    legacy_path = tmp_path / "legacy.quino.json"
    legacy_path.write_text(json.dumps(data), encoding="utf-8")

    legacy = ApplicationService()
    legacy.load_project(str(legacy_path))
    assert legacy.project.poses == []
    assert legacy.project.simulation_initial_pose_id is None


def test_load_legacy_initial_pose_migrates_to_poses_list(tmp_path) -> None:
    """An old project with `initial_pose` should migrate to poses[] + simulation_initial_pose_id."""
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    app.reset_current_pose_to_reference()
    app.set_initial_pose_from_current()
    path = tmp_path / "with_poses.quino.json"
    app.save_project(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    poses = data.pop("poses")
    data.pop("simulation_initial_pose_id", None)
    data["initial_pose"] = poses[0]
    legacy_path = tmp_path / "legacy_initial_pose.quino.json"
    legacy_path.write_text(json.dumps(data), encoding="utf-8")

    legacy = ApplicationService()
    legacy.load_project(str(legacy_path))
    assert len(legacy.project.poses) == 1
    assert legacy.project.simulation_initial_pose_id == legacy.project.poses[0].id
    assert body_id in legacy.project.poses[0].body_poses


def test_create_reference_pose_and_marker_world_position() -> None:
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = _find_marker_id(app, body_id, "A")
    marker_b = _find_marker_id(app, body_id, "B")

    pose = app.create_reference_pose()
    body_pose = pose.body_poses[body_id]
    assert body_pose.x == pytest.approx(0.0)
    assert body_pose.y == pytest.approx(0.0)
    assert body_pose.angle == pytest.approx(0.0)

    body_pose.x = 10.0
    body_pose.y = 20.0
    body_pose.angle = math.pi / 2.0

    assert marker_world_position(app.project, marker_a, pose) == pytest.approx((10.0, 20.0))
    assert marker_world_position(app.project, marker_b, pose) == pytest.approx((10.0, 120.0))


def test_pose_operations_do_not_mutate_base_marker_expressions() -> None:
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = _find_marker_id(app, body_id, "A")
    marker_b = _find_marker_id(app, body_id, "B")
    app.connect_marker_to_ground(marker_a)

    body = app._find_body(body_id)
    before = [(marker.name, marker.x.expression, marker.y.expression) for marker in body.structural_markers()]

    pose = app.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    app.set_current_pose(pose)
    result = app.solve_current_pose(
        [PoseConstraint(
            id="x_b",
            kind="marker_projected_coordinate",
            target_id=marker_b,
            metadata={"axis_x": 1.0, "axis_y": 0.0, "value": 80.0},
        )]
    )

    assert result.success
    after = [(marker.name, marker.x.expression, marker.y.expression) for marker in app._find_body(body_id).structural_markers()]
    assert after == before


def test_solve_current_pose_reports_missing_exudyn(monkeypatch) -> None:
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = _find_marker_id(app, body_id, "A")
    app.connect_marker_to_ground(marker_a)
    app.reset_current_pose_to_reference()

    monkeypatch.setattr(app.pose_runner.adapter, "is_available", lambda: False)
    result = app.solve_current_pose()

    assert result.success is False
    assert result.error == "Missing dependency: exudyn"


def test_pose_projected_coordinate_solve_preserves_length() -> None:
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = _find_marker_id(app, body_id, "A")
    marker_b = _find_marker_id(app, body_id, "B")
    app.connect_marker_to_ground(marker_a)

    pose = app.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    app.set_current_pose(pose)

    result = app.solve_current_pose(
        [PoseConstraint(
            id="x_b",
            kind="marker_projected_coordinate",
            target_id=marker_b,
            metadata={"axis_x": 1.0, "axis_y": 0.0, "value": 80.0},
        )]
    )

    assert result.success
    solved_pose = app.get_current_pose()
    assert solved_pose is not None
    bx, by = marker_world_position(app.project, marker_b, solved_pose)
    ax, ay = marker_world_position(app.project, marker_a, solved_pose)
    assert bx == pytest.approx(80.0, abs=1e-3)
    assert math.hypot(bx - ax, by - ay) == pytest.approx(100.0, abs=1e-3)


def test_simulation_uses_initial_pose_frame() -> None:
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = _find_marker_id(app, body_id, "A")
    marker_b = _find_marker_id(app, body_id, "B")
    app.connect_marker_to_ground(marker_a)

    pose = app.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    app.set_current_pose(pose)
    result = app.solve_current_pose(
        [PoseConstraint(
            id="x_b",
            kind="marker_projected_coordinate",
            target_id=marker_b,
            metadata={"axis_x": 1.0, "axis_y": 0.0, "value": 80.0},
        )]
    )
    assert result.success
    app.set_initial_pose_from_current()

    sim = app.run_kinematic_simulation()
    assert sim.success
    assert sim.frames
    frame = sim.frames[0]
    sim_pose = app.get_simulation_initial_pose()
    assert sim_pose is not None
    expected = sim_pose.body_poses[body_id]
    assert frame[f"{body_id}.x"] == pytest.approx(expected.x, abs=1e-3)
    assert frame[f"{body_id}.y"] == pytest.approx(expected.y, abs=1e-3)
    assert frame[f"{body_id}.angle"] == pytest.approx(expected.angle, abs=1e-3)


def test_multiple_poses_crud_and_simulation_selection() -> None:
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = _find_marker_id(app, body_id, "A")
    app.connect_marker_to_ground(marker_a)

    pose1 = app.create_pose("Down")
    pose1.body_poses[body_id].angle = -math.pi / 2.0

    pose2 = app.duplicate_pose(pose1.id)
    app.rename_pose(pose2.id, "Up")
    pose2.body_poses[body_id].angle = math.pi / 2.0

    assert len(app.list_poses()) == 2
    assert {pose.name for pose in app.list_poses()} == {"Down", "Up"}

    app.set_simulation_initial_pose(pose2.id)
    assert app.get_simulation_initial_pose_id() == pose2.id
    assert app.get_simulation_initial_pose().name == "Up"

    app.delete_pose(pose2.id)
    assert app.get_simulation_initial_pose_id() is None
    assert [p.id for p in app.list_poses()] == [pose1.id]


def test_pose_initial_velocity_per_driver_persisted(tmp_path) -> None:
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = _find_marker_id(app, body_id, "A")
    ground_a = app.connect_marker_to_ground(marker_a)
    driver_id = app.create_driver("Drive", "rotation", ground_a, "0 deg", "deg")

    pose = app.create_pose("Start")
    app.set_current_pose_id(pose.id)
    app.set_driver_initial_velocity(driver_id, 1.5)
    assert app.get_driver_initial_velocity(driver_id) == pytest.approx(1.5)

    path = tmp_path / "vel.quino.json"
    app.save_project(str(path))
    loaded = ApplicationService()
    loaded.load_project(str(path))
    saved_pose = loaded.get_pose(pose.id)
    assert saved_pose is not None
    assert saved_pose.initial_velocities[driver_id] == pytest.approx(1.5)


def test_delete_driver_cleans_initial_velocity_entries() -> None:
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = _find_marker_id(app, body_id, "A")
    ground_a = app.connect_marker_to_ground(marker_a)
    driver_id = app.create_driver("Drive", "rotation", ground_a, "0 deg", "deg")
    pose = app.create_pose()
    app.set_current_pose_id(pose.id)
    app.set_driver_initial_velocity(driver_id, 1.0)
    assert pose.initial_velocities.get(driver_id) == pytest.approx(1.0)

    app.delete_entity(driver_id)
    assert driver_id not in pose.initial_velocities


def test_body_angle_constraint_prescribes_horizontal() -> None:
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = _find_marker_id(app, body_id, "A")
    app.connect_marker_to_ground(marker_a)

    pose = app.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    app.set_current_pose(pose)

    result = app.solve_current_pose(
        [PoseConstraint(id="h", kind="body_angle", target_id=body_id, metadata={"angle": 0.0})]
    )

    assert result.success
    solved_pose = app.get_current_pose()
    assert solved_pose is not None
    assert solved_pose.body_poses[body_id].angle == pytest.approx(0.0, abs=1e-5)


def test_body_angle_constraint_prescribes_vertical() -> None:
    app = make_pose_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = _find_marker_id(app, body_id, "A")
    app.connect_marker_to_ground(marker_a)

    pose = app.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.1
    app.set_current_pose(pose)

    result = app.solve_current_pose(
        [PoseConstraint(id="v", kind="body_angle", target_id=body_id, metadata={"angle": math.pi / 2.0})]
    )

    assert result.success
    solved_pose = app.get_current_pose()
    assert solved_pose is not None
    assert solved_pose.body_poses[body_id].angle == pytest.approx(math.pi / 2.0, abs=1e-5)


def test_relative_body_angle_constraint_prescribes_angle() -> None:
    """Crank + coupler open chain: prescribe crank angle and the relative angle between them."""
    app = make_pose_app()
    crank_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("50 mm", "0 mm", "B"))
    marker_crank_a = _find_marker_id(app, crank_id, "A")
    marker_crank_b = _find_marker_id(app, crank_id, "B")
    coupler_id = app.create_bar("Coupler", MarkerInput("0 mm", "0 mm", "C"), MarkerInput("100 mm", "0 mm", "D"))
    marker_coupler_c = _find_marker_id(app, coupler_id, "C")

    app.connect_marker_to_ground(marker_crank_a)
    app.create_joint(
        "CrankCoupler",
        "revolute",
        JointEndpointInput(kind=JointEndpointKind.MARKER, body_id=crank_id, marker_id=marker_crank_b),
        JointEndpointInput(kind=JointEndpointKind.MARKER, body_id=coupler_id, marker_id=marker_coupler_c),
    )

    app.reset_current_pose_to_reference()

    # 2 DOF open chain: pin crank angle AND prescribe relative angle → 0 DOF
    crank_target = math.pi / 6.0   # 30°
    relative_target = math.pi / 4.0  # 45°

    result = app.solve_current_pose([
        PoseConstraint(
            id="crank_angle",
            kind="body_angle",
            target_id=crank_id,
            metadata={"angle": crank_target},
        ),
        PoseConstraint(
            id="rel_angle",
            kind="relative_body_angle",
            target_id=crank_id,
            metadata={
                "body_a_id": crank_id,
                "body_b_id": coupler_id,
                "local_phi_a": 0.0,
                "local_phi_b": 0.0,
                "angle": relative_target,
            },
        ),
    ])

    assert result.success
    solved = app.get_current_pose()
    assert solved is not None
    assert solved.body_poses[crank_id].angle == pytest.approx(crank_target, abs=1e-4)
    # coupler.angle = crank.angle - relative_target
    assert solved.body_poses[coupler_id].angle == pytest.approx(crank_target - relative_target, abs=1e-4)
