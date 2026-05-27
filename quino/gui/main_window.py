from __future__ import annotations

import copy
import math
import re
from pathlib import Path

from quino.gui.icons import get_icon
from quino.gui.widgets.tree_delegate import TreeBranchDelegate
from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.example_registry import ExampleEntry, ExampleRegistry
from quino.application.service import ApplicationService
from quino.gui.analysis_modes import mode_controller_for
from quino.domain.inputs import PropertyValueInput
from quino.domain.types import DriverType, JointEndpointKind, MarkerType
from quino.domain.blocks import BlockDiagram
from quino.domain.model import (
    Body,
    Driver,
    Expression,
    GravityLoad,
    Joint,
    Load,
    Marker,
    Parameter,
    ReactionOutput,
    Sensor,
    SimulationResult,
    Sketch,
    SketchConstraint,
    SketchConstraintType,
    SketchArc,
    SketchCircle,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
    Slider,
    Spring,
)
from quino.domain.workspace import Pose
from quino.application._context import _WorkspaceProjectProxy as Project  # back-compat alias
from quino.gui.canvas import CanvasMode, MechanismCanvas

from quino.gui.panels.pose_constraints_strip import PoseConstraintsStrip
from quino.gui.panels.workflow_tree_panel import WorkflowTreePanel
from quino.gui.widgets.run_status_widget import RunStatusWidget
from quino.pose.geometry import assembled_reference_mechanism, marker_world_position, pose_to_state_overlay
from quino.pose.kinematics import _pose_at_angle, build_drag_initial_pose, get_drag_driver, has_ground_revolute
from quino.pose.model import PoseConstraint, PoseSolveResult, PoseSolveSettings
from quino.services.expressions import DimensionMismatchError
from quino.services.plot_renderer import load_artifact, render_plot
from quino.simulation.sensor_expressions import safe_sensor_var, sensor_channel_keys
from quino.viewer.plot_window import PlotWindow
from quino.gui.widgets.inspector_widget import InspectorPropertyWidget
from quino.gui.blocks import BlockEditorWidget
from quino.gui.widgets.divergences_dock import DivergencesDock


def _changed_entity_ids_for_case(case) -> set[str]:
    """Return entity ids that have overrides, additions, or removals in the case."""
    ids = set()
    for path in case.invariant_values:
        parts = path.split("/")
        if len(parts) >= 2:
            ids.add(parts[1])
    for entity_id in case.removed_entity_ids:
        ids.add(entity_id)
    for domain, entities in case.added_entities.items():
        for ent in entities:
            eid = ent.get("id")
            if eid:
                ids.add(eid)
    return ids


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, app_service: ApplicationService | None = None) -> None:
        super().__init__()
        self.app_service = app_service or ApplicationService()
        if self.app_service.project is None:
            self.app_service.new_project("Untitled")
        # Wire the confirmation prompt that command-services raise before
        # they flip persisted runs to 'stale'. Without this the hook stays
        # at its no-op default and the user never sees a warning before
        # losing run data on a non-cosmetic edit.
        self.app_service._service_context.confirm_run_invalidation = (
            self._confirm_run_invalidation_dialog
        )

        self._selected_entity_id: str | None = None
        self._suspend_property_updates = False
        self._suspend_parameter_updates = False
        self._suspend_tree_injection = False
        self._suspend_simulation_config_updates = False
        self._last_simulation_result: SimulationResult | None = None
        self._last_simulation_state: dict[str, float] | None = None
        self._last_dof_info: str = ""
        self._current_frame_index = 0
        self._current_project_path: Path | None = None
        self._project_dirty = False
        self._plot_windows: list[PlotWindow] = []
        self._active_mode_controller = None
        self._mounted_analysis_panel: QtWidgets.QWidget | None = None
        self._tree_items: dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._expanded_tree_keys: set[str] = set()
        self._pose_constraints: dict[str, PoseConstraint] = {}
        self._pose_pick_state: dict | None = None
        self._active_prescribe_action: QtGui.QAction | None = None
        self._pending_pose_drag: tuple[str, float, float] | None = None
        self._playback_timer = QtCore.QTimer(self)
        self._playback_timer.timeout.connect(self._advance_playback)
        self._pose_drag_timer = QtCore.QTimer(self)
        self._pose_drag_timer.setInterval(50)
        self._pose_drag_timer.timeout.connect(self._process_pending_pose_drag)

        self._update_window_title()
        _icon_path = Path(__file__).parent / "icons" / "quino_app_icon_transparent_1024.png"
        if _icon_path.exists():
            self.setWindowIcon(QtGui.QIcon(str(_icon_path)))
        self.resize(1480, 920)
        self._build_ui()
        self.refresh_all()

    def _build_ui(self) -> None:
        self._app_mode = "model"
        self._build_actions()
        self._mode_selector_widget = self._build_mode_indicator()
        self._build_menu()
        self._build_common_toolbar()
        self._build_sketch_toolbar()
        self._build_model_toolbar()
        self._build_pose_toolbar()
        self._build_analysis_toolbar()
        self._mode_model_btn.setChecked(True)
        self._mode_sketch_btn.setChecked(False)
        self._mode_pose_btn.setChecked(False)
        self._mode_analysis_btn.setChecked(False)
        self.action_mode_model.setChecked(True)
        self.action_mode_sketch.setChecked(False)
        self.action_mode_pose.setChecked(False)
        self.action_mode_analysis.setChecked(False)
        self._sketch_toolbar.setVisible(False)
        self._model_toolbar.setVisible(True)
        self._pose_toolbar.setVisible(False)
        self._analysis_toolbar.setVisible(False)

        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Model", "Type"])
        self.tree.setIconSize(QtCore.QSize(18, 18))
        self.tree.setIndentation(18)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setAlternatingRowColors(False)
        from quino.gui.tree_branches import tree_branch_stylesheet
        self.tree.setStyleSheet(
            "QTreeWidget { background-color: #eef3f8; } "
            "QTreeWidget::item { background-color: #eef3f8; color: #3d3d3d; padding: 2px; } "
            "QTreeWidget::item:selected { background-color: #d4e5f7; color: #3d3d3d; outline: none; border: none; }"
            + tree_branch_stylesheet()
        )
        self.tree.setUniformRowHeights(True)
        self._tree_delegate = TreeBranchDelegate(self.tree)
        self.tree.setItemDelegateForColumn(0, self._tree_delegate)
        self._tree_delegate.visibility_toggled.connect(self._on_tree_visibility_toggled)
        self.tree.currentItemChanged.connect(self._on_tree_selection_changed)
        self.tree.itemDoubleClicked.connect(self._on_tree_item_double_clicked)

        self.left_column = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.left_column.setChildrenCollapsible(False)
        self.workflow_panel = WorkflowTreePanel(self.app_service)
        self.workflow_panel.case_selected.connect(self._on_case_selected)
        self.workflow_panel.pose_selected.connect(self._on_workflow_pose_selected)
        self.workflow_panel.analysis_selected.connect(self._on_analysis_selected)
        self.workflow_panel.run_selected.connect(self._on_run_selected)
        self.run_status = RunStatusWidget()
        self.run_status.cancel_requested.connect(self._on_cancel_run_requested)
        self.left_column.addWidget(self.workflow_panel)
        self.left_column.addWidget(self.run_status)
        self.left_column.addWidget(self.tree)
        self.left_column.setSizes([180, 36, 180])
        splitter.addWidget(self.left_column)

        executor = self.app_service.ensure_executor()
        executor.run_queued.connect(self._on_executor_run_queued)
        executor.run_started.connect(self._on_executor_run_started)
        executor.run_finished.connect(self._on_executor_run_finished)

        self._divergences_dock_widget = DivergencesDock(self.app_service)
        self._divergences_dock = QtWidgets.QDockWidget("Divergences", self)
        self._divergences_dock.setWidget(self._divergences_dock_widget)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self._divergences_dock)
        self._divergences_dock.hide()

        center_panel = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.canvas = MechanismCanvas(self.app_service)
        self.canvas.entitySelected.connect(self._select_entity_by_id)
        self.canvas.selectionCleared.connect(self._clear_selection)
        self.canvas.modelChanged.connect(self._on_canvas_model_changed)
        self.canvas.modeChanged.connect(self._on_canvas_mode_changed)
        self.canvas.dofInfoChanged.connect(self._on_dof_info_changed)
        self.canvas.poseMarkerDragged.connect(self._on_canvas_pose_marker_drag)
        self.canvas.poseMarkerPicked.connect(self._advance_pose_pick)
        self.canvas.set_edit_guard(self._prepare_for_model_edit)
        self.canvas.set_structural_edit_guard(self._check_structural_edit_allowed)
        self.action_fit_view.triggered.connect(self.canvas.fit_view)
        self._block_editor = BlockEditorWidget()
        self._block_editor.set_app_service(self.app_service)
        self._block_editor.diagramChanged.connect(self._on_block_diagram_changed)
        self._block_editor._scene.validationError.connect(self._on_block_validation_error)
        self._block_editor.blockSelected.connect(self._select_block)
        self._block_editor.selectionCleared.connect(self._clear_selection)

        self._canvas_stack = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self._canvas_stack.addWidget(self.canvas)
        self._canvas_stack.addWidget(self._block_editor)
        self._canvas_stack.setSizes([600, 250])
        self._canvas_stack.setChildrenCollapsible(True)

        self._center_stack = QtWidgets.QStackedWidget()
        self._center_stack.addWidget(self._canvas_stack)

        self._mode_selector_widget.setParent(self._center_stack)
        self._mode_selector_widget.adjustSize()
        self._mode_selector_widget.setFixedSize(self._mode_selector_widget.sizeHint())
        self._mode_selector_widget.raise_()
        # Anchor the indicator to the top-right; reposition on resize.
        self._center_stack.installEventFilter(self)
        self._position_mode_indicator()

        center_panel.addWidget(self._center_stack)

        self._playback_widget = QtWidgets.QWidget()
        playback_layout = QtWidgets.QVBoxLayout(self._playback_widget)
        playback_layout.setContentsMargins(6, 6, 6, 6)
        playback_layout.setSpacing(6)

        self.action_run_button = QtWidgets.QToolButton()
        self.action_play_button = QtWidgets.QToolButton()
        self.action_stop_button = QtWidgets.QToolButton()
        self.action_run_button.setDefaultAction(self.action_run)
        self.action_play_button.setDefaultAction(self.action_play_pause)
        self.action_stop_button.setDefaultAction(self.action_stop)
        self.timeline_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.timeline_slider.setRange(0, 0)
        self.timeline_slider.valueChanged.connect(self._on_timeline_changed)
        self.timeline_label = QtWidgets.QLabel("0 / 0")
        self.timeline_label.setMinimumWidth(80)
        self.playback_speed_spin = QtWidgets.QDoubleSpinBox()
        self.playback_speed_spin.setRange(0.0005, 100.0)
        self.playback_speed_spin.setDecimals(6)
        self.playback_speed_spin.setValue(1.0)
        self.playback_speed_spin.setSuffix(" x")
        self.playback_speed_spin.setMaximumWidth(80)
        self.duration_spin = QtWidgets.QDoubleSpinBox()
        self.duration_spin.setRange(0.001, 999999.0)
        self.duration_spin.setDecimals(3)
        self.duration_spin.setValue(1.0)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setMaximumWidth(100)
        self.steps_spin = QtWidgets.QSpinBox()
        self.steps_spin.setRange(1, 99999999)
        self.steps_spin.setValue(100)
        self.steps_spin.setMaximumWidth(100)
        self.dt_spin = QtWidgets.QDoubleSpinBox()
        self.dt_spin.setRange(1e-9, 999999.0)
        self.dt_spin.setDecimals(6)
        self.dt_spin.setValue(0.01)
        self.dt_spin.setSuffix(" s")
        self.dt_spin.setMaximumWidth(100)

        self.duration_spin.valueChanged.connect(self._on_duration_changed)
        self.steps_spin.valueChanged.connect(self._on_steps_changed)
        self.dt_spin.valueChanged.connect(self._on_dt_changed)
        self.playback_speed_spin.valueChanged.connect(self._on_playback_speed_changed)
        self._update_simulation_spin_steps()
        center_panel.addWidget(self._playback_widget)
        # The Analysis bar (run/play/stop + duration/frames/dt) is reserved
        # for analysis mode. Other modes don't need it and seeing it on
        # startup confuses the user. We hide it immediately after creation
        # and rely on _set_app_mode("analysis") to bring it back.
        self._playback_widget.setVisible(False)

        center_panel.setSizes([600, 80])
        splitter.addWidget(center_panel)

        right_panel = QtWidgets.QTabWidget()
        splitter.addWidget(right_panel)

        inspector_widget = QtWidgets.QWidget()
        inspector_vbox = QtWidgets.QVBoxLayout(inspector_widget)
        inspector_vbox.setContentsMargins(0, 0, 0, 0)
        inspector_vbox.setSpacing(0)

        # Title label: shows selected entity name + type
        self.inspector_title = QtWidgets.QLabel()
        self.inspector_title.setContentsMargins(8, 6, 8, 4)
        self.inspector_title.setTextFormat(QtCore.Qt.TextFormat.RichText)
        title_font = self.inspector_title.font()
        title_font.setPointSize(title_font.pointSize() + 1)
        self.inspector_title.setFont(title_font)
        inspector_vbox.addWidget(self.inspector_title)

        sep_line = QtWidgets.QFrame()
        sep_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        inspector_vbox.addWidget(sep_line)

        # Splitter: table on top, relations below — both always visible
        inspector_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        inspector_splitter.setChildrenCollapsible(False)
        inspector_vbox.addWidget(inspector_splitter, stretch=1)

        # Inspector property form (replaces old table)
        self.inspector = InspectorPropertyWidget()
        self.inspector.property_changed.connect(self._on_inspector_property_changed)
        self.inspector.override_reset_requested.connect(self._on_inspector_override_reset)
        inspector_scroll = QtWidgets.QScrollArea()
        inspector_scroll.setWidget(self.inspector)
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        inspector_scroll.setStyleSheet("QScrollArea { border: none; }")
        inspector_splitter.addWidget(inspector_scroll)

        # Relations area: rebuilt on each selection
        self.relations_widget = QtWidgets.QScrollArea()
        self.relations_widget.setWidgetResizable(True)
        self.relations_widget.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        relations_inner = QtWidgets.QWidget()
        self.relations_vbox = QtWidgets.QVBoxLayout(relations_inner)
        self.relations_vbox.setContentsMargins(8, 4, 8, 8)
        self.relations_vbox.setSpacing(1)
        self.relations_vbox.addStretch(1)
        self.relations_widget.setWidget(relations_inner)
        inspector_splitter.addWidget(self.relations_widget)
        inspector_splitter.setSizes([320, 160])

        right_panel.addTab(inspector_widget, "Inspector")

        parameters_widget = QtWidgets.QWidget()
        parameters_layout = QtWidgets.QVBoxLayout(parameters_widget)
        parameters_layout.setContentsMargins(0, 0, 0, 0)
        parameters_toolbar = QtWidgets.QHBoxLayout()
        self.add_parameter_button = QtWidgets.QPushButton(get_icon("add", "#3d3d3d"), "Add")
        self.add_parameter_button.clicked.connect(self._add_parameter)
        self.delete_parameter_button = QtWidgets.QPushButton(get_icon("remove", "#8b2500"), "Delete")
        self.delete_parameter_button.clicked.connect(self._delete_selected_parameter)
        parameters_toolbar.addWidget(self.add_parameter_button)
        parameters_toolbar.addWidget(self.delete_parameter_button)
        parameters_toolbar.addStretch(1)
        parameters_layout.addLayout(parameters_toolbar)
        self.parameters_table = QtWidgets.QTableWidget(0, 4)
        self.parameters_table.setHorizontalHeaderLabels(["Name", "Expression", "Unit", "Description"])
        self.parameters_table.horizontalHeader().setStretchLastSection(True)
        self.parameters_table.itemChanged.connect(self._on_parameter_item_changed)
        parameters_layout.addWidget(self.parameters_table)
        right_panel.addTab(parameters_widget, "Parameters")

        self.validation_view = QtWidgets.QPlainTextEdit()
        self.validation_view.setReadOnly(True)
        right_panel.addTab(self.validation_view, "Validation")

        self.messages = QtWidgets.QPlainTextEdit()
        self.messages.setReadOnly(True)
        right_panel.addTab(self.messages, "Messages")

        self.canvas_summary = QtWidgets.QPlainTextEdit()
        self.canvas_summary.setReadOnly(True)
        right_panel.addTab(self.canvas_summary, "Info")

        self._right_panel_tabs = right_panel

        # PoseConstraintsStrip: shown only in pose mode as a compact side strip.
        self.pose_constraints_strip = PoseConstraintsStrip(self.app_service)
        self.pose_constraints_strip.setVisible(False)
        self.pose_constraints_strip.constraint_selected.connect(self._on_pose_constraint_selected)
        self.pose_constraints_strip.constraint_delete_requested.connect(self._delete_pose_constraint)
        splitter.addWidget(self.pose_constraints_strip)

        splitter.setSizes([280, 720, 440])
        self.tree.setMinimumWidth(200)
        right_panel.setMinimumWidth(320)
        self.setCentralWidget(central)
        self.canvas.set_interaction_mode("model")

        self.statusBar().showMessage(self.app_service.simulation_runner.describe_backend())

    def _build_actions(self) -> None:
        color_base = "#3d3d3d"
        color_sketch = "#7a7f87"
        color_kinematic = "#2f6f9f"
        color_dynamic = "#c7781d"
        color_dynamic_dark = "#a85f14"
        color_sensor = "#21815e"
        color_pose = "#7b5aa6"
        color_danger = "#8b2500"

        self.action_new = QtGui.QAction(get_icon("file-new", color_base), "New", self)
        self.action_new.triggered.connect(self._new_project)
        self.action_new.setToolTip("Create a new project")

        self.action_open = QtGui.QAction(get_icon("folder-open", color_base), "Open", self)
        self.action_open.triggered.connect(self._open_project)
        self.action_open.setToolTip("Open a project file")

        self.action_save = QtGui.QAction(get_icon("content-save", color_base), "Save", self)
        self.action_save.triggered.connect(self._save_project)
        self.action_save.setToolTip("Save project")

        self.action_save_as = QtGui.QAction(get_icon("content-save-as", color_base), "Save As", self)
        self.action_save_as.triggered.connect(self._save_project_as)
        self.action_save_as.setToolTip("Save project to a new file")

        self.action_undo = QtGui.QAction(get_icon("undo", color_base), "Undo", self)
        self.action_undo.setShortcut(QtGui.QKeySequence.StandardKey.Undo)
        self.action_undo.triggered.connect(self._undo)
        self.action_undo.setToolTip("Undo last action (Ctrl+Z)")

        self.action_redo = QtGui.QAction(get_icon("redo", color_base), "Redo", self)
        self.action_redo.setShortcut(QtGui.QKeySequence.StandardKey.Redo)
        self.action_redo.triggered.connect(self._redo)
        self.action_redo.setToolTip("Redo last undone action (Ctrl+Y)")

        self.action_validate = QtGui.QAction(get_icon("check-circle", color_dynamic), "Validate", self)
        self.action_validate.triggered.connect(self.validate_model)
        self.action_validate.setToolTip("Validate model")

        self.action_run = QtGui.QAction(get_icon("run-simulation", color_dynamic), "Run", self)
        self.action_run.triggered.connect(self._on_run_action_triggered)
        self.action_run.setToolTip("Run kinematic simulation")

        self._icon_play = get_icon("play", color_dynamic)
        self._icon_pause = get_icon("pause", color_dynamic)
        self.action_play_pause = QtGui.QAction(self._icon_play, "Play", self)
        self.action_play_pause.triggered.connect(self.toggle_playback)
        self.action_play_pause.setToolTip("Play/pause animation")

        self.action_stop = QtGui.QAction(get_icon("stop", color_dynamic_dark), "Stop", self)
        self.action_stop.triggered.connect(self.stop_playback)
        self.action_stop.setToolTip("Stop animation")

        self._example_registry = ExampleRegistry()
        self._example_actions: list[tuple[QtGui.QAction, ExampleEntry]] = []

        self.action_fit_view = QtGui.QAction(get_icon("fit-view", color_base), "Fit View", self)
        self.action_fit_view.setToolTip("Fit mechanism to view")

        self.action_add_rotation_driver = self._tool_action("RotDrv", CanvasMode.CREATE_ROTATION_DRIVER, get_icon("rotate-driver", color_dynamic), "Add a rotation driver to a joint (select a joint on canvas)")
        self.action_add_translation_driver = self._tool_action("LinDrv", CanvasMode.CREATE_TRANSLATION_DRIVER, get_icon("translate-driver", color_dynamic), "Add a translation driver to a slider (select a slider joint on canvas)")

        self.action_point_sensor = self._tool_action("Point", CanvasMode.CREATE_POINT_SENSOR, get_icon("sensor-point", color_sensor), "Create a point sensor (select a marker on canvas)")
        self.action_distance_sensor = self._tool_action("Dist", CanvasMode.CREATE_DISTANCE_SENSOR, get_icon("sensor-distance", color_sensor), "Create a distance sensor (select 2 markers on canvas)")
        self.action_angle_h_sensor = self._tool_action("Ang H", CanvasMode.CREATE_ANGLE_HORIZONTAL_SENSOR, get_icon("sensor-angle-h", color_sensor), "Create an angle (horizontal) sensor (select 2 markers on canvas)")
        self.action_angle_v_sensor = self._tool_action("Ang V", CanvasMode.CREATE_ANGLE_VERTICAL_SENSOR, get_icon("sensor-angle-v", color_sensor), "Create an angle (vertical) sensor (select 2 markers on canvas)")
        self.action_angle_vector_sensor = self._tool_action("Vec", CanvasMode.CREATE_ANGLE_VECTOR_SENSOR, get_icon("sensor-angle-vec", color_sensor), "Create an angle (vector) sensor (select 4 markers on canvas)")

        self.action_add_load = self._tool_action("Load", CanvasMode.CREATE_LOAD, get_icon("load-gravity", color_dynamic), "Add a point load to a marker (select a marker on canvas)")

        self.action_add_torque = QtGui.QAction(get_icon("torque", color_dynamic), "Torque", self)
        self.action_add_torque.setEnabled(False)
        self.action_add_torque.setToolTip("Add a torque load (coming soon)")

        self.action_add_linear_spring = self._tool_action("Spring", CanvasMode.CREATE_LINEAR_SPRING, get_icon("spring", color_dynamic), "Add a linear spring between two markers (click 2 markers; second click on empty canvas attaches to ground)")
        self.action_add_rotational_spring = self._tool_action("RotSpring", CanvasMode.CREATE_ROTATIONAL_SPRING, get_icon("rot-spring", color_dynamic), "Add a rotational spring at a revolute joint (click the joint)")
        self.action_add_linear_actuator = self._tool_action("Actuator", CanvasMode.CREATE_LINEAR_ACTUATOR, get_icon("actuator", color_dynamic), "Add a linear force actuator between two markers (click 2 markers; second click on empty canvas attaches to ground)")
        self.action_add_rotational_actuator = self._tool_action("RotActuator", CanvasMode.CREATE_ROTATIONAL_ACTUATOR, get_icon("rot-actuator", color_dynamic), "Add a rotational torque actuator at a revolute joint (click the joint)")

        self.action_new_plot = QtGui.QAction(get_icon("new-graph", color_sensor), "Plot", self)
        self.action_new_plot.triggered.connect(self._on_new_plot_triggered)
        self.action_new_plot.setToolTip("Create a new plot from sensor data")

        self.action_compare_runs = QtGui.QAction(get_icon("new-graph", color_sensor), "Compare", self)
        self.action_compare_runs.triggered.connect(self._open_compare_runs_dialog)
        self.action_compare_runs.setToolTip("Compare persisted runs")

        self.action_export_script = QtGui.QAction(get_icon("content-save", color_dynamic), "Export Script", self)
        self.action_export_script.triggered.connect(self.export_to_python_script)
        self.action_export_script.setToolTip("Export Exudyn standalone Python script")

        self.action_refresh = QtGui.QAction(get_icon("refresh"), "Refresh", self)
        self.action_refresh.triggered.connect(self.refresh_all)
        self.action_refresh.setToolTip("Force a full UI refresh (use if display seems out of sync)")

        self.action_show_trajectories = QtGui.QAction(get_icon("trajectories", color_sensor), "Tracks", self)
        self.action_show_trajectories.setCheckable(True)
        self.action_show_trajectories.setChecked(True)
        self.action_show_trajectories.setEnabled(False)
        self.action_show_trajectories.triggered.connect(self._on_toggle_trajectories)
        self.action_show_trajectories.setToolTip("Show/hide sensor position trajectories on canvas")

        self.action_toggle_origin = QtGui.QAction(get_icon("origin", color_base), "Axis", self)
        self.action_toggle_origin.setCheckable(True)
        self.action_toggle_origin.setChecked(True)
        self.action_toggle_origin.triggered.connect(self._on_toggle_origin)
        self.action_toggle_origin.setToolTip("Show/hide coordinate axes (X/Y) and origin")

        self.action_toggle_grid = QtGui.QAction(get_icon("grid", color_base), "Grid", self)
        self.action_toggle_grid.setCheckable(True)
        self.action_toggle_grid.setChecked(True)
        self.action_toggle_grid.triggered.connect(self._on_toggle_grid)
        self.action_toggle_grid.setToolTip("Show/hide grid")

        self.action_toggle_sensors = QtGui.QAction(get_icon("sensor-point", color_sensor), "Sensors", self)
        self.action_toggle_sensors.setCheckable(True)
        self.action_toggle_sensors.setChecked(True)
        self.action_toggle_sensors.triggered.connect(self._on_toggle_sensors)
        self.action_toggle_sensors.setToolTip("Show/hide sensor overlays")

        self.action_add_gravity = QtGui.QAction(get_icon("gravity", color_dynamic), "Gravity", self)
        self.action_add_gravity.setToolTip("Add gravity — or select it if already present")
        self.action_add_gravity.triggered.connect(self._on_add_gravity)

        self.action_preferences = QtGui.QAction(get_icon("preferences", color_base), "Preferences", self)
        self.action_preferences.triggered.connect(self._show_preferences_dialog)
        self.action_preferences.setToolTip("Open preferences dialog")

        self.action_mode_sketch = QtGui.QAction("Sketch", self)
        self.action_mode_sketch.triggered.connect(lambda: self._set_app_mode("sketch"))
        self.action_mode_sketch.setCheckable(True)

        self.action_mode_model = QtGui.QAction("Model", self)
        self.action_mode_model.triggered.connect(lambda: self._set_app_mode("model"))
        self.action_mode_model.setCheckable(True)

        self.action_mode_pose = QtGui.QAction("Pose", self)
        self.action_mode_pose.triggered.connect(lambda: self._set_app_mode("pose"))
        self.action_mode_pose.setCheckable(True)

        self.action_mode_analysis = QtGui.QAction("Analysis", self)
        self.action_mode_analysis.triggered.connect(lambda: self._set_app_mode("analysis"))
        self.action_mode_analysis.setCheckable(True)

        self.action_delete = QtGui.QAction(get_icon("delete", color_danger), "Delete", self)
        self.action_delete.setShortcut(QtGui.QKeySequence.StandardKey.Delete)
        self.action_delete.triggered.connect(self.delete_selected_entity)
        self.action_delete.setToolTip("Delete selected entity (Del)")

        self.action_select_tool = self._tool_action("Select", CanvasMode.SELECT, get_icon("select", color_base), "Select entities")
        self.action_bar_tool = self._tool_action("Bar", CanvasMode.CREATE_BAR, get_icon("bar", color_kinematic), "Create a bar (2-marker body)")
        self.action_point_mass_tool = self._tool_action("Mass", CanvasMode.CREATE_POINT_MASS, get_icon("point-mass", color_kinematic), "Create a punctual mass (1 click)")
        self.action_body_tool = self._tool_action("Body", CanvasMode.CREATE_BODY, get_icon("body", color_kinematic), "Create a body")
        self.action_add_marker_tool = self._tool_action("Marker", CanvasMode.ADD_MARKER, get_icon("marker-plus", color_kinematic), "Add a marker to the selected body")
        self.action_joint_tool = self._tool_action("Revolute", CanvasMode.CREATE_REVOLUTE, get_icon("revolute", color_kinematic), "Create a revolute joint between marker-marker, marker-ground, or marker-slider")
        self.action_rigid_joint_tool = self._tool_action("Rigid", CanvasMode.CREATE_RIGID, get_icon("rigid", color_kinematic), "Create a rigid joint between marker-marker, marker-ground, or marker-slider")
        self.action_slider_tool = self._tool_action("Slider", CanvasMode.CREATE_SLIDER, get_icon("slider", color_kinematic), "Create a slider from 2 points, or from marker + point centered on the marker")
        self.action_ground_tool = self._tool_action("Ground", CanvasMode.CONNECT_GROUND, get_icon("ground", color_kinematic), "Click a marker to connect it to ground, or empty canvas to create a free ground")
        self.action_slider_connect_tool = self._tool_action("ToSlide", CanvasMode.CONNECT_SLIDER, get_icon("slider-connect", color_kinematic), "Connect a marker to a slider")
        self.action_sketch_point_tool = self._tool_action("Point", CanvasMode.CREATE_SKETCH_POINT, get_icon("sketch-point", color_sketch), "Create a sketch point")
        self.action_sketch_line_tool = self._tool_action("Line", CanvasMode.CREATE_SKETCH_LINE_SEGMENT, get_icon("sketch-line", color_sketch), "Create a sketch line segment")
        self.action_sketch_rectangle_tool = self._tool_action("Rect", CanvasMode.CREATE_SKETCH_RECTANGLE, get_icon("sketch-rectangle", color_sketch), "Create a sketch rectangle")
        self.action_sketch_circle_tool = self._tool_action("Circle", CanvasMode.CREATE_SKETCH_CIRCLE, get_icon("sketch-circle", color_sketch), "Create a sketch circle")
        self.action_sketch_arc_tool = self._tool_action("Arc", CanvasMode.CREATE_SKETCH_ARC_CENTER, get_icon("sketch-arc", color_sketch), "Create an arc: click center, start, end")
        self.action_sketch_infinite_line_tool = self._tool_action("Axis", CanvasMode.CREATE_SKETCH_INFINITE_LINE, get_icon("sketch-infinite-line", color_sketch), "Create a sketch infinite line")
        self.action_sketch_fix_tool = self._tool_action("Fix", CanvasMode.CREATE_SKETCH_FIX, get_icon("constraint-fix", color_sketch), "Fix a sketch point in place")
        self.action_sketch_horizontal_tool = self._tool_action("Horz", CanvasMode.CREATE_SKETCH_HORIZONTAL, get_icon("constraint-horizontal", color_sketch), "Constrain two sketch points horizontally")
        self.action_sketch_vertical_tool = self._tool_action("Vert", CanvasMode.CREATE_SKETCH_VERTICAL, get_icon("constraint-vertical", color_sketch), "Constrain two sketch points vertically")
        self.action_sketch_distance_tool = self._tool_action("Dist", CanvasMode.CREATE_SKETCH_DISTANCE, get_icon("constraint-distance", color_sketch), "Constrain the distance between two sketch points")
        self.action_sketch_horizontal_distance_tool = self._tool_action("HDist", CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE, get_icon("constraint-horizontal", color_sketch), "Constrain the horizontal projected distance between two sketch points")
        self.action_sketch_vertical_distance_tool = self._tool_action("VDist", CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE, get_icon("constraint-vertical", color_sketch), "Constrain the vertical projected distance between two sketch points")
        self.action_sketch_coincident_tool = self._tool_action("Coinc", CanvasMode.CREATE_SKETCH_COINCIDENT, get_icon("constraint-coincident", color_sketch), "Constrain two sketch points to coincide")
        self.action_sketch_parallel_tool = self._tool_action("Parallel", CanvasMode.CREATE_SKETCH_PARALLEL, get_icon("parallel", color_sketch), "Constrain two line segments to be parallel (click 2 segments)")
        self.action_sketch_perpendicular_tool = self._tool_action("Perp", CanvasMode.CREATE_SKETCH_PERPENDICULAR, get_icon("perpendicular", color_sketch), "Constrain two line segments to be perpendicular (click 2 segments)")
        self.action_sketch_equal_length_tool = self._tool_action("Equal", CanvasMode.CREATE_SKETCH_EQUAL_LENGTH, get_icon("equal-length", color_sketch), "Constrain two line segments to have equal length (click 2 segments)")
        self.action_sketch_angle_tool = self._tool_action("Angle", CanvasMode.CREATE_SKETCH_ANGLE, get_icon("angle-constraint", color_sketch), "Constrain the angle at a vertex (vertex + 2 arm points)")
        self.action_sketch_midpoint_tool = self._tool_action("Mid", CanvasMode.CREATE_SKETCH_MIDPOINT, get_icon("midpoint", color_sketch), "Constrain a point to be the midpoint of a segment (midpoint + 2 ends)")
        self.action_sketch_collinear_tool = self._tool_action("Colin", CanvasMode.CREATE_SKETCH_COLLINEAR, get_icon("collinear", color_sketch), "Constrain 3 points to be collinear (click 3 points or 1 line + 1 point)")
        self.action_sketch_symmetric_tool = self._tool_action("Sym", CanvasMode.CREATE_SKETCH_SYMMETRIC, get_icon("symmetric", color_sketch), "Constrain 2 points to be symmetric about an axis (2 pts + axis line)")
        self.action_sketch_tangent_tool = self._tool_action("Tangent", CanvasMode.CREATE_SKETCH_TANGENT, get_icon("tangent", color_sketch), "Constrain tangency between a line and a circle/arc, or between two circles/arcs")
        self.action_sketch_concentric_tool = self._tool_action("Conc", CanvasMode.CREATE_SKETCH_CONCENTRIC, get_icon("concentric", color_sketch), "Constrain two circles/arcs to be concentric (click 2 curves)")
        self.action_sketch_arc_center_tool = self._tool_action("CtrArc", CanvasMode.CREATE_SKETCH_ARC_CENTER, get_icon("arc-center", color_sketch), "Create an arc: click center, start, end")

        # Keyboard shortcuts for the most-used sketch tools (CAD conventions).
        self.action_sketch_point_tool.setShortcut(QtGui.QKeySequence("P"))
        self.action_sketch_line_tool.setShortcut(QtGui.QKeySequence("L"))
        self.action_sketch_rectangle_tool.setShortcut(QtGui.QKeySequence("R"))
        self.action_sketch_circle_tool.setShortcut(QtGui.QKeySequence("C"))
        self.action_sketch_arc_tool.setShortcut(QtGui.QKeySequence("A"))
        self.action_sketch_fix_tool.setShortcut(QtGui.QKeySequence("F"))
        self.action_sketch_horizontal_tool.setShortcut(QtGui.QKeySequence("H"))
        self.action_sketch_vertical_tool.setShortcut(QtGui.QKeySequence("V"))
        self.action_sketch_distance_tool.setShortcut(QtGui.QKeySequence("D"))
        self.action_sketch_coincident_tool.setShortcut(QtGui.QKeySequence("Shift+C"))
        self.action_sketch_parallel_tool.setShortcut(QtGui.QKeySequence("Shift+P"))
        self.action_sketch_perpendicular_tool.setShortcut(QtGui.QKeySequence("Shift+R"))
        self.action_sketch_tangent_tool.setShortcut(QtGui.QKeySequence("T"))

        self.action_solve_sketch = QtGui.QAction(get_icon("sketch-solve", color_sketch), "Solve", self)
        self.action_solve_sketch.triggered.connect(self.solve_sketch)
        self.action_solve_sketch.setToolTip("Run the sketch constraint solver")
        self.action_solve_sketch.setShortcut(QtGui.QKeySequence("Ctrl+Return"))
        self.action_toggle_sketch_visible = QtGui.QAction(get_icon("sketch-visible", color_sketch), "Show Sketch", self)
        self.action_toggle_sketch_visible.setCheckable(True)
        self.action_toggle_sketch_visible.toggled.connect(self._toggle_sketch_visible)
        self.action_toggle_sketch_visible.setToolTip("Show/hide sketch")

        self.action_pose_reset = QtGui.QAction(get_icon("refresh", color_pose), "Reset Pose", self)
        self.action_pose_reset.triggered.connect(self._reset_pose)
        self.action_pose_reset.setToolTip("Reset the current pose to the reference configuration")

        self.action_pose_solve = QtGui.QAction(get_icon("sketch-solve", color_pose), "Solve Pose", self)
        self.action_pose_solve.triggered.connect(self._solve_pose)
        self.action_pose_solve.setToolTip("Solve the current pose with the active temporary constraints")

        self.action_pose_set_initial = QtGui.QAction(get_icon("content-save", color_pose), "Set as Initial", self)
        self.action_pose_set_initial.triggered.connect(self._set_current_pose_as_initial)
        self.action_pose_set_initial.setToolTip("Persist the current pose as the project's initial pose")

        self.action_pose_clear_initial = QtGui.QAction(get_icon("remove", color_pose), "Clear Initial", self)
        self.action_pose_clear_initial.triggered.connect(self._clear_initial_pose)
        self.action_pose_clear_initial.setToolTip("Remove the persisted initial pose")

        self.action_pose_prescribe_x = QtGui.QAction(get_icon("constraint-horizontal", color_pose), "Prescribe X", self)
        self.action_pose_prescribe_x.setCheckable(True)
        self.action_pose_prescribe_x.triggered.connect(lambda checked: self._prescribe_pose_coordinate("x") if checked else self._cancel_pose_pick())
        self.action_pose_prescribe_x.setToolTip("Prescribe the global X coordinate of the selected structural marker")

        self.action_pose_prescribe_y = QtGui.QAction(get_icon("constraint-vertical", color_pose), "Prescribe Y", self)
        self.action_pose_prescribe_y.setCheckable(True)
        self.action_pose_prescribe_y.triggered.connect(lambda checked: self._prescribe_pose_coordinate("y") if checked else self._cancel_pose_pick())
        self.action_pose_prescribe_y.setToolTip("Prescribe the global Y coordinate of the selected structural marker")

        self.action_pose_prescribe_horizontal = QtGui.QAction(get_icon("sensor-angle-h", color_pose), "Horiz. Angle", self)
        self.action_pose_prescribe_horizontal.setCheckable(True)
        self.action_pose_prescribe_horizontal.triggered.connect(lambda checked: self._prescribe_horizontal_angle() if checked else self._cancel_pose_pick())
        self.action_pose_prescribe_horizontal.setToolTip("Prescribe the selected body's angle to horizontal (0°)")

        self.action_pose_prescribe_vertical = QtGui.QAction(get_icon("sensor-angle-v", color_pose), "Vert. Angle", self)
        self.action_pose_prescribe_vertical.setCheckable(True)
        self.action_pose_prescribe_vertical.triggered.connect(lambda checked: self._prescribe_vertical_angle() if checked else self._cancel_pose_pick())
        self.action_pose_prescribe_vertical.setToolTip("Prescribe the selected body's angle to vertical (90°)")

        self.action_pose_prescribe_angle = QtGui.QAction(get_icon("angle-constraint", color_pose), "Rel. Angle", self)
        self.action_pose_prescribe_angle.setCheckable(True)
        self.action_pose_prescribe_angle.triggered.connect(lambda checked: self._prescribe_relative_angle() if checked else self._cancel_pose_pick())
        self.action_pose_prescribe_angle.setToolTip("Prescribe the angle between two marker pairs on different bodies")

        self.tool_group = QtGui.QActionGroup(self)
        self.tool_group.setExclusive(True)
        for action in (
            self.action_select_tool,
            self.action_bar_tool,
            self.action_point_mass_tool,
            self.action_body_tool,
            self.action_add_marker_tool,
            self.action_joint_tool,
            self.action_rigid_joint_tool,
            self.action_slider_tool,
            self.action_ground_tool,
            self.action_slider_connect_tool,
            self.action_sketch_point_tool,
            self.action_sketch_line_tool,
            self.action_sketch_rectangle_tool,
            self.action_sketch_circle_tool,
            self.action_sketch_arc_tool,
            self.action_sketch_infinite_line_tool,
            self.action_sketch_fix_tool,
            self.action_sketch_horizontal_tool,
            self.action_sketch_vertical_tool,
            self.action_sketch_distance_tool,
            self.action_sketch_horizontal_distance_tool,
            self.action_sketch_vertical_distance_tool,
            self.action_sketch_coincident_tool,
            self.action_sketch_parallel_tool,
            self.action_sketch_perpendicular_tool,
            self.action_sketch_equal_length_tool,
            self.action_sketch_angle_tool,
            self.action_sketch_midpoint_tool,
            self.action_sketch_collinear_tool,
            self.action_sketch_symmetric_tool,
            self.action_sketch_tangent_tool,
            self.action_sketch_concentric_tool,
            self.action_sketch_arc_center_tool,
            self.action_add_rotation_driver,
            self.action_add_translation_driver,
            self.action_point_sensor,
            self.action_distance_sensor,
            self.action_angle_h_sensor,
            self.action_angle_v_sensor,
            self.action_angle_vector_sensor,
            self.action_add_load,
            self.action_add_linear_spring,
            self.action_add_rotational_spring,
            self.action_add_linear_actuator,
            self.action_add_rotational_actuator,
        ):
            self.tool_group.addAction(action)
        self.action_select_tool.setChecked(True)
        self.addAction(self.action_delete)
        self.addAction(self.action_undo)
        self.addAction(self.action_redo)

    def _tool_action(self, label: str, mode: str, icon: QtGui.QIcon | None = None, tooltip: str | None = None) -> QtGui.QAction:
        action = QtGui.QAction(icon if icon is not None else label, label, self) if icon is not None else QtGui.QAction(label, self)
        action.setCheckable(True)
        if tooltip:
            action.setToolTip(tooltip)
        action.triggered.connect(lambda checked, selected_mode=mode: checked and self._set_canvas_mode(selected_mode))
        return action

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.action_new)
        file_menu.addAction(self.action_open)
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_as)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_delete)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_preferences)

        mode_menu = menubar.addMenu("&Mode")
        mode_menu.addAction(self.action_mode_sketch)
        mode_menu.addAction(self.action_mode_model)
        mode_menu.addAction(self.action_mode_pose)
        mode_menu.addAction(self.action_mode_analysis)

        examples_menu = menubar.addMenu("E&xamples")
        self._build_examples_menu(examples_menu)

    def _add_toolbar_block(self, toolbar: QtWidgets.QToolBar, actions_grid: list[list[QtGui.QAction | None]], label: str) -> None:
        """Add a labeled block widget with a grid of tool buttons."""
        container = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(container)
        outer.setContentsMargins(2, 2, 2, 0)
        outer.setSpacing(0)

        grid_widget = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(1)

        for row_idx, row in enumerate(actions_grid):
            for col_idx, action in enumerate(row):
                if action is None:
                    grid.addWidget(QtWidgets.QWidget(), row_idx, col_idx)
                    continue
                btn = QtWidgets.QToolButton()
                btn.setDefaultAction(action)
                btn.setIconSize(QtCore.QSize(22, 22))
                btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                btn.setFixedSize(44, 44)
                font = btn.font()
                font.setPointSize(6)
                btn.setFont(font)
                grid.addWidget(btn, row_idx, col_idx)

        outer.addWidget(grid_widget)

        lbl = QtWidgets.QLabel(label)
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        font = lbl.font()
        font.setPointSize(7)
        lbl.setFont(font)
        lbl.setStyleSheet("color: #888; padding-bottom: 2px;")
        outer.addWidget(lbl)

        wa = QtWidgets.QWidgetAction(toolbar)
        wa.setDefaultWidget(container)
        toolbar.addAction(wa)

    def _add_toolbar_sep(self, toolbar: QtWidgets.QToolBar) -> None:
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        sep.setFixedWidth(8)
        wa = QtWidgets.QWidgetAction(toolbar)
        wa.setDefaultWidget(sep)
        toolbar.addAction(wa)

    def _position_mode_indicator(self) -> None:
        """Anchor the mode indicator pill to the top-right of the central
        canvas stack."""
        if not hasattr(self, "_mode_selector_widget") or not hasattr(self, "_center_stack"):
            return
        pad = 12
        cw = self._center_stack.width()
        w = self._mode_selector_widget.width()
        self._mode_selector_widget.move(max(pad, cw - w - pad), pad)

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "_center_stack", None) and event.type() == QtCore.QEvent.Type.Resize:
            self._position_mode_indicator()
        return super().eventFilter(obj, event)

    def _build_mode_indicator(self) -> QtWidgets.QWidget:
        """Top-right pill showing the active mode.

        Model↔Sketch is the only user-changeable pair (the modes that
        belong to the same canvas). Pose and Analysis are entered by
        selecting a pose/analysis in the workflow tree; we present them
        as read-only indicators that light up when active.
        """
        container = QtWidgets.QWidget()
        container.setObjectName("modeIndicatorOverlay")
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        container.setStyleSheet(
            "QWidget#modeIndicatorOverlay { background: transparent; border: none; }"
        )

        def _pill(text: str, role: str, *, position: str) -> QtWidgets.QToolButton:
            btn = QtWidgets.QToolButton()
            btn.setText(text)
            btn.setCheckable(True)
            btn.setFixedSize(70, 28)
            radii = {
                "left": "border-top-left-radius: 14px; border-bottom-left-radius: 14px;",
                "right": "border-top-right-radius: 14px; border-bottom-right-radius: 14px;",
                "middle": "",
            }[position]
            btn.setStyleSheet(
                "QToolButton { border: 1px solid #ccc; %s background: #f0f0f0;"
                " color: #666; font-weight: bold; font-size: 11px; }"
                "QToolButton:checked { background: #31556f; color: white; border-color: #31556f; }"
                "QToolButton:disabled { background: #f6f6f6; color: #aaa; }"
                % radii
            )
            btn.setProperty("mode_role", role)
            return btn

        self._mode_sketch_btn = _pill("Sketch", "sketch", position="left")
        self._mode_model_btn = _pill("Model", "model", position="middle")
        self._mode_pose_btn = _pill("Pose", "pose", position="middle")
        self._mode_analysis_btn = _pill("Analysis", "analysis", position="right")

        # Model/Sketch are interactive (user toggles); Pose/Analysis are
        # informational only — they reflect what was selected in the tree.
        self._mode_sketch_btn.clicked.connect(lambda: self._set_app_mode("sketch"))
        self._mode_model_btn.clicked.connect(lambda: self._set_app_mode("model"))
        self._mode_pose_btn.setEnabled(False)
        self._mode_analysis_btn.setEnabled(False)
        # Make the disabled buttons still readable when checked.
        for btn in (self._mode_pose_btn, self._mode_analysis_btn):
            btn.setStyleSheet(
                btn.styleSheet()
                + "QToolButton:checked:disabled { background: #31556f; color: white;"
                " border-color: #31556f; }"
            )

        layout.addWidget(self._mode_sketch_btn)
        layout.addWidget(self._mode_model_btn)
        layout.addWidget(self._mode_pose_btn)
        layout.addWidget(self._mode_analysis_btn)
        return container

    def _build_common_toolbar(self) -> None:
        toolbar = self.addToolBar("Common")
        toolbar.setIconSize(QtCore.QSize(28, 28))
        toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        toolbar.setMovable(False)

        self._add_toolbar_block(toolbar, [
            [self.action_new, self.action_open, self.action_save],
            [self.action_undo, self.action_redo, self.action_save_as],
        ], "File / Edit")
        self._add_toolbar_sep(toolbar)

        self._add_toolbar_block(toolbar, [
            [self.action_select_tool, self.action_fit_view, self.action_delete],
            [self.action_toggle_origin, self.action_toggle_grid, self.action_toggle_sensors, self.action_toggle_sketch_visible],
        ], "View")

    def _build_sketch_toolbar(self) -> None:
        self._sketch_toolbar = self.addToolBar("Sketch")
        self._sketch_toolbar.setIconSize(QtCore.QSize(28, 28))
        self._sketch_toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self._sketch_toolbar.setMovable(False)
        t = self._sketch_toolbar

        self._add_toolbar_block(t, [
            [self.action_sketch_point_tool, self.action_sketch_line_tool, self.action_sketch_rectangle_tool],
            [self.action_sketch_circle_tool, self.action_sketch_infinite_line_tool, self.action_sketch_arc_tool],
        ], "Draw")
        self._add_toolbar_sep(t)

        self._add_toolbar_block(t, [
            [self.action_sketch_fix_tool, self.action_sketch_horizontal_tool, self.action_sketch_vertical_tool, self.action_sketch_coincident_tool, self.action_sketch_distance_tool, self.action_sketch_horizontal_distance_tool, self.action_sketch_vertical_distance_tool, self.action_sketch_angle_tool, self.action_sketch_midpoint_tool],
            [self.action_sketch_collinear_tool, self.action_sketch_symmetric_tool, self.action_sketch_parallel_tool, self.action_sketch_perpendicular_tool, self.action_sketch_equal_length_tool, self.action_sketch_tangent_tool, self.action_sketch_concentric_tool],
        ], "Constraints")
        self._add_toolbar_sep(t)

        self._add_toolbar_block(t, [
            [self.action_solve_sketch],
        ], "Tools")

        self._sketch_toolbar.setVisible(False)

    def _build_model_toolbar(self) -> None:
        self._model_toolbar = self.addToolBar("Model")
        self._model_toolbar.setIconSize(QtCore.QSize(28, 28))
        self._model_toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self._model_toolbar.setMovable(False)
        t = self._model_toolbar

        self._add_toolbar_block(t, [
            [self.action_point_mass_tool, self.action_bar_tool, self.action_body_tool],
            [self.action_add_marker_tool, self.action_slider_tool, self.action_ground_tool],
        ], "Elements")
        self._add_toolbar_sep(t)

        self._add_toolbar_block(t, [
            [self.action_joint_tool, self.action_rigid_joint_tool],
        ], "Joints")
        self._add_toolbar_sep(t)

        self._add_toolbar_block(t, [
            [self.action_add_rotation_driver],
            [self.action_add_translation_driver],
        ], "Drives")
        self._add_toolbar_sep(t)

        self._add_toolbar_block(t, [
            [self.action_point_sensor, self.action_distance_sensor],
            [self.action_angle_h_sensor, self.action_angle_v_sensor, self.action_angle_vector_sensor],
        ], "Sensors")
        self._add_toolbar_sep(t)

        self._add_toolbar_block(t, [
            [self.action_add_load, self.action_add_torque],
            [self.action_add_gravity],
        ], "Loads")
        self._add_toolbar_sep(t)

        self._add_toolbar_block(t, [
            [self.action_add_rotational_spring],
            [self.action_add_linear_spring],
        ], "Springs")
        self._add_toolbar_sep(t)

        self._add_toolbar_block(t, [
            [self.action_add_rotational_actuator],
            [self.action_add_linear_actuator],
        ], "Actuators")

        self._model_toolbar.setVisible(True)

    def _build_pose_toolbar(self) -> None:
        self._pose_toolbar = self.addToolBar("Pose")
        self._pose_toolbar.setIconSize(QtCore.QSize(28, 28))
        self._pose_toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self._pose_toolbar.setMovable(False)
        t = self._pose_toolbar

        self._add_toolbar_block(t, [
            [self.action_pose_reset, self.action_pose_solve],
            [self.action_pose_set_initial, self.action_pose_clear_initial],
        ], "Pose")
        self._add_toolbar_sep(t)

        self._add_toolbar_block(t, [
            [self.action_pose_prescribe_x, self.action_pose_prescribe_y, self.action_pose_prescribe_angle],
            [self.action_pose_prescribe_horizontal, self.action_pose_prescribe_vertical, None],
        ], "Constraints")

        self._pose_toolbar.setVisible(False)

    def _build_analysis_toolbar(self) -> None:
        self._analysis_toolbar = self.addToolBar("Analysis")
        self._analysis_toolbar.setIconSize(QtCore.QSize(28, 28))
        self._analysis_toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self._analysis_toolbar.setMovable(False)
        self._analysis_toolbar.setVisible(False)

    def _set_app_mode(self, mode: str) -> None:
        if mode == self._app_mode:
            return
        previous_mode = self._app_mode
        if previous_mode == "analysis" and mode != "analysis" and self._active_mode_controller is not None:
            self._active_mode_controller.on_leave()
            self._teardown_active_mode_panel()
            self._active_mode_controller = None
        self._app_mode = mode
        self.canvas.set_interaction_mode(mode)
        if previous_mode == "pose" and mode != "pose":
            self._reset_pose_ui_state()

        if mode == "sketch":
            self._mode_sketch_btn.setChecked(True)
            self._mode_model_btn.setChecked(False)
            self._mode_pose_btn.setChecked(False)
            self._mode_analysis_btn.setChecked(False)
            self.action_mode_sketch.setChecked(True)
            self.action_mode_model.setChecked(False)
            self.action_mode_pose.setChecked(False)
            self.action_mode_analysis.setChecked(False)
            self._sketch_toolbar.setVisible(True)
            self._model_toolbar.setVisible(False)
            self._pose_toolbar.setVisible(False)
            self._analysis_toolbar.setVisible(False)
            self._playback_widget.setVisible(False)
            self._set_block_editor_visible(True)
            # Ensure sketch is visible when entering sketch mode
            if self.app_service.project and self.app_service.project.sketch is not None:
                if not self.app_service.project.sketch.visible:
                    self.app_service.set_sketch_visible(True)
                    self.action_toggle_sketch_visible.setChecked(True)
            else:
                self.app_service.create_sketch()
                self.action_toggle_sketch_visible.setChecked(True)
            self.refresh_all()
        elif mode == "pose":
            self._mode_sketch_btn.setChecked(False)
            self._mode_model_btn.setChecked(False)
            self._mode_pose_btn.setChecked(True)
            self._mode_analysis_btn.setChecked(False)
            self.action_mode_sketch.setChecked(False)
            self.action_mode_model.setChecked(False)
            self.action_mode_pose.setChecked(True)
            self.action_mode_analysis.setChecked(False)
            self._sketch_toolbar.setVisible(False)
            self._model_toolbar.setVisible(False)
            self._pose_toolbar.setVisible(True)
            self._analysis_toolbar.setVisible(False)
            self._playback_widget.setVisible(False)
            self._set_block_editor_visible(False)
            self._ensure_pose_session()
            self._load_pose_constraints_from_current_pose()
            self.pose_constraints_strip.setVisible(True)
            self.pose_constraints_strip.refresh()
            self.refresh_all()
        elif mode == "analysis":
            self._mode_sketch_btn.setChecked(False)
            self._mode_model_btn.setChecked(False)
            self._mode_pose_btn.setChecked(False)
            self._mode_analysis_btn.setChecked(True)
            self.action_mode_sketch.setChecked(False)
            self.action_mode_model.setChecked(False)
            self.action_mode_pose.setChecked(False)
            self.action_mode_analysis.setChecked(True)
            self._sketch_toolbar.setVisible(False)
            self._model_toolbar.setVisible(False)
            self._pose_toolbar.setVisible(False)
            self._analysis_toolbar.setVisible(True)
            self._playback_widget.setVisible(True)
            self._set_block_editor_visible(False)
            self._center_stack.setCurrentIndex(0)
            is_exudyn = self.app_service.simulation_runner.backend_name() == "exudyn"
            self.action_export_script.setEnabled(is_exudyn)
            workspace = self.app_service.project.workspace if self.app_service.project else None
            if workspace is not None and workspace.selected_analysis_id is not None:
                analysis = next((item for item in workspace.analyses if item.id == workspace.selected_analysis_id), None)
                if analysis is not None:
                    self._set_app_mode_analysis(analysis)
            self.refresh_all()
        else:
            self._mode_sketch_btn.setChecked(False)
            self._mode_model_btn.setChecked(True)
            self._mode_pose_btn.setChecked(False)
            self._mode_analysis_btn.setChecked(False)
            self.action_mode_sketch.setChecked(False)
            self.action_mode_model.setChecked(True)
            self.action_mode_pose.setChecked(False)
            self.action_mode_analysis.setChecked(False)
            self._sketch_toolbar.setVisible(False)
            self._model_toolbar.setVisible(True)
            self._pose_toolbar.setVisible(False)
            self._analysis_toolbar.setVisible(False)
            self._playback_widget.setVisible(False)
            self._set_block_editor_visible(True)
            self._center_stack.setCurrentIndex(0)
            if self._has_simulation_frames():
                self._rewind_simulation_to_start()
            self.canvas.set_pose_readonly(False)
            self.refresh_all()

        # Sync pose_constraints_strip visibility (visible only in pose mode)
        if mode != "pose":
            self.pose_constraints_strip.setVisible(False)

        # Force select mode when switching
        self.action_select_tool.setChecked(True)
        self.canvas.set_mode(CanvasMode.SELECT)
        self._update_status_message()

    def refresh_all(self) -> None:
        project = self.app_service.display_project
        if project is None:
            return
        self.canvas.set_display_project(project)
        if self._app_mode == "pose":
            self._ensure_pose_session()
        self._update_window_title()
        self._update_timeline_controls()
        self._apply_current_frame()
        self._populate_tree(project)
        self._apply_case_delta_highlights()
        self._populate_parameters(project)
        self._populate_inspector()
        if self._app_mode in {"model", "sketch"}:
            self._refresh_block_editor()
        if hasattr(self, "pose_constraints_strip") and self._app_mode == "pose":
            self.pose_constraints_strip.refresh()
        if hasattr(self, "workflow_panel"):
            self.workflow_panel.refresh()
        self.action_toggle_sketch_visible.setChecked(project.sketch.visible if project.sketch is not None else False)
        self.action_toggle_sensors.setChecked(project.view_state.show_sensors)
        self.canvas.set_show_sensors(project.view_state.show_sensors)
        self.canvas.set_selection(self._selected_entity_id)
        if isinstance(self._selected_entity_id, str):
            self._block_editor.set_selected(self._selected_entity_id)
        self._update_interaction_state()
        self._update_mode_button_enable_rules()
        self._update_status_message()

    def _refresh_block_editor(self) -> None:
        project = self.app_service.display_project
        self._block_editor.set_project(project)
        if project is None:
            self._block_editor.set_diagram(None)
            return
        self._block_editor.set_diagram(project.model.control_graph or BlockDiagram())
        if isinstance(self._selected_entity_id, str):
            self._block_editor.set_selected(self._selected_entity_id)

    def _set_block_editor_visible(self, visible: bool) -> None:
        if self._block_editor.isVisible() == visible:
            return
        self._block_editor.setVisible(visible)
        if visible:
            self._canvas_stack.setSizes([600, 250])
            self._refresh_block_editor()
        else:
            self._canvas_stack.setSizes([850, 0])

    def _on_block_diagram_changed(self) -> None:
        project = self.app_service.project
        if project is None:
            return
        ws = project.workspace
        if ws is not None:
            from quino.services.workspace_invalidation import invalidate_on_model_change
            invalidate_on_model_change(project)
        self._mark_project_dirty()
        self._populate_tree(self.app_service.display_project)
        self._populate_inspector()

    def _on_block_validation_error(self, message: str) -> None:
        self.statusBar().showMessage(f"Block diagram: {message}", 5000)

    def _ensure_pose_session(self) -> None:
        project = self.app_service.project
        if project is None:
            return
        # If the active selection is a default WorkspacePose, do NOT create a
        # backing project Pose: the canvas should simply render the composed
        # geometry of the current scope as a read-only snapshot.
        ws = project.workspace
        if ws is not None and ws.selected_pose_id is not None:
            wp = next((p for p in ws.poses if p.id == ws.selected_pose_id), None)
            if wp is not None and wp.is_default:
                self._pose_constraints.clear()
                self.canvas.set_pose_constraints([])
                return
        if self.app_service.get_current_pose() is not None:
            # Always reload from the active pose: prescribes are per-pose
            # state and must not bleed across pose switches.
            self._load_pose_constraints_from_current_pose()
            return
        # If the project already has poses, select the simulation initial
        # (or the first one) as the editing target. Otherwise create one.
        if project.poses:
            sim_id = self.app_service.get_simulation_initial_pose_id()
            target = sim_id if sim_id is not None else project.poses[0].id
            self.app_service.set_current_pose_id(target)
        else:
            self.app_service.create_pose(name="Reference")
        self._load_pose_constraints_from_current_pose()

    def _reset_pose_ui_state(self) -> None:
        self._pose_drag_timer.stop()
        self._pending_pose_drag = None
        if self._active_prescribe_action is not None:
            self._active_prescribe_action.setChecked(False)
        self._active_prescribe_action = None
        self._pose_pick_state = None
        self._pose_constraints.clear()
        self.canvas.set_pose_constraints([])

    def _on_poses_panel_current_changed(self, pose_id: str) -> None:
        self._load_pose_constraints_from_current_pose()
        self._apply_current_frame()
        self._populate_inspector()

    def _on_poses_panel_sim_initial_changed(self, pose_id) -> None:
        self._mark_project_dirty()
        if self._app_mode == "analysis":
            self._apply_current_frame()
            self.canvas.update()

    def _on_poses_panel_mutated(self) -> None:
        self._mark_project_dirty()

    def _on_run_study_requested(self, study_id: str) -> None:
        project_dir = self._current_project_path.parent if self._current_project_path else None
        try:
            self.app_service.workspace.run_study(
                study_id,
                self.app_service.simulation_runner,
                project_dir=project_dir,
            )
            self._mark_project_dirty()
            if hasattr(self, "workflow_panel"):
                self.workflow_panel.refresh()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Run Study Failed", str(exc))

    def _on_analysis_selected(self, analysis_id: str) -> None:
        case = self.app_service.current_case()
        if case is None:
            return
        analysis = next((item for item in case.analyses if item.id == analysis_id), None)
        if analysis is None:
            return
        self._set_app_mode("analysis")
        self._set_app_mode_analysis(analysis)

    def _on_run_selected(self, run_id: str) -> None:
        case = self.app_service.current_case()
        if case is None:
            return
        run = next((r for r in case.runs if r.id == run_id), None)
        if run is None:
            return
        analysis = next((a for a in case.analyses if a.id == run.analysis_id), None)
        if analysis is not None:
            self._set_app_mode("analysis")
            self._set_app_mode_analysis(analysis)
            if self._active_mode_controller is not None:
                self._active_mode_controller.on_run_selected(run)
        if run.status == "stale":
            self.canvas.set_playback_locked(True, "Run is stale; data preserved for plots")
            self.action_play_pause.setEnabled(False)
            self.action_stop.setEnabled(False)
        else:
            self.canvas.set_playback_locked(False)
            self.action_play_pause.setEnabled(True)
            self.action_stop.setEnabled(True)

    def _on_run_action_triggered(self) -> None:
        if self._app_mode == "analysis":
            if self._active_mode_controller is not None:
                self._active_mode_controller.on_run_clicked()
                return
        self.run_simulation()

    def _set_app_mode_analysis(self, analysis) -> None:
        controller_cls = mode_controller_for(analysis.analysis_type)
        if self._active_mode_controller is None or not isinstance(self._active_mode_controller, controller_cls):
            if self._active_mode_controller is not None:
                self._active_mode_controller.on_leave()
                self._teardown_active_mode_panel()
            controller = controller_cls(self)
            controller.build_toolbar(self)
            controller.build_config_widget(self)
            controller.build_bottom_panel(self)
            self._active_mode_controller = controller
            self._mount_active_mode_panel(controller)
        self._active_mode_controller.on_enter(analysis)

    def _mount_active_mode_panel(self, controller) -> None:
        self._teardown_active_mode_panel()
        host = QtWidgets.QWidget(self._playback_widget)
        layout = QtWidgets.QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        if controller.config_widget is not None:
            layout.addWidget(controller.config_widget)
        if controller.bottom_panel is not None:
            layout.addWidget(controller.bottom_panel, stretch=1)
        self._playback_widget.layout().addWidget(host)
        self._mounted_analysis_panel = host

    def _teardown_active_mode_panel(self) -> None:
        if self._mounted_analysis_panel is not None:
            self._mounted_analysis_panel.setParent(None)
            self._mounted_analysis_panel.deleteLater()
            self._mounted_analysis_panel = None

    def _on_run_analysis_requested(self, analysis_id: str) -> None:
        try:
            errors = self._validate_analysis_pre_run(analysis_id)
            if errors:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Cannot run analysis",
                    "Fix the following before running:\n\n - " + "\n - ".join(errors),
                )
                return
            self.app_service.ensure_executor().enqueue(analysis_id)
            self._mark_project_dirty()
            if hasattr(self, "workflow_panel"):
                self.workflow_panel.refresh()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Run Analysis Failed", str(exc))

    def _validate_analysis_pre_run(self, analysis_id: str) -> list[str]:
        project = self.app_service.project
        ws = self.app_service._workspace
        case = self.app_service.current_case()
        if ws is None or case is None:
            return ["No active workspace/case."]
        analysis = next((a for a in case.analyses if a.id == analysis_id), None)
        if analysis is None:
            return [f"Analysis {analysis_id!r} not found."]
        try:
            from quino.analysis.registry import get_runner_for_type
            from quino.services.workspace_runner import _CaseAsProject
            project_view = _CaseAsProject.from_case(case, ws)
            runner = get_runner_for_type(analysis.analysis_type)
            return [
                msg for msg in runner.validate(project_view, analysis)
                if not msg.startswith("WARNING")
            ]
        except Exception as exc:
            return [f"Validation failed: {exc}"]

    def _on_executor_run_queued(self, run_id: str) -> None:
        if self._active_mode_controller is not None:
            self._active_mode_controller.on_run_queued(run_id)
        if hasattr(self, "workflow_panel"):
            self.workflow_panel.refresh()

    def _on_executor_run_started(self, run_id: str) -> None:
        case = self.app_service.current_case()
        if case is None:
            return
        run = next((r for r in case.runs if r.id == run_id), None)
        if run is None:
            return
        analysis = next((a for a in case.analyses if a.id == run.analysis_id), None)
        label = analysis.name if analysis is not None else run_id
        pending = self.app_service.executor.pending_count() if self.app_service.executor is not None else 0
        self.run_status.show_running(run_id, label, pending=pending)
        if self._active_mode_controller is not None:
            self._active_mode_controller.on_run_started(run_id)
        if hasattr(self, "workflow_panel"):
            self.workflow_panel.refresh()

    def _on_executor_run_finished(self, run_id: str, status: str) -> None:
        run = None
        analysis_label = run_id
        case = self.app_service.current_case()
        if case is not None:
            run = next((r for r in case.runs if r.id == run_id), None)
            if run is not None:
                analysis = next(
                    (a for a in case.analyses if a.id == run.analysis_id), None
                )
                if analysis is not None:
                    analysis_label = analysis.name
        if run is not None and status == "failed":
            error_text = run.error_message or "(no error message)"
            self.run_status.show_finished(status, analysis_label, error=error_text)
            QtWidgets.QMessageBox.critical(
                self,
                "Analysis run failed",
                f"Analysis '{analysis_label}' failed:\n\n{error_text}",
            )
        elif run is not None and status in {"ok", "partial"}:
            self.run_status.show_finished(status, analysis_label)
        else:
            self.run_status.show_idle()
        if self._active_mode_controller is not None:
            self._active_mode_controller.on_run_finished(run_id, status)
        if hasattr(self, "workflow_panel"):
            self.workflow_panel.refresh()

    def _on_cancel_run_requested(self, run_id: str) -> None:
        handle = self.app_service.pending_run_handles.get(run_id)
        if handle is not None:
            handle.cancel()

    def _on_case_selected(self, case_id: str) -> None:
        ws = self.app_service._workspace
        if ws is None:
            return
        ws.selected_case_id = case_id
        self._divergences_dock_widget.show_case(case_id)
        case = ws.cases.get(case_id)
        if case and case.metadata.get("divergence_warnings"):
            self._divergences_dock.show()
        self.canvas.update()

    def _on_working_context_changed(self) -> None:
        project = self.app_service.display_project
        if project is None:
            return
        self._set_app_mode("model")
        self.canvas.set_display_project(project)
        self._populate_tree(project)
        self._apply_case_delta_highlights()
        if hasattr(self, "workflow_panel"):
            self.workflow_panel.refresh()
        self._apply_current_frame()
        self.canvas.update()

    def _on_workflow_pose_selected(self, pose_id: str) -> None:
        ws = self.app_service.project.workspace if self.app_service.project else None
        if ws is None:
            return
        pose = next((p for p in ws.poses if p.id == pose_id), None)
        if pose is None:
            return
        # Default poses show the model geometry in a read-only viewport,
        # non-default poses enter the editable pose mode.
        self.app_service.set_selected_pose(pose_id)
        self.canvas.set_pose_readonly(pose.is_default)
        already_in_pose_mode = self._app_mode == "pose"
        self._set_app_mode("pose")
        if already_in_pose_mode:
            # _set_app_mode short-circuits when the mode is unchanged; we still
            # need to refresh per-pose state (prescribes + canvas) when the
            # active pose itself just changed.
            self._load_pose_constraints_from_current_pose()
            if hasattr(self, "pose_constraints_strip"):
                self.pose_constraints_strip.refresh()
            self._apply_current_frame()

    def _on_workflow_selection_changed(self, kind: str, obj_id: str) -> None:
        ws = self.app_service.project.workspace if self.app_service.project else None
        if ws is None:
            return
        if kind == "baseline":
            self.app_service.set_working_context(baseline_id=obj_id)
            self._set_app_mode("model")
        elif kind == "case":
            case = next((c for c in ws.cases if c.id == obj_id), None)
            if case is None:
                return
            self.app_service.set_working_context(case_id=obj_id, baseline_id=case.baseline_id)
            self._set_app_mode("model")
        elif kind == "pose":
            pose = next((p for p in ws.poses if p.id == obj_id), None)
            if pose is None:
                return
            if pose.case_id is not None:
                case = next((c for c in ws.cases if c.id == pose.case_id), None)
                if case is not None:
                    self.app_service.set_working_context(case_id=case.id, baseline_id=case.baseline_id)
            elif pose.baseline_id is not None:
                self.app_service.set_working_context(baseline_id=pose.baseline_id)
            self.app_service.set_selected_pose(obj_id)
            self.canvas.set_pose_readonly(pose.is_default)
            already_in_pose_mode = self._app_mode == "pose"
            self._set_app_mode("pose")
            if already_in_pose_mode:
                self._load_pose_constraints_from_current_pose()
                if hasattr(self, "pose_constraints_strip"):
                    self.pose_constraints_strip.refresh()
                self._apply_current_frame()
        elif kind == "analysis":
            analysis = next((a for a in ws.analyses if a.id == obj_id), None)
            if analysis is None:
                return
            if analysis.case_id is not None:
                case = next((c for c in ws.cases if c.id == analysis.case_id), None)
                if case is not None:
                    self.app_service.set_working_context(case_id=case.id, baseline_id=case.baseline_id)
            elif analysis.baseline_id is not None:
                self.app_service.set_working_context(baseline_id=analysis.baseline_id)
            self.app_service.set_selected_analysis(obj_id)
            self._set_app_mode("analysis")
        self.refresh_all()

    def _update_window_title(self) -> None:
        project = self.app_service.project
        project_name = project.name if project is not None else "No Project"
        dirty_marker = "*" if self._project_dirty else ""
        path_hint = f" - {self._current_project_path.name}" if self._current_project_path else ""
        self.setWindowTitle(f"QUINO - {project_name}{dirty_marker}{path_hint}")

    def _mark_project_dirty(self) -> None:
        if not self._project_dirty:
            self._project_dirty = True
            self._update_window_title()

    def _mark_project_clean(self) -> None:
        if self._project_dirty:
            self._project_dirty = False
        self._update_window_title()

    def _build_examples_menu(self, menu: QtWidgets.QMenu) -> None:
        icon_map = {
            "Four Bar": "four-bar",
            "Slider Crank": "slider-crank",
        }
        for entry in self._example_registry.list_examples():
            icon_name = icon_map.get(entry.name, "example")
            action = QtGui.QAction(get_icon(icon_name, "#4a7ba7"), f"Load {entry.name}", self)
            action.setToolTip(entry.description)
            action.triggered.connect(lambda _checked=False, e=entry: self._load_example(e))
            menu.addAction(action)
            self._example_actions.append((action, entry))

    def load_four_bar_example(self) -> None:
        """Convenience wrapper for tests."""
        for entry in self._example_registry.list_examples():
            if entry.name == "Four Bar":
                self._load_example(entry)
                return

    def load_slider_crank_example(self) -> None:
        """Convenience wrapper for tests."""
        for entry in self._example_registry.list_examples():
            if entry.name == "Slider Crank":
                self._load_example(entry)
                return

    def _load_example(self, entry: ExampleEntry) -> None:
        if not self._confirm_save_if_dirty():
            return
        self._example_registry.load(self.app_service, entry)
        self._current_project_path = None
        self._mark_project_dirty()
        project = self.app_service.project
        if project is not None and project.model.bodies:
            self._selected_entity_id = project.model.bodies[0].id
        else:
            self._selected_entity_id = None
        self._clear_simulation_state()
        self._append_message(f"Loaded example: {entry.name}")
        self.canvas.fit_view()
        self.refresh_all()

    def validate_model(self) -> None:
        report = self.app_service.validate_model()
        lines = ["Validation report:"]
        if not report.messages:
            lines.append("  no issues found")
        for message in report.messages:
            lines.append(f"  [{message.level}] {message.code}: {message.message}")
        self.validation_view.setPlainText("\n".join(lines))
        for line in lines:
            self._append_message(line)
        self.refresh_all()

    def export_to_python_script(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            exporter = getattr(self._active_mode_controller, "export_to_python_script", None)
            if exporter is not None:
                exporter()
                return
        if self.app_service.simulation_runner.backend_name() != "exudyn":
            QtWidgets.QMessageBox.information(
                self,
                "Export not available",
                "Script export is only supported for the Exudyn solver backend.",
            )
            return
        default_dir = Path("logs")
        default_dir.mkdir(exist_ok=True)
        default_path = str(default_dir / "exudyn_simulation.py")
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Exudyn Script",
            default_path,
            "Python Files (*.py)",
        )
        if not file_path:
            return
        try:
            script = self.app_service.export_exudyn_script(
                duration=float(self.duration_spin.value()),
                steps=int(self.steps_spin.value()),
            )
            Path(file_path).write_text(script, encoding="utf-8")
            self._append_message(f"Exported Exudyn script to {file_path}")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "Export failed",
                f"Failed to export script:\n\n{exc}",
            )

    def run_simulation(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            runner = getattr(self._active_mode_controller, "run_simulation", None)
            if runner is not None:
                runner()
                return
        self._playback_timer.stop()
        self._sync_play_pause_icon()
        result = self.app_service.run_kinematic_simulation(
            duration=float(self.duration_spin.value()),
            steps=int(self.steps_spin.value()),
        )
        self._last_simulation_result = result
        self._current_frame_index = 0
        self.validation_view.setPlainText(
            "\n".join(
                ["Simulation diagnostics:"]
                + [f"  {warning}" for warning in result.warnings]
                + [f"  {message}" for message in result.messages]
                + ([f"  ERROR: {result.error}"] if result.error else [])
            ).strip()
        )
        self._append_message(f"Simulation backend: {result.backend}")
        for warning in result.warnings:
            self._append_message(f"  warning: {warning}")
        for message in result.messages:
            self._append_message(f"  {message}")
        self._update_timeline_controls()
        self._apply_current_frame()
        self._update_trajectories()
        self.refresh_all()
        if result.error:
            self._append_message(f"  ERROR: {result.error}")
            detail = ""
            icon = QtWidgets.QMessageBox.Icon.Critical
            if result.frames:
                detail = f"\n\nPartial trajectory available: {len(result.frames)} frame(s)."
                icon = QtWidgets.QMessageBox.Icon.Warning
            message_box = QtWidgets.QMessageBox(self)
            message_box.setIcon(icon)
            message_box.setWindowTitle("Analysis Error")
            message_box.setText(f"Analysis failed:\n\n{result.error}{detail}")
            message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
            message_box.exec()

    def toggle_playback(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "toggle_playback", None)
            if handler is not None:
                handler()
                return
        if self._last_simulation_result is None or not self._last_simulation_result.frames:
            return
        if self._playback_timer.isActive():
            self._playback_timer.stop()
            self._sync_play_pause_icon()
            self._update_interaction_state()
            return
        self._playback_timer.start(40)
        self._sync_play_pause_icon()
        self._update_interaction_state()

    def stop_playback(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "stop_playback", None)
            if handler is not None:
                handler()
                return
        self._playback_timer.stop()
        self._current_frame_index = 0
        self._apply_current_frame()
        self._update_timeline_controls()
        self._sync_play_pause_icon()
        self._update_interaction_state()

    def _sync_play_pause_icon(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "sync_play_pause_icon", None)
            if handler is not None:
                handler()
                return
        if self._playback_timer.isActive():
            self.action_play_pause.setIcon(self._icon_pause)
            self.action_play_pause.setText("Pause")
        else:
            self.action_play_pause.setIcon(self._icon_play)
            self.action_play_pause.setText("Play")

    def create_plot_window(self) -> None:
        win = PlotWindow(app_service=self.app_service, parent=self)
        win.window_closed.connect(lambda: self._plot_windows.remove(win) if win in self._plot_windows else None)
        win.show()
        win.prompt_import_from_simulation()
        self._plot_windows.append(win)

    def _on_new_plot_triggered(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            analysis = getattr(self._active_mode_controller, "_current_analysis", None)
            if analysis is not None:
                self._open_plot_editor_for_analysis(analysis)
                return
        self.create_plot_window()

    def _open_plot_editor_for_analysis(self, analysis) -> None:
        from quino.gui.dialogs.plot_editor_dialog import PlotEditorDialog

        project = self.app_service.display_project
        if project is None:
            return
        dialog = PlotEditorDialog(
            analysis_type=analysis.analysis_type,
            project=project,
            sweeps=getattr(analysis.config, "sweeps", []),
            parent=self,
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted or dialog.result_plot is None:
            return
        analysis.config.plots.append(dialog.result_plot)
        self._render_plot_for_analysis(analysis, dialog.result_plot)

    def _render_plot_for_analysis(self, analysis, plot_def) -> None:
        case = self.app_service.current_case()
        if case is None:
            return
        runs = [
            run for run in case.runs
            if run.analysis_id == analysis.id and run.result_ref is not None and run.status in {"ok", "partial"}
        ]
        if not runs:
            self._append_message("No persisted runs available for this analysis yet.")
            return
        artifacts = [(run.id, load_artifact(self.app_service.current_project_dir, run)) for run in runs[-1:]]
        figure = render_plot(plot_def, artifacts)
        figure.show()

    def _open_compare_runs_dialog(self) -> None:
        from quino.gui.dialogs.run_comparison_dialog import RunComparisonDialog

        dialog = RunComparisonDialog(self.app_service, parent=self)
        dialog.exec()

    def delete_selected_entity(self) -> None:
        if not self._editing_allowed():
            self._append_message("Editing is only available at t=0")
            return
        if not self._selected_entity_id:
            return
        if not self._prepare_for_model_edit():
            return
        entity_id = self._selected_entity_id
        if isinstance(entity_id, tuple):
            kind = entity_id[0]
            try:
                if kind == "block_connection" and len(entity_id) == 5:
                    _, src_instance, src_port, dst_instance, dst_port = entity_id
                    self.app_service.remove_connection(
                        src_instance=src_instance,
                        src_port=src_port,
                        dst_instance=dst_instance,
                        dst_port=dst_port,
                    )
                    self._append_message("Deleted selected block connection")
                    self._selected_entity_id = None
                    self._mark_project_dirty()
                elif kind == "block_param":
                    return
            except Exception as exc:  # pragma: no cover - UI feedback
                self._append_message(f"Delete failed: {exc}")
            self.refresh_all()
            return
        project = self.app_service.display_project
        if (
            project is not None
            and project.model.control_graph is not None
            and entity_id in project.model.control_graph.instances
        ):
            try:
                self.app_service.remove_block(entity_id)
                self._append_message("Deleted selected block")
                self._selected_entity_id = None
                self._mark_project_dirty()
            except Exception as exc:  # pragma: no cover - UI feedback
                self._append_message(f"Delete failed: {exc}")
            self.refresh_all()
            return
        consequence = self.app_service.get_marker_deletion_consequence(entity_id)
        result = "accept"
        if consequence == "to_bar":
            result = self._confirm_marker_deletion_to_bar(entity_id)
            if result == "cancel":
                return
            if result == "delete_body":
                body = self.app_service.get_body_by_marker(entity_id)
                entity_id = body.id if body else entity_id
        elif consequence == "to_point_mass":
            result = self._confirm_marker_deletion_to_point_mass(entity_id)
            if result == "cancel":
                return
            if result == "delete_body":
                body = self.app_service.get_body_by_marker(entity_id)
                entity_id = body.id if body else entity_id
        try:
            if consequence == "to_bar" and result == "accept":
                self.app_service.delete_structural_marker_convert_to_bar(entity_id)
            else:
                self.app_service.delete_entity(entity_id)
            self._append_message("Deleted selected entity")
            self._selected_entity_id = None
            self._mark_project_dirty()
        except Exception as exc:  # pragma: no cover - UI feedback
            self._append_message(f"Delete failed: {exc}")
        self.refresh_all()

    def _confirm_marker_deletion_to_bar(self, marker_id: str) -> str:
        body = self.app_service.get_body_by_marker(marker_id)
        body_name = body.name if body else "body"
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("Convert to Bar")
        msg.setText(
            f'Removing this marker will convert "{body_name}" into a Bar.\n'
            "The center of mass will be placed at the midpoint of the remaining two markers."
        )
        btn_accept = msg.addButton("Convert to Bar", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        btn_delete = msg.addButton("Delete Body", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is btn_accept:
            return "accept"
        if clicked is btn_delete:
            return "delete_body"
        return "cancel"

    def _confirm_marker_deletion_to_point_mass(self, marker_id: str) -> str:
        body = self.app_service.get_body_by_marker(marker_id)
        body_name = body.name if body else "bar"
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("Convert to Punctual Mass")
        msg.setText(
            f'Removing this marker will convert "{body_name}" into a Punctual Mass.\n'
            "The center of mass will be locked to the remaining marker."
        )
        btn_accept = msg.addButton("Convert to Punctual Mass", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        btn_delete = msg.addButton("Delete Bar", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is btn_accept:
            return "accept"
        if clicked is btn_delete:
            return "delete_body"
        return "cancel"

    def _advance_playback(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "advance_playback", None)
            if handler is not None:
                handler()
                return
        if self._last_simulation_result is None or not self._last_simulation_result.frames:
            self.stop_playback()
            return
        n_frames = len(self._last_simulation_result.frames)
        if self._current_frame_index >= n_frames - 1:
            self.stop_playback()
            return
        duration = self.duration_spin.value()
        steps = self.steps_spin.value()
        sim_dt = duration / steps if steps > 0 else 0.04
        playback_speed = self.playback_speed_spin.value()
        # Timer fires every 40 ms (~25 FPS); compute how many sim frames to skip
        step_jump = max(1, round(playback_speed * 0.04 / sim_dt))
        self._current_frame_index = min(self._current_frame_index + step_jump, n_frames - 1)
        self._apply_current_frame()
        self._update_timeline_controls()

    def _on_timeline_changed(self, value: int) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "on_timeline_changed", None)
            if handler is not None:
                handler(value)
                return
        self._current_frame_index = value
        self._apply_current_frame()
        self._update_timeline_controls()

    def _on_duration_changed(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "on_duration_changed", None)
            if handler is not None:
                handler()
                return
        if self._suspend_simulation_config_updates:
            return
        duration = self.duration_spin.value()
        dt = self.dt_spin.value()
        if dt > 0:
            steps = max(1, round(duration / dt))
            self._suspend_simulation_config_updates = True
            try:
                self.steps_spin.setValue(steps)
                actual_dt = duration / steps
                self.dt_spin.setValue(actual_dt)
            finally:
                self._suspend_simulation_config_updates = False
        self._update_simulation_spin_steps()
        self._discard_simulation_for_parameter_change("Simulation discarded because duration changed")

    def _on_steps_changed(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "on_steps_changed", None)
            if handler is not None:
                handler()
                return
        if self._suspend_simulation_config_updates:
            return
        duration = self.duration_spin.value()
        steps = self.steps_spin.value()
        if steps > 0:
            dt = duration / steps
            self._suspend_simulation_config_updates = True
            try:
                self.dt_spin.setValue(dt)
            finally:
                self._suspend_simulation_config_updates = False
        self._update_simulation_spin_steps()
        self._discard_simulation_for_parameter_change("Simulation discarded because frame count changed")

    def _on_dt_changed(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "on_dt_changed", None)
            if handler is not None:
                handler()
                return
        if self._suspend_simulation_config_updates:
            return
        duration = self.duration_spin.value()
        dt = self.dt_spin.value()
        if dt > 0:
            steps = max(1, round(duration / dt))
            self._suspend_simulation_config_updates = True
            try:
                self.steps_spin.setValue(steps)
                actual_dt = duration / steps
                self.dt_spin.setValue(actual_dt)
            finally:
                self._suspend_simulation_config_updates = False
        self._update_simulation_spin_steps()
        self._discard_simulation_for_parameter_change("Simulation discarded because delta t changed")

    def _on_playback_speed_changed(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "on_playback_speed_changed", None)
            if handler is not None:
                handler()
                return
        self._update_simulation_spin_steps()

    def _update_simulation_spin_steps(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "update_simulation_spin_steps", None)
            if handler is not None:
                handler()
                return
        self.steps_spin.setSingleStep(self._adaptive_frame_step(self.steps_spin.value()))
        self.dt_spin.setSingleStep(self._adaptive_fractional_step(self.dt_spin.value()))
        self.playback_speed_spin.setSingleStep(self._adaptive_fractional_step(self.playback_speed_spin.value()))

    def _adaptive_frame_step(self, value: int) -> int:
        return max(1, value // 10)

    def _adaptive_fractional_step(self, value: float) -> float:
        magnitude = abs(value)
        if magnitude <= 0.0:
            return 0.0005
        exponent = math.floor(math.log10(magnitude))
        return 0.5 * (10 ** exponent)

    def _discard_simulation_for_parameter_change(self, message: str) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "discard_simulation_for_parameter_change", None)
            if handler is not None:
                handler(message)
                return
        if self._has_simulation_frames():
            self._clear_simulation_state(message)

    def _rewind_simulation_to_start(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "rewind_simulation_to_start", None)
            if handler is not None:
                handler()
                return
        self._playback_timer.stop()
        self._sync_play_pause_icon()
        self._current_frame_index = 0
        self._apply_current_frame()
        self._update_timeline_controls()

    def _apply_current_frame(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "apply_current_frame", None)
            if handler is not None:
                handler()
                return
        frame = None
        time_value = 0.0
        if self._app_mode == "pose":
            frame = pose_to_state_overlay(self.app_service.get_current_pose())
        elif self._app_mode == "analysis":
            if self._last_simulation_result is not None and self._last_simulation_result.frames:
                index = max(0, min(self._current_frame_index, len(self._last_simulation_result.frames) - 1))
                frame = self._last_simulation_result.frames[index]
                time_value = self._last_simulation_result.time[index] if index < len(self._last_simulation_result.time) else 0.0
            else:
                initial_pose = self.app_service.get_simulation_initial_pose()
                if initial_pose is not None:
                    frame = pose_to_state_overlay(initial_pose)
        elif self._last_simulation_result is not None and self._last_simulation_result.frames:
            index = 0 if self._app_mode == "model" else max(0, min(self._current_frame_index, len(self._last_simulation_result.frames) - 1))
            frame = self._last_simulation_result.frames[index]
            time_value = self._last_simulation_result.time[index] if index < len(self._last_simulation_result.time) else 0.0
        self._last_simulation_state = frame
        self.canvas.set_state_overlay(frame)
        self.canvas.set_simulation_time(time_value)
        if self.app_service.project is not None:
            self._populate_canvas_summary(self.app_service.project)
        self._update_interaction_state()

    def _update_timeline_controls(self) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "update_timeline_controls", None)
            if handler is not None:
                handler()
                return
        result = self._last_simulation_result
        if result is None or not result.frames:
            self.timeline_slider.blockSignals(True)
            self.timeline_slider.setRange(0, 0)
            self.timeline_slider.setValue(0)
            self.timeline_slider.blockSignals(False)
            self.timeline_label.setText("0 / 0")
            return
        max_index = len(result.frames) - 1
        current = max(0, min(self._current_frame_index, max_index))
        self.timeline_slider.blockSignals(True)
        self.timeline_slider.setRange(0, max_index)
        self.timeline_slider.setValue(current)
        self.timeline_slider.blockSignals(False)
        current_time = result.time[current] if current < len(result.time) else float(current)
        self.timeline_label.setText(f"{current + 1} / {len(result.frames)}  t={current_time:.3f}s")

    def _has_simulation_frames(self) -> bool:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "has_simulation_frames", None)
            if handler is not None:
                return bool(handler())
        return self._last_simulation_result is not None and bool(self._last_simulation_result.frames)

    def _clear_simulation_state(self, message: str | None = None) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "clear_simulation_state", None)
            if handler is not None:
                handler(message)
                return
        self._playback_timer.stop()
        self._sync_play_pause_icon()
        self._last_simulation_result = None
        self._last_simulation_state = None
        self._current_frame_index = 0
        self._apply_current_frame()
        self.canvas.set_trajectories([])
        self.action_show_trajectories.setEnabled(False)
        self._update_timeline_controls()
        self._update_interaction_state()
        if self.app_service.project is not None:
            self.app_service.project.reaction_outputs.clear()
            self.app_service.project.sensor_outputs.clear()
        if message:
            self._append_message(message)

    def _on_toggle_trajectories(self) -> None:
        self.canvas.set_show_trajectories(self.action_show_trajectories.isChecked())

    def _on_toggle_origin(self) -> None:
        show = self.action_toggle_origin.isChecked()
        self.canvas.set_show_origin(show)
        self.canvas.set_show_axes(show)

    def _on_toggle_grid(self) -> None:
        self.canvas.set_show_grid(self.action_toggle_grid.isChecked())

    def _on_toggle_sensors(self) -> None:
        show = self.action_toggle_sensors.isChecked()
        self.canvas.set_show_sensors(show)
        if self.app_service.project is not None:
            self.app_service.project.view_state.show_sensors = show

    def _on_add_gravity(self) -> None:
        project = self.app_service.project
        if project is None:
            return
        if project.model.gravity is not None:
            self._selected_entity_id = "__gravity__"
            self.refresh_all()
            return
        if not self._editing_allowed():
            return
        if not self._prepare_for_model_edit():
            return
        self.app_service.add_gravity()
        self._selected_entity_id = "__gravity__"
        self._mark_project_dirty()
        self.refresh_all()

    def _show_preferences_dialog(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Preferences")
        dialog.setMinimumWidth(320)
        layout = QtWidgets.QFormLayout(dialog)

        origin_checkbox = QtWidgets.QCheckBox("Show coordinate axes & origin")
        origin_checkbox.setChecked(self.canvas.show_axes())
        layout.addRow(origin_checkbox)

        grid_checkbox = QtWidgets.QCheckBox("Show grid")
        grid_checkbox.setChecked(self.canvas.show_grid())
        layout.addRow(grid_checkbox)

        color_layout = QtWidgets.QHBoxLayout()
        color_button = QtWidgets.QPushButton("Choose…")
        color_preview = QtWidgets.QLabel(self.canvas.background_color())
        color_preview.setStyleSheet(
            f"background-color: {self.canvas.background_color()}; border: 1px solid #888; min-width: 60px;"
        )
        current_color = self.canvas.background_color()

        def _pick_color():
            nonlocal current_color
            color = QtWidgets.QColorDialog.getColor(
                QtGui.QColor(current_color), dialog, "Canvas Background Color"
            )
            if color.isValid():
                current_color = color.name()
                color_preview.setText(current_color)
                color_preview.setStyleSheet(
                    f"background-color: {current_color}; border: 1px solid #888; min-width: 60px;"
                )

        color_button.clicked.connect(_pick_color)
        color_layout.addWidget(color_preview)
        color_layout.addWidget(color_button)
        color_layout.addStretch()
        layout.addRow("Background color:", color_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            show_axes = origin_checkbox.isChecked()
            self.canvas.set_show_origin(show_axes)
            self.canvas.set_show_axes(show_axes)
            self.canvas.set_show_grid(grid_checkbox.isChecked())
            self.canvas.set_background_color(current_color)
            self.action_toggle_origin.setChecked(show_axes)
            self.action_toggle_grid.setChecked(self.canvas.show_grid())

    def _update_trajectories(self, *, result: SimulationResult | None = None) -> None:
        if self._app_mode == "analysis" and self._active_mode_controller is not None:
            handler = getattr(self._active_mode_controller, "update_trajectories", None)
            if handler is not None:
                handler(result=result)
                return
        """Refresh canvas trajectories.

        When *result* is given, we derive trajectories from its frames so
        the canvas shows the points produced by THAT specific run (used
        when the user selects an analysis in the tree). When *result* is
        None we fall back to project.sensor_outputs, which holds the
        most recent live simulation.
        """
        project = self.app_service.project
        if project is None:
            return
        trajectories: list[list[tuple[float, float]]] = []
        if result is not None and result.frames:
            # Build per-sensor trajectories straight from the frame stream.
            for sensor in project.model.sensors:
                if sensor.type.value != "point" or not sensor.marker_ids:
                    continue
                marker_id = sensor.marker_ids[0]
                key_x = f"marker:{marker_id}:x"
                key_y = f"marker:{marker_id}:y"
                pts: list[tuple[float, float]] = []
                for frame in result.frames:
                    if key_x in frame and key_y in frame:
                        pts.append((float(frame[key_x]), float(frame[key_y])))
                if len(pts) >= 2:
                    trajectories.append(pts)
        if not trajectories:
            for sensor in project.model.sensors:
                if sensor.type.value != "point":
                    continue
                output = project.sensor_outputs.get(sensor.id)
                if output is None or not output.data:
                    continue
                # Columns: time, x, y, vx, vy, v, ax, ay, a  →  x=col1, y=col2
                pts = [(row[0], row[1]) for row in output.data]
                if len(pts) >= 2:
                    trajectories.append(pts)
        self.canvas.set_trajectories(trajectories)
        self.action_show_trajectories.setEnabled(bool(trajectories))
        if trajectories:
            self.action_show_trajectories.setChecked(True)
            self.canvas.set_show_trajectories(True)

    def _check_structural_edit_allowed(self) -> bool:
        """Return True if structural model edits are allowed.

        When a case is active, edits are redirected into case structural diffs
        (added_entities / removed_entity_ids) instead of modifying the baseline.
        """
        project = self.app_service.project
        if project is None:
            return True
        ws = project.workspace
        if ws is None or ws.active_case_id is None:
            return True
        # Structural edits in a case are now captured as diffs — no warning needed.
        return True

    def _prepare_for_model_edit(self) -> bool:
        if self._playback_timer.isActive():
            self._append_message("Editing is only available at t=0")
            return False
        if not self._check_structural_edit_allowed():
            return False
        if not self._has_simulation_frames():
            return True
        self._playback_timer.stop()
        self._sync_play_pause_icon()
        answer = QtWidgets.QMessageBox.warning(
            self,
            "Discard Simulation?",
            (
                "The model has an active simulation result.\n\n"
                "If you modify the model, the current simulation will be removed."
            ),
            QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Ok:
            self._update_interaction_state()
            return False
        self._clear_simulation_state("Simulation discarded because the model was edited")
        return True

    def _confirm_run_invalidation_dialog(self) -> bool:
        """Installed as `ServiceContext.confirm_run_invalidation`. Command-
        services call this just before a non-cosmetic edit flips persisted
        runs to 'stale'. Returns True to proceed, False to abort the edit."""
        case = self.app_service.current_case()
        if case is None:
            return True
        ctx = self.app_service._service_context
        analysis_ids = ctx._affected_analysis_ids_for_active_scope()
        affected_runs = [
            r for r in case.runs
            if r.analysis_id in analysis_ids and r.status in {"ok", "partial"}
        ]
        if not affected_runs:
            return True
        n = len(affected_runs)
        plural = "run" if n == 1 else "runs"
        answer = QtWidgets.QMessageBox.warning(
            self,
            "Mark runs as stale?",
            (
                f"This edit will mark {n} persisted {plural} as stale.\n\n"
                "Their data is preserved on disk (plots and metrics keep working) "
                "but the canvas playback will be locked until you re-run the "
                "affected analyses."
            ),
            QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Ok,
        )
        return answer == QtWidgets.QMessageBox.StandardButton.Ok

    def _prepare_for_sketch_edit(self) -> bool:
        if self._playback_timer.isActive():
            self._append_message("Editing is only available at t=0")
            return False
        return True

    def _new_project(self) -> None:
        if not self._confirm_save_if_dirty():
            return
        name, accepted = QtWidgets.QInputDialog.getText(self, "New Project", "Project name:", text="Untitled")
        if not accepted or not name:
            return
        self.app_service.new_project(name)
        self._current_project_path = None
        self._mark_project_clean()
        self._selected_entity_id = None
        self._reset_pose_ui_state()
        self._clear_simulation_state()
        self.messages.clear()
        self.validation_view.clear()
        self.canvas.fit_view()
        self.refresh_all()

    def _open_project(self) -> None:
        if not self._confirm_save_if_dirty():
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Project",
            str(Path.cwd()),
            "QUINO Project (*.quino.json);;JSON Files (*.json)",
        )
        if not path:
            return
        self.app_service.load_project(path)
        self._current_project_path = Path(path)
        self._mark_project_clean()
        self._selected_entity_id = None
        self._reset_pose_ui_state()
        self._clear_simulation_state()
        self.messages.clear()
        self.validation_view.clear()
        self._append_message(f"Opened project: {path}")
        self.canvas._view_scale = None
        self.refresh_all()

    def _save_project(self) -> bool:
        if self._current_project_path is None:
            return self._save_project_as()
        return self._save_project_to_path(self._current_project_path)

    def _save_project_as(self) -> bool:
        project = self.app_service.project
        if project is None:
            return False
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            str(self._default_save_path()),
            "QUINO Project (*.quino.json);;JSON Files (*.json)",
        )
        if not path:
            return False
        return self._save_project_to_path(Path(path))

    def _save_project_to_path(self, path: Path) -> bool:
        project = self.app_service.project
        if project is None:
            return False
        final_path = self._normalize_project_path(path)
        self.app_service.save_project(str(final_path))
        self._current_project_path = final_path
        self._mark_project_clean()
        self._append_message(f"Saved project: {final_path}")
        return True

    def _default_save_path(self) -> Path:
        if self._current_project_path is not None:
            return self._current_project_path
        project = self.app_service.project
        suggested = "Untitled.quino.json"
        if project is not None:
            suggested = f"{project.name.replace(' ', '_')}.quino.json"
        return Path.cwd() / suggested

    def _normalize_project_path(self, path: Path) -> Path:
        if path.suffix:
            return path
        return path.with_suffix(".quino.json")

    def _confirm_save_if_dirty(self) -> bool:
        if not self._project_dirty:
            return True
        answer = QtWidgets.QMessageBox.warning(
            self,
            "Unsaved Changes",
            "The current project has unsaved changes.\n\nDo you want to save them before continuing?",
            (
                QtWidgets.QMessageBox.StandardButton.Save
                | QtWidgets.QMessageBox.StandardButton.Discard
                | QtWidgets.QMessageBox.StandardButton.Cancel
            ),
            QtWidgets.QMessageBox.StandardButton.Save,
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Cancel:
            return False
        if answer == QtWidgets.QMessageBox.StandardButton.Discard:
            return True
        if answer == QtWidgets.QMessageBox.StandardButton.Save:
            return self._save_project()
        return False

    # --- icon name per entity kind ---
    _KIND_ICON: dict[str, str] = {
        "bar": "bar", "body": "body",
        "ground": "ground",
        "reaction": "sensor-point",
        "structural": "marker", "com": "marker",
        "slider": "slider",
        "revolute": "revolute", "rigid": "rigid",
        "rotation": "rotate-driver", "translation": "translate-driver",
        "point": "sensor-point", "distance": "sensor-distance",
        "angle_horizontal": "sensor-angle-h", "angle_vertical": "sensor-angle-v",
        "angle_vector": "sensor-angle-vec",
        "constraint_fix": "constraint-fix",
        "constraint_horizontal": "constraint-horizontal",
        "constraint_vertical": "constraint-vertical",
        "constraint_distance": "constraint-distance",
        "constraint_coincident": "constraint-coincident",
        "fix": "constraint-fix", "horizontal": "constraint-horizontal",
        "vertical": "constraint-vertical", "coincident": "constraint-coincident",
        "line_segment": "sketch-line",
        "circle": "sketch-circle",
        "arc": "sketch-arc",
        "infinite_line": "sketch-infinite-line",
        "gravity": "load-gravity",
        "load": "load-gravity",
        "linear_spring": "spring", "rotational_spring": "rot-spring",
        "linear_actuator": "actuator", "rotational_actuator": "rot-actuator",
    }
    _SECTION_ICON: dict[str, str] = {
        "Bodies": "section-bodies",
        "Sliders": "section-sliders",
        "Joints": "section-joints",
        "Drivers": "section-drivers",
        "Sensors": "section-sensors",
        "Reactions": "section-reactions",
        "Sketch": "section-sketch",
        "Constraints": "constraint-distance",
        "Loads": "section-loads",
        "Springs": "section-springs",
        "Block Diagram": "workspace-blocks",
    }
    _SECTION_COLOR: dict[str, str] = {
        "Bodies": "#2f6f9f", "Sliders": "#2f6f9f", "Joints": "#2f6f9f",
        "Drivers": "#c7781d", "Sensors": "#c7781d",
        "Reactions": "#c7781d",
        "Sketch": "#7a7f87",
        "Loads": "#7a5a8f",
        "Springs": "#2a9d8f",
    }

    def _populate_tree(self, project) -> None:
        self.tree.blockSignals(True)
        self._expanded_tree_keys = self._collect_expanded_tree_keys()
        self.tree.clear()
        self._tree_items.clear()

        def _root(label: str, count: int) -> QtWidgets.QTreeWidgetItem:
            item = QtWidgets.QTreeWidgetItem([f"{label}  ({count})", ""])
            icon_name = self._SECTION_ICON.get(label, "")
            if icon_name:
                item.setIcon(0, get_icon(icon_name, size=18))
            color = QtGui.QColor(self._SECTION_COLOR.get(label, "#3d3d3d"))
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            item.setForeground(0, QtGui.QBrush(color))
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
            return item

        visible_joints = [joint for joint in project.model.joints if not joint.metadata.values.get("internal_ground_anchor")]
        bodies_root = _root("Bodies", len(project.model.bodies))
        sliders_root = _root("Sliders", len(project.model.sliders))
        joints_root = _root("Joints", len(visible_joints))
        drivers_root = _root("Drivers", len(project.model.drivers))
        sensors_root = _root("Sensors", len(project.model.sensors))
        loads_count = len(project.model.loads) + (1 if project.model.gravity is not None else 0)
        loads_root = _root("Loads", loads_count)
        springs_root = _root("Springs", len(project.model.springs))
        sketch_count = (len(project.sketch.entities) + len(project.sketch.constraints)) if project.sketch is not None else 0
        sketch_root = _root("Sketch", sketch_count)
        self.tree.addTopLevelItems([sketch_root, bodies_root, sliders_root, joints_root, drivers_root, sensors_root, loads_root, springs_root])

        if project.sketch is not None:
            groups = {
                "Points": [],
                "LineSegments": [],
                "Circles": [],
                "Arcs": [],
                "InfiniteLines": [],
                "Constraints": [],
            }
            for entity in project.sketch.entities.values():
                if isinstance(entity, SketchPoint):
                    groups["Points"].append(entity)
                elif isinstance(entity, SketchLineSegment):
                    groups["LineSegments"].append(entity)
                elif isinstance(entity, SketchCircle):
                    groups["Circles"].append(entity)
                elif isinstance(entity, SketchArc):
                    groups["Arcs"].append(entity)
                elif isinstance(entity, SketchInfiniteLine):
                    groups["InfiniteLines"].append(entity)
            groups["Constraints"] = list(project.sketch.constraints.values())
            for label, entities in groups.items():
                group_item = QtWidgets.QTreeWidgetItem([f"{label}  ({len(entities)})", ""])
                group_item.setFlags(group_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
                sketch_root.addChild(group_item)
                for entity in entities:
                    kind = entity.type.value if hasattr(entity, "type") else "point"
                    if label == "Constraints":
                        kind = f"constraint_{kind}"
                    group_item.addChild(self._entity_item(entity.name, kind, entity.id))

        for body in project.model.bodies:
            body_kind = "ground" if body.metadata.values.get("ground_anchor") else body.type.value
            body_item = self._entity_item(body.name, body_kind, body.id)
            bodies_root.addChild(body_item)
            if body.metadata.values.get("ground_anchor"):
                continue
            for marker in body.markers:
                if not marker.visible and marker.type.value == "com":
                    continue
                body_item.addChild(self._entity_item(marker.name, marker.type.value, marker.id))
        for slider in project.model.sliders:
            sliders_root.addChild(self._entity_item(slider.name, "slider", slider.id))
        for joint in visible_joints:
            joints_root.addChild(self._entity_item(joint.name, joint.type.value, joint.id))
        for driver in project.model.drivers:
            drivers_root.addChild(self._entity_item(driver.name, driver.type.value, driver.id))
        for sensor in project.model.sensors:
            sensors_root.addChild(self._entity_item(sensor.name, sensor.type.value, sensor.id))
        for load in project.model.loads:
            loads_root.addChild(self._entity_item(load.name, "load", load.id))

        if project.model.gravity is not None:
            gravity_item = self._entity_item("Gravity", "gravity", "__gravity__")
            loads_root.addChild(gravity_item)

        for spring in project.model.springs:
            springs_root.addChild(self._entity_item(spring.name, spring.spring_type.value, spring.id))

        control_graph = project.model.control_graph
        if control_graph is not None and control_graph.instances:
            blocks_root = _root("Block Diagram", len(control_graph.instances))
            self.tree.addTopLevelItem(blocks_root)
            for inst in control_graph.instances.values():
                block_item = self._entity_item(inst.instance_id, f"block_{inst.block_type}", inst.instance_id)
                blocks_root.addChild(block_item)
                for param_key, param_value in inst.parameters.items():
                    param_item = QtWidgets.QTreeWidgetItem([f"{param_key} = {param_value}", "block_param"])
                    param_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("block_param", inst.instance_id, param_key))
                    block_item.addChild(param_item)
            if control_graph.connections:
                conn_root = QtWidgets.QTreeWidgetItem([f"Connections  ({len(control_graph.connections)})", ""])
                conn_root.setFlags(conn_root.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
                blocks_root.addChild(conn_root)
                for conn in control_graph.connections:
                    conn_label = f"{conn.src_instance}.{conn.src_port} → {conn.dst_instance}.{conn.dst_port}"
                    conn_item = QtWidgets.QTreeWidgetItem([conn_label, "block_connection"])
                    conn_item.setData(
                        0,
                        QtCore.Qt.ItemDataRole.UserRole,
                        ("block_connection", conn.src_instance, conn.src_port, conn.dst_instance, conn.dst_port),
                    )
                    conn_root.addChild(conn_item)

        if project.reaction_outputs:
            reactions_root = _root("Reactions", len(project.reaction_outputs))
            self.tree.addTopLevelItem(reactions_root)
            for rxn in project.reaction_outputs.values():
                reactions_root.addChild(
                    self._entity_item(rxn.joint_name, "reaction", f"__reaction__{rxn.joint_id}")
                )

        self._restore_expanded_tree_keys()

        if self._selected_entity_id:
            item = self._tree_items.get(self._selected_entity_id)
            if item is not None:
                self.tree.setCurrentItem(item)

        self.tree.blockSignals(False)

    def _inject_case_override_hints(self, selected_entity_id: str | None) -> None:
        """Render under each overridden property row a "Baseline: ..." (or
        "Inherited from <CaseName>: ...") hint, plus a Reset button when the
        override is local to the active case (hence resettable from here)."""
        if not selected_entity_id:
            return
        project = self.app_service.project
        if project is None or project.workspace is None:
            return
        ws = project.workspace
        if not ws.active_case_id:
            return
        case = next((c for c in ws.cases if c.id == ws.active_case_id), None)
        if case is None:
            return
        from quino.services.case_diff_summary import build_case_diff_summary
        summary = build_case_diff_summary(project, case)
        # Map source_case_id -> case object for name lookup.
        case_by_id = {c.id: c for c in ws.cases}
        # Invariant override hints
        for entry in summary.invariant_overrides:
            parts = entry.path.split("/")
            if len(parts) < 3 or parts[1] != selected_entity_id:
                continue
            prop_path = parts[2]
            baseline_str = self._baseline_value_for_path(project, entry.path)
            if baseline_str is None:
                baseline_str = f"{entry.value:.4g} {entry.unit}".strip()
            if entry.is_local:
                if entry.shadows_inherited:
                    source_case = case_by_id.get(entry.source_case_id)
                    parent_label = source_case.name if source_case else "parent"
                    hint = f"Baseline: {baseline_str}  ·  Local override shadows {parent_label}"
                else:
                    hint = f"Baseline: {baseline_str}"
                self.inspector.set_property_hint(prop_path, hint, resettable=True)
            else:
                source_case = case_by_id.get(entry.source_case_id)
                src_label = source_case.name if source_case else "ancestor"
                hint = f"Inherited from {src_label}: {baseline_str} (current applies)"
                self.inspector.set_property_hint(prop_path, hint, resettable=False)
        # Reference-override hints (e.g. block parameter string overrides).
        for entry in summary.reference_overrides:
            if entry.entity_id != selected_entity_id:
                continue
            # Skip internal/positional refs for blocks
            if entry.prop in {"_position"}:
                continue
            # For block string overrides we stored {parameters: {key: value}}
            # so render each nested key with the appropriate path.
            if entry.prop == "parameters" and isinstance(entry.value, dict):
                for k in entry.value:
                    prop_path = f"block_param/{entry.entity_id}/{k}"
                    if entry.is_local:
                        self.inspector.set_property_hint(
                            prop_path, "Local override (case)", resettable=True,
                        )
                    else:
                        source_case = case_by_id.get(entry.source_case_id)
                        src_label = source_case.name if source_case else "ancestor"
                        self.inspector.set_property_hint(
                            prop_path, f"Inherited from {src_label}", resettable=False,
                        )

    def _on_inspector_override_reset(self, path: str) -> None:
        """Handle the inspector's Reset-override button.

        `path` follows the inspector's row path convention (e.g.
        ``mass`` for entity props, ``block_param/<id>/<key>`` for blocks).
        We map it back to a workspace path and clear the local override.
        """
        if self.app_service.project is None:
            return
        try:
            if path.startswith("block_param/"):
                parts = path.split("/")
                if len(parts) == 3:
                    instance_id, key = parts[1], parts[2]
                    # Try invariant first; fall back to reference_overrides.
                    ws_path = f"model/control_graph/instances/{instance_id}/parameters/{key}"
                    if not self.app_service.reset_override(path=ws_path):
                        # Look up the case's reference_overrides.parameters dict
                        ws = self.app_service.project.workspace
                        if ws and ws.active_case_id:
                            case = next((c for c in ws.cases if c.id == ws.active_case_id), None)
                            if case is not None:
                                refs = case.reference_overrides.get(instance_id, {})
                                params = refs.get("parameters", {})
                                if key in params:
                                    params.pop(key)
                                    if not params:
                                        refs.pop("parameters", None)
                                    if not refs:
                                        case.reference_overrides.pop(instance_id, None)
                                    self.app_service.entities.invalidate_index()
                self.refresh_all()
                return
            # Entity row paths: prop_path is the second component of the iv path
            # (e.g. "mass"). Reconstruct the workspace path domain from the
            # selected entity.
            if self._selected_entity_id is None:
                return
            ws_path = self._workspace_path_for_entity_prop(self._selected_entity_id, path)
            if ws_path is not None:
                self.app_service.reset_override(path=ws_path)
            self.refresh_all()
        except Exception as exc:  # pragma: no cover - UI feedback
            self._append_message(f"Reset override failed: {exc}")

    def _workspace_path_for_entity_prop(self, entity_id: str, prop: str) -> str | None:
        """Best-effort mapping from (entity_id, prop) to a workspace iv_path."""
        if self.app_service.project is None:
            return None
        proj = self.app_service.project
        # bodies / loads / springs / drivers / sliders / joints / sensors / parameters
        if any(b.id == entity_id for b in proj.model.bodies):
            return f"bodies/{entity_id}/{prop}"
        if any(s.id == entity_id for s in proj.model.sliders):
            return f"sliders/{entity_id}/{prop}"
        if any(j.id == entity_id for j in proj.model.joints):
            return f"joints/{entity_id}/{prop}"
        if any(d.id == entity_id for d in proj.model.drivers):
            return f"drivers/{entity_id}/{prop}"
        if any(ld.id == entity_id for ld in proj.model.loads):
            return f"loads/{entity_id}/{prop}"
        if any(sp.id == entity_id for sp in proj.model.springs):
            # springs use two domains: springs (rest_value, law) and springs_meta
            if prop in {"stiffness", "damping"}:
                return f"springs_meta/{entity_id}/{prop}"
            return f"springs/{entity_id}/{prop}"
        # Markers live inside bodies
        for body in proj.model.bodies:
            if any(m.id == entity_id for m in body.markers):
                return f"markers/{entity_id}/{prop}"
        if any(p.id == entity_id for p in proj.parameters):
            return f"parameters/{entity_id}"
        return None

    def _populate_block_inspector(self, block, project) -> None:
        """Render the block diagram inspector using the per-block schema."""
        from quino.gui.blocks.parameter_schema import schema_for, is_hidden_param

        self.inspector_title.setText(
            f'<b>{block.instance_id}</b> &nbsp;'
            f'<span style="color:#888;font-weight:normal">{block.block_type}</span>'
        )
        schema = schema_for(block.block_type)
        enabled = self._editing_allowed() and self._app_mode != "pose"
        params = dict(block.parameters)

        # Render schema-known params in declared order; unknown params fall
        # back to a string editor.
        rendered: set[str] = set()
        for param_name, spec in schema.items():
            path = f"block_param/{block.instance_id}/{param_name}"
            value = params.get(param_name, "")
            label = spec.label or param_name
            if spec.type == "bool":
                self.inspector.add_property_checkbox(label, path, bool(value), enabled=enabled)
            elif spec.type == "entity_ref":
                choices = (
                    spec.dynamic_choices(project, params) if spec.dynamic_choices else []
                )
                self.inspector.add_property_combo(
                    label, path, str(value or ""), choices, kind="block_entity_ref", enabled=enabled,
                )
            elif spec.type == "enum":
                if spec.dynamic_choices is not None:
                    choices = spec.dynamic_choices(project, params)
                else:
                    choices = [(c, c) for c in spec.choices]
                self.inspector.add_property_combo(
                    label, path, str(value or ""), choices, kind="block_enum", enabled=enabled,
                )
            elif spec.type in {"float", "int", "str", "list_float"}:
                self.inspector.add_property(
                    label,
                    path,
                    str(value),
                    "block_param",
                    str(value),
                    enabled=enabled,
                )
            rendered.add(param_name)

        # Remaining unknown parameters (excluding internal ones).
        for param_key, param_value in params.items():
            if param_key in rendered or is_hidden_param(param_key):
                continue
            self.inspector.add_property(
                param_key,
                f"block_param/{block.instance_id}/{param_key}",
                str(param_value),
                "block_param",
                str(param_value),
                enabled=enabled,
            )

        self.inspector.layout.addStretch()

    def _baseline_value_for_path(self, project, path: str) -> str | None:
        """Read the baseline (pre-override) value at *path* for the inspector hint.

        Supports the same path domains as the composer's resolvers
        (bodies/markers/sliders/joints/drivers/springs/loads/springs_meta).
        Returns a formatted "<value> <unit>" string, or None if the path
        cannot be resolved.
        """
        try:
            parts = path.split("/")
            if len(parts) < 3:
                return None
            domain, entity_id, prop = parts[0], parts[1], parts[2]
            obj = None
            if domain == "bodies":
                obj = next((b for b in project.model.bodies if b.id == entity_id), None)
            elif domain == "markers":
                for body in project.model.bodies:
                    for m in body.markers:
                        if m.id == entity_id:
                            obj = m
                            break
                    if obj is not None:
                        break
            elif domain == "sliders":
                obj = next((s for s in project.model.sliders if s.id == entity_id), None)
            elif domain == "joints":
                joint = next((j for j in project.model.joints if j.id == entity_id), None)
                if joint is None:
                    return None
                key = {
                    "friction_coulomb": "friction_coulomb",
                    "friction_viscous": "friction_viscous",
                    "friction_pin_radius": "friction_pin_radius",
                    "angle_limit_positive": "angle_limit_positive_deg",
                    "angle_limit_negative": "angle_limit_negative_deg",
                }.get(prop, prop)
                val = joint.metadata.values.get(key)
                if val is None:
                    return "(unset)"
                return f"{float(val):.4g}"
            elif domain == "drivers":
                obj = next((d for d in project.model.drivers if d.id == entity_id), None)
            elif domain == "springs":
                obj = next((s for s in project.model.springs if s.id == entity_id), None)
            elif domain == "springs_meta":
                spring = next((s for s in project.model.springs if s.id == entity_id), None)
                if spring is None:
                    return None
                val = spring.metadata.values.get(prop)
                if val is None:
                    return "(unset)"
                return f"{float(val):.4g}"
            elif domain == "loads":
                obj = next((l for l in project.model.loads if l.id == entity_id), None)
            elif domain == "parameters":
                p = next((p for p in project.parameters if p.id == entity_id), None)
                if p is None:
                    return None
                return p.expression

            if obj is None:
                return None
            scalar = getattr(obj, prop, None)
            if scalar is None:
                return "(unset)"
            if hasattr(scalar, "expression"):
                return scalar.expression
            return str(scalar)
        except Exception:
            return None

    def _apply_case_delta_highlights(self) -> None:
        """Highlight model tree items for entities changed in the active case.

        Color semantics:
          - dark blue: property override added by THIS case (local)
          - light blue (italic): property override inherited from an ancestor
          - dark green: entity added by THIS case (local)
          - light green (italic): entity added by an ancestor case (inherited)
          - red: entity removed by THIS case
          - light red (italic): entity removed by an ancestor case
        Tooltips spell out which case set the override / addition / removal.
        """
        # First, clear all foreground overrides + font italics on entity items
        it = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            item.setForeground(0, QtGui.QBrush())
            item.setToolTip(0, "")
            font = item.font(0)
            font.setItalic(False)
            item.setFont(0, font)
            it += 1

        project = self.app_service.project
        if project is None or project.workspace is None:
            return
        ws = project.workspace
        if ws.active_case_id is None:
            return
        case = next((c for c in ws.cases if c.id == ws.active_case_id), None)
        if case is None:
            return

        from quino.services.case_diff_summary import build_case_diff_summary
        summary = build_case_diff_summary(project, case)
        if not (summary.invariant_overrides or summary.additions or summary.removals
                or summary.reference_overrides):
            return

        case_by_id = {c.id: c for c in ws.cases}

        # Aggregate per-entity: most specific tag wins (added > removed > override).
        # Each value: (color_hex, italic, tooltip)
        per_entity: dict[str, tuple[str, bool, str]] = {}

        def _set(entity_id: str, color: str, italic: bool, tip: str) -> None:
            per_entity[entity_id] = (color, italic, tip)

        from quino.gui._palette import (
            ADDED_GREEN, ADDED_GREEN_SOFT,
            OVERRIDE_ORANGE, OVERRIDE_ORANGE_SOFT,
            REMOVED_RED, REMOVED_RED_SOFT,
        )

        for entry in summary.invariant_overrides:
            parts = entry.path.split("/")
            if len(parts) >= 2:
                eid = parts[1]
                source = case_by_id.get(entry.source_case_id)
                src_label = source.name if source else entry.source_case_id
                if entry.is_local:
                    tip = f"Property override (local): {entry.path}"
                    if entry.shadows_inherited:
                        tip += "  ·  shadows an inherited override"
                    _set(eid, OVERRIDE_ORANGE, False, tip)
                else:
                    _set(eid, OVERRIDE_ORANGE_SOFT, True,
                         f"Inherited override from {src_label}: {entry.path}")

        for entry in summary.reference_overrides:
            tip = f"Override {entry.prop}"
            source = case_by_id.get(entry.source_case_id)
            src_label = source.name if source else entry.source_case_id
            if entry.is_local:
                _set(entry.entity_id, OVERRIDE_ORANGE, False, tip + " (local)")
            else:
                _set(entry.entity_id, OVERRIDE_ORANGE_SOFT, True,
                     f"Inherited {entry.prop} from {src_label}")

        for entry in summary.removals:
            if entry.kind != "entity":
                continue
            source = case_by_id.get(entry.source_case_id)
            src_label = source.name if source else entry.source_case_id
            if entry.is_local:
                _set(str(entry.payload), REMOVED_RED, False, "Removed by this case")
            else:
                _set(str(entry.payload), REMOVED_RED_SOFT, True,
                     f"Removed by ancestor {src_label}")

        for entry in summary.additions:
            source = case_by_id.get(entry.source_case_id)
            src_label = source.name if source else entry.source_case_id
            if entry.is_local:
                _set(entry.entity_id, ADDED_GREEN, False, "Added by this case")
            else:
                _set(entry.entity_id, ADDED_GREEN_SOFT, True,
                     f"Inherited (added by {src_label})")

        # Walk tree and apply.
        it = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            data = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
            entity_id: str | None = None
            if isinstance(data, (tuple, list)) and len(data) > 1:
                entity_id = data[1]
            elif isinstance(data, str):
                entity_id = data
            if entity_id and entity_id in per_entity:
                color, italic, tip = per_entity[entity_id]
                item.setForeground(0, QtGui.QBrush(QtGui.QColor(color)))
                font = item.font(0)
                font.setItalic(italic)
                item.setFont(0, font)
                item.setToolTip(0, tip)
            it += 1

    def _collect_expanded_tree_keys(self) -> set[str]:
        keys: set[str] = set()
        def walk(item: QtWidgets.QTreeWidgetItem) -> None:
            if item.isExpanded():
                key = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
                if key is not None:
                    keys.add(key)
                else:
                    text = re.sub(r"\s+\(\d+\)$", "", item.text(0))
                    keys.add(text)
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return keys

    def _restore_expanded_tree_keys(self) -> None:
        def walk(item: QtWidgets.QTreeWidgetItem) -> None:
            key = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
            if key is None:
                key = re.sub(r"\s+\(\d+\)$", "", item.text(0))
            if key in self._expanded_tree_keys:
                item.setExpanded(True)
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _entity_item(self, label: str, kind: str, entity_id: str) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([label, kind])
        item.setData(0, QtCore.Qt.ItemDataRole.UserRole, entity_id)
        icon_name = self._KIND_ICON.get(kind, "")
        if not icon_name and kind.startswith("block_"):
            icon_name = "block-instance"
        if icon_name:
            item.setIcon(0, get_icon(icon_name, size=14))
        self._tree_items[entity_id] = item
        return item

    def _populate_parameters(self, project) -> None:
        self._suspend_parameter_updates = True
        try:
            self.parameters_table.setRowCount(len(project.parameters))
            for row, parameter in enumerate(project.parameters):
                name_item = QtWidgets.QTableWidgetItem(parameter.name)
                name_item.setData(QtCore.Qt.ItemDataRole.UserRole, parameter.id)
                self.parameters_table.setItem(row, 0, name_item)
                self.parameters_table.setItem(row, 1, QtWidgets.QTableWidgetItem(parameter.expression))
                self.parameters_table.setItem(row, 2, QtWidgets.QTableWidgetItem(parameter.unit))
                self.parameters_table.setItem(row, 3, QtWidgets.QTableWidgetItem(parameter.description))
        finally:
            self._suspend_parameter_updates = False

    def _populate_canvas_summary(self, project) -> None:
        lines = [
            f"Project: {project.name}",
            f"Backend: {self.app_service.simulation_runner.describe_backend()}",
            "",
            f"Bodies: {len(project.model.bodies)}",
            f"Sliders: {len(project.model.sliders)}",
            f"Joints: {len(project.model.joints)}",
            f"Drivers: {len(project.model.drivers)}",
            "",
        ]
        for body in project.model.bodies:
            lines.append(
                f"- {body.name} [{body.type.value}] markers={len(body.markers)} closed={body.closed_shape}"
            )
        if self._last_simulation_result is not None:
            lines.extend(
                [
                    "",
                    f"Simulation success: {self._last_simulation_result.success}",
                    f"Frames: {len(self._last_simulation_result.frames)}",
                    f"Warnings: {len(self._last_simulation_result.warnings)}",
                ]
            )
            if self._last_simulation_result.frames:
                frame = self._last_simulation_result.frames[
                    max(0, min(self._current_frame_index, len(self._last_simulation_result.frames) - 1))
                ]
                lines.extend(["", "Current frame state:"])
                for key, value in sorted(frame.items()):
                    lines.append(f"  {key} = {value:.6g}")
        self.canvas_summary.setPlainText("\n".join(lines))

    _CREATION_MODES = {
        CanvasMode.CREATE_BAR, CanvasMode.CREATE_BODY, CanvasMode.ADD_MARKER,
        CanvasMode.CREATE_REVOLUTE, CanvasMode.CREATE_RIGID,
        CanvasMode.CREATE_SLIDER, CanvasMode.CONNECT_GROUND, CanvasMode.CONNECT_SLIDER,
        CanvasMode.CREATE_ROTATION_DRIVER, CanvasMode.CREATE_TRANSLATION_DRIVER,
        CanvasMode.CREATE_POINT_SENSOR, CanvasMode.CREATE_DISTANCE_SENSOR,
        CanvasMode.CREATE_ANGLE_HORIZONTAL_SENSOR, CanvasMode.CREATE_ANGLE_VERTICAL_SENSOR,
        CanvasMode.CREATE_ANGLE_VECTOR_SENSOR, CanvasMode.CREATE_LOAD,
        CanvasMode.CREATE_SKETCH_POINT, CanvasMode.CREATE_SKETCH_LINE_SEGMENT,
        CanvasMode.CREATE_SKETCH_RECTANGLE, CanvasMode.CREATE_SKETCH_CIRCLE, CanvasMode.CREATE_SKETCH_ARC_CENTER,
        CanvasMode.CREATE_SKETCH_INFINITE_LINE,
        CanvasMode.CREATE_SKETCH_FIX, CanvasMode.CREATE_SKETCH_HORIZONTAL,
        CanvasMode.CREATE_SKETCH_VERTICAL, CanvasMode.CREATE_SKETCH_DISTANCE,
        CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE, CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE,
        CanvasMode.CREATE_SKETCH_COINCIDENT,
        CanvasMode.CREATE_SKETCH_PARALLEL, CanvasMode.CREATE_SKETCH_PERPENDICULAR,
        CanvasMode.CREATE_SKETCH_EQUAL_LENGTH, CanvasMode.CREATE_SKETCH_ANGLE,
        CanvasMode.CREATE_SKETCH_MIDPOINT,
        CanvasMode.CREATE_SKETCH_COLLINEAR, CanvasMode.CREATE_SKETCH_SYMMETRIC,
        CanvasMode.CREATE_SKETCH_TANGENT,
        CanvasMode.CREATE_SKETCH_CONCENTRIC, CanvasMode.CREATE_SKETCH_ARC_CENTER,
    }

    def _on_tree_selection_changed(self, current: QtWidgets.QTreeWidgetItem | None, previous) -> None:
        del previous
        if self._suspend_tree_injection:
            return
        entity_id = current.data(0, QtCore.Qt.ItemDataRole.UserRole) if current else None
        if isinstance(entity_id, tuple):
            kind = entity_id[0]
            if kind == "block_param" and len(entity_id) >= 3:
                self._select_block(entity_id[1], reveal=True)
                return
            if kind == "block_connection":
                self._selected_entity_id = entity_id
                self._populate_inspector()
                self.canvas.set_selection(None)
                self._block_editor.set_selected(None)
                return
        project = self.app_service.display_project
        if (
            isinstance(entity_id, str)
            and project is not None
            and project.model.control_graph is not None
            and entity_id in project.model.control_graph.instances
        ):
            self._select_block(entity_id, reveal=True)
            return
        if entity_id is not None and self.canvas.mode() in self._CREATION_MODES:
            # In a creation workflow: route the selection to the canvas without
            # overwriting canvas internal state (joint start marker, etc.)
            self.canvas.inject_entity_selection(entity_id)
            return
        self._selected_entity_id = entity_id
        self._populate_inspector()
        self.canvas.set_selection(entity_id)
        if self._app_mode == "pose" and self._pose_pick_state is not None and entity_id is not None:
            self._advance_pose_pick(entity_id)

    def _select_block(self, instance_id: str | None, *, reveal: bool = False) -> None:
        """Select a block diagram instance, clearing mechanism canvas selection.

        When ``reveal`` is True (selection coming from the model tree or
        elsewhere outside the block canvas), the canvas scrolls to bring
        the block on screen if needed. When False (selection originated in
        the canvas itself), the viewport stays put.
        """
        self._selected_entity_id = instance_id
        try:
            self.canvas.set_selection(None)
        except Exception:
            pass
        if reveal:
            self._block_editor.reveal(instance_id)
        else:
            self._block_editor.set_selected(instance_id)
        item = self._tree_items.get(instance_id) if instance_id else None
        if item is not None:
            self._suspend_tree_injection = True
            try:
                self.tree.setCurrentItem(item)
            finally:
                self._suspend_tree_injection = False
        self._populate_inspector()

    def _select_entity_by_id(self, entity_id: str) -> None:
        self._block_editor.set_selected(None)
        self._selected_entity_id = entity_id
        item = self._tree_items.get(entity_id)
        if item is not None:
            self._suspend_tree_injection = True
            try:
                self.tree.setCurrentItem(item)
            finally:
                self._suspend_tree_injection = False
        self._populate_inspector()
        self.canvas.set_selection(entity_id)
        if self._app_mode == "pose" and self._pose_pick_state is not None:
            self._advance_pose_pick(entity_id)

    def _clear_selection(self) -> None:
        self._selected_entity_id = None
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)
        self._populate_inspector()
        self.canvas.set_selection(None)
        if self._pose_pick_state is not None:
            self._cancel_pose_pick()

    def _on_canvas_model_changed(self, message: str) -> None:
        self._append_message(message)
        self._mark_project_dirty()
        self.refresh_all()

    def _on_canvas_pose_marker_drag(self, marker_id: str, x: float, y: float, final: bool) -> None:
        if self._app_mode != "pose":
            return
        marker = self.app_service.get_entity(marker_id)
        if not isinstance(marker, Marker) or marker.type is not MarkerType.STRUCTURAL:
            return
        if final:
            self._pose_drag_timer.stop()
            self._pending_pose_drag = None
            self._solve_pose_with_drag(marker_id, x, y, final=True)
            return
        self._pending_pose_drag = (marker_id, x, y)
        if not self._pose_drag_timer.isActive():
            self._pose_drag_timer.start()

    def _process_pending_pose_drag(self) -> None:
        if self._pending_pose_drag is None:
            self._pose_drag_timer.stop()
            return
        marker_id, x, y = self._pending_pose_drag
        self._pending_pose_drag = None
        self._solve_pose_with_drag(marker_id, x, y, final=False)

    def _selected_structural_marker_for_pose(self) -> Marker | None:
        if self._selected_entity_id is None:
            return None
        entity = self.app_service.get_entity(self._selected_entity_id)
        if isinstance(entity, Marker) and entity.type is MarkerType.STRUCTURAL:
            return entity
        return None

    def _active_pose_constraints(self) -> list[PoseConstraint]:
        return list(self._pose_constraints.values())

    def _pose_constraints_for_drag(self, marker_id: str) -> list[PoseConstraint]:
        return list(self._pose_constraints.values())

    def _pose_constraint_to_metadata(self, constraint: PoseConstraint) -> dict:
        return {
            "id": constraint.id,
            "kind": constraint.kind,
            "target_id": constraint.target_id,
            "metadata": copy.deepcopy(constraint.metadata),
        }

    def _pose_constraint_from_metadata(self, data: dict) -> PoseConstraint | None:
        if not isinstance(data, dict):
            return None
        constraint_id = data.get("id")
        kind = data.get("kind")
        target_id = data.get("target_id")
        metadata = data.get("metadata", {})
        if not isinstance(constraint_id, str) or not isinstance(kind, str) or not isinstance(target_id, str):
            return None
        return PoseConstraint(
            id=constraint_id,
            kind=kind,
            target_id=target_id,
            metadata=copy.deepcopy(metadata) if isinstance(metadata, dict) else {},
        )

    def _store_pose_constraints_for_current_pose(self) -> None:
        pose = self.app_service.get_current_pose()
        if pose is None:
            return
        pose.metadata.values["pose_constraints"] = [
            {"key": key, "constraint": self._pose_constraint_to_metadata(constraint)}
            for key, constraint in self._pose_constraints.items()
        ]
        self.canvas.set_pose_constraints(self._pose_constraints.values())
        self._mark_project_dirty()
        # Prescribes are part of the pose's persisted state — any change
        # invalidates simulation runs that started from this pose.
        try:
            self.app_service.poses.mark_runs_stale_for_current_pose(
                "pose prescribes changed",
            )
        except Exception:
            pass
        if hasattr(self, "pose_constraints_strip"):
            self.pose_constraints_strip.refresh()

    def _load_pose_constraints_from_current_pose(self) -> None:
        pose = self.app_service.get_current_pose()
        self._pose_constraints.clear()
        if pose is not None:
            raw_items = pose.metadata.values.get("pose_constraints", [])
            if isinstance(raw_items, list):
                for item in raw_items:
                    if not isinstance(item, dict):
                        continue
                    key = item.get("key")
                    constraint = self._pose_constraint_from_metadata(item.get("constraint", {}))
                    if isinstance(key, str) and constraint is not None:
                        self._pose_constraints[key] = constraint
        self.canvas.set_pose_constraints(self._pose_constraints.values())

    def _on_pose_constraint_selected(self, constraint_key: str) -> None:
        constraint = self._pose_constraints.get(constraint_key)
        self._selected_entity_id = constraint.target_id if constraint is not None else None
        self.canvas.set_selection(self._selected_entity_id)
        self._populate_inspector()

    def _delete_pose_constraint(self, constraint_key: str) -> None:
        if constraint_key not in self._pose_constraints:
            return
        del self._pose_constraints[constraint_key]
        self._store_pose_constraints_for_current_pose()
        self._solve_pose()
        self._append_message("Deleted pose prescribe")
        self._mark_project_dirty()

    def _seed_pose_toward_marker_target(
        self,
        marker_id: str,
        x: float,
        y: float,
        base_constraints: list[PoseConstraint],
        projected_axis: str | None = None,
        projected_value: float | None = None,
    ) -> bool:
        project = self.app_service.project
        if project is None:
            return False
        saved_pose = self.app_service.get_current_pose()
        if saved_pose is None:
            return False
        try:
            assembled = self.app_service.simulation_runner.adapter.assembler.assemble(project)
        except Exception:
            return False

        fixed_angles = {
            constraint.target_id: float(constraint.metadata["angle"])
            for constraint in base_constraints
            if constraint.kind == "body_angle" and "angle" in constraint.metadata
        }
        driver_info = get_drag_driver(assembled, saved_pose, marker_id, x, y, fixed_angles=fixed_angles)
        seed_constraint: PoseConstraint
        if driver_info is not None:
            driver_body_id, driver_angle, guess_pose = driver_info
            driver_body = assembled.bodies.get(driver_body_id)
            driver_marker_id = self._equivalent_marker_on_body(assembled, marker_id, driver_body_id)
            marker_on_driver = driver_body is not None and driver_marker_id is not None
            if marker_on_driver and has_ground_revolute(assembled, driver_body_id):
                self.app_service.set_current_pose(guess_pose)
                seeded_x, seeded_y = marker_world_position(project, marker_id, guess_pose)
                if projected_axis is not None and projected_value is not None:
                    seeded_projected = seeded_x if projected_axis == "x" else seeded_y
                    if abs(seeded_projected - projected_value) <= 1e-3:
                        return True
                if math.hypot(seeded_x - x, seeded_y - y) <= 1e-3:
                    return True
                seed_constraint = PoseConstraint(
                    id=f"pose_seed_{marker_id}",
                    kind="body_angle",
                    target_id=driver_body_id,
                    metadata={"angle": driver_angle},
                )
            else:
                seed_constraint = PoseConstraint(
                    id=f"pose_seed_{marker_id}",
                    kind="marker_position",
                    target_id=marker_id,
                    metadata={"x": x, "y": y},
                )
        else:
            seed_constraint = PoseConstraint(
                id=f"pose_seed_{marker_id}",
                kind="marker_position",
                target_id=marker_id,
                metadata={"x": x, "y": y},
            )

        try:
            result = self.app_service.solve_current_pose(
                temporary_constraints=[*base_constraints, seed_constraint],
                settings=PoseSolveSettings(tolerance=1e-6, max_iterations=30, verbose=False),
            )
        except Exception:
            self.app_service.set_current_pose(saved_pose)
            return False
        if result.success:
            return True
        self.app_service.set_current_pose(saved_pose)
        return False

    def _equivalent_marker_on_body(self, assembled, marker_id: str, body_id: str) -> str | None:
        body = assembled.bodies.get(body_id)
        if body is not None and marker_id in body.markers:
            return marker_id
        visited = {marker_id}
        queue = [marker_id]
        while queue:
            current_marker_id = queue.pop(0)
            for joint in assembled.joints:
                endpoint_a = joint.endpoint_a
                endpoint_b = joint.endpoint_b
                if endpoint_a.kind is not JointEndpointKind.MARKER or endpoint_b.kind is not JointEndpointKind.MARKER:
                    continue
                neighbor_marker_id: str | None = None
                neighbor_body_id: str | None = None
                if endpoint_a.marker_id == current_marker_id:
                    neighbor_marker_id = endpoint_b.marker_id
                    neighbor_body_id = endpoint_b.body_id
                elif endpoint_b.marker_id == current_marker_id:
                    neighbor_marker_id = endpoint_a.marker_id
                    neighbor_body_id = endpoint_a.body_id
                if neighbor_marker_id is None:
                    continue
                if neighbor_body_id == body_id:
                    return neighbor_marker_id
                if neighbor_marker_id not in visited:
                    visited.add(neighbor_marker_id)
                    queue.append(neighbor_marker_id)
        return None

    def _resolve_pose_link_markers(
        self,
        assembled,
        marker_id_1: str,
        marker_id_2: str,
        label: str,
    ) -> tuple[Body, str, str] | None:
        body_1 = self._body_for_marker_id(marker_id_1)
        body_2 = self._body_for_marker_id(marker_id_2)
        if body_1 is None or body_2 is None:
            self._append_message("Could not resolve marker bodies")
            return None
        if body_1.id == body_2.id:
            return body_1, marker_id_1, marker_id_2

        marker_1_on_body_2 = self._equivalent_marker_on_body(assembled, marker_id_1, body_2.id)
        if marker_1_on_body_2 is not None and marker_1_on_body_2 != marker_id_2:
            return body_2, marker_1_on_body_2, marker_id_2

        marker_2_on_body_1 = self._equivalent_marker_on_body(assembled, marker_id_2, body_1.id)
        if marker_2_on_body_1 is not None and marker_2_on_body_1 != marker_id_1:
            return body_1, marker_id_1, marker_2_on_body_1

        self._append_message(f"Markers must define one link for {label} angle prescription")
        return None

    def _projected_seed_free_offsets(self) -> list[float]:
        project = self.app_service.project
        if project is None:
            return [0.0]
        try:
            assembled = self.app_service.simulation_runner.adapter.assembler.assemble(project)
        except Exception:
            return [0.0, 10.0, -10.0, 25.0, -25.0, 50.0, -50.0, 100.0, -100.0]
        points: list[tuple[float, float]] = []
        pose = self.app_service.get_current_pose()
        for body_id, body in assembled.bodies.items():
            body_pose = pose.body_poses.get(body_id) if pose is not None else None
            angle = body_pose.angle if body_pose is not None else body.angle
            origin_x = body_pose.x if body_pose is not None else body.origin_x
            origin_y = body_pose.y if body_pose is not None else body.origin_y
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            for marker in body.markers.values():
                points.append((
                    origin_x + cos_a * marker.local_x - sin_a * marker.local_y,
                    origin_y + sin_a * marker.local_x + cos_a * marker.local_y,
                ))
        if not points:
            return [0.0]
        min_x = min(point[0] for point in points)
        max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_y = max(point[1] for point in points)
        reach = max(50.0, math.hypot(max_x - min_x, max_y - min_y) * 1.25)
        offsets = [0.0]
        step = max(10.0, reach / 8.0)
        value = step
        while value <= reach + 1e-9:
            offsets.extend([value, -value])
            value += step
        return offsets

    def _seed_pose_toward_projected_coordinate(
        self,
        marker_id: str,
        axis: str,
        axis_value: float,
        other_value: float,
        base_constraints: list[PoseConstraint],
    ) -> bool:
        saved_pose = copy.deepcopy(self.app_service.get_current_pose())
        for offset in self._projected_seed_free_offsets():
            if saved_pose is not None:
                self.app_service.set_current_pose(saved_pose)
            candidate_other = other_value + offset
            target_x = axis_value if axis == "x" else candidate_other
            target_y = axis_value if axis == "y" else candidate_other
            if not self._seed_pose_toward_marker_target(
                marker_id,
                target_x,
                target_y,
                base_constraints,
                projected_axis=axis,
                projected_value=axis_value,
            ):
                continue
            seeded_value = self._pose_marker_axis_value(marker_id, axis)
            if seeded_value is not None and abs(seeded_value - axis_value) <= 1e-3:
                return True
        if saved_pose is not None:
            self.app_service.set_current_pose(saved_pose)
        return False

    def _pose_marker_axis_value(self, marker_id: str, axis: str) -> float | None:
        project = self.app_service.project
        pose = self.app_service.get_current_pose()
        if project is None or pose is None:
            return None
        world_x, world_y = marker_world_position(project, marker_id, pose)
        return world_x if axis == "x" else world_y

    def _accept_kinematic_coordinate_pose(
        self,
        constraint_key: str,
        constraint: PoseConstraint,
        marker_id: str,
        axis: str,
        target_value: float,
        tolerance_mm: float,
        steps_completed: int,
    ) -> tuple[bool, PoseSolveResult, int]:
        current_value = self._pose_marker_axis_value(marker_id, axis)
        if current_value is None or abs(current_value - target_value) > max(tolerance_mm, 1e-3):
            return (
                False,
                PoseSolveResult(success=False, error="Kinematic pose did not reach prescribed coordinate"),
                steps_completed,
            )
        violation = self._pose_joint_constraint_violation(tolerance_mm=1e-3)
        if violation is not None:
            return (
                False,
                PoseSolveResult(success=False, error=violation),
                steps_completed,
            )
        final_constraint = copy.deepcopy(constraint)
        final_constraint.metadata["value"] = target_value
        self._pose_constraints[constraint_key] = final_constraint
        self._store_pose_constraints_for_current_pose()
        self._apply_current_frame()
        self._populate_inspector()
        return (
            True,
            PoseSolveResult(
                success=True,
                pose=copy.deepcopy(self.app_service.get_current_pose()),
                warnings=["Pose coordinate solved kinematically because the static solve was singular"],
                messages=["Kinematic pose coordinate fallback completed"],
                backend="kinematic_pose",
            ),
            steps_completed,
        )

    def _seed_pose_toward_body_angle(
        self,
        body_id: str,
        target_angle: float,
        base_constraints: list[PoseConstraint],
    ) -> bool:
        project = self.app_service.project
        pose = self.app_service.get_current_pose()
        if project is None or pose is None:
            return False
        try:
            assembled = self.app_service.simulation_runner.adapter.assembler.assemble(project)
        except Exception:
            return False
        fixed_angles = {
            constraint.target_id: float(constraint.metadata["angle"])
            for constraint in base_constraints
            if constraint.kind == "body_angle" and "angle" in constraint.metadata
        }
        fixed_angles[body_id] = target_angle
        seeded_pose = _pose_at_angle(assembled, pose, body_id, target_angle, fixed_angles)
        self.app_service.set_current_pose(seeded_pose)
        body_pose = seeded_pose.body_poses.get(body_id)
        if body_pose is None:
            return False
        remaining = (target_angle - body_pose.angle + math.pi) % (2.0 * math.pi) - math.pi
        if abs(remaining) > 1e-5:
            return False
        violation = self._pose_joint_constraint_violation(tolerance_mm=1e-3)
        return violation is None

    def _accept_kinematic_body_angle_pose(
        self,
        constraint_key: str,
        body_id: str,
        target_angle: float,
        tolerance_rad: float,
        steps_completed: int,
    ) -> tuple[bool, PoseSolveResult, int]:
        pose = self.app_service.get_current_pose()
        body_pose = pose.body_poses.get(body_id) if pose is not None else None
        if body_pose is None:
            return (
                False,
                PoseSolveResult(success=False, error="Kinematic pose did not resolve the prescribed body"),
                steps_completed,
            )
        remaining = (target_angle - body_pose.angle + math.pi) % (2.0 * math.pi) - math.pi
        if abs(remaining) > tolerance_rad:
            return (
                False,
                PoseSolveResult(success=False, error="Kinematic pose did not reach prescribed angle"),
                steps_completed,
            )
        violation = self._pose_joint_constraint_violation(tolerance_mm=1e-3)
        if violation is not None:
            return (
                False,
                PoseSolveResult(success=False, error=violation),
                steps_completed,
            )
        final_constraint = PoseConstraint(
            id=f"pose_body_angle_{body_id}",
            kind="body_angle",
            target_id=body_id,
            metadata={"angle": target_angle},
        )
        self._pose_constraints[constraint_key] = final_constraint
        self._store_pose_constraints_for_current_pose()
        self._apply_current_frame()
        self._populate_inspector()
        return (
            True,
            PoseSolveResult(
                success=True,
                pose=copy.deepcopy(self.app_service.get_current_pose()),
                warnings=["Pose angle solved kinematically because the static solve was singular"],
                messages=["Kinematic pose angle fallback completed"],
                backend="kinematic_pose",
            ),
            steps_completed,
        )

    def _pose_marker_world_position_from_assembled(
        self,
        assembled,
        body_id: str | None,
        marker_id: str | None,
    ) -> tuple[float, float] | None:
        if body_id is None or marker_id is None:
            return None
        body = assembled.bodies.get(body_id)
        marker = body.markers.get(marker_id) if body is not None else None
        pose = self.app_service.get_current_pose()
        if body is None or marker is None or pose is None:
            return None
        body_pose = pose.body_poses.get(body_id)
        if body_pose is None:
            return marker.global_x, marker.global_y
        cos_a = math.cos(body_pose.angle)
        sin_a = math.sin(body_pose.angle)
        return (
            body_pose.x + cos_a * marker.local_x - sin_a * marker.local_y,
            body_pose.y + sin_a * marker.local_x + cos_a * marker.local_y,
        )

    def _pose_joint_constraint_violation(self, *, tolerance_mm: float) -> str | None:
        project = self.app_service.project
        if project is None:
            return None
        try:
            assembled = self.app_service.simulation_runner.adapter.assembler.assemble(project)
        except Exception as exc:
            return f"Could not validate pose joints: {exc}"
        for joint in assembled.joints:
            endpoint_a = joint.endpoint_a
            endpoint_b = joint.endpoint_b
            endpoints = (endpoint_a, endpoint_b)
            marker_endpoints = [endpoint for endpoint in endpoints if endpoint.kind is JointEndpointKind.MARKER]
            slider_endpoints = [endpoint for endpoint in endpoints if endpoint.kind is JointEndpointKind.SLIDER]

            if len(marker_endpoints) == 2:
                pos_a = self._pose_marker_world_position_from_assembled(
                    assembled, marker_endpoints[0].body_id, marker_endpoints[0].marker_id
                )
                pos_b = self._pose_marker_world_position_from_assembled(
                    assembled, marker_endpoints[1].body_id, marker_endpoints[1].marker_id
                )
                if pos_a is None or pos_b is None:
                    continue
                gap = math.hypot(pos_a[0] - pos_b[0], pos_a[1] - pos_b[1])
                if gap > tolerance_mm:
                    return f"Kinematic pose would violate joint {joint.name}: marker gap {gap:.6g} mm"
                angular_violation = self._pose_joint_angle_limit_violation(joint, assembled)
                if angular_violation is not None:
                    return angular_violation
                continue

            if len(marker_endpoints) == 1 and any(endpoint.kind is JointEndpointKind.GROUND for endpoint in endpoints):
                marker_endpoint = marker_endpoints[0]
                body = assembled.bodies.get(marker_endpoint.body_id)
                marker = body.markers.get(marker_endpoint.marker_id) if body is not None else None
                pos = self._pose_marker_world_position_from_assembled(
                    assembled, marker_endpoint.body_id, marker_endpoint.marker_id
                )
                if marker is None or pos is None:
                    continue
                gap = math.hypot(pos[0] - marker.global_x, pos[1] - marker.global_y)
                if gap > tolerance_mm:
                    return f"Kinematic pose would violate ground joint {joint.name}: gap {gap:.6g} mm"
                angular_violation = self._pose_joint_angle_limit_violation(joint, assembled)
                if angular_violation is not None:
                    return angular_violation
                continue

            if len(marker_endpoints) == 1 and slider_endpoints:
                marker_endpoint = marker_endpoints[0]
                slider = assembled.sliders.get(slider_endpoints[0].slider_id)
                pos = self._pose_marker_world_position_from_assembled(
                    assembled, marker_endpoint.body_id, marker_endpoint.marker_id
                )
                if slider is None or pos is None:
                    continue
                dx = pos[0] - slider.origin_x
                dy = pos[1] - slider.origin_y
                normal_gap = abs(dx * slider.normal_x + dy * slider.normal_y)
                slider_coordinate = dx * slider.axis_x + dy * slider.axis_y
                if normal_gap > tolerance_mm:
                    return f"Kinematic pose would violate slider joint {joint.name}: normal gap {normal_gap:.6g} mm"
                if slider.travel_min is not None and slider_coordinate < slider.travel_min - tolerance_mm:
                    return (
                        f"Kinematic pose would violate slider joint {joint.name}: "
                        f"coordinate {slider_coordinate:.6g} mm below travel_min {slider.travel_min:.6g} mm"
                    )
                if slider.travel_max is not None and slider_coordinate > slider.travel_max + tolerance_mm:
                    return (
                        f"Kinematic pose would violate slider joint {joint.name}: "
                        f"coordinate {slider_coordinate:.6g} mm above travel_max {slider.travel_max:.6g} mm"
                    )
        return None

    def _pose_joint_angle_limit_violation(self, joint: Joint, assembled) -> str | None:
        if not self.app_service.joint_supports_angular_limits(joint):
            return None
        positive, negative = self.app_service.joint_angular_limit_values(joint)
        if positive is None and negative is None:
            return None
        current = self._pose_joint_relative_angle_delta_deg(joint, assembled)
        if current is None:
            return None
        lower = -(negative or 0.0)
        upper = positive or 0.0
        tolerance = 1e-6
        if current < lower - tolerance or current > upper + tolerance:
            return (
                f"Kinematic pose would violate angular limit on joint {joint.name}: "
                f"relative angle {current:.6g} deg outside [{lower:.6g}, {upper:.6g}] deg"
            )
        return None

    def _pose_joint_relative_angle_delta_deg(self, joint: Joint, assembled) -> float | None:
        pose = self.app_service.get_current_pose()
        if pose is None:
            return None

        def _pose_angle(body_id: str | None) -> float | None:
            if body_id is None:
                return None
            body_pose = pose.body_poses.get(body_id)
            return body_pose.angle if body_pose is not None else None

        def _is_ground_anchor(body_id: str | None) -> bool:
            if body_id is None:
                return False
            body = self.app_service.get_body(body_id)
            return bool(body is not None and body.metadata.values.get("ground_anchor"))

        if joint.endpoint_a.kind is JointEndpointKind.GROUND and joint.endpoint_b.kind is JointEndpointKind.MARKER:
            body_id = joint.endpoint_b.body_id
            pose_angle = _pose_angle(body_id)
            reference = assembled.bodies.get(body_id or "")
            if pose_angle is None or reference is None:
                return None
            return math.degrees(pose_angle - reference.angle)
        if joint.endpoint_b.kind is JointEndpointKind.GROUND and joint.endpoint_a.kind is JointEndpointKind.MARKER:
            body_id = joint.endpoint_a.body_id
            pose_angle = _pose_angle(body_id)
            reference = assembled.bodies.get(body_id or "")
            if pose_angle is None or reference is None:
                return None
            return math.degrees(pose_angle - reference.angle)

        body_a_id = joint.endpoint_a.body_id
        body_b_id = joint.endpoint_b.body_id
        pose_a = _pose_angle(body_a_id)
        pose_b = _pose_angle(body_b_id)
        ref_a = assembled.bodies.get(body_a_id or "")
        ref_b = assembled.bodies.get(body_b_id or "")
        if pose_a is None or pose_b is None or ref_a is None or ref_b is None:
            return None
        if _is_ground_anchor(body_a_id) and not _is_ground_anchor(body_b_id):
            return math.degrees((pose_b - pose_a) - (ref_b.angle - ref_a.angle))
        if _is_ground_anchor(body_b_id) and not _is_ground_anchor(body_a_id):
            return math.degrees((pose_a - pose_b) - (ref_a.angle - ref_b.angle))
        return math.degrees((pose_b - pose_a) - (ref_b.angle - ref_a.angle))

    def _solve_pose_constraint_progressively(
        self,
        constraint_key: str,
        axis: str,
        marker_id: str,
        target_value: float,
    ) -> tuple[bool, PoseSolveResult, int]:
        self._ensure_pose_session()
        starting_pose = copy.deepcopy(self.app_service.get_current_pose())
        base_constraints = [
            constraint
            for key, constraint in self._pose_constraints.items()
            if key != constraint_key
        ]
        template = PoseConstraint(
            id=f"pose_{axis}_{marker_id}",
            kind="marker_projected_coordinate",
            target_id=marker_id,
            metadata={
                "reference_x": 0.0,
                "reference_y": 0.0,
                "axis_x": 1.0 if axis == "x" else 0.0,
                "axis_y": 0.0 if axis == "x" else 1.0,
                "value": target_value,
            },
        )
        max_step_mm = 25.0
        min_step_mm = 0.25
        tolerance_mm = 1e-3
        step_limit = max_step_mm
        steps_completed = 0
        last_result = PoseSolveResult(
            success=False,
            error="Pose solve did not start",
            messages=["Progressive pose solve did not start"],
        )

        for _ in range(120):
            pose = self.app_service.get_current_pose()
            world_x, world_y = marker_world_position(self.app_service.project, marker_id, pose)
            current_value = world_x if axis == "x" else world_y
            remaining = target_value - current_value
            if abs(remaining) <= tolerance_mm:
                final_constraint = copy.deepcopy(template)
                last_result = self.app_service.solve_current_pose(
                    temporary_constraints=[*base_constraints, final_constraint],
                    settings=PoseSolveSettings(),
                )
                if last_result.success:
                    self._pose_constraints[constraint_key] = final_constraint
                    self._store_pose_constraints_for_current_pose()
                    self._apply_current_frame()
                    self._populate_inspector()
                    return True, last_result, steps_completed
                accepted, fallback_result, fallback_steps = self._accept_kinematic_coordinate_pose(
                    constraint_key,
                    final_constraint,
                    marker_id,
                    axis,
                    target_value,
                    tolerance_mm,
                    steps_completed,
                )
                if accepted:
                    return True, fallback_result, fallback_steps
                if step_limit <= min_step_mm:
                    break
                step_limit *= 0.5
                continue

            other_value = world_y if axis == "x" else world_x
            direct_seed_success = self._seed_pose_toward_projected_coordinate(
                marker_id,
                axis,
                target_value,
                other_value,
                base_constraints,
            )
            if direct_seed_success:
                accepted, fallback_result, fallback_steps = self._accept_kinematic_coordinate_pose(
                    constraint_key,
                    template,
                    marker_id,
                    axis,
                    target_value,
                    tolerance_mm,
                    steps_completed + 1,
                )
                if accepted:
                    return True, fallback_result, fallback_steps

            step_value = target_value if abs(remaining) <= step_limit else current_value + math.copysign(step_limit, remaining)
            working_constraint = copy.deepcopy(template)
            working_constraint.metadata["value"] = step_value
            seed_success = self._seed_pose_toward_projected_coordinate(
                marker_id,
                axis,
                step_value,
                other_value,
                base_constraints,
            )
            if seed_success:
                seeded_value = self._pose_marker_axis_value(marker_id, axis)
                if seeded_value is not None and abs(seeded_value - step_value) <= max(tolerance_mm, 1e-3):
                    steps_completed += 1
                    if abs(target_value - seeded_value) <= tolerance_mm:
                        accepted, fallback_result, fallback_steps = self._accept_kinematic_coordinate_pose(
                            constraint_key,
                            template,
                            marker_id,
                            axis,
                            target_value,
                            tolerance_mm,
                            steps_completed,
                        )
                        if accepted:
                            return True, fallback_result, fallback_steps
                    self._apply_current_frame()
                    self._populate_inspector()
                    QtWidgets.QApplication.processEvents()
                    continue
            last_result = self.app_service.solve_current_pose(
                temporary_constraints=[*base_constraints, working_constraint],
                settings=PoseSolveSettings(
                    tolerance=1e-7,
                    max_iterations=40,
                    verbose=False,
                ),
            )
            if last_result.success:
                new_pose = self.app_service.get_current_pose()
                new_world_x, new_world_y = marker_world_position(self.app_service.project, marker_id, new_pose)
                new_value = new_world_x if axis == "x" else new_world_y
                if abs(new_value - current_value) <= tolerance_mm and abs(remaining) > tolerance_mm:
                    if step_limit <= min_step_mm:
                        last_result = PoseSolveResult(
                            success=False,
                            error="Pose solve stalled before reaching the prescribed coordinate",
                            messages=["Progressive pose solve stalled"],
                        )
                        break
                    step_limit *= 0.5
                    continue
                steps_completed += 1
                self._apply_current_frame()
                self._populate_inspector()
                QtWidgets.QApplication.processEvents()
                continue

            if step_limit <= min_step_mm:
                break
            step_limit *= 0.5

        if starting_pose is not None:
            self.app_service.set_current_pose(starting_pose)
            self._apply_current_frame()
            self._populate_inspector()
        return False, last_result, steps_completed

    def _reset_pose(self) -> None:
        if self._app_mode != "pose":
            return
        self._reset_pose_ui_state()
        self.app_service.reset_current_pose_to_reference()
        self._apply_current_frame()
        self._populate_inspector()
        self._append_message("Pose reset to reference")

    def _solve_pose(self) -> None:
        self._ensure_pose_session()
        result = self.app_service.solve_current_pose(
            temporary_constraints=self._active_pose_constraints(),
            settings=PoseSolveSettings(),
        )
        if not result.success:
            seeded = False
            for constraint in self._active_pose_constraints():
                if constraint.kind == "body_angle" and "angle" in constraint.metadata:
                    base_constraints = [
                        other for other in self._active_pose_constraints() if other is not constraint
                    ]
                    seeded = self._seed_pose_toward_body_angle(
                        constraint.target_id,
                        float(constraint.metadata["angle"]),
                        base_constraints,
                    )
                    if not seeded:
                        break
            if seeded and self._pose_joint_constraint_violation(tolerance_mm=1e-3) is None:
                result = PoseSolveResult(
                    success=True,
                    pose=copy.deepcopy(self.app_service.get_current_pose()),
                    warnings=["Pose solved kinematically because the static solve was singular"],
                    backend="kinematic_pose",
                )
        if result.success:
            violation = self._pose_joint_constraint_violation(tolerance_mm=1e-3)
            if violation is not None:
                result = PoseSolveResult(
                    success=False,
                    pose=copy.deepcopy(self.app_service.get_current_pose()),
                    warnings=list(result.warnings),
                    messages=[*result.messages, violation],
                    backend=result.backend,
                    error=violation,
                )
        self._apply_current_frame()
        self._populate_inspector()
        if result.success:
            self._store_pose_constraints_for_current_pose()
            self._append_message("Pose solved")
            for warning in result.warnings:
                self._append_message(f"Pose warning: {warning}")
        else:
            detail = f": {result.error}" if result.error else ""
            self._append_message(f"Pose solve failed{detail}")

    def _set_current_pose_as_initial(self) -> None:
        if self._app_mode != "pose":
            return
        try:
            self.app_service.set_initial_pose_from_current()
            self._mark_project_dirty()
            self._append_message("Current pose saved as initial pose")
            self.refresh_all()
        except Exception as exc:
            self._append_message(f"Set initial pose failed: {exc}")

    def _clear_initial_pose(self) -> None:
        try:
            self.app_service.clear_initial_pose()
            self._mark_project_dirty()
            self._append_message("Initial pose cleared")
            self.refresh_all()
        except Exception as exc:
            self._append_message(f"Clear initial pose failed: {exc}")

    def _prescribe_pose_coordinate(self, axis: str) -> None:
        if self._app_mode != "pose":
            return
        self._ensure_pose_session()
        self._active_prescribe_action = self.action_pose_prescribe_x if axis == "x" else self.action_pose_prescribe_y
        label = "X" if axis == "x" else "Y"
        self._pose_pick_state = {"kind": f"{axis}_coord", "picks": []}
        self.canvas.set_mode(CanvasMode.POSE_PICK)
        self._sync_pose_pick_preview()
        self._append_message(f"Click a structural marker to prescribe {label} coordinate (Esc to cancel)")

    def _body_for_marker_id(self, marker_id: str):
        project = self.app_service.project
        if project is None:
            return None
        return next(
            (body for body in project.model.bodies if any(m.id == marker_id for m in body.markers)),
            None,
        )

    def _parse_pose_dialog_value(self, raw_text: str, *, target_unit: str, default_unit: str) -> float:
        normalized = raw_text.strip().replace(",", ".")
        try:
            return float(normalized)
        except ValueError:
            pass
        quantity = self.app_service.expression_service.evaluate_expression(
            normalized if any(ch.isalpha() for ch in normalized) else f"{normalized} {default_unit}",
            self.app_service.project.parameters,
        )
        return float(self.app_service.unit_service.convert(quantity, target_unit))

    def _prescribe_horizontal_angle(self) -> None:
        if self._app_mode != "pose":
            return
        self._ensure_pose_session()
        self._active_prescribe_action = self.action_pose_prescribe_horizontal
        self._pose_pick_state = {"kind": "horiz_angle", "picks": []}
        self.canvas.set_mode(CanvasMode.POSE_PICK)
        self._sync_pose_pick_preview()
        self._append_message("Click first marker of the link to prescribe its angle from horizontal (Esc to cancel)")

    def _prescribe_vertical_angle(self) -> None:
        if self._app_mode != "pose":
            return
        self._ensure_pose_session()
        self._active_prescribe_action = self.action_pose_prescribe_vertical
        self._pose_pick_state = {"kind": "vert_angle", "picks": []}
        self.canvas.set_mode(CanvasMode.POSE_PICK)
        self._sync_pose_pick_preview()
        self._append_message("Click first marker of the link to prescribe its angle from vertical (Esc to cancel)")

    def _prescribe_relative_angle(self) -> None:
        if self._app_mode != "pose":
            return
        self._ensure_pose_session()
        self._active_prescribe_action = self.action_pose_prescribe_angle
        self._pose_pick_state = {"kind": "relative_angle", "picks": []}
        self.canvas.set_mode(CanvasMode.POSE_PICK)
        self._sync_pose_pick_preview()
        self._append_message("Click first marker of Link A (Esc to cancel)")

    def _sync_pose_pick_preview(self) -> None:
        state = self._pose_pick_state
        if state is None:
            self.canvas.set_pose_pick_preview(None, [])
            return
        self.canvas.set_pose_pick_preview(state.get("kind"), state.get("picks", []))

    def _cancel_pose_pick(self) -> None:
        active = self._active_prescribe_action
        self._active_prescribe_action = None
        self._pose_pick_state = None
        self.canvas.set_pose_pick_preview(None, [])
        if active is not None:
            active.setChecked(False)
        if self.canvas._mode == CanvasMode.POSE_PICK:
            self.canvas.set_mode(CanvasMode.SELECT)
        self._append_message("Cancelled")

    def _finish_pose_pick(self) -> None:
        active = self._active_prescribe_action
        self._active_prescribe_action = None
        self.canvas.set_pose_pick_preview(None, [])
        if active is not None:
            active.setChecked(False)
        if self.canvas._mode == CanvasMode.POSE_PICK:
            self.canvas.set_mode(CanvasMode.SELECT)

    def _advance_pose_pick(self, entity_id: str) -> None:
        state = self._pose_pick_state
        if state is None:
            return
        entity = self.app_service.get_entity(entity_id)
        if not isinstance(entity, Marker) or entity.type is not MarkerType.STRUCTURAL:
            return

        kind: str = state["kind"]
        picks: list = state["picks"]

        if entity_id in picks:
            self._append_message("Pick a different marker")
            return
        picks.append(entity_id)
        self._sync_pose_pick_preview()

        if kind in ("x_coord", "y_coord"):
            self._pose_pick_state = None
            self._finish_pose_pick()
            axis = "x" if kind == "x_coord" else "y"
            label = "X" if axis == "x" else "Y"
            pose = self.app_service.get_current_pose()
            world_x, world_y = marker_world_position(self.app_service.project, entity_id, pose)
            current_value = world_x if axis == "x" else world_y
            text, accepted = QtWidgets.QInputDialog.getText(
                self,
                f"Prescribe {label}",
                f"Target {label} for {entity.name} [mm]:",
                text=f"{current_value:.6g}",
            )
            if not accepted or not text.strip():
                return
            try:
                value_mm = self._parse_pose_dialog_value(text, target_unit="mm", default_unit="mm")
            except Exception as exc:
                self._append_message(f"{label} must be a valid length: {exc}")
                return
            success, result, steps_completed = self._solve_pose_constraint_progressively(
                f"{axis}:{entity_id}", axis, entity_id, value_mm
            )
            if success:
                if steps_completed > 1:
                    self._append_message(f"Pose solved in {steps_completed} intermediate steps")
                else:
                    self._append_message("Pose solved")
                for warning in result.warnings:
                    self._append_message(f"Pose warning: {warning}")
            else:
                detail = f": {result.error}" if result.error else ""
                self._append_message(f"Pose solve failed{detail}")

        elif kind in ("horiz_angle", "vert_angle"):
            if len(picks) == 1:
                self._append_message(f"{entity.name} — click second marker of the same link")
            elif len(picks) == 2:
                reference_world_angle = 0.0 if kind == "horiz_angle" else math.pi / 2.0
                label = "Horizontal" if kind == "horiz_angle" else "Vertical"
                QtWidgets.QApplication.processEvents()
                self._execute_body_angle_from_picks(picks[0], picks[1], reference_world_angle, label)
                self._pose_pick_state = None
                self._finish_pose_pick()

        elif kind == "relative_angle":
            if len(picks) == 1:
                self._append_message(f"Link A: {entity.name} — click second marker of Link A")
            elif len(picks) == 2:
                self._append_message("Click first marker of Link B")
            elif len(picks) == 3:
                self._append_message(f"Link B: {entity.name} — click second marker of Link B")
            elif len(picks) == 4:
                QtWidgets.QApplication.processEvents()
                self._execute_relative_angle_from_picks(picks)
                self._pose_pick_state = None
                self._finish_pose_pick()

    def _execute_body_angle_from_picks(
        self, marker_id_1: str, marker_id_2: str, reference_world_angle: float, label: str
    ) -> None:
        assembled = assembled_reference_mechanism(self.app_service.project)
        resolved = self._resolve_pose_link_markers(assembled, marker_id_1, marker_id_2, label)
        if resolved is None:
            return
        body_1, marker_id_1, marker_id_2 = resolved
        body_asm = assembled.bodies.get(body_1.id)
        if body_asm is None:
            self._append_message("Could not resolve body in assembled mechanism")
            return
        m1 = body_asm.markers.get(marker_id_1)
        m2 = body_asm.markers.get(marker_id_2)
        if m1 is None or m2 is None:
            self._append_message("Could not resolve markers in assembled mechanism")
            return
        local_phi = math.atan2(m2.local_y - m1.local_y, m2.local_x - m1.local_x)
        pose = self.app_service.get_current_pose()
        world_1 = marker_world_position(self.app_service.project, marker_id_1, pose)
        world_2 = marker_world_position(self.app_service.project, marker_id_2, pose)
        current_world_angle = math.atan2(world_2[1] - world_1[1], world_2[0] - world_1[0])
        current_reference_angle = math.atan2(
            math.sin(current_world_angle - reference_world_angle),
            math.cos(current_world_angle - reference_world_angle),
        )
        text, accepted = QtWidgets.QInputDialog.getText(
            self,
            f"Prescribe {label} Angle",
            f"Target angle from {label.lower()} for {body_1.name} [deg]:",
            text=f"{math.degrees(current_reference_angle):.6g}",
        )
        if not accepted or not text.strip():
            return
        try:
            target_reference_angle = math.radians(
                self._parse_pose_dialog_value(text, target_unit="deg", default_unit="deg")
            )
        except Exception as exc:
            self._append_message(f"Angle must be a valid angle: {exc}")
            return
        target_world_angle = reference_world_angle + target_reference_angle
        target_body_angle = target_world_angle - local_phi
        constraint_key = f"body_angle:{body_1.id}"
        success, result, steps_completed = self._prescribe_body_angle_progressively(
            constraint_key, body_1.id, target_body_angle
        )
        if success:
            if steps_completed > 1:
                self._append_message(f"{label} angle prescribed in {steps_completed} intermediate steps")
            else:
                self._append_message(f"{label} angle prescribed")
            for warning in result.warnings:
                self._append_message(f"Pose warning: {warning}")
        else:
            detail = f": {result.error}" if result.error else ""
            self._append_message(f"{label} angle prescription failed{detail}")

    def _execute_relative_angle_from_picks(self, picks: list) -> None:
        marker_a1_id, marker_a2_id, marker_b1_id, marker_b2_id = picks
        project = self.app_service.project

        assembled = assembled_reference_mechanism(project)
        resolved_a = self._resolve_pose_link_markers(assembled, marker_a1_id, marker_a2_id, "Link A")
        resolved_b = self._resolve_pose_link_markers(assembled, marker_b1_id, marker_b2_id, "Link B")
        if resolved_a is None or resolved_b is None:
            return
        body_a1, marker_a1_id, marker_a2_id = resolved_a
        body_b1, marker_b1_id, marker_b2_id = resolved_b

        body_a1 = self._body_for_marker_id(marker_a1_id)
        body_a2 = self._body_for_marker_id(marker_a2_id)
        body_b1 = self._body_for_marker_id(marker_b1_id)
        body_b2 = self._body_for_marker_id(marker_b2_id)

        if body_a1 is None or body_a2 is None or body_b1 is None or body_b2 is None:
            self._append_message("Could not resolve marker bodies")
            return
        if body_a1.id != body_a2.id:
            self._append_message("Link A markers must be on the same body — prescription cancelled")
            return
        if body_b1.id != body_b2.id:
            self._append_message("Link B markers must be on the same body — prescription cancelled")
            return
        if body_a1.id == body_b1.id:
            self._append_message("Link A and Link B must be on different bodies — prescription cancelled")
            return

        assembled = assembled_reference_mechanism(project)
        body_a_asm = assembled.bodies.get(body_a1.id)
        body_b_asm = assembled.bodies.get(body_b1.id)
        if body_a_asm is None or body_b_asm is None:
            self._append_message("Could not resolve bodies in assembled mechanism")
            return

        ma1 = body_a_asm.markers.get(marker_a1_id)
        ma2 = body_a_asm.markers.get(marker_a2_id)
        mb1 = body_b_asm.markers.get(marker_b1_id)
        mb2 = body_b_asm.markers.get(marker_b2_id)
        if None in (ma1, ma2, mb1, mb2):
            self._append_message("Could not resolve markers in assembled mechanism")
            return

        local_phi_a = math.atan2(ma2.local_y - ma1.local_y, ma2.local_x - ma1.local_x)
        local_phi_b = math.atan2(mb2.local_y - mb1.local_y, mb2.local_x - mb1.local_x)

        pose = self.app_service.get_current_pose()
        current_relative_deg = math.degrees(
            self._current_relative_body_angle(
                pose,
                body_a1.id,
                body_b1.id,
                body_a_asm.angle,
                body_b_asm.angle,
                local_phi_a,
                local_phi_b,
            )
        )

        text, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Prescribe Relative Angle",
            f"Angle between {body_a1.name}→Link A and {body_b1.name}→Link B [deg]:",
            text=f"{current_relative_deg:.4g}",
        )
        if not accepted or not text.strip():
            return
        try:
            target_angle_rad = math.radians(
                self._parse_pose_dialog_value(text, target_unit="deg", default_unit="deg")
            )
        except Exception as exc:
            self._append_message(f"Angle must be a valid angle: {exc}")
            return

        success, result, steps_completed = self._prescribe_relative_body_angle_progressively(
            constraint_key=f"relative_body_angle:{body_a1.id}:{body_b1.id}",
            body_a_id=body_a1.id,
            body_b_id=body_b1.id,
            local_phi_a=local_phi_a,
            local_phi_b=local_phi_b,
            target_angle=target_angle_rad,
        )
        if success:
            if steps_completed > 1:
                self._append_message(f"Relative angle prescribed in {steps_completed} intermediate steps")
            else:
                self._append_message("Relative angle prescribed")
            for warning in result.warnings:
                self._append_message(f"Pose warning: {warning}")
        else:
            detail = f": {result.error}" if result.error else ""
            self._append_message(f"Relative angle prescription failed{detail}")

    def _current_relative_body_angle(
        self,
        pose,
        body_a_id: str,
        body_b_id: str,
        fallback_a_angle: float,
        fallback_b_angle: float,
        local_phi_a: float,
        local_phi_b: float,
    ) -> float:
        body_a_angle = pose.body_poses[body_a_id].angle if pose and body_a_id in pose.body_poses else fallback_a_angle
        body_b_angle = pose.body_poses[body_b_id].angle if pose and body_b_id in pose.body_poses else fallback_b_angle
        relative = (body_a_angle + local_phi_a) - (body_b_angle + local_phi_b)
        return (relative + math.pi) % (2.0 * math.pi) - math.pi

    def _prescribe_relative_body_angle_progressively(
        self,
        constraint_key: str,
        body_a_id: str,
        body_b_id: str,
        local_phi_a: float,
        local_phi_b: float,
        target_angle: float,
    ) -> tuple[bool, PoseSolveResult, int]:
        self._ensure_pose_session()
        starting_pose = copy.deepcopy(self.app_service.get_current_pose())
        base_constraints = [
            constraint
            for key, constraint in self._pose_constraints.items()
            if key != constraint_key
        ]
        template = PoseConstraint(
            id=f"pose_rel_angle_{body_a_id}_{body_b_id}",
            kind="relative_body_angle",
            target_id=body_a_id,
            metadata={
                "body_a_id": body_a_id,
                "body_b_id": body_b_id,
                "local_phi_a": local_phi_a,
                "local_phi_b": local_phi_b,
                "angle": target_angle,
            },
        )
        assembled = assembled_reference_mechanism(self.app_service.project)
        body_a_asm = assembled.bodies.get(body_a_id)
        body_b_asm = assembled.bodies.get(body_b_id)
        if body_a_asm is None or body_b_asm is None:
            return (
                False,
                PoseSolveResult(
                    success=False,
                    error="Could not resolve bodies in assembled mechanism",
                    messages=["Progressive relative body angle solve did not start"],
                ),
                0,
            )

        max_step_rad = math.pi / 4.0
        min_step_rad = math.pi / 180.0
        tolerance_rad = 1e-5
        step_limit = max_step_rad
        steps_completed = 0
        last_result = PoseSolveResult(
            success=False,
            error="Pose solve did not start",
            messages=["Progressive relative body angle solve did not start"],
        )

        for _ in range(120):
            pose = self.app_service.get_current_pose()
            current_angle = self._current_relative_body_angle(
                pose,
                body_a_id,
                body_b_id,
                body_a_asm.angle,
                body_b_asm.angle,
                local_phi_a,
                local_phi_b,
            )
            remaining = (target_angle - current_angle + math.pi) % (2.0 * math.pi) - math.pi

            if abs(remaining) <= tolerance_rad:
                final_constraint = copy.deepcopy(template)
                last_result = self.app_service.solve_current_pose(
                    temporary_constraints=[*base_constraints, final_constraint],
                    settings=PoseSolveSettings(),
                )
                if last_result.success:
                    self._pose_constraints[constraint_key] = final_constraint
                    self._store_pose_constraints_for_current_pose()
                    self._apply_current_frame()
                    self._populate_inspector()
                    return True, last_result, steps_completed
                if step_limit <= min_step_rad:
                    break
                step_limit *= 0.5
                continue

            step_angle = (
                target_angle
                if abs(remaining) <= step_limit
                else current_angle + math.copysign(step_limit, remaining)
            )
            working_constraint = copy.deepcopy(template)
            working_constraint.metadata["angle"] = step_angle
            last_result = self.app_service.solve_current_pose(
                temporary_constraints=[*base_constraints, working_constraint],
                settings=PoseSolveSettings(tolerance=1e-7, max_iterations=40),
            )
            if last_result.success:
                new_pose = self.app_service.get_current_pose()
                new_angle = self._current_relative_body_angle(
                    new_pose,
                    body_a_id,
                    body_b_id,
                    body_a_asm.angle,
                    body_b_asm.angle,
                    local_phi_a,
                    local_phi_b,
                )
                advanced = (new_angle - current_angle + math.pi) % (2.0 * math.pi) - math.pi
                if abs(advanced) <= tolerance_rad and abs(remaining) > tolerance_rad:
                    if step_limit <= min_step_rad:
                        last_result = PoseSolveResult(
                            success=False,
                            error="Pose solve stalled before reaching the prescribed relative angle",
                            messages=["Progressive relative body angle solve stalled"],
                        )
                        break
                    step_limit *= 0.5
                    continue
                steps_completed += 1
                self._apply_current_frame()
                self._populate_inspector()
                QtWidgets.QApplication.processEvents()
                continue

            if step_limit <= min_step_rad:
                break
            step_limit *= 0.5

        if starting_pose is not None:
            self.app_service.set_current_pose(starting_pose)
            self._apply_current_frame()
            self._populate_inspector()
        return False, last_result, steps_completed

    def _prescribe_body_angle_progressively(
        self,
        constraint_key: str,
        body_id: str,
        target_angle: float,
    ) -> tuple[bool, "PoseSolveResult", int]:
        self._ensure_pose_session()
        starting_pose = copy.deepcopy(self.app_service.get_current_pose())
        base_constraints = [
            c for key, c in self._pose_constraints.items() if key != constraint_key
        ]
        max_step_rad = math.pi / 4.0
        min_step_rad = math.pi / 180.0
        tolerance_rad = 1e-5
        step_limit = max_step_rad
        steps_completed = 0
        last_result = PoseSolveResult(
            success=False,
            error="Pose solve did not start",
            messages=["Progressive body angle solve did not start"],
        )

        for _ in range(120):
            pose = self.app_service.get_current_pose()
            body_pose_state = pose.body_poses.get(body_id) if pose is not None else None
            if body_pose_state is None:
                break
            current_angle = body_pose_state.angle
            remaining = target_angle - current_angle
            remaining = (remaining + math.pi) % (2 * math.pi) - math.pi

            if abs(remaining) <= tolerance_rad:
                final_constraint = PoseConstraint(
                    id=f"pose_body_angle_{body_id}",
                    kind="body_angle",
                    target_id=body_id,
                    metadata={"angle": target_angle},
                )
                last_result = self.app_service.solve_current_pose(
                    temporary_constraints=[*base_constraints, final_constraint],
                    settings=PoseSolveSettings(),
                )
                if last_result.success:
                    self._pose_constraints[constraint_key] = final_constraint
                    self._store_pose_constraints_for_current_pose()
                    self._apply_current_frame()
                    self._populate_inspector()
                    return True, last_result, steps_completed
                accepted, fallback_result, fallback_steps = self._accept_kinematic_body_angle_pose(
                    constraint_key,
                    body_id,
                    target_angle,
                    tolerance_rad,
                    steps_completed,
                )
                if accepted:
                    return True, fallback_result, fallback_steps
                if step_limit <= min_step_rad:
                    break
                step_limit *= 0.5
                continue

            step_angle = (
                target_angle
                if abs(remaining) <= step_limit
                else current_angle + math.copysign(step_limit, remaining)
            )
            working_constraint = PoseConstraint(
                id=f"pose_body_angle_{body_id}",
                kind="body_angle",
                target_id=body_id,
                metadata={"angle": step_angle},
            )
            saved_step_pose = copy.deepcopy(self.app_service.get_current_pose())
            if self._seed_pose_toward_body_angle(body_id, step_angle, base_constraints):
                steps_completed += 1
                if abs(target_angle - step_angle) <= tolerance_rad:
                    accepted, fallback_result, fallback_steps = self._accept_kinematic_body_angle_pose(
                        constraint_key,
                        body_id,
                        target_angle,
                        tolerance_rad,
                        steps_completed,
                    )
                    if accepted:
                        return True, fallback_result, fallback_steps
                self._apply_current_frame()
                self._populate_inspector()
                QtWidgets.QApplication.processEvents()
                continue
            if saved_step_pose is not None:
                self.app_service.set_current_pose(saved_step_pose)
            last_result = self.app_service.solve_current_pose(
                temporary_constraints=[*base_constraints, working_constraint],
                settings=PoseSolveSettings(tolerance=1e-7, max_iterations=40),
            )
            if last_result.success:
                new_pose = self.app_service.get_current_pose()
                new_angle = new_pose.body_poses[body_id].angle
                if abs(new_angle - current_angle) <= tolerance_rad and abs(remaining) > tolerance_rad:
                    if step_limit <= min_step_rad:
                        last_result = PoseSolveResult(
                            success=False,
                            error="Pose solve stalled before reaching the prescribed angle",
                            messages=["Progressive body angle solve stalled"],
                        )
                        break
                    step_limit *= 0.5
                    continue
                steps_completed += 1
                self._apply_current_frame()
                QtWidgets.QApplication.processEvents()
            else:
                if step_limit <= min_step_rad:
                    break
                step_limit *= 0.5
                self.app_service.set_current_pose(pose)
                self._apply_current_frame()
                self._populate_inspector()
                QtWidgets.QApplication.processEvents()
                continue

        if starting_pose is not None:
            self.app_service.set_current_pose(starting_pose)
            self._apply_current_frame()
            self._populate_inspector()
        return False, last_result, steps_completed

    def _solve_pose_with_drag(self, marker_id: str, x: float, y: float, *, final: bool) -> None:
        self._ensure_pose_session()
        project = self.app_service.project
        if project is None:
            return
        saved_pose = self.app_service.get_current_pose()
        if saved_pose is None:
            return
        try:
            assembled = self.app_service.simulation_runner.adapter.assembler.assemble(project)
        except Exception:
            return

        base_constraints = self._pose_constraints_for_drag(marker_id)
        prescribed_axes = {
            ("x" if float(constraint.metadata.get("axis_x", 0.0)) else "y")
            for constraint in base_constraints
            if constraint.kind == "marker_projected_coordinate" and constraint.target_id == marker_id
        }
        fixed_angles = {
            c.target_id: float(c.metadata["angle"])
            for c in base_constraints
            if c.kind == "body_angle" and "angle" in c.metadata
        }

        # Find the kinematic driver and build an initial-guess pose.
        driver_info = None if prescribed_axes else get_drag_driver(assembled, saved_pose, marker_id, x, y, fixed_angles=fixed_angles)
        drag_constraint: PoseConstraint
        use_body_angle = False
        if prescribed_axes == {"x", "y"}:
            return
        if prescribed_axes:
            free_axis = "y" if "x" in prescribed_axes else "x"
            drag_constraint = PoseConstraint(
                id=f"pose_drag_{marker_id}_{free_axis}",
                kind="marker_projected_coordinate",
                target_id=marker_id,
                metadata={
                    "reference_x": 0.0,
                    "reference_y": 0.0,
                    "axis_x": 1.0 if free_axis == "x" else 0.0,
                    "axis_y": 0.0 if free_axis == "x" else 1.0,
                    "value": x if free_axis == "x" else y,
                },
            )
        elif driver_info is not None:
            driver_body_id, driver_angle, guess_pose = driver_info
            driver_body = assembled.bodies.get(driver_body_id)
            marker_on_driver = driver_body is not None and marker_id in driver_body.markers
            # The kinematic propagator does not close loops, so its guess is only
            # trustworthy when the dragged marker lives on the driver body (open
            # chain or driver-body marker). For couplers in four-bar / slider-crank
            # we keep the last solved pose and let Exudyn close the loop via spring.
            use_body_angle = marker_on_driver and has_ground_revolute(assembled, driver_body_id)
            if use_body_angle:
                self.app_service.set_current_pose(guess_pose)
                drag_constraint = PoseConstraint(
                    id=f"pose_drag_{marker_id}",
                    kind="body_angle",
                    target_id=driver_body_id,
                    metadata={"angle": driver_angle},
                )
            else:
                drag_constraint = PoseConstraint(
                    id=f"pose_drag_{marker_id}",
                    kind="marker_position",
                    target_id=marker_id,
                    metadata={"x": x, "y": y},
                )
        else:
            drag_constraint = PoseConstraint(
                id=f"pose_drag_{marker_id}",
                kind="marker_position",
                target_id=marker_id,
                metadata={"x": x, "y": y},
            )

        result = self.app_service.solve_current_pose(
            temporary_constraints=[*base_constraints, drag_constraint],
            settings=PoseSolveSettings(
                tolerance=1e-8 if final else 1e-4,
                max_iterations=50 if final else 40,
                verbose=False,
            ),
        )

        if not result.success:
            # Restore the last good pose so no stretched bars are ever displayed.
            # Exception: if Exudyn is simply not installed, the kinematic estimate
            # is still better than the saved pose for single-DOF open chains.
            if self.app_service.pose_runner.backend_available():
                self.app_service.set_current_pose(saved_pose)

        self._apply_current_frame()
        if final:
            self._populate_inspector()
        if not result.success and final:
            detail = f": {result.error}" if result.error else ""
            self._append_message(f"Pose drag solve failed{detail}")

    def _on_canvas_mode_changed(self, mode: str) -> None:
        action_for_mode = {
            CanvasMode.SELECT: self.action_select_tool,
            CanvasMode.CREATE_BAR: self.action_bar_tool,
            CanvasMode.CREATE_POINT_MASS: self.action_point_mass_tool,
            CanvasMode.CREATE_BODY: self.action_body_tool,
            CanvasMode.ADD_MARKER: self.action_add_marker_tool,
            CanvasMode.CREATE_REVOLUTE: self.action_joint_tool,
            CanvasMode.CREATE_RIGID: self.action_rigid_joint_tool,
            CanvasMode.CREATE_SLIDER: self.action_slider_tool,
            CanvasMode.CONNECT_GROUND: self.action_ground_tool,
            CanvasMode.CONNECT_SLIDER: self.action_slider_connect_tool,
            CanvasMode.CREATE_SKETCH_POINT: self.action_sketch_point_tool,
            CanvasMode.CREATE_SKETCH_LINE_SEGMENT: self.action_sketch_line_tool,
            CanvasMode.CREATE_SKETCH_RECTANGLE: self.action_sketch_rectangle_tool,
            CanvasMode.CREATE_SKETCH_CIRCLE: self.action_sketch_circle_tool,
            CanvasMode.CREATE_SKETCH_ARC_CENTER: self.action_sketch_arc_tool,
            CanvasMode.CREATE_SKETCH_INFINITE_LINE: self.action_sketch_infinite_line_tool,
            CanvasMode.CREATE_SKETCH_FIX: self.action_sketch_fix_tool,
            CanvasMode.CREATE_SKETCH_HORIZONTAL: self.action_sketch_horizontal_tool,
            CanvasMode.CREATE_SKETCH_VERTICAL: self.action_sketch_vertical_tool,
            CanvasMode.CREATE_SKETCH_DISTANCE: self.action_sketch_distance_tool,
            CanvasMode.CREATE_SKETCH_HORIZONTAL_DISTANCE: self.action_sketch_horizontal_distance_tool,
            CanvasMode.CREATE_SKETCH_VERTICAL_DISTANCE: self.action_sketch_vertical_distance_tool,
            CanvasMode.CREATE_SKETCH_COINCIDENT: self.action_sketch_coincident_tool,
            CanvasMode.CREATE_SKETCH_PARALLEL: self.action_sketch_parallel_tool,
            CanvasMode.CREATE_SKETCH_PERPENDICULAR: self.action_sketch_perpendicular_tool,
            CanvasMode.CREATE_SKETCH_EQUAL_LENGTH: self.action_sketch_equal_length_tool,
            CanvasMode.CREATE_SKETCH_ANGLE: self.action_sketch_angle_tool,
            CanvasMode.CREATE_SKETCH_MIDPOINT: self.action_sketch_midpoint_tool,
            CanvasMode.CREATE_SKETCH_COLLINEAR: self.action_sketch_collinear_tool,
            CanvasMode.CREATE_SKETCH_SYMMETRIC: self.action_sketch_symmetric_tool,
            CanvasMode.CREATE_SKETCH_TANGENT: self.action_sketch_tangent_tool,
            CanvasMode.CREATE_SKETCH_CONCENTRIC: self.action_sketch_concentric_tool,
            CanvasMode.CREATE_SKETCH_ARC_CENTER: self.action_sketch_arc_center_tool,
            CanvasMode.CREATE_ROTATION_DRIVER: self.action_add_rotation_driver,
            CanvasMode.CREATE_TRANSLATION_DRIVER: self.action_add_translation_driver,
            CanvasMode.CREATE_POINT_SENSOR: self.action_point_sensor,
            CanvasMode.CREATE_DISTANCE_SENSOR: self.action_distance_sensor,
            CanvasMode.CREATE_ANGLE_HORIZONTAL_SENSOR: self.action_angle_h_sensor,
            CanvasMode.CREATE_ANGLE_VERTICAL_SENSOR: self.action_angle_v_sensor,
            CanvasMode.CREATE_ANGLE_VECTOR_SENSOR: self.action_angle_vector_sensor,
            CanvasMode.CREATE_LOAD: self.action_add_load,
            CanvasMode.CREATE_LINEAR_SPRING: self.action_add_linear_spring,
            CanvasMode.CREATE_ROTATIONAL_SPRING: self.action_add_rotational_spring,
            CanvasMode.CREATE_LINEAR_ACTUATOR: self.action_add_linear_actuator,
            CanvasMode.CREATE_ROTATIONAL_ACTUATOR: self.action_add_rotational_actuator,
        }.get(mode)
        if action_for_mode:
            if action_for_mode in self.tool_group.actions():
                action_for_mode.setChecked(True)
            else:
                # Para botones que no están en tool_group (como drivers)
                action_for_mode.setChecked(True)
        if mode != CanvasMode.POSE_PICK and self._active_prescribe_action is not None:
            self._active_prescribe_action.setChecked(False)
            self._active_prescribe_action = None
            if self._pose_pick_state is not None:
                self._pose_pick_state = None
                self.canvas.set_pose_pick_preview(None, [])
                self._append_message("Cancelled")
        self._update_status_message()

    def _on_dof_info_changed(self, text: str) -> None:
        self._last_dof_info = text
        self._update_status_message()

    def _set_canvas_mode(self, mode: str) -> None:
        if mode != CanvasMode.SELECT and not self._editing_allowed():
            self._append_message("Editing is only available at t=0")
            self.action_select_tool.setChecked(True)
            self.canvas.set_mode(CanvasMode.SELECT)
            self._update_status_message()
            return
        self.canvas.set_mode(mode)
        self._update_status_message()

    def _populate_inspector(self) -> None:
        self._suspend_property_updates = True
        try:
            self.inspector.clear_properties()
            self.inspector_title.setText("")
            # clear old relation widgets
            while self.relations_vbox.count() > 1:  # keep trailing stretch
                child = self.relations_vbox.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            if not self._selected_entity_id:
                return

            # --- Block diagram support ---
            if isinstance(self._selected_entity_id, tuple):
                selection = self._selected_entity_id
                if selection[0] == "block_connection" and len(selection) == 5:
                    _, src_instance, src_port, dst_instance, dst_port = selection
                    self.inspector_title.setText("<b>Block connection</b>")
                    self.inspector.add_property("source", "connection/source", f"{src_instance}.{src_port}", "readonly", f"{src_instance}.{src_port}", enabled=False)
                    self.inspector.add_property("target", "connection/target", f"{dst_instance}.{dst_port}", "readonly", f"{dst_instance}.{dst_port}", enabled=False)
                    self.inspector.layout.addStretch()
                return
            project = self.app_service.display_project
            block = None
            if project is not None and project.model.control_graph is not None:
                block = project.model.control_graph.instances.get(self._selected_entity_id)
            if block is not None:
                self._populate_block_inspector(block, project)
                self._inject_case_override_hints(self._selected_entity_id)
                return

            entity = self.app_service.get_entity(self._selected_entity_id)
            if entity is None:
                return

            # --- title ---
            name = getattr(entity, "name", "")
            kind_label = self._entity_kind_label(entity)
            icon_name = self._KIND_ICON.get(getattr(getattr(entity, "type", None), "value", ""), "")
            if not icon_name:
                icon_name = self._entity_default_icon(entity)
            icon_html = ""
            if icon_name:
                svg_path = Path(__file__).parent / "icons" / f"{icon_name}.svg"
                if svg_path.exists():
                    icon_html = f'<img src="{svg_path}" width="16" height="16" style="vertical-align:middle"/> '
            self.inspector_title.setText(
                f'{icon_html}<b>{name}</b> &nbsp;<span style="color:#888;font-weight:normal">{kind_label}</span>'
            )

            # --- property rows (using new widget) ---
            prop_rows = self._inspector_rows(entity)
            for label, path, value, kind, evaluated, _ in prop_rows:
                is_pose_field = path.startswith("pose:")
                if is_pose_field:
                    # Pose-scoped fields (e.g. driver initial velocity) are
                    # editable in pose mode but locked elsewhere.
                    enabled = self._app_mode == "pose" and kind not in {"readonly", "key", "section_header"}
                else:
                    enabled = self._editing_allowed() and self._app_mode != "pose" and kind not in {"readonly", "key", "section_header"}
                self.inspector.add_property(label, path, value, kind, evaluated, enabled)
            self.inspector.layout.addStretch()

            # --- inject baseline/inherited hints for case-overridden properties ---
            self._inject_case_override_hints(self._selected_entity_id)

            # --- markers section for Body/Bar (consolidated with reordering) ---
            if isinstance(entity, Body) and entity.markers:
                visible_markers = [m for m in entity.markers if m.visible or m.type.value != "com"]
                if visible_markers:
                    markers_label = QtWidgets.QLabel("Markers")
                    markers_font = markers_label.font()
                    markers_font.setPointSize(markers_font.pointSize() - 1)
                    markers_label.setFont(markers_font)
                    markers_label.setStyleSheet("color: #888; margin-top: 6px;")
                    markers_label.setContentsMargins(0, 4, 0, 0)
                    self.relations_vbox.insertWidget(self.relations_vbox.count() - 1, markers_label)

                    reorderable_ids = set(entity.edge_order) if entity.edge_order else set()

                    # Build ordered list: reorderable markers first (in edge_order), then rest
                    ordered_markers: list[tuple[int, object]] = []
                    if entity.edge_order:
                        for idx, marker_id in enumerate(entity.edge_order):
                            marker = next((m for m in entity.markers if m.id == marker_id), None)
                            if marker:
                                ordered_markers.append((idx, marker))
                    for marker in entity.markers:
                        if marker.id not in reorderable_ids:
                            if not marker.visible and marker.type.value == "com":
                                continue
                            ordered_markers.append((-1, marker))

                    for edge_idx, marker in ordered_markers:
                        row_w = QtWidgets.QWidget()
                        row_h = QtWidgets.QHBoxLayout(row_w)
                        row_h.setContentsMargins(0, 1, 0, 1)
                        row_h.setSpacing(5)

                        # Icon
                        icon_lbl = QtWidgets.QLabel()
                        icon_lbl.setPixmap(get_icon("marker", size=13).pixmap(13, 13))
                        icon_lbl.setFixedSize(16, 16)
                        icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                        row_h.addWidget(icon_lbl)

                        # Clickable name + coords
                        coords = self._evaluate_scalar(marker.x) + " / " + self._evaluate_scalar(marker.y)
                        text = f"{marker.name}  <span style='color:#999'>{coords}</span>"
                        text_lbl = QtWidgets.QLabel(text)
                        text_lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
                        text_lbl.setStyleSheet("color: #1a4a8a;")
                        text_lbl.setToolTip("Double-click to select")
                        text_lbl.mouseDoubleClickEvent = (
                            lambda _ev, eid=marker.id: self._select_entity_by_id(eid)
                        )
                        row_h.addWidget(text_lbl, stretch=1)

                        # Up/Down buttons for structural reorderable markers
                        if edge_idx >= 0 and marker.type is MarkerType.STRUCTURAL:
                            up_btn = QtWidgets.QPushButton("↑")
                            up_btn.setFixedWidth(28)
                            up_btn.setFixedHeight(20)
                            up_btn.setEnabled(self._editing_allowed() and self._app_mode != "pose" and edge_idx > 0)
                            up_btn.clicked.connect(lambda checked=False, mid=marker.id: self._on_marker_reorder(mid, -1))
                            row_h.addWidget(up_btn)

                            down_btn = QtWidgets.QPushButton("↓")
                            down_btn.setFixedWidth(28)
                            down_btn.setFixedHeight(20)
                            down_btn.setEnabled(self._editing_allowed() and self._app_mode != "pose" and edge_idx < len(entity.edge_order) - 1)
                            down_btn.clicked.connect(lambda checked=False, mid=marker.id: self._on_marker_reorder(mid, 1))
                            row_h.addWidget(down_btn)

                        self.relations_vbox.insertWidget(self.relations_vbox.count() - 1, row_w)

            # --- relations below the table ---
            relations = self._inspector_relations(entity)
            if relations:
                current_group: str | None = None
                for group, rel_icon, display, detail, ent_id in relations:
                    if group != current_group:
                        current_group = group
                        grp_label = QtWidgets.QLabel(group)
                        grp_font = grp_label.font()
                        grp_font.setPointSize(grp_font.pointSize() - 1)
                        grp_label.setFont(grp_font)
                        grp_label.setStyleSheet("color: #888; margin-top: 6px;")
                        grp_label.setContentsMargins(0, 4, 0, 0)
                        self.relations_vbox.insertWidget(self.relations_vbox.count() - 1, grp_label)

                    row_w = QtWidgets.QWidget()
                    row_h = QtWidgets.QHBoxLayout(row_w)
                    row_h.setContentsMargins(0, 1, 0, 1)
                    row_h.setSpacing(5)

                    if rel_icon:
                        icon_lbl = QtWidgets.QLabel()
                        icon_lbl.setPixmap(get_icon(rel_icon, size=13).pixmap(13, 13))
                        icon_lbl.setFixedSize(16, 16)
                        icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                        row_h.addWidget(icon_lbl)

                    text = f"{display}  <span style='color:#999'>{detail}</span>" if detail else display
                    text_lbl = QtWidgets.QLabel(text)
                    text_lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
                    if ent_id:
                        text_lbl.setStyleSheet("color: #1a4a8a;")
                        text_lbl.setToolTip("Double-click to select")
                        text_lbl.setProperty("nav_entity_id", ent_id)
                        text_lbl.mouseDoubleClickEvent = (
                            lambda _ev, eid=ent_id: self._select_entity_by_id(eid)
                        )
                    row_h.addWidget(text_lbl, stretch=1)
                    self.relations_vbox.insertWidget(self.relations_vbox.count() - 1, row_w)
        finally:
            self._suspend_property_updates = False

    def _entity_kind_label(self, entity: object) -> str:
        type_val = getattr(getattr(entity, "type", None), "value", None)
        if type_val:
            return type_val.replace("_", " ")
        if isinstance(entity, Body):
            return "body"
        if isinstance(entity, Marker):
            return "marker"
        if isinstance(entity, Slider):
            return "slider"
        if isinstance(entity, Joint):
            return "joint"
        if isinstance(entity, Driver):
            return "driver"
        if isinstance(entity, Sensor):
            return "sensor"
        if isinstance(entity, Spring):
            return "spring"
        if isinstance(entity, Parameter):
            return "parameter"
        if isinstance(entity, Sketch):
            return "sketch"
        if isinstance(entity, SketchConstraint):
            return "constraint"
        if isinstance(entity, SketchPoint):
            return "point"
        if isinstance(entity, GravityLoad):
            return "gravity"
        if isinstance(entity, ReactionOutput):
            return "reaction"
        return ""

    def _entity_default_icon(self, entity: object) -> str:
        if isinstance(entity, Body):
            return "body"
        if isinstance(entity, Marker):
            return "marker"
        if isinstance(entity, Slider):
            return "slider"
        if isinstance(entity, Joint):
            return "revolute"
        if isinstance(entity, Driver):
            return "rotate-driver"
        if isinstance(entity, Sensor):
            return "sensor-point"
        if isinstance(entity, Spring):
            return "spring"
        if isinstance(entity, SketchPoint):
            return "sketch-point"
        if isinstance(entity, SketchLineSegment):
            return "sketch-line"
        if isinstance(entity, SketchCircle):
            return "sketch-circle"
        if isinstance(entity, SketchArc):
            return "sketch-arc"
        if isinstance(entity, SketchInfiniteLine):
            return "sketch-infinite-line"
        if isinstance(entity, ReactionOutput):
            return "sensor-point"
        if isinstance(entity, SketchConstraint):
            return {
                "fix": "constraint-fix",
                "horizontal": "constraint-horizontal",
                "vertical": "constraint-vertical",
                "distance": "constraint-distance",
                "horizontal_distance": "constraint-horizontal",
                "vertical_distance": "constraint-vertical",
                "coincident": "constraint-coincident",
            }.get(entity.type.value, "constraint-distance")
        return ""

    def _on_tree_item_double_clicked(self, item: QtWidgets.QTreeWidgetItem, _col: int) -> None:
        entity_id = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if entity_id:
            self._select_entity_by_id(entity_id)
            self.canvas.center_on_entity(entity_id)

    def _on_tree_visibility_toggled(self, entity_id: str) -> None:
        """Handle visibility toggle via right-click on tree item."""
        project = self.app_service.project
        if project is None:
            return
        entity = self.app_service.get_entity(entity_id)
        if entity is None:
            return
        # Toggle visibility
        if hasattr(entity, "visible"):
            from quino.domain.inputs import PropertyValueInput
            try:
                self.app_service.update_property(entity_id, "visible", PropertyValueInput("boolean", not entity.visible))
                self._mark_project_dirty()
                self.refresh_all()
            except Exception as e:
                self._append_message(f"Cannot toggle visibility: {e}")

    def _on_marker_reorder(self, marker_id: str, direction: int) -> None:
        """Reorder markers in a body by swapping positions in edge_order."""
        if not self._selected_entity_id:
            return
        body = self.app_service.get_entity(self._selected_entity_id)
        if not isinstance(body, Body) or not body.edge_order:
            return
        try:
            idx = body.edge_order.index(marker_id)
            new_idx = idx + direction
            if 0 <= new_idx < len(body.edge_order):
                # Swap the markers in edge_order
                body.edge_order[idx], body.edge_order[new_idx] = body.edge_order[new_idx], body.edge_order[idx]
                self._mark_project_dirty()
                self.refresh_all()
        except (ValueError, IndexError):
            pass

    def _inspector_rows(self, entity: object) -> list[tuple[str, str, str, str, str, str | None]]:
        # Returns prop rows only: (label, path, value, kind, evaluated, None)
        rows: list[tuple[str, str, str, str, str, str | None]] = []

        def prop(label, path, value, kind, evaluated):
            rows.append((label, path, value, kind, evaluated, None))

        if isinstance(entity, (Body, Marker, Slider, Joint, Driver, Sensor, Load, Parameter, SketchPoint, SketchLineSegment, SketchCircle, SketchArc, SketchInfiniteLine, SketchConstraint)):
            prop("name", "name", entity.name, "expression", entity.name)

        if isinstance(entity, Body):
            prop("closed_shape", "closed_shape", str(entity.closed_shape).lower(), "boolean", str(entity.closed_shape).lower())
            prop("mass", "mass", entity.mass.expression if entity.mass else "", "expression_or_null", self._evaluate_scalar(entity.mass))
            # CoM controls (derived from the body's anchor)
            anchor = entity.com
            if anchor.kind == "bar_percent":
                percent = float(anchor.data.get("percent", 50.0))
                prop("CoM %", "position_percent", f"{percent:.6g}", "expression", f"{percent:.6g} %")
            elif anchor.kind == "local_offset":
                prop("CoM Lx", "com_offset_x", f"{float(anchor.data.get('lx', 0.0)):.6g}", "readonly", f"{float(anchor.data.get('lx', 0.0)):.6g} mm")
                prop("CoM Ly", "com_offset_y", f"{float(anchor.data.get('ly', 0.0)):.6g}", "readonly", f"{float(anchor.data.get('ly', 0.0)):.6g} mm")
            elif anchor.kind == "barycentric":
                weights = anchor.data.get("weights", {}) or {}
                prop("CoM kind", "_com_kind", "barycentric", "readonly", f"{len(weights)} weights")
            elif anchor.kind == "marker":
                prop("CoM (locked)", "_com_marker", str(anchor.data.get("marker_id", "")), "readonly", "marker")
            prop("color", "style.color", entity.style.color, "color", entity.style.color)
            prop("line width", "style.line_width", str(entity.style.line_width), "expression", str(entity.style.line_width))

        elif isinstance(entity, Marker):
            body = self.app_service.get_body_by_marker(entity.id)
            if entity.type is MarkerType.COM and body is not None and body.type.value == "point_mass":
                prop("x", "x", entity.x.expression, "readonly", self._evaluate_scalar(entity.x))
                prop("y", "y", entity.y.expression, "readonly", self._evaluate_scalar(entity.y))
            elif entity.type is MarkerType.COM and body is not None and body.type.value == "bar":
                percent = self.app_service._bar_com_percent(body)
                length = self.app_service._bar_length(body)
                distance = length * percent / 100.0
                prop("position_percent", "position_percent", f"{percent:.6g}", "expression", f"{percent:.6g} %")
                prop("position_distance", "position_distance", f"{distance:.6g} mm", "expression", f"{distance:.6g} mm")
                prop("x", "x", entity.x.expression, "readonly", self._evaluate_scalar(entity.x))
                prop("y", "y", entity.y.expression, "readonly", self._evaluate_scalar(entity.y))
            else:
                prop("x", "x", entity.x.expression, "expression", self._evaluate_scalar(entity.x))
                prop("y", "y", entity.y.expression, "expression", self._evaluate_scalar(entity.y))
            prop("visible", "visible", str(entity.visible).lower(), "boolean", str(entity.visible).lower())

        elif isinstance(entity, Slider):
            prop("origin_x", "origin_x", entity.origin_x.expression, "expression", self._evaluate_scalar(entity.origin_x))
            prop("origin_y", "origin_y", entity.origin_y.expression, "expression", self._evaluate_scalar(entity.origin_y))
            prop("angle", "angle", entity.angle.expression, "expression", self._evaluate_scalar(entity.angle))
            prop("travel_min", "travel_min", entity.travel_min.expression if entity.travel_min else "", "expression_or_null", self._evaluate_scalar(entity.travel_min))
            prop("travel_max", "travel_max", entity.travel_max.expression if entity.travel_max else "", "expression_or_null", self._evaluate_scalar(entity.travel_max))

        elif isinstance(entity, Joint):
            prop("type", "", entity.type.value, "readonly", entity.type.value)
            if self.app_service.joint_supports_angular_limits(entity):
                positive, negative = self.app_service.joint_angular_limit_values(entity)
                prop(
                    "angle_limit_positive",
                    "angle_limit_positive",
                    "" if positive is None else f"{positive:.6g} deg",
                    "expression_or_null",
                    "(unrestricted)" if positive is None else f"{positive:.6g} deg",
                )
                prop(
                    "angle_limit_negative",
                    "angle_limit_negative",
                    "" if negative is None else f"{negative:.6g} deg",
                    "expression_or_null",
                    "(unrestricted)" if negative is None else f"{negative:.6g} deg",
                )
            friction_mode = self.app_service.joint_friction_mode(entity)
            if friction_mode == "rotation":
                coulomb, viscous = self.app_service.joint_friction_values(entity)
                pin_r = self.app_service.joint_friction_pin_radius(entity)
                prop("friction_pin_radius", "friction_pin_radius", f"{pin_r:.6g} mm", "expression", f"{pin_r:.6g} mm")
                prop("friction_coulomb", "friction_coulomb", f"{coulomb:.6g}", "expression", f"{coulomb:.6g}")
                prop("friction_viscous", "friction_viscous", f"{viscous:.6g}", "expression", f"{viscous:.6g}")
                if pin_r > 1e-12:
                    prop("— formula", "", "T = μ·‖F_rótula‖·r_pin·sign(ω) + c·ω  [N·m]", "readonly", "")
                else:
                    prop("— formula", "", "T = T_coulomb·sign(ω) + c·ω  [N·m]  (sin radio → par cte.)", "readonly", "")
            elif friction_mode == "translation":
                coulomb, viscous = self.app_service.joint_friction_values(entity)
                prop("friction_coulomb", "friction_coulomb", f"{coulomb:.6g}", "expression", f"{coulomb:.6g}")
                prop("friction_viscous", "friction_viscous", f"{viscous:.6g}", "expression", f"{viscous:.6g}")
                prop("— formula", "", "F = μ·|F_normal|·sign(v) + c·v  [N]", "readonly", "")

        elif isinstance(entity, Driver):
            prop("type", "", entity.type.value, "readonly", entity.type.value)
            prop("law", "law", entity.law.expression, "expression", self._evaluate_scalar(entity.law, with_time=True))
            if self._app_mode == "pose":
                vel_unit = "rad/s" if entity.type is DriverType.ROTATION else "m/s"
                stored = self.app_service.get_driver_initial_velocity(entity.id)
                # Display empty when unset; otherwise as a SI quantity.
                display = "" if stored is None else f"{stored:g} {vel_unit}"
                evaluated = "(unset)" if stored is None else f"{stored:g} {vel_unit}"
                prop(
                    f"initial velocity (this pose, {vel_unit})",
                    "pose:initial_velocity",
                    display,
                    "expression_or_null",
                    evaluated,
                )

        elif isinstance(entity, Load):
            prop("target_marker_id", "", entity.target_marker_id, "readonly", entity.target_marker_id)
            prop("fx", "fx", entity.fx.expression, "expression", self._evaluate_scalar(entity.fx, with_time=True))
            prop("fy", "fy", entity.fy.expression, "expression", self._evaluate_scalar(entity.fy, with_time=True))

        elif isinstance(entity, Sensor):
            prop("type", "", entity.type.value, "readonly", entity.type.value)
            safe = safe_sensor_var(entity.name)
            channels = sensor_channel_keys(entity)
            if channels:
                prop("— Expression Keys —", "", "", "section_header", "")
                for ch_suffix, ch_unit in channels:
                    key = f"{safe}.{ch_suffix}"
                    prop(key, "", f"[{ch_unit}]", "key", f"[{ch_unit}]")
            output = self.app_service.project.sensor_outputs.get(entity.id)
            if output and output.columns and output.data:
                prop("— Current Values —", "", "", "section_header", "")
                frame = max(0, min(self._current_frame_index, len(output.data) - 1))
                row_data = output.data[frame]
                t = output.time[frame] if frame < len(output.time) else 0.0
                prop("t", "", f"{t:.4g} s", "readonly", f"{t:.4g} s")
                for col_idx, col_name in enumerate(output.columns):
                    if col_idx < len(row_data):
                        val = row_data[col_idx]
                        prop(col_name, "", f"{val:.6g}", "readonly", f"{val:.6g}")

        elif isinstance(entity, Parameter):
            prop("expression", "", entity.expression, "readonly", self._evaluate_parameter(entity))
            prop("unit", "", entity.unit, "readonly", entity.unit)

        elif isinstance(entity, SketchPoint):
            prop("visible", "visible", str(entity.visible).lower(), "boolean", str(entity.visible).lower())
            prop("construction", "construction", str(entity.construction).lower(), "boolean", str(entity.construction).lower())
            prop("x", "x", entity.x.text, "expression", self._evaluate_scalar(entity.x))
            prop("y", "y", entity.y.text, "expression", self._evaluate_scalar(entity.y))

        elif isinstance(entity, SketchLineSegment):
            prop("visible", "visible", str(entity.visible).lower(), "boolean", str(entity.visible).lower())
            prop("construction", "construction", str(entity.construction).lower(), "boolean", str(entity.construction).lower())
            prop("start_point_id", "start_point_id", entity.start_point_id, "readonly", self._sketch_point_reference(entity.start_point_id))
            prop("end_point_id", "end_point_id", entity.end_point_id, "readonly", self._sketch_point_reference(entity.end_point_id))

        elif isinstance(entity, SketchCircle):
            prop("visible", "visible", str(entity.visible).lower(), "boolean", str(entity.visible).lower())
            prop("construction", "construction", str(entity.construction).lower(), "boolean", str(entity.construction).lower())
            prop("center_point_id", "center_point_id", entity.center_point_id, "readonly", self._sketch_point_reference(entity.center_point_id))
            prop("radius", "radius", entity.radius.text, "expression", self._evaluate_scalar(entity.radius))

        elif isinstance(entity, SketchArc):
            prop("visible", "visible", str(entity.visible).lower(), "boolean", str(entity.visible).lower())
            prop("construction", "construction", str(entity.construction).lower(), "boolean", str(entity.construction).lower())
            prop("center_point_id", "center_point_id", entity.center_point_id, "readonly", self._sketch_point_reference(entity.center_point_id))
            prop("start_point_id", "start_point_id", entity.start_point_id, "readonly", self._sketch_point_reference(entity.start_point_id))
            prop("end_point_id", "end_point_id", entity.end_point_id, "readonly", self._sketch_point_reference(entity.end_point_id))

        elif isinstance(entity, SketchInfiniteLine):
            prop("visible", "visible", str(entity.visible).lower(), "boolean", str(entity.visible).lower())
            prop("construction", "construction", str(entity.construction).lower(), "boolean", str(entity.construction).lower())
            prop("point_a_id", "point_a_id", entity.point_a_id, "readonly", self._sketch_point_reference(entity.point_a_id))
            prop("point_b_id", "point_b_id", entity.point_b_id, "readonly", self._sketch_point_reference(entity.point_b_id))

        elif isinstance(entity, SketchConstraint):
            prop("type", "", entity.type.value, "readonly", entity.type.value)
            if entity.value is not None:
                prop("value", "value", entity.value.expression, "expression", self._evaluate_scalar(entity.value))
            if entity.type in {
                SketchConstraintType.DISTANCE,
                SketchConstraintType.HORIZONTAL_DISTANCE,
                SketchConstraintType.VERTICAL_DISTANCE,
                SketchConstraintType.RADIUS,
            }:
                label_x, label_y = self.app_service._current_sketch_constraint_label_position(entity)
                prop("label_x", "label_x", f"{label_x:.6g} mm", "expression", f"{label_x:.6g} mm")
                prop("label_y", "label_y", f"{label_y:.6g} mm", "expression", f"{label_y:.6g} mm")

        elif isinstance(entity, Spring):
            from quino.domain.types import SpringType
            prop("type", "", entity.spring_type.value, "readonly", entity.spring_type.value)
            is_rotational = entity.spring_type in (SpringType.ROTATIONAL_SPRING, SpringType.ROTATIONAL_ACTUATOR)
            is_actuator = entity.spring_type in (SpringType.LINEAR_ACTUATOR, SpringType.ROTATIONAL_ACTUATOR)
            stiffness = float(entity.metadata.values.get("stiffness", 0.0))
            damping = float(entity.metadata.values.get("damping", 0.0))
            if is_rotational:
                prop("stiffness", "stiffness", f"{stiffness:.6g}", "expression", f"{stiffness:.6g} N·mm/rad")
                prop("damping", "damping", f"{damping:.6g}", "expression", f"{damping:.6g} N·mm·s/rad")
            else:
                prop("stiffness", "stiffness", f"{stiffness:.6g}", "expression", f"{stiffness:.6g} N/mm")
                prop("damping", "damping", f"{damping:.6g}", "expression", f"{damping:.6g} N·s/mm")
            if entity.rest_value is not None:
                prop("rest_value", "rest_value", entity.rest_value.expression, "expression", self._evaluate_scalar(entity.rest_value))
            else:
                rest_unit = "rad" if is_rotational else "mm"
                prop("rest_value", "rest_value", f"0 {rest_unit}", "expression", f"0.0 {rest_unit}")
            if is_actuator:
                if entity.law is not None:
                    prop("law", "law", entity.law.expression, "expression", self._evaluate_scalar(entity.law, with_time=True))
                else:
                    prop("law", "law", "0 N" if not is_rotational else "0 N*mm", "expression", "0.0")

        elif isinstance(entity, GravityLoad):
            prop("magnitude", "magnitude", str(entity.magnitude), "expression", str(entity.magnitude))
            prop("direction_x", "direction_x", str(entity.direction_x), "expression", str(entity.direction_x))
            prop("direction_y", "direction_y", str(entity.direction_y), "expression", str(entity.direction_y))

        elif isinstance(entity, ReactionOutput):
            prop("joint", "", entity.joint_name, "readonly", entity.joint_name)
            prop("type", "", entity.endpoint_type, "readonly", entity.endpoint_type)
            if entity.time and entity.data:
                prop("— Current Values —", "", "", "section_header", "")
                frame = max(0, min(self._current_frame_index, len(entity.data) - 1))
                row_data = entity.data[frame]
                t = entity.time[frame] if frame < len(entity.time) else 0.0
                prop("t", "", f"{t:.4g} s", "readonly", f"{t:.4g} s")
                for col_idx, col_name in enumerate(entity.columns):
                    if col_idx < len(row_data):
                        val = row_data[col_idx]
                        prop(col_name, "", f"{val:.6g}", "readonly", f"{val:.6g}")

        return rows

    # relation tuple: (group, icon_name, display, detail, entity_id | None)
    def _inspector_relations(self, entity: object) -> list[tuple[str, str, str, str, str | None]]:
        rels: list[tuple[str, str, str, str, str | None]] = []
        project = self.app_service.project

        def rel(group: str, icon: str, display: str, detail: str = "", entity_id: str | None = None):
            rels.append((group, icon, display, detail, entity_id))

        if isinstance(entity, Body):
            # Only show markers in relations if not already shown in reorderable section
            if not entity.edge_order:
                for m in entity.markers:
                    if not m.visible and m.type.value == "com":
                        continue
                    coords = self._evaluate_scalar(m.x) + " / " + self._evaluate_scalar(m.y)
                    rel("Markers", "marker", m.name, coords, m.id)

        elif isinstance(entity, Marker):
            body = self.app_service.get_body_by_marker(entity.id)
            if body is not None:
                rel("Parent Body", "body" if body.type.value == "body" else "bar", body.name, body.type.value, body.id)
            joints = [j for j in project.model.joints
                      if j.endpoint_a.marker_id == entity.id or j.endpoint_b.marker_id == entity.id]
            for j in joints:
                icon_j = self._KIND_ICON.get(j.type.value, "revolute")
                other_ep = j.endpoint_b if j.endpoint_a.marker_id == entity.id else j.endpoint_a
                if other_ep.kind.value == "ground":
                    detail = "→ Ground"
                elif other_ep.kind.value == "slider" and other_ep.slider_id:
                    sl = self.app_service.get_entity(other_ep.slider_id)
                    detail = f"→ {sl.name}" if sl is not None else "→ slider"
                elif other_ep.marker_id:
                    om = self.app_service.get_entity(other_ep.marker_id)
                    ob = self.app_service.get_body_by_marker(other_ep.marker_id)
                    detail = f"→ {ob.name}.{om.name}" if om is not None and ob is not None else "→ ?"
                else:
                    detail = ""
                rel("Joints", icon_j, j.name, detail, j.id)

        elif isinstance(entity, Joint):
            for label, ep in [("A", entity.endpoint_a), ("B", entity.endpoint_b)]:
                if ep.kind.value == "ground":
                    rel("Endpoints", "ground", f"Endpoint {label}", "Ground", None)
                elif ep.kind.value == "slider" and ep.slider_id:
                    sl = self.app_service.get_entity(ep.slider_id)
                    rel("Endpoints", "slider", f"Endpoint {label}", sl.name if sl is not None else ep.slider_id or "?", ep.slider_id)
                elif ep.marker_id:
                    om = self.app_service.get_entity(ep.marker_id)
                    ob = self.app_service.get_body_by_marker(ep.marker_id)
                    rel("Endpoints", "marker", f"Endpoint {label}", f"{ob.name}.{om.name}" if om is not None and ob is not None else ep.marker_id or "?", ep.marker_id)

        elif isinstance(entity, Driver):
            joint = self.app_service.get_joint(entity.target_joint_id)
            if joint is not None:
                icon_j = self._KIND_ICON.get(joint.type.value, "revolute")
                rel("Target Joint", icon_j, joint.name, joint.type.value, entity.target_joint_id)

        elif isinstance(entity, Spring):
            from quino.domain.types import SpringEndpointKind
            for label, ep in [("A", entity.endpoint_a), ("B", entity.endpoint_b)]:
                if ep.kind is SpringEndpointKind.GROUND:
                    rel("Endpoints", "ground", f"Endpoint {label}", "Ground", None)
                elif ep.body_id is not None and ep.marker_id is not None:
                    om = self.app_service.get_entity(ep.marker_id)
                    ob = self.app_service.get_body(ep.body_id)
                    rel("Endpoints", "marker", f"Endpoint {label}", f"{ob.name}.{om.name}" if om is not None and ob is not None else ep.marker_id, ep.marker_id)

        elif isinstance(entity, Sensor):
            for mid in (entity.marker_ids or []):
                om = self.app_service.get_entity(mid)
                ob = self.app_service.get_body_by_marker(mid)
                rel("Markers", "marker", om.name if om is not None else mid, ob.name if ob is not None else "", mid)

        elif isinstance(entity, SketchLineSegment):
            rel("Points", "sketch-point", self._sketch_point_reference(entity.start_point_id), "start", entity.start_point_id)
            rel("Points", "sketch-point", self._sketch_point_reference(entity.end_point_id), "end", entity.end_point_id)
        elif isinstance(entity, SketchCircle):
            rel("Points", "sketch-point", self._sketch_point_reference(entity.center_point_id), "center", entity.center_point_id)
        elif isinstance(entity, SketchArc):
            rel("Points", "sketch-point", self._sketch_point_reference(entity.center_point_id), "center", entity.center_point_id)
            rel("Points", "sketch-point", self._sketch_point_reference(entity.start_point_id), "start", entity.start_point_id)
            rel("Points", "sketch-point", self._sketch_point_reference(entity.end_point_id), "end", entity.end_point_id)
        elif isinstance(entity, SketchInfiniteLine):
            rel("Points", "sketch-point", self._sketch_point_reference(entity.point_a_id), "A", entity.point_a_id)
            rel("Points", "sketch-point", self._sketch_point_reference(entity.point_b_id), "B", entity.point_b_id)
        elif isinstance(entity, SketchConstraint):
            for index, point_id in enumerate(entity.references, start=1):
                rel("Points", "sketch-point", self._sketch_point_reference(point_id), f"P{index}", point_id)

        return rels

    def _sketch_point_reference(self, point_id: str) -> str:
        point = self.app_service.get_entity(point_id)
        if not isinstance(point, SketchPoint):
            return point_id
        return f"{point.name} ({point_id})"

    def _evaluate_scalar(self, scalar, with_time: bool = False) -> str:
        if scalar is None:
            return "null"
        try:
            variables = {"t": self.app_service.unit_service.quantity(0.0, "s")} if with_time else None
            if isinstance(scalar, Expression):
                quantity = self.app_service.expression_service.evaluate_expression(
                    scalar.text,
                    self.app_service.project.parameters,
                    variables=variables,
                )
                return f"{self.app_service.unit_service.convert(quantity, scalar.unit):.6g} {scalar.unit}"
            quantity = self.app_service.expression_service.evaluate_property(
                scalar,
                self.app_service.project.parameters,
                variables=variables,
            )
            return f"{quantity.value:.6g} {scalar.unit}"
        except DimensionMismatchError as exc:
            if exc.suggested_unit:
                return f"Missing unit — e.g. 1 {exc.suggested_unit}"
            return f"ERROR: {exc}"
        except Exception as exc:
            return f"ERROR: {exc}"

    def _evaluate_parameter(self, parameter: Parameter) -> str:
        try:
            quantity = self.app_service.expression_service.evaluate_expression(
                parameter.expression,
                self.app_service.project.parameters,
            )
            value = self.app_service.unit_service.convert(quantity, parameter.unit)
            return f"{value:.6g} {parameter.unit}"
        except Exception as exc:
            return f"ERROR: {exc}"

    def _on_inspector_property_changed(self, path: str, value: str, kind: str) -> None:
        """Handle property changes from the inspector widget."""
        if self._suspend_property_updates or not self._selected_entity_id:
            return
        if kind in {"readonly", "section_header", "key"}:
            return
        # Block diagram parameters (text/numeric, combos, checkbox).
        if kind in {"block_param", "block_entity_ref", "block_enum", "block_bool"}:
            if not self._editing_allowed():
                return
            try:
                parts = path.split("/")
                if len(parts) == 3:
                    instance_id = parts[1]
                    param_key = parts[2]
                    coerced: object
                    if kind == "block_bool":
                        coerced = value.lower() == "true"
                    elif kind in {"block_entity_ref", "block_enum"}:
                        # Keep string verbatim (sensor_id, channel, etc.)
                        coerced = value
                    else:
                        try:
                            coerced = float(value) if "." in value else int(value)
                        except ValueError:
                            coerced = value
                    self.app_service.set_block_parameter(instance_id, param_key, coerced)
                    self._mark_project_dirty()
            except Exception as exc:  # pragma: no cover - UI feedback
                self._append_message(f"Block parameter update failed: {exc}")
            self.refresh_all()
            return
        # Pose-scoped fields are handled separately so they remain editable in
        # pose mode even though the rest of the model is locked.
        if path.startswith("pose:"):
            if self._app_mode != "pose":
                return
            try:
                self._apply_pose_property_update(self._selected_entity_id, path, value)
                self._mark_project_dirty()
            except Exception as exc:  # pragma: no cover - UI feedback
                self._append_message(f"Pose property update failed: {exc}")
            self.refresh_all()
            return
        if not self._editing_allowed() or self._app_mode == "pose":
            return
        try:
            self._apply_property_update(self._selected_entity_id, path, value, kind)
            self._mark_project_dirty()
        except Exception as exc:  # pragma: no cover - UI feedback
            self._append_message(f"Property update failed: {exc}")
        self.refresh_all()

    def _apply_pose_property_update(self, entity_id: str, path: str, raw_value: str) -> None:
        entity = self.app_service.get_entity(entity_id)
        if entity is None:
            return
        if path == "pose:initial_velocity" and isinstance(entity, Driver):
            text = raw_value.strip()
            if not text:
                self.app_service.set_driver_initial_velocity(entity_id, None)
                return
            target_unit = "rad/s" if entity.type is DriverType.ROTATION else "m/s"
            quantity = self.app_service.expression_service.evaluate_expression(
                text, self.app_service.project.parameters
            )
            si_value = self.app_service.unit_service.convert(quantity, target_unit)
            self.app_service.set_driver_initial_velocity(entity_id, float(si_value))
            return
        raise ValueError(f"Unknown pose property path: {path}")

    def _on_parameter_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._suspend_parameter_updates or not self._editing_allowed():
            return
        parameter_id = self.parameters_table.item(item.row(), 0).data(QtCore.Qt.ItemDataRole.UserRole)
        if parameter_id is None:
            return
        if not self._prepare_for_model_edit():
            self.refresh_all()
            return
        name = self.parameters_table.item(item.row(), 0).text().strip()
        expression = self.parameters_table.item(item.row(), 1).text().strip()
        unit = self.parameters_table.item(item.row(), 2).text().strip()
        description = self.parameters_table.item(item.row(), 3).text().strip()
        try:
            self.app_service.update_parameter_definition(parameter_id, name, expression, unit, description)
            self._mark_project_dirty()
        except Exception as exc:  # pragma: no cover - UI feedback
            self._append_message(f"Parameter update failed: {exc}")
        self.refresh_all()

    def _apply_property_update(self, entity_id: str, path: str, raw_value: str, kind: str) -> None:
        entity = self.app_service.get_entity(entity_id)
        if entity is None:
            return
        is_sketch = isinstance(entity, (SketchPoint, SketchLineSegment, SketchCircle, SketchArc, SketchInfiniteLine, SketchConstraint))
        if is_sketch:
            if not self._prepare_for_sketch_edit():
                return
        else:
            if not self._prepare_for_model_edit():
                return
        normalized = raw_value.strip()
        if kind == "boolean":
            value = PropertyValueInput("boolean", normalized.lower() in {"true", "1", "yes", "on"})
        elif kind == "expression_or_null" and normalized == "":
            value = PropertyValueInput("null", None)
        else:
            value = PropertyValueInput("expression", normalized)
        if isinstance(entity, (SketchPoint, SketchLineSegment, SketchCircle, SketchArc, SketchInfiniteLine)):
            self.app_service.update_sketch_entity(entity_id, path, value)
        elif isinstance(entity, SketchConstraint):
            self.app_service.update_sketch_constraint(entity_id, path, value)
        else:
            self.app_service.update_property(entity_id, path, value)

    def solve_sketch(self) -> None:
        if not self._prepare_for_sketch_edit():
            return
        report = self.app_service.solve_sketch()
        for message in report.messages:
            self._append_message(message.message)
        self._mark_project_dirty()
        self.refresh_all()

    def _toggle_sketch_visible(self, checked: bool) -> None:
        project = self.app_service.project
        if project is None:
            return
        if project.sketch is None and checked:
            self.app_service.create_sketch()
        if project.sketch is not None:
            self.app_service.set_sketch_visible(checked)
            self._mark_project_dirty()
        self.refresh_all()

    def _add_parameter(self) -> None:
        if not self._editing_allowed():
            self._append_message("Editing is only available at t=0")
            return
        if not self._prepare_for_model_edit():
            return
        existing = [parameter.name for parameter in self.app_service.project.parameters]
        index = 1
        candidate = f"P{index}"
        while candidate in existing:
            index += 1
            candidate = f"P{index}"
        self.app_service.create_parameter(candidate, "0 mm", "mm", "")
        self._append_message(f"Added parameter {candidate}")
        self._mark_project_dirty()
        self.refresh_all()

    def _delete_selected_parameter(self) -> None:
        if not self._editing_allowed():
            self._append_message("Editing is only available at t=0")
            return
        if not self._prepare_for_model_edit():
            return
        row = self.parameters_table.currentRow()
        if row < 0:
            return
        parameter_id = self.parameters_table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole)
        if parameter_id is None:
            return
        self.app_service.delete_parameter(parameter_id)
        self._append_message("Deleted parameter")
        self._mark_project_dirty()
        self.refresh_all()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802 - Qt override
        if self.app_service.executor is not None:
            self.app_service.executor.shutdown()
        if QtWidgets.QApplication.platformName().lower() == "offscreen":
            event.accept()
            return
        if self._confirm_save_if_dirty():
            event.accept()
        else:
            event.ignore()

    def _append_message(self, message: str) -> None:
        current = self.messages.toPlainText()
        text = f"{current}\n{message}".strip()
        self.messages.setPlainText(text)

    def _undo(self) -> None:
        if not self._editing_allowed():
            self._append_message("Editing is only available at t=0")
            return
        if not self._prepare_for_model_edit():
            return
        if self.app_service.undo():
            self._reset_pose_ui_state()
            self._append_message("Undo")
            self._mark_project_dirty()
            self.refresh_all()

    def _redo(self) -> None:
        if not self._editing_allowed():
            self._append_message("Editing is only available at t=0")
            return
        if not self._prepare_for_model_edit():
            return
        if self.app_service.redo():
            self._reset_pose_ui_state()
            self._append_message("Redo")
            self._mark_project_dirty()
            self.refresh_all()

    def _create_driver_for_selected(self, driver_type: str) -> None:
        if not self._editing_allowed():
            self._append_message("Editing is only available at t=0")
            return
        if not self._prepare_for_model_edit():
            return
        if not self._selected_entity_id:
            self._append_message("Select a joint before creating a driver")
            return
        entity = self.app_service.get_entity(self._selected_entity_id)
        if entity is None:
            self._append_message("Select a valid joint before creating a driver")
            return
        if not isinstance(entity, Joint):
            self._append_message("Select a joint before creating a driver")
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
            return
        default_law = "20 deg * t / 1 s" if driver_type == "rotation" else "10 mm * t / 1 s"
        law, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Create Driver",
            "Driver law:",
            text=default_law,
        )
        if not accepted or not law.strip():
            return
        try:
            self.app_service.create_driver(
                name.strip(),
                driver_type,
                entity.id,
                law.strip(),
                "deg" if driver_type == "rotation" else "mm",
            )
            self._append_message(f"Created {driver_type} driver {name.strip()}")
            self._mark_project_dirty()
            self.refresh_all()
        except Exception as exc:  # pragma: no cover - UI feedback
            self._append_message(f"Driver creation failed: {exc}")

    def _next_name(self, prefix: str, existing: list[str]) -> str:
        index = 1
        candidate = f"{prefix}{index}"
        while candidate in existing:
            index += 1
            candidate = f"{prefix}{index}"
        return candidate

    def _editing_allowed(self) -> bool:
        if self._playback_timer.isActive():
            return False
        if self._app_mode == "analysis":
            return False
        if self._last_simulation_result is None or not self._last_simulation_result.frames:
            return True
        return self._current_frame_index == 0

    def _update_interaction_state(self) -> None:
        editing_allowed = self._editing_allowed()
        non_pose_editing_allowed = editing_allowed and self._app_mode != "pose"
        pose_editing_allowed = editing_allowed and self._app_mode == "pose"
        has_simulation = self._has_simulation_frames()
        self.canvas.set_editing_enabled(editing_allowed)
        if not editing_allowed and self.canvas.mode() != CanvasMode.SELECT:
            self.action_select_tool.setChecked(True)
            self.canvas.set_mode(CanvasMode.SELECT)
        for action in (
            self.action_undo,
            self.action_redo,
            self.action_delete,
        ):
            action.setEnabled(non_pose_editing_allowed)
        for action in (
            self.action_bar_tool,
            self.action_point_mass_tool,
            self.action_body_tool,
            self.action_add_marker_tool,
            self.action_joint_tool,
            self.action_rigid_joint_tool,
            self.action_slider_tool,
            self.action_ground_tool,
            self.action_slider_connect_tool,
            self.action_add_rotation_driver,
            self.action_add_translation_driver,
            self.action_add_load,
        ):
            action.setEnabled(non_pose_editing_allowed)
        for action in (
            self.action_sketch_point_tool,
            self.action_sketch_line_tool,
            self.action_sketch_rectangle_tool,
            self.action_sketch_circle_tool,
            self.action_sketch_arc_tool,
            self.action_sketch_infinite_line_tool,
            self.action_sketch_fix_tool,
            self.action_sketch_horizontal_tool,
            self.action_sketch_vertical_tool,
            self.action_sketch_distance_tool,
            self.action_sketch_horizontal_distance_tool,
            self.action_sketch_vertical_distance_tool,
            self.action_sketch_coincident_tool,
            self.action_sketch_parallel_tool,
            self.action_sketch_perpendicular_tool,
            self.action_sketch_equal_length_tool,
            self.action_sketch_angle_tool,
            self.action_sketch_midpoint_tool,
            self.action_sketch_collinear_tool,
            self.action_sketch_symmetric_tool,
            self.action_sketch_tangent_tool,
            self.action_sketch_concentric_tool,
            self.action_sketch_arc_center_tool,
            self.action_solve_sketch,
        ):
            action.setEnabled(non_pose_editing_allowed)
        for action in (
            self.action_pose_reset,
            self.action_pose_solve,
            self.action_pose_set_initial,
            self.action_pose_clear_initial,
            self.action_pose_prescribe_x,
            self.action_pose_prescribe_y,
            self.action_pose_prescribe_horizontal,
            self.action_pose_prescribe_vertical,
            self.action_pose_prescribe_angle,
        ):
            action.setEnabled(pose_editing_allowed)
        in_sketch_mode = self._app_mode == "sketch"
        self.action_toggle_sketch_visible.setEnabled(self._app_mode != "sketch" and self._app_mode != "pose")
        if in_sketch_mode:
            self.action_toggle_sketch_visible.setChecked(True)
        self.add_parameter_button.setEnabled(non_pose_editing_allowed)
        self.delete_parameter_button.setEnabled(non_pose_editing_allowed)
        self.action_play_pause.setEnabled(has_simulation)
        self.action_stop.setEnabled(has_simulation)
        self.timeline_slider.setEnabled(has_simulation)
        if non_pose_editing_allowed:
            edit_triggers = (
                QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
                | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
                | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
            )
            self.parameters_table.setEditTriggers(edit_triggers)
        else:
            self.parameters_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.parameters_table.clearFocus()
        self._update_status_message()

    def _update_mode_button_enable_rules(self) -> None:
        """Pose/Analysis indicators are always disabled (informational).
        Model/Sketch stay enabled so the user can flip between the two
        canvases that share the geometry. We keep the hook for callers
        and use it to re-anchor the indicator pill in case the central
        widget resized while no resize event was forwarded."""
        self._position_mode_indicator()

    def _update_status_message(self) -> None:
        mode = self.canvas.mode()
        mode_label = {
            "select": "Select",
            "create_bar": "Create Bar",
            "create_point_mass": "Punctual Mass",
            "create_body": "Create Body",
            "add_marker": "Marker",
            "create_revolute": "Revolute",
            "create_rigid": "Rigid",
            "create_slider": "Create Slider",
            "connect_ground": "Ground",
            "connect_slider": "To Slider",
            "create_sketch_point": "Point",
            "create_sketch_line_segment": "Line",
            "create_sketch_rectangle": "Rect",
            "create_sketch_circle": "Circle",
            "create_sketch_infinite_line": "Axis",
            "create_sketch_fix": "Fix",
            "create_sketch_horizontal": "Horz",
            "create_sketch_vertical": "Vert",
            "create_sketch_distance": "Dist",
            "create_sketch_coincident": "Coinc",
            "create_sketch_parallel": "Parallel",
            "create_sketch_perpendicular": "Perp",
            "create_sketch_equal_length": "Equal",
            "create_sketch_angle": "Angle",
            "create_sketch_midpoint": "Mid",
            "create_sketch_collinear": "Colin",
            "create_sketch_symmetric": "Sym",
            "create_sketch_tangent": "Tangent",
            "create_sketch_concentric": "Conc",
            "create_sketch_arc_center": "Arc",
            "create_rotation_driver": "RotDrv",
            "create_translation_driver": "LinDrv",
            "create_load": "Load",
        }.get(mode, mode)
        mode_hint = {
            "create_bar": "2 clicks",
            "create_point_mass": "1 click",
            "create_body": "Click to place points, Enter/Esc to finish",
            "create_slider": "2 clicks for axis",
            "create_sketch_point": "1 click",
            "create_sketch_line_segment": "2 clicks or snap to existing points",
            "create_sketch_rectangle": "2 opposite corners",
            "create_sketch_circle": "Center + radius point",
            "create_sketch_infinite_line": "2 points define direction",
            "create_sketch_fix": "Click 1 sketch point",
            "create_sketch_horizontal": "Click 2 sketch points",
            "create_sketch_vertical": "Click 2 sketch points",
            "create_sketch_distance": "Click 2 sketch points, then label",
            "create_sketch_coincident": "Click 2 sketch points",
            "create_sketch_parallel": "Click 4 sketch points (2 per line)",
            "create_sketch_perpendicular": "Click 4 sketch points (2 per line)",
            "create_sketch_equal_length": "Click 4 sketch points (2 per line)",
            "create_sketch_angle": "Click vertex then 2 arm points",
            "create_sketch_midpoint": "Click midpoint then 2 endpoints",
            "create_sketch_collinear": "Click 2 segments",
            "create_sketch_symmetric": "Click 2 points then axis line (2 pts)",
            "create_sketch_tangent": "Click 1 line + 1 curve, or 2 curves",
            "create_sketch_concentric": "Click 2 circles/arcs",
            "create_sketch_arc_center": "Click center, start, end",
            "create_load": "Click a marker",
        }.get(mode)

        if self._editing_allowed():
            suffix = "Editable (t=0)"
        else:
            suffix = f"Playback frame {self._current_frame_index + 1} (read-only)"

        backend = self.app_service.simulation_runner.describe_backend().replace(" backend: ", " ")
        if mode_hint:
            message = f"Backend: {backend}  |  Tool: {mode_label} ({mode_hint})  |  {suffix}"
        else:
            message = f"Backend: {backend}  |  Tool: {mode_label}  |  {suffix}"

        sketch = self.app_service.project.sketch if self.app_service.project else None
        if sketch and sketch.solve_error:
            message += f"  |  ⚠ Sketch: {sketch.solve_error}"
            self.statusBar().setStyleSheet("QStatusBar { color: #b84840; }")
        else:
            self.statusBar().setStyleSheet("")
        dof_text = getattr(self, "_last_dof_info", "")
        if dof_text:
            message += f"  |  {dof_text}"
        self.statusBar().showMessage(message)
