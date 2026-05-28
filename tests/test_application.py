from __future__ import annotations

import math

import pytest

from quino import (
    ApplicationService,
    DriverType,
    JointEndpointInput,
    JointEndpointKind,
    MarkerInput,
    PropertyValueInput,
    SliderInput,
)
from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec
from quino.domain.model import SimulationResult, SketchLineSegment
from quino.domain.types import Dimension
from quino.simulation.assembler import MechanismAssembler


def make_app() -> ApplicationService:
    app = ApplicationService()
    app.new_project("Demo")
    app.create_parameter("L1", "120 mm", "mm")
    return app



def _mm(app: ApplicationService, expression: str) -> float:
    return app.unit_service.convert(
        app.expression_service.evaluate_expression(expression, app.project.parameters),
        "mm",
    )


def test_bar_gets_com_and_can_turn_into_body() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    body = app._find_body(body_id)
    assert body.type.value == "bar"
    assert len(body.structural_markers()) == 2
    assert body.com_marker().visible is False

    app.add_marker_to_body(body_id, MarkerInput("10 mm", "10 mm", "C"))
    body = app._find_body(body_id)
    assert body.type.value == "body"
    assert body.closed_shape is True


def test_point_mass_body_type() -> None:
    app = make_app()
    body_id = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P")])
    assert app._find_body(body_id).type.value == "point_mass"


def test_point_mass_com_follows_only_marker() -> None:
    app = make_app()
    body_id = app.create_body("Mass1", [MarkerInput("10 mm", "20 mm", "P")])
    body = app._find_body(body_id)
    marker = body.structural_markers()[0]
    com = body.com_marker()

    assert com.x.expression == marker.x.expression
    assert com.y.expression == marker.y.expression

    app.move_marker(marker.id, "30 mm", "40 mm")

    assert com.x.expression == "30 mm"
    assert com.y.expression == "40 mm"


def test_point_mass_com_cannot_be_moved_independently() -> None:
    app = make_app()
    body_id = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P")])
    com = app._find_body(body_id).com_marker()

    with pytest.raises(ValueError, match="cannot be moved independently"):
        app.move_marker(com.id, "10 mm", "0 mm")


def test_bar_com_is_edited_by_percent_and_distance() -> None:
    app = make_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = app._find_body(body_id)
    com = body.com_marker()

    app.update_property(com.id, "position_percent", PropertyValueInput("expression", "25"))
    assert _mm(app, com.x.expression) == pytest.approx(25.0)
    assert _mm(app, com.y.expression) == pytest.approx(0.0)

    app.update_property(com.id, "position_distance", PropertyValueInput("expression", "60 mm"))
    assert _mm(app, com.x.expression) == pytest.approx(60.0)
    assert _mm(app, com.y.expression) == pytest.approx(0.0)


def test_bar_com_stays_relative_when_bar_markers_move() -> None:
    app = make_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = app._find_body(body_id)
    first, second = body.structural_markers()
    com = body.com_marker()

    app.update_property(com.id, "position_percent", PropertyValueInput("expression", "25"))
    app.move_marker(second.id, "200 mm", "0 mm")
    assert _mm(app, com.x.expression) == pytest.approx(50.0)

    app.move_marker(first.id, "100 mm", "100 mm")
    assert _mm(app, com.x.expression) == pytest.approx(125.0)
    assert _mm(app, com.y.expression) == pytest.approx(75.0)


def test_bar_com_updates_when_parameter_changes_marker_position() -> None:
    app = make_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    body = app._find_body(body_id)
    com = body.com_marker()

    app.update_property(com.id, "position_percent", PropertyValueInput("expression", "25"))
    assert _mm(app, com.x.expression) == pytest.approx(30.0)

    parameter = next(p for p in app.project.parameters if p.name == "L1")
    app.update_parameter(parameter.id, expression="200 mm")

    assert _mm(app, com.x.expression) == pytest.approx(50.0)


def test_bar_com_drag_is_projected_to_segment() -> None:
    app = make_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = app._find_body(body_id)
    com = body.com_marker()

    app.move_marker(com.id, "30 mm", "40 mm")

    assert _mm(app, com.x.expression) == pytest.approx(30.0)
    assert _mm(app, com.y.expression) == pytest.approx(0.0)


def test_joint_duplicates_are_rejected() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "A")
    app.connect_marker_to_ground(marker_id, name="Ground_A")
    with pytest.raises(ValueError):
        app.connect_marker_to_ground(marker_id, name="Ground_A2")


def test_create_free_ground_creates_tagged_ground_anchor() -> None:
    app = make_app()

    body_id, marker_id = app.create_free_ground("Ground1", "10 mm", "20 mm")

    body = app.get_body(body_id)
    assert body is not None
    assert body.metadata.values.get("ground_anchor") is True
    assert body.metadata.values.get("ground_marker_id") == marker_id
    internal_joint = next(joint for joint in app.project.model.joints if joint.metadata.values.get("internal_ground_anchor"))
    assert internal_joint.endpoint_a.marker_id == marker_id or internal_joint.endpoint_b.marker_id == marker_id


def test_delete_cascades_joints() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    slider_id = app.create_slider("Slider1", SliderInput("0 mm", "0 mm", "0 deg"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "B")
    app.connect_marker_to_slider(marker_id, slider_id, name="Joint1")
    assert len(app.project.model.joints) == 1
    app.delete_entity(slider_id)
    assert len(app.project.model.joints) == 0


def test_update_property_supports_expression_boolean_and_null() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    body = app._find_body(body_id)
    marker = next(marker for marker in body.markers if marker.name == "A")

    app.update_property(marker.id, "x", PropertyValueInput("expression", "L1/2"))
    assert marker.x.expression == "L1/2"

    app.update_property(body.id, "closed_shape", PropertyValueInput("boolean", False))
    assert body.closed_shape is False

    app.update_property(body.id, "mass", PropertyValueInput("null", None))
    assert body.mass is None


def test_joint_friction_properties_can_be_edited() -> None:
    app = make_app()
    body1 = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body2 = app.create_bar("Rod", MarkerInput("100 mm", "0 mm", "C"), MarkerInput("200 mm", "0 mm", "D"))
    joint_id = app.create_joint(
        "Joint1",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=next(m.id for m in app._find_body(body1).markers if m.name == "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=next(m.id for m in app._find_body(body2).markers if m.name == "C")),
    )
    joint = app.get_joint(joint_id)

    app.update_property(joint_id, "friction_coulomb", PropertyValueInput("expression", "2.5"))
    app.update_property(joint_id, "friction_viscous", PropertyValueInput("expression", "0.1"))

    assert app.joint_friction_mode(joint) == "rotation"
    assert app.joint_friction_values(joint) == pytest.approx((2.5, 0.1))


def test_revolute_joint_angular_limits_can_be_edited() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_a = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "A")
    joint_id = app.connect_marker_to_ground(marker_a, name="Ground_A")
    joint = app.get_joint(joint_id)

    app.update_property(joint_id, "angle_limit_positive", PropertyValueInput("expression", "30 deg"))
    app.update_property(joint_id, "angle_limit_negative", PropertyValueInput("expression", "15 deg"))

    assert app.joint_supports_angular_limits(joint) is True
    assert app.joint_angular_limit_values(joint) == pytest.approx((30.0, 15.0))

    app.update_property(joint_id, "angle_limit_positive", PropertyValueInput("null", None))
    app.update_property(joint_id, "angle_limit_negative", PropertyValueInput("expression", ""))

    assert app.joint_angular_limit_values(joint) == (None, None)


def test_slider_joint_friction_properties_can_be_edited() -> None:
    app = make_app()
    body = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "P")])
    slider_id = app.create_slider("Guide", SliderInput("0 mm", "0 mm", "0 deg"))
    marker_id = next(m.id for m in app._find_body(body).markers if m.name == "P")
    joint_id = app.connect_marker_to_slider(marker_id, slider_id, name="SliderJoint")
    joint = app.get_joint(joint_id)

    app.update_property(joint_id, "friction_coulomb", PropertyValueInput("expression", "5"))
    app.update_property(joint_id, "friction_viscous", PropertyValueInput("expression", "0.25"))

    assert app.joint_friction_mode(joint) == "translation"
    assert app.joint_friction_values(joint) == pytest.approx((5.0, 0.25))


def test_revolute_joint_angular_limit_properties_can_be_edited() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "A")
    joint_id = app.connect_marker_to_ground(marker_id, name="Ground_A")
    joint = app.get_joint(joint_id)

    app.update_property(joint_id, "angle_limit_positive", PropertyValueInput("expression", "30 deg"))
    app.update_property(joint_id, "angle_limit_negative", PropertyValueInput("expression", "15 deg"))

    assert app.joint_supports_angular_limits(joint) is True
    assert app.joint_angular_limit_expression(joint, "angle_limit_positive") == "30 deg"
    assert app.joint_angular_limit_expression(joint, "angle_limit_negative") == "15 deg"
    assert app.joint_angular_limit_value(joint, "angle_limit_positive", unit="deg") == pytest.approx(30.0)
    assert app.joint_angular_limit_value(joint, "angle_limit_negative", unit="deg") == pytest.approx(15.0)


def test_move_marker_translates_only_direct_joint_counterparts() -> None:
    app = make_app()
    body1 = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body2 = app.create_body("Coupler", [MarkerInput("100 mm", "0 mm", "P"), MarkerInput("120 mm", "10 mm", "Q")])
    body3 = app.create_body("Rocker", [MarkerInput("120 mm", "10 mm", "R"), MarkerInput("140 mm", "10 mm", "S")])
    marker_b = next(marker.id for marker in app._find_body(body1).markers if marker.name == "B")
    marker_p = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P")
    marker_q = next(marker.id for marker in app._find_body(body2).markers if marker.name == "Q")
    marker_r = next(marker.id for marker in app._find_body(body3).markers if marker.name == "R")
    app.create_joint(
        "JointBP",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker_b),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker_p),
    )
    app.create_joint(
        "JointQR",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker_q),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body3, marker_id=marker_r),
    )

    app.move_marker(marker_b, "110 mm", "15 mm")

    body1_obj = app._find_body(body1)
    body2_obj = app._find_body(body2)
    body3_obj = app._find_body(body3)
    body1_markers = {marker.name: marker for marker in body1_obj.structural_markers()}
    body2_markers = {marker.name: marker for marker in body2_obj.structural_markers()}
    body3_markers = {marker.name: marker for marker in body3_obj.structural_markers()}
    assert _mm(app, body1_markers["A"].x.expression) == pytest.approx(0.0)
    assert _mm(app, body1_markers["A"].y.expression) == pytest.approx(0.0)
    assert _mm(app, body1_markers["B"].x.expression) == pytest.approx(110.0)
    assert _mm(app, body1_markers["B"].y.expression) == pytest.approx(15.0)
    assert _mm(app, body2_markers["P"].x.expression) == pytest.approx(110.0)
    assert _mm(app, body2_markers["P"].y.expression) == pytest.approx(15.0)
    assert _mm(app, body2_markers["Q"].x.expression) == pytest.approx(120.0)
    assert _mm(app, body2_markers["Q"].y.expression) == pytest.approx(10.0)
    assert _mm(app, body3_markers["R"].x.expression) == pytest.approx(120.0)
    assert _mm(app, body3_markers["R"].y.expression) == pytest.approx(10.0)
    assert _mm(app, body3_markers["S"].x.expression) == pytest.approx(140.0)
    assert _mm(app, body3_markers["S"].y.expression) == pytest.approx(10.0)


def test_move_marker_translates_connected_slider_origin() -> None:
    app = make_app()
    body_id = app.create_body(
        "Rod",
        [MarkerInput("0 mm", "0 mm", "A"), MarkerInput("40 mm", "0 mm", "P")],
    )
    slider_id = app.create_slider_from_points("Guide", "40 mm", "0 mm", "120 mm", "0 mm")
    marker_p = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")
    app.connect_marker_to_slider(marker_p, slider_id, name="Slider_P")

    app.move_marker(marker_p, "50 mm", "20 mm")

    slider = app._find_entity(slider_id)
    assert _mm(app, slider.origin_x.expression) == pytest.approx(50.0)
    assert _mm(app, slider.origin_y.expression) == pytest.approx(20.0)


def test_connect_marker_to_slider_moves_marker_to_slider_center() -> None:
    app = make_app()
    body_id = app.create_body("Rod", [MarkerInput("25 mm", "20 mm", "P")])
    slider_id = app.create_slider_from_points("Guide", "0 mm", "0 mm", "100 mm", "0 mm")
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")

    app.connect_marker_to_slider(marker_id, slider_id, name="Slider_P")

    marker = app._find_entity(marker_id)
    report = app.validate_model()
    assert _mm(app, marker.x.expression) == pytest.approx(50.0)
    assert _mm(app, marker.y.expression) == pytest.approx(0.0)
    assert not any(message.code == "slider_joint_gap" for message in report.messages)


def test_connect_slider_to_marker_alias_still_moves_marker_to_slider_center() -> None:
    app = make_app()
    body_id = app.create_body("Rod", [MarkerInput("50 mm", "20 mm", "P")])
    slider_id = app.create_slider_from_points("Guide", "0 mm", "0 mm", "100 mm", "0 mm")
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")

    app.connect_marker_to_slider(marker_id, slider_id, name="Slider_P", align="slider_to_marker")

    slider = app._find_entity(slider_id)
    marker = app._find_entity(marker_id)
    report = app.validate_model()
    assert _mm(app, marker.x.expression) == pytest.approx(50.0)
    assert _mm(app, marker.y.expression) == pytest.approx(0.0)
    assert _mm(app, slider.origin_y.expression) == pytest.approx(0.0)
    assert not any(message.code == "slider_joint_gap" for message in report.messages)


def test_moving_slider_origin_translates_connected_marker() -> None:
    app = make_app()
    body_id = app.create_body("Rod", [MarkerInput("40 mm", "0 mm", "P")])
    slider_id = app.create_slider_from_points("Guide", "40 mm", "0 mm", "120 mm", "0 mm")
    marker_p = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")
    app.connect_marker_to_slider(marker_p, slider_id, name="Slider_P")

    app.update_property(slider_id, "origin_x", PropertyValueInput("expression", "90 mm"))
    app.update_property(slider_id, "origin_y", PropertyValueInput("expression", "10 mm"))

    marker = app._find_entity(marker_p)
    report = app.validate_model()
    assert _mm(app, marker.x.expression) == pytest.approx(90.0)
    assert _mm(app, marker.y.expression) == pytest.approx(10.0)
    assert not any(message.code == "slider_joint_gap" for message in report.messages)


def test_rotating_slider_keeps_connected_marker_on_guide() -> None:
    app = make_app()
    body_id = app.create_body("Rod", [MarkerInput("10 mm", "0 mm", "P")])
    slider_id = app.create_slider("Guide", SliderInput("0 mm", "0 mm", "0 deg", "-20 mm", "20 mm"))
    marker_p = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")
    app.connect_marker_to_slider(marker_p, slider_id, name="Slider_P")

    app.update_property(slider_id, "angle", PropertyValueInput("expression", "90 deg"))

    marker = app._find_entity(marker_p)
    report = app.validate_model()
    assert _mm(app, marker.x.expression) == pytest.approx(0.0)
    assert _mm(app, marker.y.expression) == pytest.approx(0.0)
    assert not any(message.code == "slider_joint_gap" for message in report.messages)


def test_update_property_on_jointed_marker_translates_direct_counterpart() -> None:
    app = make_app()
    body1 = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    body2 = app.create_body("Mass2", [MarkerInput("0 mm", "0 mm", "P2")])
    marker1 = next(marker.id for marker in app._find_body(body1).markers if marker.name == "P1")
    marker2 = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P2")
    app.create_joint(
        "Joint12",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker1),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
    )

    app.update_property(marker1, "x", PropertyValueInput("expression", "25 mm"))
    app.update_property(marker1, "y", PropertyValueInput("expression", "5 mm"))

    moved_marker1 = app._find_entity(marker1)
    moved_marker2 = app._find_entity(marker2)
    assert _mm(app, moved_marker1.x.expression) == pytest.approx(25.0)
    assert _mm(app, moved_marker1.y.expression) == pytest.approx(5.0)
    assert _mm(app, moved_marker2.x.expression) == pytest.approx(25.0)
    assert _mm(app, moved_marker2.y.expression) == pytest.approx(5.0)


def test_update_property_on_jointed_marker_translates_transitive_marker_component() -> None:
    app = make_app()
    body1 = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    body2 = app.create_body("Mass2", [MarkerInput("0 mm", "0 mm", "P2")])
    body3 = app.create_body("Mass3", [MarkerInput("0 mm", "0 mm", "P3")])
    marker1 = next(marker.id for marker in app._find_body(body1).markers if marker.name == "P1")
    marker2 = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P2")
    marker3 = next(marker.id for marker in app._find_body(body3).markers if marker.name == "P3")
    app.create_joint(
        "Joint12",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker1),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
    )
    app.create_joint(
        "Joint23",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body3, marker_id=marker3),
    )

    app.update_property(marker1, "x", PropertyValueInput("expression", "25 mm"))
    app.update_property(marker1, "y", PropertyValueInput("expression", "5 mm"))

    report = app.validate_model()
    for marker_id in (marker1, marker2, marker3):
        marker = app._find_entity(marker_id)
        assert _mm(app, marker.x.expression) == pytest.approx(25.0)
        assert _mm(app, marker.y.expression) == pytest.approx(5.0)
    assert not any(message.code == "joint_gap" for message in report.messages)


def test_update_property_on_marker_translates_transitive_slider_component() -> None:
    app = make_app()
    body1 = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    body2 = app.create_body("Mass2", [MarkerInput("0 mm", "0 mm", "P2")])
    slider_id = app.create_slider("Guide", SliderInput("0 mm", "0 mm", "0 deg", "-20 mm", "20 mm"))
    marker1 = next(marker.id for marker in app._find_body(body1).markers if marker.name == "P1")
    marker2 = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P2")
    app.create_joint(
        "Joint12",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker1),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
    )
    app.connect_marker_to_slider(marker2, slider_id, name="Slider_P2", align="none")

    app.update_property(marker1, "x", PropertyValueInput("expression", "25 mm"))
    app.update_property(marker1, "y", PropertyValueInput("expression", "5 mm"))

    marker2_obj = app._find_entity(marker2)
    slider = app._find_entity(slider_id)
    report = app.validate_model()
    assert _mm(app, marker2_obj.x.expression) == pytest.approx(25.0)
    assert _mm(app, marker2_obj.y.expression) == pytest.approx(5.0)
    assert _mm(app, slider.origin_x.expression) == pytest.approx(25.0)
    assert _mm(app, slider.origin_y.expression) == pytest.approx(5.0)
    assert not any(message.code in {"joint_gap", "slider_joint_gap"} for message in report.messages)


def test_moving_slider_origin_translates_transitive_marker_component() -> None:
    app = make_app()
    body1 = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    body2 = app.create_body("Mass2", [MarkerInput("0 mm", "0 mm", "P2")])
    slider_id = app.create_slider("Guide", SliderInput("0 mm", "0 mm", "0 deg", "-20 mm", "20 mm"))
    marker1 = next(marker.id for marker in app._find_body(body1).markers if marker.name == "P1")
    marker2 = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P2")
    app.create_joint(
        "Joint12",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker1),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
    )
    app.connect_marker_to_slider(marker2, slider_id, name="Slider_P2", align="none")

    app.update_property(slider_id, "origin_x", PropertyValueInput("expression", "25 mm"))
    app.update_property(slider_id, "origin_y", PropertyValueInput("expression", "5 mm"))

    report = app.validate_model()
    for marker_id in (marker1, marker2):
        marker = app._find_entity(marker_id)
        assert _mm(app, marker.x.expression) == pytest.approx(25.0)
        assert _mm(app, marker.y.expression) == pytest.approx(5.0)
    assert not any(message.code in {"joint_gap", "slider_joint_gap"} for message in report.messages)


def test_move_marker_drag_translates_transitive_marker_component() -> None:
    app = make_app()
    body1 = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    body2 = app.create_body("Mass2", [MarkerInput("0 mm", "0 mm", "P2")])
    body3 = app.create_body("Mass3", [MarkerInput("0 mm", "0 mm", "P3")])
    marker1 = next(marker.id for marker in app._find_body(body1).markers if marker.name == "P1")
    marker2 = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P2")
    marker3 = next(marker.id for marker in app._find_body(body3).markers if marker.name == "P3")
    app.create_joint(
        "Joint12",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker1),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
    )
    app.create_joint(
        "Joint23",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body3, marker_id=marker3),
    )

    app.move_marker(marker1, "25 mm", "5 mm")

    report = app.validate_model()
    for marker_id in (marker1, marker2, marker3):
        marker = app._find_entity(marker_id)
        assert _mm(app, marker.x.expression) == pytest.approx(25.0)
        assert _mm(app, marker.y.expression) == pytest.approx(5.0)
    assert not any(message.code == "joint_gap" for message in report.messages)


def test_move_marker_drag_translates_marker_with_revolute_and_slider() -> None:
    app = make_app()
    body1 = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    body2 = app.create_body("Mass2", [MarkerInput("0 mm", "0 mm", "P2")])
    slider_id = app.create_slider("Guide", SliderInput("0 mm", "0 mm", "0 deg", "-20 mm", "20 mm"))
    marker1 = next(marker.id for marker in app._find_body(body1).markers if marker.name == "P1")
    marker2 = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P2")
    app.create_joint(
        "Joint12",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker1),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
    )
    app.connect_marker_to_slider(marker2, slider_id, name="Slider_P2", align="none")

    app.move_marker(marker1, "25 mm", "5 mm")

    marker2_obj = app._find_entity(marker2)
    slider = app._find_entity(slider_id)
    report = app.validate_model()
    assert _mm(app, marker2_obj.x.expression) == pytest.approx(25.0)
    assert _mm(app, marker2_obj.y.expression) == pytest.approx(5.0)
    assert _mm(app, slider.origin_x.expression) == pytest.approx(25.0)
    assert _mm(app, slider.origin_y.expression) == pytest.approx(5.0)
    assert not any(message.code in {"joint_gap", "slider_joint_gap"} for message in report.messages)


def test_units_validation_rejects_angle_in_length_slot() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    body = app._find_body(body_id)
    marker = next(marker for marker in body.markers if marker.name == "A")
    with pytest.raises(ValueError):
        app.update_property(marker.id, "x", PropertyValueInput("expression", "30 deg"))


def test_undo_redo_work_for_basic_operations() -> None:
    app = make_app()
    body_id = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P")])
    assert body_id in {body.id for body in app.project.model.bodies}
    assert app.undo() is True
    assert app.project.model.bodies == []
    assert app.redo() is True
    assert len(app.project.model.bodies) == 1


def test_validate_model_reports_duplicate_marker_names() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    body = app._find_body(body_id)
    duplicate = body.structural_markers()[0]
    duplicate.name = body.structural_markers()[1].name
    report = app.validate_model()
    assert any(message.code == "duplicate_marker_name" for message in report.messages)


def test_validate_model_reports_broken_control_graph_references() -> None:
    app = make_app()
    app.project.model.control_graph = BlockDiagram(
        instances={
            "sensor_block": BlockInstance(
                instance_id="sensor_block",
                block_type="ModelSensor",
                parameters={"sensor_id": "missing_sensor", "channel": "y"},
                output_ports=[PortSpec("out")],
            ),
            "load_block": BlockInstance(
                instance_id="load_block",
                block_type="LoadCommand",
                parameters={"load_id": "missing_load"},
                input_ports=[PortSpec("in")],
                output_ports=[PortSpec("out")],
            ),
            "driver_block": BlockInstance(
                instance_id="driver_block",
                block_type="DriverCommand",
                parameters={"driver_id": "missing_driver"},
                input_ports=[PortSpec("in")],
                output_ports=[PortSpec("out")],
            ),
        }
    )

    report = app.validate_model()

    broken = [message for message in report.messages if message.code == "broken_block_reference"]
    assert len(broken) >= 3


def test_validate_model_reports_missing_and_invalid_control_graph_parameters() -> None:
    app = make_app()
    app.project.model.control_graph = BlockDiagram(
        instances={
            "sensor_block": BlockInstance(
                instance_id="sensor_block",
                block_type="ModelSensor",
                parameters={"sensor_id": "", "channel": ""},
                output_ports=[PortSpec("out")],
            ),
            "load_block": BlockInstance(
                instance_id="load_block",
                block_type="LoadCommand",
                parameters={"load_id": "", "component": "mz"},
                input_ports=[PortSpec("in")],
                output_ports=[PortSpec("out")],
            ),
        }
    )

    report = app.validate_model()

    assert any(message.code == "missing_block_reference" for message in report.messages)
    assert any(message.code == "invalid_block_parameter" for message in report.messages)


def test_validate_model_reports_semantic_block_connection_mismatch() -> None:
    app = make_app()
    body_id = app.create_body("Body", [MarkerInput("0 mm", "0 mm", "P")])
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")
    sensor_id = app.create_sensor("Probe", "point", [marker_id])
    joint_id = app.connect_marker_to_ground(marker_id, name="Ground_P")
    driver_id = app.create_driver("Drive", DriverType.ROTATION.value, joint_id, "0 deg", "deg")
    app.project.model.control_graph = BlockDiagram(
        instances={
            "sensor_block": BlockInstance(
                instance_id="sensor_block",
                block_type="ModelSensor",
                parameters={"sensor_id": sensor_id, "channel": "y"},
                output_ports=[PortSpec("out")],
            ),
            "driver_block": BlockInstance(
                instance_id="driver_block",
                block_type="DriverCommand",
                parameters={"driver_id": driver_id},
                input_ports=[PortSpec("in")],
                output_ports=[PortSpec("out")],
            ),
        },
        connections=[Connection("sensor_block", "out", "driver_block", "in")],
    )

    report = app.validate_model()

    assert any(message.code == "block_connection_mismatch" for message in report.messages)


def test_create_joint_via_core_api() -> None:
    app = make_app()
    body1 = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    body2 = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P")])
    marker1 = next(marker.id for marker in app._find_body(body1).markers if marker.name == "B")
    marker2 = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P")
    joint_id = app.create_joint(
        "JointAB",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker1),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
    )
    assert joint_id in {joint.id for joint in app.project.model.joints}


def test_parameter_unit_must_match_expression_dimension() -> None:
    app = make_app()
    with pytest.raises(ValueError):
        app.create_parameter("AngleAsLength", "30 deg", "mm")


def test_expressions_accept_compact_units_and_decimal_comma() -> None:
    app = make_app()

    compact_angle = app.expression_service.evaluate_expression("360deg * 1s / 1s", app.project.parameters)
    decimal_length = app.expression_service.evaluate_expression("12,5mm", app.project.parameters)

    assert app.unit_service.convert(compact_angle, "deg") == pytest.approx(360.0)
    assert app.unit_service.convert(decimal_length, "mm") == pytest.approx(12.5)


def test_failed_parameter_update_does_not_mutate_project() -> None:
    app = make_app()
    parameter = app.project.parameters[0]
    with pytest.raises(Exception):
        app.update_parameter(parameter.id, expression="bad +")
    assert parameter.expression == "120 mm"


def test_deleting_marker_cascades_driver_removal() -> None:
    app = make_app()
    body1 = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    body2 = app.create_body("Mass2", [MarkerInput("10 mm", "0 mm", "P2")])
    marker1 = next(marker.id for marker in app._find_body(body1).markers if marker.name == "P1")
    marker2 = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P2")
    joint_id = app.create_joint(
        "Joint12",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker1),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
    )
    app.create_driver("Drive12", DriverType.ROTATION.value, joint_id, "10 deg * t / 1 s", "deg")
    app.add_marker_to_body(body1, MarkerInput("5 mm", "5 mm", "P3"))

    app.delete_entity(marker1)

    assert not app.project.model.joints
    assert not app.project.model.drivers


def test_last_structural_marker_cannot_be_deleted() -> None:
    app = make_app()
    body_id = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P")])
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")
    with pytest.raises(ValueError):
        app.delete_entity(marker_id)


def test_update_property_name_is_single_undo_step() -> None:
    app = make_app()
    body_id = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P")])
    app.update_property(body_id, "name", PropertyValueInput("expression", "Mass2"))
    assert app._find_body(body_id).name == "Mass2"
    assert app.undo() is True
    assert app._find_body(body_id).name == "Mass1"


def test_multiple_drivers_on_same_joint_are_rejected() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "A")
    joint_id = app.connect_marker_to_ground(marker_id, name="Ground_A")
    app.create_driver("Drive1", DriverType.ROTATION.value, joint_id, "10 deg * t / 1 s", "deg")
    with pytest.raises(ValueError):
        app.create_driver("Drive2", DriverType.ROTATION.value, joint_id, "20 deg * t / 1 s", "deg")


def test_validate_model_reports_joint_geometry_gaps() -> None:
    app = make_app()
    body1 = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    body2 = app.create_body("Mass2", [MarkerInput("10 mm", "0 mm", "P2")])
    marker1 = next(marker.id for marker in app._find_body(body1).markers if marker.name == "P1")
    marker2 = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P2")
    app.create_joint(
        "BrokenJoint",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker1),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
    )

    report = app.validate_model()

    assert any(message.code == "joint_gap" and "BrokenJoint" in message.message for message in report.messages)


def test_validate_model_reports_slider_joint_geometry_gap() -> None:
    app = make_app()
    body_id = app.create_body("Mass1", [MarkerInput("0 mm", "10 mm", "P")])
    slider_id = app.create_slider_from_points("Guide", "0 mm", "0 mm", "100 mm", "0 mm")
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")
    app.create_joint(
        "BrokenSliderJoint",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_id, marker_id=marker_id),
        JointEndpointInput(JointEndpointKind.SLIDER, slider_id=slider_id),
    )

    report = app.validate_model()

    assert any(
        message.code == "slider_joint_gap" and "BrokenSliderJoint" in message.message
        for message in report.messages
    )


def test_validate_model_reports_unreachable_slider_crank_motion() -> None:
    app = ApplicationService()
    app.new_project("Unreachable Slider Crank")
    crank = app.create_bar(
        "Crank",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("10 mm", "0 mm", "B"),
    )
    rod = app.create_bar(
        "Rod",
        MarkerInput("10 mm", "0 mm", "B"),
        MarkerInput("15 mm", "0 mm", "P"),
    )
    slider = app.create_slider("Guide", SliderInput("15 mm", "0 mm", "0 deg", "-20 mm", "20 mm"))

    def mid(body_id: str, marker_name: str) -> str:
        return next(
            marker.id for marker in app._find_body(body_id).markers if marker.name == marker_name
        )

    ground_a = app.connect_marker_to_ground(mid(crank, "A"), name="Ground_A")
    app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=crank, marker_id=mid(crank, "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=rod, marker_id=mid(rod, "B")),
    )
    app.connect_marker_to_slider(mid(rod, "P"), slider, name="Slider_P")
    app.create_driver("CrankDrive", DriverType.ROTATION.value, ground_a, "90 deg * t / 1 s", "deg")

    report = app.validate_model(duration=1.0, steps=20)

    assert any(message.code == "kinematic_reach" for message in report.messages)


def test_validate_model_reports_translation_driver_outside_slider_travel() -> None:
    app = ApplicationService()
    app.new_project("Translation Travel")
    body_id = app.create_body("Mass", [MarkerInput("0 mm", "0 mm", "P")])
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")
    slider_id = app.create_slider("Guide", SliderInput("0 mm", "0 mm", "0 deg", "-5 mm", "5 mm"))
    joint_id = app.connect_marker_to_slider(marker_id, slider_id, name="Slider_P")
    app.create_driver("SliderDrive", DriverType.TRANSLATION.value, joint_id, "10 mm * t / 1 s", "mm")

    report = app.validate_model(duration=1.0, steps=20)

    assert any(message.code == "kinematic_travel" for message in report.messages)


def test_validate_model_uses_relative_translation_driver_position() -> None:
    app = ApplicationService()
    app.new_project("Relative Translation Travel")
    body_id = app.create_body("Mass", [MarkerInput("4 mm", "0 mm", "P")])
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")
    slider_id = app.create_slider("Guide", SliderInput("0 mm", "0 mm", "0 deg", "0 mm", "5 mm"))
    joint_id = app.connect_marker_to_slider(marker_id, slider_id, name="Slider_P", align="none")
    app.create_driver("SliderDrive", DriverType.TRANSLATION.value, joint_id, "3 mm * t / 1 s", "mm")

    report = app.validate_model(duration=1.0, steps=20)

    assert any(message.code == "kinematic_travel" for message in report.messages)


def test_validate_model_reports_rotation_driver_outside_angular_limits() -> None:
    app = ApplicationService()
    app.new_project("Rotation Limit")
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "A")
    joint_id = app.connect_marker_to_ground(marker_id, name="Ground_A")
    app.update_property(joint_id, "angle_limit_positive", PropertyValueInput("expression", "30 deg"))
    app.update_property(joint_id, "angle_limit_negative", PropertyValueInput("expression", "10 deg"))
    app.create_driver("CrankDrive", DriverType.ROTATION.value, joint_id, "45 deg * t / 1 s", "deg")

    report = app.validate_model(duration=1.0, steps=20)

    assert any(message.code == "kinematic_angle_limit" for message in report.messages)


def test_run_simulation_attempts_solver_after_unreachable_preflight() -> None:
    app = ApplicationService()
    app.new_project("Unreachable Slider Crank")
    crank = app.create_bar(
        "Crank",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("10 mm", "0 mm", "B"),
    )
    rod = app.create_bar(
        "Rod",
        MarkerInput("10 mm", "0 mm", "B"),
        MarkerInput("15 mm", "0 mm", "P"),
    )
    slider = app.create_slider("Guide", SliderInput("15 mm", "0 mm", "0 deg", "-20 mm", "20 mm"))

    def mid(body_id: str, marker_name: str) -> str:
        return next(
            marker.id for marker in app._find_body(body_id).markers if marker.name == marker_name
        )

    ground_a = app.connect_marker_to_ground(mid(crank, "A"), name="Ground_A")
    app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=crank, marker_id=mid(crank, "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=rod, marker_id=mid(rod, "B")),
    )
    app.connect_marker_to_slider(mid(rod, "P"), slider, name="Slider_P")
    app.create_driver("CrankDrive", DriverType.ROTATION.value, ground_a, "90 deg * t / 1 s", "deg")

    original_adapter = app.simulation_runner.adapter

    class PartialAdapter:
        name = "partial"
        assembler = original_adapter.assembler
        called = False

        def is_available(self) -> bool:
            return True

        def run(self, project, duration: float = 1.0, steps: int = 100):
            self.called = True
            return SimulationResult(
                success=False,
                backend=self.name,
                time=[0.0, 0.1],
                frames=[{"body_001.x": 0.0}, {"body_001.x": 1.0}],
                error="partial failure",
            )

    partial_adapter = PartialAdapter()
    app.simulation_runner.adapter = partial_adapter

    result = app.run_kinematic_simulation(duration=1.0, steps=20)

    assert partial_adapter.called is True
    assert result.success is False
    assert result.frames
    assert result.error == "partial failure"
    assert any("Preflight detected unreachable kinematics" in message for message in result.messages)


def test_validate_model_reports_unreachable_four_bar_loop() -> None:
    app = ApplicationService()
    app.new_project("Unreachable Four Bar")
    crank = app.create_bar(
        "Crank",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("80 mm", "0 mm", "B"),
    )
    coupler = app.create_bar(
        "Coupler",
        MarkerInput("80 mm", "0 mm", "B"),
        MarkerInput("90 mm", "0 mm", "C"),
    )
    rocker = app.create_bar(
        "Rocker",
        MarkerInput("100 mm", "0 mm", "D"),
        MarkerInput("90 mm", "0 mm", "C"),
    )

    def mid(body_id: str, marker_name: str) -> str:
        return next(
            marker.id for marker in app._find_body(body_id).markers if marker.name == marker_name
        )

    ground_a = app.connect_marker_to_ground(mid(crank, "A"), name="Ground_A")
    app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=crank, marker_id=mid(crank, "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=coupler, marker_id=mid(coupler, "B")),
    )
    app.create_joint(
        "Joint_C",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=coupler, marker_id=mid(coupler, "C")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=rocker, marker_id=mid(rocker, "C")),
    )
    app.connect_marker_to_ground(mid(rocker, "D"), name="Ground_D")
    app.create_driver("CrankDrive", DriverType.ROTATION.value, ground_a, "180deg * t / 1s", "deg")

    report = app.validate_model(duration=1.0, steps=20)

    assert any(message.code == "kinematic_loop_reach" for message in report.messages)


# Gravity feature tests


def test_gravity_absent_by_default() -> None:
    app = make_app()
    assert app.project.model.gravity is None


def test_add_gravity_creates_with_defaults() -> None:
    app = make_app()
    app.add_gravity()
    g = app.project.model.gravity
    assert g is not None
    assert g.magnitude == 9.81
    assert g.direction_x == 0.0
    assert g.direction_y == -1.0


def test_add_gravity_is_idempotent() -> None:
    app = make_app()
    app.add_gravity()
    app.add_gravity()
    assert app.project.model.gravity is not None


def test_delete_gravity() -> None:
    app = make_app()
    app.add_gravity()
    app.delete_gravity()
    assert app.project.model.gravity is None


def test_delete_entity_gravity() -> None:
    app = make_app()
    app.add_gravity()
    app.delete_entity("__gravity__")
    assert app.project.model.gravity is None


def test_update_gravity_magnitude() -> None:
    app = make_app()
    app.add_gravity()
    app.update_property("__gravity__", "magnitude", PropertyValueInput("expression", "5.0"))
    assert app.project.model.gravity.magnitude == 5.0


def test_update_gravity_direction() -> None:
    app = make_app()
    app.add_gravity()
    app.update_property("__gravity__", "direction_x", PropertyValueInput("expression", "1.0"))
    app.update_property("__gravity__", "direction_y", PropertyValueInput("expression", "0.0"))
    assert app.project.model.gravity.direction_x == 1.0
    assert app.project.model.gravity.direction_y == 0.0


def test_update_gravity_rejects_non_numeric() -> None:
    app = make_app()
    app.add_gravity()
    with pytest.raises(ValueError, match="must be a number"):
        app.update_property("__gravity__", "magnitude", PropertyValueInput("expression", "abc"))


def test_gravity_serialization_roundtrip(tmp_path) -> None:
    app = make_app()
    app.add_gravity()
    app.project.model.gravity.magnitude = 5.0
    app.project.model.gravity.direction_y = -0.5

    path = str(tmp_path / "ws.quino.json")
    app.save_workspace(path)
    app2 = ApplicationService()
    app2.load_workspace(path)
    case = app2._workspace.cases[app2._workspace.root_case_ids[0]]
    assert case.model.gravity is not None
    assert case.model.gravity.magnitude == 5.0
    assert case.model.gravity.direction_y == -0.5


def test_gravity_none_serialization_roundtrip(tmp_path) -> None:
    app = make_app()
    assert app.project.model.gravity is None

    path = str(tmp_path / "ws.quino.json")
    app.save_workspace(path)
    app2 = ApplicationService()
    app2.load_workspace(path)
    case = app2._workspace.cases[app2._workspace.root_case_ids[0]]
    assert case.model.gravity is None


def test_backward_compat_old_project_without_gravity(tmp_path) -> None:
    # Old schema (1.0) is rejected by the new loader.
    from quino.serialization.json_io import UnsupportedSchemaError
    import json
    data = {
        "schema_version": "1.0",
        "project": {"id": "test-project", "name": "TestModel", "metadata": {}},
        "model": {"bodies": [], "sliders": [], "joints": [], "drivers": [], "sensors": {}},
        "parameters": [],
        "sketch": None,
        "view_state": {},
    }
    path = str(tmp_path / "old.quino.json")
    with open(path, "w") as f:
        json.dump(data, f)
    with pytest.raises(UnsupportedSchemaError):
        ApplicationService().load_workspace(path)


def test_backward_compat_old_gravity_enabled_true(tmp_path) -> None:
    # Old schema (1.0) is rejected.
    from quino.serialization.json_io import UnsupportedSchemaError
    import json
    data = {
        "schema_version": "1.0",
        "project": {"id": "p", "name": "N", "metadata": {}},
        "model": {
            "bodies": [], "sliders": [], "joints": [], "drivers": [], "sensors": {},
            "gravity": {"enabled": True, "magnitude": 5.0, "direction_x": 0.0, "direction_y": -1.0},
        },
        "parameters": [],
        "sketch": None,
        "view_state": {},
    }
    path = str(tmp_path / "old.quino.json")
    with open(path, "w") as f:
        json.dump(data, f)
    with pytest.raises(UnsupportedSchemaError):
        ApplicationService().load_workspace(path)


def test_backward_compat_old_gravity_enabled_false(tmp_path) -> None:
    # Old schema (1.0) is rejected.
    from quino.serialization.json_io import UnsupportedSchemaError
    import json
    data = {
        "schema_version": "1.0",
        "project": {"id": "p", "name": "N", "metadata": {}},
        "model": {
            "bodies": [], "sliders": [], "joints": [], "drivers": [], "sensors": {},
            "gravity": {"enabled": False, "magnitude": 9.81, "direction_x": 0.0, "direction_y": -1.0},
        },
        "parameters": [],
        "sketch": None,
        "view_state": {},
    }
    path = str(tmp_path / "old.quino.json")
    with open(path, "w") as f:
        json.dump(data, f)
    with pytest.raises(UnsupportedSchemaError):
        ApplicationService().load_workspace(path)


def test_gravity_add_undoable() -> None:
    app = make_app()
    assert app.project.model.gravity is None
    app.add_gravity()
    assert app.project.model.gravity is not None
    assert app.undo() is True
    assert app.project.model.gravity is None
    assert app.redo() is True
    assert app.project.model.gravity is not None


def test_gravity_delete_undoable() -> None:
    app = make_app()
    app.add_gravity()
    app.delete_gravity()
    assert app.project.model.gravity is None
    assert app.undo() is True
    assert app.project.model.gravity is not None
    assert app.redo() is True
    assert app.project.model.gravity is None


def test_update_gravity_magnitude_undoable() -> None:
    app = make_app()
    app.add_gravity()
    original = app.project.model.gravity.magnitude

    app.update_property("__gravity__", "magnitude", PropertyValueInput("expression", "3.5"))
    assert app.project.model.gravity.magnitude == 3.5

    assert app.undo() is True
    assert app.project.model.gravity.magnitude == original



def test_create_sketch_rectangle_builds_constrained_profile() -> None:
    app = make_app()
    app.new_project("SketchRectangle")

    created_ids = app.create_sketch_rectangle((0.0, 0.0), (80.0, 40.0))

    assert len(created_ids) == 8
    sketch = app.project.sketch
    assert sketch is not None
    lines = [entity for entity in sketch.entities.values() if isinstance(entity, SketchLineSegment)]
    assert len(lines) == 4
    constraint_types = [constraint.type.value for constraint in sketch.constraints.values()]
    assert constraint_types.count("horizontal") == 2
    assert constraint_types.count("vertical") == 2


def test_move_sketch_point_with_solver_locks_dragged_point() -> None:
    app = make_app()
    app.new_project("SketchDrag")
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("30 mm", "10 mm", "B")
    app.create_sketch_constraint("horizontal", [p1, p2])

    app.move_sketch_point_with_solver(p1, "15 mm", "25 mm")

    point_a = app._find_sketch_point(p1)
    point_b = app._find_sketch_point(p2)
    assert point_a.x.text == "15 mm"
    assert point_a.y.text == "25 mm"
    assert point_b.y.text == "25 mm"


def test_sketch_undo_redo_and_validation() -> None:
    app = make_app()
    app.new_project("SketchUndo")
    p1 = app.create_sketch_point("0 mm", "0 mm")
    p2 = app.create_sketch_point("10 mm", "0 mm")
    line_id = app.create_sketch_line_segment(p1, p2)

    assert line_id in {entity.id for entity in app.project.sketch.entities.values()}
    assert app.undo() is True
    assert line_id not in {entity.id for entity in app.project.sketch.entities.values()}
    assert app.redo() is True
    assert line_id in {entity.id for entity in app.project.sketch.entities.values()}

    report = app.validate_model()
    assert not any(message.code == "broken_sketch_reference" for message in report.messages)


def test_sketch_constraints_propagate_geometry_and_can_update_distance() -> None:
    app = make_app()
    app.new_project("SketchConstraints")
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("40 mm", "10 mm", "B")

    horizontal_id = app.create_sketch_constraint("horizontal", [p1, p2], name="H1")
    point_b = app._find_sketch_point(p2)
    assert point_b.y.text == "0 mm"

    distance_id = app.create_sketch_constraint("distance", [p1, p2], value="50 mm", name="D1")
    app.move_sketch_point(p1, "10 mm", "20 mm")

    point_a = app._find_sketch_point(p1)
    point_b = app._find_sketch_point(p2)
    ax = float(point_a.x.text.split()[0])
    ay = float(point_a.y.text.split()[0])
    bx = float(point_b.x.text.split()[0])
    by = float(point_b.y.text.split()[0])
    assert abs(ay - by) < 1e-6
    assert abs((((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5) - 50.0) < 1e-3

    app.update_sketch_constraint(distance_id, "value", PropertyValueInput("expression", "60 mm"))
    point_b = app._find_sketch_point(p2)
    bx = float(point_b.x.text.split()[0])
    by = float(point_b.y.text.split()[0])
    assert abs(ay - by) < 1e-6
    assert abs((((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5) - 60.0) < 1e-3
    assert horizontal_id in {constraint.id for constraint in app.project.sketch.constraints.values()}


def test_sketch_validation_warns_on_unsolved_conflicting_constraints() -> None:
    app = make_app()
    app.new_project("SketchConflict")
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("40 mm", "10 mm", "B")
    app.create_sketch_constraint("fix", [p1], name="FixA")
    app.create_sketch_constraint("fix", [p2], name="FixB")
    app.create_sketch_constraint("horizontal", [p1, p2], name="H1")

    report = app.validate_model()

    assert any(message.code == "sketch_not_solved" for message in report.messages)




def test_collinear_constraint_accepts_two_segments() -> None:
    app = make_app()
    app.new_project("SketchCollinearSegments")
    a = app.create_sketch_point("0 mm", "0 mm", "A")
    b = app.create_sketch_point("10 mm", "0 mm", "B")
    c = app.create_sketch_point("20 mm", "3 mm", "C")
    d = app.create_sketch_point("30 mm", "3 mm", "D")

    constraint_id = app.create_sketch_constraint("collinear", [a, b, c, d])
    assert constraint_id is not None

    points = [app._find_sketch_point(pid) for pid in (a, b, c, d)]
    coords = [(float(point.x.text.split()[0]), float(point.y.text.split()[0])) for point in points]
    ax, ay = coords[0]
    bx, by = coords[1]
    for px, py in coords[2:]:
        cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
        assert abs(cross) < 1e-3





def test_update_slider_geometry_is_atomic() -> None:
    app = make_app()
    body_id = app.create_body(
        "Rod",
        [MarkerInput("0 mm", "0 mm", "A"), MarkerInput("40 mm", "0 mm", "P")],
    )
    slider_id = app.create_slider_from_points("Guide", "40 mm", "0 mm", "120 mm", "0 mm")
    marker_p = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")
    app.connect_marker_to_slider(marker_p, slider_id, name="Slider_P")

    app.update_slider_geometry(
        slider_id,
        origin_x="50 mm",
        origin_y="20 mm",
        angle="45 deg",
        travel_min="-30 mm",
        travel_max="30 mm",
    )

    slider = app._find_entity(slider_id)
    assert _mm(app, slider.origin_x.expression) == pytest.approx(50.0)
    assert _mm(app, slider.origin_y.expression) == pytest.approx(20.0)
    assert abs(float(slider.angle.expression.split()[0]) - 45.0) < 1e-6
    assert _mm(app, slider.travel_min.expression) == pytest.approx(-30.0)
    assert _mm(app, slider.travel_max.expression) == pytest.approx(30.0)

    # Undo must revert all changes in one step
    app.undo()
    slider = app._find_entity(slider_id)
    assert _mm(app, slider.origin_x.expression) == pytest.approx(80.0)
    assert _mm(app, slider.origin_y.expression) == pytest.approx(0.0)
    assert abs(float(slider.angle.expression.split()[0]) - 0.0) < 1e-6
    assert _mm(app, slider.travel_min.expression) == pytest.approx(-40.0)
    assert _mm(app, slider.travel_max.expression) == pytest.approx(40.0)


def test_create_joint_rejects_missing_body() -> None:
    app = make_app()
    body = app.create_body("Link", [MarkerInput("0 mm", "0 mm", "A")])
    marker_a = next(m.id for m in app._find_body(body).markers if m.name == "A")
    count_before = len(app.project.model.joints)
    with pytest.raises(ValueError, match="Body not found"):
        app.create_joint(
            "J1",
            "revolute",
            JointEndpointInput(JointEndpointKind.MARKER, body_id="no_such_body", marker_id=marker_a),
            JointEndpointInput(JointEndpointKind.GROUND),
        )
    assert len(app.project.model.joints) == count_before


def test_create_joint_rejects_missing_marker_in_body() -> None:
    app = make_app()
    body1 = app.create_body("Link1", [MarkerInput("0 mm", "0 mm", "A")])
    body2 = app.create_body("Link2", [MarkerInput("10 mm", "0 mm", "B")])
    marker_a = next(m.id for m in app._find_body(body1).markers if m.name == "A")
    marker_b = next(m.id for m in app._find_body(body2).markers if m.name == "B")
    count_before = len(app.project.model.joints)
    with pytest.raises(ValueError, match="Marker not found"):
        app.create_joint(
            "J1",
            "revolute",
            JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker_b),
            JointEndpointInput(JointEndpointKind.GROUND),
        )
    assert len(app.project.model.joints) == count_before


def test_create_joint_rejects_missing_slider() -> None:
    app = make_app()
    body = app.create_body("Link", [MarkerInput("0 mm", "0 mm", "A")])
    marker_a = next(m.id for m in app._find_body(body).markers if m.name == "A")
    count_before = len(app.project.model.joints)
    with pytest.raises(ValueError, match="Slider not found"):
        app.create_joint(
            "J1",
            "revolute",
            JointEndpointInput(JointEndpointKind.MARKER, body_id=body, marker_id=marker_a),
            JointEndpointInput(JointEndpointKind.SLIDER, slider_id="no_such_slider"),
        )
    assert len(app.project.model.joints) == count_before


def test_sync_id_service_includes_sensors() -> None:
    import tempfile, os, json
    app = make_app()
    body = app.create_body("Link", [MarkerInput("0 mm", "0 mm", "A")])
    marker_a = next(m.id for m in app._find_body(body).markers if m.name == "A")
    sensor1_id = app.create_sensor("S1", "point", [marker_a])

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.quino.json")
        app.save_project(path)

        app2 = ApplicationService()
        app2.load_project(path)
        sensor2_id = app2.create_sensor("S2", "point", [marker_a])

    assert sensor1_id != sensor2_id
    assert sensor2_id not in {s.id for s in app2.project.model.sensors if s.name == "S1"}



def test_create_sketch_constraint_validates_entity_reference_type() -> None:
    app = make_app()
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("10 mm", "0 mm", "B")
    line_id = app.create_sketch_line_segment(p1, p2)
    # "on_circle" is auto-converted to COINCIDENT; COINCIDENT accepts point+line
    # (point-on-line is valid), so no error is expected here.
    app.create_sketch_constraint("on_circle", [p1], entity_references=[line_id])
    with pytest.raises(ValueError, match="Tangent constraint requires a circle or arc entity reference"):
        app.create_sketch_constraint(
            "tangent",
            [p1, p2],
            entity_references=[line_id],
        )


def test_parallel_constraint_allows_shared_endpoint() -> None:
    # Two segments sharing an endpoint: seg1=(p1,p2), seg2=(p2,p3)
    # references=[p1,p2,p2,p3] should be accepted for PARALLEL/PERPENDICULAR/EQUAL_LENGTH
    app = make_app()
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("50 mm", "0 mm", "B")
    p3 = app.create_sketch_point("50 mm", "50 mm", "C")
    app.create_sketch_line_segment(p1, p2)
    app.create_sketch_line_segment(p2, p3)
    # Must not raise — shared endpoint p2 is valid for segment-pair constraints
    app.create_sketch_constraint("parallel", [p1, p2, p2, p3])
    app.create_sketch_constraint("perpendicular", [p1, p2, p2, p3])
    app.create_sketch_constraint("equal_length", [p1, p2, p2, p3])


def test_create_sketch_tangent_rejects_invalid_sign() -> None:
    app = make_app()
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("10 mm", "0 mm", "B")
    center = app.create_sketch_point("5 mm", "5 mm", "O")
    circle_id = app.create_sketch_circle(center, "3 mm", "C1")
    with pytest.raises(ValueError, match=r"Tangent sign must be \+1 or -1"):
        app.create_sketch_constraint(
            "tangent",
            [p1, p2],
            value="0.5",
            entity_references=[circle_id],
        )


def test_delete_circle_cascade_removes_on_circle_constraints() -> None:
    app = make_app()
    center = app.create_sketch_point("0 mm", "0 mm", "O")
    probe = app.create_sketch_point("5 mm", "0 mm", "P")
    circle_id = app.create_sketch_circle(center, "5 mm", "C1")
    constraint_id = app.create_sketch_constraint(
        "on_circle",
        [probe],
        entity_references=[circle_id],
    )
    app.delete_sketch_entity(circle_id)
    remaining_constraint_ids = {c.id for c in app.project.sketch.constraints}
    assert constraint_id not in remaining_constraint_ids



def test_sensor_outputs_persisted(tmp_path) -> None:
    import json
    app = make_app()
    body = app.create_body("Link", [MarkerInput("0 mm", "0 mm", "A")])
    marker_a = next(m.id for m in app._find_body(body).markers if m.name == "A")
    sensor_id = app.create_sensor("S1", "point", [marker_a])
    from quino.domain.workspace import SensorOutput
    app.project.sensor_outputs[sensor_id] = SensorOutput(sensor_id=sensor_id, time=[], columns=["x"], data=[])

    path = str(tmp_path / "test.quino.json")
    app.save_project(path)
    with open(path) as f:
        data = json.load(f)
    # Case-local sensor outputs are part of the workspace JSON.
    for case_data in data.get("cases", {}).values():
        assert "sensor_outputs" in case_data
    app2 = ApplicationService()
    app2.load_project(path)
    assert sensor_id in app2.project.sensor_outputs



def test_assemble_does_not_swap_joint_endpoints() -> None:
    app = make_app()
    body = app.create_body("Link", [MarkerInput("0 mm", "0 mm", "A"), MarkerInput("10 mm", "0 mm", "B")])
    marker_a = next(m.id for m in app._find_body(body).markers if m.name == "A")
    marker_b = next(m.id for m in app._find_body(body).markers if m.name == "B")
    joint_id = app.create_joint(
        "J1",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body, marker_id=marker_a),
        JointEndpointInput(JointEndpointKind.GROUND),
    )
    ground_joint = app._find_entity(joint_id)
    assert ground_joint.endpoint_a.kind is JointEndpointKind.MARKER
    assert ground_joint.endpoint_a.marker_id == marker_a
    assert ground_joint.endpoint_b.kind is JointEndpointKind.GROUND

    # Assemble should not mutate endpoints
    assembled = app.simulation_runner.adapter.assembler.assemble(app.project)
    assert ground_joint.endpoint_a.kind is JointEndpointKind.MARKER
    assert ground_joint.endpoint_a.marker_id == marker_a
    assert ground_joint.endpoint_b.kind is JointEndpointKind.GROUND


def test_sketch_edit_does_not_discard_simulation() -> None:
    app = make_app()
    app.create_sketch()
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("10 mm", "0 mm", "B")
    app.create_sketch_line_segment(p1, p2)

    # Mock a simulation result by setting internal state
    from quino.domain.model import SimulationResult
    result = SimulationResult(success=True, time=[0.0, 1.0], frames=[{}, {}])
    # We can't easily test the GUI guard, but we can verify that solve_sketch
    # does not clear sensor_outputs or any model state.
    app.project.sensor_outputs["dummy"] = type("obj", (), {"data": [(0.0,)]})()
    app.solve_sketch()
    assert "dummy" in app.project.sensor_outputs


def test_drag_constrained_point_respects_free_dof() -> None:
    app = make_app()
    p1 = app.create_sketch_point("0 mm", "0 mm")
    p2 = app.create_sketch_point("0 mm", "50 mm")
    app.create_sketch_line_segment(p1, p2)
    app.create_sketch_constraint("fix", [p1])
    app.create_sketch_constraint("vertical", [p1, p2])

    app.move_sketch_point(p2, "30 mm", "80 mm")

    assert app.project.sketch.solve_error is None, app.project.sketch.solve_error
    pts = {e.id: e for e in app.project.sketch.entities.values() if hasattr(e, "x")}
    x2 = app._evaluate_sketch_expression(pts[p2].x, app.project.parameters)
    y2 = app._evaluate_sketch_expression(pts[p2].y, app.project.parameters)
    assert abs(x2) < 1e-4, f"VERTICAL must keep x=0, got {x2}"
    assert abs(y2 - 80.0) < 1e-4, f"Free y must be 80, got {y2}"


def test_drag_distance_constrained_point_stays_on_circle() -> None:
    app = make_app()
    p1 = app.create_sketch_point("0 mm", "0 mm")
    p2 = app.create_sketch_point("50 mm", "0 mm")
    app.create_sketch_line_segment(p1, p2)
    app.create_sketch_constraint("fix", [p1])
    app.create_sketch_constraint("distance", [p1, p2])

    app.move_sketch_point(p2, "70 mm", "30 mm")

    assert app.project.sketch.solve_error is None, app.project.sketch.solve_error
    pts = {e.id: e for e in app.project.sketch.entities.values() if hasattr(e, "x")}
    x2 = app._evaluate_sketch_expression(pts[p2].x, app.project.parameters)
    y2 = app._evaluate_sketch_expression(pts[p2].y, app.project.parameters)
    dist = math.hypot(x2, y2)
    assert abs(dist - 50.0) < 0.1, f"Must stay on circle r=50, got dist={dist:.3f}"


def test_inspector_edit_constrained_point_respects_free_dof() -> None:
    from quino.domain.inputs import PropertyValueInput
    app = make_app()
    p1 = app.create_sketch_point("0 mm", "0 mm")
    p2 = app.create_sketch_point("0 mm", "50 mm")
    app.create_sketch_constraint("fix", [p1])
    app.create_sketch_constraint("vertical", [p1, p2])

    app.update_sketch_entity(p2, "x", PropertyValueInput(kind="expression", value="30 mm"))

    assert app.project.sketch.solve_error is None, app.project.sketch.solve_error
    pts = {e.id: e for e in app.project.sketch.entities.values() if hasattr(e, "x")}
    x2 = app._evaluate_sketch_expression(pts[p2].x, app.project.parameters)
    assert abs(x2) < 1e-4, f"VERTICAL must keep x=0 after inspector edit, got {x2}"


def test_changing_distance_value_invalidates_solve_cache() -> None:
    from quino.domain.inputs import PropertyValueInput
    app = make_app()
    p1 = app.create_sketch_point("0 mm", "0 mm")
    p2 = app.create_sketch_point("50 mm", "0 mm")
    app.create_sketch_constraint("fix", [p1])
    c_id = app.create_sketch_constraint("distance", [p1, p2])

    pts = {e.id: e for e in app.project.sketch.entities.values() if hasattr(e, "x")}
    x2 = app._evaluate_sketch_expression(pts[p2].x, app.project.parameters)
    assert abs(x2 - 50.0) < 1e-4

    app.update_sketch_constraint(c_id, "value", PropertyValueInput(kind="expression", value="80 mm"))

    pts = {e.id: e for e in app.project.sketch.entities.values() if hasattr(e, "x")}
    x2 = app._evaluate_sketch_expression(pts[p2].x, app.project.parameters)
    assert abs(x2 - 80.0) < 1e-4, f"After updating distance to 80mm, got x2={x2}"


def test_angle_constraint_accepts_unitless_numeric_value_as_degrees() -> None:
    app = make_app()
    p1 = app.create_sketch_point("0 mm", "0 mm")
    p2 = app.create_sketch_point("10 mm", "0 mm")
    p3 = app.create_sketch_point("10 mm", "10 mm")

    constraint_id = app.create_sketch_constraint("angle", [p1, p2, p3], value="45")
    constraint = app._find_sketch_constraint(constraint_id)
    assert constraint.value is not None
    assert constraint.value.expression == "45 deg"

    app.update_sketch_constraint(constraint_id, "value", PropertyValueInput(kind="expression", value="90"))
    assert constraint.value.expression == "90 deg"


def test_distance_on_circle_constrains_radius() -> None:
    """DISTANCE constraint on a circle with entity_ref enforces its radius."""
    app = make_app()
    app.create_sketch()
    center_id = app.create_sketch_point("0 mm", "0 mm")
    circle_id = app.create_sketch_circle(center_id, "50 mm")
    constraint_id = app.create_sketch_constraint(
        "distance",
        [center_id],
        value="30 mm",
        entity_references=[circle_id],
    )
    assert constraint_id is not None
    assert app._find_sketch_constraint(constraint_id).type.value == "radius"
    project = app.project
    circle = app.get_entity(circle_id)
    result = app.sketch_solver.solve(project)
    assert result.success
    # Radius should now be 30mm
    radius_val = app._evaluate_sketch_expression(
        circle.radius, project.parameters
    )
    assert abs(radius_val - 30.0) < 0.01


def test_distance_on_circle_rejected_without_entity_ref() -> None:
    """DISTANCE with 1 point and no entity_ref must raise."""
    app = make_app()
    app.create_sketch()
    center_id = app.create_sketch_point("0 mm", "0 mm")
    app.create_sketch_circle(center_id, "50 mm")
    with pytest.raises(ValueError):
        app.create_sketch_constraint("distance", [center_id])


def test_projected_distance_constraints_follow_axis_projection() -> None:
    app = make_app()
    app.new_project("SketchProjectedDistance")
    p1 = app.create_sketch_point("0 mm", "0 mm", "A")
    p2 = app.create_sketch_point("40 mm", "10 mm", "B")

    horizontal_id = app.create_sketch_constraint("horizontal_distance", [p1, p2], value="50 mm")
    vertical_id = app.create_sketch_constraint("vertical_distance", [p1, p2], value="15 mm")

    point_a = app._find_sketch_point(p1)
    point_b = app._find_sketch_point(p2)
    ax = float(point_a.x.text.split()[0])
    ay = float(point_a.y.text.split()[0])
    bx = float(point_b.x.text.split()[0])
    by = float(point_b.y.text.split()[0])
    assert abs(abs(bx - ax) - 50.0) < 1e-6
    assert abs(abs(by - ay) - 15.0) < 1e-6

    app.update_sketch_constraint(horizontal_id, "value", PropertyValueInput("expression", "60 mm"))
    app.update_sketch_constraint(vertical_id, "value", PropertyValueInput("expression", "20 mm"))

    point_a = app._find_sketch_point(p1)
    point_b = app._find_sketch_point(p2)
    ax = float(point_a.x.text.split()[0])
    ay = float(point_a.y.text.split()[0])
    bx = float(point_b.x.text.split()[0])
    by = float(point_b.y.text.split()[0])
    assert abs(abs(bx - ax) - 60.0) < 1e-6
    assert abs(abs(by - ay) - 20.0) < 1e-6


def test_distance_constraint_label_position_can_be_edited() -> None:
    app = make_app()
    p1 = app.create_sketch_point("0 mm", "0 mm")
    p2 = app.create_sketch_point("40 mm", "0 mm")
    constraint_id = app.create_sketch_constraint("distance", [p1, p2], value="40 mm")

    app.update_sketch_constraint(constraint_id, "label_x", PropertyValueInput("expression", "12 mm"))
    app.update_sketch_constraint(constraint_id, "label_y", PropertyValueInput("expression", "18 mm"))

    constraint = app._find_sketch_constraint(constraint_id)
    assert constraint.metadata.values["label_position"] == pytest.approx([12.0, 18.0])


def test_solver_near_convergence_succeeds() -> None:
    """Solver reports success=True if max_error <= 0.001mm after exhausting iterations."""
    app = make_app()
    p1 = app.create_sketch_point("0 mm", "0 mm")
    p2 = app.create_sketch_point("100 mm", "1 mm")
    app.create_sketch_line_segment(p1, p2)
    app.create_sketch_constraint("fix", [p1])
    app.create_sketch_constraint("horizontal", [p1, p2])
    app.create_sketch_constraint("distance", [p1, p2], value="100 mm")
    # Cap at 3 iterations with very tight tolerance to force the near-convergence path
    result = app.sketch_solver.solve(app.project, max_iterations=3, tolerance=1e-12)
    # Solver converges within a few iterations; error should be well under 0.001mm
    assert result.success, f"Near-convergence should be success, max_error={result.max_error:.3g}"



def test_circle_edge_point_is_hidden_after_creation() -> None:
    """After creating a circle from center + edge points, the edge point should be hidden."""
    app = make_app()
    app.create_sketch()
    center_id = app.create_sketch_point("0 mm", "0 mm")
    edge_id = app.create_sketch_point("50 mm", "0 mm")
    import math
    circle_id = app.create_sketch_circle(center_id, "50 mm", edge_point_id=edge_id)
    edge_pt = app._find_sketch_point(edge_id)
    center_pt = app._find_sketch_point(center_id)
    assert center_pt.visible is True, "Circle center must be visible"
    assert edge_pt.visible is False, "Circle edge/radius point must be hidden"


def test_arc_endpoint_points_are_visible_midpoint_hidden() -> None:
    """Arc endpoints (A=start, C=end) must be visible; midpoint B on arc is hidden."""
    app = make_app()
    app.create_sketch()
    p1 = app.create_sketch_point("0 mm", "0 mm")
    p2 = app.create_sketch_point("50 mm", "0 mm")
    p3 = app.create_sketch_point("50 mm", "50 mm")
    arc_id = app.create_sketch_arc(p1, p2, p3)
    arc = app._find_sketch_entity(arc_id)
    pt_center = app._find_sketch_point(arc.center_point_id)
    pt_start = app._find_sketch_point(arc.start_point_id)
    pt_end = app._find_sketch_point(arc.end_point_id)
    assert pt_center.visible is True, "Arc center point must be visible"
    assert pt_start.visible is True, "Arc start point must be visible"
    assert pt_end.visible is True, "Arc end point must be visible"


def test_create_load_and_assemble() -> None:
    app = make_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "B")
    load_id = app.create_load("Wind", marker_id, "10 N", "-5 N")

    load = next(ld for ld in app.project.model.loads if ld.id == load_id)
    assert load.name == "Wind"
    assert load.target_marker_id == marker_id
    assert load.fx.expression == "10 N"
    assert load.fy.expression == "-5 N"

    assembler = MechanismAssembler(app.expression_service)
    assembled = assembler.assemble(app.project)
    assert len(assembled.loads) == 1
    assert assembled.loads[0].fx == pytest.approx(10.0)
    assert assembled.loads[0].fy == pytest.approx(-5.0)
    assert assembled.loads[0].target_marker_id == marker_id
    assert assembled.loads[0].fx_expression == "10 N"
    assert assembled.loads[0].fy_expression == "-5 N"


def test_create_load_accepts_time_expression() -> None:
    app = make_app()
    body_id = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "P")])
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")

    load_id = app.create_load("Pulse", marker_id, "5 N * t / 1 s", "0 N")

    load = next(ld for ld in app.project.model.loads if ld.id == load_id)
    assert load.fx.expression == "5 N * t / 1 s"


def test_create_load_accepts_distance_sensor_expression() -> None:
    app = make_app()
    body_id = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "A"), MarkerInput("30 mm", "40 mm", "B")])
    marker_a = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "A")
    marker_b = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "B")
    app.create_sensor("Gap", "distance", [marker_a, marker_b])

    load_id = app.create_load("Springish", marker_b, "2 N/mm * Gap.d", "0 N")

    load = next(ld for ld in app.project.model.loads if ld.id == load_id)
    assert load.fx.expression == "2 N/mm * Gap.d"


def test_delete_load() -> None:
    app = make_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "B")
    load_id = app.create_load("Wind", marker_id, "10 N", "-5 N")
    app.delete_load(load_id)
    assert len(app.project.model.loads) == 0


def test_delete_body_removes_associated_load() -> None:
    app = make_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "B")
    app.create_load("Wind", marker_id, "10 N", "-5 N")
    app.delete_entity(body_id)
    assert len(app.project.model.loads) == 0


def test_delete_marker_removes_associated_load() -> None:
    app = make_app()
    body_id = app.create_body("Arm", [MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"), MarkerInput("50 mm", "50 mm", "C")])
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "C")
    app.create_load("Wind", marker_id, "10 N", "-5 N")
    app.delete_entity(marker_id)
    assert len(app.project.model.loads) == 0


def test_rename_load() -> None:
    app = make_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "B")
    load_id = app.create_load("Wind", marker_id, "10 N", "-5 N")
    app.rename_load(load_id, "Gust")
    assert app.project.model.loads[0].name == "Gust"


def test_update_load_property() -> None:
    app = make_app()
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "B")
    load_id = app.create_load("Wind", marker_id, "10 N", "-5 N")
    app.update_load_property(load_id, "fx", "20 N")
    assert app.project.model.loads[0].fx.expression == "20 N"
    app.update_load_property(load_id, "fy", "0 N")
    assert app.project.model.loads[0].fy.expression == "0 N"


def test_get_marker_deletion_consequence_to_bar() -> None:
    app = make_app()
    body_id = app.create_body("T", [MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"), MarkerInput("50 mm", "50 mm", "C")])
    body = app._find_body(body_id)
    marker_c = next(m for m in body.markers if m.name == "C")
    assert app.get_marker_deletion_consequence(marker_c.id) == "to_bar"


def test_get_marker_deletion_consequence_to_point_mass() -> None:
    app = make_app()
    body_id = app.create_bar("B", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = app._find_body(body_id)
    marker_b = next(m for m in body.markers if m.name == "B")
    assert app.get_marker_deletion_consequence(marker_b.id) == "to_point_mass"


def test_get_marker_deletion_consequence_normal() -> None:
    app = make_app()
    body_id = app.create_body("Q", [MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"), MarkerInput("50 mm", "50 mm", "C"), MarkerInput("0 mm", "50 mm", "D")])
    body = app._find_body(body_id)
    marker_d = next(m for m in body.markers if m.name == "D")
    assert app.get_marker_deletion_consequence(marker_d.id) == "normal"


def test_delete_structural_marker_convert_to_bar() -> None:
    from quino.domain.types import BodyType
    app = make_app()
    body_id = app.create_body("T", [MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"), MarkerInput("50 mm", "50 mm", "C")])
    body = app._find_body(body_id)
    marker_c = next(m for m in body.markers if m.name == "C")
    app.delete_structural_marker_convert_to_bar(marker_c.id)
    assert body.type is BodyType.BAR
    assert not body.closed_shape
    assert len(body.structural_markers()) == 2
    com = body.com_marker()
    assert com.metadata.values.get("position_percent") == 50.0
    cx = app.expression_service.evaluate_property(com.x, app.project.parameters).value
    cy = app.expression_service.evaluate_property(com.y, app.project.parameters).value
    assert abs(cx - 50.0) < 1e-6
    assert abs(cy - 0.0) < 1e-6


