from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.inputs import JointEndpointInput, MarkerInput, PropertyValueInput
from quino.domain.model import Body, Project, Slider
from quino.domain.types import DriverType, JointEndpointKind, JointType, MarkerType
from quino.simulation.assembler import AssembledMechanism


@dataclass(slots=True)
class CanvasMarker:
    entity_id: str
    body_id: str
    name: str
    x: float
    y: float
    marker_type: MarkerType
    visible: bool


@dataclass(slots=True)
class CanvasSlider:
    entity_id: str
    name: str
    origin_x: float
    origin_y: float
    angle: float
    travel_min: float
    travel_max: float


class CanvasMode:
    SELECT = "select"
    CREATE_BAR = "create_bar"
    CREATE_BODY = "create_body"
    ADD_MARKER = "add_marker"
    CREATE_REVOLUTE = "create_revolute"
    CREATE_RIGID = "create_rigid"
    CREATE_SLIDER = "create_slider"
    CONNECT_GROUND = "connect_ground"
    CONNECT_SLIDER = "connect_slider"


class MechanismCanvas(QtWidgets.QWidget):
    entitySelected = QtCore.Signal(str)
    modelChanged = QtCore.Signal(str)

    def __init__(self, app_service: ApplicationService, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.app_service = app_service
        self._selected_entity_id: str | None = None
        self._state_overlay: dict[str, float] | None = None
        self._screen_markers: list[tuple[CanvasMarker, QtCore.QPointF]] = []
        self._screen_sliders: list[tuple[CanvasSlider, QtCore.QLineF, QtCore.QPointF]] = []
        self._screen_slider_handles: list[tuple[str, str, QtCore.QPointF]] = []
        self._screen_joints: list[tuple[str, QtCore.QPointF]] = []
        self._screen_drivers: list[tuple[str, QtCore.QPointF]] = []
        self._mode = CanvasMode.SELECT
        self._editing_enabled = True
        self._creation_points: list[tuple[float, float]] = []
        self._joint_start_marker: CanvasMarker | None = None
        self._slider_start_marker: CanvasMarker | None = None
        self._hover_world: tuple[float, float] | None = None
        self._dragging_marker: CanvasMarker | None = None
        self._drag_preview: tuple[str, float, float] | None = None
        self._dragging_slider: tuple[str, str] | None = None
        self._dragging_slider_preview: dict[str, float] | None = None
        self._view_scale: float | None = None
        self._view_center_x = 0.0
        self._view_center_y = 0.0
        self._panning = False
        self._pan_last_screen: QtCore.QPointF | None = None
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._creation_points.clear()
        self._joint_start_marker = None
        self._slider_start_marker = None
        self._hover_world = None
        self._dragging_marker = None
        self._drag_preview = None
        self._dragging_slider = None
        self._dragging_slider_preview = None
        self.update()

    def fit_view(self) -> None:
        transform = self._fit_transform()
        self._view_scale, self._view_center_x, self._view_center_y = transform
        self._sync_view_state()
        self.update()

    def set_selection(self, entity_id: str | None) -> None:
        self._selected_entity_id = entity_id
        self.update()

    def set_state_overlay(self, state: dict[str, float] | None) -> None:
        self._state_overlay = state
        self.update()

    def set_editing_enabled(self, enabled: bool) -> None:
        self._editing_enabled = enabled
        if not enabled:
            self._creation_points.clear()
            self._joint_start_marker = None
            self._slider_start_marker = None
            self._dragging_marker = None
            self._drag_preview = None
            self._dragging_slider = None
            self._dragging_slider_preview = None
        self.update()

    def screen_position_for_world(self, x: float, y: float) -> QtCore.QPoint:
        point = self._to_screen(x, y, self._current_transform())
        return QtCore.QPoint(int(round(point.x())), int(round(point.y())))

    def screen_position_for_entity(self, entity_id: str) -> QtCore.QPoint | None:
        project = self.app_service.project
        if project is None:
            return None
        assembled = self._assembled_mechanism(project)
        markers = self._collect_markers(project, assembled)
        for marker in markers:
            if marker.entity_id == entity_id:
                return self.screen_position_for_world(marker.x, marker.y)
        sliders = self._collect_sliders(project)
        for slider in sliders:
            if slider.entity_id == entity_id:
                return self.screen_position_for_world(slider.origin_x, slider.origin_y)
        marker_map = {marker.entity_id: marker for marker in markers}
        slider_map = {slider.entity_id: slider for slider in sliders}
        for joint in project.model.joints:
            if joint.id == entity_id:
                position = self._joint_world_position(joint, marker_map, slider_map)
                if position is not None:
                    return self.screen_position_for_world(position[0], position[1])
        for driver in project.model.drivers:
            if driver.id == entity_id:
                joint = self.app_service._find_joint(driver.target_joint_id)
                position = self._joint_world_position(joint, marker_map, slider_map)
                if position is not None:
                    return self.screen_position_for_world(position[0], position[1])
        return None

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QtGui.QColor("#f5f1e8"))

        project = self.app_service.project
        transform = self._current_transform()
        if project is None or not project.model.bodies:
            self._draw_grid(painter, transform)
            self._draw_empty_state(painter)
            self._draw_creation_overlay(painter, transform)
            return

        assembled = self._assembled_mechanism(project)
        markers = self._collect_markers(project, assembled)
        sliders = self._collect_sliders(project)
        self._draw_grid(painter, transform)
        self._draw_sliders(painter, sliders, transform)
        self._draw_bodies(painter, project, markers, transform)
        self._draw_joints(painter, project, markers, sliders, transform)
        self._draw_drivers(painter, project, markers, sliders, transform)
        self._draw_markers(painter, markers, transform)
        self._draw_creation_overlay(painter, transform)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # pragma: no cover - UI behavior
        super().resizeEvent(event)
        if self._view_scale is None:
            self.fit_view()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        transform = self._current_transform()
        world_before = self._to_world(event.position(), transform)
        scale_factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self._view_scale = max(0.1, min(transform[0] * scale_factor, 500.0))
        self._view_center_x = world_before[0] - (event.position().x() - self.width() * 0.5) / self._view_scale
        self._view_center_y = world_before[1] + (event.position().y() - self.height() * 0.5) / self._view_scale
        self._sync_view_state()
        self.update()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        if event.button() in {QtCore.Qt.MouseButton.MiddleButton, QtCore.Qt.MouseButton.RightButton}:
            self._panning = True
            self._pan_last_screen = event.position()
            return
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setFocus()
        clicked = event.position()
        clicked_marker = self._marker_at(clicked)
        clicked_slider = self._slider_at(clicked)
        clicked_slider_handle = self._slider_handle_at(clicked)
        clicked_joint = self._joint_at(clicked)
        clicked_driver = self._driver_at(clicked)
        world = self._to_world(clicked, self._current_transform())

        if self._mode == CanvasMode.SELECT:
            if clicked_marker is not None:
                self._selected_entity_id = clicked_marker.entity_id
                self.entitySelected.emit(clicked_marker.entity_id)
                if self._editing_enabled:
                    self._dragging_marker = clicked_marker
                    self._drag_preview = (clicked_marker.entity_id, clicked_marker.x, clicked_marker.y)
                self.update()
                return
            if clicked_slider is not None:
                self._selected_entity_id = clicked_slider.entity_id
                self.entitySelected.emit(clicked_slider.entity_id)
                if self._editing_enabled:
                    handle = clicked_slider_handle or (clicked_slider.entity_id, "center")
                    self._dragging_slider = (handle[0], handle[1])
                    self._dragging_slider_preview = self._slider_preview_for_handle(handle[0], handle[1], world)
                self.update()
                return
            if clicked_joint is not None:
                self._selected_entity_id = clicked_joint
                self.entitySelected.emit(clicked_joint)
                self.update()
                return
            if clicked_driver is not None:
                self._selected_entity_id = clicked_driver
                self.entitySelected.emit(clicked_driver)
                self.update()
                return
            super().mousePressEvent(event)
            return

        if not self._require_editing():
            return

        if self._mode == CanvasMode.CREATE_BAR:
            self._creation_points.append(world)
            if len(self._creation_points) == 2:
                self._create_bar_from_points()
            self.update()
            return

        if self._mode == CanvasMode.CREATE_BODY:
            self._append_creation_point(world)
            self.update()
            return

        if self._mode == CanvasMode.ADD_MARKER:
            self._add_marker_to_selected_body(world)
            return

        if self._mode in {CanvasMode.CREATE_REVOLUTE, CanvasMode.CREATE_RIGID}:
            if clicked_marker is None:
                return
            self._handle_joint_click(clicked_marker)
            return

        if self._mode == CanvasMode.CREATE_SLIDER:
            self._creation_points.append(world)
            if len(self._creation_points) == 2:
                self._create_slider_from_points()
            self.update()
            return

        if self._mode == CanvasMode.CONNECT_GROUND:
            if clicked_marker is None:
                return
            self._create_ground_joint(clicked_marker)
            return

        if self._mode == CanvasMode.CONNECT_SLIDER:
            if self._slider_start_marker is None:
                if clicked_marker is None:
                    return
                self._slider_start_marker = clicked_marker
                self.entitySelected.emit(clicked_marker.entity_id)
                self.update()
                return
            if clicked_slider is None:
                return
            self._create_slider_joint(self._slider_start_marker, clicked_slider)
            self._slider_start_marker = None
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        self._hover_world = self._to_world(event.position(), self._current_transform())
        if self._panning and self._pan_last_screen is not None:
            current = event.position()
            dx = current.x() - self._pan_last_screen.x()
            dy = current.y() - self._pan_last_screen.y()
            scale = self._current_transform()[0]
            self._view_center_x -= dx / scale
            self._view_center_y += dy / scale
            self._pan_last_screen = current
            self._sync_view_state()
            self.update()
            return
        if self._editing_enabled and self._mode == CanvasMode.SELECT and self._dragging_marker is not None:
            self._drag_preview = (
                self._dragging_marker.entity_id,
                self._hover_world[0],
                self._hover_world[1],
            )
        elif self._editing_enabled and self._mode == CanvasMode.SELECT and self._dragging_slider is not None:
            slider_id, handle_kind = self._dragging_slider
            self._dragging_slider_preview = self._slider_preview_for_handle(slider_id, handle_kind, self._hover_world)
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        if event.button() in {QtCore.Qt.MouseButton.MiddleButton, QtCore.Qt.MouseButton.RightButton}:
            self._panning = False
            self._pan_last_screen = None
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._dragging_marker is not None:
            if not self._require_editing():
                self._dragging_marker = None
                self._drag_preview = None
                return
            if self._drag_preview is None:
                x, y = self._to_world(event.position(), self._current_transform())
                self._drag_preview = (self._dragging_marker.entity_id, x, y)
            marker_id, x, y = self._drag_preview
            self.app_service.move_marker(marker_id, self._mm_expression(x), self._mm_expression(y))
            self._dragging_marker = None
            self._drag_preview = None
            self.modelChanged.emit(f"Moved marker to ({x:.2f}, {y:.2f}) mm")
            self.update()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._dragging_slider is not None:
            if not self._require_editing():
                self._dragging_slider = None
                self._dragging_slider_preview = None
                return
            slider_id, _handle_kind = self._dragging_slider
            preview = self._dragging_slider_preview
            self._dragging_slider = None
            self._dragging_slider_preview = None
            if preview is None:
                return
            self.app_service.update_property(slider_id, "origin_x", PropertyValueInput("expression", self._mm_expression(preview["origin_x"])))
            self.app_service.update_property(slider_id, "origin_y", PropertyValueInput("expression", self._mm_expression(preview["origin_y"])))
            self.app_service.update_property(slider_id, "angle", PropertyValueInput("expression", self._deg_expression(preview["angle_deg"])))
            self.app_service.update_property(slider_id, "travel_min", PropertyValueInput("expression", self._mm_expression(preview["travel_min"])))
            self.app_service.update_property(slider_id, "travel_max", PropertyValueInput("expression", self._mm_expression(preview["travel_max"])))
            self.modelChanged.emit(f"Updated slider {self.app_service._find_entity(slider_id).name}")
            self.update()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        if self._mode == CanvasMode.CREATE_BODY and event.button() == QtCore.Qt.MouseButton.LeftButton:
            if not self._require_editing():
                return
            world = self._to_world(event.position(), self._current_transform())
            self._append_creation_point(world)
            self._finalize_body_creation()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        if self._mode == CanvasMode.CREATE_BODY and event.key() in {
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
        }:
            if not self._require_editing():
                return
            self._finalize_body_creation()
            return
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self._creation_points.clear()
            self._joint_start_marker = None
            self._slider_start_marker = None
            self._hover_world = None
            self._drag_preview = None
            self._dragging_marker = None
            self.update()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        if not self._editing_enabled:
            self.modelChanged.emit("Editing is only available at t=0")
            return
        world = self._to_world(event.pos(), self._current_transform())
        marker = self._marker_at(event.pos())
        slider = self._slider_at(event.pos())
        joint_id = self._joint_at(event.pos())
        driver_id = self._driver_at(event.pos())
        menu = QtWidgets.QMenu(self)
        delete_action = None
        rename_action = None
        toggle_joint_type_action = None
        edit_driver_law_action = None
        connect_ground_action = None
        add_marker_action = None
        toggle_com_action = None
        slider_actions: dict[QtGui.QAction, str] = {}
        if marker is not None:
            delete_action = menu.addAction("Delete")
            connect_ground_action = menu.addAction("Connect To Ground")
            add_marker_action = menu.addAction("Add Marker To Body")
            slider_menu = menu.addMenu("Connect To Slider")
            for slider_item in self.app_service.project.model.sliders:
                slider_actions[slider_menu.addAction(slider_item.name)] = slider_item.id
            body = self.app_service._find_body(marker.body_id)
            com_marker = body.com_marker()
            toggle_com_action = menu.addAction("Hide CoM" if com_marker.visible else "Show CoM")
        elif slider is not None:
            rename_action = menu.addAction("Rename Slider")
            delete_action = menu.addAction("Delete")
        elif joint_id is not None:
            rename_action = menu.addAction("Rename Joint")
            toggle_joint_type_action = menu.addAction("Toggle Revolute/Rigid")
            delete_action = menu.addAction("Delete")
        elif driver_id is not None:
            rename_action = menu.addAction("Rename Driver")
            edit_driver_law_action = menu.addAction("Edit Driver Law")
            delete_action = menu.addAction("Delete")
        else:
            selected_body = self._selected_body()
            if selected_body is not None:
                add_marker_action = menu.addAction("Add Marker To Body")
                com_marker = selected_body.com_marker()
                toggle_com_action = menu.addAction("Hide CoM" if com_marker.visible else "Show CoM")
        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        if chosen is rename_action:
            target_id = slider.entity_id if slider is not None else joint_id if joint_id is not None else driver_id
            if target_id is not None:
                self._rename_entity_dialog(target_id)
            return
        if chosen is toggle_joint_type_action and joint_id is not None:
            self._toggle_joint_type(joint_id)
            return
        if chosen is edit_driver_law_action and driver_id is not None:
            self._edit_driver_law_dialog(driver_id)
            return
        if chosen is delete_action:
            target_id = (
                marker.entity_id
                if marker is not None
                else slider.entity_id
                if slider is not None
                else joint_id
                if joint_id is not None
                else driver_id
                if driver_id is not None
                else self._selected_entity_id
            )
            if target_id:
                self.app_service.delete_entity(target_id)
                self.modelChanged.emit("Deleted entity")
            return
        if chosen is connect_ground_action and marker is not None:
            self._create_ground_joint(marker)
            return
        if chosen is add_marker_action:
            self._add_marker_to_selected_body(world, fallback_body=marker.body_id if marker is not None else None)
            return
        if chosen is toggle_com_action:
            body = self.app_service._find_body(marker.body_id) if marker is not None else self._selected_body()
            if body is not None:
                com_marker = body.com_marker()
                self.app_service.update_property(
                    com_marker.id,
                    "visible",
                    PropertyValueInput("boolean", not com_marker.visible),
                )
                self.modelChanged.emit("Toggled CoM visibility")
            return
        if chosen in slider_actions and marker is not None:
            details = self._request_ground_or_slider_joint("SliderJoint")
            if details is None:
                return
            name, joint_type = details
            self.app_service.connect_marker_to_slider(
                marker.entity_id,
                slider_actions[chosen],
                joint_type=joint_type,
                name=name,
            )
            self.modelChanged.emit(f"Created {name}")

    def _marker_at(self, screen_pos: QtCore.QPointF) -> CanvasMarker | None:
        screen_markers = self._screen_markers
        if not screen_markers and self.app_service.project is not None:
            transform = self._current_transform()
            screen_markers = [
                (marker, self._to_screen(marker.x, marker.y, transform))
                for marker in self._collect_markers(self.app_service.project)
                if marker.visible
            ]
        for marker, marker_pos in reversed(screen_markers):
            if QtCore.QLineF(screen_pos, marker_pos).length() <= 10.0:
                return marker
        return None

    def _slider_at(self, screen_pos: QtCore.QPointF) -> CanvasSlider | None:
        screen_sliders = self._screen_sliders
        if not screen_sliders and self.app_service.project is not None:
            transform = self._current_transform()
            sliders = self._collect_sliders(self.app_service.project)
            screen_sliders = []
            for slider in sliders:
                axis_x = math.cos(slider.angle)
                axis_y = math.sin(slider.angle)
                start = self._to_screen(
                    slider.origin_x + slider.travel_min * axis_x,
                    slider.origin_y + slider.travel_min * axis_y,
                    transform,
                )
                end = self._to_screen(
                    slider.origin_x + slider.travel_max * axis_x,
                    slider.origin_y + slider.travel_max * axis_y,
                    transform,
                )
                center = self._to_screen(slider.origin_x, slider.origin_y, transform)
                screen_sliders.append((slider, QtCore.QLineF(start, end), center))
        for slider, line, center in reversed(screen_sliders):
            if QtCore.QLineF(screen_pos, center).length() <= 12.0:
                return slider
            if self._distance_to_segment(screen_pos, line) <= 8.0:
                return slider
        return None

    def _slider_handle_at(self, screen_pos: QtCore.QPointF) -> tuple[str, str] | None:
        handles = self._screen_slider_handles
        if not handles and self.app_service.project is not None:
            transform = self._current_transform()
            for slider in self._collect_sliders(self.app_service.project):
                axis_x = math.cos(slider.angle)
                axis_y = math.sin(slider.angle)
                start = self._to_screen(
                    slider.origin_x + slider.travel_min * axis_x,
                    slider.origin_y + slider.travel_min * axis_y,
                    transform,
                )
                end = self._to_screen(
                    slider.origin_x + slider.travel_max * axis_x,
                    slider.origin_y + slider.travel_max * axis_y,
                    transform,
                )
                center = self._to_screen(slider.origin_x, slider.origin_y, transform)
                handles.extend(
                    [
                        (slider.entity_id, "start", start),
                        (slider.entity_id, "center", center),
                        (slider.entity_id, "end", end),
                    ]
                )
        for slider_id, handle_kind, point in reversed(handles):
            if QtCore.QLineF(screen_pos, point).length() <= 10.0:
                return slider_id, handle_kind
        return None

    def _joint_at(self, screen_pos: QtCore.QPointF) -> str | None:
        for entity_id, center in reversed(self._screen_joints):
            if QtCore.QLineF(screen_pos, center).length() <= 11.0:
                return entity_id
        return None

    def _driver_at(self, screen_pos: QtCore.QPointF) -> str | None:
        for entity_id, center in reversed(self._screen_drivers):
            if QtCore.QLineF(screen_pos, center).length() <= 12.0:
                return entity_id
        return None

    def _distance_to_segment(self, point: QtCore.QPointF, segment: QtCore.QLineF) -> float:
        x1, y1 = segment.p1().x(), segment.p1().y()
        x2, y2 = segment.p2().x(), segment.p2().y()
        px, py = point.x(), point.y()
        dx, dy = x2 - x1, y2 - y1
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return math.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.hypot(px - proj_x, py - proj_y)

    def _draw_empty_state(self, painter: QtGui.QPainter) -> None:
        painter.setPen(QtGui.QPen(QtGui.QColor("#7a7366")))
        painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "Load or create a mechanism")

    def _collect_markers(
        self,
        project: Project,
        assembled: AssembledMechanism | None = None,
    ) -> list[CanvasMarker]:
        markers: list[CanvasMarker] = []
        preview_map = {}
        if self._drag_preview is not None:
            preview_map[self._drag_preview[0]] = (self._drag_preview[1], self._drag_preview[2])
        for body in project.model.bodies:
            for marker in body.markers:
                x, y = self._marker_world_position(project, body.id, marker.id, assembled)
                if x is None or y is None:
                    continue
                if marker.id in preview_map:
                    x, y = preview_map[marker.id]
                markers.append(
                    CanvasMarker(
                        entity_id=marker.id,
                        body_id=body.id,
                        name=marker.name,
                        x=x,
                        y=y,
                        marker_type=marker.type,
                        visible=marker.visible or marker.type is MarkerType.STRUCTURAL,
                    )
                )
        return markers

    def _collect_sliders(self, project: Project) -> list[CanvasSlider]:
        sliders: list[CanvasSlider] = []
        for slider in project.model.sliders:
            try:
                origin_x = self.app_service.expression_service.evaluate_property(slider.origin_x, project.parameters).value
                origin_y = self.app_service.expression_service.evaluate_property(slider.origin_y, project.parameters).value
                angle = self.app_service.unit_service.convert(
                    self.app_service.expression_service.evaluate_expression(slider.angle.expression, project.parameters),
                    "rad",
                )
                travel_min = (
                    self.app_service.expression_service.evaluate_property(slider.travel_min, project.parameters).value
                    if slider.travel_min is not None
                    else -40.0
                )
                travel_max = (
                    self.app_service.expression_service.evaluate_property(slider.travel_max, project.parameters).value
                    if slider.travel_max is not None
                    else 40.0
                )
            except Exception:
                continue
            if self._dragging_slider_preview is not None and self._dragging_slider is not None and self._dragging_slider[0] == slider.id:
                origin_x = self._dragging_slider_preview["origin_x"]
                origin_y = self._dragging_slider_preview["origin_y"]
                angle = math.radians(self._dragging_slider_preview["angle_deg"])
                travel_min = self._dragging_slider_preview["travel_min"]
                travel_max = self._dragging_slider_preview["travel_max"]
            sliders.append(
                CanvasSlider(
                    entity_id=slider.id,
                    name=slider.name,
                    origin_x=origin_x,
                    origin_y=origin_y,
                    angle=angle,
                    travel_min=travel_min,
                    travel_max=travel_max,
                )
            )
        return sliders

    def _fit_transform(self) -> tuple[float, float, float]:
        project = self.app_service.project
        if project is None:
            return 2.0, 0.0, 0.0
        assembled = self._assembled_mechanism(project)
        markers = self._collect_markers(project, assembled)
        sliders = self._collect_sliders(project)
        if not markers and not sliders and not self._creation_points:
            return 2.0, 0.0, 0.0
        xs = [marker.x for marker in markers]
        ys = [marker.y for marker in markers]
        for slider in sliders:
            axis_x = math.cos(slider.angle)
            axis_y = math.sin(slider.angle)
            xs.extend([slider.origin_x + slider.travel_min * axis_x, slider.origin_x + slider.travel_max * axis_x])
            ys.extend([slider.origin_y + slider.travel_min * axis_y, slider.origin_y + slider.travel_max * axis_y])
        if self._creation_points:
            xs.extend(point[0] for point in self._creation_points)
            ys.extend(point[1] for point in self._creation_points)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        margin = 50.0
        scale = min(
            max((self.width() - 2 * margin) / span_x, 1.0),
            max((self.height() - 2 * margin) / span_y, 1.0),
        )
        return scale, 0.5 * (min_x + max_x), 0.5 * (min_y + max_y)

    def _current_transform(self) -> tuple[float, float, float]:
        if self._view_scale is None:
            project = self.app_service.project
            if (
                project is not None
                and (project.view_state.zoom != 1.0 or project.view_state.pan_x != 0.0 or project.view_state.pan_y != 0.0)
            ):
                self._view_scale = project.view_state.zoom
                self._view_center_x = project.view_state.pan_x
                self._view_center_y = project.view_state.pan_y
            else:
                self._view_scale, self._view_center_x, self._view_center_y = self._fit_transform()
                self._sync_view_state()
        return self._view_scale, self._view_center_x, self._view_center_y

    def _sync_view_state(self) -> None:
        project = self.app_service.project
        if project is None or self._view_scale is None:
            return
        project.view_state.zoom = self._view_scale
        project.view_state.pan_x = self._view_center_x
        project.view_state.pan_y = self._view_center_y

    def _to_screen(self, x: float, y: float, transform) -> QtCore.QPointF:
        scale, center_x, center_y = transform
        px = (x - center_x) * scale + self.width() * 0.5
        py = self.height() * 0.5 - (y - center_y) * scale
        return QtCore.QPointF(px, py)

    def _to_world(self, point: QtCore.QPointF, transform) -> tuple[float, float]:
        scale, center_x, center_y = transform
        x = (point.x() - self.width() * 0.5) / scale + center_x
        y = (self.height() * 0.5 - point.y()) / scale + center_y
        return x, y

    def _draw_grid(self, painter: QtGui.QPainter, transform) -> None:
        scale, center_x, center_y = transform
        painter.setPen(QtGui.QPen(QtGui.QColor("#e2dbcf"), 1.0))
        spacing_world = 20.0
        spacing = max(spacing_world * scale, 18.0)
        if spacing <= 0:
            return
        world_left = center_x - self.width() * 0.5 / scale
        world_top = center_y + self.height() * 0.5 / scale
        start_x = math.floor(world_left / spacing_world) * spacing_world
        start_y = math.ceil(world_top / spacing_world) * spacing_world
        x = start_x
        while x <= center_x + self.width() * 0.5 / scale:
            screen_x = self._to_screen(x, center_y, transform).x()
            painter.drawLine(QtCore.QPointF(screen_x, 0.0), QtCore.QPointF(screen_x, float(self.height())))
            x += spacing_world
        y = start_y
        while y >= center_y - self.height() * 0.5 / scale:
            screen_y = self._to_screen(center_x, y, transform).y()
            painter.drawLine(QtCore.QPointF(0.0, screen_y), QtCore.QPointF(float(self.width()), screen_y))
            y -= spacing_world

    def _draw_bodies(
        self,
        painter: QtGui.QPainter,
        project: Project,
        markers: list[CanvasMarker],
        transform,
    ) -> None:
        marker_map = {marker.entity_id: marker for marker in markers}
        for body in project.model.bodies:
            structural = [marker_map[marker.id] for marker in body.structural_markers() if marker.id in marker_map]
            if not structural:
                continue
            selected = self._selected_entity_id == body.id
            pen = QtGui.QPen(QtGui.QColor("#31556f"), 2.3)
            fill = QtGui.QColor(178, 201, 218, 85)
            if selected:
                pen.setColor(QtGui.QColor("#c75b12"))
                pen.setWidthF(3.2)
                fill = QtGui.QColor(230, 173, 112, 80)
            painter.setPen(pen)
            if len(structural) == 1:
                point = self._to_screen(structural[0].x, structural[0].y, transform)
                painter.setBrush(QtGui.QBrush(fill))
                painter.drawEllipse(point, 9.0, 9.0)
                painter.setPen(QtGui.QPen(QtGui.QColor("#5b5247")))
                painter.drawText(point + QtCore.QPointF(10.0, -10.0), body.name)
                continue
            ordered = [
                marker_map[marker_id]
                for marker_id in body.edge_order
                if marker_id in marker_map and marker_map[marker_id].marker_type is MarkerType.STRUCTURAL
            ]
            if len(ordered) < 2:
                ordered = structural
            polygon = QtGui.QPolygonF([self._to_screen(marker.x, marker.y, transform) for marker in ordered])
            if body.closed_shape and len(ordered) >= 3:
                painter.setBrush(QtGui.QBrush(fill))
                painter.drawPolygon(polygon)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            else:
                painter.drawPolyline(polygon)
            name_pos = self._to_screen(ordered[0].x, ordered[0].y, transform)
            painter.setPen(QtGui.QPen(QtGui.QColor("#5b5247")))
            painter.drawText(name_pos + QtCore.QPointF(8.0, -8.0), body.name)

    def _draw_joints(
        self,
        painter: QtGui.QPainter,
        project: Project,
        markers: list[CanvasMarker],
        sliders: list[CanvasSlider],
        transform,
    ) -> None:
        self._screen_joints = []
        marker_map = {marker.entity_id: marker for marker in markers}
        slider_map = {slider.entity_id: slider for slider in sliders}
        for joint in project.model.joints:
            position = self._joint_world_position(joint, marker_map, slider_map)
            if position is None:
                continue
            point = self._to_screen(position[0], position[1], transform)
            self._screen_joints.append((joint.id, point))
            pen_color = QtGui.QColor("#2f3a4b")
            if self._selected_entity_id == joint.id:
                pen_color = QtGui.QColor("#c75b12")
                painter.setBrush(QtGui.QBrush(QtGui.QColor(231, 111, 81, 45)))
                painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                painter.drawEllipse(point, 10.5, 10.5)
            painter.setPen(QtGui.QPen(pen_color, 1.8))
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#faf8f2")))
            if joint.type is JointType.RIGID:
                painter.drawRect(QtCore.QRectF(point.x() - 5.5, point.y() - 5.5, 11.0, 11.0))
            else:
                painter.drawEllipse(point, 5.5, 5.5)
            if joint.endpoint_a.kind is JointEndpointKind.GROUND or joint.endpoint_b.kind is JointEndpointKind.GROUND:
                self._draw_ground_symbol(painter, point)
            if joint.endpoint_a.kind is JointEndpointKind.SLIDER or joint.endpoint_b.kind is JointEndpointKind.SLIDER:
                slider_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.SLIDER else joint.endpoint_b
                slider = slider_map.get(slider_endpoint.slider_id or "")
                if slider is not None:
                    self._draw_slider_joint_symbol(painter, point, slider.angle)

    def _draw_drivers(
        self,
        painter: QtGui.QPainter,
        project: Project,
        markers: list[CanvasMarker],
        sliders: list[CanvasSlider],
        transform,
    ) -> None:
        self._screen_drivers = []
        marker_map = {marker.entity_id: marker for marker in markers}
        slider_map = {slider.entity_id: slider for slider in sliders}
        for driver in project.model.drivers:
            try:
                joint = self.app_service._find_joint(driver.target_joint_id)
            except ValueError:
                continue
            position = self._joint_world_position(joint, marker_map, slider_map)
            if position is None:
                continue
            point = self._to_screen(position[0], position[1], transform)
            accent = QtGui.QColor("#7f5539")
            if self._selected_entity_id == driver.id:
                accent = QtGui.QColor("#c75b12")
                painter.setBrush(QtGui.QBrush(QtGui.QColor(199, 91, 18, 36)))
                painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                painter.drawEllipse(point, 13.5, 13.5)
            painter.setPen(QtGui.QPen(accent, 2.0))
            if driver.type is DriverType.ROTATION:
                arc_rect = QtCore.QRectF(point.x() - 18.0, point.y() - 18.0, 36.0, 36.0)
                painter.drawArc(arc_rect, 40 * 16, 260 * 16)
                arrow = QtGui.QPolygonF(
                    [
                        QtCore.QPointF(point.x() + 4.0, point.y() - 17.0),
                        QtCore.QPointF(point.x() + 11.0, point.y() - 16.0),
                        QtCore.QPointF(point.x() + 7.0, point.y() - 10.0),
                    ]
                )
                painter.setBrush(QtGui.QBrush(accent))
                painter.drawPolygon(arrow)
                anchor = QtCore.QPointF(point.x() + 20.0, point.y() - 20.0)
            else:
                slider = self._slider_for_joint(joint, slider_map)
                angle = slider.angle if slider is not None else 0.0
                axis = QtCore.QPointF(math.cos(angle), -math.sin(angle))
                start = self._offset_point(point, axis, -16.0)
                end = self._offset_point(point, axis, 16.0)
                painter.drawLine(start, end)
                left = QtCore.QPointF(-axis.y(), axis.x())
                arrow = QtGui.QPolygonF(
                    [
                        end,
                        self._offset_point(self._offset_point(end, axis, -7.0), left, 4.0),
                        self._offset_point(self._offset_point(end, axis, -7.0), left, -4.0),
                    ]
                )
                painter.setBrush(QtGui.QBrush(accent))
                painter.drawPolygon(arrow)
                anchor = QtCore.QPointF(end.x() + 6.0, end.y() - 6.0)
            self._screen_drivers.append((driver.id, point))
            painter.setPen(QtGui.QPen(QtGui.QColor("#5a4634")))
            painter.drawText(anchor, driver.name)

    def _draw_markers(self, painter: QtGui.QPainter, markers: list[CanvasMarker], transform) -> None:
        self._screen_markers = []
        for marker in markers:
            if not marker.visible:
                continue
            point = self._to_screen(marker.x, marker.y, transform)
            self._screen_markers.append((marker, point))
            if marker.marker_type is MarkerType.COM:
                fill = QtGui.QColor("#d66a4e")
                radius = 5.5
            else:
                fill = QtGui.QColor("#1e1e1e")
                radius = 4.0
            if self._selected_entity_id == marker.entity_id:
                painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                painter.setBrush(QtGui.QBrush(QtGui.QColor(199, 91, 18, 48)))
                painter.drawEllipse(point, radius + 7.0, radius + 7.0)
                fill = QtGui.QColor("#c75b12")
                radius += 1.5
            painter.setPen(QtGui.QPen(QtGui.QColor("#faf8f2"), 1.0))
            painter.setBrush(QtGui.QBrush(fill))
            painter.drawEllipse(point, radius, radius)
            painter.setPen(QtGui.QPen(QtGui.QColor("#5b5247")))
            painter.drawText(point + QtCore.QPointF(6.0, -6.0), marker.name)

    def _draw_sliders(self, painter: QtGui.QPainter, sliders: list[CanvasSlider], transform) -> None:
        self._screen_sliders = []
        self._screen_slider_handles = []
        for slider in sliders:
            axis_x = math.cos(slider.angle)
            axis_y = math.sin(slider.angle)
            start = self._to_screen(
                slider.origin_x + slider.travel_min * axis_x,
                slider.origin_y + slider.travel_min * axis_y,
                transform,
            )
            end = self._to_screen(
                slider.origin_x + slider.travel_max * axis_x,
                slider.origin_y + slider.travel_max * axis_y,
                transform,
            )
            center = self._to_screen(slider.origin_x, slider.origin_y, transform)
            self._screen_sliders.append((slider, QtCore.QLineF(start, end), center))
            selected = self._selected_entity_id == slider.entity_id
            pen = QtGui.QPen(QtGui.QColor("#457b9d"), 3.0)
            if selected:
                pen.setColor(QtGui.QColor("#c75b12"))
                pen.setWidthF(4.0)
                painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                painter.setBrush(QtGui.QBrush(QtGui.QColor(69, 123, 157, 28)))
                painter.drawEllipse(center, 16.0, 16.0)
            painter.setPen(pen)
            painter.drawLine(start, end)
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#f0f7fb")))
            painter.drawEllipse(start, 4.0, 4.0)
            painter.drawEllipse(end, 4.0, 4.0)
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#457b9d") if not selected else QtGui.QColor("#c75b12")))
            painter.drawRect(QtCore.QRectF(center.x() - 6.5, center.y() - 6.5, 13.0, 13.0))
            self._screen_slider_handles.extend(
                [
                    (slider.entity_id, "start", start),
                    (slider.entity_id, "center", center),
                    (slider.entity_id, "end", end),
                ]
            )
            painter.setPen(QtGui.QPen(QtGui.QColor("#3c3428")))
            painter.drawText(center + QtCore.QPointF(8.0, 16.0), slider.name)

    def _draw_creation_overlay(self, painter: QtGui.QPainter, transform) -> None:
        if self._creation_points:
            painter.setPen(QtGui.QPen(QtGui.QColor("#2a9d8f"), 2.0, QtCore.Qt.PenStyle.DashLine))
            polyline_points = [self._to_screen(x, y, transform) for x, y in self._creation_points]
            if self._hover_world is not None and self._mode in {
                CanvasMode.CREATE_BAR,
                CanvasMode.CREATE_BODY,
                CanvasMode.CREATE_SLIDER,
            }:
                polyline_points.append(self._to_screen(self._hover_world[0], self._hover_world[1], transform))
            if len(polyline_points) >= 2:
                painter.drawPolyline(QtGui.QPolygonF(polyline_points))
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#2a9d8f")))
            for point in polyline_points[: len(self._creation_points)]:
                painter.drawEllipse(point, 4.5, 4.5)
        if self._joint_start_marker is not None and self._hover_world is not None:
            painter.setPen(QtGui.QPen(QtGui.QColor("#f4a261"), 2.0, QtCore.Qt.PenStyle.DashLine))
            start = self._to_screen(self._joint_start_marker.x, self._joint_start_marker.y, transform)
            end = self._to_screen(self._hover_world[0], self._hover_world[1], transform)
            painter.drawLine(start, end)
        if self._slider_start_marker is not None and self._hover_world is not None:
            painter.setPen(QtGui.QPen(QtGui.QColor("#8d6cab"), 2.0, QtCore.Qt.PenStyle.DashLine))
            start = self._to_screen(self._slider_start_marker.x, self._slider_start_marker.y, transform)
            end = self._to_screen(self._hover_world[0], self._hover_world[1], transform)
            painter.drawLine(start, end)

    def _append_creation_point(self, world: tuple[float, float]) -> None:
        if self._creation_points:
            last_x, last_y = self._creation_points[-1]
            if math.hypot(world[0] - last_x, world[1] - last_y) < 1e-6:
                return
        self._creation_points.append(world)

    def _create_bar_from_points(self) -> None:
        if not self._require_editing():
            return
        if len(self._creation_points) != 2:
            return
        name = self._next_name("Bar", [body.name for body in self.app_service.project.model.bodies])
        (x1, y1), (x2, y2) = self._creation_points
        body_id = self.app_service.create_bar(
            name,
            MarkerInput(self._mm_expression(x1), self._mm_expression(y1), "A"),
            MarkerInput(self._mm_expression(x2), self._mm_expression(y2), "B"),
        )
        self._creation_points.clear()
        self.entitySelected.emit(body_id)
        self.modelChanged.emit(f"Created {name}")

    def _finalize_body_creation(self) -> None:
        if not self._require_editing():
            return
        if not self._creation_points:
            return
        name = self._next_name("Body", [body.name for body in self.app_service.project.model.bodies])
        markers = [
            MarkerInput(self._mm_expression(x), self._mm_expression(y), chr(ord("A") + index))
            for index, (x, y) in enumerate(self._creation_points)
        ]
        body_id = self.app_service.create_body(name, markers)
        self._creation_points.clear()
        self.entitySelected.emit(body_id)
        self.modelChanged.emit(f"Created {name}")

    def _create_slider_from_points(self) -> None:
        if not self._require_editing():
            return
        if len(self._creation_points) != 2:
            return
        name = self._next_name("Slider", [slider.name for slider in self.app_service.project.model.sliders])
        (x1, y1), (x2, y2) = self._creation_points
        slider_id = self.app_service.create_slider_from_points(
            name,
            self._mm_expression(x1),
            self._mm_expression(y1),
            self._mm_expression(x2),
            self._mm_expression(y2),
        )
        self._creation_points.clear()
        self.entitySelected.emit(slider_id)
        self.modelChanged.emit(f"Created {name}")

    def _handle_joint_click(self, marker: CanvasMarker) -> None:
        if not self._require_editing():
            return
        if self._joint_start_marker is None:
            self._joint_start_marker = marker
            self.entitySelected.emit(marker.entity_id)
            self.update()
            return
        first = self._joint_start_marker
        self._joint_start_marker = None
        if first.entity_id == marker.entity_id:
            self.update()
            return
        name = self._request_joint_name()
        if name is None:
            self.update()
            return
        self.app_service.move_marker(first.entity_id, self._mm_expression(marker.x), self._mm_expression(marker.y))
        if self._mode == CanvasMode.CREATE_RIGID:
            joint_id = self.app_service.create_rigid_joint(
                name,
                JointEndpointInput(JointEndpointKind.MARKER, body_id=first.body_id, marker_id=first.entity_id),
                JointEndpointInput(JointEndpointKind.MARKER, body_id=marker.body_id, marker_id=marker.entity_id),
            )
        else:
            joint_id = self.app_service.create_joint(
                name,
                "revolute",
                JointEndpointInput(JointEndpointKind.MARKER, body_id=first.body_id, marker_id=first.entity_id),
                JointEndpointInput(JointEndpointKind.MARKER, body_id=marker.body_id, marker_id=marker.entity_id),
            )
        self.entitySelected.emit(joint_id)
        self.modelChanged.emit(f"Created {name}")

    def _create_ground_joint(self, marker: CanvasMarker) -> None:
        if not self._require_editing():
            return
        details = self._request_ground_or_slider_joint("GroundJoint")
        if details is None:
            return
        name, joint_type = details
        joint_id = self.app_service.connect_marker_to_ground(marker.entity_id, joint_type=joint_type, name=name)
        self.entitySelected.emit(joint_id)
        self.modelChanged.emit(f"Created {name}")

    def _create_slider_joint(self, marker: CanvasMarker, slider: CanvasSlider) -> None:
        if not self._require_editing():
            return
        details = self._request_ground_or_slider_joint("SliderJoint")
        if details is None:
            return
        name, joint_type = details
        joint_id = self.app_service.connect_marker_to_slider(
            marker.entity_id,
            slider.entity_id,
            joint_type=joint_type,
            name=name,
        )
        self.entitySelected.emit(joint_id)
        self.modelChanged.emit(f"Created {name}")

    def _add_marker_to_selected_body(
        self, world: tuple[float, float], fallback_body: str | None = None
    ) -> None:
        if not self._require_editing():
            return
        body = self._selected_body(fallback_body=fallback_body)
        if body is None:
            self.modelChanged.emit("Select a body before adding a marker")
            return
        marker_id = self.app_service.add_marker_to_body_at(
            body.id,
            self._mm_expression(world[0]),
            self._mm_expression(world[1]),
        )
        self.entitySelected.emit(marker_id)
        self.modelChanged.emit(f"Added marker to {body.name}")

    def _selected_body(self, fallback_body: str | None = None) -> Body | None:
        if fallback_body is not None:
            return self.app_service._find_body(fallback_body)
        if self._selected_entity_id is None:
            return None
        try:
            entity = self.app_service._find_entity(self._selected_entity_id)
        except ValueError:
            return None
        if isinstance(entity, Body):
            return entity
        if isinstance(entity, CanvasMarker):  # pragma: no cover - defensive
            return self.app_service._find_body(entity.body_id)
        try:
            return self.app_service._find_body_by_marker(self._selected_entity_id)
        except ValueError:
            return None

    def _mm_expression(self, value: float) -> str:
        return f"{value:.3f} mm"

    def _deg_expression(self, value: float) -> str:
        return f"{value:.6f} deg"

    def _next_name(self, prefix: str, existing: list[str]) -> str:
        index = 1
        candidate = f"{prefix}{index}"
        while candidate in existing:
            index += 1
            candidate = f"{prefix}{index}"
        return candidate

    def _request_joint_name(self) -> str | None:
        if not self._require_editing():
            return None
        default_name = self._next_name("Joint", [joint.name for joint in self.app_service.project.model.joints])
        title = "Create Rigid Joint" if self._mode == CanvasMode.CREATE_RIGID else "Create Revolute Joint"
        name, accepted = QtWidgets.QInputDialog.getText(self, title, "Joint name:", text=default_name)
        if not accepted or not name.strip():
            return None
        return name.strip()

    def _request_ground_or_slider_joint(self, prefix: str) -> tuple[str, str] | None:
        if not self._require_editing():
            return None
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Create Joint")
        layout = QtWidgets.QFormLayout(dialog)
        name_edit = QtWidgets.QLineEdit(self._next_name(prefix, [joint.name for joint in self.app_service.project.model.joints]))
        type_combo = QtWidgets.QComboBox()
        type_combo.addItems(["revolute", "rigid"])
        layout.addRow("Name", name_edit)
        layout.addRow("Type", type_combo)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() != int(QtWidgets.QDialog.DialogCode.Accepted):
            return None
        name = name_edit.text().strip()
        if not name:
            return None
        return name, type_combo.currentText()

    def _rename_entity_dialog(self, entity_id: str) -> None:
        if not self._require_editing():
            return
        entity = self.app_service._find_entity(entity_id)
        old_name = entity.name
        name, accepted = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=entity.name)
        if not accepted or not name.strip():
            return
        self.app_service.rename_entity(entity_id, name.strip())
        self.modelChanged.emit(f"Renamed {old_name} to {name.strip()}")

    def _toggle_joint_type(self, joint_id: str) -> None:
        if not self._require_editing():
            return
        joint = self.app_service._find_joint(joint_id)
        target = JointType.RIGID.value if joint.type is JointType.REVOLUTE else JointType.REVOLUTE.value
        self.app_service.set_joint_type(joint_id, target)
        self.modelChanged.emit(f"Joint {joint.name} set to {target}")

    def _edit_driver_law_dialog(self, driver_id: str) -> None:
        if not self._require_editing():
            return
        driver = self.app_service._find_entity(driver_id)
        name, accepted = QtWidgets.QInputDialog.getText(self, "Driver Law", "Law:", text=driver.law.expression)
        if not accepted or not name.strip():
            return
        self.app_service.update_property(driver_id, "law", PropertyValueInput("expression", name.strip()))
        self.modelChanged.emit(f"Updated law for {driver.name}")

    def _assembled_mechanism(self, project: Project) -> AssembledMechanism | None:
        adapter = self.app_service.simulation_runner.adapter
        if not hasattr(adapter, "assembler"):
            return None
        try:
            return adapter.assembler.assemble(project)
        except Exception:
            return None

    def _marker_world_position(
        self,
        project: Project,
        body_id: str,
        marker_id: str,
        assembled: AssembledMechanism | None,
    ) -> tuple[float | None, float | None]:
        if assembled is not None:
            assembled_body = assembled.bodies.get(body_id)
            assembled_marker = assembled_body.markers.get(marker_id) if assembled_body is not None else None
            if assembled_body is not None and assembled_marker is not None:
                pose_x = self._state_overlay.get(f"{body_id}.x") if self._state_overlay is not None else assembled_body.origin_x
                pose_y = self._state_overlay.get(f"{body_id}.y") if self._state_overlay is not None else assembled_body.origin_y
                pose_angle = self._state_overlay.get(f"{body_id}.angle") if self._state_overlay is not None else assembled_body.angle
                if pose_x is None:
                    pose_x = assembled_body.origin_x
                if pose_y is None:
                    pose_y = assembled_body.origin_y
                if pose_angle is None:
                    pose_angle = assembled_body.angle
                cos_a = math.cos(pose_angle)
                sin_a = math.sin(pose_angle)
                return (
                    pose_x + cos_a * assembled_marker.local_x - sin_a * assembled_marker.local_y,
                    pose_y + sin_a * assembled_marker.local_x + cos_a * assembled_marker.local_y,
                )
        try:
            body = self.app_service._find_body(body_id)
            marker = next(item for item in body.markers if item.id == marker_id)
            x = self.app_service.expression_service.evaluate_property(marker.x, project.parameters).value
            y = self.app_service.expression_service.evaluate_property(marker.y, project.parameters).value
            return x, y
        except Exception:
            return None, None

    def _slider_preview_for_handle(
        self,
        slider_id: str,
        handle_kind: str,
        world: tuple[float, float],
    ) -> dict[str, float]:
        slider = self.app_service._find_entity(slider_id)
        if not isinstance(slider, Slider):
            raise ValueError("Unknown slider for preview")
        project = self.app_service.project
        origin_x = self.app_service.expression_service.evaluate_property(slider.origin_x, project.parameters).value
        origin_y = self.app_service.expression_service.evaluate_property(slider.origin_y, project.parameters).value
        angle = self.app_service.expression_service.evaluate_property(slider.angle, project.parameters).value
        travel_min = (
            self.app_service.expression_service.evaluate_property(slider.travel_min, project.parameters).value
            if slider.travel_min is not None
            else -40.0
        )
        travel_max = (
            self.app_service.expression_service.evaluate_property(slider.travel_max, project.parameters).value
            if slider.travel_max is not None
            else 40.0
        )
        if handle_kind == "center":
            return {
                "origin_x": world[0],
                "origin_y": world[1],
                "angle_deg": math.degrees(angle),
                "travel_min": travel_min,
                "travel_max": travel_max,
            }
        dx = world[0] - origin_x
        dy = world[1] - origin_y
        half_length = max(math.hypot(dx, dy), 1e-3)
        angle_deg = math.degrees(math.atan2(dy, dx))
        if handle_kind == "start":
            angle_deg = math.degrees(math.atan2(-dy, -dx))
        return {
            "origin_x": origin_x,
            "origin_y": origin_y,
            "angle_deg": angle_deg,
            "travel_min": -half_length,
            "travel_max": half_length,
        }

    def _joint_world_position(
        self,
        joint,
        marker_map: dict[str, CanvasMarker],
        slider_map: dict[str, CanvasSlider],
    ) -> tuple[float, float] | None:
        endpoints = [joint.endpoint_a, joint.endpoint_b]
        for endpoint in endpoints:
            if endpoint.kind is JointEndpointKind.MARKER and endpoint.marker_id in marker_map:
                marker = marker_map[endpoint.marker_id]
                return marker.x, marker.y
        for endpoint in endpoints:
            if endpoint.kind is JointEndpointKind.SLIDER and endpoint.slider_id in slider_map:
                slider = slider_map[endpoint.slider_id]
                return slider.origin_x, slider.origin_y
        return None

    def _slider_for_joint(self, joint, slider_map: dict[str, CanvasSlider]) -> CanvasSlider | None:
        for endpoint in (joint.endpoint_a, joint.endpoint_b):
            if endpoint.kind is JointEndpointKind.SLIDER and endpoint.slider_id in slider_map:
                return slider_map[endpoint.slider_id]
        return None

    def _draw_ground_symbol(self, painter: QtGui.QPainter, point: QtCore.QPointF) -> None:
        base_y = point.y() + 9.0
        painter.drawLine(QtCore.QPointF(point.x() - 10.0, base_y), QtCore.QPointF(point.x() + 10.0, base_y))
        for index in range(-2, 3):
            x = point.x() + index * 4.0
            painter.drawLine(QtCore.QPointF(x - 2.0, base_y), QtCore.QPointF(x + 2.0, base_y + 5.0))

    def _draw_slider_joint_symbol(self, painter: QtGui.QPainter, point: QtCore.QPointF, angle: float) -> None:
        axis_x = math.cos(angle)
        axis_y = -math.sin(angle)
        tangent = QtCore.QPointF(axis_x, axis_y)
        normal = QtCore.QPointF(-axis_y, axis_x)
        corners = [
            self._offset_point(self._offset_point(point, tangent, 8.0), normal, 5.0),
            self._offset_point(self._offset_point(point, tangent, 8.0), normal, -5.0),
            self._offset_point(self._offset_point(point, tangent, -8.0), normal, -5.0),
            self._offset_point(self._offset_point(point, tangent, -8.0), normal, 5.0),
        ]
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawPolygon(QtGui.QPolygonF(corners))

    def _require_editing(self) -> bool:
        if self._editing_enabled:
            return True
        self.modelChanged.emit("Editing is only available at t=0")
        return False

    def _offset_point(self, point: QtCore.QPointF, direction: QtCore.QPointF, scale: float) -> QtCore.QPointF:
        return QtCore.QPointF(point.x() + direction.x() * scale, point.y() + direction.y() * scale)
