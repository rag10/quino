from __future__ import annotations

from quino.analysis.kinematic_sweeps import SweepStrategy, strategy_for
from quino.domain.workspace import SweepDef


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
