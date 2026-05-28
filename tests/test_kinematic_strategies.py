from __future__ import annotations

import math

from quino.analysis.kinematic_sweeps import (
    SweepStrategy,
    compute_sweep_base_value,
    strategy_for,
)
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.model import BodyPose
from quino.domain.workspace import Pose, SweepDef


def test_strategy_for_returns_subclass() -> None:
    strategy = strategy_for(SweepDef(id="x", variable_kind="marker_x", target_ids=["m1"]))
    assert isinstance(strategy, SweepStrategy)


def test_marker_x_strategy_builds_marker_projected_constraint() -> None:
    strategy = strategy_for(SweepDef(id="x", variable_kind="marker_x", target_ids=["m1"]))
    constraints = strategy.constraints(2.5)
    assert len(constraints) == 1
    constraint = constraints[0]
    assert constraint.kind == "marker_projected_coordinate"
    assert constraint.target_id == "m1"
    assert constraint.metadata["axis_x"] == 1.0
    assert constraint.metadata["axis_y"] == 0.0
    assert constraint.metadata["value"] == 2.5


def test_slider_stroke_strategy_uses_bound_geometry() -> None:
    strategy = strategy_for(SweepDef(id="x", variable_kind="slider_stroke", target_ids=["sl1", "mA"]))
    strategy.bind_geometry(axis=(1.0, 0.0), reference=(50.0, 0.0))
    constraints = strategy.constraints(20.0)
    assert constraints[0].metadata["axis_x"] == 1.0
    assert constraints[0].metadata["reference_x"] == 50.0
    assert constraints[0].metadata["value"] == 20.0


def test_angle_horizontal_strategy_builds_relative_body_angle_constraint() -> None:
    strategy = strategy_for(SweepDef(id="x", variable_kind="angle_horizontal", target_ids=["mA", "mB"]))
    strategy.bind_bodies(body_a_id="bodyA", body_b_id="__ground__", local_phi_a=0.0, local_phi_b=0.0)
    constraints = strategy.constraints(30.0)
    assert constraints[0].kind == "relative_body_angle"
    assert constraints[0].metadata["body_a_id"] == "bodyA"
    assert constraints[0].metadata["body_b_id"] == "__ground__"
    assert constraints[0].metadata["angle"] == 30.0


def _bar_project():
    svc = ApplicationService()
    svc.new_workspace("k")
    body_id = svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = svc.get_body(body_id)
    marker_a = next(marker for marker in body.markers if marker.name == "A")
    marker_b = next(marker for marker in body.markers if marker.name == "B")
    svc.connect_marker_to_ground(marker_a.id, joint_type="revolute", name="Pivot")
    return svc, body_id, marker_a, marker_b


def test_compute_sweep_base_value_marker_x() -> None:
    svc, body_id, marker_a, marker_b = _bar_project()
    pose = Pose(id="p1", name="P1", body_poses={body_id: BodyPose(body_id=body_id, x=10.0, y=20.0, angle=0.0)})
    sweep = SweepDef(id="sw", variable_kind="marker_x", target_ids=[marker_b.id])
    base = compute_sweep_base_value(svc.project, sweep, pose)
    # Marker B is at (100, 0) locally, body at (10, 20) → world x = 110
    assert base == 110.0


def test_compute_sweep_base_value_marker_y() -> None:
    svc, body_id, marker_a, marker_b = _bar_project()
    pose = Pose(id="p1", name="P1", body_poses={body_id: BodyPose(body_id=body_id, x=0.0, y=5.0, angle=math.radians(90))})
    sweep = SweepDef(id="sw", variable_kind="marker_y", target_ids=[marker_b.id])
    base = compute_sweep_base_value(svc.project, sweep, pose)
    # Marker B at (100, 0) locally, body rotated 90° at (0, 5):
    # world = (0 + cos(90)*100 - sin(90)*0, 5 + sin(90)*100 + cos(90)*0) = (0, 105)
    assert abs(base - 105.0) < 1e-9


def test_compute_sweep_base_value_angle_horizontal() -> None:
    svc, body_id, marker_a, marker_b = _bar_project()
    pose = Pose(id="p1", name="P1", body_poses={body_id: BodyPose(body_id=body_id, x=0.0, y=0.0, angle=math.radians(30))})
    sweep = SweepDef(id="sw", variable_kind="angle_horizontal", target_ids=[marker_a.id, marker_b.id])
    base = compute_sweep_base_value(svc.project, sweep, pose)
    # Segment A->B is horizontal in sketch (local_phi_a = 0).
    # Body rotated 30°, so world angle of segment = 30°.
    # base = body_angle + local_phi_a = 30°
    assert abs(base - math.radians(30)) < 1e-9
