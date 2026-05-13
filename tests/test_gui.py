from __future__ import annotations

import json

import pytest
from PySide6 import QtCore, QtTest, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput, PropertyValueInput, SliderInput
from quino.gui.main_window import MainWindow


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
    assert window.tree.topLevelItemCount() == 7
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
    assert not window._mode_sim_btn.isChecked()
    assert window._model_toolbar.isVisible()
    assert not window._sketch_toolbar.isVisible()
    assert not window._sim_toolbar.isVisible()

    # Switch to Sketch mode
    window._set_app_mode("sketch")
    qt_app.processEvents()
    assert window._app_mode == "sketch"
    assert window._mode_sketch_btn.isChecked()
    assert not window._mode_model_btn.isChecked()
    assert not window._mode_sim_btn.isChecked()
    assert window._sketch_toolbar.isVisible()
    assert not window._model_toolbar.isVisible()
    assert not window._sim_toolbar.isVisible()
    assert window.app_service.project.sketch is not None
    assert window.app_service.project.sketch.visible is True

    # Switch to Sim mode
    window._set_app_mode("sim")
    qt_app.processEvents()
    assert window._app_mode == "sim"
    assert window._mode_sim_btn.isChecked()
    assert not window._mode_sketch_btn.isChecked()
    assert not window._mode_model_btn.isChecked()
    assert window._sim_toolbar.isVisible()
    assert not window._sketch_toolbar.isVisible()
    assert not window._model_toolbar.isVisible()
    assert hasattr(window, "action_export_script")
    assert window.action_export_script.isEnabled()  # Exudyn is the default backend

    # Switch back to Model mode
    window._set_app_mode("model")
    qt_app.processEvents()
    assert window._app_mode == "model"
    assert window._mode_model_btn.isChecked()
    assert not window._mode_sketch_btn.isChecked()
    assert not window._mode_sim_btn.isChecked()
    assert window._model_toolbar.isVisible()
    assert not window._sketch_toolbar.isVisible()
    assert not window._sim_toolbar.isVisible()

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


def test_mode_selector_is_overlaid_on_canvas() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())
    window.show()
    qt_app.processEvents()

    assert window._mode_model_btn.parentWidget().objectName() == "modeSelectorOverlay"
    assert window._mode_model_btn.parentWidget().parentWidget() is window._canvas_stack
    assert window._mode_model_btn.parentWidget().pos() == QtCore.QPoint(12, 12)

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

    # Change background color directly
    window.canvas.set_background_color("#ffffff")
    qt_app.processEvents()
    assert window.canvas.background_color() == "#ffffff"

    # Preferences dialog exists and can be invoked
    assert window.action_preferences is not None

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
