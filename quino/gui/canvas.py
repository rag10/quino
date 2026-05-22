from __future__ import annotations

import math
from copy import deepcopy
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
    Spring,
    SpringEndpoint,
)
from quino.domain.sketch_constraints import CONSTRAINT_SPECS, ConstraintSpec
from quino.domain.types import BodyType, DriverType, JointEndpointKind, JointType, MarkerType, SketchConstraintType, SketchEntityType, SpringEndpointKind
from quino.services.mechanism_dof import compute_mechanism_dof
from quino.simulation.assembler import AssembledMechanism
from quino.simulation.sensor_expressions import sensor_channel_keys


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
class CanvasGround:
    entity_id: str
    marker_id: str
    name: str
    x: float
    y: float


@dataclass(slots=True)
class CanvasSensorScope:
    sensor_id: str
    box_rect: QtCore.QRectF
    header_rect: QtCore.QRectF
    collapse_rect: QtCore.QRectF
    anchor_point: QtCore.QPointF


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


@dataclass(slots=True)
class SnapCandidate:
    x: float
    y: float
    kind: str
    priority: int
    distance: float
    entity_id: str | None = None



class CanvasMode:
    SELECT = "select"
    CREATE_BAR = "create_bar"
    CREATE_POINT_MASS = "create_point_mass"
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
    CREATE_LOAD = "create_load"
    CREATE_LINEAR_SPRING = "create_linear_spring"
    CREATE_ROTATIONAL_SPRING = "create_rotational_spring"
    CREATE_LINEAR_ACTUATOR = "create_linear_actuator"
    CREATE_ROTATIONAL_ACTUATOR = "create_rotational_actuator"
    CREATE_SKETCH_POINT = "create_sketch_point"
    CREATE_SKETCH_LINE_SEGMENT = "create_sketch_line_segment"
    CREATE_SKETCH_RECTANGLE = "create_sketch_rectangle"
    CREATE_SKETCH_CIRCLE = "create_sketch_circle"
    CREATE_SKETCH_INFINITE_LINE = "create_sketch_infinite_line"
    CREATE_SKETCH_FIX = "create_sketch_fix"
    CREATE_SKETCH_HORIZONTAL = "create_sketch_horizontal"
    CREATE_SKETCH_VERTICAL = "create_sketch_vertical"
    CREATE_SKETCH_DISTANCE = "create_sketch_distance"
    CREATE_SKETCH_HORIZONTAL_DISTANCE = "create_sketch_horizontal_distance"
    CREATE_SKETCH_VERTICAL_DISTANCE = "create_sketch_vertical_distance"
    CREATE_SKETCH_COINCIDENT = "create_sketch_coincident"
    CREATE_SKETCH_PARALLEL = "create_sketch_parallel"
    CREATE_SKETCH_PERPENDICULAR = "create_sketch_perpendicular"
    CREATE_SKETCH_EQUAL_LENGTH = "create_sketch_equal_length"
    CREATE_SKETCH_ANGLE = "create_sketch_angle"
    CREATE_SKETCH_MIDPOINT = "create_sketch_midpoint"
    CREATE_SKETCH_COLLINEAR = "create_sketch_collinear"
    CREATE_SKETCH_SYMMETRIC = "create_sketch_symmetric"
    CREATE_SKETCH_TANGENT = "create_sketch_tangent"
    CREATE_SKETCH_CONCENTRIC = "create_sketch_concentric"
    CREATE_SKETCH_ARC_CENTER = "create_sketch_arc_center"
    POSE_PICK = "pose_pick"


# Map CanvasMode constraint creation strings to SketchConstraintType
_CONSTRAINT_MODE_TO_TYPE: dict[str, SketchConstraintType] = {
    CanvasMode.CREATE_SKETCH_HORIZONTAL:    SketchConstraintType.HORIZONTAL,
    CanvasMode.CREATE_SKETCH_VERTICAL:      SketchConstraintType.VERTICAL,
    CanvasMode.CREATE_SKETCH_DISTANCE:      SketchConstraintType.DISTANCE,
    CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE: SketchConstraintType.HORIZONTAL_DISTANCE,
    CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE: SketchConstraintType.VERTICAL_DISTANCE,
    CanvasMode.CREATE_SKETCH_COINCIDENT:    SketchConstraintType.COINCIDENT,
    CanvasMode.CREATE_SKETCH_PARALLEL:      SketchConstraintType.PARALLEL,
    CanvasMode.CREATE_SKETCH_PERPENDICULAR: SketchConstraintType.PERPENDICULAR,
    CanvasMode.CREATE_SKETCH_EQUAL_LENGTH:  SketchConstraintType.EQUAL_LENGTH,
    CanvasMode.CREATE_SKETCH_ANGLE:         SketchConstraintType.ANGLE,
    CanvasMode.CREATE_SKETCH_MIDPOINT:      SketchConstraintType.MIDPOINT,
    CanvasMode.CREATE_SKETCH_COLLINEAR:     SketchConstraintType.COLLINEAR,
    CanvasMode.CREATE_SKETCH_SYMMETRIC:     SketchConstraintType.SYMMETRIC,
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

# Modes where a single segment click should contribute both endpoints at once.
# The user sees "click 2 segments" instead of "click 4 points".
_SEGMENT_PAIR_MODES: frozenset[str] = frozenset({
    CanvasMode.CREATE_SKETCH_PARALLEL,
    CanvasMode.CREATE_SKETCH_PERPENDICULAR,
    CanvasMode.CREATE_SKETCH_EQUAL_LENGTH,
    CanvasMode.CREATE_SKETCH_COLLINEAR,
})

_LINE_TWO_POINT_CONSTRAINT_MODES: frozenset[str] = frozenset({
    CanvasMode.CREATE_SKETCH_DISTANCE,
    CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE,
    CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE,
})

_SKETCH_CONSTRAINT_TYPE_STR: dict[str, str] = {
    CanvasMode.CREATE_SKETCH_HORIZONTAL:    "horizontal",
    CanvasMode.CREATE_SKETCH_VERTICAL:      "vertical",
    CanvasMode.CREATE_SKETCH_DISTANCE:      "distance",
    CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE: "horizontal_distance",
    CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE: "vertical_distance",
    CanvasMode.CREATE_SKETCH_COINCIDENT:    "coincident",
    CanvasMode.CREATE_SKETCH_PARALLEL:      "parallel",
    CanvasMode.CREATE_SKETCH_PERPENDICULAR: "perpendicular",
    CanvasMode.CREATE_SKETCH_EQUAL_LENGTH:  "equal_length",
    CanvasMode.CREATE_SKETCH_ANGLE:         "angle",
    CanvasMode.CREATE_SKETCH_MIDPOINT:      "midpoint",
    CanvasMode.CREATE_SKETCH_COLLINEAR:     "collinear",
    CanvasMode.CREATE_SKETCH_SYMMETRIC:     "symmetric",
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
    poseMarkerDragged = QtCore.Signal(str, float, float, bool)
    poseMarkerPicked = QtCore.Signal(str)

    def __init__(self, app_service: ApplicationService, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.app_service = app_service
        self._display_project: Project | None = None
        self._selected_entity_id: str | None = None
        self._selected_entity_ids: set[str] = set()
        self._state_overlay: dict[str, float] | None = None
        self._simulation_time: float = 0.0
        self._screen_markers: list[tuple[CanvasMarker, QtCore.QPointF]] = []
        self._screen_grounds: list[tuple[CanvasGround, QtCore.QPointF]] = []
        self._screen_bodies: list[tuple[str, str, object]] = []
        self._screen_sliders: list[tuple[CanvasSlider, QtCore.QLineF, QtCore.QPointF]] = []
        self._screen_sketch_points: list[tuple[CanvasSketchPoint, QtCore.QPointF]] = []
        self._screen_sketch_entities: list[tuple[CanvasSketchEntity, object]] = []
        self._screen_sketch_constraints: list[tuple[str, QtCore.QPointF]] = []
        self._screen_slider_handles: list[tuple[str, str, QtCore.QPointF]] = []
        self._screen_joints: list[tuple[str, QtCore.QPointF]] = []
        self._screen_drivers: list[tuple[str, QtCore.QPointF]] = []
        self._screen_sensors: list[CanvasSensorScope] = []
        self._screen_loads: list[tuple[str, QtCore.QPointF]] = []
        self._screen_springs: list[tuple[str, QtCore.QPointF]] = []
        self._mode = CanvasMode.SELECT
        self._interaction_mode = "all"
        self._editing_enabled = True
        self._creation_points: list[tuple[float, float]] = []
        self._joint_start_entity: CanvasMarker | CanvasSlider | CanvasGround | None = None
        self._slider_creation_marker: CanvasMarker | None = None
        self._spring_start: CanvasMarker | None = None  # first endpoint for spring/actuator creation
        self._spring_start_world: tuple[float, float] | None = None  # world coords of first click
        self._driver_start_joint_id: str | None = None
        self._sensor_marker_ids: list[str] = []
        self._pose_pick_preview_kind: str | None = None
        self._pose_pick_marker_ids: list[str] = []
        self._pose_constraints: list[dict] = []
        self._pose_readonly: bool = False
        self._playback_locked: bool = False
        self._playback_lock_reason: str = ""
        self._creation_entity_ids: list[str] = []
        self._pending_distance_constraint_refs: list[str] = []
        self._hover_world: tuple[float, float] | None = None
        self._hovered_sketch_point_id: str | None = None
        self._hovered_sketch_entity_id: str | None = None
        self._dragging_marker: CanvasMarker | None = None
        self._dragging_pose_marker: CanvasMarker | None = None
        self._dragging_pose_marker_start: QtCore.QPointF | None = None
        self._dragging_pose_marker_active = False
        self._drag_preview: tuple[str, float, float] | None = None
        self._dragging_sketch_point: CanvasSketchPoint | None = None
        self._dragging_sketch_point_preview: tuple[str, float, float] | None = None
        self._dragging_sketch_solution_preview: dict[str, tuple[float, float]] = {}
        self._dragging_sketch_circle_id: str | None = None
        self._dragging_sketch_circle_preview_radius: float | None = None
        self._dragging_ground: CanvasGround | None = None
        self._dragging_ground_preview: tuple[str, float, float] | None = None
        self._dragging_sensor_scope_id: str | None = None
        self._dragging_sensor_scope_offset = QtCore.QPointF(0.0, 0.0)
        self._dragging_sensor_scope_preview: dict[str, QtCore.QPointF] = {}
        self._dragging_slider: tuple[str, str] | None = None
        self._dragging_slider_preview: dict[str, float] | None = None
        self._box_selection_start: QtCore.QPointF | None = None
        self._box_selection_current: QtCore.QPointF | None = None
        self._view_scale: float | None = None
        self._view_center_x = 0.0
        self._view_center_y = 0.0
        self._panning = False
        self._pan_last_screen: QtCore.QPointF | None = None
        self._pending_joint_creation: dict[str, str | int | None] | None = None
        self._edit_guard: Callable[[], bool] | None = None
        self._structural_edit_guard: Callable[[], bool] | None = None
        self._trajectories: list[list[tuple[float, float]]] = []
        self._show_trajectories: bool = True
        self._snap_preview_world: tuple[float, float] | None = None
        self._snap_kind: str | None = None
        self._snap_entity_id: str | None = None
        self._last_snap_candidate: SnapCandidate | None = None
        self._inference_lock: str | None = None
        self._snap_to_point: bool = False
        self._dof_result = None
        self._last_mouse_screen: QtCore.QPointF = QtCore.QPointF(0.0, 0.0)
        self._show_origin: bool = True
        self._show_axes: bool = True
        self._show_grid: bool = True
        self._show_sensors: bool = True
        self._collapsed_sensor_scopes: set[str] = set()
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

    def set_show_sensors(self, show: bool) -> None:
        self._show_sensors = show
        self.displaySettingsChanged.emit()
        self.update()

    def show_sensors(self) -> bool:
        return self._show_sensors

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
                    self._selected_entity_ids.clear()
                    self.selectionCleared.emit()
            self._dragging_marker = None
            self._dragging_pose_marker = None
            self._dragging_pose_marker_start = None
            self._dragging_pose_marker_active = False
            self._drag_preview = None
            self._dragging_slider = None
            self._dragging_slider_preview = None
        elif mode in {"model", "pose", "sim"}:
            if self._selected_entity_id is not None:
                if self._is_sketch_entity(self._selected_entity_id):
                    self._selected_entity_id = None
                    self._selected_entity_ids.clear()
                    self.selectionCleared.emit()
            self._dragging_pose_marker = None
            self._dragging_pose_marker_start = None
            self._dragging_pose_marker_active = False
            self._drag_preview = None
            self._dragging_sketch_point = None
            self._dragging_sketch_point_preview = None
            self._dragging_sketch_circle_id = None
            self._dragging_sketch_circle_preview_radius = None
        self._hovered_sketch_point_id = None
        self._hovered_sketch_entity_id = None
        self.update()

    def _is_sketch_entity(self, entity_id: str) -> bool:
        project = self._read_project()
        if project is None or project.sketch is None:
            return False
        if any(p.id == entity_id for p in project.sketch.points()):
            return True
        if entity_id in project.sketch.entities:
            return True
        if entity_id in project.sketch.constraints:
            return True
        return False

    def _is_point_fixed(self, point_id: str) -> bool:
        project = self._read_project()
        if project is None or project.sketch is None:
            return False
        return any(
            c.type == SketchConstraintType.FIX and point_id in c.references
            for c in project.sketch.constraints.values()
        )

    def _reset_tool_state(self) -> None:
        self._creation_points.clear()
        self._joint_start_entity = None
        self._slider_creation_marker = None
        self._spring_start = None
        self._spring_start_world = None
        self._driver_start_joint_id = None
        self._sensor_marker_ids = []
        self._pose_pick_preview_kind = None
        self._pose_pick_marker_ids = []
        self._creation_entity_ids = []
        self._pending_distance_constraint_refs = []
        self._hover_world = None
        self._hovered_sketch_point_id = None
        self._hovered_sketch_entity_id = None
        self._dragging_marker = None
        self._dragging_pose_marker = None
        self._dragging_pose_marker_start = None
        self._dragging_pose_marker_active = False
        self._drag_preview = None
        self._dragging_sketch_point = None
        self._dragging_sketch_point_preview = None
        self._dragging_sketch_solution_preview = {}
        self._dragging_sketch_circle_id = None
        self._dragging_sketch_circle_preview_radius = None
        self._dragging_ground = None
        self._dragging_ground_preview = None
        self._dragging_sensor_scope_id = None
        self._dragging_sensor_scope_preview = {}
        self._dragging_slider = None
        self._dragging_slider_preview = None
        self._box_selection_start = None
        self._box_selection_current = None
        self._pending_joint_creation = None
        self._snap_preview_world = None
        self._snap_kind = None
        self._snap_entity_id = None
        self._last_snap_candidate = None
        self._inference_lock = None

    def set_mode(self, mode: str) -> None:
        if self._mode in _CONSTRAINT_SPEC and mode != self._mode:
            # Constraint was in progress and tool changed — provide feedback
            self.modelChanged.emit("Constraint cancelled: tool changed")
        if mode in _CONSTRAINT_MODE_TO_TYPE and self._selected_entity_ids:
            ctype = _CONSTRAINT_MODE_TO_TYPE[mode]
            if ctype in {
                SketchConstraintType.HORIZONTAL,
                SketchConstraintType.VERTICAL,
                SketchConstraintType.COINCIDENT,
                SketchConstraintType.PARALLEL,
                SketchConstraintType.PERPENDICULAR,
                SketchConstraintType.EQUAL_LENGTH,
            }:
                try:
                    constraint_id = self.app_service.apply_sketch_constraint_from_entities(
                        ctype.value,
                        list(self._selected_entity_ids),
                    )
                except Exception:
                    pass
                else:
                    self._reset_tool_state()
                    self._selected_entity_id = constraint_id
                    self._selected_entity_ids = {constraint_id}
                    self.entitySelected.emit(constraint_id)
                    self.modelChanged.emit(f"Created sketch {ctype.value} constraint")
                    self._mode = CanvasMode.SELECT
                    self._set_cursor_for_mode(CanvasMode.SELECT)
                    self.modeChanged.emit(CanvasMode.SELECT)
                    self.update()
                    return
        self._reset_tool_state()
        self._mode = mode
        self._set_cursor_for_mode(mode)
        self.modeChanged.emit(mode)
        self.update()

    def set_pose_pick_preview(self, kind: str | None, marker_ids: list[str] | tuple[str, ...] | None = None) -> None:
        self._pose_pick_preview_kind = kind
        self._pose_pick_marker_ids = list(marker_ids or [])
        self.update()

    def set_pose_constraints(self, constraints) -> None:
        self._pose_constraints = [
            {
                "kind": getattr(constraint, "kind", None),
                "target_id": getattr(constraint, "target_id", None),
                "metadata": dict(getattr(constraint, "metadata", {}) or {}),
            }
            for constraint in constraints
        ]
        self.update()

    def set_pose_readonly(self, readonly: bool) -> None:
        self._pose_readonly = bool(readonly)
        self.update()

    def is_pose_readonly(self) -> bool:
        return self._pose_readonly

    def set_playback_locked(self, locked: bool, reason: str = "") -> None:
        self._playback_locked = bool(locked)
        self._playback_lock_reason = reason
        self.update()

    def is_playback_locked(self) -> bool:
        return self._playback_locked

    def _set_cursor_for_mode(self, mode: str) -> None:
        cursor_map = {
            CanvasMode.CREATE_SKETCH_POINT: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_LINE_SEGMENT: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_RECTANGLE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_CIRCLE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_ARC_CENTER: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_INFINITE_LINE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_FIX: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_HORIZONTAL: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_VERTICAL: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_DISTANCE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_COINCIDENT: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_PARALLEL: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_PERPENDICULAR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_EQUAL_LENGTH: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_ANGLE: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_MIDPOINT: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_COLLINEAR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_SYMMETRIC: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_TANGENT: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_SKETCH_CONCENTRIC: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_BAR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_POINT_MASS: QtCore.Qt.CursorShape.CrossCursor,
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
            CanvasMode.CREATE_LOAD: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_LINEAR_SPRING: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_ROTATIONAL_SPRING: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_LINEAR_ACTUATOR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.CREATE_ROTATIONAL_ACTUATOR: QtCore.Qt.CursorShape.CrossCursor,
            CanvasMode.POSE_PICK: QtCore.Qt.CursorShape.CrossCursor,
        }
        self.setCursor(QtGui.QCursor(cursor_map.get(mode, QtCore.Qt.CursorShape.ArrowCursor)))

    def fit_view(self) -> None:
        transform = self._fit_transform()
        self._view_scale, self._view_center_x, self._view_center_y = transform
        self._sync_view_state()
        self.update()

    def center_on_entity(self, entity_id: str) -> None:
        project = self._display_project if self._display_project is not None else self.app_service.project
        if project is None:
            return
        if project.sketch is not None:
            for entity in project.sketch.entities.values():
                if isinstance(entity, SketchPoint) and entity.id == entity_id:
                    try:
                        x = self.app_service._evaluate_sketch_expression(entity.x, project.parameters)
                        y = self.app_service._evaluate_sketch_expression(entity.y, project.parameters)
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
        assembled = self._assembled_mechanism(project)
        canvas_markers = self._collect_markers(project, assembled)
        canvas_sliders = self._collect_sliders(project)
        marker_pos = {cm.entity_id: (cm.x, cm.y) for cm in canvas_markers}
        for driver in project.model.drivers:
            if driver.id == entity_id:
                joint = self.app_service.get_joint(driver.target_joint_id)
                if joint is not None:
                    slider_map = {s.entity_id: s for s in canvas_sliders}
                    pos = self._joint_world_position(joint, {cm.entity_id: cm for cm in canvas_markers}, slider_map)
                    if pos is not None:
                        self._view_center_x, self._view_center_y = pos
                        self._sync_view_state()
                        self.update()
                return
        for sensor in project.model.sensors:
            if sensor.id == entity_id:
                xs, ys = [], []
                for mid in sensor.marker_ids:
                    pos = marker_pos.get(mid)
                    if pos is not None:
                        xs.append(pos[0])
                        ys.append(pos[1])
                if xs:
                    self._view_center_x = sum(xs) / len(xs)
                    self._view_center_y = sum(ys) / len(ys)
                    self._sync_view_state()
                    self.update()
                return

    def set_selection(self, entity_id: str | None) -> None:
        if entity_id is not None and self._interaction_mode != "all":
            is_sketch = self._is_sketch_entity(entity_id)
            if self._interaction_mode == "sketch" and not is_sketch:
                entity_id = None
            elif self._interaction_mode in ("model", "pose", "sim") and is_sketch:
                entity_id = None
        self._selected_entity_id = entity_id
        self._selected_entity_ids = {entity_id} if entity_id is not None else set()
        self.update()

    def _select_canvas_entity(self, entity_id: str | None, *, additive: bool = False) -> None:
        if entity_id is None:
            if not additive:
                self._selected_entity_id = None
                self._selected_entity_ids.clear()
                self.selectionCleared.emit()
            self.update()
            return
        if additive:
            if entity_id in self._selected_entity_ids:
                self._selected_entity_ids.remove(entity_id)
                self._selected_entity_id = next(iter(self._selected_entity_ids), None)
            else:
                self._selected_entity_ids.add(entity_id)
                self._selected_entity_id = entity_id
        else:
            self._selected_entity_ids = {entity_id}
            self._selected_entity_id = entity_id
        selected_snapshot = set(self._selected_entity_ids)
        primary_snapshot = self._selected_entity_id
        self.entitySelected.emit(entity_id)
        if additive:
            self._selected_entity_ids = selected_snapshot
            self._selected_entity_id = primary_snapshot
        self.update()

    def set_state_overlay(self, state: dict[str, float] | None) -> None:
        self._state_overlay = state
        self.update()

    def set_simulation_time(self, time: float) -> None:
        self._simulation_time = time
        self.update()

    def set_trajectories(self, trajectories: list[list[tuple[float, float]]]) -> None:
        self._trajectories = trajectories
        self.update()

    def set_show_trajectories(self, show: bool) -> None:
        self._show_trajectories = show
        self.update()

    def set_display_project(self, project: Project | None) -> None:
        self._display_project = project
        self.update()

    def _read_project(self) -> Project | None:
        """Single source of truth for read-only queries (paint/find/iterate).

        Returns the composed project (case overlays applied) when available,
        falling back to the baseline project. Edits MUST go through the
        ApplicationService fachade, not through this read view.
        """
        return self._display_project if self._display_project is not None else self.app_service.project

    def _case_delta_ids(self) -> tuple[set[str], set[str]]:
        """Return (overridden_ids, added_ids) for the active case, empty if none.

        Used to draw subtle visual markers (e.g. blue accent) on entities
        whose properties were overridden in the active case, and a green
        accent on entities added by the case.
        """
        project = self.app_service.project
        if project is None or project.workspace is None:
            return (set(), set())
        ws = project.workspace
        if ws.active_case_id is None:
            return (set(), set())
        case = next((c for c in ws.cases if c.id == ws.active_case_id), None)
        if case is None:
            return (set(), set())
        overridden: set[str] = set()
        for path in case.invariant_values:
            parts = path.split("/")
            if len(parts) >= 2:
                overridden.add(parts[1])
        for entity_id, _ in case.reference_overrides.items():
            overridden.add(entity_id)
        added: set[str] = set()
        for domain, entities in case.added_entities.items():
            for ent in entities:
                eid = ent.get("id") or ent.get("instance_id")
                if eid:
                    added.add(eid)
        return (overridden, added)

    def set_editing_enabled(self, enabled: bool) -> None:
        self._editing_enabled = enabled
        if not enabled:
            self._creation_points.clear()
            self._joint_start_entity = None
            self._slider_creation_marker = None
            self._driver_start_joint_id = None
            self._sensor_marker_ids = []
            self._creation_entity_ids = []
            self._pending_distance_constraint_refs = []
            self._dragging_marker = None
            self._dragging_pose_marker = None
            self._dragging_pose_marker_start = None
            self._dragging_pose_marker_active = False
            self._drag_preview = None
            self._dragging_ground = None
            self._dragging_ground_preview = None
            self._dragging_sensor_scope_id = None
            self._dragging_sensor_scope_preview = {}
            self._dragging_sketch_point = None
            self._dragging_sketch_point_preview = None
            self._dragging_sketch_solution_preview = {}
            self._dragging_slider = None
            self._dragging_slider_preview = None
            self._box_selection_start = None
            self._box_selection_current = None
            self._snap_preview_world = None
            self._snap_kind = None
            self._snap_entity_id = None
            self._last_snap_candidate = None
            self._inference_lock = None
            self._snap_to_point = False
        self.update()

    def set_edit_guard(self, guard: Callable[[], bool] | None) -> None:
        self._edit_guard = guard

    def set_structural_edit_guard(self, guard: Callable[[], bool] | None) -> None:
        """Set a callback invoked before structural mutations that bypass _require_editing (e.g. context menu delete/connect)."""
        self._structural_edit_guard: Callable[[], bool] | None = guard

    def inject_entity_selection(self, entity_id: str) -> None:
        """Process a tree-selection as if the user had clicked the entity on the canvas."""
        if not self._editing_enabled:
            return
        project = self._read_project()
        if project is None:
            return

        # Build lookup maps
        assembled = self._assembled_mechanism(project)
        markers = self._collect_markers(project, assembled)
        grounds = self._collect_grounds(project, assembled)
        sliders = self._collect_sliders(project)
        marker_map = {m.entity_id: m for m in markers}
        ground_map = {g.entity_id: g for g in grounds}
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
            slider = slider_map.get(entity_id)
            ground = ground_map.get(entity_id)
            if marker is not None or slider is not None or ground is not None:
                self._handle_joint_click(marker or slider or ground)
            return

        if self._mode == CanvasMode.CONNECT_GROUND:
            marker = marker_map.get(entity_id)
            if marker is not None:
                self._create_ground_joint(marker)
            elif entity_id in ground_map:
                self.entitySelected.emit(entity_id)
            return

        if self._mode == CanvasMode.CONNECT_SLIDER:
            marker = marker_map.get(entity_id)
            ground = ground_map.get(entity_id)
            slider = slider_map.get(entity_id)
            if self._joint_start_entity is None:
                if marker is None and slider is None and ground is None:
                    return
                self._joint_start_entity = marker or slider or ground
                self.entitySelected.emit(entity_id)
                self.update()
                return
            self._handle_joint_click(marker or slider or ground)
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

        if self._mode == CanvasMode.CREATE_LOAD:
            marker = marker_map.get(entity_id)
            if marker is not None:
                self._create_load_from_marker(entity_id)
            return

        if self._mode in {CanvasMode.CREATE_LINEAR_SPRING, CanvasMode.CREATE_LINEAR_ACTUATOR}:
            marker = marker_map.get(entity_id)
            if marker is not None:
                self._handle_spring_click(marker, (marker.x, marker.y))
            return

        if self._mode in {CanvasMode.CREATE_ROTATIONAL_SPRING, CanvasMode.CREATE_ROTATIONAL_ACTUATOR}:
            joint_ids = {j.id for j in project.model.joints}
            if entity_id in joint_ids:
                self._handle_rotational_spring_click(entity_id)
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
            CanvasMode.CREATE_SKETCH_ARC_CENTER: 3,
            CanvasMode.CREATE_SKETCH_INFINITE_LINE: 2,
        }
        if self._mode in _sketch_entity_modes:
            sketch_point = self.app_service.get_sketch_point(entity_id)
            if sketch_point is None:
                return
            x = self.app_service._evaluate_sketch_expression(sketch_point.x, project.parameters)
            y = self.app_service._evaluate_sketch_expression(sketch_point.y, project.parameters)
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
            sketch_entity = self.app_service.get_entity(entity_id)
            n_pts, n_ent = _CONSTRAINT_SPEC[self._mode]
            if sketch_point is not None:
                x = self.app_service._evaluate_sketch_expression(sketch_point.x, project.parameters)
                y = self.app_service._evaluate_sketch_expression(sketch_point.y, project.parameters)
                fake_pt = type("_Pt", (), {"entity_id": sketch_point.id, "x": x, "y": y})()
                self._handle_constraint_input_click(fake_pt, None, n_pts, n_ent)
            elif isinstance(sketch_entity, (SketchLineSegment, SketchInfiniteLine, SketchCircle, SketchArc)):
                if isinstance(sketch_entity, SketchLineSegment):
                    point_ids = [sketch_entity.start_point_id, sketch_entity.end_point_id]
                elif isinstance(sketch_entity, SketchInfiniteLine):
                    point_ids = [sketch_entity.point_a_id, sketch_entity.point_b_id]
                elif isinstance(sketch_entity, SketchCircle):
                    point_ids = [sketch_entity.center_point_id]
                else:
                    point_ids = [
                        sketch_entity.center_point_id,
                        sketch_entity.start_point_id,
                        sketch_entity.end_point_id,
                    ]
                fake_entity = type(
                    "_Entity",
                    (),
                    {
                        "entity_id": sketch_entity.id,
                        "entity_type": sketch_entity.type,
                        "point_ids": point_ids,
                    },
                )()
                self._handle_constraint_input_click(None, fake_entity, n_pts, n_ent)
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
        project = self._read_project()
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
        if project.sketch is not None:
            constraint = project.sketch.constraints.get(entity_id)
            if constraint is not None:
                anchor = self._sketch_constraint_anchor(constraint, point_map, self._current_transform())
                if anchor is not None:
                    return QtCore.QPoint(int(round(anchor.x())), int(round(anchor.y())))
        assembled = self._assembled_mechanism(project)
        markers = self._collect_markers(project, assembled)
        grounds = self._collect_grounds(project, assembled)
        for marker in markers:
            if marker.entity_id == entity_id:
                return self.screen_position_for_world(marker.x, marker.y)
        for ground in grounds:
            if ground.entity_id == entity_id:
                return self.screen_position_for_world(ground.x, ground.y)
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
        for sensor in project.model.sensors:
            if sensor.id == entity_id:
                geometry = self._sensor_screen_geometry(sensor, marker_map, self._current_transform())
                if geometry is None:
                    return None
                box_rect = self._sensor_scope_rect(
                    sensor,
                    self._sensor_scope_top_left(sensor, geometry["anchor"]),
                    sensor.id in self._collapsed_sensor_scopes,
                )
                return QtCore.QPoint(int(round(box_rect.center().x())), int(round(box_rect.center().y())))
        return None

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QtGui.QColor(self._background_color))

        project = self._display_project if self._display_project is not None else self.app_service.project
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
        grounds = self._collect_grounds(project, assembled)
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
                self._draw_grounds(painter, grounds, transform)
                self._draw_joints(painter, project, assembled, markers, sliders, transform)
                self._draw_drivers(painter, project, markers, sliders, transform)
                self._draw_sensors(painter, project, markers, transform)
                self._draw_markers(painter, markers, transform)
                self._draw_pose_constraint_icons(painter, project, markers, transform)
                self._draw_forces(painter, project, markers, transform)
                self._draw_loads(painter, project, markers, transform)
                self._draw_reactions(painter, project, transform)
            self._draw_springs(painter, project, assembled, transform)
            painter.restore()
            self._draw_sketch(painter, sketch_points, sketch_entities, transform, invalid=sketch_invalid)
            self._draw_sketch_constraints(painter, project, sketch_points, transform, invalid=sketch_invalid)
            if (
                self._show_trajectories
                and self._trajectories
                and self._interaction_mode == "analysis"
            ):
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
                self._draw_grounds(painter, grounds, transform)
                self._draw_joints(painter, project, assembled, markers, sliders, transform)
                self._draw_drivers(painter, project, markers, sliders, transform)
                self._draw_sensors(painter, project, markers, transform)
                self._draw_markers(painter, markers, transform)
                self._draw_pose_constraint_icons(painter, project, markers, transform)
                self._draw_forces(painter, project, markers, transform)
                self._draw_loads(painter, project, markers, transform)
                self._draw_reactions(painter, project, transform)
            elif not sketch_points and not sketch_entities:
                self._draw_empty_state(painter)
            self._draw_springs(painter, project, assembled, transform)
            if (
                self._show_trajectories
                and self._trajectories
                and self._interaction_mode == "analysis"
            ):
                self._draw_trajectories(painter, transform)

        self._draw_creation_overlay(painter, transform)
        self._draw_edge_rulers(painter, transform)
        self._draw_pose_dof_info(painter, project)
        self._draw_active_case_badge(painter)

        if self._pose_readonly:
            painter.fillRect(self.rect(), QtGui.QColor(180, 180, 180, 45))

        if self._playback_locked:
            painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 35))
            painter.setPen(QtGui.QPen(QtGui.QColor("#444")))
            font = painter.font()
            font.setPointSize(14)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter,
                             self._playback_lock_reason or "Playback disabled")

    def _draw_active_case_badge(self, painter: QtGui.QPainter) -> None:
        """Top-left stack of badges showing the active context.

        - ``Case: <name>`` when a case is the working scope.
        - ``Pose: <name>`` when a workspace pose is selected (i.e. pose mode).
        Badges stack vertically with a small gap so they don't overlap.
        """
        project = self.app_service.project
        if project is None or project.workspace is None:
            return
        ws = project.workspace
        badges: list[tuple[str, str]] = []  # (text, color)
        if ws.active_case_id is not None:
            case = next((c for c in ws.cases if c.id == ws.active_case_id), None)
            if case is not None:
                badges.append((f"Case: {case.name}", "#2255aa"))
        if self._interaction_mode == "pose" and ws.selected_pose_id:
            wp = next((p for p in ws.poses if p.id == ws.selected_pose_id), None)
            if wp is not None:
                tag = " [default]" if wp.is_default else ""
                badges.append((f"Pose: {wp.name}{tag}", "#c75b12"))
        if not badges:
            return
        painter.save()
        font = painter.font()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        pad = 6
        x = 8
        y = 8
        for text, color_hex in badges:
            text_rect = metrics.boundingRect(text)
            rect = QtCore.QRectF(x, y, text_rect.width() + pad * 2, text_rect.height() + pad)
            color = QtGui.QColor(color_hex)
            painter.setPen(QtGui.QPen(color, 1.0))
            translucent = QtGui.QColor(color)
            translucent.setAlpha(30)
            painter.setBrush(QtGui.QBrush(translucent))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QtGui.QPen(color))
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)
            y += rect.height() + 4
        painter.restore()

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
        clicked_ground = self._ground_at(clicked)
        clicked_body = self._body_at(clicked)
        clicked_slider = self._slider_at(clicked)
        clicked_slider_handle = self._slider_handle_at(clicked)
        clicked_joint = self._joint_at(clicked)
        clicked_driver = self._driver_at(clicked)
        clicked_sensor = self._sensor_at(clicked)
        clicked_load = self._load_at(clicked)
        clicked_spring = self._spring_at(clicked)
        clicked_constraint = self._sketch_constraint_at(clicked)
        world = self._to_world(clicked, self._current_transform())
        additive_selection = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)

        if self._mode == CanvasMode.POSE_PICK:
            if clicked_marker is not None and clicked_marker.marker_type is MarkerType.STRUCTURAL:
                self.poseMarkerPicked.emit(clicked_marker.entity_id)
            return

        if self._mode == CanvasMode.SELECT:
            if clicked_sketch_point is not None and self._interaction_mode in ("sketch", "all"):
                self._select_canvas_entity(clicked_sketch_point.entity_id, additive=additive_selection)
                point_is_locked = self._is_point_fixed(clicked_sketch_point.entity_id) or (
                    self._dof_result is not None
                    and self._dof_result.point_dof.get(clicked_sketch_point.entity_id, 2) == 0
                )
                if self._editing_enabled and not point_is_locked and not additive_selection:
                    self._dragging_sketch_point = clicked_sketch_point
                    self._dragging_sketch_point_preview = (
                        clicked_sketch_point.entity_id,
                        clicked_sketch_point.x,
                        clicked_sketch_point.y,
                    )
                self.update()
                return
            if clicked_constraint is not None and self._interaction_mode in ("sketch", "all"):
                self._select_canvas_entity(clicked_constraint, additive=additive_selection)
                return
            if clicked_sketch_entity is not None and self._interaction_mode in ("sketch", "all"):
                self._select_canvas_entity(clicked_sketch_entity.entity_id, additive=additive_selection)
                if (
                    self._editing_enabled
                    and not additive_selection
                    and clicked_sketch_entity.entity_type is SketchEntityType.CIRCLE
                ):
                    circle = self.app_service.get_entity(clicked_sketch_entity.entity_id)
                    if isinstance(circle, SketchCircle):
                        center_point = self.app_service.get_sketch_point(circle.center_point_id)
                        if center_point is not None:
                            self._dragging_sketch_circle_id = clicked_sketch_entity.entity_id
                            cx = self.app_service._evaluate_sketch_expression(center_point.x, self.app_service.project.parameters)
                            cy = self.app_service._evaluate_sketch_expression(center_point.y, self.app_service.project.parameters)
                            self._dragging_sketch_circle_preview_radius = max(1e-6, math.hypot(world[0] - cx, world[1] - cy))
                return
            if clicked_marker is not None and self._interaction_mode in ("model", "pose", "sim", "all"):
                self._select_canvas_entity(clicked_marker.entity_id, additive=additive_selection)
                if self._editing_enabled:
                    if self._interaction_mode == "pose" and clicked_marker.marker_type is MarkerType.STRUCTURAL:
                        if not self._pose_readonly:
                            self._dragging_pose_marker = clicked_marker
                            self._dragging_pose_marker_start = event.position()
                            self._dragging_pose_marker_active = False
                    elif self._interaction_mode != "pose":
                        self._dragging_marker = clicked_marker
                        self._drag_preview = (clicked_marker.entity_id, clicked_marker.x, clicked_marker.y)
                self.update()
                return
            if clicked_ground is not None and self._interaction_mode in ("model", "pose", "sim", "all"):
                self._select_canvas_entity(clicked_ground.entity_id, additive=additive_selection)
                if self._editing_enabled and self._interaction_mode != "pose":
                    self._dragging_ground = clicked_ground
                    self._dragging_ground_preview = (clicked_ground.marker_id, clicked_ground.x, clicked_ground.y)
                self.update()
                return
            if clicked_slider is not None and self._interaction_mode in ("model", "pose", "sim", "all"):
                self._select_canvas_entity(clicked_slider.entity_id, additive=additive_selection)
                if self._editing_enabled and self._interaction_mode != "pose":
                    handle = clicked_slider_handle or (clicked_slider.entity_id, "center")
                    self._dragging_slider = (handle[0], handle[1])
                    self._dragging_slider_preview = self._slider_preview_for_handle(handle[0], handle[1], world)
                self.update()
                return
            if clicked_joint is not None and self._interaction_mode in ("model", "pose", "sim", "all"):
                self._select_canvas_entity(clicked_joint, additive=additive_selection)
                return
            if clicked_driver is not None and self._interaction_mode in ("model", "pose", "sim", "all"):
                self._select_canvas_entity(clicked_driver, additive=additive_selection)
                return
            if clicked_sensor is not None and self._interaction_mode in ("model", "pose", "sim", "all"):
                sensor_id, hit_kind = clicked_sensor
                self._select_canvas_entity(sensor_id, additive=additive_selection)
                if hit_kind == "collapse":
                    if sensor_id in self._collapsed_sensor_scopes:
                        self._collapsed_sensor_scopes.remove(sensor_id)
                    else:
                        self._collapsed_sensor_scopes.add(sensor_id)
                elif self._editing_enabled and not additive_selection:
                    scope = next((item for item in self._screen_sensors if item.sensor_id == sensor_id), None)
                    if scope is not None:
                        self._dragging_sensor_scope_id = sensor_id
                        self._dragging_sensor_scope_offset = clicked - scope.box_rect.topLeft()
                return
            if clicked_load is not None and self._interaction_mode in ("model", "pose", "sim", "all"):
                self._select_canvas_entity(clicked_load, additive=additive_selection)
                return
            if clicked_spring is not None and self._interaction_mode in ("model", "pose", "sim", "all"):
                self._select_canvas_entity(clicked_spring, additive=additive_selection)
                return
            if clicked_body is not None and self._interaction_mode in ("model", "pose", "sim", "all"):
                self._select_canvas_entity(clicked_body, additive=additive_selection)
                return
            if self._interaction_mode in ("sketch", "all"):
                self._box_selection_start = clicked
                self._box_selection_current = clicked
                if not additive_selection:
                    self._selected_entity_id = None
                    self._selected_entity_ids.clear()
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
            CanvasMode.CREATE_SKETCH_DISTANCE,
            CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE,
            CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE,
        } and self._pending_distance_constraint_refs:
            constraint_type = _SKETCH_CONSTRAINT_TYPE_STR.get(self._mode, SketchConstraintType.DISTANCE.value)
            constraint_id = self.app_service.create_sketch_constraint(
                constraint_type,
                list(self._pending_distance_constraint_refs),
            )
            constraint = self.app_service.project.sketch.constraints.get(constraint_id)
            if constraint is not None:
                constraint.metadata.values["label_position"] = [world[0], world[1]]
            self._pending_distance_constraint_refs = []
            self._sensor_marker_ids = []
            self._creation_points.clear()
            self.entitySelected.emit(constraint_id)
            self.modelChanged.emit(f"Created sketch {constraint_type.replace('_', ' ')} constraint")
            self.set_mode(CanvasMode.SELECT)
            return

        if self._mode == CanvasMode.CREATE_SKETCH_RECTANGLE:
            snapped = self._apply_creation_inference(self._snap_world(world, include_model=False))
            self._snap_preview_world = snapped
            self._creation_points.append((snapped[0], snapped[1]))
            if len(self._creation_points) >= 2:
                try:
                    created_ids = self.app_service.create_sketch_rectangle(self._creation_points[0], self._creation_points[1])
                except Exception as exc:
                    QtWidgets.QMessageBox.warning(self, "Rectangle error", str(exc))
                    self.set_mode(CanvasMode.SELECT)
                    return
                created_id = created_ids[4] if len(created_ids) >= 5 else created_ids[0]
                self.entitySelected.emit(created_id)
                self.modelChanged.emit("Created sketch rectangle")
                self.set_mode(CanvasMode.SELECT)
            else:
                self.update()
            return

        if self._mode in {
            CanvasMode.CREATE_SKETCH_LINE_SEGMENT,
            CanvasMode.CREATE_SKETCH_CIRCLE,
            CanvasMode.CREATE_SKETCH_ARC_CENTER,
            CanvasMode.CREATE_SKETCH_INFINITE_LINE,
        }:
            snapped = self._snap_world(world, include_model=False)
            if self._mode == CanvasMode.CREATE_SKETCH_ARC_CENTER and len(self._creation_points) == 2:
                cx, cy = self._creation_points[0]
                sx, sy = self._creation_points[1]
                r = math.hypot(sx - cx, sy - cy)
                if r > 1e-9:
                    angle = math.atan2(snapped[1] - cy, snapped[0] - cx)
                    snapped = (cx + r * math.cos(angle), cy + r * math.sin(angle))
            self._snap_preview_world = snapped
            point_id = self._resolve_or_create_sketch_point(snapped, clicked_sketch_point)
            self._creation_points.append((snapped[0], snapped[1]))
            self._sensor_marker_ids.append(point_id)
            required = {
                CanvasMode.CREATE_SKETCH_LINE_SEGMENT: 2,
                CanvasMode.CREATE_SKETCH_CIRCLE: 2,
                CanvasMode.CREATE_SKETCH_ARC_CENTER: 3,
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

        if self._mode == CanvasMode.CREATE_POINT_MASS:
            self._create_point_mass_at(world)
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
            if clicked_marker is None and clicked_ground is None and clicked_slider is None:
                return
            self._handle_joint_click(clicked_marker or clicked_slider or clicked_ground)
            return

        if self._mode == CanvasMode.CREATE_SLIDER:
            if not self._creation_points and clicked_marker is not None:
                self._slider_creation_marker = clicked_marker
                self._creation_points = [(clicked_marker.x, clicked_marker.y)]
                self.entitySelected.emit(clicked_marker.entity_id)
                self.update()
                return
            self._creation_points.append(world)
            if len(self._creation_points) == 2:
                if self._slider_creation_marker is not None:
                    self._create_slider_from_marker()
                else:
                    self._create_slider_from_points()
            self.update()
            return

        if self._mode == CanvasMode.CONNECT_GROUND:
            if clicked_marker is not None:
                self._create_ground_joint(clicked_marker)
                return
            self._create_free_ground_at(world)
            return

        if self._mode == CanvasMode.CONNECT_SLIDER:
            if self._joint_start_entity is None:
                if clicked_marker is None and clicked_slider is None and clicked_ground is None:
                    return
                self._joint_start_entity = clicked_marker or clicked_slider or clicked_ground
                self.entitySelected.emit(self._joint_start_entity.entity_id)
                self.update()
                return
            self._handle_joint_click(clicked_marker or clicked_slider or clicked_ground)
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

        if self._mode == CanvasMode.CREATE_LOAD:
            if clicked_marker is None:
                return
            self._create_load_from_marker(clicked_marker.entity_id)
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

        if self._mode in {CanvasMode.CREATE_LINEAR_SPRING, CanvasMode.CREATE_LINEAR_ACTUATOR}:
            effective_marker = clicked_marker
            if effective_marker is None and clicked_body is not None:
                effective_marker = self._nearest_marker_on_body(clicked_body, clicked)
            self._handle_spring_click(effective_marker, world)
            return

        if self._mode in {CanvasMode.CREATE_ROTATIONAL_SPRING, CanvasMode.CREATE_ROTATIONAL_ACTUATOR}:
            self._handle_rotational_spring_click(clicked_joint)
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
        if self._box_selection_start is not None:
            self._box_selection_current = event.position()
            self.update()
            return
        if self._editing_enabled and self._mode == CanvasMode.SELECT and self._dragging_pose_marker is not None:
            if self._pose_readonly:
                return
            if not self._dragging_pose_marker_active:
                start = self._dragging_pose_marker_start
                if start is None:
                    self._dragging_pose_marker_start = event.position()
                elif QtCore.QLineF(start, event.position()).length() >= float(QtWidgets.QApplication.startDragDistance()):
                    self._dragging_pose_marker_active = True
            if not self._dragging_pose_marker_active:
                self._snap_preview_world = None
                self._drag_preview = None
                self.update()
                super().mouseMoveEvent(event)
                return
            snapped = self._snap_world(self._hover_world, include_model=False)
            self._snap_preview_world = snapped
            # Keep _drag_preview up to date so the mouse-release emit fires with
            # the cursor position (not the stale click position). Visual rendering
            # ignores _drag_preview in pose mode — see _collect_markers.
            self._drag_preview = (self._dragging_pose_marker.entity_id, snapped[0], snapped[1])
            self.poseMarkerDragged.emit(self._dragging_pose_marker.entity_id, snapped[0], snapped[1], False)
        elif self._editing_enabled and self._mode == CanvasMode.SELECT and self._dragging_marker is not None:
            snapped = self._snap_world(self._hover_world, include_model=False)
            self._snap_preview_world = snapped
            self._drag_preview = (self._dragging_marker.entity_id, snapped[0], snapped[1])
        elif self._editing_enabled and self._mode == CanvasMode.SELECT and self._dragging_ground is not None:
            snapped = self._snap_world(self._hover_world, include_model=False)
            self._snap_preview_world = snapped
            self._dragging_ground_preview = (self._dragging_ground.marker_id, snapped[0], snapped[1])
        elif self._editing_enabled and self._mode == CanvasMode.SELECT and self._dragging_sensor_scope_id is not None:
            top_left = event.position() - self._dragging_sensor_scope_offset
            top_left = QtCore.QPointF(
                min(max(8.0, top_left.x()), max(8.0, self.width() - 164.0)),
                min(max(8.0, top_left.y()), max(8.0, self.height() - 32.0)),
            )
            self._dragging_sensor_scope_preview[self._dragging_sensor_scope_id] = top_left
            self._snap_preview_world = None
        elif self._editing_enabled and self._mode == CanvasMode.SELECT and self._dragging_sketch_point is not None:
            snapped = self._snap_world(self._hover_world, include_model=False, exclude_point_id=self._dragging_sketch_point.entity_id)
            self._snap_preview_world = snapped
            self._dragging_sketch_point_preview = (
                self._dragging_sketch_point.entity_id,
                snapped[0],
                snapped[1],
            )
            self._dragging_sketch_solution_preview = self._preview_sketch_drag_solution(
                self._dragging_sketch_point.entity_id,
                snapped,
            )
        elif self._editing_enabled and self._mode == CanvasMode.SELECT and self._dragging_sketch_circle_id is not None:
            circle = self.app_service.get_entity(self._dragging_sketch_circle_id)
            if isinstance(circle, SketchCircle):
                center_point = self.app_service.get_sketch_point(circle.center_point_id)
                if center_point is not None:
                    cx = self.app_service._evaluate_sketch_expression(center_point.x, self.app_service.project.parameters)
                    cy = self.app_service._evaluate_sketch_expression(center_point.y, self.app_service.project.parameters)
                    self._dragging_sketch_circle_preview_radius = max(1e-6, math.hypot(self._hover_world[0] - cx, self._hover_world[1] - cy))
        elif self._editing_enabled and self._mode == CanvasMode.SELECT and self._dragging_slider is not None:
            slider_id, handle_kind = self._dragging_slider
            self._dragging_slider_preview = self._slider_preview_for_handle(slider_id, handle_kind, self._hover_world)
        elif self._mode in {
            CanvasMode.CREATE_SKETCH_POINT,
            CanvasMode.CREATE_SKETCH_LINE_SEGMENT,
            CanvasMode.CREATE_SKETCH_RECTANGLE,
            CanvasMode.CREATE_SKETCH_CIRCLE,
            CanvasMode.CREATE_SKETCH_ARC_CENTER,
            CanvasMode.CREATE_SKETCH_INFINITE_LINE,
            CanvasMode.CREATE_SKETCH_FIX,
            CanvasMode.CREATE_SKETCH_HORIZONTAL,
            CanvasMode.CREATE_SKETCH_VERTICAL,
            CanvasMode.CREATE_SKETCH_DISTANCE,
            CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE,
            CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE,
            CanvasMode.CREATE_SKETCH_COINCIDENT,
            CanvasMode.CREATE_SKETCH_PARALLEL,
            CanvasMode.CREATE_SKETCH_PERPENDICULAR,
            CanvasMode.CREATE_SKETCH_EQUAL_LENGTH,
            CanvasMode.CREATE_SKETCH_ANGLE,
            CanvasMode.CREATE_SKETCH_MIDPOINT,
            CanvasMode.CREATE_SKETCH_COLLINEAR,
            CanvasMode.CREATE_SKETCH_SYMMETRIC,
            CanvasMode.CREATE_SKETCH_TANGENT,
            CanvasMode.CREATE_SKETCH_CONCENTRIC,
        }:
            snapped = self._snap_world(self._hover_world, include_model=False)
            if self._mode in {CanvasMode.CREATE_SKETCH_LINE_SEGMENT, CanvasMode.CREATE_SKETCH_RECTANGLE}:
                snapped = self._apply_creation_inference(snapped)
            if self._mode == CanvasMode.CREATE_SKETCH_ARC_CENTER and len(self._creation_points) == 2:
                cx, cy = self._creation_points[0]
                sx, sy = self._creation_points[1]
                r = math.hypot(sx - cx, sy - cy)
                if r > 1e-9:
                    angle = math.atan2(snapped[1] - cy, snapped[0] - cx)
                    snapped = (cx + r * math.cos(angle), cy + r * math.sin(angle))
            self._snap_preview_world = snapped
        else:
            self._snap_preview_world = None
            self._snap_to_point = False
        # Update DOF info for status bar when in sketch mode
        if self._interaction_mode == "sketch":
            project = self._read_project()
            if project is not None and project.sketch is not None:
                dof_result = self.app_service.sketch_solver.analyze_dof(project)
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
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._box_selection_start is not None:
            additive_selection = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
            self._finish_box_selection(additive=additive_selection)
            self.update()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._dragging_pose_marker is not None:
            if self._pose_readonly:
                self._dragging_pose_marker = None
                self._dragging_pose_marker_start = None
                self._dragging_pose_marker_active = False
                self._drag_preview = None
                return
            if self._dragging_pose_marker_active:
                if self._drag_preview is None:
                    x, y = self._to_world(event.position(), self._current_transform())
                    self._drag_preview = (self._dragging_pose_marker.entity_id, x, y)
                marker_id, x, y = self._drag_preview
                self.poseMarkerDragged.emit(marker_id, x, y, True)
            self._dragging_pose_marker = None
            self._dragging_pose_marker_start = None
            self._dragging_pose_marker_active = False
            self._drag_preview = None
            self.update()
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
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._dragging_ground is not None:
            if not self._require_editing():
                self._dragging_ground = None
                self._dragging_ground_preview = None
                return
            if self._dragging_ground_preview is None:
                x, y = self._to_world(event.position(), self._current_transform())
                self._dragging_ground_preview = (self._dragging_ground.marker_id, x, y)
            marker_id, x, y = self._dragging_ground_preview
            ground_name = self._dragging_ground.name
            self.app_service.move_marker(marker_id, self._mm_expression(x), self._mm_expression(y))
            self._dragging_ground = None
            self._dragging_ground_preview = None
            self.modelChanged.emit(f"Moved ground {ground_name} to ({x:.2f}, {y:.2f}) mm")
            self.update()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._dragging_sensor_scope_id is not None:
            sensor_id = self._dragging_sensor_scope_id
            top_left = self._dragging_sensor_scope_preview.get(sensor_id)
            self._dragging_sensor_scope_id = None
            if top_left is not None:
                self.app_service.update_sensor_scope_position(sensor_id, top_left.x(), top_left.y())
                self.modelChanged.emit("Moved sensor scope")
            self._dragging_sensor_scope_preview = {}
            self.update()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._dragging_sketch_point is not None:
            if not self._require_editing():
                self._dragging_sketch_point = None
                self._dragging_sketch_point_preview = None
                self._dragging_sketch_solution_preview = {}
                self._snap_preview_world = None
                return
            point_name = self._dragging_sketch_point.name
            if self._dragging_sketch_point_preview is None:
                x, y = self._to_world(event.position(), self._current_transform())
                self._dragging_sketch_point_preview = (self._dragging_sketch_point.entity_id, x, y)
            point_id, x, y = self._dragging_sketch_point_preview
            self.app_service.move_sketch_point_with_solver(point_id, self._mm_expression(x), self._mm_expression(y))
            self._dragging_sketch_point = None
            self._dragging_sketch_point_preview = None
            self._dragging_sketch_solution_preview = {}
            self._snap_preview_world = None
            self.modelChanged.emit(f"Moved sketch point {point_name} to ({x:.2f}, {y:.2f}) mm")
            self.update()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._dragging_sketch_circle_id is not None:
            if not self._require_editing():
                self._dragging_sketch_circle_id = None
                self._dragging_sketch_circle_preview_radius = None
                return
            circle_id = self._dragging_sketch_circle_id
            radius = self._dragging_sketch_circle_preview_radius
            self._dragging_sketch_circle_id = None
            self._dragging_sketch_circle_preview_radius = None
            if radius is None:
                return
            try:
                self.app_service.update_sketch_entity(
                    circle_id,
                    "radius",
                    PropertyValueInput("expression", self._mm_expression(radius)),
                )
                self.modelChanged.emit(f"Updated circle radius to {radius:.2f} mm")
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Circle error", str(exc))
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
            slider_entity = self._read_project().model.sliders
            slider_name = next((s.name for s in slider_entity if s.id == slider_id), slider_id)
            self.modelChanged.emit(f"Updated slider {slider_name}")
            self.update()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:  # pragma: no cover - exercised indirectly in GUI tests
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            constraint_id = self._sketch_constraint_at(event.position())
            if constraint_id is not None:
                constraint = self.app_service.project.sketch.constraints.get(constraint_id)
                if constraint is not None and constraint.type in {
                    SketchConstraintType.DISTANCE,
                    SketchConstraintType.HORIZONTAL_DISTANCE,
                    SketchConstraintType.VERTICAL_DISTANCE,
                    SketchConstraintType.RADIUS,
                } and constraint.value is not None:
                    value, accepted = QtWidgets.QInputDialog.getText(
                        self,
                        "Edit Radius" if constraint.type is SketchConstraintType.RADIUS else "Edit Distance",
                        "Radius:" if constraint.type is SketchConstraintType.RADIUS else "Distance:",
                        text=constraint.value.expression,
                    )
                    if accepted and value.strip():
                        try:
                            self.app_service.edit_distance_constraint_value(constraint_id, value.strip())
                            self.modelChanged.emit("Updated sketch distance constraint")
                        except Exception as exc:
                            QtWidgets.QMessageBox.warning(self, "Distance error", str(exc))
                    return
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
            if not self._editing_enabled:
                self.modelChanged.emit("Editing is only available at t=0")
                return
            self._open_sketch_context_menu(event)
            return
        if not self._editing_enabled:
            self.modelChanged.emit("Editing is only available at t=0")
            return
        world = self._to_world(event.pos(), self._current_transform())
        marker = self._marker_at(event.pos())
        slider = self._slider_at(event.pos())
        joint_id = self._joint_at(event.pos())
        driver_id = self._driver_at(event.pos())
        sensor_id = self._sensor_at(event.pos())
        load_id = self._load_at(event.pos())
        spring_id = self._spring_at(event.pos())
        menu = QtWidgets.QMenu(self)
        delete_action = None
        rename_action = None
        toggle_joint_type_action = None
        edit_driver_law_action = None
        connect_ground_action = None
        add_marker_action = None
        add_load_action = None
        toggle_com_action = None
        slider_actions: dict[QtGui.QAction, str] = {}
        if marker is not None:
            delete_action = menu.addAction("Delete")
            connect_ground_action = menu.addAction("Connect To Ground")
            add_marker_action = menu.addAction("Add Marker To Body")
            add_load_action = menu.addAction("Add Load")
            slider_menu = menu.addMenu("Connect To Slider")
            for slider_item in self._read_project().model.sliders:
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
        elif sensor_id is not None:
            rename_action = menu.addAction("Rename Sensor")
            delete_action = menu.addAction("Delete")
        elif load_id is not None:
            rename_action = menu.addAction("Rename Load")
            delete_action = menu.addAction("Delete")
        elif spring_id is not None:
            rename_action = menu.addAction("Rename Spring")
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
            target_id = (
                slider.entity_id if slider is not None
                else joint_id if joint_id is not None
                else driver_id if driver_id is not None
                else sensor_id if sensor_id is not None
                else load_id if load_id is not None
                else spring_id
            )
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
            if self._structural_edit_guard is not None and not self._structural_edit_guard():
                return
            target_id = (
                marker.entity_id
                if marker is not None
                else slider.entity_id
                if slider is not None
                else joint_id
                if joint_id is not None
                else driver_id
                if driver_id is not None
                else sensor_id
                if sensor_id is not None
                else load_id
                if load_id is not None
                else spring_id
                if spring_id is not None
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
        if chosen is add_load_action and marker is not None:
            self._add_load_dialog(marker.entity_id)
            return
        if chosen in slider_actions and marker is not None:
            if self._structural_edit_guard is not None and not self._structural_edit_guard():
                return
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
        project = self._display_project if self._display_project is not None else self.app_service.project
        if not screen_markers and project is not None:
            assembled = self._assembled_mechanism(project)
            transform = self._current_transform()
            screen_markers = [
                (marker, self._to_screen(marker.x, marker.y, transform))
                for marker in self._collect_markers(project, assembled)
                if marker.visible
            ]
        for marker, marker_pos in reversed(screen_markers):
            if QtCore.QLineF(screen_pos, marker_pos).length() <= 10.0:
                return marker
        return None

    def _ground_at(self, screen_pos: QtCore.QPointF) -> CanvasGround | None:
        screen_grounds = self._screen_grounds
        project = self._display_project if self._display_project is not None else self.app_service.project
        if not screen_grounds and project is not None:
            assembled = self._assembled_mechanism(project)
            transform = self._current_transform()
            screen_grounds = [
                (ground, self._to_screen(ground.x, ground.y, transform))
                for ground in self._collect_grounds(project, assembled)
            ]
        for ground, ground_pos in reversed(screen_grounds):
            if QtCore.QLineF(screen_pos, ground_pos).length() <= 14.0:
                return ground
        return None

    def _slider_at(self, screen_pos: QtCore.QPointF) -> CanvasSlider | None:
        screen_sliders = self._screen_sliders
        project = self._display_project if self._display_project is not None else self.app_service.project
        if not screen_sliders and project is not None:
            transform = self._current_transform()
            sliders = self._collect_sliders(project)
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
        project = self._display_project if self._display_project is not None else self.app_service.project
        if not handles and project is not None:
            transform = self._current_transform()
            for slider in self._collect_sliders(project):
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

    def _load_at(self, screen_pos: QtCore.QPointF) -> str | None:
        for entity_id, center in reversed(self._screen_loads):
            if QtCore.QLineF(screen_pos, center).length() <= 12.0:
                return entity_id
        return None

    def _spring_at(self, screen_pos: QtCore.QPointF) -> str | None:
        for entity_id, center in reversed(self._screen_springs):
            if QtCore.QLineF(screen_pos, center).length() <= 14.0:
                return entity_id
        return None

    def _nearest_marker_on_body(self, body_id: str, screen_pos: QtCore.QPointF) -> "CanvasMarker | None":
        candidates = [
            (QtCore.QLineF(screen_pos, pos).length(), marker)
            for marker, pos in self._screen_markers
            if marker.body_id == body_id and marker.visible
        ]
        if not candidates:
            return None
        structural = [(d, m) for d, m in candidates if m.marker_type is not MarkerType.COM]
        pool = structural if structural else candidates
        return min(pool, key=lambda x: x[0])[1]

    def _sketch_constraint_at(self, screen_pos: QtCore.QPointF) -> str | None:
        for constraint_id, center in reversed(self._screen_sketch_constraints):
            if QtCore.QLineF(screen_pos, center).length() <= 12.0:
                return constraint_id
        return None

    def _open_sketch_context_menu(self, event: QtGui.QContextMenuEvent) -> None:
        clicked_point = self._sketch_point_at(event.pos())
        clicked_entity = self._sketch_entity_at(event.pos())
        target_id = clicked_point.entity_id if clicked_point is not None else (
            clicked_entity.entity_id if clicked_entity is not None else None
        )
        if target_id is not None and target_id not in self._selected_entity_ids:
            self._select_canvas_entity(target_id)
        selected = list(self._selected_entity_ids)
        if not selected and target_id is None:
            return
        menu = QtWidgets.QMenu(self)
        delete_action = menu.addAction("Delete")
        construction_action = menu.addAction("Toggle Construction")
        fix_action = menu.addAction("Fix/Unfix") if any(self.app_service.get_sketch_point(eid) for eid in selected) else None
        menu.addSeparator()
        compatible: dict[QtGui.QAction, SketchConstraintType] = {}
        for label, ctype in [
            ("Horizontal", SketchConstraintType.HORIZONTAL),
            ("Vertical", SketchConstraintType.VERTICAL),
            ("Coincident", SketchConstraintType.COINCIDENT),
            ("Parallel", SketchConstraintType.PARALLEL),
            ("Perpendicular", SketchConstraintType.PERPENDICULAR),
            ("Equal", SketchConstraintType.EQUAL_LENGTH),
        ]:
            compatible[menu.addAction(label)] = ctype
        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        try:
            if chosen is delete_action:
                for entity_id in selected:
                    self.app_service.delete_entity(entity_id)
                self._selected_entity_ids.clear()
                self._selected_entity_id = None
                self.modelChanged.emit("Deleted sketch selection")
                return
            if chosen is construction_action:
                enabled = self.app_service.toggle_sketch_construction(selected)
                self.modelChanged.emit("Enabled construction geometry" if enabled else "Disabled construction geometry")
                return
            if fix_action is not None and chosen is fix_action:
                self._toggle_fix_for_points(selected)
                self.modelChanged.emit("Toggled sketch fix constraint")
                return
            if chosen in compatible:
                constraint_id = self.app_service.apply_sketch_constraint_from_entities(
                    compatible[chosen].value,
                    selected,
                )
                self.entitySelected.emit(constraint_id)
                self.modelChanged.emit(f"Created sketch {compatible[chosen].value} constraint")
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Sketch action", str(exc))

    def _toggle_fix_for_points(self, entity_ids: list[str]) -> None:
        project = self._read_project()
        if project is None or project.sketch is None:
            return
        point_ids = [entity_id for entity_id in entity_ids if self.app_service.get_sketch_point(entity_id) is not None]
        if not point_ids:
            return
        existing_fix_ids = [
            constraint.id
            for constraint in project.sketch.constraints.values()
            if constraint.type is SketchConstraintType.FIX and any(pid in constraint.references for pid in point_ids)
        ]
        if existing_fix_ids:
            for constraint_id in existing_fix_ids:
                self.app_service.delete_sketch_constraint(constraint_id)
            return
        for point_id in point_ids:
            self.app_service.create_sketch_constraint(SketchConstraintType.FIX.value, [point_id])

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
        """Compute arc geometry from (center, start, end) world coordinates.

        Returns (center_x, center_y, radius, start_angle, span_angle) where
        start_angle is the angle to the start point and span_angle is the
        shorter arc from start to end (positive = CCW, negative = CW).
        The end point is projected onto the arc circle so markers 2 and 3
        always lie exactly on the arc.
        """
        if len(points) != 3:
            return None
        (cx, cy), (sx, sy), (ex, ey) = points
        radius = math.hypot(sx - cx, sy - cy)
        if radius < 1e-9:
            return None
        start_angle = math.atan2(sy - cy, sx - cx)
        end_angle = math.atan2(ey - cy, ex - cx)
        span = self._normalize_angle(end_angle - start_angle)
        return cx, cy, radius, start_angle, span

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
        # In pose mode the mechanism geometry comes from the kinematic solve, so
        # don't override the dragged marker's display position — that would
        # detach it from the bars and produce visible stretching.
        if self._drag_preview is not None and self._dragging_pose_marker is None:
            preview_map[self._drag_preview[0]] = (self._drag_preview[1], self._drag_preview[2])
        for body in project.model.bodies:
            is_ground_anchor = self._is_ground_anchor_body(body)
            structural_has_preview = (
                body.type is BodyType.BAR
                and any(sm.id in preview_map for sm in body.structural_markers())
            )
            for marker in body.markers:
                x, y = self._marker_world_position(project, body.id, marker.id, assembled)
                if x is None or y is None:
                    continue
                if marker.id in preview_map:
                    x, y = preview_map[marker.id]
                    if marker.type is MarkerType.COM and body.type is BodyType.BAR:
                        x, y = self._project_point_onto_bar(project, body, x, y, assembled)
                elif marker.type is MarkerType.COM and structural_has_preview:
                    cx, cy = self._bar_com_preview(project, body, preview_map, assembled)
                    if cx is not None:
                        x, y = cx, cy
                markers.append(
                    CanvasMarker(
                        entity_id=marker.id,
                        body_id=body.id,
                        name=marker.name,
                        x=x,
                        y=y,
                        marker_type=marker.type,
                        visible=(
                            not is_ground_anchor
                            and (marker.visible or marker.type is MarkerType.STRUCTURAL)
                        ),
                    )
                )
        return markers

    def _collect_grounds(
        self,
        project: Project,
        assembled: AssembledMechanism | None = None,
    ) -> list[CanvasGround]:
        grounds: list[CanvasGround] = []
        for body in project.model.bodies:
            if not self._is_ground_anchor_body(body):
                continue
            marker_id = body.metadata.values.get("ground_marker_id")
            if not isinstance(marker_id, str):
                continue
            x, y = self._marker_world_position(project, body.id, marker_id, assembled)
            if x is None or y is None:
                continue
            if self._dragging_ground_preview is not None and self._dragging_ground_preview[0] == marker_id:
                x = self._dragging_ground_preview[1]
                y = self._dragging_ground_preview[2]
            grounds.append(
                CanvasGround(
                    entity_id=body.id,
                    marker_id=marker_id,
                    name=body.name,
                    x=x,
                    y=y,
                )
            )
        return grounds

    def _is_ground_anchor_body(self, body: Body) -> bool:
        return bool(body.metadata.values.get("ground_anchor"))

    def _bar_com_preview(
        self,
        project: Project,
        body: Body,
        preview_map: dict,
        assembled: AssembledMechanism | None = None,
    ) -> tuple[float | None, float | None]:
        structural = body.structural_markers()
        if len(structural) < 2:
            return None, None
        x1, y1 = self._marker_world_position(project, body.id, structural[0].id, assembled)
        x2, y2 = self._marker_world_position(project, body.id, structural[1].id, assembled)
        if x1 is None or x2 is None:
            return None, None
        if structural[0].id in preview_map:
            x1, y1 = preview_map[structural[0].id]
        if structural[1].id in preview_map:
            x2, y2 = preview_map[structural[1].id]
        t = self.app_service._bar_com_percent(body) / 100.0
        return x1 + t * (x2 - x1), y1 + t * (y2 - y1)

    def _project_point_onto_bar(
        self,
        project: Project,
        body: Body,
        x: float,
        y: float,
        assembled: AssembledMechanism | None = None,
    ) -> tuple[float, float]:
        structural = body.structural_markers()
        if len(structural) < 2:
            return x, y
        x1, y1 = self._marker_world_position(project, body.id, structural[0].id, assembled)
        x2, y2 = self._marker_world_position(project, body.id, structural[1].id, assembled)
        if x1 is None or x2 is None:
            return x, y
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-12:
            return x1, y1
        t = ((x - x1) * dx + (y - y1) * dy) / length_sq
        t = max(0.0, min(1.0, t))
        return x1 + t * dx, y1 + t * dy

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
        if self._dragging_sketch_solution_preview:
            preview_map.update(self._dragging_sketch_solution_preview)
        if self._dragging_sketch_point_preview is not None:
            preview_map[self._dragging_sketch_point_preview[0]] = (
                self._dragging_sketch_point_preview[1],
                self._dragging_sketch_point_preview[2],
            )
        for entity in project.sketch.entities.values():
            if not isinstance(entity, SketchPoint):
                continue
            try:
                x = self.app_service._evaluate_sketch_expression(entity.x, project.parameters)
                y = self.app_service._evaluate_sketch_expression(entity.y, project.parameters)
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
        for entity in project.sketch.entities.values():
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
                    radius = (
                        self._dragging_sketch_circle_preview_radius
                        if entity.id == self._dragging_sketch_circle_id and self._dragging_sketch_circle_preview_radius is not None
                        else self.app_service._evaluate_sketch_expression(entity.radius, project.parameters)
                    )
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
                        point_ids=[entity.center_point_id, entity.start_point_id, entity.end_point_id],
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
        project = self._read_project()
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
            project = self._read_project()
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
        project = self._read_project()
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

    def _draw_edge_rulers(self, painter: QtGui.QPainter, transform) -> None:
        scale, center_x, center_y = transform
        if scale <= 0.0:
            return
        gutter_left = 34.0
        gutter_bottom = 20.0
        width = float(self.width())
        height = float(self.height())
        world_left = center_x - width * 0.5 / scale
        world_right = center_x + width * 0.5 / scale
        world_top = center_y + height * 0.5 / scale
        world_bottom = center_y - height * 0.5 / scale
        step_world = self._nice_ruler_step(60.0 / scale)
        if step_world <= 0.0:
            return

        bg = QtGui.QColor(self._background_color)
        bg.setAlpha(230)
        painter.save()
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRect(QtCore.QRectF(0.0, 0.0, gutter_left, height - gutter_bottom))
        painter.drawRect(QtCore.QRectF(gutter_left, height - gutter_bottom, width - gutter_left, gutter_bottom))
        painter.drawRect(QtCore.QRectF(0.0, height - gutter_bottom, gutter_left, gutter_bottom))

        font = painter.font()
        font.setPointSizeF(max(6.5, font.pointSizeF() - 1.5 if font.pointSizeF() > 0 else 7.0))
        painter.setFont(font)
        label_pen = QtGui.QPen(QtGui.QColor("#5f666d"), 1.0)
        tick_pen = QtGui.QPen(QtGui.QColor("#8f969d"), 1.0)

        painter.setClipRect(QtCore.QRectF(gutter_left, height - gutter_bottom, width - gutter_left, gutter_bottom))
        painter.setPen(tick_pen)
        start_x = math.floor(world_left / step_world) * step_world
        x = start_x
        while x <= world_right + 1e-9:
            screen_x = self._to_screen(x, center_y, transform).x()
            if gutter_left <= screen_x <= width:
                painter.drawLine(QtCore.QPointF(screen_x, height - gutter_bottom), QtCore.QPointF(screen_x, height - gutter_bottom + 5.0))
                painter.setPen(label_pen)
                painter.drawText(QtCore.QPointF(screen_x + 2.0, height - 5.0), self._format_ruler_value(x))
                painter.setPen(tick_pen)
            x += step_world

        painter.setClipRect(QtCore.QRectF(0.0, 0.0, gutter_left, height - gutter_bottom))
        start_y = math.floor(world_bottom / step_world) * step_world
        y = start_y
        while y <= world_top + 1e-9:
            screen_y = self._to_screen(center_x, y, transform).y()
            if 0.0 <= screen_y <= height - gutter_bottom:
                painter.drawLine(QtCore.QPointF(gutter_left - 5.0, screen_y), QtCore.QPointF(gutter_left, screen_y))
                painter.setPen(label_pen)
                painter.drawText(QtCore.QRectF(0.0, screen_y - 8.0, gutter_left - 7.0, 16.0), QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter, self._format_ruler_value(y))
                painter.setPen(tick_pen)
            y += step_world

        painter.setClipping(False)
        painter.setPen(QtGui.QPen(QtGui.QColor("#a5acae"), 1.0))
        painter.drawLine(QtCore.QPointF(gutter_left, 0.0), QtCore.QPointF(gutter_left, height))
        painter.drawLine(QtCore.QPointF(0.0, height - gutter_bottom), QtCore.QPointF(width, height - gutter_bottom))
        painter.setPen(label_pen)
        painter.drawText(QtCore.QRectF(0.0, height - gutter_bottom, gutter_left - 2.0, gutter_bottom), QtCore.Qt.AlignmentFlag.AlignCenter, "mm")
        painter.restore()

    def _nice_ruler_step(self, minimum_world_step: float) -> float:
        if minimum_world_step <= 0.0:
            return 1.0
        exponent = math.floor(math.log10(minimum_world_step))
        base = 10.0 ** exponent
        normalized = minimum_world_step / base
        if normalized <= 1.0:
            return 1.0 * base
        if normalized <= 2.0:
            return 2.0 * base
        if normalized <= 5.0:
            return 5.0 * base
        return 10.0 * base

    def _format_ruler_value(self, value: float) -> str:
        rounded = 0.0 if abs(value) < 1e-9 else value
        return f"{rounded:.6g}"

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
            project = self._read_project()
            if project is not None and project.sketch is not None:
                dof_result = self.app_service.sketch_solver.analyze_dof(project)
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

        hide_construction = self._interaction_mode in ("model", "sim")
        point_map = {point.entity_id: point for point in points}
        for entity in entities:
            if not entity.visible:
                continue
            if hide_construction and entity.construction:
                continue
            pen_color = _entity_color(entity.entity_id, entity.construction)
            if entity.entity_id in self._selected_entity_ids:
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
                painter.drawArc(rect, int(math.degrees(start_angle) * 16), int(math.degrees(span_angle) * 16))
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
            if hide_construction and point.construction:
                continue
            screen_point = self._to_screen(point.x, point.y, transform)
            self._screen_sketch_points.append((point, screen_point))
            radius = 3.5
            fill = _point_color(point.entity_id, point.construction)
            if point.entity_id in self._selected_entity_ids:
                painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                painter.setBrush(QtGui.QBrush(QtGui.QColor(199, 91, 18, 36)))
                painter.drawEllipse(screen_point, radius + 5.0, radius + 5.0)
                fill = QtGui.QColor("#c75b12")
            elif self._hovered_sketch_point_id == point.entity_id:
                fill = QtGui.QColor(color_pt_hover)
            painter.setPen(QtGui.QPen(QtGui.QColor("#f0f4f8"), 1.0))
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
        for constraint in project.sketch.constraints.values():
            anchor = self._sketch_constraint_anchor(constraint, point_map, transform)
            if anchor is None:
                continue
            is_bad = constraint.id in (project.sketch.bad_constraint_ids or [])
            if is_bad:
                color = QtGui.QColor("#e74c3c")  # solid red — this constraint failed
            elif invalid:
                color = QtGui.QColor("#b84840")  # legacy rust for whole-sketch invalid
            else:
                color = QtGui.QColor("#7f8c8d")  # normal grey
            if self._selected_entity_id == constraint.id:
                color = QtGui.QColor("#c75b12")  # selection overrides
            painter.setPen(QtGui.QPen(color, 1.1, QtCore.Qt.PenStyle.DashLine))
            if constraint.type in {
                SketchConstraintType.DISTANCE,
                SketchConstraintType.HORIZONTAL_DISTANCE,
                SketchConstraintType.VERTICAL_DISTANCE,
            } and len(constraint.references) == 2:
                p1 = point_map.get(constraint.references[0])
                p2 = point_map.get(constraint.references[1])
                if p1 is not None and p2 is not None:
                    s1 = self._to_screen(p1.x, p1.y, transform)
                    s2 = self._to_screen(p2.x, p2.y, transform)
                    if constraint.type is SketchConstraintType.HORIZONTAL_DISTANCE:
                        self._draw_projected_distance_annotation(painter, s1, s2, constraint, color, transform, axis=0)
                    elif constraint.type is SketchConstraintType.VERTICAL_DISTANCE:
                        self._draw_projected_distance_annotation(painter, s1, s2, constraint, color, transform, axis=1)
                    else:
                        painter.drawLine(s1, s2)
                        self._draw_distance_annotation(painter, s1, s2, constraint, color, transform)
            elif constraint.type is SketchConstraintType.RADIUS and len(constraint.references) == 1 and len(constraint.entity_references) == 1:
                center = point_map.get(constraint.references[0])
                entity = project.sketch.entities.get(constraint.entity_references[0]) if project.sketch is not None else None
                if center is not None and isinstance(entity, (SketchCircle, SketchArc)):
                    self._draw_radius_annotation(painter, center, entity, constraint, color, transform)
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
                    self._draw_constraint_icon(painter, mid1, constraint.type, color)
                    self._draw_constraint_icon(painter, mid2, constraint.type, color)
                    self._screen_sketch_constraints.append((constraint.id, mid1))
                    self._screen_sketch_constraints.append((constraint.id, mid2))
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

            if constraint.type not in {
                SketchConstraintType.PARALLEL,
                SketchConstraintType.PERPENDICULAR,
                SketchConstraintType.EQUAL_LENGTH,
            }:
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
        overridden_ids, added_ids = self._case_delta_ids()
        for body in project.model.bodies:
            if self._is_ground_anchor_body(body):
                continue
            structural = [marker_map[marker.id] for marker in body.structural_markers() if marker.id in marker_map]
            if not structural:
                continue
            selected = self._selected_entity_id == body.id
            base_color = QtGui.QColor(body.style.color) if body.style.color else QtGui.QColor("#31556f")
            base_width = body.style.line_width if body.style.line_width else 2.3
            pen = QtGui.QPen(base_color, base_width)
            fill = QtGui.QColor(base_color.red(), base_color.green(), base_color.blue(), 85)
            # Case-delta accents: blue=overridden, green=added by case.
            # Selected highlight wins on top.
            marker_overridden = any(m.id in overridden_ids for m in body.markers)
            if body.id in added_ids:
                pen.setColor(QtGui.QColor("#228822"))
                pen.setWidthF(base_width + 0.5)
            elif body.id in overridden_ids or marker_overridden:
                pen.setColor(QtGui.QColor("#2255aa"))
                pen.setWidthF(base_width + 0.5)
            if selected:
                pen.setColor(QtGui.QColor("#c75b12"))
                pen.setWidthF(base_width + 1.0)
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
            # Calculate centroid of polygon for label placement
            if len(polygon) > 0:
                centroid = QtCore.QPointF(0.0, 0.0)
                for point in polygon:
                    centroid += point
                centroid /= len(polygon)
                name_pos = centroid
            else:
                name_pos = self._to_screen(ordered[0].x, ordered[0].y, transform)
            painter.setPen(QtGui.QPen(QtGui.QColor("#5b5247")))
            # Draw text centered at the name_pos
            fm = painter.fontMetrics()
            text_width = fm.horizontalAdvance(body.name)
            text_height = fm.height()
            painter.drawText(name_pos.x() - text_width / 2, name_pos.y() + text_height / 4, body.name)

    def _draw_grounds(self, painter: QtGui.QPainter, grounds: list[CanvasGround], transform) -> None:
        self._screen_grounds = []
        for ground in grounds:
            point = self._to_screen(ground.x, ground.y, transform)
            self._screen_grounds.append((ground, point))
            pen_color = QtGui.QColor("#5a4634")
            if self._selected_entity_id == ground.entity_id:
                pen_color = QtGui.QColor("#c75b12")
                painter.setBrush(QtGui.QBrush(QtGui.QColor(199, 91, 18, 40)))
                painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                painter.drawEllipse(point, 12.0, 12.0)
            painter.setPen(QtGui.QPen(pen_color, 2.0))
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#faf8f2")))
            painter.drawRect(QtCore.QRectF(point.x() - 5.0, point.y() - 5.0, 10.0, 10.0))
            self._draw_ground_symbol(painter, point)
            painter.setPen(QtGui.QPen(QtGui.QColor("#5b5247")))
            painter.drawText(point + QtCore.QPointF(10.0, -10.0), ground.name)

    def _draw_joints(
        self,
        painter: QtGui.QPainter,
        project: Project,
        assembled,
        markers: list[CanvasMarker],
        sliders: list[CanvasSlider],
        transform,
    ) -> None:
        self._screen_joints = []
        marker_map = {marker.entity_id: marker for marker in markers}
        slider_map = {slider.entity_id: slider for slider in sliders}
        overridden_ids, added_ids = self._case_delta_ids()
        for joint in project.model.joints:
            if joint.metadata.values.get("internal_ground_anchor"):
                continue
            position = self._joint_world_position(joint, marker_map, slider_map)
            if position is None:
                continue
            point = self._to_screen(position[0], position[1], transform)
            self._screen_joints.append((joint.id, point))
            pen_color = QtGui.QColor("#2f3a4b")
            if joint.id in added_ids:
                pen_color = QtGui.QColor("#228822")
            elif joint.id in overridden_ids:
                pen_color = QtGui.QColor("#2255aa")
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
                self._draw_joint_angle_limit_arc(painter, joint, point, assembled)
            if joint.endpoint_a.kind is JointEndpointKind.GROUND or joint.endpoint_b.kind is JointEndpointKind.GROUND:
                self._draw_ground_symbol(painter, point)
            if joint.endpoint_a.kind is JointEndpointKind.SLIDER or joint.endpoint_b.kind is JointEndpointKind.SLIDER:
                slider_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.SLIDER else joint.endpoint_b
                slider = slider_map.get(slider_endpoint.slider_id or "")
                if slider is not None:
                    self._draw_slider_joint_symbol(painter, point, slider.angle)

    def _draw_joint_angle_limit_arc(self, painter: QtGui.QPainter, joint: Joint, point: QtCore.QPointF, assembled) -> None:
        if not self.app_service.joint_supports_angular_limits(joint):
            return
        positive, negative = self.app_service.joint_angular_limit_values(joint)
        if positive is None and negative is None:
            return
        limits = self._joint_angle_limit_arc_bounds(joint, assembled, positive, negative)
        if limits is None:
            return
        start_angle_deg, span_angle_deg = limits
        if span_angle_deg <= 1e-9:
            return
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#7f5539"), 1.2, QtCore.Qt.PenStyle.DashLine))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        radius = 16.0
        rect = QtCore.QRectF(point.x() - radius, point.y() - radius, radius * 2.0, radius * 2.0)
        painter.drawArc(rect, int(-start_angle_deg * 16.0), int(-span_angle_deg * 16.0))
        painter.restore()

    def _joint_angle_limit_arc_bounds(
        self,
        joint: Joint,
        assembled,
        positive_deg: float | None,
        negative_deg: float | None,
    ) -> tuple[float, float] | None:
        orientation = self._joint_limit_orientation(joint, assembled)
        if orientation is None:
            return None
        reference_angle, current_relative = orientation
        lower = reference_angle + current_relative - math.radians(negative_deg or 0.0)
        upper = reference_angle + current_relative + math.radians(positive_deg or 0.0)
        start = math.degrees(lower)
        span = math.degrees(upper - lower)
        return start, span

    def _joint_limit_orientation(self, joint: Joint, assembled) -> tuple[float, float] | None:
        if assembled is None:
            return None
        if joint.endpoint_a.kind is JointEndpointKind.GROUND and joint.endpoint_b.kind is JointEndpointKind.MARKER:
            body_b = assembled.bodies.get(joint.endpoint_b.body_id or "")
            if body_b is None:
                return None
            return 0.0, body_b.angle
        if joint.endpoint_b.kind is JointEndpointKind.GROUND and joint.endpoint_a.kind is JointEndpointKind.MARKER:
            body_a = assembled.bodies.get(joint.endpoint_a.body_id or "")
            if body_a is None:
                return None
            return 0.0, body_a.angle
        body_a_id, body_b_id = self._joint_limit_body_ids(joint)
        body_a = assembled.bodies.get(body_a_id)
        body_b = assembled.bodies.get(body_b_id)
        if body_a is None or body_b is None:
            return None
        if self._is_ground_anchor_body_ref(body_a) and not self._is_ground_anchor_body_ref(body_b):
            return body_a.angle, body_b.angle - body_a.angle
        if self._is_ground_anchor_body_ref(body_b) and not self._is_ground_anchor_body_ref(body_a):
            return body_b.angle, body_a.angle - body_b.angle
        return body_a.angle, body_b.angle - body_a.angle

    def _joint_limit_body_ids(self, joint: Joint) -> tuple[str | None, str | None]:
        return joint.endpoint_a.body_id, joint.endpoint_b.body_id

    def _is_ground_anchor_body_ref(self, body) -> bool:
        body_id = getattr(body, "body_id", None)
        if not body_id:
            return False
        domain_body = self.app_service.get_body(body_id)
        return bool(domain_body is not None and self._is_ground_anchor_body(domain_body))

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

    def _draw_sensors(
        self,
        painter: QtGui.QPainter,
        project: Project,
        markers: list[CanvasMarker],
        transform,
    ) -> None:
        self._screen_sensors = []
        if not self._show_sensors:
            return
        marker_map = {marker.entity_id: marker for marker in markers}
        base_color = QtGui.QColor("#1a7a4a")
        sel_color = QtGui.QColor("#27ae60")
        line_color = QtGui.QColor("#5f8f77")
        for sensor in project.model.sensors:
            try:
                geometry = self._sensor_screen_geometry(sensor, marker_map, transform)
                if geometry is None:
                    continue
                is_selected = self._selected_entity_id == sensor.id
                color = sel_color if is_selected else base_color
                anchor = geometry["anchor"]
                box_origin = self._sensor_scope_top_left(sensor, anchor)
                collapsed = sensor.id in self._collapsed_sensor_scopes
                box_rect = self._sensor_scope_rect(sensor, box_origin, collapsed)
                header_rect = QtCore.QRectF(box_rect.x(), box_rect.y(), box_rect.width(), 22.0)
                collapse_rect = QtCore.QRectF(box_rect.right() - 18.0, box_rect.y() + 3.0, 14.0, 14.0)
                self._draw_sensor_measured_geometry(painter, geometry, line_color)
                self._draw_sensor_scope_connector(painter, anchor, box_rect, line_color)
                if is_selected:
                    painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                    painter.setBrush(QtGui.QBrush(QtGui.QColor(39, 174, 96, 28)))
                    painter.drawRoundedRect(box_rect.adjusted(-4.0, -4.0, 4.0, 4.0), 8.0, 8.0)
                painter.setPen(QtGui.QPen(color, 1.2))
                painter.setBrush(QtGui.QBrush(QtGui.QColor("#fffdf7")))
                painter.drawRoundedRect(box_rect, 7.0, 7.0)
                painter.setPen(QtGui.QPen(QtGui.QColor("#dfe8de"), 1.0))
                painter.setBrush(QtGui.QBrush(QtGui.QColor("#eef7ef")))
                painter.drawRoundedRect(header_rect, 7.0, 7.0)
                painter.fillRect(QtCore.QRectF(header_rect.x(), header_rect.bottom() - 7.0, header_rect.width(), 7.0), QtGui.QColor("#eef7ef"))
                painter.setPen(QtGui.QPen(color, 1.0))
                painter.setBrush(QtGui.QBrush(color))
                painter.drawEllipse(QtCore.QPointF(header_rect.x() + 11.0, header_rect.center().y()), 4.0, 4.0)
                title_font = QtGui.QFont(painter.font())
                title_font.setPointSizeF(max(7.0, title_font.pointSizeF() - 1.0 if title_font.pointSizeF() > 0 else 8.0))
                title_font.setBold(True)
                painter.setFont(title_font)
                painter.setPen(QtGui.QPen(QtGui.QColor("#0d4d2e")))
                painter.drawText(QtCore.QRectF(header_rect.x() + 20.0, header_rect.y(), header_rect.width() - 40.0, header_rect.height()), QtCore.Qt.AlignmentFlag.AlignVCenter, sensor.name)
                arrow = ">" if collapsed else "v"
                painter.drawText(collapse_rect, QtCore.Qt.AlignmentFlag.AlignCenter, arrow)
                if not collapsed:
                    value_font = QtGui.QFont(painter.font())
                    value_font.setBold(False)
                    value_font.setPointSizeF(max(6.0, value_font.pointSizeF() - 1.0 if value_font.pointSizeF() > 0 else 7.0))
                    painter.setFont(value_font)
                    painter.setPen(QtGui.QPen(QtGui.QColor("#48624f")))
                    rows = self._sensor_scope_rows(project, sensor)
                    y = header_rect.bottom() + 6.0
                    for label, value in rows:
                        painter.drawText(QtCore.QRectF(box_rect.x() + 6.0, y, box_rect.width() * 0.55, 12.0), QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter, label)
                        painter.drawText(QtCore.QRectF(box_rect.x() + box_rect.width() * 0.55, y, box_rect.width() * 0.4 - 6.0, 12.0), QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter, value)
                        y += 12.0
                self._screen_sensors.append(
                    CanvasSensorScope(
                        sensor_id=sensor.id,
                        box_rect=box_rect,
                        header_rect=header_rect,
                        collapse_rect=collapse_rect,
                        anchor_point=anchor,
                    )
                )
            except Exception:
                # Keep the rest of the canvas responsive even if one sensor is incomplete
                # or transiently inconsistent during an interactive drag.
                continue

    def _sensor_at(self, screen_pos: QtCore.QPointF) -> tuple[str, str] | None:
        if not self._show_sensors:
            return None
        for scope in reversed(self._screen_sensors):
            if scope.collapse_rect.contains(screen_pos):
                return scope.sensor_id, "collapse"
            if scope.box_rect.contains(screen_pos):
                return scope.sensor_id, "scope"
        return None

    def _sensor_screen_geometry(self, sensor, marker_map: dict[str, CanvasMarker], transform):
        positions = [self._to_screen(marker_map[mid].x, marker_map[mid].y, transform) for mid in sensor.marker_ids if mid in marker_map]
        if not positions:
            return None
        sensor_type = sensor.type.value
        if sensor_type == "point":
            return {"kind": sensor_type, "anchor": positions[0], "points": positions}
        if sensor_type in {"distance", "angle_horizontal", "angle_vertical"}:
            if len(positions) < 2:
                return None
            p1, p2 = positions[:2]
            anchor = QtCore.QPointF((p1.x() + p2.x()) * 0.5, (p1.y() + p2.y()) * 0.5)
            return {"kind": sensor_type, "anchor": anchor, "points": [p1, p2]}
        if sensor_type == "angle_vector" and len(positions) >= 4:
            intersection = self._line_intersection(positions[0], positions[1], positions[2], positions[3])
            if intersection is None:
                intersection = QtCore.QPointF(
                    sum(point.x() for point in positions[:4]) / 4.0,
                    sum(point.y() for point in positions[:4]) / 4.0,
                )
            return {"kind": sensor_type, "anchor": intersection, "points": positions[:4]}
        if sensor_type == "angle_vector":
            return None
        anchor = positions[0]
        return {"kind": sensor_type, "anchor": anchor, "points": positions}

    def _sensor_scope_top_left(self, sensor, anchor: QtCore.QPointF) -> QtCore.QPointF:
        preview = self._dragging_sensor_scope_preview.get(sensor.id)
        if preview is not None:
            return preview
        canvas_x = sensor.metadata.values.get("scope_canvas_x")
        canvas_y = sensor.metadata.values.get("scope_canvas_y")
        if canvas_x is not None and canvas_y is not None:
            try:
                return QtCore.QPointF(float(canvas_x), float(canvas_y))
            except (TypeError, ValueError):
                pass
        x = min(max(anchor.x() + 24.0, 12.0), max(12.0, self.width() - 168.0))
        y = min(max(anchor.y() - 18.0, 12.0), max(12.0, self.height() - 86.0))
        return QtCore.QPointF(x, y)

    def _sensor_scope_rect(self, sensor, top_left: QtCore.QPointF, collapsed: bool) -> QtCore.QRectF:
        rows = 0 if collapsed else len(self._sensor_scope_rows(self._read_project(), sensor))
        width = 156.0
        height = 24.0 if collapsed else 30.0 + rows * 12.0 + 6.0
        return QtCore.QRectF(top_left.x(), top_left.y(), width, height)

    def _sensor_scope_rows(self, project: Project | None, sensor) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        if project is None:
            return rows
        output = project.sensor_outputs.get(sensor.id)
        if output is not None and output.columns and output.data:
            frame_index = 0
            if output.time:
                frame_index = min(range(len(output.time)), key=lambda idx: abs(output.time[idx] - self._simulation_time))
            frame_index = max(0, min(frame_index, len(output.data) - 1))
            values = output.data[frame_index]
            for col_idx, name in enumerate(output.columns):
                if col_idx < len(values):
                    rows.append((name, f"{values[col_idx]:.4g}"))
            return rows
        for suffix, unit in sensor_channel_keys(sensor):
            label = suffix.replace("_", " ")
            rows.append((label, f"[{unit}]"))
        return rows

    def _draw_sensor_measured_geometry(self, painter: QtGui.QPainter, geometry: dict, color: QtGui.QColor) -> None:
        painter.save()
        painter.setPen(QtGui.QPen(color, 1.0, QtCore.Qt.PenStyle.DashLine))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        kind = geometry["kind"]
        points = geometry["points"]
        if kind == "point":
            painter.drawEllipse(points[0], 4.5, 4.5)
        elif kind in {"distance", "angle_horizontal", "angle_vertical"} and len(points) >= 2:
            painter.drawLine(points[0], points[1])
        elif kind == "angle_vector" and len(points) >= 4:
            painter.drawLine(points[0], points[1])
            painter.drawLine(points[2], points[3])
            center = geometry["anchor"]
            r = min(
                max(10.0, QtCore.QLineF(center, points[0]).length() * 0.35),
                max(10.0, QtCore.QLineF(center, points[2]).length() * 0.35),
            )
            start = math.degrees(math.atan2(-(points[0].y() - center.y()), points[0].x() - center.x()))
            end = math.degrees(math.atan2(-(points[2].y() - center.y()), points[2].x() - center.x()))
            span = end - start
            while span <= 0.0:
                span += 360.0
            if span > 180.0:
                span -= 360.0
            rect = QtCore.QRectF(center.x() - r, center.y() - r, 2.0 * r, 2.0 * r)
            painter.drawArc(rect, int(-start * 16.0), int(-span * 16.0))
        painter.restore()

    def _draw_sensor_scope_connector(self, painter: QtGui.QPainter, anchor: QtCore.QPointF, box_rect: QtCore.QRectF, color: QtGui.QColor) -> None:
        end = QtCore.QPointF(box_rect.left(), box_rect.center().y())
        path = QtGui.QPainterPath(anchor)
        control_dx = max(24.0, abs(end.x() - anchor.x()) * 0.4)
        path.cubicTo(
            QtCore.QPointF(anchor.x() + control_dx, anchor.y()),
            QtCore.QPointF(end.x() - control_dx, end.y()),
            end,
        )
        painter.save()
        painter.setPen(QtGui.QPen(color, 1.0, QtCore.Qt.PenStyle.DashLine))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.restore()

    def _line_intersection(
        self,
        p1: QtCore.QPointF,
        p2: QtCore.QPointF,
        p3: QtCore.QPointF,
        p4: QtCore.QPointF,
    ) -> QtCore.QPointF | None:
        x1, y1, x2, y2 = p1.x(), p1.y(), p2.x(), p2.y()
        x3, y3, x4, y4 = p3.x(), p3.y(), p4.x(), p4.y()
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) <= 1e-9:
            return None
        det1 = x1 * y2 - y1 * x2
        det2 = x3 * y4 - y3 * x4
        px = (det1 * (x3 - x4) - (x1 - x2) * det2) / denom
        py = (det1 * (y3 - y4) - (y1 - y2) * det2) / denom
        return QtCore.QPointF(px, py)

    def _draw_markers(self, painter: QtGui.QPainter, markers: list[CanvasMarker], transform) -> None:
        self._screen_markers = []
        overridden_ids, added_ids = self._case_delta_ids()
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
            # Case-delta ring (drawn behind the marker fill).
            if marker.entity_id in added_ids:
                painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                painter.setBrush(QtGui.QBrush(QtGui.QColor(34, 136, 34, 80)))
                painter.drawEllipse(point, radius + 4.0, radius + 4.0)
            elif marker.entity_id in overridden_ids:
                painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                painter.setBrush(QtGui.QBrush(QtGui.QColor(34, 85, 170, 80)))
                painter.drawEllipse(point, radius + 4.0, radius + 4.0)
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

    def _draw_pose_dof_info(self, painter: QtGui.QPainter, project: Project) -> None:
        """Draw DOF count in the top-right corner when in pose mode."""
        if self._interaction_mode != "pose":
            return
        pose_constraint_count = len(self._pose_constraints)
        dof_result = compute_mechanism_dof(project, pose_constraint_count)
        text = f"DOF: {dof_result.total_dof}"
        if dof_result.pose_constraint_count:
            text += f"  (constraints: {dof_result.pose_constraint_count})"
        painter.save()
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QtGui.QPen(QtGui.QColor("#2f6f9f"), 1))
        metrics = painter.fontMetrics()
        text_rect = metrics.boundingRect(text)
        padding = 6
        x = self.width() - text_rect.width() - padding * 2
        y = padding
        rect = QtCore.QRectF(x, y, text_rect.width() + padding * 2, text_rect.height() + padding)
        painter.fillRect(rect, QtGui.QColor(255, 255, 255, 200))
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _draw_pose_constraint_icons(
        self,
        painter: QtGui.QPainter,
        project: Project,
        markers: list[CanvasMarker],
        transform,
    ) -> None:
        if self._interaction_mode != "pose" or not self._pose_constraints:
            return
        marker_map = {marker.entity_id: marker for marker in markers}
        body_markers: dict[str, list[CanvasMarker]] = {}
        for marker in markers:
            if marker.body_id is not None:
                body_markers.setdefault(marker.body_id, []).append(marker)

        def marker_point(marker_id: str | None) -> QtCore.QPointF | None:
            marker = marker_map.get(marker_id or "")
            if marker is None:
                return None
            return self._to_screen(marker.x, marker.y, transform)

        def body_point(body_id: str | None) -> QtCore.QPointF | None:
            body = body_markers.get(body_id or "")
            structural = [marker for marker in body or [] if marker.marker_type is MarkerType.STRUCTURAL]
            if not structural:
                return None
            x = sum(marker.x for marker in structural) / len(structural)
            y = sum(marker.y for marker in structural) / len(structural)
            return self._to_screen(x, y, transform)

        def draw_fix_icon(center: QtCore.QPointF, angle_rad: float = 0.0) -> None:
            painter.save()
            painter.translate(center)
            painter.rotate(math.degrees(angle_rad))
            painter.setPen(QtGui.QPen(QtGui.QColor("#8b2500"), 1.2))
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#f4a261")))
            left = QtGui.QPolygonF([
                QtCore.QPointF(-12.0, 0.0),
                QtCore.QPointF(-3.0, -5.0),
                QtCore.QPointF(-3.0, 5.0),
            ])
            right = QtGui.QPolygonF([
                QtCore.QPointF(12.0, 0.0),
                QtCore.QPointF(3.0, -5.0),
                QtCore.QPointF(3.0, 5.0),
            ])
            painter.drawPolygon(left)
            painter.drawPolygon(right)
            painter.drawLine(QtCore.QPointF(-2.0, -7.0), QtCore.QPointF(-2.0, 7.0))
            painter.drawLine(QtCore.QPointF(2.0, -7.0), QtCore.QPointF(2.0, 7.0))
            painter.restore()

        for constraint in self._pose_constraints:
            kind = constraint.get("kind")
            target_id = constraint.get("target_id")
            metadata = constraint.get("metadata", {})
            if kind == "marker_projected_coordinate":
                point = marker_point(target_id)
                if point is None:
                    continue
                axis_x = float(metadata.get("axis_x", 0.0)) if isinstance(metadata, dict) else 0.0
                draw_fix_icon(point + QtCore.QPointF(0.0, -18.0), 0.0 if axis_x else math.pi / 2.0)
            elif kind == "body_angle":
                point = body_point(target_id)
                if point is not None:
                    draw_fix_icon(point + QtCore.QPointF(0.0, -22.0), math.pi / 4.0)
            elif kind == "relative_body_angle" and isinstance(metadata, dict):
                for body_id in (metadata.get("body_a_id"), metadata.get("body_b_id")):
                    point = body_point(body_id if isinstance(body_id, str) else None)
                    if point is not None:
                        draw_fix_icon(point + QtCore.QPointF(0.0, -22.0), math.pi / 4.0)

    def _draw_forces(
        self,
        painter: QtGui.QPainter,
        project: Project,
        markers: list[CanvasMarker],
        transform,
    ) -> None:
        gravity = project.model.gravity
        if gravity is None:
            return
        marker_map = {marker.entity_id: marker for marker in markers}
        scale_mm_per_n = 3.0
        arrow_color = QtGui.QColor("#e63946")
        text_color = QtGui.QColor("#e63946")
        for body in project.model.bodies:
            if body.mass is None:
                continue
            try:
                mass_result = self.app_service.expression_service.evaluate_property(
                    body.mass, project.parameters
                )
                mass = mass_result.value
            except Exception:
                continue
            if mass <= 0:
                continue
            force = mass * gravity.magnitude
            com_marker = body.com_marker()
            if com_marker is None or com_marker.id not in marker_map:
                continue
            canvas_com = marker_map[com_marker.id]
            com_screen = self._to_screen(canvas_com.x, canvas_com.y, transform)
            dx = gravity.direction_x
            dy = gravity.direction_y
            length = math.sqrt(dx * dx + dy * dy)
            if length == 0:
                continue
            dx /= length
            dy /= length
            arrow_length_mm = force * scale_mm_per_n
            end_x = canvas_com.x + dx * arrow_length_mm
            end_y = canvas_com.y + dy * arrow_length_mm
            end_screen = self._to_screen(end_x, end_y, transform)
            painter.save()
            painter.setOpacity(0.6)
            pen = QtGui.QPen(arrow_color, 3.0, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(com_screen, end_screen)
            screen_dx = end_screen.x() - com_screen.x()
            screen_dy = end_screen.y() - com_screen.y()
            screen_len = math.sqrt(screen_dx * screen_dx + screen_dy * screen_dy)
            if screen_len > 1e-6:
                ux = screen_dx / screen_len
                uy = screen_dy / screen_len
                arrow_size = 12.0
                wing = 6.0
                # Base of the arrowhead (slightly back from the tip)
                bx = end_screen.x() - ux * arrow_size
                by = end_screen.y() - uy * arrow_size
                # Wing vectors perpendicular to the shaft
                wx = -uy * wing
                wy = ux * wing
                p1 = QtCore.QPointF(bx + wx, by + wy)
                p2 = QtCore.QPointF(bx - wx, by - wy)
                painter.setBrush(QtGui.QBrush(arrow_color))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.drawPolygon(QtGui.QPolygonF([end_screen, p1, p2]))
            painter.restore()
            painter.setPen(QtGui.QPen(text_color))
            painter.drawText(end_screen + QtCore.QPointF(8.0, -8.0), f"{force:.2f} N")

    def _draw_loads(
        self,
        painter: QtGui.QPainter,
        project: Project,
        markers: list[CanvasMarker],
        transform,
    ) -> None:
        self._screen_loads = []
        marker_map = {marker.entity_id: marker for marker in markers}
        scale_mm_per_n = 3.0
        base_arrow_color = QtGui.QColor(69, 123, 157, 192)
        base_text_color = QtGui.QColor("#457b9d")
        selected_arrow_color = QtGui.QColor(231, 111, 81, 220)
        selected_text_color = QtGui.QColor("#c75b12")
        for load in project.model.loads:
            canvas_marker = marker_map.get(load.target_marker_id)
            if canvas_marker is None:
                continue
            try:
                time_value = self._simulation_time if self._state_overlay is not None else 0.0
                variables = {"t": self.app_service.unit_service.quantity(time_value, "s")}
                fx = self.app_service.expression_service.evaluate_property(load.fx, project.parameters, variables=variables).value
                fy = self.app_service.expression_service.evaluate_property(load.fy, project.parameters, variables=variables).value
            except Exception:
                fx, fy = 0.0, 0.0
            force = math.sqrt(fx * fx + fy * fy)
            is_selected = self._selected_entity_id == load.id
            marker_screen = self._to_screen(canvas_marker.x, canvas_marker.y, transform)
            if force < 1e-9:
                # Draw a small indicator so time-dependent loads are visible even when zero at t=0
                indicator_color = selected_arrow_color if is_selected else base_arrow_color
                painter.setPen(QtGui.QPen(indicator_color, 2.0))
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawEllipse(marker_screen, 4.0, 4.0)
                self._screen_loads.append((load.id, marker_screen))
                continue
            dx = fx / force
            dy = fy / force
            arrow_length_mm = force * scale_mm_per_n
            end_x = canvas_marker.x + dx * arrow_length_mm
            end_y = canvas_marker.y + dy * arrow_length_mm
            end_screen = self._to_screen(end_x, end_y, transform)
            if is_selected:
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(QtGui.QBrush(QtGui.QColor(231, 111, 81, 45)))
                painter.drawEllipse(end_screen, 14.0, 14.0)
            arrow_color = selected_arrow_color if is_selected else base_arrow_color
            text_color = selected_text_color if is_selected else base_text_color
            painter.save()
            painter.setOpacity(0.7)
            pen = QtGui.QPen(arrow_color, 3.0, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(marker_screen, end_screen)
            screen_dx = end_screen.x() - marker_screen.x()
            screen_dy = end_screen.y() - marker_screen.y()
            screen_len = math.sqrt(screen_dx * screen_dx + screen_dy * screen_dy)
            if screen_len > 1e-6:
                ux = screen_dx / screen_len
                uy = screen_dy / screen_len
                arrow_size = 12.0
                wing = 6.0
                bx = end_screen.x() - ux * arrow_size
                by = end_screen.y() - uy * arrow_size
                wx = -uy * wing
                wy = ux * wing
                p1 = QtCore.QPointF(bx + wx, by + wy)
                p2 = QtCore.QPointF(bx - wx, by - wy)
                painter.setBrush(QtGui.QBrush(arrow_color))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.drawPolygon(QtGui.QPolygonF([end_screen, p1, p2]))
            painter.restore()
            self._screen_loads.append((load.id, end_screen))
            painter.setPen(QtGui.QPen(text_color))
            painter.drawText(end_screen + QtCore.QPointF(8.0, -8.0), f"{force:.2f} N")

    def _draw_reactions(
        self,
        painter: QtGui.QPainter,
        project: Project,
        transform,
    ) -> None:
        if self._state_overlay is None or not project.reaction_outputs:
            return
        arrow_color = QtGui.QColor("#f4a261")
        text_color = QtGui.QColor("#f4a261")
        scale_mm_per_n = 3.0
        for rxn in project.reaction_outputs.values():
            if not rxn.data or not rxn.positions or not rxn.time:
                continue
            t = self._simulation_time
            frame_idx = min(range(len(rxn.time)), key=lambda i: abs(rxn.time[i] - t))
            frame_idx = max(0, min(frame_idx, len(rxn.data) - 1, len(rxn.positions) - 1))
            row = rxn.data[frame_idx]
            fx = row[0] if len(row) > 0 else 0.0
            fy = row[1] if len(row) > 1 else 0.0
            mz = row[3] if len(row) > 3 else 0.0
            force = math.sqrt(fx * fx + fy * fy)
            origin_x, origin_y = rxn.positions[frame_idx]
            origin_screen = self._to_screen(origin_x, origin_y, transform)

            # Force arrow
            if force >= 1e-9:
                dx = fx / force
                dy = fy / force
                arrow_length_mm = force * scale_mm_per_n
                end_x = origin_x + dx * arrow_length_mm
                end_y = origin_y + dy * arrow_length_mm
                end_screen = self._to_screen(end_x, end_y, transform)
                painter.save()
                painter.setOpacity(0.75)
                pen = QtGui.QPen(arrow_color, 3.0, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(origin_screen, end_screen)
                screen_dx = end_screen.x() - origin_screen.x()
                screen_dy = end_screen.y() - origin_screen.y()
                screen_len = math.sqrt(screen_dx * screen_dx + screen_dy * screen_dy)
                if screen_len > 1e-6:
                    ux = screen_dx / screen_len
                    uy = screen_dy / screen_len
                    arrow_size = 12.0
                    wing = 6.0
                    bx = end_screen.x() - ux * arrow_size
                    by = end_screen.y() - uy * arrow_size
                    wx = -uy * wing
                    wy = ux * wing
                    p1 = QtCore.QPointF(bx + wx, by + wy)
                    p2 = QtCore.QPointF(bx - wx, by - wy)
                    painter.setBrush(QtGui.QBrush(arrow_color))
                    painter.setPen(QtCore.Qt.PenStyle.NoPen)
                    painter.drawPolygon(QtGui.QPolygonF([end_screen, p1, p2]))
                painter.restore()
                painter.setPen(QtGui.QPen(text_color))
                painter.drawText(end_screen + QtCore.QPointF(8.0, -8.0), f"{force:.2f} N")

            # Moment arc
            if abs(mz) >= 1e-9:
                arc_radius = 30.0  # screen pixels
                start_deg = 45.0
                span_deg = 270.0 if mz > 0 else -270.0
                end_deg = start_deg + span_deg
                end_rad = math.radians(end_deg)
                arc_rect = QtCore.QRectF(
                    origin_screen.x() - arc_radius, origin_screen.y() - arc_radius,
                    2.0 * arc_radius, 2.0 * arc_radius,
                )
                painter.save()
                painter.setOpacity(0.75)
                pen = QtGui.QPen(arrow_color, 3.0, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawArc(arc_rect, int(start_deg * 16), int(span_deg * 16))
                tip = origin_screen + QtCore.QPointF(arc_radius * math.cos(end_rad), -arc_radius * math.sin(end_rad))
                if mz > 0:
                    tang = QtCore.QPointF(math.sin(end_rad), math.cos(end_rad))
                else:
                    tang = QtCore.QPointF(-math.sin(end_rad), -math.cos(end_rad))
                arrow_size = 10.0
                wing = 5.0
                perp = QtCore.QPointF(-tang.y(), tang.x())
                p1 = tip - tang * arrow_size + perp * wing
                p2 = tip - tang * arrow_size - perp * wing
                painter.setBrush(QtGui.QBrush(arrow_color))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.drawPolygon(QtGui.QPolygonF([tip, p1, p2]))
                painter.restore()
                painter.setPen(QtGui.QPen(text_color))
                painter.drawText(tip + QtCore.QPointF(8.0, -8.0), f"{mz:.3f} Nm")

    def _body_at(self, point: QtCore.QPointF) -> str | None:
        project = self._display_project if self._display_project is not None else self.app_service.project
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
                CanvasMode.CREATE_SKETCH_RECTANGLE,
                CanvasMode.CREATE_SKETCH_CIRCLE,
                CanvasMode.CREATE_SKETCH_ARC_CENTER,
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
        elif constraint_type in {
            SketchConstraintType.DISTANCE,
            SketchConstraintType.HORIZONTAL_DISTANCE,
            SketchConstraintType.VERTICAL_DISTANCE,
            SketchConstraintType.RADIUS,
        }:
            _line(3, 5, 11, 5)
            _line(3, 9, 11, 9)
            _line(2, 3, 2, 7)
            _line(12, 7, 12, 11)
            if constraint_type is SketchConstraintType.HORIZONTAL_DISTANCE:
                _line(4, 11, 10, 11)
            elif constraint_type is SketchConstraintType.VERTICAL_DISTANCE:
                _line(11, 4, 11, 10)
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
        label_position = constraint.metadata.values.get("label_position")
        if isinstance(label_position, list) and len(label_position) == 2:
            label_screen = self._to_screen(float(label_position[0]), float(label_position[1]), transform)
            mx = 0.5 * (s1.x() + s2.x())
            my = 0.5 * (s1.y() + s2.y())
            offset = -(label_screen.x() - mx) * uy + (label_screen.y() - my) * ux
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
                project = self._read_project()
                result = self.app_service.expression_service.evaluate_property(
                    constraint.value, project.parameters
                )
                text = f"{result.value:.4g} {result.unit}"
            except Exception:
                pass
        mid = QtCore.QPointF(0.5 * (d1.x() + d2.x()), 0.5 * (d1.y() + d2.y()))
        painter.setPen(QtGui.QPen(color))
        painter.drawText(mid + QtCore.QPointF(4, -4), text)

    def _draw_radius_annotation(
        self,
        painter: QtGui.QPainter,
        center: CanvasSketchPoint,
        entity: CanvasSketchEntity,
        constraint: SketchConstraint,
        color: QtGui.QColor,
        transform,
    ) -> None:
        if entity.radius is None or entity.radius <= 1e-9:
            return
        center_screen = self._to_screen(center.x, center.y, transform)
        label_position = constraint.metadata.values.get("label_position")
        if isinstance(label_position, list) and len(label_position) == 2:
            label_world = (float(label_position[0]), float(label_position[1]))
            dx = label_world[0] - center.x
            dy = label_world[1] - center.y
        else:
            dx = 1.0
            dy = -0.6
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            dx, dy, length = 1.0, 0.0, 1.0
        ux = dx / length
        uy = dy / length
        rim_world = (center.x + ux * entity.radius, center.y + uy * entity.radius)
        rim_screen = self._to_screen(rim_world[0], rim_world[1], transform)
        painter.setPen(QtGui.QPen(color, 1.0))
        painter.drawLine(center_screen, rim_screen)
        self._draw_arrow(painter, rim_screen, -ux, uy, color)
        text = "R ?"
        if constraint.value is not None:
            try:
                project = self._read_project()
                result = self.app_service.expression_service.evaluate_property(
                    constraint.value, project.parameters
                )
                text = f"R {result.value:.4g} {result.unit}"
            except Exception:
                pass
        text_anchor = rim_screen + QtCore.QPointF(8.0 * ux, -8.0 * uy)
        painter.setPen(QtGui.QPen(color))
        painter.drawText(text_anchor, text)

    def _draw_projected_distance_annotation(
        self,
        painter: QtGui.QPainter,
        s1: QtCore.QPointF,
        s2: QtCore.QPointF,
        constraint: SketchConstraint,
        color: QtGui.QColor,
        transform,
        *,
        axis: int,
    ) -> None:
        label_position = constraint.metadata.values.get("label_position")
        if isinstance(label_position, list) and len(label_position) == 2:
            label_screen = self._to_screen(float(label_position[0]), float(label_position[1]), transform)
            label_axis = label_screen.y() if axis == 0 else label_screen.x()
        else:
            label_axis = 0.5 * (s1.y() + s2.y()) - 18.0 if axis == 0 else 0.5 * (s1.x() + s2.x()) + 18.0
        painter.setPen(QtGui.QPen(color, 0.8, QtCore.Qt.PenStyle.DashLine))
        if axis == 0:
            d1 = QtCore.QPointF(s1.x(), label_axis)
            d2 = QtCore.QPointF(s2.x(), label_axis)
            painter.drawLine(s1, d1)
            painter.drawLine(s2, d2)
            painter.setPen(QtGui.QPen(color, 1.0))
            painter.drawLine(d1, d2)
            self._draw_arrow(painter, d1, 1.0, 0.0, color)
            self._draw_arrow(painter, d2, -1.0, 0.0, color)
            mid = QtCore.QPointF(0.5 * (d1.x() + d2.x()), label_axis)
        else:
            d1 = QtCore.QPointF(label_axis, s1.y())
            d2 = QtCore.QPointF(label_axis, s2.y())
            painter.drawLine(s1, d1)
            painter.drawLine(s2, d2)
            painter.setPen(QtGui.QPen(color, 1.0))
            painter.drawLine(d1, d2)
            self._draw_arrow(painter, d1, 0.0, 1.0, color)
            self._draw_arrow(painter, d2, 0.0, -1.0, color)
            mid = QtCore.QPointF(label_axis, 0.5 * (d1.y() + d2.y()))
        text = "?"
        if constraint.value is not None:
            try:
                project = self._read_project()
                result = self.app_service.expression_service.evaluate_property(
                    constraint.value, project.parameters
                )
                text = f"{result.value:.4g} {result.unit}"
            except Exception:
                pass
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
                project = self._read_project()
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
        project = self._read_project()
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
            self._add_inferred_line_constraint(point_ids[0], point_ids[1])
            message = "Created sketch line segment"
        elif self._mode == CanvasMode.CREATE_SKETCH_CIRCLE:
            p1 = self.app_service.get_sketch_point(point_ids[0])
            p2 = self.app_service.get_sketch_point(point_ids[1])
            if p1 is None or p2 is None:
                raise ValueError("Sketch point not found for circle creation")
            x1 = self.app_service._evaluate_sketch_expression(p1.x, self.app_service.project.parameters)
            y1 = self.app_service._evaluate_sketch_expression(p1.y, self.app_service.project.parameters)
            x2 = self.app_service._evaluate_sketch_expression(p2.x, self.app_service.project.parameters)
            y2 = self.app_service._evaluate_sketch_expression(p2.y, self.app_service.project.parameters)
            radius = math.hypot(x2 - x1, y2 - y1)
            created_id = self.app_service.create_sketch_circle(
                point_ids[0], self._mm_expression(radius), edge_point_id=point_ids[1]
            )
            message = "Created sketch circle"
        elif self._mode == CanvasMode.CREATE_SKETCH_ARC_CENTER:
            pts = [self.app_service.get_sketch_point(pid) for pid in point_ids[:3]]
            if any(p is None for p in pts):
                raise ValueError("Sketch point not found for arc creation")
            params = self.app_service.project.parameters
            coords = [
                (self.app_service._evaluate_sketch_expression(p.x, params),
                 self.app_service._evaluate_sketch_expression(p.y, params))
                for p in pts
            ]
            cx, cy = coords[0]
            sx, sy = coords[1]
            ex_raw, ey_raw = coords[2]
            radius = math.hypot(sx - cx, sy - cy)
            if radius > 1e-9 and abs(math.hypot(ex_raw - cx, ey_raw - cy) - radius) > 1e-6:
                angle = math.atan2(ey_raw - cy, ex_raw - cx)
                self.app_service.move_sketch_point(
                    point_ids[2],
                    self._mm_expression(cx + radius * math.cos(angle)),
                    self._mm_expression(cy + radius * math.sin(angle)),
                )
            created_id = self.app_service.create_sketch_arc(point_ids[0], point_ids[1], point_ids[2])
            message = "Created sketch arc"
        elif self._mode == CanvasMode.CREATE_SKETCH_INFINITE_LINE:
            created_id = self.app_service.create_sketch_infinite_line(point_ids[0], point_ids[1])
            message = "Created sketch infinite line"
        else:
            return
        if created_id is not None:
            self.entitySelected.emit(created_id)
        self.modelChanged.emit(message)
        if self._mode == CanvasMode.CREATE_SKETCH_LINE_SEGMENT and len(point_ids) >= 2:
            end_point = self.app_service.get_sketch_point(point_ids[1])
            if end_point is not None:
                x = self.app_service._evaluate_sketch_expression(end_point.x, self.app_service.project.parameters)
                y = self.app_service._evaluate_sketch_expression(end_point.y, self.app_service.project.parameters)
                self._sensor_marker_ids = [point_ids[1]]
                self._creation_points = [(x, y)]
                self._selected_entity_id = created_id
                self._selected_entity_ids = {created_id} if created_id is not None else set()
                self.update()
                return
        self.set_mode(CanvasMode.SELECT)

    def _canvas_sketch_point_by_id(self, pid: str) -> CanvasSketchPoint | None:
        for cpt, _ in self._screen_sketch_points:
            if cpt.entity_id == pid:
                return cpt
        return None

    def _sketch_point_snapshot(self, pid: str) -> CanvasSketchPoint | None:
        cpt = self._canvas_sketch_point_by_id(pid)
        if cpt is not None:
            return cpt
        if self.app_service.project is None:
            return None
        point = self.app_service.get_sketch_point(pid)
        if point is None:
            return None
        return CanvasSketchPoint(
            entity_id=point.id,
            name=point.name,
            x=self.app_service._evaluate_sketch_expression(point.x, self.app_service.project.parameters),
            y=self.app_service._evaluate_sketch_expression(point.y, self.app_service.project.parameters),
            construction=point.construction,
            visible=point.visible,
        )

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
                cpt = self._sketch_point_snapshot(center_id)
                if cpt:
                    self._creation_points.append((cpt.x, cpt.y))
                    self._sensor_marker_ids.append(center_id)
            elif clicked_sketch_point is not None and pts_left > 0:
                self._creation_points.append((clicked_sketch_point.x, clicked_sketch_point.y))
                self._sensor_marker_ids.append(clicked_sketch_point.entity_id)

        elif self._mode == CanvasMode.CREATE_SKETCH_COINCIDENT:
            if (
                clicked_sketch_entity is not None
                and clicked_sketch_entity.entity_type in (
                    SketchEntityType.CIRCLE,
                    SketchEntityType.ARC,
                    SketchEntityType.LINE_SEGMENT,
                    SketchEntityType.INFINITE_LINE,
                )
                and not self._creation_entity_ids
            ):
                self._creation_entity_ids.append(clicked_sketch_entity.entity_id)
            elif clicked_sketch_point is not None and pts_left > 0:
                self._creation_points.append((clicked_sketch_point.x, clicked_sketch_point.y))
                self._sensor_marker_ids.append(clicked_sketch_point.entity_id)

        # Tangent supports either line+curve or curve+curve.
        elif self._mode == CanvasMode.CREATE_SKETCH_TANGENT:
            if (
                clicked_sketch_entity is not None
                and clicked_sketch_entity.entity_type in (SketchEntityType.CIRCLE, SketchEntityType.ARC)
                and ent_left > 0
                and clicked_sketch_entity.entity_id not in self._creation_entity_ids
            ):
                self._creation_entity_ids.append(clicked_sketch_entity.entity_id)
            elif (
                clicked_sketch_entity is not None
                and clicked_sketch_entity.entity_type in (SketchEntityType.LINE_SEGMENT, SketchEntityType.INFINITE_LINE)
                and pts_left >= 2
            ):
                for pid in clicked_sketch_entity.point_ids[:2]:
                    cpt = self._sketch_point_snapshot(pid)
                    if cpt:
                        self._creation_points.append((cpt.x, cpt.y))
                        self._sensor_marker_ids.append(pid)
            elif clicked_sketch_point is not None and pts_left > 0:
                self._creation_points.append((clicked_sketch_point.x, clicked_sketch_point.y))
                self._sensor_marker_ids.append(clicked_sketch_point.entity_id)

        # Constraints expecting entity refs (ON_CIRCLE)
        elif n_ent > 0:
            if (clicked_sketch_entity is not None
                    and clicked_sketch_entity.entity_type in (SketchEntityType.CIRCLE, SketchEntityType.ARC)
                    and ent_left > 0):
                self._creation_entity_ids.append(clicked_sketch_entity.entity_id)
            elif (clicked_sketch_entity is not None
                    and clicked_sketch_entity.entity_type in (SketchEntityType.LINE_SEGMENT, SketchEntityType.INFINITE_LINE)
                    and pts_left >= 2):
                for pid in clicked_sketch_entity.point_ids[:2]:
                    cpt = self._sketch_point_snapshot(pid)
                    if cpt:
                        self._creation_points.append((cpt.x, cpt.y))
                        self._sensor_marker_ids.append(pid)
            elif clicked_sketch_point is not None and pts_left > 0:
                self._creation_points.append((clicked_sketch_point.x, clicked_sketch_point.y))
                self._sensor_marker_ids.append(clicked_sketch_point.entity_id)

        # DISTANCE on circle: clicking a circle = radius constraint (1 pt + 1 entity)
        elif (
            self._mode == CanvasMode.CREATE_SKETCH_DISTANCE
            and clicked_sketch_entity is not None
            and clicked_sketch_entity.entity_type is SketchEntityType.CIRCLE
            and not self._sensor_marker_ids
        ):
            center_id = clicked_sketch_entity.point_ids[0]
            cpt = self._sketch_point_snapshot(center_id)
            if cpt:
                self._creation_points.append((cpt.x, cpt.y))
                self._sensor_marker_ids.append(center_id)
                self._creation_entity_ids.append(clicked_sketch_entity.entity_id)
                self._finalize_sketch_constraint_creation()
                return

        # Point-only constraints
        else:
            if clicked_sketch_point is not None and pts_left > 0:
                # Point takes priority over line so endpoints can be selected individually
                self._creation_points.append((clicked_sketch_point.x, clicked_sketch_point.y))
                self._sensor_marker_ids.append(clicked_sketch_point.entity_id)
            elif (clicked_sketch_entity is not None
                    and clicked_sketch_entity.entity_type in (SketchEntityType.LINE_SEGMENT, SketchEntityType.INFINITE_LINE)
                    and pts_left > 0):
                if self._mode in _SEGMENT_PAIR_MODES and pts_left >= 2:
                    # PARALLEL / PERPENDICULAR / EQUAL_LENGTH: one segment click = both endpoints
                    for pid in clicked_sketch_entity.point_ids[:2]:
                        cpt = self._sketch_point_snapshot(pid)
                        if cpt:
                            self._creation_points.append((cpt.x, cpt.y))
                            self._sensor_marker_ids.append(pid)
                elif self._mode in _LINE_TWO_POINT_CONSTRAINT_MODES and pts_left >= 2:
                    # Distance-like constraints can be applied directly to a segment/axis.
                    for pid in clicked_sketch_entity.point_ids[:2]:
                        cpt = self._sketch_point_snapshot(pid)
                        if cpt:
                            self._creation_points.append((cpt.x, cpt.y))
                            self._sensor_marker_ids.append(pid)
                elif self._mode == CanvasMode.CREATE_SKETCH_SYMMETRIC and pts_left >= 2:
                    for pid in clicked_sketch_entity.point_ids[:2]:
                        cpt = self._sketch_point_snapshot(pid)
                        if cpt:
                            self._creation_points.append((cpt.x, cpt.y))
                            self._sensor_marker_ids.append(pid)
                else:
                    nearest_id = self._nearest_endpoint_of_entity(
                        clicked_sketch_entity, self._last_mouse_screen
                    )
                    if nearest_id is not None:
                        cpt = self._sketch_point_snapshot(nearest_id)
                        if cpt:
                            self._creation_points.append((cpt.x, cpt.y))
                            self._sensor_marker_ids.append(nearest_id)

        if self._mode == CanvasMode.CREATE_SKETCH_COINCIDENT and self._creation_entity_ids:
            target_pts = 1
            target_ents = 1
        elif self._mode == CanvasMode.CREATE_SKETCH_TANGENT and len(self._creation_entity_ids) >= 2:
            target_pts = 0
            target_ents = 2
        else:
            target_pts = n_pts
            target_ents = n_ent
        collected_pts = min(len(self._sensor_marker_ids), target_pts)
        collected_ents = min(len(self._creation_entity_ids), target_ents)
        if target_ents > 0:
            self.modelChanged.emit(
                f"{_CONSTRAINT_LABEL.get(self._mode, 'Constraint')}: "
                f"{collected_pts}/{target_pts} points, {collected_ents}/{target_ents} curves"
            )
        elif self._mode in _SEGMENT_PAIR_MODES:
            segments_done = len(self._sensor_marker_ids) // 2
            self.modelChanged.emit(
                f"{_CONSTRAINT_LABEL.get(self._mode, 'Constraint')}: "
                f"{segments_done}/2 segments"
            )
        else:
            self.modelChanged.emit(
                f"{_CONSTRAINT_LABEL.get(self._mode, 'Constraint')}: "
                f"{collected_pts}/{target_pts} points"
            )
        required_pts = target_pts
        required_ents = target_ents
        if len(self._sensor_marker_ids) >= required_pts and len(self._creation_entity_ids) >= required_ents:
            if self._mode in {
                CanvasMode.CREATE_SKETCH_DISTANCE,
                CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE,
                CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE,
            } and n_ent == 0:
                self._pending_distance_constraint_refs = list(self._sensor_marker_ids[:n_pts])
                self.modelChanged.emit(f"{_CONSTRAINT_LABEL.get(self._mode, 'Distance')}: click label position")
                return
            self._finalize_sketch_constraint_creation()

    def _finalize_sketch_constraint_creation(self) -> None:
        n_pts = _CONSTRAINT_SPEC.get(self._mode, (2, 0))[0]
        # Radius form: DISTANCE with 1 point + 1 entity ref
        actual_n_pts = (
            1
            if (self._mode == CanvasMode.CREATE_SKETCH_DISTANCE
                and len(self._creation_entity_ids) == 1
                and len(self._sensor_marker_ids) == 1)
            or (self._mode == CanvasMode.CREATE_SKETCH_COINCIDENT
                and len(self._creation_entity_ids) == 1
                and len(self._sensor_marker_ids) == 1)
            else 0
            if (self._mode == CanvasMode.CREATE_SKETCH_TANGENT
                and len(self._creation_entity_ids) == 2
                and len(self._sensor_marker_ids) == 0)
            else n_pts
        )
        point_ids = list(self._sensor_marker_ids[:actual_n_pts])
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
            value_str = f"{angle_deg} deg"
        elif self._mode == CanvasMode.CREATE_SKETCH_TANGENT:
            # External/Internal sign only matters for curve-curve tangency.
            # For line+curve the sign has no geometric meaning — skip the dialog.
            if len(entity_refs) == 2 and not point_ids:
                items = ["External (+1)", "Internal (-1)"]
                item, ok = QtWidgets.QInputDialog.getItem(
                    self, "Tangent Constraint", "Tangency type:", items, 0, False
                )
                if not ok:
                    self.set_mode(CanvasMode.SELECT)
                    return
                value_str = "1" if item == items[0] else "-1"
            else:
                # Line+curve case: sign is irrelevant; pass +1 as a placeholder.
                value_str = "1"

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

    def _apply_creation_inference(self, world: tuple[float, float]) -> tuple[float, float]:
        self._inference_lock = None
        if not self._creation_points:
            return world
        start = self._creation_points[-1]
        tolerance = 6.0 / max(self._current_transform()[0], 1e-9)
        dx = world[0] - start[0]
        dy = world[1] - start[1]
        if abs(dy) <= tolerance:
            self._inference_lock = "horizontal"
            if self._mode == CanvasMode.CREATE_SKETCH_LINE_SEGMENT:
                return world[0], start[1]
        if abs(dx) <= tolerance:
            self._inference_lock = "vertical"
            if self._mode == CanvasMode.CREATE_SKETCH_LINE_SEGMENT:
                return start[0], world[1]
        return world

    def _add_inferred_line_constraint(self, point_a_id: str, point_b_id: str) -> None:
        p1 = self.app_service.get_sketch_point(point_a_id)
        p2 = self.app_service.get_sketch_point(point_b_id)
        if p1 is None or p2 is None or self.app_service.project is None:
            return
        x1 = self.app_service._evaluate_sketch_expression(p1.x, self.app_service.project.parameters)
        y1 = self.app_service._evaluate_sketch_expression(p1.y, self.app_service.project.parameters)
        x2 = self.app_service._evaluate_sketch_expression(p2.x, self.app_service.project.parameters)
        y2 = self.app_service._evaluate_sketch_expression(p2.y, self.app_service.project.parameters)
        tolerance = 1e-6
        try:
            if abs(y2 - y1) <= tolerance:
                self.app_service.create_sketch_constraint(SketchConstraintType.HORIZONTAL.value, [point_a_id, point_b_id])
            elif abs(x2 - x1) <= tolerance:
                self.app_service.create_sketch_constraint(SketchConstraintType.VERTICAL.value, [point_a_id, point_b_id])
        except Exception:
            return

    def _preview_sketch_drag_solution(
        self,
        point_id: str,
        target: tuple[float, float],
    ) -> dict[str, tuple[float, float]]:
        project = self._read_project()
        if project is None or project.sketch is None:
            return {}
        temp_project = deepcopy(project)
        temp_point = temp_project.sketch.entities.get(point_id) if temp_project.sketch is not None else None
        if not isinstance(temp_point, SketchPoint):
            return {}
        temp_point.x.text = self._mm_expression(target[0])
        temp_point.y.text = self._mm_expression(target[1])
        result = self.app_service.sketch_solver.solve(temp_project, locked_point_ids={point_id})
        if not result.success:
            return {}
        return result.positions

    def _finish_box_selection(self, *, additive: bool) -> None:
        if self._box_selection_start is None or self._box_selection_current is None:
            return
        start = self._box_selection_start
        current = self._box_selection_current
        rect = QtCore.QRectF(start, current).normalized()
        crossed = current.x() < start.x()
        selected: set[str] = set(self._selected_entity_ids) if additive else set()
        for point, screen in self._screen_sketch_points:
            if rect.contains(screen):
                selected.add(point.entity_id)
        for entity, geometry in self._screen_sketch_entities:
            bounds = self._screen_geometry_bounds(geometry)
            if bounds is None:
                continue
            contained = rect.contains(bounds.topLeft()) and rect.contains(bounds.bottomRight())
            if (crossed and rect.intersects(bounds)) or (not crossed and contained):
                selected.add(entity.entity_id)
        self._box_selection_start = None
        self._box_selection_current = None
        self._selected_entity_ids = selected
        self._selected_entity_id = next(iter(selected), None)
        if self._selected_entity_id is not None:
            selected_snapshot = set(self._selected_entity_ids)
            primary_snapshot = self._selected_entity_id
            self.entitySelected.emit(self._selected_entity_id)
            self._selected_entity_ids = selected_snapshot
            self._selected_entity_id = primary_snapshot
        else:
            self.selectionCleared.emit()

    def _screen_geometry_bounds(self, geometry: object) -> QtCore.QRectF | None:
        if isinstance(geometry, QtCore.QLineF):
            return QtCore.QRectF(geometry.p1(), geometry.p2()).normalized().adjusted(-3.0, -3.0, 3.0, 3.0)
        if isinstance(geometry, QtCore.QRectF):
            return geometry
        if isinstance(geometry, tuple) and geometry and geometry[0] == "arc":
            return geometry[1]
        return None

    def _snap_world(
        self,
        world: tuple[float, float],
        include_model: bool,
        exclude_point_id: str | None = None,
    ) -> tuple[float, float]:
        project = self._read_project()
        if project is None or project.sketch is None or not project.sketch.visible:
            return world
        candidates: list[SnapCandidate] = []
        sketch_points = self._collect_sketch_points(project)
        point_map = {point.entity_id: point for point in sketch_points}
        threshold = 8.0 / max(self._current_transform()[0], 1e-9)
        for point in sketch_points:
            if point.entity_id == exclude_point_id:
                continue
            distance = math.hypot(world[0] - point.x, world[1] - point.y)
            candidates.append(SnapCandidate(point.x, point.y, "endpoint", 0, distance, point.entity_id))
        entities = self._collect_sketch_entities(project)
        for entity in entities:
            if entity.entity_type in {SketchEntityType.LINE_SEGMENT, SketchEntityType.INFINITE_LINE} and len(entity.point_ids) >= 2:
                p1 = point_map.get(entity.point_ids[0])
                p2 = point_map.get(entity.point_ids[1])
                if p1 is not None and p2 is not None:
                    mx = 0.5 * (p1.x + p2.x)
                    my = 0.5 * (p1.y + p2.y)
                    candidates.append(SnapCandidate(mx, my, "midpoint", 1, math.hypot(world[0] - mx, world[1] - my), entity.entity_id))
            snapped = self._snap_to_sketch_entity(world, entity, point_map)
            if snapped is None:
                continue
            distance = math.hypot(world[0] - snapped[0], world[1] - snapped[1])
            candidates.append(SnapCandidate(snapped[0], snapped[1], "projection", 4, distance, entity.entity_id))
        for ix, iy in self._line_intersection_candidates(entities, point_map):
            candidates.append(SnapCandidate(ix, iy, "intersection", 2, math.hypot(world[0] - ix, world[1] - iy), None))
        if include_model:
            assembled = self._assembled_mechanism(project)
            for marker in self._collect_markers(project, assembled):
                distance = math.hypot(world[0] - marker.x, world[1] - marker.y)
                candidates.append(SnapCandidate(marker.x, marker.y, "model", 5, distance, marker.entity_id))
        self._snap_to_point = False
        self._snap_kind = None
        self._snap_entity_id = None
        close_candidates = [candidate for candidate in candidates if candidate.distance <= threshold * 1.5]
        if close_candidates:
            best = min(close_candidates, key=lambda item: (item.priority, item.distance))
            if (
                self._last_snap_candidate is not None
                and self._last_snap_candidate.distance <= threshold * 1.5
            ):
                sticky = min(
                    close_candidates,
                    key=lambda item: math.hypot(
                        item.x - self._last_snap_candidate.x,
                        item.y - self._last_snap_candidate.y,
                    ),
                )
                sticky_distance = math.hypot(world[0] - sticky.x, world[1] - sticky.y)
                if sticky.kind == self._last_snap_candidate.kind and sticky_distance <= threshold * 1.5:
                    best = sticky
            if best.distance <= threshold:
                self._snap_to_point = True
                self._snap_kind = best.kind
                self._snap_entity_id = best.entity_id
                self._last_snap_candidate = best
                return best.x, best.y
        self._last_snap_candidate = None
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

    def _line_intersection_candidates(
        self,
        entities: list[CanvasSketchEntity],
        point_map: dict[str, CanvasSketchPoint],
    ) -> list[tuple[float, float]]:
        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for entity in entities:
            if entity.entity_type is not SketchEntityType.LINE_SEGMENT or len(entity.point_ids) < 2:
                continue
            p1 = point_map.get(entity.point_ids[0])
            p2 = point_map.get(entity.point_ids[1])
            if p1 is not None and p2 is not None:
                segments.append(((p1.x, p1.y), (p2.x, p2.y)))
        result: list[tuple[float, float]] = []
        for index, (a1, a2) in enumerate(segments):
            for b1, b2 in segments[index + 1:]:
                hit = self._segment_intersection(a1, a2, b1, b2)
                if hit is not None:
                    result.append(hit)
        return result

    def _segment_intersection(
        self,
        a1: tuple[float, float],
        a2: tuple[float, float],
        b1: tuple[float, float],
        b2: tuple[float, float],
    ) -> tuple[float, float] | None:
        ax, ay = a1
        bx, by = a2
        cx, cy = b1
        dx, dy = b2
        den = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
        if abs(den) <= 1e-12:
            return None
        t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / den
        u = ((cx - ax) * (by - ay) - (cy - ay) * (bx - ax)) / den
        if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
            return ax + t * (bx - ax), ay + t * (by - ay)
        return None

    def _draw_springs(
        self,
        painter: QtGui.QPainter,
        project: Project,
        assembled: AssembledMechanism | None,
        transform,
    ) -> None:
        self._screen_springs = []
        if not project.model.springs:
            return
        spring_color = QtGui.QColor("#2a9d8f")
        actuator_color = QtGui.QColor("#8d6cab")
        selected_color = QtGui.QColor("#c75b12")

        for spring in project.model.springs:
            is_selected = self._selected_entity_id == spring.id
            is_actuator = spring.spring_type.value in ("linear_actuator", "rotational_actuator")
            is_rotational = spring.spring_type.value in ("rotational_spring", "rotational_actuator")
            base_color = actuator_color if is_actuator else spring_color
            color = selected_color if is_selected else base_color

            ax, ay = self._spring_endpoint_world(project, spring.endpoint_a, assembled)
            bx, by = self._spring_endpoint_world(project, spring.endpoint_b, assembled)
            if ax is None or bx is None:
                continue

            pt_a = self._to_screen(ax, ay, transform)
            pt_b = self._to_screen(bx, by, transform)
            mid = QtCore.QPointF((pt_a.x() + pt_b.x()) * 0.5, (pt_a.y() + pt_b.y()) * 0.5)
            self._screen_springs.append((spring.id, mid))

            if is_selected:
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(QtGui.QBrush(QtGui.QColor(selected_color.red(), selected_color.green(), selected_color.blue(), 40)))
                painter.drawEllipse(mid, 14.0, 14.0)

            painter.setPen(QtGui.QPen(color, 2.0, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

            if is_rotational:
                self._draw_rotational_spring_symbol(painter, pt_a, pt_b, color, is_actuator)
            else:
                self._draw_linear_spring_symbol(painter, pt_a, pt_b, color, is_actuator)

            painter.setPen(QtGui.QPen(color.darker(130)))
            painter.drawText(mid + QtCore.QPointF(6.0, -6.0), spring.name)

    def _spring_endpoint_world(
        self,
        project: Project,
        ep,
        assembled: AssembledMechanism | None,
    ) -> tuple[float | None, float | None]:
        if ep.kind is SpringEndpointKind.GROUND:
            if ep.ground_x is not None:
                x = self.app_service.expression_service.evaluate_property(ep.ground_x, project.parameters).value
                y = self.app_service.expression_service.evaluate_property(ep.ground_y, project.parameters).value
                return x, y
            return 0.0, 0.0
        if ep.body_id is None or ep.marker_id is None:
            return None, None
        return self._marker_world_position(project, ep.body_id, ep.marker_id, assembled)

    def _draw_linear_spring_symbol(
        self,
        painter: QtGui.QPainter,
        pt_a: QtCore.QPointF,
        pt_b: QtCore.QPointF,
        color: QtGui.QColor,
        is_actuator: bool,
    ) -> None:
        dx = pt_b.x() - pt_a.x()
        dy = pt_b.y() - pt_a.y()
        length = math.hypot(dx, dy)
        if length < 1e-3:
            return
        ux, uy = dx / length, dy / length
        nx, ny = -uy, ux  # normal

        if is_actuator:
            # Cylinder body with double-headed arrow
            shaft = length * 0.5
            cyl_w = 8.0
            half = shaft * 0.5
            cx = (pt_a.x() + pt_b.x()) * 0.5
            cy = (pt_a.y() + pt_b.y()) * 0.5
            c1 = QtCore.QPointF(cx - ux * half, cy - uy * half)
            c2 = QtCore.QPointF(cx + ux * half, cy + uy * half)
            rect_pts = QtGui.QPolygonF([
                c1 + QtCore.QPointF(nx * cyl_w, ny * cyl_w),
                c2 + QtCore.QPointF(nx * cyl_w, ny * cyl_w),
                c2 - QtCore.QPointF(nx * cyl_w, ny * cyl_w),
                c1 - QtCore.QPointF(nx * cyl_w, ny * cyl_w),
            ])
            painter.drawPolygon(rect_pts)
            painter.drawLine(pt_a, c1)
            painter.drawLine(c2, pt_b)
            arrow_size = 8.0
            wing = 4.0
            for tip, direction in ((pt_b, 1.0), (pt_a, -1.0)):
                base = tip - QtCore.QPointF(ux * arrow_size * direction, uy * arrow_size * direction)
                p1 = base + QtCore.QPointF(nx * wing, ny * wing)
                p2 = base - QtCore.QPointF(nx * wing, ny * wing)
                painter.setBrush(QtGui.QBrush(color))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.drawPolygon(QtGui.QPolygonF([tip, p1, p2]))
                painter.setPen(QtGui.QPen(color, 2.0))
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        else:
            # Zigzag spring symbol
            n_coils = 6
            coil_w = 6.0
            lead = min(length * 0.15, 10.0)
            zigzag_len = length - 2.0 * lead
            if zigzag_len < 4.0:
                painter.drawLine(pt_a, pt_b)
                return
            pts = [pt_a]
            pts.append(pt_a + QtCore.QPointF(ux * lead, uy * lead))
            seg_len = zigzag_len / (n_coils * 2)
            for i in range(n_coils * 2):
                t = lead + (i + 1) * seg_len
                side = coil_w if i % 2 == 0 else -coil_w
                pts.append(QtCore.QPointF(
                    pt_a.x() + ux * t + nx * side,
                    pt_a.y() + uy * t + ny * side,
                ))
            pts.append(pt_b - QtCore.QPointF(ux * lead, uy * lead))
            pts.append(pt_b)
            painter.drawPolyline(QtGui.QPolygonF(pts))

    def _draw_rotational_spring_symbol(
        self,
        painter: QtGui.QPainter,
        pt_a: QtCore.QPointF,
        pt_b: QtCore.QPointF,
        color: QtGui.QColor,
        is_actuator: bool,
    ) -> None:
        # Draw at the midpoint between the two endpoints
        cx = (pt_a.x() + pt_b.x()) * 0.5
        cy = (pt_a.y() + pt_b.y()) * 0.5
        center = QtCore.QPointF(cx, cy)
        radius = 14.0
        rect = QtCore.QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0)

        # Dashed line between endpoints
        painter.setPen(QtGui.QPen(color, 1.2, QtCore.Qt.PenStyle.DashLine))
        painter.drawLine(pt_a, pt_b)

        painter.setPen(QtGui.QPen(color, 2.0))
        if is_actuator:
            painter.drawArc(rect, 30 * 16, 300 * 16)
            # Arrow at start of arc
            angle_rad = math.radians(30.0 + 300.0)
            tip = center + QtCore.QPointF(radius * math.cos(math.radians(30.0 + 300.0)), -radius * math.sin(math.radians(30.0 + 300.0)))
            tang = QtCore.QPointF(-math.sin(angle_rad), -math.cos(angle_rad))
            p1 = tip + tang * 5.0 + QtCore.QPointF(-tang.y(), tang.x()) * 3.0
            p2 = tip + tang * 5.0 - QtCore.QPointF(-tang.y(), tang.x()) * 3.0
            painter.setBrush(QtGui.QBrush(color))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawPolygon(QtGui.QPolygonF([tip, p1, p2]))
            painter.setPen(QtGui.QPen(color, 2.0))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            # Second arrow at end
            tip2 = center + QtCore.QPointF(radius * math.cos(math.radians(30.0)), -radius * math.sin(math.radians(30.0)))
            tang2 = QtCore.QPointF(math.sin(math.radians(30.0)), math.cos(math.radians(30.0)))
            p3 = tip2 + tang2 * 5.0 + QtCore.QPointF(-tang2.y(), tang2.x()) * 3.0
            p4 = tip2 + tang2 * 5.0 - QtCore.QPointF(-tang2.y(), tang2.x()) * 3.0
            painter.setBrush(QtGui.QBrush(color))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawPolygon(QtGui.QPolygonF([tip2, p3, p4]))
            painter.setPen(QtGui.QPen(color, 2.0))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        else:
            painter.drawArc(rect, 40 * 16, 280 * 16)
            # Arrow at end of arc
            end_angle = math.radians(40.0 + 280.0)
            tip = center + QtCore.QPointF(radius * math.cos(end_angle), -radius * math.sin(end_angle))
            tang = QtCore.QPointF(math.sin(end_angle), math.cos(end_angle))
            p1 = tip + tang * 6.0 + QtCore.QPointF(-tang.y(), tang.x()) * 3.5
            p2 = tip + tang * 6.0 - QtCore.QPointF(-tang.y(), tang.x()) * 3.5
            painter.setBrush(QtGui.QBrush(color))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawPolygon(QtGui.QPolygonF([tip, p1, p2]))
            painter.setPen(QtGui.QPen(color, 2.0))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

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
                CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE,
                CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE,
                CanvasMode.CREATE_SKETCH_COINCIDENT,
            }:
                polyline_points.append(self._to_screen(self._hover_world[0], self._hover_world[1], transform))
            if len(polyline_points) >= 2:
                painter.drawPolyline(QtGui.QPolygonF(polyline_points))
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#2a9d8f")))
            for point in polyline_points[: len(self._creation_points)]:
                painter.drawEllipse(point, 4.5, 4.5)
        self._draw_pose_pick_preview(painter, transform)
        if self._joint_start_entity is not None and self._hover_world is not None:
            painter.setPen(QtGui.QPen(QtGui.QColor("#8d6cab"), 2.0, QtCore.Qt.PenStyle.DashLine))
            if isinstance(self._joint_start_entity, CanvasMarker):
                start = self._to_screen(self._joint_start_entity.x, self._joint_start_entity.y, transform)
            elif isinstance(self._joint_start_entity, CanvasGround):
                start = self._to_screen(self._joint_start_entity.x, self._joint_start_entity.y, transform)
            else:
                start = self._to_screen(
                    self._joint_start_entity.origin_x,
                    self._joint_start_entity.origin_y,
                    transform,
                )
            end = self._to_screen(self._hover_world[0], self._hover_world[1], transform)
            painter.drawLine(start, end)
        is_spring_mode = self._mode in {
            CanvasMode.CREATE_LINEAR_SPRING,
            CanvasMode.CREATE_LINEAR_ACTUATOR,
        }
        if is_spring_mode and self._hover_world is not None:
            is_actuator_mode = self._mode in {CanvasMode.CREATE_LINEAR_ACTUATOR, CanvasMode.CREATE_ROTATIONAL_ACTUATOR}
            preview_color = QtGui.QColor("#8d6cab") if is_actuator_mode else QtGui.QColor("#2a9d8f")
            hover_screen = self._to_screen(self._hover_world[0], self._hover_world[1], transform)
            if self._spring_start is not None:
                start_screen = self._to_screen(self._spring_start.x, self._spring_start.y, transform)
                painter.setPen(QtGui.QPen(preview_color, 2.0, QtCore.Qt.PenStyle.DashLine))
                painter.drawLine(start_screen, hover_screen)
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(QtGui.QBrush(preview_color))
                painter.drawEllipse(start_screen, 4.5, 4.5)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QBrush(preview_color))
            painter.drawEllipse(hover_screen, 4.5, 4.5)
        if self._pending_distance_constraint_refs and self._hover_world is not None and self.app_service.project is not None:
            point_map = {point.entity_id: point for point in self._collect_sketch_points(self.app_service.project)}
            if all(point_id in point_map for point_id in self._pending_distance_constraint_refs[:2]):
                p1 = point_map[self._pending_distance_constraint_refs[0]]
                p2 = point_map[self._pending_distance_constraint_refs[1]]
                s1 = self._to_screen(p1.x, p1.y, transform)
                s2 = self._to_screen(p2.x, p2.y, transform)
                label = self._to_screen(self._hover_world[0], self._hover_world[1], transform)
                painter.setPen(QtGui.QPen(QtGui.QColor("#2f80ed"), 1.2, QtCore.Qt.PenStyle.DashLine))
                painter.drawLine(s1, label)
                painter.drawLine(s2, label)
                preview_value = QtCore.QLineF(s1, s2).length() / max(transform[0], 1e-9)
                if self._mode == CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE:
                    preview_value = abs(p2.x - p1.x)
                elif self._mode == CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE:
                    preview_value = abs(p2.y - p1.y)
                painter.drawText(label + QtCore.QPointF(6.0, -6.0), f"{preview_value:.3g} mm")
        if self._mode in {
            CanvasMode.CREATE_SKETCH_POINT,
            CanvasMode.CREATE_SKETCH_LINE_SEGMENT,
            CanvasMode.CREATE_SKETCH_RECTANGLE,
            CanvasMode.CREATE_SKETCH_CIRCLE,
            CanvasMode.CREATE_SKETCH_ARC_CENTER,
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
                if self._snap_kind == "midpoint":
                    triangle = QtGui.QPolygonF([
                        snap_point + QtCore.QPointF(0.0, -8.0),
                        snap_point + QtCore.QPointF(7.0, 5.0),
                        snap_point + QtCore.QPointF(-7.0, 5.0),
                    ])
                    painter.drawPolygon(triangle)
                elif self._snap_kind == "intersection":
                    painter.drawLine(snap_point + QtCore.QPointF(-7.0, -7.0), snap_point + QtCore.QPointF(7.0, 7.0))
                    painter.drawLine(snap_point + QtCore.QPointF(-7.0, 7.0), snap_point + QtCore.QPointF(7.0, -7.0))
            else:
                painter.setPen(QtGui.QPen(QtGui.QColor("#c75b12"), 1.4))
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawEllipse(snap_point, 6.5, 6.5)
                painter.drawLine(snap_point + QtCore.QPointF(-8.0, 0.0), snap_point + QtCore.QPointF(8.0, 0.0))
                painter.drawLine(snap_point + QtCore.QPointF(0.0, -8.0), snap_point + QtCore.QPointF(0.0, 8.0))
        if self._box_selection_start is not None and self._box_selection_current is not None:
            rect = QtCore.QRectF(self._box_selection_start, self._box_selection_current).normalized()
            left_to_right = self._box_selection_current.x() >= self._box_selection_start.x()
            color = QtGui.QColor("#2f80ed" if left_to_right else "#2a9d8f")
            painter.setPen(QtGui.QPen(color, 1.2, QtCore.Qt.PenStyle.DashLine))
            fill = QtGui.QColor(color)
            fill.setAlpha(35)
            painter.setBrush(QtGui.QBrush(fill))
            painter.drawRect(rect)

    def _draw_pose_pick_preview(self, painter: QtGui.QPainter, transform) -> None:
        proj = self._read_project()
        if self._mode != CanvasMode.POSE_PICK or not self._pose_pick_marker_ids or proj is None:
            return
        markers = {
            marker.entity_id: marker
            for marker in self._collect_markers(
                proj,
                self._assembled_mechanism(proj),
            )
        }
        points = [
            self._to_screen(markers[marker_id].x, markers[marker_id].y, transform)
            for marker_id in self._pose_pick_marker_ids
            if marker_id in markers
        ]
        if not points:
            return

        color = QtGui.QColor("#2f80ed")
        painter.setPen(QtGui.QPen(color, 2.0, QtCore.Qt.PenStyle.DashLine))
        painter.setBrush(QtGui.QBrush(color))

        def draw_segment(start: QtCore.QPointF, end: QtCore.QPointF) -> None:
            painter.drawLine(start, end)
            painter.drawEllipse(start, 4.5, 4.5)
            painter.drawEllipse(end, 4.5, 4.5)

        if self._pose_pick_preview_kind in {"horiz_angle", "vert_angle"}:
            if len(points) == 1 and self._hover_world is not None:
                hover = self._to_screen(self._hover_world[0], self._hover_world[1], transform)
                draw_segment(points[0], hover)
            elif len(points) >= 2:
                draw_segment(points[0], points[1])
            return

        if self._pose_pick_preview_kind == "relative_angle":
            if len(points) >= 2:
                draw_segment(points[0], points[1])
            elif len(points) == 1 and self._hover_world is not None:
                hover = self._to_screen(self._hover_world[0], self._hover_world[1], transform)
                draw_segment(points[0], hover)
            if len(points) == 3 and self._hover_world is not None:
                hover = self._to_screen(self._hover_world[0], self._hover_world[1], transform)
                draw_segment(points[2], hover)
            elif len(points) >= 4:
                draw_segment(points[2], points[3])

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
                if self._inference_lock:
                    painter.setPen(QtGui.QPen(QtGui.QColor("#2f80ed"), 2.0, QtCore.Qt.PenStyle.DashLine))
                painter.drawPolyline(QtGui.QPolygonF(preview_points))
                start_world = self._creation_points[-1]
                length = math.hypot(preview_world[0] - start_world[0], preview_world[1] - start_world[1])
                angle = math.degrees(math.atan2(preview_world[1] - start_world[1], preview_world[0] - start_world[0]))
                painter.drawText(preview_point + QtCore.QPointF(8.0, -10.0), f"{length:.3g} mm  {angle:.1f} deg")
            return
        if self._mode == CanvasMode.CREATE_SKETCH_RECTANGLE and len(self._creation_points) == 1:
            p1 = self._creation_points[0]
            p2 = preview_world
            top_left = self._to_screen(p1[0], p1[1], transform)
            bottom_right = self._to_screen(p2[0], p2[1], transform)
            rect = QtCore.QRectF(top_left, bottom_right).normalized()
            if self._inference_lock:
                painter.setPen(QtGui.QPen(QtGui.QColor("#2f80ed"), 2.0, QtCore.Qt.PenStyle.DashLine))
            painter.drawRect(rect)
            text = f"{abs(p2[0] - p1[0]):.3g} x {abs(p2[1] - p1[1]):.3g} mm"
            painter.drawText(rect.bottomRight() + QtCore.QPointF(6.0, -6.0), text)
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
                start_deg = math.degrees(math.atan2(sy - cy, sx - cx))
                end_deg = math.degrees(math.atan2(preview_world[1] - cy, preview_world[0] - cx))
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
        label_position = constraint.metadata.values.get("label_position")
        if isinstance(label_position, list) and len(label_position) == 2:
            return self._to_screen(float(label_position[0]), float(label_position[1]), transform)
        refs = [point_map.get(point_id) for point_id in constraint.references]
        refs = [point for point in refs if point is not None]
        if not refs:
            return None
        if constraint.type is SketchConstraintType.RADIUS and len(refs) == 1:
            point = refs[0]
            return self._to_screen(point.x, point.y, transform) + QtCore.QPointF(24.0, -18.0)
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
        name = self._next_name("Bar", [body.name for body in self._read_project().model.bodies])
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

    def _create_point_mass_at(self, world: tuple[float, float]) -> None:
        if not self._require_editing():
            return
        name = self._next_name("Mass", [body.name for body in self._read_project().model.bodies])
        x, y = world
        body_id = self.app_service.create_punctual_mass(name, self._mm_expression(x), self._mm_expression(y))
        self.entitySelected.emit(body_id)
        self.modelChanged.emit(f"Created {name}")
        self.set_mode(CanvasMode.SELECT)

    def _finalize_body_creation(self) -> None:
        if not self._require_editing():
            return
        if not self._creation_points:
            return
        name = self._next_name("Body", [body.name for body in self._read_project().model.bodies])
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
        name = self._next_name("Slider", [slider.name for slider in self._read_project().model.sliders])
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

    def _create_slider_from_marker(self) -> None:
        if not self._require_editing():
            return
        if len(self._creation_points) != 2 or self._slider_creation_marker is None:
            return
        details = self._request_ground_or_slider_joint("SliderJoint")
        if details is None:
            self._creation_points.clear()
            self._slider_creation_marker = None
            self.set_mode(CanvasMode.SELECT)
            return
        name, joint_type = details
        marker = self._slider_creation_marker
        (_, _), (x2, y2) = self._creation_points
        slider_name = self._next_name("Slider", [slider.name for slider in self._read_project().model.sliders])
        slider_id = self.app_service.create_slider_from_points(
            slider_name,
            self._mm_expression(2.0 * marker.x - x2),
            self._mm_expression(2.0 * marker.y - y2),
            self._mm_expression(x2),
            self._mm_expression(y2),
        )
        joint_id = self.app_service.connect_marker_to_slider(
            marker.entity_id,
            slider_id,
            joint_type=joint_type,
            name=name,
            align="marker_to_slider",
        )
        self._creation_points.clear()
        self._slider_creation_marker = None
        self.entitySelected.emit(joint_id)
        self.modelChanged.emit(f"Created {slider_name} and {name}")
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
            (b for b in self._read_project().model.bodies if b.id == new_body_id), None
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

    def _handle_joint_click(self, entity: CanvasMarker | CanvasSlider | CanvasGround) -> None:
        if not self._require_editing():
            return
        if self._joint_start_entity is None:
            self._joint_start_entity = entity
            self.entitySelected.emit(entity.entity_id)
            self.update()
            return
        first = self._joint_start_entity
        self._joint_start_entity = None
        if first.entity_id == entity.entity_id:
            self.update()
            return
        if isinstance(first, CanvasMarker) and isinstance(entity, CanvasMarker):
            self._create_marker_joint(first, entity)
            return
        if isinstance(first, CanvasMarker) and isinstance(entity, CanvasSlider):
            self._create_slider_joint(first, entity, align="marker_to_slider")
            return
        if isinstance(first, CanvasSlider) and isinstance(entity, CanvasMarker):
            self._create_slider_joint(entity, first, align="marker_to_slider")
            return
        if isinstance(first, CanvasMarker) and isinstance(entity, CanvasGround):
            self._create_ground_entity_joint(first, entity)
            return
        if isinstance(first, CanvasGround) and isinstance(entity, CanvasMarker):
            self._create_ground_entity_joint(entity, first)
            return
        self.update()

    def _create_marker_joint(self, first: CanvasMarker, second: CanvasMarker) -> None:
        name = self._request_joint_name()
        if name is None:
            self.update()
            return
        self.app_service.move_marker(first.entity_id, self._mm_expression(second.x), self._mm_expression(second.y))
        if self._mode == CanvasMode.CREATE_RIGID:
            joint_id = self.app_service.create_rigid_joint(
                name,
                JointEndpointInput(JointEndpointKind.MARKER, body_id=first.body_id, marker_id=first.entity_id),
                JointEndpointInput(JointEndpointKind.MARKER, body_id=second.body_id, marker_id=second.entity_id),
            )
        else:
            joint_id = self.app_service.create_joint(
                name,
                "revolute",
                JointEndpointInput(JointEndpointKind.MARKER, body_id=first.body_id, marker_id=first.entity_id),
                JointEndpointInput(JointEndpointKind.MARKER, body_id=second.body_id, marker_id=second.entity_id),
            )
        self.entitySelected.emit(joint_id)
        self.modelChanged.emit(f"Created {name}")
        self.set_mode(CanvasMode.SELECT)

    def _create_ground_entity_joint(self, marker: CanvasMarker, ground: CanvasGround) -> None:
        if not self._require_editing():
            return
        details = self._request_ground_or_slider_joint("GroundJoint")
        if details is None:
            return
        name, joint_type = details
        if joint_type == "rigid":
            joint_id = self.app_service.create_rigid_joint(
                name,
                JointEndpointInput(JointEndpointKind.MARKER, body_id=marker.body_id, marker_id=marker.entity_id),
                JointEndpointInput(JointEndpointKind.MARKER, body_id=ground.entity_id, marker_id=ground.marker_id),
            )
        else:
            joint_id = self.app_service.create_joint(
                name,
                "revolute",
                JointEndpointInput(JointEndpointKind.MARKER, body_id=marker.body_id, marker_id=marker.entity_id),
                JointEndpointInput(JointEndpointKind.MARKER, body_id=ground.entity_id, marker_id=ground.marker_id),
            )
        self.entitySelected.emit(joint_id)
        self.modelChanged.emit(f"Created {name}")
        self.set_mode(CanvasMode.SELECT)

    def _create_free_ground_at(self, world: tuple[float, float]) -> None:
        if not self._require_editing():
            return
        name = self._next_name("Ground", [body.name for body in self._read_project().model.bodies])
        body_id, _marker_id = self.app_service.create_ground_anchor(name, self._mm_expression(world[0]), self._mm_expression(world[1]))
        self.entitySelected.emit(body_id)
        self.modelChanged.emit(f"Created {name}")
        self.set_mode(CanvasMode.SELECT)

    _SPRING_TYPE_NAMES = {
        CanvasMode.CREATE_LINEAR_SPRING: ("linear_spring", "LinearSpring"),
        CanvasMode.CREATE_ROTATIONAL_SPRING: ("rotational_spring", "RotSpring"),
        CanvasMode.CREATE_LINEAR_ACTUATOR: ("linear_actuator", "LinActuator"),
        CanvasMode.CREATE_ROTATIONAL_ACTUATOR: ("rotational_actuator", "RotActuator"),
    }

    def _handle_spring_click(self, clicked_marker: "CanvasMarker | None", world: tuple[float, float]) -> None:
        if not self._require_editing():
            self._spring_start = None
            self._spring_start_world = None
            return

        if self._spring_start is None and self._spring_start_world is None:
            # First click must be on a body marker — ignore empty-canvas clicks
            if clicked_marker is not None:
                self._spring_start = clicked_marker
                self.update()
            return

        # Second click: guard against mode switch between first and second clicks
        if self._mode not in self._SPRING_TYPE_NAMES:
            self._spring_start = None
            self._spring_start_world = None
            self.update()
            return

        # Reject same-marker for both endpoints
        if clicked_marker is not None and self._spring_start is not None:
            if clicked_marker.entity_id == self._spring_start.entity_id:
                self._spring_start = None
                self._spring_start_world = None
                self.update()
                return

        spring_type_str, default_prefix = self._SPRING_TYPE_NAMES[self._mode]
        existing_names = [s.name for s in self._read_project().model.springs]
        name = self._next_name(default_prefix, existing_names)

        def _make_ep(marker: "CanvasMarker | None", world_pos: "tuple[float, float]") -> SpringEndpoint:
            if marker is not None:
                return SpringEndpoint(kind=SpringEndpointKind.MARKER, body_id=marker.body_id, marker_id=marker.entity_id)
            # No marker clicked — create an editable ground anchor body at that position
            anchor_ep = self._create_ground_anchor(world_pos)
            if anchor_ep is not None:
                return anchor_ep
            # Fallback (should not happen): raw ground coordinate
            from quino.domain.model import ScalarProperty
            from quino.domain.types import Dimension
            gx, gy = world_pos
            return SpringEndpoint(
                kind=SpringEndpointKind.GROUND,
                ground_x=ScalarProperty(expression=f"{gx:.6g} mm", unit="mm", expected_dimension=Dimension.LENGTH),
                ground_y=ScalarProperty(expression=f"{gy:.6g} mm", unit="mm", expected_dimension=Dimension.LENGTH),
            )

        ep_a = _make_ep(self._spring_start, self._spring_start_world or (0.0, 0.0))
        ep_b = _make_ep(clicked_marker, world)
        self._spring_start = None
        self._spring_start_world = None
        try:
            spring_id = self.app_service.create_spring(name, spring_type_str, ep_a, ep_b)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Create Spring Failed", str(exc))
            self.set_mode(CanvasMode.SELECT)
            return
        self.entitySelected.emit(spring_id)
        self.modelChanged.emit(f"Created {name}")
        self.set_mode(CanvasMode.SELECT)

    def _create_ground_anchor(self, world_pos: tuple[float, float]) -> "SpringEndpoint | None":
        """Create a PointMass body + rigid ground joint at world_pos; return a MARKER SpringEndpoint for it."""
        project = self._read_project()
        if project is None:
            return None
        existing_body_names = [b.name for b in project.model.bodies]
        anchor_name = self._next_name("Anchor", existing_body_names)
        gx, gy = world_pos
        x_expr = self._mm_expression(gx)
        y_expr = self._mm_expression(gy)
        try:
            body_id, marker_id = self.app_service.create_ground_anchor(anchor_name, x_expr, y_expr)
        except Exception:
            return None
        return SpringEndpoint(kind=SpringEndpointKind.MARKER, body_id=body_id, marker_id=marker_id)

    def _handle_rotational_spring_click(self, joint_id: str | None) -> None:
        if not self._require_editing():
            return
        if joint_id is None:
            return
        project = self._read_project()
        if project is None:
            return
        joint = next((j for j in project.model.joints if j.id == joint_id), None)
        if joint is None:
            return

        assembled = self._assembled_mechanism(project)
        markers = self._collect_markers(project, assembled)
        marker_map = {cm.entity_id: cm for cm in markers}

        def _joint_ep_to_spring_ep(ep, other_ep) -> SpringEndpoint:
            from quino.domain.model import ScalarProperty
            from quino.domain.types import Dimension
            if ep.kind is JointEndpointKind.MARKER:
                return SpringEndpoint(
                    kind=SpringEndpointKind.MARKER,
                    body_id=ep.body_id,
                    marker_id=ep.marker_id,
                )
            pos_x, pos_y = 0.0, 0.0
            if other_ep.kind is JointEndpointKind.MARKER and other_ep.marker_id in marker_map:
                cm = marker_map[other_ep.marker_id]
                pos_x, pos_y = cm.x, cm.y
            return SpringEndpoint(
                kind=SpringEndpointKind.GROUND,
                ground_x=ScalarProperty(expression=f"{pos_x:.6g} mm", unit="mm", expected_dimension=Dimension.LENGTH),
                ground_y=ScalarProperty(expression=f"{pos_y:.6g} mm", unit="mm", expected_dimension=Dimension.LENGTH),
            )

        ep_a = _joint_ep_to_spring_ep(joint.endpoint_a, joint.endpoint_b)
        ep_b = _joint_ep_to_spring_ep(joint.endpoint_b, joint.endpoint_a)

        spring_type_str, default_prefix = self._SPRING_TYPE_NAMES[self._mode]
        existing_names = [s.name for s in project.model.springs]
        name = self._next_name(default_prefix, existing_names)

        try:
            spring_id = self.app_service.create_spring(name, spring_type_str, ep_a, ep_b)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Create Spring Failed", str(exc))
            self.set_mode(CanvasMode.SELECT)
            return
        self.entitySelected.emit(spring_id)
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
        default_name = self._next_name("Joint", [joint.name for joint in self._read_project().model.joints])
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
            self._next_name("Joint", [joint.name for joint in self._read_project().model.joints])
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
        name_edit = QtWidgets.QLineEdit(self._next_name(prefix, [joint.name for joint in self._read_project().model.joints]))
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

    def _add_load_dialog(self, marker_id: str) -> None:
        if not self._require_editing():
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Add Load")
        layout = QtWidgets.QFormLayout(dialog)
        name_edit = QtWidgets.QLineEdit("Load")
        fx_edit = QtWidgets.QLineEdit("0 N")
        fy_edit = QtWidgets.QLineEdit("0 N")
        layout.addRow("Name:", name_edit)
        layout.addRow("Fx:", fx_edit)
        layout.addRow("Fy:", fy_edit)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() != int(QtWidgets.QDialog.DialogCode.Accepted):
            return
        name = name_edit.text().strip()
        fx = fx_edit.text().strip()
        fy = fy_edit.text().strip()
        if not name:
            return
        try:
            self.app_service.create_load(name, marker_id, fx, fy)
            self.modelChanged.emit(f"Added load {name}")
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Add Load Failed", str(exc))

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

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Edit Driver Law")
        layout = QtWidgets.QVBoxLayout(dialog)

        hint = QtWidgets.QLabel(
            "Expression for position/angle as a function of time.\n"
            "Use <b>t</b> for time (has unit <i>s</i>).\n"
            "Examples: &nbsp;<code>90 deg * t / 1 s</code> &nbsp;|&nbsp; <code>50 mm * sin(t * 1 rad / 1 s)</code>"
        )
        hint.setWordWrap(True)
        hint.setTextFormat(QtCore.Qt.TextFormat.RichText)
        layout.addWidget(hint)

        form = QtWidgets.QFormLayout()
        law_edit = QtWidgets.QLineEdit(driver.law.expression)
        form.addRow("Law:", law_edit)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        text = law_edit.text().strip()
        if not text:
            return
        self.app_service.update_property(driver_id, "law", PropertyValueInput("expression", text))
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
        project = self._read_project()
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
            [driver.name for driver in self._read_project().model.drivers],
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

    def _create_load_from_marker(self, marker_id: str) -> None:
        if not self._require_editing():
            return
        default_name = self._next_name(
            "Load",
            [load.name for load in self._read_project().model.loads],
        )
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Add Load")
        layout = QtWidgets.QFormLayout(dialog)
        name_edit = QtWidgets.QLineEdit(default_name)
        fx_edit = QtWidgets.QLineEdit("0 N")
        fy_edit = QtWidgets.QLineEdit("0 N")
        layout.addRow("Name:", name_edit)
        layout.addRow("Fx:", fx_edit)
        layout.addRow("Fy:", fy_edit)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() != int(QtWidgets.QDialog.DialogCode.Accepted):
            self.set_mode(CanvasMode.SELECT)
            return
        name = name_edit.text().strip()
        fx = fx_edit.text().strip()
        fy = fy_edit.text().strip()
        if not name:
            self.set_mode(CanvasMode.SELECT)
            return
        try:
            self.app_service.create_load(name, marker_id, fx, fy)
            self.modelChanged.emit(f"Added load {name}")
            self.set_mode(CanvasMode.SELECT)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Add Load Failed", str(exc))
            self.set_mode(CanvasMode.SELECT)

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
            [sensor.name for sensor in self._read_project().model.sensors],
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
        if self._interaction_mode == "pose":
            return self._editing_enabled
        if self._editing_enabled:
            if self._edit_guard is None or self._edit_guard():
                return True
            self.modelChanged.emit("Model edit cancelled")
            return False
        self.modelChanged.emit("Editing is only available at t=0")
        return False

    def _offset_point(self, point: QtCore.QPointF, direction: QtCore.QPointF, scale: float) -> QtCore.QPointF:
        return QtCore.QPointF(point.x() + direction.x() * scale, point.y() + direction.y() * scale)
