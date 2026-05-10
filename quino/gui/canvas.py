from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.inputs import JointEndpointInput, MarkerInput, PropertyValueInput
from quino.domain.model import (
    Body,
    Project,
    SketchConstraint,
    SketchArc,
    SketchCircle,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
    Slider,
)
from quino.domain.sketch_constraints import CONSTRAINT_SPECS, ConstraintSpec
from quino.domain.types import DriverType, JointEndpointKind, JointType, MarkerType, SketchConstraintType, SketchEntityType
from quino.services.sketch_dof import SketchDofAnalyzer
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


@dataclass(slots=True)
class CanvasSketchPoint:
    entity_id: str
    name: str
    x: float
    y: float
    visible: bool
    construction: bool


@dataclass(slots=True)
class CanvasSketchEntity:
    entity_id: str
    name: str
    entity_type: SketchEntityType
    point_ids: list[str]
    visible: bool
    construction: bool
    radius: float | None = None



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
    CREATE_ROTATION_DRIVER = "create_rotation_driver"
    CREATE_TRANSLATION_DRIVER = "create_translation_driver"
    CREATE_POINT_SENSOR = "create_point_sensor"
    CREATE_DISTANCE_SENSOR = "create_distance_sensor"
    CREATE_ANGLE_HORIZONTAL_SENSOR = "create_angle_horizontal_sensor"
    CREATE_ANGLE_VERTICAL_SENSOR = "create_angle_vertical_sensor"
    CREATE_ANGLE_VECTOR_SENSOR = "create_angle_vector_sensor"
    CREATE_SKETCH_POINT = "create_sketch_point"
    CREATE_SKETCH_LINE_SEGMENT = "create_sketch_line_segment"
    CREATE_SKETCH_CIRCLE = "create_sketch_circle"
    CREATE_SKETCH_ARC = "create_sketch_arc"
    CREATE_SKETCH_INFINITE_LINE = "create_sketch_infinite_line"
    CREATE_SKETCH_FIX = "create_sketch_fix"
    CREATE_SKETCH_HORIZONTAL = "create_sketch_horizontal"
    CREATE_SKETCH_VERTICAL = "create_sketch_vertical"
    CREATE_SKETCH_DISTANCE = "create_sketch_distance"
    CREATE_SKETCH_COINCIDENT = "create_sketch_coincident"
    CREATE_SKETCH_PARALLEL = "create_sketch_parallel"
    CREATE_SKETCH_PERPENDICULAR = "create_sketch_perpendicular"
    CREATE_SKETCH_EQUAL_LENGTH = "create_sketch_equal_length"
    CREATE_SKETCH_ANGLE = "create_sketch_angle"
    CREATE_SKETCH_MIDPOINT = "create_sketch_midpoint"
    CREATE_SKETCH_COLLINEAR = "create_sketch_collinear"
    CREATE_SKETCH_SYMMETRIC = "create_sketch_symmetric"
    CREATE_SKETCH_ON_CIRCLE = "create_sketch_on_circle"
    CREATE_SKETCH_TANGENT = "create_sketch_tangent"
    CREATE_SKETCH_CONCENTRIC = "create_sketch_concentric"
    CREATE_SKETCH_ARC_CENTER = "create_sketch_arc_center"


# Map CanvasMode constraint creation strings to SketchConstraintType
_CONSTRAINT_MODE_TO_TYPE: dict[str, SketchConstraintType] = {
    CanvasMode.CREATE_SKETCH_HORIZONTAL:    SketchConstraintType.HORIZONTAL,
    CanvasMode.CREATE_SKETCH_VERTICAL:      SketchConstraintType.VERTICAL,
    CanvasMode.CREATE_SKETCH_DISTANCE:      SketchConstraintType.DISTANCE,
    CanvasMode.CREATE_SKETCH_COINCIDENT:    SketchConstraintType.COINCIDENT,
    CanvasMode.CREATE_SKETCH_PARALLEL:      SketchConstraintType.PARALLEL,
    CanvasMode.CREATE_SKETCH_PERPENDICULAR: SketchConstraintType.PERPENDICULAR,
    CanvasMode.CREATE_SKETCH_EQUAL_LENGTH:  SketchConstraintType.EQUAL_LENGTH,
    CanvasMode.CREATE_SKETCH_ANGLE:         SketchConstraintType.ANGLE,
    CanvasMode.CREATE_SKETCH_MIDPOINT:      SketchConstraintType.MIDPOINT,
    CanvasMode.CREATE_SKETCH_COLLINEAR:     SketchConstraintType.COLLINEAR,
    CanvasMode.CREATE_SKETCH_SYMMETRIC:     SketchConstraintType.SYMMETRIC,
    CanvasMode.CREATE_SKETCH_ON_CIRCLE:     SketchConstraintType.ON_CIRCLE,
    CanvasMode.CREATE_SKETCH_TANGENT:       SketchConstraintType.TANGENT,
    CanvasMode.CREATE_SKETCH_CONCENTRIC:    SketchConstraintType.COINCIDENT,  # maps to coincident
}

_CONSTRAINT_SPEC: dict[str, tuple[int, int]] = {
    mode: (spec.points, spec.entities)
    for mode, ctype in _CONSTRAINT_MODE_TO_TYPE.items()
    if (spec := CONSTRAINT_SPECS.get(ctype)) is not None
}
# concentric is a special case handled above via coincident mapping
_CONSTRAINT_SPEC.setdefault(CanvasMode.CREATE_SKETCH_CONCENTRIC, (2, 0))

_SKETCH_CONSTRAINT_POINT_COUNT: dict[str, int] = {k: v[0] for k, v in _CONSTRAINT_SPEC.items()}

_CONSTRAINT_LABEL: dict[str, str] = {
    mode: (CONSTRAINT_SPECS.get(ctype) or ConstraintSpec(0, 0, None, "Constraint")).label
    for mode, ctype in _CONSTRAINT_MODE_TO_TYPE.items()
}
_CONSTRAINT_LABEL.setdefault(CanvasMode.CREATE_SKETCH_CONCENTRIC, "Concentric")

_SKETCH_CONSTRAINT_TYPE_STR: dict[str, str] = {
    CanvasMode.CREATE_SKETCH_HORIZONTAL:    "horizontal",
    CanvasMode.CREATE_SKETCH_VERTICAL:      "vertical",
    CanvasMode.CREATE_SKETCH_DISTANCE:      "distance",
    CanvasMode.CREATE_SKETCH_COINCIDENT:    "coincident",
    CanvasMode.CREATE_SKETCH_PARALLEL:      "parallel",
    CanvasMode.CREATE_SKETCH_PERPENDICULAR: "perpendicular",
    CanvasMode.CREATE_SKETCH_EQUAL_LENGTH:  "equal_length",
    CanvasMode.CREATE_SKETCH_ANGLE:         "angle",
    CanvasMode.CREATE_SKETCH_MIDPOINT:      "midpoint",
    CanvasMode.CREATE_SKETCH_COLLINEAR:     "collinear",
    CanvasMode.CREATE_SKETCH_SYMMETRIC:     "symmetric",
    CanvasMode.CREATE_SKETCH_ON_CIRCLE:     "on_circle",
    CanvasMode.CREATE_SKETCH_TANGENT:       "tangent",
    # CONCENTRIC maps to coincident at finalization (no new type)
}


class MechanismCanvas(QtWidgets.QWidget):
    entitySelected = QtCore.Signal(str)
    selectionCleared = QtCore.Signal()
    modelChanged = QtCore.Signal(str)
    modeChanged = QtCore.Signal(str)
    dofInfoChanged = QtCore.Signal(str)
    displaySettingsChanged = QtCore.Signal()

    def __init__(self, app_service: ApplicationService, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.app_service = app_service
        self._selected_entity_id: str | None = None
        self._state_overlay: dict[str, float] | None = None
        self._screen_markers: list[tuple[CanvasMarker, QtCore.QPointF]] = []
        self._screen_bodies: list[tuple[str, str, object]] = []
        self._screen_sliders: list[tuple[CanvasSlider, QtCore.QLineF, QtCore.QPointF]] = []
        self._screen_sketch_points: list[tuple[CanvasSketchPoint, QtCore.QPointF]] = []
        self._screen_sketch_entities: list[tuple[CanvasSketchEntity, object]] = []
        self._screen_sketch_constraints: list[tuple[str, QtCore.QPointF]] = []
        self._screen_slider_handles: list[tuple[str, str, QtCore.QPointF]] = []
        self._screen_joints: list[tuple[str, QtCore.QPointF]] = []
        self._screen_drivers: list[tuple[str, QtCore.QPointF]] = []
        self._mode = CanvasMode.SELECT
        self._interaction_mode = "all"
        self._editing_enabled = True
        self._creation_points: list[tuple[float, float]] = []
        self._joint_start_marker: CanvasMarker | None = None
        self._slider_joint_start: CanvasMarker | CanvasSlider | None = None
        self._driver_start_joint_id: str | None = None
        self._sensor_marker_ids: list[str] = []
        self._creation_entity_ids: list[str] = []
        self._hover_world: tuple[float, float] | None = None
        self._hovered_sketch_point_id: str | None = None
        self._hovered_sketch_entity_id: str | None = None
        self._dragging_marker: CanvasMarker | None = None
        self._drag_preview: tuple[str, float, float] | None = None
        self._dragging_sketch_point: CanvasSketchPoint | None = None
        self._dragging_sketch_point_preview: tuple[str, float, float] | None = None
        self._dragging_slider: tuple[str, str] | None = None
        self._dragging_slider_preview: dict[str, float] | None = None
        self._view_scale: float | None = None
        self._view_center_x = 0.0
        self._view_center_y = 0.0
        self._panning = False
        self._pan_last_screen: QtCore.QPointF | None = None
        self._pending_joint_creation: dict[str, str | int | None] | None = None
        self._edit_guard: Callable[[], bool] | None = None
        self._trajectories: list[list[tuple[float, float]]] = []
        self._show_trajectories: bool = True
        self._snap_preview_world: tuple[float, float] | None = None
        self._snap_to_point: bool = False
        self._dof_result = None
        self._last_mouse_screen: QtCore.QPointF = QtCore.QPointF(0.0, 0.0)
        self._show_origin: bool = True
        self._show_axes: bool = True
        self._show_grid: bool = True
        self._background_color: str = "#f5f1e8"
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    def mode(self) -> str:
        return self._mode

    def show_origin(self) -> bool:
        return self._show_origin

    def show_axes(self) -> bool:
        return self._show_axes

    def show_grid(self) -> bool:
        return self._show_grid

    def background_color(self) -> str:
        return self._background_color

    def set_show_origin(self, show: bool) -> None:
        self._show_origin = show
        self.displaySettingsChanged.emit()
        self.update()

    def set_show_axes(self, show: bool) -> None:
        self._show_axes = show
        self.displaySettingsChanged.emit()
        self.update()

    def set_show_grid(self, show: bool) -> None:
        self._show_grid = show
        self.displaySettingsChanged.emit()
        self.update()

    def set_background_color(self, color: str) -> None:
        self._background_color = color
        self.displaySettingsChanged.emit()
        self.update()

    def set_interaction_mode(self, mode: str) -> None:
        self._interaction_mode = mode
        # Clear any hover/selection that belongs to the now-disabled domain
        if mode == "sketch":
            if self._selected_entity_id is not None:
                # Check if selected entity is a model entity (not sketch)
                if not self._is_sketch_entity(self._selected_entity_id):
                    self._selected_entity_id = None
                    self.selectionCleared.emit()
            self._dragging_marker = None
            self._drag_preview = None
            self._dragging_slider = None
            self._dragging_slider_preview = None
        elif mode == "model":
            if self._selected_entity_id is not None:
                if self._is_sketch_entity(self._selected_entity_id):
                    self._selected_entity_id = None
                    self.selectionCleared.emit()
            self._dragging_sketch_point = None
            self._dragging_sketch_point_preview = None
        self._hovered_sketch_point_id = None
        self._hovered_sketch_entity_id = None
        self.update()

    def _is_sketch_entity(self, entity_id: str) -> bool:
        project = self.app_service.project
        if project is None or project.sketch is None:
            return False
        if any(p.id == entity_id for p in project.sketch.points()):
            return True
        if any(e.id == entity_id for e in project.sketch.entities):
            return True
        if any(c.id == entity_id for c in project.sketch.constraints):
            return True
        return False

    def _is_point_fixed(self, point_id: str) -> bool:
        project = self.app_service.project
        if project is None or project.sketch is None:
            return False
        return any(
            c.type == SketchConstraintType.FIX and point_id in c.references
            for c in project.sketch.constraints
        )

    def _reset_tool_state(self) -> None:
        self._creation_points.clear()
        self._joint_start_marker = None
        self._slider_joint_start = None
        self._driver_start_joint_id = None
        self._sensor_marker_ids = []
        self._creation_entity_ids = []
        self._hover_world = None
        self._hovered_sketch_point_id = None
        self._hovered_sketch_entity_id = None
        self._dragging_marker = None
        self._drag_preview = None
        self._dragging_sketch_point = None
        self._dragging_sketch_point_preview = None
        self._dragging_slider = None
        self._dragging_slider_preview = None
        self._pending_joint_creation = None
        self._snap_preview_world = None

    def set_mode(self, mode: str) -> None:
        if self._mode in _CONSTRAINT_SPEC and mode != self._mode:
            # Constraint was in progress and tool changed — provide feedback
            self.modelChanged.emit("Constraint cancelled: tool changed")
        self._reset_tool_state()
        self._mode = mode
        self._set_cursor_for_mode(mode)
        self.modeChanged.emit(mode)
        self.update()

    def _set_cursor_for_mode(self, mode: str) -> None:
        cursor_map = {
            CanvasMode.CREATE_SKETCH_POINT: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_LINE_SEGMENT: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_CIRCLE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_ARC: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_ARC_CENTER: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_INFINITE_LINE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_FIX: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_HORIZONTAL: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_VERTICAL: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_DISTANCE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_COINCIDENT: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_PARALLEL: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_PERPENDICULAR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_EQUAL_LENGTH: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_ANGLE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_MIDPOINT: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_COLLINEAR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_SYMMETRIC: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_ON_CIRCLE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_TANGENT: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_CONCENTRIC: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_BAR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_BODY: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.ADD_MARKER: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_REVOLUTE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_RIGID: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SLIDER: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CONNECT_GROUND: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CONNECT_SLIDER: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_ROTATION_DRIVER: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_TRANSLATION_DRIVER: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_POINT_SENSOR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_DISTANCE_SENSOR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_ANGLE_HORIZONTAL_SENSOR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_ANGLE_VERTICAL_SENSOR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_ANGLE_VECTOR_SENSOR: QtCore.Qt.CursorShape.CrossCursor,
        }
        self.setCursor(QtGui.QCursor(cursor_map.get(mode, QtCore.Qt.CursorShape.ArrowCursor)))

    def fit_view(self) -> None:
        transform = self._fit_transform()
        self._view_scale, self._view_center_x, self._view_center_y = transform
        self._sync_view_state()
        self.update()

    def center_on_entity(self, entity_id: str) -> None:
        project = self.app_service.project
        if project is None:
            return
        if project.sketch is not None:
            for entity in project.sketch.entities:
                if isinstance(entity, SketchPoint) and entity.id == entity_id:
                    try:
                        x = self.app_service.expression_service.evaluate_property(entity.x, project.parameters).value
                        y = self.app_service.expression_service.evaluate_property(entity.y, project.parameters).value
                    except Exception:
                        return
                    self._view_center_x, self._view_center_y = x, y
                    self._sync_view_state()
                    self.update()
                    return
        assembled = self._assembled_mechanism(project)
        for body in project.model.bodies:
            for marker in body.markers:
                if marker.id == entity_id:
                    x, y = self._marker_world_position(project, body.id, marker.id, assembled)
                    if x is not None and y is not None:
                        self._view_center_x, self._view_center_y = x, y
                        self._sync_view_state()
                        self.update()
                    return
        for slider in project.model.sliders:
            if slider.id == entity_id:
                try:
                    ox = self.app_service.expression_service.evaluate_property(slider.origin_x, project.parameters).value
                    oy = self.app_service.expression_service.evaluate_property(slider.origin_y, project.parameters).value
                    self._view_center_x, self._view_center_y = ox, oy
                    self._sync_view_state()
                    self.update()
                except Exception:
                    pass
                return

    def set_selection(self, entity_id: str | None) -> None:
        if entity_id is not None and self._interaction_mode != "all":
            is_sketch = self._is_sketch_entity(entity_id)
            if self._interaction_mode == "sketch" and not is_sketch:
                entity_id = None
            elif self._interaction_mode in ("model", "sim") and is_sketch:
                entity_id = None
        self._selected_entity_id = entity_id
        self.update()

    def set_state_overlay(self, state: dict[str, float] | None) -> None:
        self._state_overlay = state
        self.update()

    def set_trajectories(self, trajectories: list[list[tuple[float, float]]]) -> None:
        self._trajectories = trajectories
        self.update()

    def set_show_trajectories(self, show: bool) -> None:
        self._show_trajectories = show
        self.update()

    def set_editing_enabled(self, enabled: bool) -> None:
        self._editing_enabled = enabled
        if not enabled:
            self._creation_points.clear()
            self._joint_start_marker = None
            self._slider_joint_start = None
            self._driver_start_joint_id = None
            self._sensor_marker_ids = []
            self._dragging_marker = None
            self._drag_preview = None
            self._dragging_sketch_point = None
            self._dragging_sketch_point_preview = None
            self._dragging_slider = None
            self._dragging_slider_preview = None
            self._snap_preview_world = None
            self._snap_to_point = False
        self.update()

    def set_edit_guard(self, guard: Callable[[], bool] | None) -> None:
        self._edit_guard = guard

    def inject_entity_selection(self, entity_id: str) -> None:
        """Process a tree-selection as if the user had clicked the entity on the canvas."""
        if not self._editing_enabled:
            return
        project = self.app_service.project
        if project is None:
            return

        # Build lookup maps
        assembled = self._assembled_mechanism(project)
        markers = self._collect_markers(project, assembled)
        sliders = self._collect_sliders(project)
        marker_map = {m.entity_id: m for m in markers}
        slider_map = {s.entity_id: s for s in sliders}

        # Modes that accept a marker click
        if self._mode == CanvasMode.ADD_MARKER:
            # Selecting a body or marker from the tree sets the target body for the next canvas click
            body_ids = {b.id for b in project.model.bodies}
            if entity_id in body_ids:
                self._selected_entity_id = entity_id
                self.entitySelected.emit(entity_id)
                self.update()
            elif entity_id in marker_map:
                # If a marker was selected, use its body
                self._selected_entity_id = marker_map[entity_id].body_id
                self.entitySelected.emit(marker_map[entity_id].body_id)
                self.update()
            return

        if self._mode in {
            CanvasMode.CREATE_REVOLUTE,
            CanvasMode.CREATE_RIGID,
        }:
            marker = marker_map.get(entity_id)
            if marker is not None:
                self._handle_joint_click(marker)
            return

        if self._mode == CanvasMode.CONNECT_GROUND:
            marker = marker_map.get(entity_id)
            if marker is not None:
                self._create_ground_joint(marker)
            return

        if self._mode == CanvasMode.CONNECT_SLIDER:
            marker = marker_map.get(entity_id)
            slider = slider_map.get(entity_id)
            if self._slider_joint_start is None:
                if marker is None and slider is None:
                    return
                self._slider_joint_start = marker if marker is not None else slider
                self.entitySelected.emit(entity_id)
                self.update()
                return
            start = self._slider_joint_start
            if isinstance(start, CanvasMarker) and slider is not None:
                self._create_slider_joint(start, slider, align="marker_to_slider")
                self._slider_joint_start = None
            elif isinstance(start, CanvasSlider) and marker is not None:
                self._create_slider_joint(marker, start, align="marker_to_slider")
                self._slider_joint_start = None
            return

        if self._mode in {
            CanvasMode.CREATE_ROTATION_DRIVER,
            CanvasMode.CREATE_TRANSLATION_DRIVER,
        }:
            # Accept a joint selected from the tree
            joint_ids = {j.id for j in project.model.joints}
            if entity_id in joint_ids:
                driver_type = "rotation" if self._mode == CanvasMode.CREATE_ROTATION_DRIVER else "translation"
                self._create_driver_for_joint(entity_id, driver_type)
            return

        if self._mode == CanvasMode.CREATE_POINT_SENSOR:
            marker = marker_map.get(entity_id)
            if marker is not None:
                self._create_sensor_from_markers([entity_id], "point")
            return

        if self._mode in {
            CanvasMode.CREATE_DISTANCE_SENSOR,
            CanvasMode.CREATE_ANGLE_HORIZONTAL_SENSOR,
            CanvasMode.CREATE_ANGLE_VERTICAL_SENSOR,
            CanvasMode.CREATE_ANGLE_VECTOR_SENSOR,
        }:
            marker = marker_map.get(entity_id)
            if marker is not None:
                required = 4 if self._mode == CanvasMode.CREATE_ANGLE_VECTOR_SENSOR else 2
                self._handle_sensor_marker_selection(marker, required)
            return

        _sketch_entity_modes = {
            CanvasMode.CREATE_SKETCH_LINE_SEGMENT: 2,
            CanvasMode.CREATE_SKETCH_CIRCLE: 2,
            CanvasMode.CREATE_SKETCH_ARC: 3,
            CanvasMode.CREATE_SKETCH_ARC_CENTER: 3,
            CanvasMode.CREATE_SKETCH_INFINITE_LINE: 2,
        }
        if self._mode in _sketch_entity_modes:
            sketch_point = self.app_service.get_sketch_point(entity_id)
            if sketch_point is None:
                return
            x = self.app_service.expression_service.evaluate_property(sketch_point.x, project.parameters).value
            y = self.app_service.expression_service.evaluate_property(sketch_point.y, project.parameters).value
            self._creation_points.append((x, y))
            self._sensor_marker_ids.append(sketch_point.id)
            required = _sketch_entity_modes[self._mode]
            if len(self._sensor_marker_ids) >= required:
                self._finalize_sketch_creation()
            else:
                self.entitySelected.emit(sketch_point.id)
                self.update()
            return

        if self._mode in _CONSTRAINT_SPEC:
            # In inject_entity_selection, entity_id is always a sketch point or entity
            sketch_point = self.app_service.get_sketch_point(entity_id)
            n_pts, n_ent = _CONSTRAINT_SPEC[self._mode]
            if sketch_point is not None:
                x = self.app_service.expression_service.evaluate_property(sketch_point.x, project.parameters).value
                y = self.app_service.expression_service.evaluate_property(sketch_point.y, project.parameters).value
                fake_pt = type("_Pt", (), {"entity_id": sketch_point.id, "x": x, "y": y})()
                self._handle_constraint_input_click(fake_pt, None, n_pts, n_ent)
            self.update()
            return

        if self._mode == CanvasMode.CREATE_SKETCH_FIX:
            sketch_point = self.app_service.get_sketch_point(entity_id)
            if sketch_point is None:
                return
            constraint_id = self.app_service.create_sketch_constraint(
                SketchConstraintType.FIX.value,
                [sketch_point.id],
            )
            self.entitySelected.emit(constraint_id)
            self.modelChanged.emit("Created sketch fix constraint")
            self.set_mode(CanvasMode.SELECT)
            return

    def screen_position_for_world(self, x: float, y: float) -> QtCore.QPoint:
        point = self._to_screen(x, y, self._current_transform())
        return QtCore.QPoint(int(round(point.x())), int(round(point.y())))

    def screen_position_for_entity(self, entity_id: str) -> QtCore.QPoint | None:
        project = self.app_service.project
        if project is None:
            return None
        sketch_points = self._collect_sketch_points(project)
        for point in sketch_points:
            if point.entity_id == entity_id:
                return self.screen_position_for_world(point.x, point.y)
        sketch_entities = self._collect_sketch_entities(project)
        point_map = {point.entity_id: point for point in sketch_points}
        for entity in sketch_entities:
            if entity.entity_id != entity_id:
                continue
            anchor = self._sketch_entity_anchor(entity, point_map)
            if anchor is not None:
                return self.screen_position_for_world(anchor[0], anchor[1])
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
                joint = self.app_service.get_joint(driver.target_joint_id)
                if joint is not None:
                    position = self._joint_world_position(joint, marker_map, slider_map)
                    if position is not None:
                        return self.screen_position_for_world(position[0], position[1])
        return None

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QtGui.QColor(self._background_color))

        project = self.app_service.project
        transform = self._current_transform()
        if project is None:
            if self._show_grid:
                self._draw_grid(painter, transform)
            if self._show_origin or self._show_axes:
                self._draw_origin_and_axes(painter, transform)
            self._draw_empty_state(painter)
            self._draw_creation_overlay(painter, transform)
            return

        assembled = self._assembled_mechanism(project)
        markers = self._collect_markers(project, assembled)
        sliders = self._collect_sliders(project)
        sketch_points = self._collect_sketch_points(project)
        sketch_entities = self._collect_sketch_entities(project)
        sketch_invalid = project.sketch is not None and project.sketch.solve_error is not None
        model_dimmed = self._interaction_mode == "sketch"

        if self._show_grid:
            self._draw_grid(painter, transform)
        if self._show_origin or self._show_axes:
            self._draw_origin_and_axes(painter, transform)

        if model_dimmed:
            # In sketch mode: draw dimmed model layer first, then crisp sketch on top
            painter.save()
            painter.setOpacity(0.25)
            self._draw_sliders(painter, sliders, transform)
            if project.model.bodies:
                self._draw_bodies(painter, project, markers, transform)
                self._draw_joints(painter, project, markers, sliders, transform)
                self._draw_drivers(painter, project, markers, sliders, transform)
                self._draw_markers(painter, markers, transform)
            painter.restore()
            self._draw_sketch(painter, sketch_points, sketch_entities, transform, invalid=sketch_invalid)
            self._draw_sketch_constraints(painter, project, sketch_points, transform, invalid=sketch_invalid)
            if self._show_trajectories and self._trajectories:
                self._draw_trajectories(painter, transform)
            if not sketch_points and not sketch_entities and not project.model.bodies:
                self._draw_empty_state(painter)
        else:
            # Normal order: sketch then model
            self._draw_sketch(painter, sketch_points, sketch_entities, transform, invalid=sketch_invalid)
            self._draw_sketch_constraints(painter, project, sketch_points, transform, invalid=sketch_invalid)
            self._draw_sliders(painter, sliders, transform)
            if project.model.bodies:
                self._draw_bodies(painter, project, markers, transform)
                self._draw_joints(painter, project, markers, sliders, transform)
                self._draw_drivers(painter, project, markers, sliders, transform)
                self._draw_markers(painter, markers, transform)
            elif not sketch_points and not sketch_entities:
                self._draw_empty_state(painter)
            if self._show_trajectories and self._trajectories:
                self._draw_trajectories(painter, transform)

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
        self._last_mouse_screen = event.position()
        if event.button() in {QtCore.Qt.MouseButton.MiddleButton, QtCore.Qt.MouseButton.RightButton}:
            self._panning = True
            self._pan_last_screen = event.position()
            return
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setFocus()
        clicked = event.position()
        clicked_sketch_point = self._sketch_point_at(clicked)
        clicked_sketch_entity = self._sketch_entity_at(clicked)
        clicked_marker = self._marker_at(clicked)
        clicked_body = self._body_at(clicked)
        clicked_slider = self._slider_at(clicked)
        clicked_slider_handle = self._slider_handle_at(clicked)
        clicked_joint = self._joint_at(clicked)
        clicked_driver = self._driver_at(clicked)
        world = self._to_world(clicked, self._current_transform())

        if self._mode == CanvasMode.SELECT:
            if clicked_sketch_point is not None and self._interaction_mode in ("sketch", "all"):
                self._selected_entity_id = clicked_sketch_point.entity_id
                self.entitySelected.emit(clicked_sketch_point.entity_id)
                point_is_locked = self._is_point_fixed(clicked_sketch_point.entity_id) or (
                    self._dof_result is not None
                    and self._dof_result.point_dof.get(clicked_sketch_point.entity_id, 2) == 0
                )
                if self._editing_enabled and not point_is_locked:
                    self._dragging_sketch_point = clicked_sketch_point
                    self._dragging_sketch_point_preview = (
                        clicked_sketch_point.entity_id,
                        clicked_sketch_point.x,
                        clicked_sketch_point.y,
                    )
                self.update()
                return
            if clicked_sketch_entity is not None and self._interaction_mode in ("sketch", "all"):
                self._selected_entity_id = clicked_sketch_entity.entity_id
                self.entitySelected.emit(clicked_sketch_entity.entity_id)
                self.update()
                return
            if clicked_marker is not None and self._interaction_mode in ("model", "sim", "all"):
                self._selected_entity_id = clicked_marker.entity_id
                self.entitySelected.emit(clicked_marker.entity_id)
                if self._editing_enabled:
                    self._dragging_marker = clicked_marker
                    self._drag_preview = (clicked_marker.entity_id, clicked_marker.x, clicked_marker.y)
                self.update()
                return
            if clicked_slider is not None and self._interaction_mode in ("model", "sim", "all"):
                self._selected_entity_id = clicked_slider.entity_id
                self.entitySelected.emit(clicked_slider.entity_id)
                if self._editing_enabled:
                    handle = clicked_slider_handle or (clicked_slider.entity_id, "center")
                    self._dragging_slider = (handle[0], handle[1])
                    self._dragging_slider_preview = self._slider_preview_for_handle(handle[0], handle[1], world)
                self.update()
                return
            if clicked_joint is not None and self._interaction_mode in ("model", "sim", "all"):
                self._selected_entity_id = clicked_joint
                self.entitySelected.emit(clicked_joint)
                self.update()
                return
            if clicked_driver is not None and self._interaction_mode in ("model", "sim", "all"):
                self._selected_entity_id = clicked_driver
                self.entitySelected.emit(clicked_driver)
                self.update()
                return
            if clicked_body is not None and self._interaction_mode in ("model", "sim", "all"):
                self._selected_entity_id = clicked_body
                self.entitySelected.emit(clicked_body)
                self.update()
                return
            super().mousePressEvent(event)
            return

        if not self._require_editing():
            return

        if self._mode == CanvasMode.CREATE_SKETCH_POINT:
            snapped = self._snap_world(world, include_model=False)
            self._snap_preview_world = snapped
            point_id = self.app_service.create_sketch_point(self._mm_expression(snapped[0]), self._mm_expression(snapped[1]))
            self.entitySelected.emit(point_id)
            self.modelChanged.emit("Created sketch point")
            self.set_mode(CanvasMode.SELECT)
            return

        if self._mode in {
            CanvasMode.CREATE_SKETCH_LINE_SEGMENT,
            CanvasMode.CREATE_SKETCH_CIRCLE,
            CanvasMode.CREATE_SKETCH_ARC,
            CanvasMode.CREATE_SKETCH_ARC_CENTER,
            CanvasMode.CREATE_SKETCH_INFINITE_LINE,
        }:
            snapped = self._snap_world(world, include_model=False)
            self._snap_preview_world = snapped
            point_id = self._resolve_or_create_sketch_point(snapped, clicked_sketch_point)
            self._creation_points.append((snapped[0], snapped[1]))
            self._sensor_marker_ids.append(point_id)
            required = {
                CanvasMode.CREATE_SKETCH_LINE_SEGMENT: 2,
                CanvasMode.CREATE_SKETCH_CIRCLE: 2,
                CanvasMode.CREATE_SKETCH_ARC: 3,
                CanvasMode.CREATE_SKETCH_INFINITE_LINE: 2,
            }[self._mode]
            if len(self._sensor_marker_ids) >= required:
                self._finalize_sketch_creation()
            self.update()
            return

        if self._mode == CanvasMode.CREATE_SKETCH_FIX:
            if clicked_sketch_point is None:
                return
            constraint_id = self.app_service.create_sketch_constraint(
                SketchConstraintType.FIX.value,
                [clicked_sketch_point.entity_id],
            )
            self.entitySelected.emit(constraint_id)
            self.modelChanged.emit("Created sketch fix constraint")
            self.set_mode(CanvasMode.SELECT)
            return

        if self._mode in _CONSTRAINT_SPEC:
            n_pts, n_ent = _CONSTRAINT_SPEC[self._mode]
            self._handle_constraint_input_click(
                clicked_sketch_point, clicked_sketch_entity, n_pts, n_ent
            )
            self.update()
            return

        if self._mode == CanvasMode.CREATE_BAR:
            if clicked_marker is not None:
                self._handle_marker_click_during_creation(clicked_marker)
                if len(self._creation_points) == 2:
                    self._create_bar_from_points()
                return
            self._creation_points.append(world)
            if len(self._creation_points) == 2:
                self._create_bar_from_points()
            self.update()
            return

        if self._mode == CanvasMode.CREATE_BODY:
            if clicked_marker is not None:
                self._handle_marker_click_during_creation(clicked_marker)
                return
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
            if self._slider_joint_start is None:
                if clicked_marker is None and clicked_slider is None:
                    return
                self._slider_joint_start = clicked_marker if clicked_marker is not None else clicked_slider
                self.entitySelected.emit(self._slider_joint_start.entity_id)
                self.update()
                return
            start = self._slider_joint_start
            if isinstance(start, CanvasMarker):
                if clicked_slider is None:
                    return
                self._create_slider_joint(start, clicked_slider, align="marker_to_slider")
                self._slider_joint_start = None
                return
            if isinstance(start, CanvasSlider):
                if clicked_marker is None:
                    return
                self._create_slider_joint(clicked_marker, start, align="marker_to_slider")
                self._slider_joint_start = None
                return

        if self._mode in {CanvasMode.CREATE_ROTATION_DRIVER, CanvasMode.CREATE_TRANSLATION_DRIVER}:
            if clicked_joint is None:
                return
            driver_type = "rotation" if self._mode == CanvasMode.CREATE_ROTATION_DRIVER else "translation"
            self._create_driver_for_joint(clicked_joint, driver_type)
            return

        if self._mode == CanvasMode.CREATE_POINT_SENSOR:
            if clicked_marker is None:
                return
            self._create_sensor_from_markers([clicked_marker.entity_id], "point")
            return

        if self._mode == CanvasMode.CREATE_DISTANCE_SENSOR:
            if clicked_marker is None:
                return
            self._handle_sensor_marker_selection(clicked_marker, 2)
            return

        if self._mode == CanvasMode.CREATE_ANGLE_HORIZONTAL_SENSOR:
            if clicked_marker is None:
                return
            self._handle_sensor_marker_selection(clicked_marker, 2)
            return

        if self._mode == CanvasMode.CREATE_ANGLE_VERTICAL_SENSOR:
            if clicked_marker is None:
                return
            self._handle_sensor_marker_selection(clicked_marker, 2)
            return

        if self._mode == CanvasMode.CREATE_ANGLE_VECTOR_SENSOR:
            if clicked_marker is None:
                return
            self._handle_sensor_marker_selection(clicked_marker, 4)
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        self._hover_world = self._to_world(event.position(), self._current_transform())
        self._update_hover_targets(event.position())
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
            snapped = self._snap_world(self._hover_world, include_model=False)
            self._snap_preview_world = snapped
            self._drag_preview = (self._dragging_marker.entity_id, snapped[0], snapped[1])
        elif self._editing_enabled and self._mode == CanvasMode.SELECT and self._dragging_sketch_point is not None:
            snapped = self._snap_world(self._hover_world, include_model=False, exclude_point_id=self._dragging_sketch_point.entity_id)
            self._snap_preview_world = snapped
            self._dragging_sketch_point_preview = (
                self._dragging_sketch_point.entity_id,
                snapped[0],
                snapped[1],
            )
        elif self._editing_enabled and self._mode == CanvasMode.SELECT and self._dragging_slider is not None:
            slider_id, handle_kind = self._dragging_slider
            self._dragging_slider_preview = self._slider_preview_for_handle(slider_id, handle_kind, self._hover_world)
        elif self._mode in {
            CanvasMode.CREATE_SKETCH_POINT,
            CanvasMode.CREATE_SKETCH_LINE_SEGMENT,
            CanvasMode.CREATE_SKETCH_CIRCLE,
            CanvasMode.CREATE_SKETCH_ARC,
            CanvasMode.CREATE_SKETCH_ARC_CENTER,
            CanvasMode.CREATE_SKETCH_INFINITE_LINE,
            CanvasMode.CREATE_SKETCH_FIX,
            CanvasMode.CREATE_SKETCH_HORIZONTAL,
            CanvasMode.CREATE_SKETCH_VERTICAL,
            CanvasMode.CREATE_SKETCH_DISTANCE,
            CanvasMode.CREATE_SKETCH_COINCIDENT,
            CanvasMode.CREATE_SKETCH_PARALLEL,
            CanvasMode.CREATE_SKETCH_PERPENDICULAR,
            CanvasMode.CREATE_SKETCH_EQUAL_LENGTH,
            CanvasMode.CREATE_SKETCH_ANGLE,
            CanvasMode.CREATE_SKETCH_MIDPOINT,
            CanvasMode.CREATE_SKETCH_COLLINEAR,
            CanvasMode.CREATE_SKETCH_SYMMETRIC,
            CanvasMode.CREATE_SKETCH_ON_CIRCLE,
            CanvasMode.CREATE_SKETCH_TANGENT,
            CanvasMode.CREATE_SKETCH_CONCENTRIC,
        }:
            self._snap_preview_world = self._snap_world(self._hover_world, include_model=False)
        else:
            self._snap_preview_world = None
            self._snap_to_point = False
        # Update DOF info for status bar when in sketch mode
        if self._interaction_mode == "sketch":
            project = self.app_service.project
            if project is not None and project.sketch is not None:
                dof_result = SketchDofAnalyzer().analyze(project.sketch)
                self._dof_result = dof_result
                self.dofInfoChanged.emit(f"Free DOF: {dof_result.total_free_dof}")
            else:
                self._dof_result = None
                self.dofInfoChanged.emit("")
        else:
            self.dofInfoChanged.emit("")
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
            marker_label = self._marker_label(marker_id)
            self._dragging_marker = None
            self._drag_preview = None
            self.modelChanged.emit(f"Moved marker {marker_label} to ({x:.2f}, {y:.2f}) mm")
            self.update()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._dragging_sketch_point is not None:
            if not self._require_editing():
                self._dragging_sketch_point = None
                self._dragging_sketch_point_preview = None
                self._snap_preview_world = None
                return
            point_name = self._dragging_sketch_point.name
            if self._dragging_sketch_point_preview is None:
                x, y = self._to_world(event.position(), self._current_transform())
                self._dragging_sketch_point_preview = (self._dragging_sketch_point.entity_id, x, y)
            point_id, x, y = self._dragging_sketch_point_preview
            self.app_service.move_sketch_point(point_id, self._mm_expression(x), self._mm_expression(y))
            self._dragging_sketch_point = None
            self._dragging_sketch_point_preview = None
            self._snap_preview_world = None
            self.modelChanged.emit(f"Moved sketch point {point_name} to ({x:.2f}, {y:.2f}) mm")
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
            self.app_service.update_slider_geometry(
                slider_id,
                origin_x=self._mm_expression(preview["origin_x"]),
                origin_y=self._mm_expression(preview["origin_y"]),
                angle=self._deg_expression(preview["angle_deg"]),
                travel_min=self._mm_expression(preview["travel_min"]),
                travel_max=self._mm_expression(preview["travel_max"]),
            )
            slider_entity = self.app_service.project.model.sliders
            slider_name = next((s.name for s in slider_entity if s.id == slider_id), slider_id)
            self.modelChanged.emit(f"Updated slider {slider_name}")
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
            if self._mode in _CONSTRAINT_SPEC:
                self.modelChanged.emit("Constraint cancelled: Esc")
            self._reset_tool_state()
            self._selected_entity_id = None
            self.selectionCleared.emit()
            if self._mode != CanvasMode.SELECT:
                self._mode = CanvasMode.SELECT
                self._set_cursor_for_mode(CanvasMode.SELECT)
                self.modeChanged.emit(CanvasMode.SELECT)
            self.update()
            return
        super().keyPressEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        self._hover_world = None
        self._hovered_sketch_point_id = None
        self._hovered_sketch_entity_id = None
        self._snap_preview_world = None
        self.update()
        super().leaveEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        if self._interaction_mode == "sketch":
            return
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
            body = self.app_service.get_body(marker.body_id)
            if body is not None:
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
            body = self.app_service.get_body(marker.body_id) if marker is not None else self._selected_body()
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

    def _project_point_to_segment(
        self,
        point: tuple[float, float],
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> tuple[float, float]:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            return start
        t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denom))
        return start[0] + t * dx, start[1] + t * dy

    def _project_point_to_line(
        self,
        point: tuple[float, float],
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> tuple[float, float]:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            return start
        t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denom
        return start[0] + t * dx, start[1] + t * dy

    def _project_point_to_circle(
        self,
        point: tuple[float, float],
        center: tuple[float, float],
        radius: float,
    ) -> tuple[float, float]:
        dx = point[0] - center[0]
        dy = point[1] - center[1]
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            return center[0] + radius, center[1]
        scale = radius / length
        return center[0] + dx * scale, center[1] + dy * scale

    def _project_point_to_arc(
        self,
        point: tuple[float, float],
        points: list[tuple[float, float]],
    ) -> tuple[float, float] | None:
        arc = self._arc_geometry_from_tuples(points)
        if arc is None:
            return None
        center_x, center_y, radius, start_angle, span_angle = arc
        angle = math.atan2(point[1] - center_y, point[0] - center_x)
        end_angle = start_angle + span_angle
        candidates = [start_angle, end_angle, angle]
        clamped = min(candidates, key=lambda candidate: abs(self._normalize_angle(angle - candidate)))
        if span_angle >= 0:
            if self._angle_is_between(angle, start_angle, end_angle):
                clamped = angle
        else:
            if self._angle_is_between(angle, end_angle, start_angle):
                clamped = angle
        return center_x + math.cos(clamped) * radius, center_y + math.sin(clamped) * radius

    def _arc_geometry(self, points: list[CanvasSketchPoint]) -> tuple[float, float, float, float, float] | None:
        return self._arc_geometry_from_tuples([(point.x, point.y) for point in points])

    def _arc_geometry_from_tuples(
        self,
        points: list[tuple[float, float]],
    ) -> tuple[float, float, float, float, float] | None:
        if len(points) != 3:
            return None
        (x1, y1), (x2, y2), (x3, y3) = points
        determinant = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        if abs(determinant) <= 1e-9:
            return None
        ux = (
            (x1 * x1 + y1 * y1) * (y2 - y3)
            + (x2 * x2 + y2 * y2) * (y3 - y1)
            + (x3 * x3 + y3 * y3) * (y1 - y2)
        ) / determinant
        uy = (
            (x1 * x1 + y1 * y1) * (x3 - x2)
            + (x2 * x2 + y2 * y2) * (x1 - x3)
            + (x3 * x3 + y3 * y3) * (x2 - x1)
        ) / determinant
        radius = math.hypot(x1 - ux, y1 - uy)
        a1 = math.atan2(y1 - uy, x1 - ux)
        a2 = math.atan2(y2 - uy, x2 - ux)
        a3 = math.atan2(y3 - uy, x3 - ux)
        span = self._normalize_angle(a3 - a1)
        if not self._angle_is_between(a2, a1, a1 + span):
            span = span - 2 * math.pi if span > 0 else span + 2 * math.pi
        return ux, uy, radius, a1, span

    def _normalize_angle(self, angle: float) -> float:
        while angle <= -math.pi:
            angle += 2 * math.pi
        while angle > math.pi:
            angle -= 2 * math.pi
        return angle

    def _angle_is_between(self, angle: float, start: float, end: float) -> bool:
        start_n = self._normalize_angle(start)
        end_n = self._normalize_angle(end)
        angle_n = self._normalize_angle(angle)
        if start_n <= end_n:
            return start_n - 1e-9 <= angle_n <= end_n + 1e-9
        return angle_n >= start_n - 1e-9 or angle_n <= end_n + 1e-9

    _TRAJECTORY_COLORS = [
        QtGui.QColor("#e63946"),
        QtGui.QColor("#2196f3"),
        QtGui.QColor("#4caf50"),
        QtGui.QColor("#ff9800"),
        QtGui.QColor("#9c27b0"),
        QtGui.QColor("#00bcd4"),
        QtGui.QColor("#ff5722"),
        QtGui.QColor("#8bc34a"),
    ]

    def _draw_trajectories(self, painter: QtGui.QPainter, transform) -> None:
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        for idx, points in enumerate(self._trajectories):
            if len(points) < 2:
                continue
            color = self._TRAJECTORY_COLORS[idx % len(self._TRAJECTORY_COLORS)]
            pen = QtGui.QPen(color, 1.5)
            pen.setStyle(QtCore.Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            path = QtGui.QPainterPath()
            path.moveTo(self._to_screen(*points[0], transform))
            for pt in points[1:]:
                path.lineTo(self._to_screen(*pt, transform))
            painter.drawPath(path)

    def _draw_empty_state(self, painter: QtGui.QPainter) -> None:
        painter.setPen(QtGui.QPen(QtGui.QColor("#7a7366")))
        painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "Load or create a mechanism or sketch")

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

    def _collect_sketch_points(self, project: Project) -> list[CanvasSketchPoint]:
        points: list[CanvasSketchPoint] = []
        if project.sketch is None or not project.sketch.visible:
            return points
        preview_map = {}
        if self._dragging_sketch_point_preview is not None:
            preview_map[self._dragging_sketch_point_preview[0]] = (
                self._dragging_sketch_point_preview[1],
                self._dragging_sketch_point_preview[2],
            )
        for entity in project.sketch.entities:
            if not isinstance(entity, SketchPoint):
                continue
            try:
                x = self.app_service.expression_service.evaluate_property(entity.x, project.parameters).value
                y = self.app_service.expression_service.evaluate_property(entity.y, project.parameters).value
            except Exception:
                continue
            if entity.id in preview_map:
                x, y = preview_map[entity.id]
            points.append(
                CanvasSketchPoint(
                    entity_id=entity.id,
                    name=entity.name,
                    x=x,
                    y=y,
                    visible=entity.visible,
                    construction=entity.construction,
                )
            )
        return points

    def _collect_sketch_entities(self, project: Project) -> list[CanvasSketchEntity]:
        entities: list[CanvasSketchEntity] = []
        if project.sketch is None or not project.sketch.visible:
            return entities
        for entity in project.sketch.entities:
            if isinstance(entity, SketchPoint):
                continue
            if isinstance(entity, SketchLineSegment):
                entities.append(
                    CanvasSketchEntity(
                        entity_id=entity.id,
                        name=entity.name,
                        entity_type=entity.type,
                        point_ids=[entity.start_point_id, entity.end_point_id],
                        visible=entity.visible,
                        construction=entity.construction,
                    )
                )
            elif isinstance(entity, SketchCircle):
                try:
                    radius = self.app_service.expression_service.evaluate_property(entity.radius, project.parameters).value
                except Exception:
                    continue
                entities.append(
                    CanvasSketchEntity(
                        entity_id=entity.id,
                        name=entity.name,
                        entity_type=entity.type,
                        point_ids=[entity.center_point_id],
                        visible=entity.visible,
                        construction=entity.construction,
                        radius=radius,
                    )
                )
            elif isinstance(entity, SketchArc):
                entities.append(
                    CanvasSketchEntity(
                        entity_id=entity.id,
                        name=entity.name,
                        entity_type=entity.type,
                        point_ids=[entity.point_a_id, entity.point_b_id, entity.point_c_id],
                        visible=entity.visible,
                        construction=entity.construction,
                        
                    )
                )
            elif isinstance(entity, SketchInfiniteLine):
                entities.append(
                    CanvasSketchEntity(
                        entity_id=entity.id,
                        name=entity.name,
                        entity_type=entity.type,
                        point_ids=[entity.point_a_id, entity.point_b_id],
                        visible=entity.visible,
                        construction=entity.construction,
                    )
                )
        return entities

    def _fit_transform(self) -> tuple[float, float, float]:
        project = self.app_service.project
        if project is None:
            return 2.0, 0.0, 0.0
        assembled = self._assembled_mechanism(project)
        markers = self._collect_markers(project, assembled)
        sliders = self._collect_sliders(project)
        sketch_points = self._collect_sketch_points(project)
        if not markers and not sliders and not sketch_points and not self._creation_points:
            return 2.0, 0.0, 0.0
        xs = [marker.x for marker in markers]
        ys = [marker.y for marker in markers]
        xs.extend(point.x for point in sketch_points)
        ys.extend(point.y for point in sketch_points)
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

    def _draw_origin_and_axes(self, painter: QtGui.QPainter, transform) -> None:
        origin = self._to_screen(0.0, 0.0, transform)
        w = float(self.width())
        h = float(self.height())
        if self._show_axes:
            # X axis (red)
            painter.setPen(QtGui.QPen(QtGui.QColor("#e74c3c"), 1.2))
            painter.drawLine(QtCore.QPointF(0.0, origin.y()), QtCore.QPointF(w, origin.y()))
            # Y axis (green)
            painter.setPen(QtGui.QPen(QtGui.QColor("#27ae60"), 1.2))
            painter.drawLine(QtCore.QPointF(origin.x(), 0.0), QtCore.QPointF(origin.x(), h))
            # Arrowheads at positive ends
            arrow = 8.0
            painter.setPen(QtGui.QPen(QtGui.QColor("#e74c3c"), 1.2))
            painter.drawLine(QtCore.QPointF(w - arrow, origin.y() - arrow / 2), QtCore.QPointF(w, origin.y()))
            painter.drawLine(QtCore.QPointF(w - arrow, origin.y() + arrow / 2), QtCore.QPointF(w, origin.y()))
            painter.setPen(QtGui.QPen(QtGui.QColor("#27ae60"), 1.2))
            painter.drawLine(QtCore.QPointF(origin.x() - arrow / 2, arrow), QtCore.QPointF(origin.x(), 0.0))
            painter.drawLine(QtCore.QPointF(origin.x() + arrow / 2, arrow), QtCore.QPointF(origin.x(), 0.0))
        if self._show_origin:
            painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#555555")))
            painter.drawEllipse(origin, 3.5, 3.5)

    def _draw_sketch(
        self,
        painter: QtGui.QPainter,
        points: list[CanvasSketchPoint],
        entities: list[CanvasSketchEntity],
        transform,
        *,
        invalid: bool = False,
    ) -> None:
        self._screen_sketch_points = []
        self._screen_sketch_entities = []
        # Base colours vary by validity state
        if invalid:
            color_normal       = "#c2524a"  # muted red
            color_construction = "#b87060"  # reddish-tan
            color_hover        = "#a03030"  # darker red hover
            color_pt_normal    = "#b84840"  # red point fill
            color_pt_const     = "#a86858"  # reddish-tan point fill
            color_pt_hover     = "#902828"
        else:
            color_normal       = "#a7adb5"
            color_construction = "#c6a77a"
            color_hover        = "#6f7b86"
            color_pt_normal    = "#8d949b"
            color_pt_const     = "#b59b75"
            color_pt_hover     = "#5e6a75"

        # DOF-based colouring (only when sketch is valid)
        dof_result = None
        if not invalid:
            project = self.app_service.project
            if project is not None and project.sketch is not None:
                dof_result = SketchDofAnalyzer().analyze(project.sketch)
                self._dof_result = dof_result

        def _entity_color(entity_id: str, construction: bool) -> QtGui.QColor:
            if dof_result is not None and entity_id in dof_result.fully_constrained_entity_ids:
                return QtGui.QColor("#4caf50")
            return QtGui.QColor(color_normal if not construction else color_construction)

        def _point_color(point_id: str, construction: bool) -> QtGui.QColor:
            if construction:
                return QtGui.QColor(color_pt_const)
            if dof_result is not None:
                dof = dof_result.point_dof.get(point_id, 2)
                if dof == 0:
                    return QtGui.QColor("#4caf50")
                if dof == 1:
                    return QtGui.QColor("#ffc107")
            return QtGui.QColor(color_pt_normal)

        point_map = {point.entity_id: point for point in points}
        for entity in entities:
            if not entity.visible:
                continue
            pen_color = _entity_color(entity.entity_id, entity.construction)
            if self._selected_entity_id == entity.entity_id:
                pen_color = QtGui.QColor("#c75b12")
            elif self._hovered_sketch_entity_id == entity.entity_id:
                pen_color = QtGui.QColor(color_hover)
            pen = QtGui.QPen(pen_color, 1.2)
            if entity.construction:
                pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            geometry = None
            if entity.entity_type is SketchEntityType.LINE_SEGMENT:
                if not all(point_id in point_map for point_id in entity.point_ids):
                    continue
                p1 = point_map[entity.point_ids[0]]
                p2 = point_map[entity.point_ids[1]]
                line = QtCore.QLineF(self._to_screen(p1.x, p1.y, transform), self._to_screen(p2.x, p2.y, transform))
                painter.drawLine(line)
                geometry = line
            elif entity.entity_type is SketchEntityType.CIRCLE:
                if entity.point_ids[0] not in point_map or entity.radius is None:
                    continue
                center_point = point_map[entity.point_ids[0]]
                center = self._to_screen(center_point.x, center_point.y, transform)
                radius_px = abs(entity.radius * transform[0])
                rect = QtCore.QRectF(
                    center.x() - radius_px,
                    center.y() - radius_px,
                    2.0 * radius_px,
                    2.0 * radius_px,
                )
                painter.drawEllipse(rect)
                geometry = rect
            elif entity.entity_type is SketchEntityType.ARC:
                if not all(point_id in point_map for point_id in entity.point_ids):
                    continue
                arc_points = [point_map[point_id] for point_id in entity.point_ids]
                arc = self._arc_geometry(arc_points)
                if arc is None:
                    continue
                center_x, center_y, radius, start_angle, span_angle = arc
                center = self._to_screen(center_x, center_y, transform)
                radius_px = abs(radius * transform[0])
                rect = QtCore.QRectF(
                    center.x() - radius_px, center.y() - radius_px,
                    2.0 * radius_px, 2.0 * radius_px,
                )
                painter.drawArc(rect, int(-math.degrees(start_angle) * 16), int(-math.degrees(span_angle) * 16))
                geometry = ("arc", rect, start_angle, span_angle)
            elif entity.entity_type is SketchEntityType.INFINITE_LINE:
                if not all(point_id in point_map for point_id in entity.point_ids):
                    continue
                p1 = point_map[entity.point_ids[0]]
                p2 = point_map[entity.point_ids[1]]
                dx = p2.x - p1.x
                dy = p2.y - p1.y
                length = math.hypot(dx, dy)
                if length <= 1e-9:
                    continue
                ux = dx / length
                uy = dy / length
                span = max(self.width(), self.height()) / max(transform[0], 1e-9) * 1.2
                start = self._to_screen(p1.x - ux * span, p1.y - uy * span, transform)
                end = self._to_screen(p1.x + ux * span, p1.y + uy * span, transform)
                line = QtCore.QLineF(start, end)
                painter.drawLine(line)
                geometry = line
            if geometry is not None:
                self._screen_sketch_entities.append((entity, geometry))
                if self._should_draw_sketch_label(entity.entity_id):
                    anchor = self._sketch_entity_label_anchor(entity, geometry)
                    if anchor is not None:
                        self._draw_sketch_label(painter, anchor, entity.name, pen_color)
        for point in points:
            if not point.visible:
                continue
            screen_point = self._to_screen(point.x, point.y, transform)
            self._screen_sketch_points.append((point, screen_point))
            radius = 3.5
            fill = _point_color(point.entity_id, point.construction)
            if self._selected_entity_id == point.entity_id:
                painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                painter.setBrush(QtGui.QBrush(QtGui.QColor(199, 91, 18, 36)))
                painter.drawEllipse(screen_point, radius + 5.0, radius + 5.0)
                fill = QtGui.QColor("#c75b12")
            elif self._hovered_sketch_point_id == point.entity_id:
                fill = QtGui.QColor(color_pt_hover)
            painter.setPen(QtGui.QPen(QtGui.QColor("#f5f1e8"), 1.0))
            painter.setBrush(QtGui.QBrush(fill))
            painter.drawEllipse(screen_point, radius, radius)
            if self._should_draw_sketch_label(point.entity_id):
                self._draw_sketch_label(
                    painter,
                    screen_point + QtCore.QPointF(7.0, -8.0),
                    point.name,
                    QtGui.QColor("#6f7881"),
                )

    def _draw_sketch_constraints(
        self,
        painter: QtGui.QPainter,
        project: Project,
        points: list[CanvasSketchPoint],
        transform,
        *,
        invalid: bool = False,
    ) -> None:
        self._screen_sketch_constraints = []
        if project.sketch is None or not project.sketch.visible:
            return
        point_map = {point.entity_id: point for point in points}
        for constraint in project.sketch.constraints:
            anchor = self._sketch_constraint_anchor(constraint, point_map, transform)
            if anchor is None:
                continue
            color = QtGui.QColor("#b84840" if invalid else "#7f8c8d")
            if self._selected_entity_id == constraint.id:
                color = QtGui.QColor("#c75b12")
            painter.setPen(QtGui.QPen(color, 1.1, QtCore.Qt.PenStyle.DashLine))
            if constraint.type is SketchConstraintType.DISTANCE and len(constraint.references) == 2:
                p1 = point_map.get(constraint.references[0])
                p2 = point_map.get(constraint.references[1])
                if p1 is not None and p2 is not None:
                    s1 = self._to_screen(p1.x, p1.y, transform)
                    s2 = self._to_screen(p2.x, p2.y, transform)
                    painter.drawLine(s1, s2)
                    self._draw_distance_annotation(painter, s1, s2, constraint, color, transform)
            elif constraint.type is SketchConstraintType.FIX and constraint.references:
                point = point_map.get(constraint.references[0])
                if point is not None:
                    screen = self._to_screen(point.x, point.y, transform)
                    painter.drawRect(QtCore.QRectF(screen.x() - 5.0, screen.y() + 5.0, 10.0, 6.0))
            elif constraint.type in {
                SketchConstraintType.PARALLEL,
                SketchConstraintType.PERPENDICULAR,
                SketchConstraintType.EQUAL_LENGTH,
            } and len(constraint.references) == 4:
                # Draw dashed line between midpoints of the two line segments
                refs4 = [point_map.get(pid) for pid in constraint.references]
                if all(p is not None for p in refs4):
                    mid1 = self._to_screen(
                        0.5 * (refs4[0].x + refs4[1].x),
                        0.5 * (refs4[0].y + refs4[1].y), transform,
                    )
                    mid2 = self._to_screen(
                        0.5 * (refs4[2].x + refs4[3].x),
                        0.5 * (refs4[2].y + refs4[3].y), transform,
                    )
                    painter.drawLine(mid1, mid2)
            elif constraint.type is SketchConstraintType.ANGLE and len(constraint.references) == 3:
                vertex = point_map.get(constraint.references[0])
                arm1 = point_map.get(constraint.references[1])
                arm2 = point_map.get(constraint.references[2])
                if vertex is not None and arm1 is not None and arm2 is not None:
                    vscreen = self._to_screen(vertex.x, vertex.y, transform)
                    d1x = arm1.x - vertex.x; d1y = arm1.y - vertex.y
                    d2x = arm2.x - vertex.x; d2y = arm2.y - vertex.y
                    len1 = math.hypot(d1x, d1y); len2 = math.hypot(d2x, d2y)
                    if len1 > 1e-9 and len2 > 1e-9:
                        radius_px = min(20.0, 0.25 * min(
                            math.hypot((arm1.x - vertex.x) * transform[0],
                                       (arm1.y - vertex.y) * transform[0]),
                            math.hypot((arm2.x - vertex.x) * transform[0],
                                       (arm2.y - vertex.y) * transform[0]),
                        ))
                        rect = QtCore.QRectF(
                            vscreen.x() - radius_px, vscreen.y() - radius_px,
                            2 * radius_px, 2 * radius_px,
                        )
                        start_deg = -math.degrees(math.atan2(d1y, d1x))
                        end_deg = -math.degrees(math.atan2(d2y, d2x))
                        span = end_deg - start_deg
                        while span > 180: span -= 360
                        while span < -180: span += 360
                        painter.drawArc(rect, int(start_deg * 16), int(span * 16))
                        self._draw_angle_annotation(
                            painter, vscreen, start_deg, end_deg, radius_px, constraint, color
                        )
            # Draw new constraint visual indicators
            if constraint.type is SketchConstraintType.COLLINEAR and len(constraint.references) >= 2:
                refs3 = [point_map.get(pid) for pid in constraint.references[:3]]
                if all(r is not None for r in refs3):
                    pts = [self._to_screen(r.x, r.y, transform) for r in refs3]
                    xs = [p.x() for p in pts]; ys = [p.y() for p in pts]
                    mid_x = (min(xs) + max(xs)) * 0.5; mid_y = (min(ys) + max(ys)) * 0.5
                    extend = 15.0
                    dx = xs[-1] - xs[0]; dy = ys[-1] - ys[0]
                    length = math.hypot(dx, dy)
                    if length > 1e-9:
                        ux, uy = dx / length, dy / length
                        painter.drawLine(
                            QtCore.QPointF(mid_x - ux * extend, mid_y - uy * extend),
                            QtCore.QPointF(mid_x + ux * extend, mid_y + uy * extend),
                        )
            elif constraint.type is SketchConstraintType.SYMMETRIC and len(constraint.references) == 4:
                refs4 = [point_map.get(pid) for pid in constraint.references]
                if all(r is not None for r in refs4):
                    p1s = self._to_screen(refs4[0].x, refs4[0].y, transform)
                    p2s = self._to_screen(refs4[1].x, refs4[1].y, transform)
                    axs = self._to_screen(refs4[2].x, refs4[2].y, transform)
                    axe = self._to_screen(refs4[3].x, refs4[3].y, transform)
                    mid = QtCore.QPointF(0.5 * (p1s.x() + p2s.x()), 0.5 * (p1s.y() + p2s.y()))
                    painter.drawLine(p1s, mid)
                    painter.drawLine(mid, p2s)
                    painter.drawLine(axs, axe)
            elif constraint.type is SketchConstraintType.ON_CIRCLE and len(constraint.references) == 1:
                pt = point_map.get(constraint.references[0])
                if pt is not None:
                    ps = self._to_screen(pt.x, pt.y, transform)
                    painter.drawRect(QtCore.QRectF(ps.x() - 4, ps.y() - 4, 8, 8))
            elif constraint.type is SketchConstraintType.TANGENT and len(constraint.references) == 2:
                refs2 = [point_map.get(pid) for pid in constraint.references[:2]]
                if all(r is not None for r in refs2):
                    p1s = self._to_screen(refs2[0].x, refs2[0].y, transform)
                    p2s = self._to_screen(refs2[1].x, refs2[1].y, transform)
                    mid = QtCore.QPointF(0.5 * (p1s.x() + p2s.x()), 0.5 * (p1s.y() + p2s.y()))
                    painter.drawRect(QtCore.QRectF(mid.x() - 3, mid.y() - 3, 6, 6))

            self._draw_constraint_icon(painter, anchor, constraint.type, color)
            self._screen_sketch_constraints.append((constraint.id, anchor))

    def _draw_bodies(
        self,
        painter: QtGui.QPainter,
        project: Project,
        markers: list[CanvasMarker],
        transform,
    ) -> None:
        self._screen_bodies = []
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
                self._screen_bodies.append((body.id, "point", point))
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
            self._screen_bodies.append((body.id, "closed" if body.closed_shape and len(ordered) >= 3 else "open", polygon))
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
            joint = self.app_service.get_joint(driver.target_joint_id)
            if joint is None:
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

    def _body_at(self, point: QtCore.QPointF) -> str | None:
        project = self.app_service.project
        if project is None:
            return None
        if not self._screen_bodies:
            assembled = self._assembled_mechanism(project)
            markers = self._collect_markers(project, assembled)
            marker_map = {marker.entity_id: marker for marker in markers}
            cached_bodies: list[tuple[str, str, object]] = []
            for body in project.model.bodies:
                structural = [marker_map[marker.id] for marker in body.structural_markers() if marker.id in marker_map]
                if not structural:
                    continue
                if len(structural) == 1:
                    cached_bodies.append((body.id, "point", self._to_screen(structural[0].x, structural[0].y, self._current_transform())))
                    continue
                ordered = [
                    marker_map[marker_id]
                    for marker_id in body.edge_order
                    if marker_id in marker_map and marker_map[marker_id].marker_type is MarkerType.STRUCTURAL
                ]
                if len(ordered) < 2:
                    ordered = structural
                polygon = QtGui.QPolygonF([self._to_screen(marker.x, marker.y, self._current_transform()) for marker in ordered])
                cached_bodies.append((body.id, "closed" if body.closed_shape and len(ordered) >= 3 else "open", polygon))
            self._screen_bodies = cached_bodies
        tolerance = 8.0
        for body_id, shape_kind, shape in reversed(self._screen_bodies):
            if shape_kind == "point":
                center = shape
                if math.hypot(point.x() - center.x(), point.y() - center.y()) <= 12.0:
                    return body_id
                continue
            polygon = shape
            if shape_kind == "closed":
                if polygon.containsPoint(point, QtCore.Qt.FillRule.OddEvenFill):
                    return body_id
            for index in range(len(polygon) - 1):
                line = QtCore.QLineF(polygon[index], polygon[index + 1])
                if line.length() <= 1e-9:
                    continue
                if self._distance_to_segment(point, line) <= tolerance:
                    return body_id
            if shape_kind == "closed" and len(polygon) >= 3:
                line = QtCore.QLineF(polygon[-1], polygon[0])
                if self._distance_to_segment(point, line) <= tolerance:
                    return body_id
        return None

    def _sketch_point_at(self, point: QtCore.QPointF) -> CanvasSketchPoint | None:
        for sketch_point, screen_point in reversed(self._screen_sketch_points):
            if math.hypot(point.x() - screen_point.x(), point.y() - screen_point.y()) <= 8.0:
                return sketch_point
        return None

    def _sketch_entity_at(self, point: QtCore.QPointF) -> CanvasSketchEntity | None:
        tolerance = 7.0
        for entity, geometry in reversed(self._screen_sketch_entities):
            if isinstance(geometry, QtCore.QLineF):
                if self._distance_to_segment(point, geometry) <= tolerance:
                    return entity
            elif isinstance(geometry, QtCore.QRectF):
                center = geometry.center()
                radius = geometry.width() * 0.5
                distance = math.hypot(point.x() - center.x(), point.y() - center.y())
                if abs(distance - radius) <= tolerance:
                    return entity
            elif isinstance(geometry, tuple) and geometry and geometry[0] == "arc":
                rect = geometry[1]
                center = rect.center()
                radius = rect.width() * 0.5
                distance = math.hypot(point.x() - center.x(), point.y() - center.y())
                if abs(distance - radius) <= tolerance:
                    return entity
        return None

    def _update_hover_targets(self, screen_pos: QtCore.QPointF) -> None:
        if self._interaction_mode in ("sketch", "all"):
            hovered_point = self._sketch_point_at(screen_pos)
            self._hovered_sketch_point_id = hovered_point.entity_id if hovered_point is not None else None
            if hovered_point is not None:
                self._hovered_sketch_entity_id = None
                _hovered_is_locked = self._is_point_fixed(hovered_point.entity_id) or (
                    self._dof_result is not None
                    and self._dof_result.point_dof.get(hovered_point.entity_id, 2) == 0
                )
                if self._mode == CanvasMode.SELECT and self._editing_enabled and _hovered_is_locked:
                    self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ForbiddenCursor))
                elif self._mode == CanvasMode.SELECT:
                    self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ArrowCursor))
                return
            hovered_entity = self._sketch_entity_at(screen_pos)
            self._hovered_sketch_entity_id = hovered_entity.entity_id if hovered_entity is not None else None
            if self._mode == CanvasMode.SELECT:
                self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ArrowCursor))
        else:
            self._hovered_sketch_point_id = None
            self._hovered_sketch_entity_id = None

    def _should_draw_sketch_label(self, entity_id: str) -> bool:
        return (
            self._selected_entity_id == entity_id
            or self._hovered_sketch_point_id == entity_id
            or self._hovered_sketch_entity_id == entity_id
            or self._mode in {
                CanvasMode.CREATE_SKETCH_POINT,
                CanvasMode.CREATE_SKETCH_LINE_SEGMENT,
                CanvasMode.CREATE_SKETCH_CIRCLE,
                CanvasMode.CREATE_SKETCH_ARC,
                CanvasMode.CREATE_SKETCH_INFINITE_LINE,
            }
        )

    def _draw_constraint_icon(
        self,
        painter: QtGui.QPainter,
        anchor: QtCore.QPointF,
        constraint_type: SketchConstraintType,
        color: QtGui.QColor,
    ) -> None:
        size = 14.0
        r = QtCore.QRectF(anchor.x() - size / 2, anchor.y() - size / 2, size, size)
        pen = QtGui.QPen(color, 1.2)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        def _line(x1, y1, x2, y2):
            painter.drawLine(
                QtCore.QPointF(r.x() + x1, r.y() + y1),
                QtCore.QPointF(r.x() + x2, r.y() + y2),
            )

        if constraint_type is SketchConstraintType.FIX:
            # Small solid square
            painter.setBrush(QtGui.QBrush(color))
            painter.drawRect(QtCore.QRectF(r.x() + 4, r.y() + 4, 6, 6))
        elif constraint_type is SketchConstraintType.HORIZONTAL:
            _line(2, 7, 12, 7)
            _line(8, 4, 12, 7)
            _line(8, 10, 12, 7)
        elif constraint_type is SketchConstraintType.VERTICAL:
            _line(7, 2, 7, 12)
            _line(4, 6, 7, 2)
            _line(10, 6, 7, 2)
        elif constraint_type is SketchConstraintType.DISTANCE:
            _line(3, 5, 11, 5)
            _line(3, 9, 11, 9)
            _line(2, 3, 2, 7)
            _line(12, 7, 12, 11)
        elif constraint_type is SketchConstraintType.COINCIDENT:
            painter.drawEllipse(QtCore.QRectF(r.x() + 2, r.y() + 4, 6, 6))
            painter.drawEllipse(QtCore.QRectF(r.x() + 6, r.y() + 4, 6, 6))
        elif constraint_type is SketchConstraintType.PARALLEL:
            _line(3, 4, 11, 4)
            _line(3, 10, 11, 10)
        elif constraint_type is SketchConstraintType.PERPENDICULAR:
            _line(3, 3, 3, 11)
            _line(3, 9, 11, 9)
        elif constraint_type is SketchConstraintType.EQUAL_LENGTH:
            _line(2, 5, 12, 5)
            painter.drawText(QtCore.QPointF(r.x() + 4, r.y() + 11), "=")
        elif constraint_type is SketchConstraintType.ANGLE:
            # Small arc with two arms
            painter.drawArc(QtCore.QRectF(r.x() + 2, r.y() + 2, 10, 10), 0, -90 * 16)
            _line(7, 7, 12, 7)
            _line(7, 7, 7, 12)
        elif constraint_type is SketchConstraintType.MIDPOINT:
            _line(2, 7, 12, 7)
            painter.setBrush(QtGui.QBrush(color))
            painter.drawEllipse(QtCore.QPointF(r.x() + 7, r.y() + 7), 2, 2)
        elif constraint_type is SketchConstraintType.COLLINEAR:
            _line(2, 7, 12, 7)
            painter.setBrush(QtGui.QBrush(color))
            painter.drawEllipse(QtCore.QPointF(r.x() + 4, r.y() + 7), 1.5, 1.5)
            painter.drawEllipse(QtCore.QPointF(r.x() + 7, r.y() + 7), 1.5, 1.5)
            painter.drawEllipse(QtCore.QPointF(r.x() + 10, r.y() + 7), 1.5, 1.5)
        elif constraint_type is SketchConstraintType.SYMMETRIC:
            _line(7, 2, 7, 12)
            _line(3, 5, 7, 2)
            _line(3, 9, 7, 12)
        elif constraint_type is SketchConstraintType.ON_CIRCLE:
            painter.drawEllipse(QtCore.QRectF(r.x() + 2, r.y() + 2, 10, 10))
            painter.setBrush(QtGui.QBrush(color))
            painter.drawEllipse(QtCore.QPointF(r.x() + 7, r.y() + 7), 1.5, 1.5)
        elif constraint_type is SketchConstraintType.TANGENT:
            painter.drawEllipse(QtCore.QRectF(r.x() + 2, r.y() + 4, 8, 8))
            _line(8, 2, 12, 6)

    def _draw_distance_annotation(
        self,
        painter: QtGui.QPainter,
        s1: QtCore.QPointF,
        s2: QtCore.QPointF,
        constraint: SketchConstraint,
        color: QtGui.QColor,
        transform,
    ) -> None:
        dx = s2.x() - s1.x()
        dy = s2.y() - s1.y()
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return
        ux = dx / length
        uy = dy / length
        offset = 18.0
        # Extension-line end points on the dimension line
        d1 = QtCore.QPointF(s1.x() - uy * offset, s1.y() + ux * offset)
        d2 = QtCore.QPointF(s2.x() - uy * offset, s2.y() + ux * offset)
        painter.setPen(QtGui.QPen(color, 0.8, QtCore.Qt.PenStyle.DashLine))
        painter.drawLine(s1, d1)
        painter.drawLine(s2, d2)
        painter.setPen(QtGui.QPen(color, 1.0))
        painter.drawLine(d1, d2)
        # Arrow heads
        self._draw_arrow(painter, d1, ux, uy, color)
        self._draw_arrow(painter, d2, -ux, -uy, color)
        # Text
        text = "?"
        if constraint.value is not None:
            try:
                project = self.app_service.project
                result = self.app_service.expression_service.evaluate_property(
                    constraint.value, project.parameters
                )
                text = f"{result.value:.4g} {result.unit}"
            except Exception:
                pass
        mid = QtCore.QPointF(0.5 * (d1.x() + d2.x()), 0.5 * (d1.y() + d2.y()))
        painter.setPen(QtGui.QPen(color))
        painter.drawText(mid + QtCore.QPointF(4, -4), text)

    def _draw_angle_annotation(
        self,
        painter: QtGui.QPainter,
        vscreen: QtCore.QPointF,
        start_deg: float,
        end_deg: float,
        radius_px: float,
        constraint: SketchConstraint,
        color: QtGui.QColor,
    ) -> None:
        # Arrow heads at arc ends
        start_rad = math.radians(-start_deg)
        end_rad = math.radians(-end_deg)
        a1 = QtCore.QPointF(vscreen.x() + radius_px * math.cos(start_rad), vscreen.y() + radius_px * math.sin(start_rad))
        a2 = QtCore.QPointF(vscreen.x() + radius_px * math.cos(end_rad), vscreen.y() + radius_px * math.sin(end_rad))
        tangent1 = (-math.sin(start_rad), math.cos(start_rad))
        tangent2 = (-math.sin(end_rad), math.cos(end_rad))
        self._draw_arrow(painter, a1, tangent1[0], tangent1[1], color)
        self._draw_arrow(painter, a2, tangent2[0], tangent2[1], color)
        # Text
        text = "?°"
        if constraint.value is not None:
            try:
                project = self.app_service.project
                val_rad = self.app_service.expression_service.evaluate_property(
                    constraint.value, project.parameters
                ).value
                text = f"{math.degrees(val_rad):.1f}°"
            except Exception:
                pass
        bisect_deg = (start_deg + end_deg) / 2
        bisect_rad = math.radians(-bisect_deg)
        label_radius = radius_px + 10
        label_pos = QtCore.QPointF(
            vscreen.x() + label_radius * math.cos(bisect_rad),
            vscreen.y() + label_radius * math.sin(bisect_rad),
        )
        painter.setPen(QtGui.QPen(color))
        painter.drawText(label_pos, text)

    def _draw_arrow(
        self,
        painter: QtGui.QPainter,
        tip: QtCore.QPointF,
        ux: float,
        uy: float,
        color: QtGui.QColor,
    ) -> None:
        size = 4.0
        ax = -uy * size
        ay = ux * size
        painter.setPen(QtGui.QPen(color, 1.0))
        painter.drawLine(tip, QtCore.QPointF(tip.x() + ux * size + ax, tip.y() + uy * size + ay))
        painter.drawLine(tip, QtCore.QPointF(tip.x() + ux * size - ax, tip.y() + uy * size - ay))

    def _draw_sketch_label(
        self,
        painter: QtGui.QPainter,
        anchor: QtCore.QPointF,
        text: str,
        color: QtGui.QColor,
    ) -> None:
        metrics = painter.fontMetrics()
        rect = metrics.boundingRect(text)
        bubble = QtCore.QRectF(
            anchor.x() - 4.0,
            anchor.y() - rect.height() + 1.0,
            rect.width() + 8.0,
            rect.height() + 4.0,
        )
        painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        painter.setBrush(QtGui.QBrush(QtGui.QColor(250, 248, 242, 215)))
        painter.drawRoundedRect(bubble, 4.0, 4.0)
        painter.setPen(QtGui.QPen(color))
        painter.drawText(anchor, text)

    def _sketch_entity_label_anchor(
        self,
        entity: CanvasSketchEntity,
        geometry: object,
    ) -> QtCore.QPointF | None:
        if isinstance(geometry, QtCore.QLineF):
            return geometry.center() + QtCore.QPointF(6.0, -8.0)
        if isinstance(geometry, QtCore.QRectF):
            return geometry.topRight() + QtCore.QPointF(6.0, -4.0)
        if isinstance(geometry, tuple) and geometry and geometry[0] == "arc":
            rect = geometry[1]
            return rect.topRight() + QtCore.QPointF(6.0, -4.0)
        return None

    def _sketch_entity_anchor(
        self,
        entity: CanvasSketchEntity,
        point_map: dict[str, CanvasSketchPoint],
    ) -> tuple[float, float] | None:
        if entity.entity_type is SketchEntityType.CIRCLE and entity.point_ids[0] in point_map:
            center = point_map[entity.point_ids[0]]
            return center.x, center.y
        coords = [point_map[point_id] for point_id in entity.point_ids if point_id in point_map]
        if not coords:
            return None
        return (
            sum(point.x for point in coords) / len(coords),
            sum(point.y for point in coords) / len(coords),
        )

    def _resolve_or_create_sketch_point(
        self,
        world: tuple[float, float],
        clicked_point: CanvasSketchPoint | None,
    ) -> str:
        if clicked_point is not None:
            return clicked_point.entity_id
        project = self.app_service.project
        if project is not None and project.sketch is not None:
            for point in self._collect_sketch_points(project):
                if math.hypot(point.x - world[0], point.y - world[1]) <= 1e-6:
                    return point.entity_id
        return self.app_service.create_sketch_point(self._mm_expression(world[0]), self._mm_expression(world[1]))

    def _finalize_sketch_creation(self) -> None:
        point_ids = list(self._sensor_marker_ids)
        self._sensor_marker_ids = []
        self._creation_points.clear()
        created_id: str | None = None
        if self._mode == CanvasMode.CREATE_SKETCH_LINE_SEGMENT:
            created_id = self.app_service.create_sketch_line_segment(point_ids[0], point_ids[1])
            message = "Created sketch line segment"
        elif self._mode == CanvasMode.CREATE_SKETCH_CIRCLE:
            p1 = self.app_service.get_sketch_point(point_ids[0])
            p2 = self.app_service.get_sketch_point(point_ids[1])
            if p1 is None or p2 is None:
                raise ValueError("Sketch point not found for circle creation")
            x1 = self.app_service.expression_service.evaluate_property(p1.x, self.app_service.project.parameters).value
            y1 = self.app_service.expression_service.evaluate_property(p1.y, self.app_service.project.parameters).value
            x2 = self.app_service.expression_service.evaluate_property(p2.x, self.app_service.project.parameters).value
            y2 = self.app_service.expression_service.evaluate_property(p2.y, self.app_service.project.parameters).value
            radius = math.hypot(x2 - x1, y2 - y1)
            created_id = self.app_service.create_sketch_circle(point_ids[0], self._mm_expression(radius))
            message = "Created sketch circle"
        elif self._mode == CanvasMode.CREATE_SKETCH_ARC:
            created_id = self.app_service.create_sketch_arc(point_ids[0], point_ids[1], point_ids[2])
            message = "Created sketch arc"
        elif self._mode == CanvasMode.CREATE_SKETCH_ARC_CENTER:
            pts = [self.app_service.get_sketch_point(pid) for pid in point_ids[:3]]
            if any(p is None for p in pts):
                raise ValueError("Sketch point not found for arc creation")
            coords = [
                (self.app_service.expression_service.evaluate_property(p.x, self.app_service.project.parameters).value,
                 self.app_service.expression_service.evaluate_property(p.y, self.app_service.project.parameters).value)
                for p in pts
            ]
            created_id = self.app_service.create_sketch_arc_by_center(
                coords[0][0], coords[0][1],
                coords[1][0], coords[1][1],
                coords[2][0], coords[2][1],
            )
            message = "Created sketch arc (center mode)"
        elif self._mode == CanvasMode.CREATE_SKETCH_INFINITE_LINE:
            created_id = self.app_service.create_sketch_infinite_line(point_ids[0], point_ids[1])
            message = "Created sketch infinite line"
        else:
            return
        if created_id is not None:
            self.entitySelected.emit(created_id)
        self.modelChanged.emit(message)
        self.set_mode(CanvasMode.SELECT)

    def _canvas_sketch_point_by_id(self, pid: str) -> CanvasSketchPoint | None:
        for cpt, _ in self._screen_sketch_points:
            if cpt.entity_id == pid:
                return cpt
        return None

    def _nearest_endpoint_of_entity(
        self, entity: CanvasSketchEntity, click_screen: QtCore.QPointF
    ) -> str | None:
        """Return the point_id of the entity endpoint closest to click_screen."""
        best_id = None
        best_dist = float("inf")
        transform = self._current_transform()
        for pid in entity.point_ids:
            pt = self._canvas_sketch_point_by_id(pid)
            if pt is None:
                continue
            sp = self._to_screen(pt.x, pt.y, transform)
            d = math.hypot(sp.x() - click_screen.x(), sp.y() - click_screen.y())
            if d < best_dist:
                best_dist = d
                best_id = pid
        return best_id

    def _handle_constraint_input_click(
        self,
        clicked_sketch_point: CanvasSketchPoint | None,
        clicked_sketch_entity: CanvasSketchEntity | None,
        n_pts: int,
        n_ent: int,
    ) -> None:
        """Accumulate point/entity inputs for the current constraint mode."""
        pts_left = n_pts - len(self._sensor_marker_ids)
        ent_left = n_ent - len(self._creation_entity_ids)

        # CONCENTRIC: circle click resolves to center point ID
        if self._mode == CanvasMode.CREATE_SKETCH_CONCENTRIC:
            if (clicked_sketch_entity is not None
                    and clicked_sketch_entity.entity_type in (SketchEntityType.CIRCLE, SketchEntityType.ARC)
                    and pts_left > 0):
                center_id = clicked_sketch_entity.point_ids[0]
                cpt = self._canvas_sketch_point_by_id(center_id)
                if cpt:
                    self._creation_points.append((cpt.x, cpt.y))
                    self._sensor_marker_ids.append(center_id)
            elif clicked_sketch_point is not None and pts_left > 0:
                self._creation_points.append((clicked_sketch_point.x, clicked_sketch_point.y))
                self._sensor_marker_ids.append(clicked_sketch_point.entity_id)

        # Constraints expecting entity refs (ON_CIRCLE, TANGENT)
        elif n_ent > 0:
            if (clicked_sketch_entity is not None
                    and clicked_sketch_entity.entity_type in (SketchEntityType.CIRCLE, SketchEntityType.ARC)
                    and ent_left > 0):
                self._creation_entity_ids.append(clicked_sketch_entity.entity_id)
            elif (clicked_sketch_entity is not None
                    and clicked_sketch_entity.entity_type in (SketchEntityType.LINE_SEGMENT, SketchEntityType.INFINITE_LINE)
                    and pts_left >= 2):
                for pid in clicked_sketch_entity.point_ids[:2]:
                    cpt = self._canvas_sketch_point_by_id(pid)
                    if cpt:
                        self._creation_points.append((cpt.x, cpt.y))
                        self._sensor_marker_ids.append(pid)
            elif clicked_sketch_point is not None and pts_left > 0:
                self._creation_points.append((clicked_sketch_point.x, clicked_sketch_point.y))
                self._sensor_marker_ids.append(clicked_sketch_point.entity_id)

        # Point-only constraints: line click → nearest endpoint only (1 slot)
        else:
            if (clicked_sketch_entity is not None
                    and clicked_sketch_entity.entity_type in (SketchEntityType.LINE_SEGMENT, SketchEntityType.INFINITE_LINE)
                    and pts_left > 0):
                nearest_id = self._nearest_endpoint_of_entity(
                    clicked_sketch_entity, self._last_mouse_screen
                )
                if nearest_id is not None:
                    cpt = self._canvas_sketch_point_by_id(nearest_id)
                    if cpt:
                        self._creation_points.append((cpt.x, cpt.y))
                        self._sensor_marker_ids.append(nearest_id)
            elif clicked_sketch_point is not None and pts_left > 0:
                self._creation_points.append((clicked_sketch_point.x, clicked_sketch_point.y))
                self._sensor_marker_ids.append(clicked_sketch_point.entity_id)

        collected_pts = min(len(self._sensor_marker_ids), n_pts)
        collected_ents = min(len(self._creation_entity_ids), n_ent)
        if n_ent > 0:
            self.modelChanged.emit(
                f"{_CONSTRAINT_LABEL.get(self._mode, 'Constraint')}: "
                f"{collected_pts}/{n_pts} points, {collected_ents}/{n_ent} curves"
            )
        else:
            self.modelChanged.emit(
                f"{_CONSTRAINT_LABEL.get(self._mode, 'Constraint')}: "
                f"{collected_pts}/{n_pts} points"
            )
        if len(self._sensor_marker_ids) >= n_pts and len(self._creation_entity_ids) >= n_ent:
            self._finalize_sketch_constraint_creation()

    def _finalize_sketch_constraint_creation(self) -> None:
        n_pts = _CONSTRAINT_SPEC.get(self._mode, (2, 0))[0]
        point_ids = list(self._sensor_marker_ids[:n_pts])
        entity_refs = list(self._creation_entity_ids)
        self._sensor_marker_ids = []
        self._creation_entity_ids = []
        self._creation_points.clear()

        # CONCENTRIC creates a COINCIDENT on the two circle centers
        if self._mode == CanvasMode.CREATE_SKETCH_CONCENTRIC:
            constraint_type_str = SketchConstraintType.COINCIDENT.value
        else:
            constraint_type_str = _SKETCH_CONSTRAINT_TYPE_STR.get(self._mode)
        if constraint_type_str is None:
            return

        value_str: str | None = None
        if self._mode == CanvasMode.CREATE_SKETCH_ANGLE:
            try:
                default_deg = self.app_service._current_sketch_angle_degrees(
                    point_ids[0], point_ids[1], point_ids[2]
                )
            except Exception:
                default_deg = 90.0
            angle_deg, ok = QtWidgets.QInputDialog.getDouble(
                self, "Angle Constraint", "Angle between arms (degrees):",
                default_deg, -359.9999, 359.9999, 3,
            )
            if not ok:
                self.set_mode(CanvasMode.SELECT)
                return
            value_str = str(angle_deg)
        elif self._mode == CanvasMode.CREATE_SKETCH_TANGENT:
            items = ["External (+1)", "Internal (-1)"]
            item, ok = QtWidgets.QInputDialog.getItem(
                self, "Tangent Constraint", "Tangency type:", items, 0, False
            )
            if not ok:
                self.set_mode(CanvasMode.SELECT)
                return
            value_str = "1" if item == items[0] else "-1"

        try:
            constraint_id = self.app_service.create_sketch_constraint(
                constraint_type_str, point_ids,
                value=value_str,
                entity_references=entity_refs if entity_refs else None,
            )
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Constraint error", str(exc))
            self.set_mode(CanvasMode.SELECT)
            return
        self.entitySelected.emit(constraint_id)
        self.modelChanged.emit(f"Created sketch {constraint_type_str} constraint")
        self.set_mode(CanvasMode.SELECT)

    def _snap_world(
        self,
        world: tuple[float, float],
        include_model: bool,
        exclude_point_id: str | None = None,
    ) -> tuple[float, float]:
        project = self.app_service.project
        if project is None or project.sketch is None or not project.sketch.visible:
            return world
        candidates: list[tuple[float, float, float]] = []
        sketch_points = self._collect_sketch_points(project)
        point_map = {point.entity_id: point for point in sketch_points}
        threshold = 8.0 / max(self._current_transform()[0], 1e-9)
        for point in sketch_points:
            if point.entity_id == exclude_point_id:
                continue
            distance = math.hypot(world[0] - point.x, world[1] - point.y)
            candidates.append((distance, point.x, point.y))
        for entity in self._collect_sketch_entities(project):
            snapped = self._snap_to_sketch_entity(world, entity, point_map)
            if snapped is None:
                continue
            distance = math.hypot(world[0] - snapped[0], world[1] - snapped[1])
            candidates.append((distance, snapped[0], snapped[1]))
        if include_model:
            assembled = self._assembled_mechanism(project)
            for marker in self._collect_markers(project, assembled):
                distance = math.hypot(world[0] - marker.x, world[1] - marker.y)
                candidates.append((distance, marker.x, marker.y))
        self._snap_to_point = False
        if candidates:
            best = min(candidates, key=lambda item: item[0])
            if best[0] <= threshold:
                self._snap_to_point = True
                return best[1], best[2]
        return world

    def _snap_to_sketch_entity(
        self,
        world: tuple[float, float],
        entity: CanvasSketchEntity,
        point_map: dict[str, CanvasSketchPoint],
    ) -> tuple[float, float] | None:
        if entity.entity_type is SketchEntityType.LINE_SEGMENT:
            p1 = point_map.get(entity.point_ids[0])
            p2 = point_map.get(entity.point_ids[1])
            if p1 is None or p2 is None:
                return None
            return self._project_point_to_segment(world, (p1.x, p1.y), (p2.x, p2.y))
        if entity.entity_type is SketchEntityType.CIRCLE:
            center = point_map.get(entity.point_ids[0])
            if center is None or entity.radius is None:
                return None
            return self._project_point_to_circle(world, (center.x, center.y), entity.radius)
        if entity.entity_type is SketchEntityType.ARC:
            arc_points = [point_map.get(point_id) for point_id in entity.point_ids]
            if any(point is None for point in arc_points):
                return None
            return self._project_point_to_arc(
                world,
                [(point.x, point.y) for point in arc_points if point is not None],
            )
        if entity.entity_type is SketchEntityType.INFINITE_LINE:
            p1 = point_map.get(entity.point_ids[0])
            p2 = point_map.get(entity.point_ids[1])
            if p1 is None or p2 is None:
                return None
            return self._project_point_to_line(world, (p1.x, p1.y), (p2.x, p2.y))
        return None

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
                CanvasMode.CREATE_SKETCH_HORIZONTAL,
                CanvasMode.CREATE_SKETCH_VERTICAL,
                CanvasMode.CREATE_SKETCH_DISTANCE,
                CanvasMode.CREATE_SKETCH_COINCIDENT,
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
        if self._slider_joint_start is not None and self._hover_world is not None:
            painter.setPen(QtGui.QPen(QtGui.QColor("#8d6cab"), 2.0, QtCore.Qt.PenStyle.DashLine))
            if isinstance(self._slider_joint_start, CanvasMarker):
                start = self._to_screen(self._slider_joint_start.x, self._slider_joint_start.y, transform)
            else:
                start = self._to_screen(
                    self._slider_joint_start.origin_x,
                    self._slider_joint_start.origin_y,
                    transform,
                )
            end = self._to_screen(self._hover_world[0], self._hover_world[1], transform)
            painter.drawLine(start, end)
        if self._mode in {
            CanvasMode.CREATE_SKETCH_POINT,
            CanvasMode.CREATE_SKETCH_LINE_SEGMENT,
            CanvasMode.CREATE_SKETCH_CIRCLE,
            CanvasMode.CREATE_SKETCH_ARC,
            CanvasMode.CREATE_SKETCH_INFINITE_LINE,
        } and self._hover_world is not None:
            preview = self._snap_preview_world or self._hover_world
            preview_point = self._to_screen(preview[0], preview[1], transform)
            painter.setPen(QtGui.QPen(QtGui.QColor("#8b8f96"), 1.6, QtCore.Qt.PenStyle.DashLine))
            self._draw_sketch_creation_preview(painter, transform, preview, preview_point)
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#8b8f96")))
            painter.drawEllipse(preview_point, 3.5, 3.5)
        if self._snap_preview_world is not None:
            snap_point = self._to_screen(self._snap_preview_world[0], self._snap_preview_world[1], transform)
            if self._snap_to_point:
                painter.setPen(QtGui.QPen(QtGui.QColor("#4caf50"), 1.8))
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawEllipse(snap_point, 8.0, 8.0)
            else:
                painter.setPen(QtGui.QPen(QtGui.QColor("#c75b12"), 1.4))
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawEllipse(snap_point, 6.5, 6.5)
                painter.drawLine(snap_point + QtCore.QPointF(-8.0, 0.0), snap_point + QtCore.QPointF(8.0, 0.0))
                painter.drawLine(snap_point + QtCore.QPointF(0.0, -8.0), snap_point + QtCore.QPointF(0.0, 8.0))

    def _draw_sketch_creation_preview(
        self,
        painter: QtGui.QPainter,
        transform,
        preview_world: tuple[float, float],
        preview_point: QtCore.QPointF,
    ) -> None:
        if self._mode == CanvasMode.CREATE_SKETCH_POINT:
            return
        preview_points = [self._to_screen(x, y, transform) for x, y in self._creation_points]
        if self._mode == CanvasMode.CREATE_SKETCH_LINE_SEGMENT:
            preview_points.append(preview_point)
            if len(preview_points) >= 2:
                painter.drawPolyline(QtGui.QPolygonF(preview_points))
            return
        if self._mode == CanvasMode.CREATE_SKETCH_CIRCLE and len(self._creation_points) == 1:
            center_world = self._creation_points[0]
            center_screen = self._to_screen(center_world[0], center_world[1], transform)
            radius = math.hypot(preview_world[0] - center_world[0], preview_world[1] - center_world[1])
            radius_px = abs(radius * transform[0])
            rect = QtCore.QRectF(
                center_screen.x() - radius_px,
                center_screen.y() - radius_px,
                2.0 * radius_px,
                2.0 * radius_px,
            )
            painter.drawEllipse(rect)
            painter.drawLine(center_screen, preview_point)
            return
        if self._mode == CanvasMode.CREATE_SKETCH_ARC:
            if len(self._creation_points) < 2:
                preview_points.append(preview_point)
                if len(preview_points) >= 2:
                    painter.drawPolyline(QtGui.QPolygonF(preview_points))
                return
            arc = self._arc_geometry_from_tuples(
                [self._creation_points[0], self._creation_points[1], preview_world]
            )
            if arc is None:
                preview_points.append(preview_point)
                painter.drawPolyline(QtGui.QPolygonF(preview_points))
                return
            center_x, center_y, radius, start_angle, span_angle = arc
            center = self._to_screen(center_x, center_y, transform)
            radius_px = abs(radius * transform[0])
            rect = QtCore.QRectF(
                center.x() - radius_px,
                center.y() - radius_px,
                2.0 * radius_px,
                2.0 * radius_px,
            )
            painter.drawArc(rect, int(-math.degrees(start_angle) * 16), int(-math.degrees(span_angle) * 16))
            return
        if self._mode == CanvasMode.CREATE_SKETCH_ARC_CENTER:
            n = len(self._creation_points)
            if n == 0:
                return
            cx, cy = self._creation_points[0]
            center_screen = self._to_screen(cx, cy, transform)
            radius = math.hypot(preview_world[0] - cx, preview_world[1] - cy)
            if n == 1:
                # Show circle ghost with radius to cursor
                radius_px = abs(radius * transform[0])
                rect = QtCore.QRectF(
                    center_screen.x() - radius_px, center_screen.y() - radius_px,
                    2.0 * radius_px, 2.0 * radius_px,
                )
                painter.drawEllipse(rect)
                painter.drawLine(center_screen, preview_point)
            else:
                # n == 2: show arc from start to cursor (shortest span)
                sx, sy = self._creation_points[1]
                r2 = math.hypot(sx - cx, sy - cy)
                if r2 < 1e-9:
                    return
                radius_px = abs(r2 * transform[0])
                rect = QtCore.QRectF(
                    center_screen.x() - radius_px, center_screen.y() - radius_px,
                    2.0 * radius_px, 2.0 * radius_px,
                )
                start_deg = math.degrees(math.atan2(-(sy - cy), sx - cx))
                end_deg = math.degrees(math.atan2(-(preview_world[1] - cy), preview_world[0] - cx))
                span = (end_deg - start_deg + 180.0) % 360.0 - 180.0
                painter.drawArc(rect, int(start_deg * 16), int(span * 16))
            return
        if self._mode == CanvasMode.CREATE_SKETCH_INFINITE_LINE and len(self._creation_points) == 1:
            p1 = self._creation_points[0]
            p2 = preview_world
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length = math.hypot(dx, dy)
            if length <= 1e-9:
                return
            ux = dx / length
            uy = dy / length
            span = max(self.width(), self.height()) / max(transform[0], 1e-9) * 1.2
            start = self._to_screen(p1[0] - ux * span, p1[1] - uy * span, transform)
            end = self._to_screen(p1[0] + ux * span, p1[1] + uy * span, transform)
            painter.drawLine(start, end)

    def _sketch_constraint_anchor(
        self,
        constraint: SketchConstraint,
        point_map: dict[str, CanvasSketchPoint],
        transform,
    ) -> QtCore.QPointF | None:
        refs = [point_map.get(point_id) for point_id in constraint.references]
        refs = [point for point in refs if point is not None]
        if not refs:
            return None
        if len(refs) == 1:
            point = refs[0]
            return self._to_screen(point.x, point.y, transform) + QtCore.QPointF(10.0, 18.0)
        midpoint_x = sum(point.x for point in refs) / len(refs)
        midpoint_y = sum(point.y for point in refs) / len(refs)
        return self._to_screen(midpoint_x, midpoint_y, transform) + QtCore.QPointF(8.0, -10.0)

    def _append_creation_point(self, world: tuple[float, float]) -> None:
        if self._creation_points:
            last_x, last_y = self._creation_points[-1]
            if math.hypot(world[0] - last_x, world[1] - last_y) < 1e-6:
                return
        self._creation_points.append(world)

    def _handle_marker_click_during_creation(self, clicked_marker: CanvasMarker) -> None:
        if not self._require_editing():
            return
        details = self._request_creation_marker_joint(clicked_marker)
        if details is None:
            self._creation_points.clear()
            self.set_mode(CanvasMode.SELECT)
            self.update()
            return
        joint_name, joint_type = details
        new_marker_index = len(self._creation_points)
        self._creation_points.append((clicked_marker.x, clicked_marker.y))
        if joint_name is not None and joint_type is not None:
            self._pending_joint_creation = {
                "clicked_marker_id": clicked_marker.entity_id,
                "clicked_body_id": clicked_marker.body_id,
                "joint_type": joint_type,
                "joint_name": joint_name,
                "new_marker_index": new_marker_index,
                "creation_mode": self._mode,
            }
        self.update()

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
        if self._pending_joint_creation:
            self._create_pending_joint(body_id)
        self.modelChanged.emit(f"Created {name}")
        self.set_mode(CanvasMode.SELECT)

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
        if self._pending_joint_creation:
            self._create_pending_joint(body_id)
        self.modelChanged.emit(f"Created {name}")
        self.set_mode(CanvasMode.SELECT)

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
        self.set_mode(CanvasMode.SELECT)

    def _create_pending_joint(self, new_body_id: str) -> None:
        if not self._pending_joint_creation:
            return
        clicked_marker_id = self._pending_joint_creation.get("clicked_marker_id")
        clicked_body_id = self._pending_joint_creation.get("clicked_body_id")
        joint_type = self._pending_joint_creation.get("joint_type")
        joint_name = self._pending_joint_creation.get("joint_name")
        new_marker_index = self._pending_joint_creation.get("new_marker_index")
        creation_mode = self._pending_joint_creation.get("creation_mode")
        if (
            not isinstance(clicked_marker_id, str)
            or not isinstance(clicked_body_id, str)
            or not isinstance(joint_type, str)
            or not isinstance(joint_name, str)
            or not isinstance(new_marker_index, int)
        ):
            self._pending_joint_creation = None
            return
        new_body = next(
            (b for b in self.app_service.project.model.bodies if b.id == new_body_id), None
        )
        if not new_body:
            self._pending_joint_creation = None
            return
        structural = new_body.structural_markers()
        if creation_mode not in {CanvasMode.CREATE_BAR, CanvasMode.CREATE_BODY}:
            self._pending_joint_creation = None
            return
        if new_marker_index < 0 or new_marker_index >= len(structural):
            self._pending_joint_creation = None
            return
        new_marker_id = structural[new_marker_index].id
        if joint_type == "rigid":
            self.app_service.create_rigid_joint(
                joint_name,
                JointEndpointInput(JointEndpointKind.MARKER, body_id=clicked_body_id, marker_id=clicked_marker_id),
                JointEndpointInput(JointEndpointKind.MARKER, body_id=new_body_id, marker_id=new_marker_id),
            )
        else:
            self.app_service.create_joint(
                joint_name,
                "revolute",
                JointEndpointInput(JointEndpointKind.MARKER, body_id=clicked_body_id, marker_id=clicked_marker_id),
                JointEndpointInput(JointEndpointKind.MARKER, body_id=new_body_id, marker_id=new_marker_id),
            )
        self.modelChanged.emit(f"Created {joint_name}")
        self._pending_joint_creation = None

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
        self.set_mode(CanvasMode.SELECT)

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
        self.set_mode(CanvasMode.SELECT)

    def _create_slider_joint(
        self,
        marker: CanvasMarker,
        slider: CanvasSlider,
        *,
        align: str = "marker_to_slider",
    ) -> None:
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
            align=align,
        )
        self.entitySelected.emit(joint_id)
        self.modelChanged.emit(f"Created {name}")
        self.set_mode(CanvasMode.SELECT)

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
        self.set_mode(CanvasMode.SELECT)

    def _selected_body(self, fallback_body: str | None = None) -> Body | None:
        if fallback_body is not None:
            return self.app_service.get_body(fallback_body)
        if self._selected_entity_id is None:
            return None
        entity = self.app_service.get_entity(self._selected_entity_id)
        if entity is None:
            return None
        if isinstance(entity, Body):
            return entity
        if hasattr(entity, "body_id"):
            return self.app_service.get_body(entity.body_id)
        return self.app_service.get_body_by_marker(self._selected_entity_id)

    def _mm_expression(self, value: float) -> str:
        return f"{value:.3f} mm"

    def _deg_expression(self, value: float) -> str:
        return f"{value:.6f} deg"

    def _marker_label(self, marker_id: str) -> str:
        marker = self.app_service.get_entity(marker_id)
        body = self.app_service.get_body_by_marker(marker_id)
        if marker is not None and body is not None:
            return f"{body.name}.{marker.name}"
        return marker_id

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

    def _request_creation_marker_joint(self, clicked_marker: CanvasMarker) -> tuple[str | None, str | None] | None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Existing Marker")
        layout = QtWidgets.QFormLayout(dialog)
        message = QtWidgets.QLabel(
            f"A marker '{clicked_marker.name}' exists at this location.\n"
            "Create the new marker here and optionally connect it."
        )
        layout.addRow(message)
        joint_name = QtWidgets.QLineEdit(
            self._next_name("Joint", [joint.name for joint in self.app_service.project.model.joints])
        )
        type_combo = QtWidgets.QComboBox()
        type_combo.addItems(["revolute", "rigid"])
        layout.addRow("Joint name:", joint_name)
        layout.addRow("Joint type:", type_combo)
        buttons = QtWidgets.QDialogButtonBox(self)
        connect_button = buttons.addButton("Create joint", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        no_joint_button = buttons.addButton("No joint", QtWidgets.QDialogButtonBox.ButtonRole.DestructiveRole)
        cancel_button = buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        layout.addRow(buttons)

        selected: dict[str, str] = {}

        def choose_connect() -> None:
            selected["action"] = "connect"
            dialog.accept()

        def choose_no_joint() -> None:
            selected["action"] = "no_joint"
            dialog.accept()

        def choose_cancel() -> None:
            selected["action"] = "cancel"
            dialog.reject()

        connect_button.clicked.connect(choose_connect)
        no_joint_button.clicked.connect(choose_no_joint)
        cancel_button.clicked.connect(choose_cancel)

        if dialog.exec() != int(QtWidgets.QDialog.DialogCode.Accepted):
            return None
        if selected.get("action") == "no_joint":
            return None, None
        name = joint_name.text().strip()
        if not name:
            return None
        return name, type_combo.currentText()

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
        entity = self.app_service.get_entity(entity_id)
        if entity is None:
            return
        old_name = entity.name
        name, accepted = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=entity.name)
        if not accepted or not name.strip():
            return
        self.app_service.rename_entity(entity_id, name.strip())
        self.modelChanged.emit(f"Renamed {old_name} to {name.strip()}")

    def _toggle_joint_type(self, joint_id: str) -> None:
        if not self._require_editing():
            return
        joint = self.app_service.get_joint(joint_id)
        if joint is None:
            return
        target = JointType.RIGID.value if joint.type is JointType.REVOLUTE else JointType.REVOLUTE.value
        self.app_service.set_joint_type(joint_id, target)
        self.modelChanged.emit(f"Joint {joint.name} set to {target}")

    def _edit_driver_law_dialog(self, driver_id: str) -> None:
        if not self._require_editing():
            return
        driver = self.app_service.get_entity(driver_id)
        if driver is None or not hasattr(driver, "law"):
            return
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
        body = self.app_service.get_body(body_id)
        if body is None:
            return None, None
        marker = next((item for item in body.markers if item.id == marker_id), None)
        if marker is None:
            return None, None
        x = self.app_service.expression_service.evaluate_property(marker.x, project.parameters).value
        y = self.app_service.expression_service.evaluate_property(marker.y, project.parameters).value
        return x, y

    def _slider_preview_for_handle(
        self,
        slider_id: str,
        handle_kind: str,
        world: tuple[float, float],
    ) -> dict[str, float]:
        slider = self.app_service.get_entity(slider_id)
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
                "angle_deg": angle,
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

    def _create_driver_for_joint(self, joint_id: str, driver_type: str) -> None:
        if not self._require_editing():
            return
        joint = self.app_service.get_joint(joint_id)
        if joint is None:
            self.modelChanged.emit("Invalid joint selected")
            return
        default_name = self._next_name(
            "RotationDriver" if driver_type == "rotation" else "TranslationDriver",
            [driver.name for driver in self.app_service.project.model.drivers],
        )
        name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Create Driver",
            "Driver name:",
            text=default_name,
        )
        if not accepted or not name.strip():
            self.set_mode(CanvasMode.SELECT)
            return
        default_law = "20 deg * t / 1 s" if driver_type == "rotation" else "10 mm * t / 1 s"
        law, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Create Driver",
            "Driver law:",
            text=default_law,
        )
        if not accepted or not law.strip():
            self.set_mode(CanvasMode.SELECT)
            return
        try:
            self.app_service.create_driver(
                name.strip(),
                driver_type,
                joint_id,
                law.strip(),
                "deg" if driver_type == "rotation" else "mm",
            )
            self.modelChanged.emit(f"Created {driver_type} driver {name.strip()}")
            self.set_mode(CanvasMode.SELECT)
        except Exception as exc:  # pragma: no cover - UI feedback
            self.modelChanged.emit(f"Driver creation failed: {exc}")
            self.set_mode(CanvasMode.SELECT)

    def _handle_sensor_marker_selection(self, marker: CanvasMarker, required_count: int) -> None:
        mid = marker.entity_id
        if mid in self._sensor_marker_ids:
            return  # duplicate, ignore
        self._sensor_marker_ids.append(mid)
        self.entitySelected.emit(mid)
        self.update()
        remaining = required_count - len(self._sensor_marker_ids)
        if remaining > 0:
            noun = "marker" if remaining == 1 else "markers"
            self.modelChanged.emit(f"Select {remaining} more {noun}")
            return
        ids = list(self._sensor_marker_ids)
        self._sensor_marker_ids = []
        self._create_sensor_from_markers(ids, self._get_sensor_type())

    def _get_sensor_type(self) -> str:
        mode_map = {
            CanvasMode.CREATE_DISTANCE_SENSOR: "distance",
            CanvasMode.CREATE_ANGLE_HORIZONTAL_SENSOR: "angle_horizontal",
            CanvasMode.CREATE_ANGLE_VERTICAL_SENSOR: "angle_vertical",
            CanvasMode.CREATE_ANGLE_VECTOR_SENSOR: "angle_vector",
        }
        return mode_map.get(self._mode, "point")

    def _create_sensor_from_markers(self, marker_ids: list[str], sensor_type: str) -> None:
        if not self._require_editing():
            return
        type_labels = {
            "point": "Point Sensor",
            "distance": "Distance Sensor",
            "angle_horizontal": "Angle (Horizontal) Sensor",
            "angle_vertical": "Angle (Vertical) Sensor",
            "angle_vector": "Angle (Vector) Sensor",
        }
        default_name = self._next_name(
            type_labels.get(sensor_type, "Sensor"),
            [sensor.name for sensor in self.app_service.project.model.sensors],
        )
        name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Create Sensor",
            "Sensor name:",
            text=default_name,
        )
        if not accepted or not name.strip():
            self.set_mode(CanvasMode.SELECT)
            return
        try:
            self.app_service.create_sensor(name.strip(), sensor_type, marker_ids)
            self.modelChanged.emit(f"Created {type_labels.get(sensor_type, 'sensor')} {name.strip()}")
            self.set_mode(CanvasMode.SELECT)
        except Exception as exc:  # pragma: no cover - UI feedback
            self.modelChanged.emit(f"Sensor creation failed: {exc}")
            self.set_mode(CanvasMode.SELECT)

    def _require_editing(self) -> bool:
        if self._editing_enabled:
            if self._edit_guard is None or self._edit_guard():
                return True
            self.modelChanged.emit("Model edit cancelled")
            return False
        self.modelChanged.emit("Editing is only available at t=0")
        return False

    def _offset_point(self, point: QtCore.QPointF, direction: QtCore.QPointF, scale: float) -> QtCore.QPointF:
        return QtCore.QPointF(point.x() + direction.x() * scale, point.y() + direction.y() * scale)
