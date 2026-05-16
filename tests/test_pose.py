from __future__ import annotations

import json
import math

import pytest

from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
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
    assert loaded.project.initial_pose is not None
    assert body_id in loaded.project.initial_pose.body_poses

    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("initial_pose", None)
    legacy_path = tmp_path / "legacy.quino.json"
    legacy_path.write_text(json.dumps(data), encoding="utf-8")

    legacy = ApplicationService()
    legacy.load_project(str(legacy_path))
    assert legacy.project.initial_pose is None


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
    expected = app.project.initial_pose.body_poses[body_id]
    assert frame[f"{body_id}.x"] == pytest.approx(expected.x, abs=1e-3)
    assert frame[f"{body_id}.y"] == pytest.approx(expected.y, abs=1e-3)
    assert frame[f"{body_id}.angle"] == pytest.approx(expected.angle, abs=1e-3)
