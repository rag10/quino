from __future__ import annotations

from PySide6 import QtCore, QtTest, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput, SliderInput
from quino.gui.main_window import MainWindow


def _expr_value(expression: str) -> float:
    return float(expression.split()[0])


def test_main_window_loads_examples_and_runs_validation() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(ApplicationService())

    window.load_four_bar_example()

    assert window.app_service.project is not None
    assert window.app_service.project.name == "Four Bar"
    assert window.tree.topLevelItemCount() == 4
    assert "Bodies: 3" in window.canvas_summary.toPlainText()
    assert window.canvas is not None
    assert not window.canvas.grab().isNull()

    window.validate_model()

    assert "Validation report:" in window.messages.toPlainText()
    assert "Validation report:" in window.validation_view.toPlainText()
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
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        staticmethod(lambda *args, **kwargs: ("45 deg * t / 1 s", True)),
    )
    window.canvas._edit_driver_law_dialog(driver_id)
    assert window.app_service._find_entity(driver_id).law.expression == "45 deg * t / 1 s"

    window.close()
    qt_app.processEvents()
