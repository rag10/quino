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
from quino.domain.model import SimulationResult


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
    assert _mm(app, slider.origin_x.expression) == pytest.approx(90.0)
    assert _mm(app, slider.origin_y.expression) == pytest.approx(20.0)


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
    assert _mm(app, marker.x.expression) == pytest.approx(50.0)
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
    assert _mm(app, marker.y.expression) == pytest.approx(10.0)
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
    app.connect_marker_to_slider(marker_id, slider_id, name="BrokenSliderJoint")

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
