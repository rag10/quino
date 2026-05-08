from __future__ import annotations

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


def make_app() -> ApplicationService:
    app = ApplicationService()
    app.new_project("Demo")
    app.create_parameter("L1", "120 mm", "mm")
    return app


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


def test_joint_duplicates_are_rejected() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "A")
    app.connect_marker_to_ground(marker_id, name="Ground_A")
    with pytest.raises(ValueError):
        app.connect_marker_to_ground(marker_id, name="Ground_A2")


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
