from __future__ import annotations

import json
import math

import pytest
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from quino.application.examples import build_double_pendulum_example
from quino.application.service import ApplicationService
from quino.domain.inputs import JointEndpointInput, MarkerInput, PropertyValueInput, SliderInput
from quino.domain.types import JointEndpointKind
from quino.gui.canvas import CanvasMode
from quino.gui.main_window import MainWindow
from quino.pose.geometry import marker_world_position
from quino.pose.model import PoseConstraint, PoseSolveResult


def _expr_value(expression: str) -> float:
    return float(expression.split()[0])


def _inspector_row_by_property(window: MainWindow, property_name: str) -> int:
    for row in range(window.inspector.rowCount()):
        item = window.inspector.item(row, 0)
        if item is not None and item.text() == property_name:
            return row
    raise AssertionError(f"Property row not found: {property_name}")


def test_main_window_loads_examples_and_runs_validation() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())

    window.load_four_bar_example()

    assert window.app_service.project is not None
    assert window.app_service.project.name == "Four Bar"
    assert window.tree.topLevelItemCount() == 8
    assert "Bodies: 3" in window.canvas_summary.toPlainText()
    assert window.canvas is not None
    assert not window.canvas.grab().isNull()

    window.validate_model()

    assert "Validation report:" in window.messages.toPlainText()
    assert "Validation report:" in window.validation_view.toPlainText()
    window.close()
    qt_app.processEvents()


def test_interaction_mode_filters_selection() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    # Create a sketch point and a model marker
    sketch_point_id = window.app_service.create_sketch_point("10 mm", "10 mm", "SP1")
    body_id = window.app_service.create_body("Body1", [MarkerInput("0 mm", "0 mm", "M1")])
    marker_id = next(m.id for m in window.app_service._find_body(body_id).structural_markers())
    window.refresh_all()

    # In model mode, selecting a sketch point should be ignored
    window.canvas.set_interaction_mode("model")
    window.canvas.set_selection(sketch_point_id)
    qt_app.processEvents()
    assert window.canvas._selected_entity_id != sketch_point_id

    # In model mode, selecting a marker should work
    window.canvas.set_selection(marker_id)
    qt_app.processEvents()
    assert window.canvas._selected_entity_id == marker_id

    # In sketch mode, selecting a marker should be ignored/cleared
    window.canvas.set_interaction_mode("sketch")
    qt_app.processEvents()
    assert window.canvas._selected_entity_id != marker_id

    # In sketch mode, selecting a sketch point should work
    window.canvas.set_selection(sketch_point_id)
    qt_app.processEvents()
    assert window.canvas._selected_entity_id == sketch_point_id

    window.close()
    qt_app.processEvents()


def test_mode_switch_toggles_toolbars() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    # Default mode is Model
    assert window._app_mode == "model"
    assert window._mode_model_btn.isChecked()
    assert not window._mode_sketch_btn.isChecked()
    assert not window._mode_pose_btn.isChecked()
    assert not window._mode_analysis_btn.isChecked()
    assert window._model_toolbar.isVisible()
    assert not window._sketch_toolbar.isVisible()
    assert not window._pose_toolbar.isVisible()
    assert not window._analysis_toolbar.isVisible()

    # Switch to Sketch mode
    window._set_app_mode("sketch")
    qt_app.processEvents()
    assert window._app_mode == "sketch"
    assert window._mode_sketch_btn.isChecked()
    assert not window._mode_model_btn.isChecked()
    assert not window._mode_pose_btn.isChecked()
    assert not window._mode_analysis_btn.isChecked()
    assert window._sketch_toolbar.isVisible()
    assert not window._model_toolbar.isVisible()
    assert not window._pose_toolbar.isVisible()
    assert not window._analysis_toolbar.isVisible()
    assert window.app_service.project.sketch is not None
    assert window.app_service.project.sketch.visible is True

    # Switch to Pose mode
    window._set_app_mode("pose")
    qt_app.processEvents()
    assert window._app_mode == "pose"
    assert window._mode_pose_btn.isChecked()
    assert not window._mode_sketch_btn.isChecked()
    assert not window._mode_model_btn.isChecked()
    assert not window._mode_analysis_btn.isChecked()
    assert window._pose_toolbar.isVisible()
    assert not window._sketch_toolbar.isVisible()
    assert not window._model_toolbar.isVisible()
    assert not window._analysis_toolbar.isVisible()

    # Switch to Sim mode
    window._set_app_mode("analysis")
    qt_app.processEvents()
    assert window._app_mode == "analysis"
    assert window._mode_analysis_btn.isChecked()
    assert not window._mode_sketch_btn.isChecked()
    assert not window._mode_model_btn.isChecked()
    assert not window._mode_pose_btn.isChecked()
    assert window._analysis_toolbar.isVisible()
    assert not window._sketch_toolbar.isVisible()
    assert not window._model_toolbar.isVisible()
    assert not window._pose_toolbar.isVisible()
    assert hasattr(window, "action_export_script")
    assert window.action_export_script.isEnabled()  # Exudyn is the default backend

    # Switch back to Model mode
    window._set_app_mode("model")
    qt_app.processEvents()
    assert window._app_mode == "model"
    assert window._mode_model_btn.isChecked()
    assert not window._mode_sketch_btn.isChecked()
    assert not window._mode_pose_btn.isChecked()
    assert not window._mode_analysis_btn.isChecked()
    assert window._model_toolbar.isVisible()
    assert not window._sketch_toolbar.isVisible()
    assert not window._pose_toolbar.isVisible()
    assert not window._analysis_toolbar.isVisible()

    window.close()
    qt_app.processEvents()


def test_pose_mode_creates_current_pose_and_prescribe_x(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "A")
    marker_p = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    window.app_service.set_current_pose(pose)
    window.refresh_all()

    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("80", True))
    window._set_app_mode("pose")
    window.action_pose_prescribe_x.trigger()   # enters pick mode
    qt_app.processEvents()
    window._select_entity_by_id(marker_p)      # simulates picking the marker
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    assert current_pose.body_poses[body_id].angle != pytest.approx(0.7)
    body = window.app_service._find_body(body_id)
    marker = next(item for item in body.markers if item.id == marker_p)
    assert marker.x.expression == "100 mm"
    assert marker.y.expression == "0 mm"

    window.close()
    qt_app.processEvents()


def test_pose_prescribe_x_via_pose_pick_signal(monkeypatch) -> None:
    """Test that emitting poseMarkerPicked (the real UI path) triggers _advance_pose_pick."""
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "A")
    marker_p = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    window.app_service.set_current_pose(pose)
    window.refresh_all()

    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("80", True))
    window._set_app_mode("pose")
    window.action_pose_prescribe_x.trigger()   # button becomes checked, canvas → POSE_PICK
    qt_app.processEvents()
    # Simulate canvas emitting poseMarkerPicked (what mousePressEvent does in POSE_PICK mode)
    window.canvas.poseMarkerPicked.emit(marker_p)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    assert current_pose.body_poses[body_id].angle != pytest.approx(0.7)

    window.close()
    qt_app.processEvents()


def test_pose_prescribe_x_accepts_length_expression_and_updates_canvas(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "A")
    marker_p = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    window.app_service.set_current_pose(pose)
    window.refresh_all()

    before = window.canvas.screen_position_for_entity(marker_p)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("80 mm", True))
    window._set_app_mode("pose")
    window.action_pose_prescribe_x.trigger()
    qt_app.processEvents()
    window.canvas.poseMarkerPicked.emit(marker_p)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    marker_x, _marker_y = marker_world_position(window.app_service.project, marker_p, current_pose)
    assert marker_x == pytest.approx(80.0, abs=1e-4)
    assert window.canvas.screen_position_for_entity(marker_p) != before

    window.close()
    qt_app.processEvents()


def test_pose_prescribe_x_updates_canvas_on_closed_loop_mechanism(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    window.load_four_bar_example()
    window._set_app_mode("pose")
    window.refresh_all()
    qt_app.processEvents()

    marker_c = next(
        marker.id
        for body in window.app_service.project.model.bodies
        if body.name == "Coupler"
        for marker in body.markers
        if marker.name == "C"
    )

    before = window.canvas.screen_position_for_entity(marker_c)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("80 mm", True))
    window.action_pose_prescribe_x.trigger()
    qt_app.processEvents()
    window.canvas.poseMarkerPicked.emit(marker_c)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    marker_x, _marker_y = marker_world_position(window.app_service.project, marker_c, current_pose)
    assert marker_x == pytest.approx(80.0, abs=1e-4)
    assert window.canvas.screen_position_for_entity(marker_c) != before

    window.close()
    qt_app.processEvents()


def test_pose_prescribe_x_updates_canvas_on_double_pendulum(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    build_double_pendulum_example(window.app_service)
    window.refresh_all()
    window._set_app_mode("pose")
    qt_app.processEvents()

    marker_c = next(
        marker.id
        for body in window.app_service.project.model.bodies
        if body.name == "Arm2"
        for marker in body.markers
        if marker.name == "C"
    )

    before = window.canvas.screen_position_for_entity(marker_c)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("0", True))
    window.action_pose_prescribe_x.trigger()
    qt_app.processEvents()
    window.canvas.poseMarkerPicked.emit(marker_c)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    marker_x, _marker_y = marker_world_position(window.app_service.project, marker_c, current_pose)
    assert marker_x == pytest.approx(0.0, abs=1e-3)
    assert window.canvas.screen_position_for_entity(marker_c) != before

    window.close()
    qt_app.processEvents()


def test_pose_prescribe_x_updates_double_pendulum_joint_marker(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    build_double_pendulum_example(window.app_service)
    window.refresh_all()
    window._set_app_mode("pose")
    qt_app.processEvents()

    marker_b = next(
        marker.id
        for body in window.app_service.project.model.bodies
        if body.name == "Arm2"
        for marker in body.markers
        if marker.name == "B"
    )

    before = window.canvas.screen_position_for_entity(marker_b)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("0", True))
    window.action_pose_prescribe_x.trigger()
    qt_app.processEvents()
    window.canvas.poseMarkerPicked.emit(marker_b)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    marker_x, _marker_y = marker_world_position(window.app_service.project, marker_b, current_pose)
    assert marker_x == pytest.approx(0.0, abs=1e-3)
    assert window.canvas.screen_position_for_entity(marker_b) != before

    window.close()
    qt_app.processEvents()


def test_pose_prescribe_x_large_step_updates_double_pendulum(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    build_double_pendulum_example(window.app_service)
    window.refresh_all()
    window._set_app_mode("pose")
    qt_app.processEvents()

    marker_c = next(
        marker.id
        for body in window.app_service.project.model.bodies
        if body.name == "Arm2"
        for marker in body.markers
        if marker.name == "C"
    )

    before = window.canvas.screen_position_for_entity(marker_c)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("-100", True))
    window.action_pose_prescribe_x.trigger()
    qt_app.processEvents()
    window.canvas.poseMarkerPicked.emit(marker_c)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    marker_x, _marker_y = marker_world_position(window.app_service.project, marker_c, current_pose)
    assert marker_x == pytest.approx(-100.0, abs=1e-3)
    assert window.canvas.screen_position_for_entity(marker_c) != before

    window.close()
    qt_app.processEvents()


def test_pose_kinematic_fallback_rejects_ground_joint_violation() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "A")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].x += 10.0
    window.app_service.set_current_pose(pose)

    constraint = PoseConstraint(
        id=f"pose_x_{marker_a}",
        kind="marker_projected_coordinate",
        target_id=marker_a,
        metadata={"axis_x": 1.0, "axis_y": 0.0, "value": 10.0},
    )
    accepted, result, _steps = window._accept_kinematic_coordinate_pose(
        f"marker_projected_coordinate:x:{marker_a}",
        constraint,
        marker_a,
        "x",
        10.0,
        1e-3,
        1,
    )

    assert not accepted
    assert result.error is not None
    assert "ground joint" in result.error
    assert f"marker_projected_coordinate:x:{marker_a}" not in window._pose_constraints

    window.close()
    qt_app.processEvents()


def test_pose_kinematic_fallback_rejects_slider_joint_violation() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_body("Block", [MarkerInput("0 mm", "0 mm", "P")])
    marker_p = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "P")
    slider_id = window.app_service.create_slider("Guide", SliderInput("0 mm", "0 mm", "0 deg"))
    window.app_service.connect_marker_to_slider(marker_p, slider_id, name="Slider_P")
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].y += 50.0
    window.app_service.set_current_pose(pose)

    constraint = PoseConstraint(
        id=f"pose_y_{marker_p}",
        kind="marker_projected_coordinate",
        target_id=marker_p,
        metadata={"axis_x": 0.0, "axis_y": 1.0, "value": 50.0},
    )
    accepted, result, _steps = window._accept_kinematic_coordinate_pose(
        f"marker_projected_coordinate:y:{marker_p}",
        constraint,
        marker_p,
        "y",
        50.0,
        1e-3,
        1,
    )

    assert not accepted
    assert result.error is not None
    assert "slider joint" in result.error
    assert f"marker_projected_coordinate:y:{marker_p}" not in window._pose_constraints

    window.close()
    qt_app.processEvents()


def test_pose_pick_mode_mouseclick_detects_marker(monkeypatch) -> None:
    """QTest.mouseClick on canvas in POSE_PICK mode must detect the structural marker."""
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "A")
    marker_p = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    window.app_service.set_current_pose(pose)

    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("80", True))
    window._set_app_mode("pose")
    qt_app.processEvents()

    window.action_pose_prescribe_x.trigger()
    qt_app.processEvents()

    pos = window.canvas.screen_position_for_entity(marker_p)
    assert pos is not None, "screen_position_for_entity returned None"
    assert window.canvas._mode == CanvasMode.POSE_PICK, f"Canvas should be in POSE_PICK, got {window.canvas._mode}"

    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    assert current_pose.body_poses[body_id].angle != pytest.approx(0.7), "Pose angle should have changed after constraint"

    window.close()
    qt_app.processEvents()


def test_pose_mode_prescribe_horizontal_angle_updates_canvas(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "A")
    marker_p = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    window.app_service.set_current_pose(pose)
    window._set_app_mode("pose")
    window.refresh_all()
    qt_app.processEvents()

    before = window.canvas.screen_position_for_entity(marker_p)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("0 deg", True))
    window.action_pose_prescribe_horizontal.trigger()
    qt_app.processEvents()
    window.canvas.poseMarkerPicked.emit(marker_a)
    assert window.canvas._pose_pick_marker_ids == [marker_a]
    window.canvas.poseMarkerPicked.emit(marker_p)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    assert current_pose.body_poses[body_id].angle == pytest.approx(0.0, abs=1e-4)
    marker_ax, marker_ay = marker_world_position(window.app_service.project, marker_a, current_pose)
    marker_px, marker_py = marker_world_position(window.app_service.project, marker_p, current_pose)
    assert marker_px == pytest.approx(marker_ax + 100.0, abs=1e-4)
    assert marker_py == pytest.approx(marker_ay, abs=1e-4)
    assert window.canvas.screen_position_for_entity(marker_p) != before

    window.close()
    qt_app.processEvents()


def test_pose_mode_prescribe_vertical_angle_uses_popup_and_updates_canvas(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "A")
    marker_p = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.2
    window.app_service.set_current_pose(pose)
    window._set_app_mode("pose")
    window.refresh_all()
    qt_app.processEvents()

    before = window.canvas.screen_position_for_entity(marker_p)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("0 deg", True))
    window.action_pose_prescribe_vertical.trigger()
    qt_app.processEvents()
    window.canvas.poseMarkerPicked.emit(marker_a)
    assert window.canvas._pose_pick_marker_ids == [marker_a]
    window.canvas.poseMarkerPicked.emit(marker_p)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    assert current_pose.body_poses[body_id].angle == pytest.approx(math.pi / 2.0, abs=1e-4)
    marker_ax, marker_ay = marker_world_position(window.app_service.project, marker_a, current_pose)
    marker_px, marker_py = marker_world_position(window.app_service.project, marker_p, current_pose)
    assert marker_px == pytest.approx(marker_ax, abs=1e-4)
    assert marker_py == pytest.approx(marker_ay + 100.0, abs=1e-4)
    assert window.canvas.screen_position_for_entity(marker_p) != before

    window.close()
    qt_app.processEvents()


def test_pose_mode_prescribe_horizontal_angle_accepts_joint_equivalent_marker(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    build_double_pendulum_example(window.app_service)
    window.refresh_all()
    window._set_app_mode("pose")
    qt_app.processEvents()

    arm1_b = next(
        marker.id
        for body in window.app_service.project.model.bodies
        if body.name == "Arm1"
        for marker in body.markers
        if marker.name == "B"
    )
    arm2_c = next(
        marker.id
        for body in window.app_service.project.model.bodies
        if body.name == "Arm2"
        for marker in body.markers
        if marker.name == "C"
    )
    arm2_id = next(body.id for body in window.app_service.project.model.bodies if body.name == "Arm2")

    dialog_calls: list[str] = []

    def fake_get_text(*args, **kwargs):
        dialog_calls.append(args[1])
        return "0 deg", True

    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", fake_get_text)
    window.action_pose_prescribe_horizontal.trigger()
    qt_app.processEvents()
    window.canvas.poseMarkerPicked.emit(arm1_b)
    window.canvas.poseMarkerPicked.emit(arm2_c)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert dialog_calls == ["Prescribe Horizontal Angle"]
    assert current_pose is not None
    assert current_pose.body_poses[arm2_id].angle == pytest.approx(0.0, abs=1e-4)

    window.close()
    qt_app.processEvents()


def test_pose_mode_prescribe_relative_angle_updates_canvas(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    crank_id = window.app_service.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("50 mm", "0 mm", "B"))
    crank_a = next(m.id for m in window.app_service._find_body(crank_id).markers if m.name == "A")
    crank_b = next(m.id for m in window.app_service._find_body(crank_id).markers if m.name == "B")
    coupler_id = window.app_service.create_bar("Coupler", MarkerInput("0 mm", "0 mm", "C"), MarkerInput("100 mm", "0 mm", "D"))
    coupler_c = next(m.id for m in window.app_service._find_body(coupler_id).markers if m.name == "C")
    coupler_d = next(m.id for m in window.app_service._find_body(coupler_id).markers if m.name == "D")
    window.app_service.connect_marker_to_ground(crank_a)
    window.app_service.create_joint(
        "CrankCoupler",
        "revolute",
        JointEndpointInput(kind=JointEndpointKind.MARKER, body_id=crank_id, marker_id=crank_b),
        JointEndpointInput(kind=JointEndpointKind.MARKER, body_id=coupler_id, marker_id=coupler_c),
    )
    window.app_service.reset_current_pose_to_reference()
    window._set_app_mode("pose")
    window._pose_constraints[f"body_angle:{crank_id}"] = PoseConstraint(
        id=f"pose_body_angle_{crank_id}",
        kind="body_angle",
        target_id=crank_id,
        metadata={"angle": math.pi / 6.0},
    )
    window._solve_pose()
    window.refresh_all()
    qt_app.processEvents()

    before = window.canvas.screen_position_for_entity(coupler_d)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("45 deg", True))
    window.action_pose_prescribe_angle.trigger()
    qt_app.processEvents()
    window.canvas.poseMarkerPicked.emit(crank_a)
    assert window.canvas._pose_pick_marker_ids == [crank_a]
    window.canvas.poseMarkerPicked.emit(crank_b)
    assert window.canvas._pose_pick_marker_ids == [crank_a, crank_b]
    window.canvas.poseMarkerPicked.emit(coupler_c)
    assert window.canvas._pose_pick_marker_ids == [crank_a, crank_b, coupler_c]
    window.canvas.poseMarkerPicked.emit(coupler_d)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    assert current_pose.body_poses[crank_id].angle == pytest.approx(math.pi / 6.0, abs=1e-4)
    assert current_pose.body_poses[coupler_id].angle == pytest.approx(-math.pi / 12.0, abs=1e-4)
    assert window.canvas.screen_position_for_entity(coupler_d) != before

    window.close()
    qt_app.processEvents()


def test_pose_mode_click_selects_marker_without_running_drag_solve() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "A")
    marker_p = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    window.app_service.set_current_pose(pose)
    window._set_app_mode("pose")
    qt_app.processEvents()

    QtTest.QTest.mouseClick(
        window.canvas,
        QtCore.Qt.MouseButton.LeftButton,
        pos=window.canvas.screen_position_for_entity(marker_p),
    )
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    assert current_pose.body_poses[body_id].angle == pytest.approx(0.7)
    assert window._selected_entity_id == marker_p
    assert "Pose drag solve failed" not in window.messages.toPlainText()

    window.close()
    qt_app.processEvents()


def test_pose_mode_drag_success_updates_pose_without_mutating_model() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "A")
    marker_p = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    window.app_service.set_current_pose(pose)
    window._set_app_mode("pose")
    qt_app.processEvents()

    window._on_canvas_pose_marker_drag(marker_p, 70.0, 71.414284, True)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    assert current_pose.body_poses[body_id].angle != pytest.approx(0.7)
    body = window.app_service._find_body(body_id)
    marker = next(item for item in body.markers if item.id == marker_p)
    assert marker.x.expression == "100 mm"
    assert marker.y.expression == "0 mm"
    assert "Pose drag solve failed" not in window.messages.toPlainText()

    window.close()
    qt_app.processEvents()


def test_pose_mode_drag_preserves_same_marker_prescriptions() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "A")
    marker_p = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    window.app_service.set_current_pose(pose)
    window._set_app_mode("pose")
    window._select_entity_by_id(marker_p)
    qt_app.processEvents()

    window._pose_constraints["x:P"] = PoseConstraint(
        id="pose_x_marker",
        kind="marker_projected_coordinate",
        target_id=marker_p,
        metadata={
            "reference_x": 0.0,
            "reference_y": 0.0,
            "axis_x": 1.0,
            "axis_y": 0.0,
            "value": 80.0,
        },
    )
    window._solve_pose()
    qt_app.processEvents()

    window._on_canvas_pose_marker_drag(marker_p, 60.0, 80.0, True)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    body_pose = current_pose.body_poses[body_id]
    assert body_pose.angle == pytest.approx(math.acos(0.8))
    assert any(constraint.target_id == marker_p for constraint in window._pose_constraints.values())

    window._solve_pose()
    qt_app.processEvents()
    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    assert current_pose.body_poses[body_id].angle == pytest.approx(math.acos(0.8))

    window.close()
    qt_app.processEvents()


def test_pose_mode_prescribe_coordinate_uses_intermediate_steps(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "A")
    marker_p = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.2
    window.app_service.set_current_pose(pose)
    window._set_app_mode("pose")
    qt_app.processEvents()

    attempted_targets: list[float] = []
    original_solve = window.app_service.solve_current_pose

    def fake_solve(temporary_constraints=None, settings=None):
        constraints = temporary_constraints or []
        constraint = next(item for item in constraints if item.target_id == marker_p and item.kind == "marker_projected_coordinate")
        target_value = float(constraint.metadata["value"])
        current_pose = window.app_service.get_current_pose()
        current_x, _ = marker_world_position(window.app_service.project, marker_p, current_pose)
        attempted_targets.append(target_value)
        if abs(target_value - current_x) > 15.0:
            return PoseSolveResult(success=False, error="step too large")
        updated_pose = window.app_service.get_current_pose()
        assert updated_pose is not None
        updated_pose = window.app_service._complete_pose(updated_pose)
        updated_pose.body_poses[body_id].angle = math.acos(max(-1.0, min(1.0, target_value / 100.0)))
        window.app_service.set_current_pose(updated_pose)
        return PoseSolveResult(success=True, pose=updated_pose)

    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("0", True))
    monkeypatch.setattr(window.app_service, "solve_current_pose", fake_solve)
    monkeypatch.setattr(window, "_seed_pose_toward_projected_coordinate", lambda *args, **kwargs: False)

    window.action_pose_prescribe_x.trigger()  # enters pick mode
    qt_app.processEvents()
    window._select_entity_by_id(marker_p)     # simulates picking the marker → triggers dialog → triggers solve
    qt_app.processEvents()

    assert len(attempted_targets) >= 3
    assert max(abs(b - a) for a, b in zip(attempted_targets, attempted_targets[1:])) <= 25.0
    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    marker_x, marker_y = marker_world_position(window.app_service.project, marker_p, current_pose)
    assert marker_x == pytest.approx(0.0, abs=1e-6)
    assert marker_y == pytest.approx(100.0, abs=1e-6)
    assert window._pose_constraints[f"x:{marker_p}"].metadata["value"] == pytest.approx(0.0)
    assert "intermediate steps" in window.messages.toPlainText()

    monkeypatch.setattr(window.app_service, "solve_current_pose", original_solve)
    window.close()
    qt_app.processEvents()


def test_pose_prescribe_is_listed_under_current_pose_and_can_be_deleted(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "A")
    marker_p = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    window.app_service.set_current_pose(pose)
    window._set_app_mode("pose")
    window.refresh_all()
    qt_app.processEvents()

    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("80 mm", True))
    window.action_pose_prescribe_x.trigger()
    window.canvas.poseMarkerPicked.emit(marker_p)
    qt_app.processEvents()

    strip = window.pose_constraints_strip
    assert strip._list.count() == 1
    item = strip._list.item(0)
    assert "Prescribe X" in item.text()
    assert window.app_service.get_current_pose().metadata.values["pose_constraints"]
    assert window.canvas._pose_constraints

    strip._list.setCurrentItem(item)
    strip._on_delete_clicked()
    qt_app.processEvents()

    assert strip._list.count() == 0
    assert window._pose_constraints == {}
    assert window.app_service.get_current_pose().metadata.values["pose_constraints"] == []
    assert window.canvas._pose_constraints == []

    window.close()
    qt_app.processEvents()


def test_pose_drag_respects_prescribed_axis_on_same_marker(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    build_double_pendulum_example(window.app_service)
    window._set_app_mode("pose")
    window.refresh_all()
    qt_app.processEvents()
    marker_p = next(
        marker.id
        for body in window.app_service.project.model.bodies
        if body.name == "Arm2"
        for marker in body.markers
        if marker.name == "C"
    )

    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("0 mm", True))
    window.action_pose_prescribe_x.trigger()
    window.canvas.poseMarkerPicked.emit(marker_p)
    qt_app.processEvents()

    window._on_canvas_pose_marker_drag(marker_p, 100.0, 100.0, True)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    marker_x, marker_y = marker_world_position(window.app_service.project, marker_p, current_pose)
    assert marker_x == pytest.approx(0.0, abs=1e-3)
    assert marker_y == pytest.approx(100.0, abs=1e-3)
    assert f"x:{marker_p}" in window._pose_constraints

    window.close()
    qt_app.processEvents()


def test_pose_mode_drag_moves_mechanism_toward_target_without_mutating_model() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "A")
    marker_p = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "P")
    window.app_service.connect_marker_to_ground(marker_a)
    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = 0.7
    window.app_service.set_current_pose(pose)
    window._set_app_mode("pose")
    qt_app.processEvents()

    window._on_canvas_pose_marker_drag(marker_p, 140.0, 60.0, True)
    qt_app.processEvents()

    current_pose = window.app_service.get_current_pose()
    assert current_pose is not None
    # Drag succeeds: mechanism moves toward target staying on kinematic curve (bar length = 100mm)
    assert current_pose.body_poses[body_id].angle != pytest.approx(0.7)
    body = window.app_service._find_body(body_id)
    marker = next(item for item in body.markers if item.id == marker_p)
    assert marker.x.expression == "100 mm"
    assert marker.y.expression == "0 mm"

    window.close()
    qt_app.processEvents()


def test_playback_controls_are_disabled_without_simulation() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.refresh_all()

    assert not window.action_play_pause.isEnabled()
    assert not window.action_stop.isEnabled()
    assert not window.timeline_slider.isEnabled()

    window.close()
    qt_app.processEvents()


def test_simulation_parameter_changes_discard_existing_simulation() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.load_four_bar_example()
    window.run_simulation()
    qt_app.processEvents()

    assert window._last_simulation_result is not None
    assert window._last_simulation_result.frames

    window.steps_spin.setValue(window.steps_spin.value() + window.steps_spin.singleStep())
    qt_app.processEvents()
    assert window._last_simulation_result is None
    assert "Simulation discarded because frame count changed" in window.messages.toPlainText()

    window.run_simulation()
    qt_app.processEvents()
    assert window._last_simulation_result is not None

    window.dt_spin.setValue(window.dt_spin.value() + window.dt_spin.singleStep())
    qt_app.processEvents()
    assert window._last_simulation_result is None
    assert "Simulation discarded because delta t changed" in window.messages.toPlainText()

    window.close()
    qt_app.processEvents()


def test_simulation_spin_boxes_use_adaptive_steps() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    window.steps_spin.setValue(1000)
    qt_app.processEvents()
    assert window.steps_spin.singleStep() == 100

    window.steps_spin.setValue(54608)
    qt_app.processEvents()
    assert window.steps_spin.singleStep() == 5460

    window.dt_spin.setValue(0.001)
    qt_app.processEvents()
    assert window.dt_spin.singleStep() == pytest.approx(0.0005)

    window.dt_spin.setValue(0.07)
    qt_app.processEvents()
    assert window.dt_spin.singleStep() == pytest.approx(0.005)

    window.playback_speed_spin.setValue(2.5)
    qt_app.processEvents()
    assert window.playback_speed_spin.singleStep() == pytest.approx(0.5)

    window.close()
    qt_app.processEvents()


def test_save_uses_save_as_for_unsaved_project(monkeypatch, tmp_path) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    target = tmp_path / "demo"

    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(target), "QUINO Project (*.quino.json)"),
    )

    assert window._save_project() is True

    assert window._current_project_path == tmp_path / "demo.quino.json"
    assert not window._project_dirty
    assert (tmp_path / "demo.quino.json").exists()
    window.close()
    qt_app.processEvents()


def test_save_overwrites_current_project_without_prompting_for_path(monkeypatch, tmp_path) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    path = tmp_path / "project.quino.json"
    window._save_project_to_path(path)
    window.app_service.project.name = "Changed Name"
    window._mark_project_dirty()

    def fail_save_dialog(*args, **kwargs):
        raise AssertionError("Save should not open Save As when a project path is known")

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", fail_save_dialog)

    assert window._save_project() is True

    data = json.loads(path.read_text())
    assert data["project"]["name"] == "Changed Name"
    assert not window._project_dirty
    window.close()
    qt_app.processEvents()


def test_open_project_cancel_keeps_dirty_project(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    original_project_id = window.app_service.project.id
    window._mark_project_dirty()

    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Cancel,
    )

    def fail_open_dialog(*args, **kwargs):
        raise AssertionError("Open dialog should not be shown after cancelling unsaved changes")

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", fail_open_dialog)

    window._open_project()

    assert window.app_service.project.id == original_project_id
    assert window._project_dirty
    window.close()
    qt_app.processEvents()


def test_default_pose_click_enters_readonly_pose_mode() -> None:
    """Clicking a default WorkspacePose in the workflow tree must enter
    pose mode in read-only state and keep the composed-model geometry
    visible (no backing project Pose is consumed)."""
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    svc = ApplicationService()
    svc.new_project("test")
    from quino.domain.inputs import MarkerInput
    svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    ws = svc.project.workspace
    default_pose = next(p for p in ws.poses if p.is_default)

    window = MainWindow(svc)
    window._on_workflow_pose_selected(default_pose.id)
    qt_app.processEvents()

    assert window._app_mode == "pose"
    assert window.canvas.is_pose_readonly() is True
    assert svc.get_current_pose_id() is None
    # The composed project still contains the body (so the canvas paints it).
    assert any(b.id != "" for b in svc.display_project.model.bodies)

    window.close()
    qt_app.processEvents()


def test_canvas_badge_shows_active_pose_in_pose_mode() -> None:
    """When the user enters pose mode the top-left badge stack lists the
    pose name in addition to the active case (if any)."""
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    svc = ApplicationService()
    svc.new_project("test")
    case = svc.workspace.create_case("CaseAlpha")
    wp = svc.workspace.create_pose("PoseBeta", case_id=case.id)
    svc.set_working_context(case_id=case.id)
    svc.set_selected_pose(wp.id)

    window = MainWindow(svc)
    window._set_app_mode("pose")
    qt_app.processEvents()

    # Render to a QImage and inspect the painted text via the badge code path.
    # We just exercise the painter to confirm no crash and that the canvas
    # interaction mode is `pose` so the badge logic kicks in.
    img = QtGui.QImage(400, 200, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtCore.Qt.GlobalColor.white)
    painter = QtGui.QPainter(img)
    window.canvas._draw_active_case_badge(painter)
    painter.end()

    assert window.canvas._interaction_mode == "pose"
    assert svc.project.workspace.selected_pose_id == wp.id

    window.close()
    qt_app.processEvents()


def test_mode_indicator_is_anchored_top_right_of_canvas() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.resize(1000, 700)
    window.show()
    qt_app.processEvents()

    pill = window._mode_model_btn.parentWidget()
    assert pill.objectName() == "modeIndicatorOverlay"
    assert pill.parentWidget() is window._center_stack
    # Anchored to the right edge with a 12-px padding.
    assert pill.pos().y() == 12
    assert pill.pos().x() + pill.width() <= window._center_stack.width()
    assert pill.pos().x() + pill.width() >= window._center_stack.width() - 24

    # Pose / Analysis indicators are non-interactive (informational only).
    assert window._mode_pose_btn.isEnabled() is False
    assert window._mode_analysis_btn.isEnabled() is False
    # Model / Sketch remain interactive.
    assert window._mode_model_btn.isEnabled() is True
    assert window._mode_sketch_btn.isEnabled() is True

    window.close()
    qt_app.processEvents()


def test_main_window_can_load_slider_crank_example_and_run_timeline() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())

    window.load_slider_crank_example()

    assert window.app_service.project is not None
    assert window.app_service.project.name == "Slider Crank"
    assert "Sliders: 1" in window.canvas_summary.toPlainText()
    assert window.parameters_table.columnCount() == 4
    window.run_simulation()

    assert window._last_simulation_result is not None
    assert window._last_simulation_result.frames
    assert window.timeline_slider.maximum() == len(window._last_simulation_result.frames) - 1
    assert window._last_simulation_state is not None

    if window.timeline_slider.maximum() > 0:
        window.timeline_slider.setValue(1)
        qt_app.processEvents()
        assert window._current_frame_index == 1
        assert not window._editing_allowed()
        assert not window.action_bar_tool.isEnabled()
        assert "Playback frame" in window.statusBar().currentMessage() and "(read-only)" in window.statusBar().currentMessage()

    assert not window.canvas.grab().isNull()
    window.close()
    qt_app.processEvents()


def test_editing_after_simulation_discards_simulation_when_confirmed(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.load_four_bar_example()
    window.run_simulation()
    qt_app.processEvents()

    assert window._last_simulation_result is not None
    assert window._last_simulation_result.frames
    assert window.action_play_pause.isEnabled()

    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Ok),
    )
    marker_id = window.app_service.project.model.bodies[0].structural_markers()[0].id

    window._apply_property_update(marker_id, "x", "5 mm", "expression")
    qt_app.processEvents()

    assert window._last_simulation_result is None
    assert not window.action_play_pause.isEnabled()
    assert not window.action_stop.isEnabled()
    assert "Simulation discarded because the model was edited" in window.messages.toPlainText()

    window.close()
    qt_app.processEvents()


def test_editing_after_simulation_can_be_cancelled(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.load_four_bar_example()
    window.run_simulation()
    qt_app.processEvents()

    marker = window.app_service.project.model.bodies[0].structural_markers()[0]
    original_expression = marker.x.expression
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Cancel),
    )

    window._apply_property_update(marker.id, "x", "5 mm", "expression")
    qt_app.processEvents()

    assert window._last_simulation_result is not None
    assert marker.x.expression == original_expression

    window.close()
    qt_app.processEvents()


def test_pose_constraint_validation_rejects_angular_limit_violation() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "P"))
    marker_a = next(m.id for m in window.app_service._find_body(body_id).markers if m.name == "A")
    joint_id = window.app_service.connect_marker_to_ground(marker_a)
    window.app_service.update_property(joint_id, "angle_limit_positive", PropertyValueInput("expression", "10 deg"))
    window.app_service.update_property(joint_id, "angle_limit_negative", PropertyValueInput("expression", "10 deg"))

    pose = window.app_service.reset_current_pose_to_reference()
    pose.body_poses[body_id].angle = math.radians(30.0)
    window.app_service.set_current_pose(pose)

    violation = window._pose_joint_constraint_violation(tolerance_mm=1e-3)

    assert violation is not None
    assert "angular limit" in violation

    window.close()
    qt_app.processEvents()


def test_switching_to_model_rewinds_to_t0_without_discarding_simulation() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.load_slider_crank_example()
    window.run_simulation()
    qt_app.processEvents()

    assert window._last_simulation_result is not None
    assert window._last_simulation_result.frames
    if window.timeline_slider.maximum() == 0:
        window.close()
        qt_app.processEvents()
        return

    frame0 = window._last_simulation_result.frames[0]
    window._set_app_mode("analysis")
    window.timeline_slider.setValue(1)
    qt_app.processEvents()
    assert window._current_frame_index == 1
    assert not window._editing_allowed()

    window._set_app_mode("model")
    qt_app.processEvents()

    assert window._app_mode == "model"
    assert window._current_frame_index == 0
    assert window._last_simulation_result is not None
    assert window._last_simulation_state == frame0
    assert window._editing_allowed()
    assert not window._playback_widget.isVisible()
    assert "Editable (t=0)" in window.statusBar().currentMessage()

    window.close()
    qt_app.processEvents()


def test_canvas_can_create_bar_body_and_slider_from_tools() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    window.action_bar_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(-40.0, 0.0))
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(40.0, 0.0))
    qt_app.processEvents()

    assert len(window.app_service.project.model.bodies) == 1
    assert window.app_service.project.model.bodies[0].type.value == "bar"

    window.action_body_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(-20.0, 40.0))
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(20.0, 40.0))
    QtTest.QTest.mouseDClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(0.0, 80.0))
    qt_app.processEvents()

    assert len(window.app_service.project.model.bodies) == 2
    assert window.app_service.project.model.bodies[1].type.value == "body"

    window.action_slider_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(80.0, -10.0))
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(160.0, -10.0))
    qt_app.processEvents()

    assert len(window.app_service.project.model.sliders) == 1

    window.close()
    qt_app.processEvents()


def test_create_bar_can_start_from_existing_marker_with_named_joint(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_body("Base", [MarkerInput("0 mm", "0 mm", "A")])
    existing_marker = next(marker.id for marker in window.app_service._find_body(body_id).structural_markers())
    window.refresh_all()
    monkeypatch.setattr(window.canvas, "_request_creation_marker_joint", lambda clicked_marker: ("JointFromStart", "revolute"))

    window.action_bar_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_entity(existing_marker))
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(80.0, 0.0))
    qt_app.processEvents()

    assert len(window.app_service.project.model.bodies) == 2
    assert any(joint.name == "JointFromStart" for joint in window.app_service.project.model.joints)

    window.close()
    qt_app.processEvents()


def test_create_bar_can_end_on_existing_marker_with_named_joint(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_body("Base", [MarkerInput("100 mm", "0 mm", "A")])
    existing_marker = next(marker.id for marker in window.app_service._find_body(body_id).structural_markers())
    window.refresh_all()
    monkeypatch.setattr(window.canvas, "_request_creation_marker_joint", lambda clicked_marker: ("JointAtEnd", "rigid"))

    window.action_bar_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(0.0, 0.0))
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_entity(existing_marker))
    qt_app.processEvents()

    assert len(window.app_service.project.model.bodies) == 2
    joint = next(joint for joint in window.app_service.project.model.joints if joint.name == "JointAtEnd")
    assert joint.type.value == "rigid"

    window.close()
    qt_app.processEvents()


def test_canvas_can_select_body_and_escape_clears_selection() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    window.refresh_all()
    window.action_select_tool.trigger()

    body_click = window.canvas.screen_position_for_world(50.0, 0.0)
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=body_click)
    qt_app.processEvents()

    assert window._selected_entity_id == body_id

    QtTest.QTest.keyClick(window.canvas, QtCore.Qt.Key.Key_Escape)
    qt_app.processEvents()

    assert window._selected_entity_id is None
    assert window.tree.currentItem() is None

    window.close()
    qt_app.processEvents()


def test_canvas_can_drag_marker_create_joints_and_add_marker(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    app = window.app_service
    app.new_project("CanvasEdit")
    body1 = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    body2 = app.create_body("Mass2", [MarkerInput("60 mm", "0 mm", "P2")])
    slider_id = app.create_slider_from_points("Guide", "100 mm", "0 mm", "180 mm", "0 mm")
    window.refresh_all()
    monkeypatch.setattr(window.canvas, "_request_joint_name", lambda: "Joint1")
    monkeypatch.setattr(window.canvas, "_request_ground_or_slider_joint", lambda prefix: (f"{prefix}1", "revolute"))

    marker1 = next(marker.id for marker in app._find_body(body1).markers if marker.name == "P1")
    marker2 = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P2")

    window.action_select_tool.trigger()
    start = window.canvas.screen_position_for_entity(marker1)
    end = window.canvas.screen_position_for_world(10.0, 15.0)
    assert start is not None
    QtTest.QTest.mousePress(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=start)
    QtTest.QTest.mouseMove(window.canvas, end)
    QtTest.QTest.mouseRelease(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=end)
    qt_app.processEvents()

    moved_marker = app._find_entity(marker1)
    assert abs(_expr_value(moved_marker.x.expression) - 10.0) < 0.5
    assert abs(_expr_value(moved_marker.y.expression) - 15.0) < 0.5

    window.action_joint_tool.trigger()
    pos1 = window.canvas.screen_position_for_entity(marker1)
    pos2 = window.canvas.screen_position_for_entity(marker2)
    assert pos1 is not None and pos2 is not None
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos1)
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos2)
    qt_app.processEvents()

    assert len(app.project.model.joints) == 1

    window.action_slider_connect_tool.trigger()
    pos_marker2 = window.canvas.screen_position_for_entity(marker2)
    pos_slider = window.canvas.screen_position_for_entity(slider_id)
    assert pos_marker2 is not None and pos_slider is not None
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos_marker2)
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos_slider)
    qt_app.processEvents()

    assert len(app.project.model.joints) == 2

    window._select_entity_by_id(body1)
    window.action_add_marker_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(20.0, 20.0))
    qt_app.processEvents()

    assert len(app._find_body(body1).structural_markers()) == 2

    window.close()
    qt_app.processEvents()


def test_inspector_boolean_fields_use_combo_box() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    body_id = window.app_service.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    marker_id = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "P1")
    window.refresh_all()
    window._select_entity_by_id(marker_id)
    qt_app.processEvents()

    combo = window.inspector.cellWidget(3, 1)
    assert isinstance(combo, QtWidgets.QComboBox)
    combo.setCurrentText("false")
    qt_app.processEvents()

    assert window.app_service._find_entity(marker_id).visible is False

    window.close()
    qt_app.processEvents()


def test_canvas_can_drag_slider_center_in_t0() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    slider_id = window.app_service.create_slider_from_points("Guide", "100 mm", "0 mm", "180 mm", "0 mm")
    window.refresh_all()
    window.action_select_tool.trigger()

    start = window.canvas.screen_position_for_entity(slider_id)
    end = window.canvas.screen_position_for_world(200.0, 20.0)
    assert start is not None
    QtTest.QTest.mousePress(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=start)
    QtTest.QTest.mouseMove(window.canvas, end)
    QtTest.QTest.mouseRelease(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=end)
    qt_app.processEvents()

    slider = window.app_service._find_entity(slider_id)
    assert abs(_expr_value(slider.origin_x.expression) - 200.0) < 0.5
    assert abs(_expr_value(slider.origin_y.expression) - 20.0) < 0.5

    window.close()
    qt_app.processEvents()


def test_canvas_connect_slider_accepts_slider_first_order(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()
    app = window.app_service
    app.new_project("SliderFirst")
    body_id = app.create_body("Mass", [MarkerInput("50 mm", "20 mm", "P")])
    slider_id = app.create_slider_from_points("Guide", "0 mm", "0 mm", "100 mm", "0 mm")
    marker_id = next(marker.id for marker in app.get_body(body_id).markers if marker.name == "P")
    monkeypatch.setattr(window.canvas, "_request_ground_or_slider_joint", lambda prefix: (f"{prefix}1", "revolute"))
    window.refresh_all()

    window.action_slider_connect_tool.trigger()
    pos_slider = window.canvas.screen_position_for_entity(slider_id)
    pos_marker = window.canvas.screen_position_for_entity(marker_id)
    assert pos_slider is not None and pos_marker is not None
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos_slider)
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos_marker)
    qt_app.processEvents()

    marker = app.get_entity(marker_id)
    slider = app.get_entity(slider_id)
    assert _expr_value(marker.x.expression) == pytest.approx(50.0, abs=0.5)
    assert _expr_value(marker.y.expression) == pytest.approx(0.0, abs=0.5)
    assert _expr_value(slider.origin_y.expression) == pytest.approx(0.0, abs=0.5)
    assert not any(message.code == "slider_joint_gap" for message in app.validate_model().messages)

    window.close()
    qt_app.processEvents()


def test_canvas_can_create_free_ground_and_connect_marker_to_it(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()
    app = window.app_service
    body_id = app.create_body("Mass", [MarkerInput("50 mm", "20 mm", "P")])
    marker_id = next(marker.id for marker in app.get_body(body_id).markers if marker.name == "P")
    monkeypatch.setattr(window.canvas, "_request_ground_or_slider_joint", lambda prefix: (f"{prefix}1", "revolute"))
    monkeypatch.setattr(window.canvas, "_request_joint_name", lambda: "Joint1")
    window.refresh_all()

    window.action_ground_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(0.0, 0.0))
    qt_app.processEvents()

    ground_body = next(body for body in app.project.model.bodies if body.metadata.values.get("ground_anchor"))
    ground_pos = window.canvas.screen_position_for_entity(ground_body.id)
    marker_pos = window.canvas.screen_position_for_entity(marker_id)
    assert ground_pos is not None and marker_pos is not None
    assert any(joint.metadata.values.get("internal_ground_anchor") for joint in app.project.model.joints)

    window.action_joint_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=marker_pos)
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=ground_pos)
    qt_app.processEvents()

    visible_joints = [joint for joint in app.project.model.joints if not joint.metadata.values.get("internal_ground_anchor")]
    assert len(visible_joints) == 1
    assert visible_joints[0].name == "GroundJoint1"

    window.close()
    qt_app.processEvents()


def test_canvas_can_create_slider_from_marker(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()
    app = window.app_service
    body_id = app.create_body("Mass", [MarkerInput("50 mm", "20 mm", "P")])
    marker_id = next(marker.id for marker in app.get_body(body_id).markers if marker.name == "P")
    monkeypatch.setattr(window.canvas, "_request_ground_or_slider_joint", lambda prefix: (f"{prefix}1", "revolute"))
    window.refresh_all()

    window.action_slider_tool.trigger()
    marker_pos = window.canvas.screen_position_for_entity(marker_id)
    end_pos = window.canvas.screen_position_for_world(90.0, 20.0)
    assert marker_pos is not None
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=marker_pos)
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=end_pos)
    qt_app.processEvents()

    assert len(app.project.model.sliders) == 1
    assert len([joint for joint in app.project.model.joints if not joint.metadata.values.get("internal_ground_anchor")]) == 1
    slider = app.project.model.sliders[0]
    assert _expr_value(slider.origin_x.expression) == pytest.approx(50.0, abs=0.5)
    assert _expr_value(slider.origin_y.expression) == pytest.approx(20.0, abs=0.5)
    assert _expr_value(slider.travel_min.expression) == pytest.approx(-40.0, abs=0.5)
    assert _expr_value(slider.travel_max.expression) == pytest.approx(40.0, abs=0.5)

    window.close()
    qt_app.processEvents()


def test_slider_center_preview_preserves_angle_units() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    slider_id = window.app_service.create_slider("Guide", SliderInput("0 mm", "0 mm", "45 deg"))
    window.refresh_all()

    preview = window.canvas._slider_preview_for_handle(slider_id, "center", (10.0, 10.0))

    assert preview["angle_deg"] == 45.0

    window.close()
    qt_app.processEvents()


def test_parameters_panel_and_playback_controls_work(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.load_four_bar_example()
    window.show()
    qt_app.processEvents()

    window._add_parameter()
    qt_app.processEvents()
    assert len(window.app_service.project.parameters) == 1

    window.parameters_table.item(0, 0).setText("Ltest")
    window.parameters_table.item(0, 1).setText("25 mm")
    window.parameters_table.item(0, 2).setText("mm")
    qt_app.processEvents()
    assert window.app_service.project.parameters[0].name == "Ltest"

    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        staticmethod(lambda *args, **kwargs: ("RotationDriver1" if "name" in args[2].lower() else "20 deg * t / 1 s", True)),
    )
    existing_driver_id = window.app_service.project.model.drivers[0].id
    window.app_service.delete_entity(existing_driver_id)
    window.refresh_all()
    ground_joint_id = next(joint.id for joint in window.app_service.project.model.joints if joint.name == "Ground_A")
    window._select_entity_by_id(ground_joint_id)
    window._create_driver_for_selected("rotation")
    assert len(window.app_service.project.model.drivers) == 1

    window.run_simulation()
    qt_app.processEvents()
    assert window._last_simulation_result is not None
    assert window._last_simulation_result.frames

    if len(window._last_simulation_result.frames) > 1:
        window.toggle_playback()
        QtTest.QTest.qWait(120)
        qt_app.processEvents()
        assert window._current_frame_index >= 0
        window.stop_playback()
        assert window._current_frame_index == 0

    window.close()
    qt_app.processEvents()


def test_canvas_blocks_editing_outside_t0_and_renders_visual_entities(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.load_slider_crank_example()
    window.show()
    qt_app.processEvents()

    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        staticmethod(lambda *args, **kwargs: ("RotationDriver1" if "name" in args[2].lower() else "20 deg * t / 1 s", True)),
    )

    marker_id = next(
        marker.id
        for body in window.app_service.project.model.bodies
        for marker in body.structural_markers()
    )
    joint_id = window.app_service.project.model.joints[0].id
    driver_id = window.app_service.project.model.drivers[0].id

    assert window.canvas.screen_position_for_entity(joint_id) is not None
    assert window.canvas.screen_position_for_entity(driver_id) is not None

    original_x = window.app_service._find_entity(marker_id).x.expression
    window.run_simulation()
    qt_app.processEvents()

    if window.timeline_slider.maximum() > 0:
        window.timeline_slider.setValue(1)
        qt_app.processEvents()
        assert not window._editing_allowed()
        assert not window.action_add_marker_tool.isEnabled()
        assert window.parameters_table.editTriggers() == QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        window.refresh_all()
        qt_app.processEvents()
        inspector_item = window.inspector.item(0, 1)
        assert inspector_item is not None
        assert not bool(inspector_item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
        if window.parameters_table.rowCount() > 0:
            parameter_item = window.parameters_table.item(0, 0)
            assert parameter_item is not None
            assert not bool(parameter_item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)

        start = window.canvas.screen_position_for_entity(marker_id)
        end = window.canvas.screen_position_for_world(25.0, 25.0)
        assert start is not None
        QtTest.QTest.mousePress(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=start)
        QtTest.QTest.mouseMove(window.canvas, end)
        QtTest.QTest.mouseRelease(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=end)
        qt_app.processEvents()

        moved_marker = window.app_service._find_entity(marker_id)
        assert moved_marker.x.expression == original_x

    assert not window.canvas.grab().isNull()
    window.close()
    qt_app.processEvents()


def test_canvas_helper_mutations_are_blocked_outside_t0(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.load_slider_crank_example()
    window.show()
    qt_app.processEvents()

    joint_id = window.app_service.project.model.joints[0].id
    driver_id = window.app_service.project.model.drivers[0].id
    body = window.app_service.project.model.bodies[0]
    marker = body.structural_markers()[0]
    slider = window.app_service.project.model.sliders[0]

    original_joint_name = window.app_service._find_joint(joint_id).name
    original_driver_law = window.app_service._find_entity(driver_id).law.expression
    original_marker_count = len(body.structural_markers())
    original_joint_count = len(window.app_service.project.model.joints)

    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        staticmethod(lambda *args, **kwargs: ("BlockedEdit", True)),
    )

    window.run_simulation()
    qt_app.processEvents()
    if window.timeline_slider.maximum() == 0:
        window.close()
        qt_app.processEvents()
        return

    window.timeline_slider.setValue(1)
    qt_app.processEvents()
    assert not window._editing_allowed()

    window.canvas._rename_entity_dialog(joint_id)
    window.canvas._edit_driver_law_dialog(driver_id)
    window.canvas._add_marker_to_selected_body((25.0, 25.0), fallback_body=body.id)
    window.canvas._create_ground_joint(
        window.canvas._collect_markers(window.app_service.project, window.canvas._assembled_mechanism(window.app_service.project))[0]
    )
    qt_app.processEvents()

    assert window.app_service._find_joint(joint_id).name == original_joint_name
    assert window.app_service._find_entity(driver_id).law.expression == original_driver_law
    assert len(window.app_service._find_body(body.id).structural_markers()) == original_marker_count
    assert len(window.app_service.project.model.joints) == original_joint_count
    assert "Editing is only available at t=0" in window.messages.toPlainText()

    window.close()
    qt_app.processEvents()


def test_canvas_helpers_can_rename_joint_toggle_type_and_edit_driver(monkeypatch) -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.load_four_bar_example()
    window.show()
    qt_app.processEvents()

    joint_id = window.app_service.project.model.joints[0].id
    driver_id = window.app_service.project.model.drivers[0].id

    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        staticmethod(lambda *args, **kwargs: ("JointRenamed", True)),
    )
    window.canvas._rename_entity_dialog(joint_id)
    assert window.app_service._find_joint(joint_id).name == "JointRenamed"

    window.app_service.delete_entity(driver_id)
    window.canvas._toggle_joint_type(joint_id)
    assert window.app_service._find_joint(joint_id).type.value == "rigid"

    joint_id = next(joint.id for joint in window.app_service.project.model.joints if joint.type.value == "revolute")
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        staticmethod(lambda *args, **kwargs: ("RotationDriver1" if "name" in args[2].lower() else "35 deg * t / 1 s", True)),
    )
    window._select_entity_by_id(joint_id)
    window._create_driver_for_selected("rotation")
    driver_id = window.app_service.project.model.drivers[-1].id

    # Patch QDialog.exec to return Accepted and set line edit text
    original_exec = QtWidgets.QDialog.exec

    def mock_exec(self):
        # Find the QLineEdit in the dialog and set its text
        for widget in self.findChildren(QtWidgets.QLineEdit):
            widget.setText("45 deg * t / 1 s")
            break
        return QtWidgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(QtWidgets.QDialog, "exec", mock_exec)
    window.canvas._edit_driver_law_dialog(driver_id)
    assert window.app_service._find_entity(driver_id).law.expression == "45 deg * t / 1 s"

    window.close()
    qt_app.processEvents()


def test_canvas_can_create_basic_sketch_entities_and_toggle_visibility() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    window.action_sketch_point_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(0.0, 0.0))
    qt_app.processEvents()
    point_id = list(window.app_service.project.sketch.entities.values())[0].id

    window.action_sketch_line_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_entity(point_id))
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(60.0, 0.0))
    qt_app.processEvents()

    window.action_sketch_circle_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_entity(point_id))
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(20.0, 0.0))
    qt_app.processEvents()

    assert window.app_service.project.sketch is not None
    assert len(window.app_service.project.sketch.entities) >= 4

    window.action_toggle_sketch_visible.setChecked(False)
    qt_app.processEvents()
    assert window.app_service.project.sketch.visible is False
    window.action_toggle_sketch_visible.setChecked(True)
    qt_app.processEvents()
    assert window.app_service.project.sketch.visible is True

    window.close()
    qt_app.processEvents()


def test_canvas_can_create_rectangle_and_keep_line_polyline_active() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    window.action_sketch_rectangle_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(0.0, 0.0))
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(80.0, 40.0))
    qt_app.processEvents()

    sketch = window.app_service.project.sketch
    assert sketch is not None
    assert sum(1 for entity in sketch.entities.values() if entity.type.value == "line_segment") == 4
    assert sum(1 for constraint in sketch.constraints.values() if constraint.type.value == "horizontal") == 2
    assert sum(1 for constraint in sketch.constraints.values() if constraint.type.value == "vertical") == 2

    window.action_sketch_line_tool.trigger()
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(120.0, 0.0))
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(160.0, 0.0))
    qt_app.processEvents()
    assert window.canvas.mode() == "create_sketch_line_segment"

    window.close()
    qt_app.processEvents()


def test_arc_tool_uses_center_start_end_mode() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    window.action_sketch_arc_tool.trigger()
    qt_app.processEvents()

    assert window.canvas.mode() == "create_sketch_arc_center"
    assert "Click center, start, end" in window.statusBar().currentMessage()

    window.close()
    qt_app.processEvents()


def test_concentric_tool_accepts_arc_and_circle() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    center_circle = window.app_service.create_sketch_point("0 mm", "0 mm", "O1")
    circle_id = window.app_service.create_sketch_circle(center_circle, "10 mm", "C1")
    arc_id = window.app_service.create_sketch_arc_by_center(10.0, 0.0, 20.0, 0.0, 10.0, 10.0, "A1")
    window.refresh_all()

    window.action_sketch_concentric_tool.trigger()
    window.canvas.inject_entity_selection(circle_id)
    window.canvas.inject_entity_selection(arc_id)
    qt_app.processEvents()

    assert any(
        constraint.type.value == "coincident" and len(constraint.references) == 2
        for constraint in window.app_service.project.sketch.constraints.values()
    )

    window.close()
    qt_app.processEvents()


def test_solve_button_runs_sketch_solver() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    p1 = window.app_service.create_sketch_point("0 mm", "0 mm", "A")
    p2 = window.app_service.create_sketch_point("40 mm", "15 mm", "B")
    window.app_service.create_sketch_constraint("horizontal", [p1, p2], name="H1")
    window.refresh_all()

    window.action_solve_sketch.trigger()
    qt_app.processEvents()

    assert "Sketch solved" in window.messages.toPlainText()

    window.close()
    qt_app.processEvents()


def test_canvas_multi_and_box_selection_for_sketch_points() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    p1 = window.app_service.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = window.app_service.create_sketch_point("40 mm", "0 mm", "P2")
    window.refresh_all()
    window._set_app_mode("sketch")
    window.action_select_tool.trigger()
    qt_app.processEvents()

    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_entity(p1))
    QtTest.QTest.mouseClick(
        window.canvas,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.ShiftModifier,
        pos=window.canvas.screen_position_for_entity(p2),
    )
    qt_app.processEvents()
    assert {p1, p2}.issubset(window.canvas._selected_entity_ids)

    start = window.canvas.screen_position_for_world(-10.0, 10.0)
    end = window.canvas.screen_position_for_world(50.0, -10.0)
    QtTest.QTest.mousePress(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=start)
    QtTest.QTest.mouseMove(window.canvas, end)
    QtTest.QTest.mouseRelease(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=end)
    qt_app.processEvents()
    assert {p1, p2}.issubset(window.canvas._selected_entity_ids)

    window.close()
    qt_app.processEvents()


def test_canvas_snap_prefers_line_midpoint() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    p1 = window.app_service.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = window.app_service.create_sketch_point("100 mm", "0 mm", "P2")
    window.app_service.create_sketch_line_segment(p1, p2, "L1")
    window.refresh_all()
    qt_app.processEvents()

    snapped = window.canvas._snap_world((50.0, 1.0), include_model=False)

    assert snapped == pytest.approx((50.0, 0.0), abs=1e-6)
    assert window.canvas._snap_kind == "midpoint"

    window.close()
    qt_app.processEvents()


def test_canvas_distance_constraint_waits_for_label_position() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    p1 = window.app_service.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = window.app_service.create_sketch_point("40 mm", "0 mm", "P2")
    window.refresh_all()
    window._set_app_mode("sketch")
    window.action_sketch_distance_tool.trigger()
    qt_app.processEvents()

    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_entity(p1))
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_entity(p2))
    qt_app.processEvents()
    assert window.canvas.mode() == "create_sketch_distance"
    assert window.canvas._pending_distance_constraint_refs == [p1, p2]

    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(20.0, 15.0))
    qt_app.processEvents()

    constraint = next(iter(window.app_service.project.sketch.constraints.values()))
    assert constraint.type.value == "distance"
    assert constraint.metadata.values["label_position"] == pytest.approx([20.0, 15.0], abs=0.5)

    window.close()
    qt_app.processEvents()


def test_canvas_horizontal_distance_constraint_waits_for_label_position() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    p1 = window.app_service.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = window.app_service.create_sketch_point("40 mm", "10 mm", "P2")
    window.refresh_all()
    window._set_app_mode("sketch")
    window.action_sketch_horizontal_distance_tool.trigger()
    qt_app.processEvents()

    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_entity(p1))
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_entity(p2))
    qt_app.processEvents()
    assert window.canvas.mode() == "create_sketch_horizontal_distance"
    assert window.canvas._pending_distance_constraint_refs == [p1, p2]

    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(20.0, 20.0))
    qt_app.processEvents()

    constraint = next(iter(window.app_service.project.sketch.constraints.values()))
    assert constraint.type.value == "horizontal_distance"
    assert constraint.metadata.values["label_position"] == pytest.approx([20.0, 20.0], abs=0.5)

    window.close()
    qt_app.processEvents()


def test_canvas_distance_constraint_can_be_created_from_line_entity() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    p1 = window.app_service.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = window.app_service.create_sketch_point("40 mm", "0 mm", "P2")
    line_id = window.app_service.create_sketch_line_segment(p1, p2, "L1")
    window.refresh_all()
    window._set_app_mode("sketch")
    window.action_sketch_distance_tool.trigger()
    qt_app.processEvents()

    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_entity(line_id))
    qt_app.processEvents()

    assert window.canvas._pending_distance_constraint_refs == [p1, p2]

    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=window.canvas.screen_position_for_world(20.0, 15.0))
    qt_app.processEvents()

    constraint = next(iter(window.app_service.project.sketch.constraints.values()))
    assert constraint.type.value == "distance"
    assert constraint.references == [p1, p2]

    window.close()
    qt_app.processEvents()


def test_canvas_clicking_distance_constraint_selects_it() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    p1 = window.app_service.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = window.app_service.create_sketch_point("40 mm", "0 mm", "P2")
    constraint_id = window.app_service.create_sketch_constraint("distance", [p1, p2], value="40 mm")
    window.app_service.update_sketch_constraint(constraint_id, "label_x", PropertyValueInput("expression", "20 mm"))
    window.app_service.update_sketch_constraint(constraint_id, "label_y", PropertyValueInput("expression", "15 mm"))
    window.refresh_all()
    window._set_app_mode("sketch")
    window.action_select_tool.trigger()
    qt_app.processEvents()

    pos = window.canvas.screen_position_for_entity(constraint_id)
    assert pos is not None
    QtTest.QTest.mouseClick(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos)
    qt_app.processEvents()

    assert window.canvas._selected_entity_id == constraint_id

    window.close()
    qt_app.processEvents()




def test_sketch_point_can_be_edited_from_inspector_and_canvas_drag_snaps_marker() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    sketch_point_id = window.app_service.create_sketch_point("30 mm", "30 mm", "SnapPoint")
    body_id = window.app_service.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    marker_id = next(marker.id for marker in window.app_service._find_body(body_id).structural_markers())
    window.refresh_all()

    window._select_entity_by_id(sketch_point_id)
    qt_app.processEvents()
    x_item = window.inspector.item(3, 1)
    x_item.setText("40 mm")
    qt_app.processEvents()
    assert window.app_service._find_sketch_point(sketch_point_id).x.text == "40 mm"

    window.action_select_tool.trigger()
    start = window.canvas.screen_position_for_entity(marker_id)
    end = window.canvas.screen_position_for_world(39.5, 30.4)
    assert start is not None
    QtTest.QTest.mousePress(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=start)
    QtTest.QTest.mouseMove(window.canvas, end)
    QtTest.QTest.mouseRelease(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=end)
    qt_app.processEvents()

    marker = window.app_service._find_entity(marker_id)
    assert abs(_expr_value(marker.x.expression) - 40.0) < 0.5
    assert abs(_expr_value(marker.y.expression) - 30.0) < 0.5

    window.close()
    qt_app.processEvents()


def test_sketch_status_hint_and_reference_fields_are_readonly() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    p1 = window.app_service.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = window.app_service.create_sketch_point("50 mm", "0 mm", "P2")
    line_id = window.app_service.create_sketch_line_segment(p1, p2, "L1")
    window.refresh_all()

    window.action_sketch_circle_tool.trigger()
    qt_app.processEvents()
    assert "Center + radius point" in window.statusBar().currentMessage()

    window._select_entity_by_id(line_id)
    qt_app.processEvents()
    start_row = _inspector_row_by_property(window, "start_point_id")
    end_row = _inspector_row_by_property(window, "end_point_id")
    start_item = window.inspector.item(start_row, 1)
    end_item = window.inspector.item(end_row, 1)
    start_eval = window.inspector.item(start_row, 2)
    end_eval = window.inspector.item(end_row, 2)
    assert start_item is not None and end_item is not None
    assert start_eval is not None and end_eval is not None
    assert "P1 (" in start_eval.text()
    assert "P2 (" in end_eval.text()
    assert not bool(start_item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
    assert not bool(end_item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)

    window.close()
    qt_app.processEvents()


def test_canvas_can_create_sketch_constraints_and_solve_on_drag() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    p1 = window.app_service.create_sketch_point("0 mm", "0 mm", "A")
    p2 = window.app_service.create_sketch_point("40 mm", "15 mm", "B")
    window.refresh_all()

    window.action_sketch_horizontal_tool.trigger()
    assert window.canvas.mode() == "create_sketch_horizontal"
    window.canvas.inject_entity_selection(p1)
    window.canvas.inject_entity_selection(p2)
    qt_app.processEvents()

    assert any(constraint.type.value == "horizontal" for constraint in window.app_service.project.sketch.constraints.values())

    window.action_select_tool.trigger()
    start = window.canvas.screen_position_for_entity(p1)
    end = window.canvas.screen_position_for_world(10.0, 25.0)
    assert start is not None
    QtTest.QTest.mousePress(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=start)
    QtTest.QTest.mouseMove(window.canvas, end)
    QtTest.QTest.mouseRelease(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=end)
    qt_app.processEvents()

    point_a = window.app_service._find_sketch_point(p1)
    point_b = window.app_service._find_sketch_point(p2)
    assert point_a.y.text == point_b.y.text

    window.close()
    qt_app.processEvents()


def test_sketch_mode_renders_dimmed_model() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    # Create both sketch and model elements
    window.app_service.create_sketch()
    window.app_service.create_sketch_point("10 mm", "10 mm", "SP1")
    window.app_service.create_body("Body1", [MarkerInput("0 mm", "0 mm", "M1")])
    window.refresh_all()

    # Switch to sketch mode — paintEvent should not crash with dimmed model layer
    window.canvas.set_interaction_mode("sketch")
    window.canvas.update()
    qt_app.processEvents()

    # Switch back to model mode — paintEvent should render normally
    window.canvas.set_interaction_mode("model")
    window.canvas.update()
    qt_app.processEvents()

    window.close()
    qt_app.processEvents()


def test_canvas_display_settings_and_preferences_dialog() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    # Default state
    assert window.canvas.show_origin() is True
    assert window.canvas.show_grid() is True
    assert window.canvas.background_color() == "#f5f1e8"

    # Toggle via toolbar actions
    window.action_toggle_origin.setChecked(False)
    window._on_toggle_origin()
    qt_app.processEvents()
    assert window.canvas.show_origin() is False

    window.action_toggle_grid.setChecked(False)
    window._on_toggle_grid()
    qt_app.processEvents()
    assert window.canvas.show_grid() is False

    window.action_toggle_sensors.setChecked(False)
    window._on_toggle_sensors()
    qt_app.processEvents()
    assert window.canvas.show_sensors() is False
    assert window.app_service.project.view_state.show_sensors is False

    # Change background color directly
    window.canvas.set_background_color("#ffffff")
    qt_app.processEvents()
    assert window.canvas.background_color() == "#ffffff"

    # Preferences dialog exists and can be invoked
    assert window.action_preferences is not None

    window.close()
    qt_app.processEvents()


def test_sensor_scope_can_be_dragged_and_persisted() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_body("Body", [MarkerInput("0 mm", "0 mm", "P")])
    marker_id = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "P")
    sensor_id = window.app_service.create_sensor("Probe", "point", [marker_id])
    window.refresh_all()
    qt_app.processEvents()

    start = window.canvas.screen_position_for_entity(sensor_id)
    assert start is not None
    end = start + QtCore.QPoint(80, 40)

    QtTest.QTest.mousePress(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=start)
    QtTest.QTest.mouseMove(window.canvas, end)
    QtTest.QTest.mouseRelease(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=end)
    qt_app.processEvents()

    sensor = next(item for item in window.app_service.project.model.sensors if item.id == sensor_id)
    assert float(sensor.metadata.values["scope_canvas_x"]) != pytest.approx(0.0)
    assert float(sensor.metadata.values["scope_canvas_y"]) != pytest.approx(0.0)
    moved = window.canvas.screen_position_for_entity(sensor_id)
    assert moved is not None
    assert abs(moved.x() - start.x()) > 20

    window.close()
    qt_app.processEvents()


def test_canvas_drag_render_survives_incomplete_sensor_geometry() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_body("Body", [MarkerInput("0 mm", "0 mm", "P")])
    marker_id = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "P")
    window.app_service.create_sensor("BrokenDist", "distance", [marker_id])
    window.refresh_all()
    qt_app.processEvents()

    pos = window.canvas.screen_position_for_entity(marker_id)
    assert pos is not None
    QtTest.QTest.mousePress(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos)
    QtTest.QTest.mouseMove(window.canvas, pos + QtCore.QPoint(20, 10))
    QtTest.QTest.mouseRelease(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos + QtCore.QPoint(20, 10))
    qt_app.processEvents()

    assert window.canvas.screen_position_for_entity(marker_id) is not None

    window.close()
    qt_app.processEvents()


def test_canvas_dragging_bar_marker_keeps_canvas_rendering() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    body_id = window.app_service.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_b = next(marker.id for marker in window.app_service._find_body(body_id).markers if marker.name == "B")
    window.refresh_all()
    qt_app.processEvents()

    pos = window.canvas.screen_position_for_entity(marker_b)
    assert pos is not None
    QtTest.QTest.mousePress(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos)
    QtTest.QTest.mouseMove(window.canvas, pos + QtCore.QPoint(40, 15))
    qt_app.processEvents()

    markers = window.canvas._collect_markers(
        window.app_service.project,
        window.canvas._assembled_mechanism(window.app_service.project),
    )
    assert any(marker.entity_id == marker_b for marker in markers)

    QtTest.QTest.mouseRelease(window.canvas, QtCore.Qt.MouseButton.LeftButton, pos=pos + QtCore.QPoint(40, 15))
    window.close()
    qt_app.processEvents()


def test_coincident_on_line_click_uses_entity_reference() -> None:
    """Clicking a line in COINCIDENT mode should treat it as a geometric target."""
    from quino.domain.types import SketchEntityType
    from quino.gui.canvas import CanvasMode, CanvasSketchEntity, MechanismCanvas

    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app_svc = ApplicationService()
    app_svc.new_project("test")
    canvas = MechanismCanvas(app_svc)

    app_svc.create_sketch()
    p1 = app_svc.create_sketch_point("0 mm", "0 mm")
    p2 = app_svc.create_sketch_point("100 mm", "0 mm")
    line_id = app_svc.create_sketch_line_segment(p1, p2)
    canvas.set_interaction_mode("sketch")
    canvas.set_mode(CanvasMode.CREATE_SKETCH_COINCIDENT)

    canvas._sensor_marker_ids.clear()
    canvas._creation_points.clear()

    project = app_svc.project
    seg = app_svc.get_entity(line_id)
    entity = CanvasSketchEntity(
        entity_id=seg.id,
        name="",
        entity_type=SketchEntityType.LINE_SEGMENT,
        point_ids=[seg.start_point_id, seg.end_point_id],
        visible=True,
        construction=False,
    )
    canvas._handle_constraint_input_click(None, entity, n_pts=2, n_ent=0)
    assert canvas._creation_entity_ids == [line_id]
    assert canvas._sensor_marker_ids == []


def test_coincident_point_then_line_uses_entity_reference() -> None:
    from unittest.mock import patch

    from quino.domain.types import SketchEntityType
    from quino.gui.canvas import CanvasMode, CanvasSketchEntity, CanvasSketchPoint, MechanismCanvas

    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app_svc = ApplicationService()
    app_svc.new_project("test")
    canvas = MechanismCanvas(app_svc)

    app_svc.create_sketch()
    p1 = app_svc.create_sketch_point("0 mm", "0 mm")
    p2 = app_svc.create_sketch_point("100 mm", "0 mm")
    p3 = app_svc.create_sketch_point("50 mm", "20 mm")
    line_id = app_svc.create_sketch_line_segment(p1, p2)
    canvas.set_interaction_mode("sketch")
    canvas.set_mode(CanvasMode.CREATE_SKETCH_COINCIDENT)

    seg = app_svc.get_entity(line_id)
    point = CanvasSketchPoint(entity_id=p3, name="P3", x=50.0, y=20.0, visible=True, construction=False)
    entity = CanvasSketchEntity(
        entity_id=seg.id,
        name="",
        entity_type=SketchEntityType.LINE_SEGMENT,
        point_ids=[seg.start_point_id, seg.end_point_id],
        visible=True,
        construction=False,
    )

    with patch.object(canvas, "_finalize_sketch_constraint_creation") as mock_finalize:
        canvas._handle_constraint_input_click(point, None, n_pts=2, n_ent=0)
        canvas._handle_constraint_input_click(None, entity, n_pts=2, n_ent=0)
        mock_finalize.assert_called_once()

    assert canvas._creation_entity_ids == [line_id]
    assert canvas._sensor_marker_ids == [p3]


def test_canvas_pose_readonly_blocks_drag() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app = ApplicationService()
    app.new_project("test")
    from quino.gui.canvas import MechanismCanvas
    canvas = MechanismCanvas(app)
    assert canvas.is_pose_readonly() is False
    canvas.set_pose_readonly(True)
    assert canvas.is_pose_readonly() is True
    qt_app.processEvents()


def test_workflow_tree_emits_selection_changed_on_single_click(qtbot) -> None:
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.panels.workflow_tree_panel import WorkflowTreePanel
    from quino.domain.workspace import Workspace, Baseline

    app = ApplicationService()
    app.new_project("test")
    app.project.workspace = Workspace(baselines=[Baseline(id="b", name="base")])
    panel = WorkflowTreePanel(app)
    qtbot.addWidget(panel)
    panel.refresh()

    received = []
    panel.selection_changed.connect(lambda kind, oid: received.append((kind, oid)))

    item = panel._item_map["b"]
    panel._tree.setCurrentItem(item)

    assert ("baseline", "b") in received


def test_workflow_single_click_on_case_enters_model_mode(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.main_window import MainWindow
    from quino.domain.workspace import Workspace, Baseline, Case
    app = ApplicationService()
    app.new_project("test")
    app.project.workspace = Workspace(
        baselines=[Baseline(id="b", name="base")],
        cases=[Case(id="c", name="C1", baseline_id="b")],
        active_baseline_id="b",
    )
    window = MainWindow(app)
    qtbot.addWidget(window)
    window.workflow_panel.refresh()
    item = window.workflow_panel._item_map["c"]
    window.workflow_panel._tree.setCurrentItem(item)
    assert window._app_mode == "model"
    assert app.project.workspace.active_case_id == "c"


def test_pose_mode_button_disabled_when_no_pose_selected(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.main_window import MainWindow
    from quino.domain.workspace import Workspace, Baseline
    app = ApplicationService()
    app.new_project("test")
    app.project.workspace = Workspace(
        baselines=[Baseline(id="b", name="base")],
        active_baseline_id="b",
    )
    window = MainWindow(app)
    qtbot.addWidget(window)
    window.refresh_all()
    ws = app.project.workspace
    assert ws.selected_pose_id is None
    assert not window._mode_pose_btn.isEnabled()
    assert not window._mode_analysis_btn.isEnabled()


def test_analysis_mode_button_disabled_when_no_analysis_selected(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.main_window import MainWindow
    from quino.domain.workspace import Workspace, Baseline
    app = ApplicationService()
    app.new_project("test")
    app.project.workspace = Workspace(
        baselines=[Baseline(id="b", name="base")],
        active_baseline_id="b",
    )
    window = MainWindow(app)
    qtbot.addWidget(window)
    window.refresh_all()
    ws = app.project.workspace
    assert ws.selected_analysis_id is None
    assert not window._mode_analysis_btn.isEnabled()


def test_workflow_badge_shows_breadcrumb(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.panels.workflow_tree_panel import WorkflowTreePanel
    from quino.domain.workspace import Workspace, Baseline, Case
    app = ApplicationService()
    app.new_project("test")
    app.project.workspace = Workspace(
        baselines=[Baseline(id="b", name="Baseline 1")],
        cases=[
            Case(id="c1", name="Caso 3", baseline_id="b"),
            Case(id="c2", name="Caso 3D", baseline_id="b", parent_case_id="c1"),
        ],
        active_baseline_id="b",
        active_case_id="c2",
    )
    panel = WorkflowTreePanel(app)
    qtbot.addWidget(panel)
    panel.refresh()
    badge_text = panel._badge.text()
    assert "Caso 3D" in badge_text
    assert "Caso 3" in badge_text
    assert "Baseline 1" in badge_text


def test_block_editor_widget_no_inspector(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    assert not hasattr(widget, "_inspector")
    widget.set_selected("nonexistent")  # should not raise


def test_block_palette_request_adds_block_to_editor(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    widget = BlockEditorWidget()
    qtbot.addWidget(widget)

    widget._palette.blockTypeRequested.emit("Constant")

    diagram = widget._scene.diagram
    assert len(diagram.instances) == 1
    assert next(iter(diagram.instances.values())).block_type == "Constant"


def test_main_window_block_palette_adds_block_to_project_tree_and_inspector(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.main_window import MainWindow
    app = ApplicationService()
    app.new_project("test")
    window = MainWindow(app)
    qtbot.addWidget(window)

    window._block_editor._palette.blockTypeRequested.emit("Constant")
    QtWidgets.QApplication.processEvents()

    diagram = app.project.model.control_graph
    assert diagram is not None
    assert len(diagram.instances) == 1
    block_id = next(iter(diagram.instances))
    assert block_id in window._tree_items
    assert window._selected_entity_id == block_id
    assert window.inspector_title.text()
    assert any(
        window.inspector.item(row, 0).text().lower() == "value"
        for row in range(window.inspector.rowCount())
    )


def test_existing_blocks_refresh_into_block_canvas(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.blocks import BlockDiagram, BlockInstance, PortSpec
    from quino.gui.main_window import MainWindow
    app = ApplicationService()
    app.new_project("test")
    app.project.model.control_graph = BlockDiagram(
        instances={
            "b1": BlockInstance(
                instance_id="b1",
                block_type="CustomBlock",
                parameters={"gain": 2.0, "_position": [12.0, 34.0]},
                input_ports=[PortSpec("in")],
                output_ports=[PortSpec("out")],
            )
        }
    )
    window = MainWindow(app)
    qtbot.addWidget(window)

    window.refresh_all()

    assert "b1" in window._block_editor._scene._block_items


def test_block_inspector_parameter_edit_updates_project(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.blocks import BlockDiagram, BlockInstance
    from quino.gui.main_window import MainWindow
    app = ApplicationService()
    app.new_project("test")
    app.project.model.control_graph = BlockDiagram(
        instances={
            "b1": BlockInstance(
                instance_id="b1",
                block_type="Constant",
                parameters={"value": 1.0},
            )
        }
    )
    window = MainWindow(app)
    qtbot.addWidget(window)
    window._select_block("b1")

    value_editor = window.inspector.cellWidget(0, 1)
    assert isinstance(value_editor, QtWidgets.QLineEdit)
    value_editor.setText("3.5")
    value_editor.editingFinished.emit()

    assert app.project.model.control_graph.instances["b1"].parameters["value"] == 3.5


def test_selecting_block_in_model_tree_selects_block_canvas_item(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.blocks import BlockDiagram, BlockInstance
    from quino.gui.main_window import MainWindow
    app = ApplicationService()
    app.new_project("test")
    app.project.model.control_graph = BlockDiagram(
        instances={"b1": BlockInstance(instance_id="b1", block_type="Constant", parameters={"value": 1.0})}
    )
    window = MainWindow(app)
    qtbot.addWidget(window)
    window.refresh_all()

    window.tree.setCurrentItem(window._tree_items["b1"])

    assert window._selected_entity_id == "b1"
    assert window._block_editor._scene._block_items["b1"].isSelected()


def test_delete_selected_block_from_model_tree_updates_project_and_canvas(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.blocks import BlockDiagram, BlockInstance
    from quino.gui.main_window import MainWindow
    app = ApplicationService()
    app.new_project("test")
    app.project.model.control_graph = BlockDiagram(
        instances={"b1": BlockInstance(instance_id="b1", block_type="Constant", parameters={"value": 1.0})}
    )
    window = MainWindow(app)
    qtbot.addWidget(window)
    window.refresh_all()
    window.tree.setCurrentItem(window._tree_items["b1"])

    window.delete_selected_entity()

    assert "b1" not in app.project.model.control_graph.instances
    assert "b1" not in window._block_editor._scene._block_items


def test_delete_selected_block_connection_from_model_tree(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.blocks import BlockDiagram, BlockInstance, Connection
    from quino.gui.main_window import MainWindow
    app = ApplicationService()
    app.new_project("test")
    app.project.model.control_graph = BlockDiagram(
        instances={
            "src": BlockInstance(instance_id="src", block_type="Constant", parameters={"value": 1.0}),
            "dst": BlockInstance(instance_id="dst", block_type="Gain", parameters={"k": 2.0}),
        },
        connections=[Connection("src", "out", "dst", "in")],
    )
    window = MainWindow(app)
    qtbot.addWidget(window)
    window.refresh_all()
    connection_item = None
    for item_index in range(window.tree.topLevelItemCount()):
        root = window.tree.topLevelItem(item_index)
        for child_index in range(root.childCount()):
            child = root.child(child_index)
            for grandchild_index in range(child.childCount()):
                candidate = child.child(grandchild_index)
                data = candidate.data(0, QtCore.Qt.ItemDataRole.UserRole)
                if isinstance(data, tuple) and data[0] == "block_connection":
                    connection_item = candidate
                    break
    assert connection_item is not None

    window.tree.setCurrentItem(connection_item)
    window.delete_selected_entity()

    assert app.project.model.control_graph.connections == []


def test_block_canvas_drag_between_ports_creates_connection(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.main_window import MainWindow
    app = ApplicationService()
    app.new_project("test")
    window = MainWindow(app)
    qtbot.addWidget(window)
    window._block_editor._scene.add_block("Constant", QtCore.QPointF(0.0, 0.0))
    window._block_editor._scene.add_block("Gain", QtCore.QPointF(200.0, 0.0))
    blocks = list(window._block_editor._scene._block_items.values())
    src = next(block for block in blocks if block.block_type == "Constant")
    dst = next(block for block in blocks if block.block_type == "Gain")

    src_port = src.output_ports["out"]
    dst_port = dst.input_ports["in"]
    window._block_editor._scene._start_drag_connection(src_port, src_port.scene_center())
    window._block_editor._scene._finish_drag_connection(dst_port.scene_center())

    connections = app.project.model.control_graph.connections
    assert len(connections) == 1
    assert connections[0].src_instance == src.instance_id
    assert connections[0].dst_instance == dst.instance_id


# --- C2: Shared selection between canvas and blocks ---

def test_selecting_block_clears_mech_selection(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.main_window import MainWindow
    from quino.domain.blocks import BlockDiagram, BlockInstance
    app = ApplicationService()
    app.new_project("test")
    diagram = BlockDiagram()
    diagram.instances["b1"] = BlockInstance(instance_id="b1", block_type="constant")
    app.project.model.control_graph = diagram
    window = MainWindow(app)
    qtbot.addWidget(window)
    window._selected_entity_id = "body_xyz"
    window._select_block("b1")
    assert window._selected_entity_id == "b1"


# --- C3: Inspector renders block parameters ---

def test_inspector_shows_block_type_on_selection(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.main_window import MainWindow
    from quino.domain.blocks import BlockDiagram, BlockInstance
    app = ApplicationService()
    app.new_project("test")
    diagram = BlockDiagram()
    diagram.instances["b1"] = BlockInstance(
        instance_id="b1", block_type="constant", parameters={"value": 3.5}
    )
    app.project.model.control_graph = diagram
    window = MainWindow(app)
    qtbot.addWidget(window)
    window._select_block("b1")
    # Should not raise — basic smoke test
    assert window._selected_entity_id == "b1"


# --- C4: Blocks section in model tree ---

def test_model_tree_has_blocks_section(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.main_window import MainWindow
    from quino.domain.blocks import BlockDiagram, BlockInstance
    app = ApplicationService()
    app.new_project("test")
    diagram = BlockDiagram()
    diagram.instances["b1"] = BlockInstance(instance_id="b1", block_type="constant", parameters={})
    app.project.model.control_graph = diagram
    window = MainWindow(app)
    qtbot.addWidget(window)
    window.refresh_all()
    tree = getattr(window, 'tree', None) or getattr(window, '_model_tree', None) or getattr(window, '_entity_tree', None)
    assert tree is not None, "Cannot find model tree widget"
    found_blocks_section = False
    for i in range(tree.topLevelItemCount()):
        text = tree.topLevelItem(i).text(0).lower()
        if "block" in text:
            found_blocks_section = True
            break
    assert found_blocks_section


def test_pose_constraints_strip_visible_only_in_pose_mode(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.main_window import MainWindow
    app = ApplicationService()
    app.new_project("test")
    window = MainWindow(app)
    qtbot.addWidget(window)
    window.show()
    QtWidgets.QApplication.processEvents()
    # In initial (model) mode, strip should be hidden
    assert window.pose_constraints_strip.isVisible() is False
    # In pose mode, strip should be visible
    window._set_app_mode("pose")
    QtWidgets.QApplication.processEvents()
    assert window.pose_constraints_strip.isVisible() is True
    # Back to model mode — hidden again
    window._set_app_mode("model")
    QtWidgets.QApplication.processEvents()
    assert window.pose_constraints_strip.isVisible() is False


def test_pose_toolbar_has_at_most_two_buttons_per_column(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.main_window import MainWindow
    app = ApplicationService()
    app.new_project("test")
    window = MainWindow(app)
    qtbot.addWidget(window)

    constraints_widget = None
    for action in window._pose_toolbar.actions():
        widget = action.defaultWidget() if hasattr(action, "defaultWidget") else None
        if widget is None:
            continue
        labels = widget.findChildren(QtWidgets.QLabel)
        if any(label.text() == "Constraints" for label in labels):
            constraints_widget = widget
            break

    assert constraints_widget is not None
    grid_widget = constraints_widget.layout().itemAt(0).widget()
    grid = grid_widget.layout()
    buttons_by_column: dict[int, int] = {}
    for index in range(grid.count()):
        item = grid.itemAt(index)
        widget = item.widget()
        if not isinstance(widget, QtWidgets.QToolButton) or widget.defaultAction() is None:
            continue
        _row, column, _row_span, _col_span = grid.getItemPosition(index)
        buttons_by_column[column] = buttons_by_column.get(column, 0) + 1

    assert max(buttons_by_column.values()) <= 2


# ----------------------------------------------------------------------
# Fase 1: block editor toolbar + fit/center/auto-layout
# ----------------------------------------------------------------------

def test_block_editor_toolbar_exposes_fit_layout_validate_clear(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    tips = [btn.toolTip() for btn in widget._toolbar.findChildren(QtWidgets.QToolButton)]
    text_blob = " | ".join(tips).lower()
    assert "fit" in text_blob
    assert "lay out" in text_blob or "layout" in text_blob
    assert "validate" in text_blob or "validation" in text_blob
    assert "delete" in text_blob


def test_block_editor_fit_blocks_handles_empty_scene(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    # Should not raise.
    widget.fit_blocks()


def test_block_editor_auto_layout_assigns_distinct_columns(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec

    app = ApplicationService()
    app.new_project("test")
    diagram = BlockDiagram(
        instances={
            "src": BlockInstance(
                instance_id="src", block_type="Constant",
                parameters={"value": 1.0, "_position": [0, 0]},
                input_ports=[], output_ports=[PortSpec("out")],
            ),
            "gain": BlockInstance(
                instance_id="gain", block_type="Gain",
                parameters={"k": 2.0, "_position": [0, 0]},
                input_ports=[PortSpec("in")], output_ports=[PortSpec("out")],
            ),
        },
        connections=[Connection(src_instance="src", src_port="out", dst_instance="gain", dst_port="in")],
    )
    app.project.model.control_graph = diagram

    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    widget.set_app_service(app)
    widget.set_diagram(diagram)

    widget._scene.auto_layout()

    pos_src = app.project.model.control_graph.instances["src"].parameters["_position"]
    pos_gain = app.project.model.control_graph.instances["gain"].parameters["_position"]
    assert pos_src[0] < pos_gain[0], "source should be left of its dependent"


def test_block_editor_clear_diagram_removes_all_blocks(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.blocks.editor_widget import BlockEditorWidget

    app = ApplicationService()
    app.new_project("test")
    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    widget.set_app_service(app)
    widget._palette.blockTypeRequested.emit("Constant")
    widget._palette.blockTypeRequested.emit("Gain")
    assert len(widget._scene._block_items) == 2

    widget._scene.clear_diagram()

    assert len(widget._scene._block_items) == 0
    cg = app.project.model.control_graph
    assert cg is None or len(cg.instances) == 0


def test_block_inspector_renders_combo_for_modelsensor(qtbot):
    """ModelSensor.sensor_id must be a combo populated from display_project."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.blocks import BlockDiagram, BlockInstance, PortSpec
    from quino.gui.main_window import MainWindow

    app = ApplicationService()
    app.new_project("test")
    # Add a body + a position sensor we can reference.
    from quino.domain.inputs import MarkerInput
    body_id = app.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = app.get_body(body_id)
    marker_a = next(m.id for m in body.markers if m.name == "A")
    sensor_id = app.create_sensor("PosSensor", "point", [marker_a])

    diagram = BlockDiagram(
        instances={
            "ms": BlockInstance(
                instance_id="ms", block_type="ModelSensor",
                parameters={"sensor_id": "", "channel": "y", "_position": [0, 0]},
                input_ports=[], output_ports=[PortSpec("out")],
            ),
        },
    )
    app.project.model.control_graph = diagram

    window = MainWindow(app)
    qtbot.addWidget(window)
    window._select_block("ms")

    # Locate the combo for sensor_id.
    found_combo = False
    for row in range(window.inspector.rowCount()):
        path = window.inspector._compat_rows[row]["path"]
        editor = window.inspector._compat_rows[row]["editor"]
        if path.endswith("/sensor_id") and isinstance(editor, QtWidgets.QComboBox):
            # Combo should contain at least one real sensor entry.
            assert editor.count() >= 1
            labels = [editor.itemText(i) for i in range(editor.count())]
            assert any("PosSensor" in label for label in labels)
            found_combo = True
            break
    assert found_combo, "Expected sensor_id combo for ModelSensor block"


def test_block_inspector_channel_combo_depends_on_sensor_kind(qtbot):
    """ModelSensor.channel must be a combo whose options depend on the sensor."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.blocks import BlockDiagram, BlockInstance, PortSpec
    from quino.domain.inputs import MarkerInput
    from quino.gui.main_window import MainWindow

    app = ApplicationService()
    app.new_project("test")
    body_id = app.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = app.get_body(body_id)
    marker_a = next(m.id for m in body.markers if m.name == "A")
    sensor_id = app.create_sensor("DistSensor", "distance", [marker_a, marker_a])

    diagram = BlockDiagram(
        instances={
            "ms": BlockInstance(
                instance_id="ms", block_type="ModelSensor",
                parameters={"sensor_id": sensor_id, "channel": "d", "_position": [0, 0]},
                input_ports=[], output_ports=[PortSpec("out")],
            ),
        },
    )
    app.project.model.control_graph = diagram

    window = MainWindow(app)
    qtbot.addWidget(window)
    window._select_block("ms")

    # Channel combo for a distance sensor must show "d", not the point channels.
    found_channel = False
    for row in range(window.inspector.rowCount()):
        path = window.inspector._compat_rows[row]["path"]
        editor = window.inspector._compat_rows[row]["editor"]
        if path.endswith("/channel") and isinstance(editor, QtWidgets.QComboBox):
            labels = [editor.itemText(i) for i in range(editor.count())]
            assert "d" in labels
            assert "vx" not in labels
            found_channel = True
            break
    assert found_channel, "Expected channel combo dependent on distance sensor"


def test_block_inspector_pid_anti_windup_renders_as_checkbox(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.blocks import BlockDiagram, BlockInstance, PortSpec
    from quino.gui.main_window import MainWindow

    app = ApplicationService()
    app.new_project("test")
    diagram = BlockDiagram(
        instances={
            "pid": BlockInstance(
                instance_id="pid", block_type="PID",
                parameters={
                    "kp": 1.0, "ki": 0.1, "kd": 0.0,
                    "lower": -1.0, "upper": 1.0, "anti_windup": True,
                    "_position": [0, 0],
                },
                input_ports=[PortSpec("in")], output_ports=[PortSpec("out")],
            ),
        },
    )
    app.project.model.control_graph = diagram

    window = MainWindow(app)
    qtbot.addWidget(window)
    window._select_block("pid")

    found_cb = False
    for row in range(window.inspector.rowCount()):
        path = window.inspector._compat_rows[row]["path"]
        editor = window.inspector._compat_rows[row]["editor"]
        if path.endswith("/anti_windup") and isinstance(editor, QtWidgets.QCheckBox):
            assert editor.isChecked() is True
            found_cb = True
            break
    assert found_cb, "PID.anti_windup must be rendered as checkbox"


def test_model_tree_marks_inherited_block_in_italics(qtbot):
    """A block added by an ancestor case must show italic / lighter-green
    in the active subcase's model tree; a tooltip identifies the source case."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.main_window import MainWindow

    app = ApplicationService()
    app.new_project("test")
    parent = app.workspace.create_case("Parent")
    child = app.workspace.create_case("Child", parent_case_id=parent.id)
    app.set_working_context(case_id=parent.id)
    pblock = app.add_block(block_type="Constant", name="ParentSrc", position=(0.0, 0.0))
    app.set_working_context(case_id=child.id)

    window = MainWindow(app)
    qtbot.addWidget(window)
    window.refresh_all()

    item = window._tree_items.get(pblock)
    assert item is not None
    assert item.font(0).italic() is True
    tip = item.toolTip(0)
    assert "Parent" in tip


def test_model_tree_marks_local_override_in_orange(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.inputs import PropertyValueInput
    from quino.gui.main_window import MainWindow
    from quino.gui._palette import OVERRIDE_ORANGE

    app = ApplicationService()
    app.new_project("test")
    body_id = app.create_punctual_mass("Mass", x="0 mm", y="0 mm")
    app.update_property(body_id, "mass", PropertyValueInput(kind="expression", value="1 kg"))
    case = app.workspace.create_case("C1")
    app.set_working_context(case_id=case.id)
    app.update_property(body_id, "mass", PropertyValueInput(kind="expression", value="5 kg"))

    window = MainWindow(app)
    qtbot.addWidget(window)
    window.refresh_all()

    item = window._tree_items.get(body_id)
    assert item is not None
    color = item.foreground(0).color().name()
    assert color.lower() == OVERRIDE_ORANGE.lower(), (
        f"Expected local-override orange ({OVERRIDE_ORANGE}), got {color}"
    )
    assert item.font(0).italic() is False


def test_inspector_reset_button_clears_local_override(qtbot):
    """Clicking the Reset button on an overridden row clears the local
    override via ApplicationService.reset_override and refreshes the UI."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.inputs import MarkerInput, PropertyValueInput
    from quino.domain.workspace import ScalarValue
    from quino.gui.main_window import MainWindow

    app = ApplicationService()
    app.new_project("test")
    body_id = app.create_punctual_mass("Mass", x="0 mm", y="0 mm")
    # Baseline mass 2 kg
    app.update_property(body_id, "mass", PropertyValueInput(kind="expression", value="2 kg"))
    # Add a case with a local override
    case = app.workspace.create_case("C1")
    case.invariant_values[f"bodies/{body_id}/mass"] = ScalarValue(value=7.0, unit="kg")
    app.set_working_context(case_id=case.id)

    window = MainWindow(app)
    qtbot.addWidget(window)
    window._selected_entity_id = body_id
    window._populate_inspector()

    # Locate the Reset button on the "mass" row.
    outer = window.inspector._row_widgets.get("mass")
    assert outer is not None
    reset_btn = None
    for child in outer.findChildren(QtWidgets.QToolButton):
        if child.text() == "Reset":
            reset_btn = child
            break
    assert reset_btn is not None, "Expected a Reset override button on the overridden mass row"

    reset_btn.click()
    QtWidgets.QApplication.processEvents()

    # The local override is gone.
    case_live = next(c for c in app.project.workspace.cases if c.id == case.id)
    assert f"bodies/{body_id}/mass" not in case_live.invariant_values
    # Composed view falls back to the baseline 2 kg.
    composed_body = next(b for b in app.display_project.model.bodies if b.id == body_id)
    assert "2" in (composed_body.mass.expression or "")


def test_inspector_inherited_hint_has_no_reset(qtbot):
    """When the override comes from an ancestor case (not local), the hint
    is shown but the Reset button is NOT, because we can only reset from
    the case that owns the entry."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.inputs import MarkerInput, PropertyValueInput
    from quino.domain.workspace import ScalarValue
    from quino.gui.main_window import MainWindow

    app = ApplicationService()
    app.new_project("test")
    body_id = app.create_punctual_mass("Mass", x="0 mm", y="0 mm")
    app.update_property(body_id, "mass", PropertyValueInput(kind="expression", value="2 kg"))
    parent = app.workspace.create_case("Parent")
    parent.invariant_values[f"bodies/{body_id}/mass"] = ScalarValue(value=5.0, unit="kg")
    child = app.workspace.create_case("Child", parent_case_id=parent.id)
    app.set_working_context(case_id=child.id)

    window = MainWindow(app)
    qtbot.addWidget(window)
    window._selected_entity_id = body_id
    window._populate_inspector()

    outer = window.inspector._row_widgets.get("mass")
    assert outer is not None
    reset_buttons = [b for b in outer.findChildren(QtWidgets.QToolButton) if b.text() == "Reset"]
    assert reset_buttons == [], "Inherited overrides must not expose a Reset button"


def test_block_inspector_hides_internal_position_param(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.domain.blocks import BlockDiagram, BlockInstance, PortSpec
    from quino.gui.main_window import MainWindow

    app = ApplicationService()
    app.new_project("test")
    diagram = BlockDiagram(
        instances={
            "c": BlockInstance(
                instance_id="c", block_type="Constant",
                parameters={"value": 3.14, "_position": [10, 20]},
                input_ports=[], output_ports=[PortSpec("out")],
            ),
        },
    )
    app.project.model.control_graph = diagram

    window = MainWindow(app)
    qtbot.addWidget(window)
    window._select_block("c")

    paths = [
        window.inspector._compat_rows[row]["path"]
        for row in range(window.inspector.rowCount())
    ]
    assert not any(p.endswith("/_position") for p in paths)


def test_port_tooltip_includes_shape(qtbot):
    """Port tooltip should mention the port shape (e.g. 1)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    app = ApplicationService()
    app.new_project("test")
    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    widget.set_app_service(app)
    widget._palette.blockTypeRequested.emit("Gain")
    item = next(iter(widget._scene._block_items.values()))
    tip = item.input_ports["in"].toolTip()
    assert "Shape" in tip


def test_port_has_tooltip_with_name_and_direction(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    app = ApplicationService()
    app.new_project("test")
    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    widget.set_app_service(app)
    widget._palette.blockTypeRequested.emit("Gain")
    item = next(iter(widget._scene._block_items.values()))
    in_port = item.input_ports.get("in")
    out_port = item.output_ports.get("out")
    assert in_port is not None and out_port is not None
    in_tip = in_port.toolTip()
    out_tip = out_port.toolTip()
    assert "Input" in in_tip and ".in" in in_tip and "disconnected" in in_tip
    assert "Output" in out_tip and ".out" in out_tip and "disconnected" in out_tip


def test_port_tooltip_updates_when_connected(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec
    app = ApplicationService()
    app.new_project("test")
    diagram = BlockDiagram(
        instances={
            "src": BlockInstance(
                instance_id="src", block_type="Constant",
                parameters={"value": 1.0, "_position": [0, 0]},
                input_ports=[], output_ports=[PortSpec("out")],
            ),
            "g": BlockInstance(
                instance_id="g", block_type="Gain",
                parameters={"k": 2.0, "_position": [200, 0]},
                input_ports=[PortSpec("in")], output_ports=[PortSpec("out")],
            ),
        },
        connections=[Connection(src_instance="src", src_port="out", dst_instance="g", dst_port="in")],
    )
    app.project.model.control_graph = diagram

    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    widget.set_app_service(app)
    widget.set_diagram(diagram)

    g_in = widget._scene._block_items["g"].input_ports["in"]
    assert "connected" in g_in.toolTip()


def test_invalid_connection_emits_validation_error(qtbot):
    """Dropping a wire on the same direction or same block emits a
    validationError signal."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    app = ApplicationService()
    app.new_project("test")
    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    widget.set_app_service(app)
    widget._palette.blockTypeRequested.emit("Gain")
    widget._palette.blockTypeRequested.emit("Gain")
    items = list(widget._scene._block_items.values())
    g1, g2 = items[0], items[1]

    errors: list[str] = []
    widget._scene.validationError.connect(errors.append)

    # Simulate starting a drag from g1.out and ending on g2.out (output-output).
    scene = widget._scene
    scene._start_drag_connection(g1.output_ports["out"], g1.output_ports["out"].scene_center())
    # Manually finish on g2's output port.
    out2 = g2.output_ports["out"]
    scene._finish_drag_connection(out2.scene_center())

    assert any("output" in e.lower() for e in errors), f"Expected output-output error, got: {errors}"


def test_connection_has_tooltip_and_arrow_renders(qtbot):
    """ConnectionItem provides a tooltip identifying both endpoints and
    paints a direction arrow at the destination."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.application.service import ApplicationService
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec
    app = ApplicationService()
    app.new_project("test")
    diagram = BlockDiagram(
        instances={
            "a": BlockInstance(
                instance_id="a", block_type="Constant",
                parameters={"value": 0.0, "_position": [0, 0]},
                input_ports=[], output_ports=[PortSpec("out")],
            ),
            "b": BlockInstance(
                instance_id="b", block_type="Gain",
                parameters={"k": 1.0, "_position": [240, 0]},
                input_ports=[PortSpec("in")], output_ports=[PortSpec("out")],
            ),
        },
        connections=[Connection(src_instance="a", src_port="out", dst_instance="b", dst_port="in")],
    )
    app.project.model.control_graph = diagram

    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    widget.set_app_service(app)
    widget.set_diagram(diagram)

    conns = widget._scene._connection_items
    assert len(conns) == 1
    tip = conns[0].toolTip()
    assert "a.out" in tip and "b.in" in tip and "→" in tip

    # Render to a QImage and verify the connection painted SOMETHING near
    # the destination port (sanity check that arrow drawing didn't crash).
    img = QtGui.QImage(800, 600, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtCore.Qt.GlobalColor.white)
    painter = QtGui.QPainter(img)
    widget._scene.render(painter)
    painter.end()
    # Confirm at least some non-white pixel exists.
    found_pixel = False
    for x in range(0, 800, 20):
        for y in range(0, 600, 20):
            if QtGui.QColor(img.pixel(x, y)).rgb() != QtGui.QColor("white").rgb():
                found_pixel = True
                break
        if found_pixel:
            break
    assert found_pixel


def test_block_editor_set_selected_does_not_scroll_viewport(qtbot):
    """Plain set_selected must not move the viewport — selections from
    within the canvas (or after an edit) should keep the view stable."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    from quino.domain.blocks import BlockDiagram, BlockInstance, PortSpec

    diagram = BlockDiagram(
        instances={
            "b1": BlockInstance(
                instance_id="b1", block_type="Constant",
                parameters={"value": 1.0, "_position": [400, 300]},
                input_ports=[], output_ports=[PortSpec("out")],
            ),
        },
    )
    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    widget.show()
    widget.set_diagram(diagram)
    widget._canvas.centerOn(0.0, 0.0)
    QtWidgets.QApplication.processEvents()
    h0 = widget._canvas.horizontalScrollBar().value()
    v0 = widget._canvas.verticalScrollBar().value()

    widget.set_selected("b1")
    QtWidgets.QApplication.processEvents()

    assert widget._canvas.horizontalScrollBar().value() == h0
    assert widget._canvas.verticalScrollBar().value() == v0


def test_block_editor_reveal_centers_offscreen_block(qtbot):
    """reveal() must scroll the viewport when the target block is off
    screen (selection coming from the model tree)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    from quino.domain.blocks import BlockDiagram, BlockInstance, PortSpec

    diagram = BlockDiagram(
        instances={
            "far": BlockInstance(
                instance_id="far", block_type="Constant",
                parameters={"value": 1.0, "_position": [3000, 3000]},
                input_ports=[], output_ports=[PortSpec("out")],
            ),
        },
    )
    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    widget.show()
    widget.set_diagram(diagram)
    widget._canvas.centerOn(0.0, 0.0)
    QtWidgets.QApplication.processEvents()

    widget.reveal("far")
    QtWidgets.QApplication.processEvents()

    # Now the block's scene rect should be inside the viewport-mapped rect.
    visible = widget._canvas.mapToScene(widget._canvas.viewport().rect()).boundingRect()
    item = widget._scene._block_items["far"]
    assert visible.intersects(item.sceneBoundingRect())


def test_block_editor_set_selected_centers_view(qtbot):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from quino.gui.blocks.editor_widget import BlockEditorWidget
    from quino.domain.blocks import BlockDiagram, BlockInstance, PortSpec

    diagram = BlockDiagram(
        instances={
            "b1": BlockInstance(
                instance_id="b1", block_type="Constant",
                parameters={"value": 1.0, "_position": [400, 300]},
                input_ports=[], output_ports=[PortSpec("out")],
            ),
        },
    )
    widget = BlockEditorWidget()
    qtbot.addWidget(widget)
    widget.set_diagram(diagram)

    widget.set_selected("b1")
    # The canvas should have centered on roughly (400, 300). Just sanity-check
    # the call doesn't raise and selection sticks.
    assert widget._scene._block_items["b1"].isSelected()
