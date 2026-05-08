from __future__ import annotations

from pathlib import Path

from quino.gui.icons import get_icon
from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.examples import build_four_bar_example, build_slider_crank_example
from quino.application.service import ApplicationService
from quino.domain.inputs import PropertyValueInput
from quino.domain.model import Body, Driver, Joint, Marker, Parameter, Project, Sensor, SimulationResult, Slider
from quino.gui.canvas import CanvasMode, MechanismCanvas
from quino.viewer.dataset import SensorDataset
from quino.viewer.qt_widget import SensorPlotWidget


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, app_service: ApplicationService | None = None) -> None:
        super().__init__()
        self.app_service = app_service or ApplicationService()
        if self.app_service.project is None:
            self.app_service.new_project("Untitled")

        self._selected_entity_id: str | None = None
        self._suspend_property_updates = False
        self._suspend_parameter_updates = False
        self._last_simulation_result: SimulationResult | None = None
        self._last_simulation_state: dict[str, float] | None = None
        self._current_frame_index = 0
        self._plot_windows: list[QtWidgets.QMainWindow] = []
        self._playback_timer = QtCore.QTimer(self)
        self._playback_timer.timeout.connect(self._advance_playback)

        self.setWindowTitle("QUINO")
        _icon_path = Path(__file__).parent / "icons" / "quino_app_icon_transparent_1024.png"
        if _icon_path.exists():
            self.setWindowIcon(QtGui.QIcon(str(_icon_path)))
        self.resize(1480, 920)
        self._build_ui()
        self.refresh_all()

    def _build_ui(self) -> None:
        self._build_actions()
        self._build_menu()
        self._build_toolbar()

        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Model", "Type"])
        self.tree.setIconSize(QtCore.QSize(18, 18))
        self.tree.setIndentation(14)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setAlternatingRowColors(True)
        self.tree.currentItemChanged.connect(self._on_tree_selection_changed)
        self.tree.itemDoubleClicked.connect(self._on_tree_item_double_clicked)
        splitter.addWidget(self.tree)

        center_panel = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.canvas = MechanismCanvas(self.app_service)
        self.canvas.entitySelected.connect(self._select_entity_by_id)
        self.canvas.selectionCleared.connect(self._clear_selection)
        self.canvas.modelChanged.connect(self._on_canvas_model_changed)
        self.canvas.modeChanged.connect(self._on_canvas_mode_changed)
        self.canvas.set_edit_guard(self._prepare_for_model_edit)
        self.action_fit_view.triggered.connect(self.canvas.fit_view)
        center_panel.addWidget(self.canvas)

        playback_widget = QtWidgets.QWidget()
        playback_layout = QtWidgets.QVBoxLayout(playback_widget)
        playback_layout.setContentsMargins(6, 6, 6, 6)
        playback_layout.setSpacing(6)

        playback_group = QtWidgets.QGroupBox("Simulation")
        playback_group.setFlat(True)
        playback_group_layout = QtWidgets.QVBoxLayout(playback_group)
        playback_group_layout.setContentsMargins(0, 0, 0, 0)
        playback_group_layout.setSpacing(4)

        controls_layout = QtWidgets.QHBoxLayout()
        self.action_run_button = QtWidgets.QToolButton()
        self.action_play_button = QtWidgets.QToolButton()
        self.action_stop_button = QtWidgets.QToolButton()
        self.action_run_button.setDefaultAction(self.action_run)
        self.action_play_button.setDefaultAction(self.action_play_pause)
        self.action_stop_button.setDefaultAction(self.action_stop)
        controls_layout.addWidget(self.action_run_button)
        controls_layout.addWidget(self.action_play_button)
        controls_layout.addWidget(self.action_stop_button)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(QtWidgets.QLabel("Frame:"))
        self.timeline_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.timeline_slider.setRange(0, 0)
        self.timeline_slider.valueChanged.connect(self._on_timeline_changed)
        controls_layout.addWidget(self.timeline_slider)
        self.timeline_label = QtWidgets.QLabel("0 / 0")
        self.timeline_label.setMinimumWidth(80)
        controls_layout.addWidget(self.timeline_label)
        playback_group_layout.addLayout(controls_layout)

        config_layout = QtWidgets.QHBoxLayout()
        config_layout.addWidget(QtWidgets.QLabel("Duration:"))
        self.duration_spin = QtWidgets.QDoubleSpinBox()
        self.duration_spin.setRange(0.1, 60.0)
        self.duration_spin.setValue(1.0)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setMaximumWidth(100)
        config_layout.addWidget(self.duration_spin)
        config_layout.addSpacing(20)
        config_layout.addWidget(QtWidgets.QLabel("Steps:"))
        self.steps_spin = QtWidgets.QSpinBox()
        self.steps_spin.setRange(1, 2000)
        self.steps_spin.setValue(100)
        self.steps_spin.setMaximumWidth(100)
        config_layout.addWidget(self.steps_spin)
        config_layout.addStretch()
        playback_group_layout.addLayout(config_layout)

        playback_layout.addWidget(playback_group)
        center_panel.addWidget(playback_widget)

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

        self.inspector = QtWidgets.QTableWidget(0, 3)
        self.inspector.setHorizontalHeaderLabels(["Property", "Value", "Evaluated"])
        self.inspector.itemChanged.connect(self._on_inspector_item_changed)
        header = self.inspector.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        inspector_splitter.addWidget(self.inspector)

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

        splitter.setSizes([260, 720, 440])
        self.tree.setMinimumWidth(200)
        right_panel.setMinimumWidth(320)
        self.setCentralWidget(central)

        self.statusBar().showMessage(self.app_service.simulation_runner.describe_backend())

    def _build_actions(self) -> None:
        color_base = "#3d3d3d"
        color_success = "#1a6b4a"
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

        self.action_undo = QtGui.QAction(get_icon("undo", color_base), "Undo", self)
        self.action_undo.setShortcut(QtGui.QKeySequence.StandardKey.Undo)
        self.action_undo.triggered.connect(self._undo)
        self.action_undo.setToolTip("Undo last action (Ctrl+Z)")

        self.action_redo = QtGui.QAction(get_icon("redo", color_base), "Redo", self)
        self.action_redo.setShortcut(QtGui.QKeySequence.StandardKey.Redo)
        self.action_redo.triggered.connect(self._redo)
        self.action_redo.setToolTip("Redo last undone action (Ctrl+Y)")

        self.action_validate = QtGui.QAction(get_icon("check-circle", color_base), "Validate", self)
        self.action_validate.triggered.connect(self.validate_model)
        self.action_validate.setToolTip("Validate model")

        self.action_run = QtGui.QAction(get_icon("run-simulation", color_success), "Run", self)
        self.action_run.triggered.connect(self.run_simulation)
        self.action_run.setToolTip("Run kinematic simulation")

        self._icon_play = get_icon("play")
        self._icon_pause = get_icon("pause")
        self.action_play_pause = QtGui.QAction(self._icon_play, "Play", self)
        self.action_play_pause.triggered.connect(self.toggle_playback)
        self.action_play_pause.setToolTip("Play/pause animation")

        self.action_stop = QtGui.QAction(get_icon("stop", color_danger), "Stop", self)
        self.action_stop.triggered.connect(self.stop_playback)
        self.action_stop.setToolTip("Stop animation")

        self.action_four_bar = QtGui.QAction(get_icon("four-bar", color_base), "Load Four Bar", self)
        self.action_four_bar.triggered.connect(self.load_four_bar_example)
        self.action_four_bar.setToolTip("Load a four-bar linkage example")

        self.action_slider_crank = QtGui.QAction(get_icon("slider-crank", color_base), "Load Slider Crank", self)
        self.action_slider_crank.triggered.connect(self.load_slider_crank_example)
        self.action_slider_crank.setToolTip("Load a slider-crank mechanism example")

        self.action_fit_view = QtGui.QAction(get_icon("fit-view", color_base), "Fit View", self)
        self.action_fit_view.setToolTip("Fit mechanism to view")

        self.action_add_rotation_driver = self._tool_action("Rotation Driver", CanvasMode.CREATE_ROTATION_DRIVER, get_icon("rotate-driver", color_base), "Add a rotation driver to a joint (select a joint on canvas)")
        self.action_add_translation_driver = self._tool_action("Translation Driver", CanvasMode.CREATE_TRANSLATION_DRIVER, get_icon("translate-driver", color_base), "Add a translation driver to a slider (select a slider joint on canvas)")

        self.action_point_sensor = self._tool_action("Point", CanvasMode.CREATE_POINT_SENSOR, get_icon("sensor-point"), "Create a point sensor (select a marker on canvas)")
        self.action_distance_sensor = self._tool_action("Distance", CanvasMode.CREATE_DISTANCE_SENSOR, get_icon("sensor-distance"), "Create a distance sensor (select 2 markers on canvas)")
        self.action_angle_h_sensor = self._tool_action("Angle H", CanvasMode.CREATE_ANGLE_HORIZONTAL_SENSOR, get_icon("sensor-angle-h"), "Create an angle (horizontal) sensor (select 2 markers on canvas)")
        self.action_angle_v_sensor = self._tool_action("Angle V", CanvasMode.CREATE_ANGLE_VERTICAL_SENSOR, get_icon("sensor-angle-v"), "Create an angle (vertical) sensor (select 2 markers on canvas)")
        self.action_angle_vector_sensor = self._tool_action("Angle Vec", CanvasMode.CREATE_ANGLE_VECTOR_SENSOR, get_icon("sensor-angle-vec"), "Create an angle (vector) sensor (select 4 markers on canvas)")

        self.action_new_plot = QtGui.QAction(get_icon("new-graph"), "New Graph", self)
        self.action_new_plot.triggered.connect(self.create_plot_window)
        self.action_new_plot.setToolTip("Create a new plot from sensor data")

        self.action_refresh = QtGui.QAction(get_icon("refresh"), "Refresh", self)
        self.action_refresh.triggered.connect(self.refresh_all)
        self.action_refresh.setToolTip("Force a full UI refresh (use if display seems out of sync)")

        self.action_show_trajectories = QtGui.QAction(get_icon("trajectories"), "Trajectories", self)
        self.action_show_trajectories.setCheckable(True)
        self.action_show_trajectories.setChecked(True)
        self.action_show_trajectories.setEnabled(False)
        self.action_show_trajectories.triggered.connect(self._on_toggle_trajectories)
        self.action_show_trajectories.setToolTip("Show/hide sensor position trajectories on canvas")

        self.action_delete = QtGui.QAction(get_icon("delete", color_danger), "Delete", self)
        self.action_delete.setShortcut(QtGui.QKeySequence.StandardKey.Delete)
        self.action_delete.triggered.connect(self.delete_selected_entity)
        self.action_delete.setToolTip("Delete selected entity (Del)")

        self.action_select_tool = self._tool_action("Select", CanvasMode.SELECT, get_icon("select", color_base), "Select entities")
        self.action_bar_tool = self._tool_action("Bar", CanvasMode.CREATE_BAR, get_icon("bar", color_base), "Create a bar (2-marker body)")
        self.action_body_tool = self._tool_action("Body", CanvasMode.CREATE_BODY, get_icon("body", color_base), "Create a body")
        self.action_add_marker_tool = self._tool_action("Add Marker", CanvasMode.ADD_MARKER, get_icon("marker-plus", color_base), "Add a marker to the selected body")
        self.action_joint_tool = self._tool_action("Revolute Joint", CanvasMode.CREATE_REVOLUTE, get_icon("revolute", color_base), "Create a revolute joint")
        self.action_rigid_joint_tool = self._tool_action("Rigid Joint", CanvasMode.CREATE_RIGID, get_icon("rigid", color_base), "Create a rigid joint")
        self.action_slider_tool = self._tool_action("Slider", CanvasMode.CREATE_SLIDER, get_icon("slider", color_base), "Create a slider")
        self.action_ground_tool = self._tool_action("Ground Joint", CanvasMode.CONNECT_GROUND, get_icon("ground", color_base), "Connect a marker to ground")
        self.action_slider_connect_tool = self._tool_action("Marker To Slider", CanvasMode.CONNECT_SLIDER, get_icon("slider-connect", color_base), "Connect a marker to a slider")

        self.tool_group = QtGui.QActionGroup(self)
        self.tool_group.setExclusive(True)
        for action in (
            self.action_select_tool,
            self.action_bar_tool,
            self.action_body_tool,
            self.action_add_marker_tool,
            self.action_joint_tool,
            self.action_rigid_joint_tool,
            self.action_slider_tool,
            self.action_ground_tool,
            self.action_slider_connect_tool,
            self.action_add_rotation_driver,
            self.action_add_translation_driver,
            self.action_point_sensor,
            self.action_distance_sensor,
            self.action_angle_h_sensor,
            self.action_angle_v_sensor,
            self.action_angle_vector_sensor,
        ):
            self.tool_group.addAction(action)
        self.action_select_tool.setChecked(True)
        self.addAction(self.action_delete)
        self.addAction(self.action_undo)
        self.addAction(self.action_redo)

    def _tool_action(self, label: str, mode: str, icon: QtGui.QIcon | None = None, tooltip: str | None = None) -> QtGui.QAction:
        action = QtGui.QAction(icon or label, label, self)
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
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_delete)

        examples_menu = menubar.addMenu("E&xamples")
        examples_menu.addAction(self.action_four_bar)
        examples_menu.addAction(self.action_slider_crank)

    def _build_toolbar(self) -> None:
        toolbar = self.addToolBar("Modeling")
        toolbar.setIconSize(QtCore.QSize(28, 28))
        toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        toolbar.setMovable(False)

        def _block(actions_grid: list[list[QtGui.QAction | None]], label: str) -> None:
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
                    btn.setIconSize(QtCore.QSize(28, 28))
                    btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                    btn.setFixedSize(52, 52)
                    font = btn.font()
                    font.setPointSize(7)
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

        def _sep() -> None:
            sep = QtWidgets.QFrame()
            sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
            sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
            sep.setFixedWidth(8)
            wa = QtWidgets.QWidgetAction(toolbar)
            wa.setDefaultWidget(sep)
            toolbar.addAction(wa)

        _block([
            [self.action_new, self.action_open, self.action_save],
            [self.action_undo, self.action_redo, self.action_refresh],
        ], "File / Edit")
        _sep()

        _block([
            [self.action_select_tool, self.action_fit_view, self.action_delete],
        ], "View")
        _sep()

        _block([
            [self.action_bar_tool, self.action_body_tool, self.action_add_marker_tool, self.action_joint_tool, self.action_rigid_joint_tool],
            [self.action_ground_tool, self.action_slider_tool, self.action_slider_connect_tool, self.action_add_rotation_driver, self.action_add_translation_driver],
        ], "Geometry / Drivers")
        _sep()

        _block([
            [self.action_point_sensor, self.action_distance_sensor, self.action_angle_h_sensor],
            [self.action_angle_v_sensor, self.action_angle_vector_sensor, None],
        ], "Sensors")
        _sep()

        _block([
            [self.action_validate, self.action_run],
            [self.action_play_pause, self.action_stop],
        ], "Simulation")
        _sep()

        _block([
            [self.action_new_plot, self.action_show_trajectories],
        ], "Results")

    def refresh_all(self) -> None:
        project = self.app_service.project
        if project is None:
            return
        self.setWindowTitle(f"QUINO - {project.name}")
        self._update_timeline_controls()
        self._apply_current_frame()
        self._populate_tree(project)
        self._populate_parameters(project)
        self._populate_inspector()
        self.canvas.set_selection(self._selected_entity_id)
        self._update_interaction_state()

    def load_four_bar_example(self) -> None:
        result = build_four_bar_example(self.app_service)
        self._selected_entity_id = result.body_ids[0]
        self._clear_simulation_state()
        self._append_message("Loaded four-bar example")
        self.canvas.fit_view()
        self.refresh_all()

    def load_slider_crank_example(self) -> None:
        result = build_slider_crank_example(self.app_service)
        self._selected_entity_id = result.body_ids[0]
        self._clear_simulation_state()
        self._append_message("Loaded slider-crank example")
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

    def run_simulation(self) -> None:
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
            message_box.setWindowTitle("Simulation Error")
            message_box.setText(f"Simulation failed:\n\n{result.error}{detail}")
            message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
            message_box.exec()

    def toggle_playback(self) -> None:
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
        self._playback_timer.stop()
        self._current_frame_index = 0
        self._apply_current_frame()
        self._update_timeline_controls()
        self._sync_play_pause_icon()
        self._update_interaction_state()

    def _sync_play_pause_icon(self) -> None:
        if self._playback_timer.isActive():
            self.action_play_pause.setIcon(self._icon_pause)
            self.action_play_pause.setText("Pause")
        else:
            self.action_play_pause.setIcon(self._icon_play)
            self.action_play_pause.setText("Play")

    def create_plot_window(self) -> None:
        if self.app_service.project is None:
            self._append_message("No project loaded")
            return
        dataset = SensorDataset(self.app_service.project)
        if not dataset.has_data():
            QtWidgets.QMessageBox.information(self, "No Data", "No sensor data available. Run a simulation first.")
            return
        sensor_names = dataset.get_matrix_names()
        if not sensor_names:
            QtWidgets.QMessageBox.information(self, "No Data", "No sensor data available.")
            return
        dialog = QtWidgets.QDialog(self, QtCore.Qt.WindowType.Window)
        dialog.setWindowTitle("Select Sensors to Plot")
        dialog.resize(300, 400)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel("Select sensors to load:"))
        list_widget = QtWidgets.QListWidget()
        for name in sensor_names:
            list_widget.addItem(name)
        list_widget.setSelectionMode(QtWidgets.QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(list_widget)
        button_layout = QtWidgets.QHBoxLayout()
        btn_ok = QtWidgets.QPushButton("OK")
        btn_cancel = QtWidgets.QPushButton("Cancel")
        button_layout.addWidget(btn_ok)
        button_layout.addWidget(btn_cancel)
        layout.addLayout(button_layout)
        btn_ok.clicked.connect(dialog.accept)
        btn_cancel.clicked.connect(dialog.reject)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        selected = [item.text() for item in list_widget.selectedItems()]
        if not selected:
            return
        plot_window = QtWidgets.QMainWindow(self)
        plot_window.setWindowTitle(f"QUINO Plot - {', '.join(selected[:2])}{'...' if len(selected) > 2 else ''}")
        plot_window.resize(1200, 600)
        plot_widget = SensorPlotWidget(dataset, plot_window)
        plot_window.setCentralWidget(plot_widget)
        plot_window.show()
        for sensor_name in selected:
            plot_widget.load_sensor(sensor_name)
        self._plot_windows.append(plot_window)
        self._append_message(f"Created plot with {len(selected)} sensor(s)")

    def delete_selected_entity(self) -> None:
        if not self._editing_allowed():
            self._append_message("Editing is only available at t=0")
            return
        if not self._selected_entity_id:
            return
        if not self._prepare_for_model_edit():
            return
        try:
            self.app_service.delete_entity(self._selected_entity_id)
            self._append_message("Deleted selected entity")
            self._selected_entity_id = None
        except Exception as exc:  # pragma: no cover - UI feedback
            self._append_message(f"Delete failed: {exc}")
        self.refresh_all()

    def _advance_playback(self) -> None:
        if self._last_simulation_result is None or not self._last_simulation_result.frames:
            self.stop_playback()
            return
        if self._current_frame_index >= len(self._last_simulation_result.frames) - 1:
            self.stop_playback()
            return
        self._current_frame_index += 1
        self._apply_current_frame()
        self._update_timeline_controls()

    def _on_timeline_changed(self, value: int) -> None:
        self._current_frame_index = value
        self._apply_current_frame()
        self._update_timeline_controls()

    def _apply_current_frame(self) -> None:
        frame = None
        if self._last_simulation_result is not None and self._last_simulation_result.frames:
            index = max(0, min(self._current_frame_index, len(self._last_simulation_result.frames) - 1))
            frame = self._last_simulation_result.frames[index]
        self._last_simulation_state = frame
        self.canvas.set_state_overlay(frame)
        if self.app_service.project is not None:
            self._populate_canvas_summary(self.app_service.project)
        self._update_interaction_state()

    def _update_timeline_controls(self) -> None:
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
        return self._last_simulation_result is not None and bool(self._last_simulation_result.frames)

    def _clear_simulation_state(self, message: str | None = None) -> None:
        self._playback_timer.stop()
        self._sync_play_pause_icon()
        self._last_simulation_result = None
        self._last_simulation_state = None
        self._current_frame_index = 0
        self.canvas.set_state_overlay(None)
        self.canvas.set_trajectories([])
        self.action_show_trajectories.setEnabled(False)
        self._update_timeline_controls()
        self._update_interaction_state()
        if message:
            self._append_message(message)

    def _on_toggle_trajectories(self) -> None:
        self.canvas.set_show_trajectories(self.action_show_trajectories.isChecked())

    def _update_trajectories(self) -> None:
        project = self.app_service.project
        if project is None:
            return
        trajectories = []
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

    def _prepare_for_model_edit(self) -> bool:
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

    def _new_project(self) -> None:
        name, accepted = QtWidgets.QInputDialog.getText(self, "New Project", "Project name:", text="Untitled")
        if not accepted or not name:
            return
        self.app_service.new_project(name)
        self._selected_entity_id = None
        self._clear_simulation_state()
        self.messages.clear()
        self.validation_view.clear()
        self.canvas.fit_view()
        self.refresh_all()

    def _open_project(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Project",
            str(Path.cwd()),
            "QUINO Project (*.quino.json);;JSON Files (*.json)",
        )
        if not path:
            return
        self.app_service.load_project(path)
        self._selected_entity_id = None
        self._clear_simulation_state()
        self.messages.clear()
        self.validation_view.clear()
        self._append_message(f"Opened project: {path}")
        self.canvas._view_scale = None
        self.refresh_all()

    def _save_project(self) -> None:
        project = self.app_service.project
        if project is None:
            return
        suggested = f"{project.name.replace(' ', '_')}.quino.json"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Project",
            str(Path.cwd() / suggested),
            "QUINO Project (*.quino.json);;JSON Files (*.json)",
        )
        if not path:
            return
        self.app_service.save_project(path)
        self._append_message(f"Saved project: {path}")

    # --- icon name per entity kind ---
    _KIND_ICON: dict[str, str] = {
        "bar": "bar", "body": "body",
        "structural": "marker", "com": "marker",
        "slider": "slider",
        "revolute": "revolute", "rigid": "rigid",
        "rotation": "rotate-driver", "translation": "translate-driver",
        "point": "sensor-point", "distance": "sensor-distance",
        "angle_horizontal": "sensor-angle-h", "angle_vertical": "sensor-angle-v",
        "angle_vector": "sensor-angle-vec",
    }
    _SECTION_ICON: dict[str, str] = {
        "Bodies": "body", "Sliders": "slider", "Joints": "revolute",
        "Drivers": "rotate-driver", "Sensors": "sensor-point",
    }
    _SECTION_COLOR: dict[str, str] = {
        "Bodies": "#31556f", "Sliders": "#457b9d", "Joints": "#2f3a4b",
        "Drivers": "#7f5539", "Sensors": "#1a6b4a",
    }

    def _populate_tree(self, project: Project) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()

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

        bodies_root = _root("Bodies", len(project.model.bodies))
        sliders_root = _root("Sliders", len(project.model.sliders))
        joints_root = _root("Joints", len(project.model.joints))
        drivers_root = _root("Drivers", len(project.model.drivers))
        sensors_root = _root("Sensors", len(project.model.sensors))
        self.tree.addTopLevelItems([bodies_root, sliders_root, joints_root, drivers_root, sensors_root])

        for body in project.model.bodies:
            body_item = self._entity_item(body.name, body.type.value, body.id)
            bodies_root.addChild(body_item)
            for marker in body.markers:
                if not marker.visible and marker.type.value == "com":
                    continue
                body_item.addChild(self._entity_item(marker.name, marker.type.value, marker.id))
        for slider in project.model.sliders:
            sliders_root.addChild(self._entity_item(slider.name, "slider", slider.id))
        for joint in project.model.joints:
            joints_root.addChild(self._entity_item(joint.name, joint.type.value, joint.id))
        for driver in project.model.drivers:
            drivers_root.addChild(self._entity_item(driver.name, driver.type.value, driver.id))
        for sensor in project.model.sensors:
            sensors_root.addChild(self._entity_item(sensor.name, sensor.type.value, sensor.id))

        self.tree.expandAll()
        self.tree.blockSignals(False)

        if self._selected_entity_id:
            matches = self.tree.findItems("", QtCore.Qt.MatchFlag.MatchContains | QtCore.Qt.MatchFlag.MatchRecursive, 0)
            for item in matches:
                if item.data(0, QtCore.Qt.ItemDataRole.UserRole) == self._selected_entity_id:
                    self.tree.setCurrentItem(item)
                    break

    def _entity_item(self, label: str, kind: str, entity_id: str) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([label, kind])
        item.setData(0, QtCore.Qt.ItemDataRole.UserRole, entity_id)
        icon_name = self._KIND_ICON.get(kind, "")
        if icon_name:
            item.setIcon(0, get_icon(icon_name, size=13))
        return item

    def _populate_parameters(self, project: Project) -> None:
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

    def _populate_canvas_summary(self, project: Project) -> None:
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
        CanvasMode.CREATE_ANGLE_VECTOR_SENSOR,
    }

    def _on_tree_selection_changed(self, current: QtWidgets.QTreeWidgetItem | None, previous) -> None:
        del previous
        entity_id = current.data(0, QtCore.Qt.ItemDataRole.UserRole) if current else None
        if entity_id is not None and self.canvas.mode() in self._CREATION_MODES:
            # In a creation workflow: route the selection to the canvas without
            # overwriting canvas internal state (joint start marker, etc.)
            self.canvas.inject_entity_selection(entity_id)
            return
        self._selected_entity_id = entity_id
        self._populate_inspector()
        self.canvas.set_selection(entity_id)

    def _select_entity_by_id(self, entity_id: str) -> None:
        self._selected_entity_id = entity_id
        matches = self.tree.findItems("", QtCore.Qt.MatchFlag.MatchContains | QtCore.Qt.MatchFlag.MatchRecursive, 0)
        for item in matches:
            if item.data(0, QtCore.Qt.ItemDataRole.UserRole) == entity_id:
                self.tree.setCurrentItem(item)
                break
        self._populate_inspector()
        self.canvas.set_selection(entity_id)

    def _clear_selection(self) -> None:
        self._selected_entity_id = None
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)
        self._populate_inspector()
        self.canvas.set_selection(None)

    def _on_canvas_model_changed(self, message: str) -> None:
        self._append_message(message)
        self.refresh_all()

    def _on_canvas_mode_changed(self, mode: str) -> None:
        action_for_mode = {
            CanvasMode.SELECT: self.action_select_tool,
            CanvasMode.CREATE_BAR: self.action_bar_tool,
            CanvasMode.CREATE_BODY: self.action_body_tool,
            CanvasMode.ADD_MARKER: self.action_add_marker_tool,
            CanvasMode.CREATE_REVOLUTE: self.action_joint_tool,
            CanvasMode.CREATE_RIGID: self.action_rigid_joint_tool,
            CanvasMode.CREATE_SLIDER: self.action_slider_tool,
            CanvasMode.CONNECT_GROUND: self.action_ground_tool,
            CanvasMode.CONNECT_SLIDER: self.action_slider_connect_tool,
            CanvasMode.CREATE_ROTATION_DRIVER: self.action_add_rotation_driver,
            CanvasMode.CREATE_TRANSLATION_DRIVER: self.action_add_translation_driver,
            CanvasMode.CREATE_POINT_SENSOR: self.action_point_sensor,
            CanvasMode.CREATE_DISTANCE_SENSOR: self.action_distance_sensor,
            CanvasMode.CREATE_ANGLE_HORIZONTAL_SENSOR: self.action_angle_h_sensor,
            CanvasMode.CREATE_ANGLE_VERTICAL_SENSOR: self.action_angle_v_sensor,
            CanvasMode.CREATE_ANGLE_VECTOR_SENSOR: self.action_angle_vector_sensor,
        }.get(mode)
        if action_for_mode:
            if action_for_mode in self.tool_group.actions():
                action_for_mode.setChecked(True)
            else:
                # Para botones que no están en tool_group (como drivers)
                action_for_mode.setChecked(True)
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
            self.inspector.setRowCount(0)
            self.inspector_title.setText("")
            # clear old relation widgets
            while self.relations_vbox.count() > 1:  # keep trailing stretch
                child = self.relations_vbox.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            if not self._selected_entity_id:
                return
            try:
                entity = self.app_service._find_entity(self._selected_entity_id)
            except ValueError:
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

            # --- property rows ---
            prop_rows = self._inspector_rows(entity)
            self.inspector.setRowCount(len(prop_rows))
            for row_index, (label, path, value, kind, evaluated, _) in enumerate(prop_rows):
                label_item = QtWidgets.QTableWidgetItem(label)
                label_item.setFlags(label_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                self.inspector.setItem(row_index, 0, label_item)

                evaluated_item = QtWidgets.QTableWidgetItem(evaluated)
                evaluated_item.setFlags(evaluated_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                if evaluated.startswith("ERROR:"):
                    evaluated_item.setForeground(QtGui.QColor("#c0392b"))

                if kind == "boolean":
                    value_item = QtWidgets.QTableWidgetItem(value)
                    value_item.setFlags(value_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                    value_item.setData(QtCore.Qt.ItemDataRole.UserRole, (path, kind))
                    self.inspector.setItem(row_index, 1, value_item)
                    combo = QtWidgets.QComboBox(self.inspector)
                    combo.addItems(["false", "true"])
                    combo.setCurrentText(value)
                    combo.setEnabled(self._editing_allowed())
                    combo.currentTextChanged.connect(
                        lambda text, current_path=path: self._on_inspector_boolean_changed(current_path, text)
                    )
                    self.inspector.setCellWidget(row_index, 1, combo)
                else:
                    value_item = QtWidgets.QTableWidgetItem(value)
                    value_item.setData(QtCore.Qt.ItemDataRole.UserRole, (path, kind))
                    if not self._editing_allowed() or kind == "readonly":
                        value_item.setFlags(value_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                    self.inspector.setItem(row_index, 1, value_item)
                self.inspector.setItem(row_index, 2, evaluated_item)

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
        if isinstance(entity, Parameter):
            return "parameter"
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
        return ""

    def _on_tree_item_double_clicked(self, item: QtWidgets.QTreeWidgetItem, _col: int) -> None:
        entity_id = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if entity_id:
            self._select_entity_by_id(entity_id)
            self.canvas.center_on_entity(entity_id)

    def _inspector_rows(self, entity: object) -> list[tuple[str, str, str, str, str, str | None]]:
        # Returns prop rows only: (label, path, value, kind, evaluated, None)
        rows: list[tuple[str, str, str, str, str, str | None]] = []

        def prop(label, path, value, kind, evaluated):
            rows.append((label, path, value, kind, evaluated, None))

        if isinstance(entity, (Body, Marker, Slider, Joint, Driver, Sensor, Parameter)):
            prop("name", "name", entity.name, "expression", entity.name)

        if isinstance(entity, Body):
            prop("closed_shape", "closed_shape", str(entity.closed_shape).lower(), "boolean", str(entity.closed_shape).lower())
            prop("mass", "mass", entity.mass.expression if entity.mass else "", "expression_or_null", self._evaluate_scalar(entity.mass))
            prop("inertia", "inertia", entity.inertia.expression if entity.inertia else "", "expression_or_null", self._evaluate_scalar(entity.inertia))

        elif isinstance(entity, Marker):
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

        elif isinstance(entity, Driver):
            prop("type", "", entity.type.value, "readonly", entity.type.value)
            prop("law", "law", entity.law.expression, "expression", self._evaluate_scalar(entity.law, with_time=True))

        elif isinstance(entity, Sensor):
            prop("type", "", entity.type.value, "readonly", entity.type.value)
            output = self.app_service.project.sensor_outputs.get(entity.id)
            if output and output.columns and output.data:
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

        return rows

    # relation tuple: (group, icon_name, display, detail, entity_id | None)
    def _inspector_relations(self, entity: object) -> list[tuple[str, str, str, str, str | None]]:
        rels: list[tuple[str, str, str, str, str | None]] = []
        project = self.app_service.project

        def rel(group: str, icon: str, display: str, detail: str = "", entity_id: str | None = None):
            rels.append((group, icon, display, detail, entity_id))

        if isinstance(entity, Body):
            for m in entity.markers:
                if not m.visible and m.type.value == "com":
                    continue
                coords = self._evaluate_scalar(m.x) + " / " + self._evaluate_scalar(m.y)
                rel("Markers", "marker", m.name, coords, m.id)

        elif isinstance(entity, Marker):
            try:
                body = self.app_service._find_body_by_marker(entity.id)
                rel("Parent Body", "body" if body.type.value == "body" else "bar", body.name, body.type.value, body.id)
            except Exception:
                pass
            joints = [j for j in project.model.joints
                      if j.endpoint_a.marker_id == entity.id or j.endpoint_b.marker_id == entity.id]
            for j in joints:
                icon_j = self._KIND_ICON.get(j.type.value, "revolute")
                other_ep = j.endpoint_b if j.endpoint_a.marker_id == entity.id else j.endpoint_a
                if other_ep.kind.value == "ground":
                    detail = "→ Ground"
                elif other_ep.kind.value == "slider" and other_ep.slider_id:
                    try:
                        sl = self.app_service._find_entity(other_ep.slider_id)
                        detail = f"→ {sl.name}"
                    except Exception:
                        detail = "→ slider"
                elif other_ep.marker_id:
                    try:
                        om = self.app_service._find_entity(other_ep.marker_id)
                        ob = self.app_service._find_body_by_marker(other_ep.marker_id)
                        detail = f"→ {ob.name}.{om.name}"
                    except Exception:
                        detail = "→ ?"
                else:
                    detail = ""
                rel("Joints", icon_j, j.name, detail, j.id)

        elif isinstance(entity, Joint):
            for label, ep in [("A", entity.endpoint_a), ("B", entity.endpoint_b)]:
                if ep.kind.value == "ground":
                    rel("Endpoints", "ground", f"Endpoint {label}", "Ground", None)
                elif ep.kind.value == "slider" and ep.slider_id:
                    try:
                        sl = self.app_service._find_entity(ep.slider_id)
                        rel("Endpoints", "slider", f"Endpoint {label}", sl.name, ep.slider_id)
                    except Exception:
                        rel("Endpoints", "slider", f"Endpoint {label}", ep.slider_id or "?", ep.slider_id)
                elif ep.marker_id:
                    try:
                        om = self.app_service._find_entity(ep.marker_id)
                        ob = self.app_service._find_body_by_marker(ep.marker_id)
                        rel("Endpoints", "marker", f"Endpoint {label}", f"{ob.name}.{om.name}", ep.marker_id)
                    except Exception:
                        rel("Endpoints", "marker", f"Endpoint {label}", ep.marker_id or "?", ep.marker_id)

        elif isinstance(entity, Driver):
            try:
                joint = self.app_service._find_entity(entity.target_joint_id)
                icon_j = self._KIND_ICON.get(joint.type.value, "revolute")
                rel("Target Joint", icon_j, joint.name, joint.type.value, entity.target_joint_id)
            except Exception:
                pass

        elif isinstance(entity, Sensor):
            for mid in (entity.marker_ids or []):
                try:
                    om = self.app_service._find_entity(mid)
                    ob = self.app_service._find_body_by_marker(mid)
                    rel("Markers", "marker", om.name, ob.name, mid)
                except Exception:
                    rel("Markers", "marker", mid, "", mid)

        return rels

    def _evaluate_scalar(self, scalar, with_time: bool = False) -> str:
        if scalar is None:
            return "null"
        try:
            variables = {"t": self.app_service.unit_service.quantity(0.0, "s")} if with_time else None
            quantity = self.app_service.expression_service.evaluate_property(
                scalar,
                self.app_service.project.parameters,
                variables=variables,
            )
            return f"{quantity.value:.6g} {scalar.unit}"
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

    def _on_inspector_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._suspend_property_updates or item.column() != 1 or not self._selected_entity_id or not self._editing_allowed():
            return
        data = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not data:
            return
        path, kind = data
        if not path or kind == "readonly":
            return
        try:
            self._apply_property_update(self._selected_entity_id, path, item.text(), kind)
        except Exception as exc:  # pragma: no cover - UI feedback
            self._append_message(f"Property update failed: {exc}")
        self.refresh_all()

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
            self.app_service.rename_entity(parameter_id, name)
            self.app_service.update_parameter(parameter_id, expression=expression, unit=unit, description=description)
        except Exception as exc:  # pragma: no cover - UI feedback
            self._append_message(f"Parameter update failed: {exc}")
        self.refresh_all()

    def _on_inspector_boolean_changed(self, path: str, text: str) -> None:
        if self._suspend_property_updates or not self._selected_entity_id or not self._editing_allowed():
            return
        try:
            self._apply_property_update(self._selected_entity_id, path, text, "boolean")
        except Exception as exc:  # pragma: no cover - UI feedback
            self._append_message(f"Property update failed: {exc}")
        self.refresh_all()

    def _apply_property_update(self, entity_id: str, path: str, raw_value: str, kind: str) -> None:
        if not self._prepare_for_model_edit():
            return
        normalized = raw_value.strip()
        if kind == "boolean":
            value = PropertyValueInput("boolean", normalized.lower() in {"true", "1", "yes", "on"})
        elif kind == "expression_or_null" and normalized == "":
            value = PropertyValueInput("null", None)
        else:
            value = PropertyValueInput("expression", normalized)
        self.app_service.update_property(entity_id, path, value)

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
        self.refresh_all()

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
            self._append_message("Undo")
            self.refresh_all()

    def _redo(self) -> None:
        if not self._editing_allowed():
            self._append_message("Editing is only available at t=0")
            return
        if not self._prepare_for_model_edit():
            return
        if self.app_service.redo():
            self._append_message("Redo")
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
        try:
            entity = self.app_service._find_entity(self._selected_entity_id)
        except ValueError:
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
        if self._last_simulation_result is None or not self._last_simulation_result.frames:
            return True
        return self._current_frame_index == 0

    def _update_interaction_state(self) -> None:
        editing_allowed = self._editing_allowed()
        has_simulation = self._has_simulation_frames()
        self.canvas.set_editing_enabled(editing_allowed)
        if not editing_allowed and self.canvas.mode() != CanvasMode.SELECT:
            self.action_select_tool.setChecked(True)
            self.canvas.set_mode(CanvasMode.SELECT)
        for action in (
            self.action_undo,
            self.action_redo,
            self.action_bar_tool,
            self.action_body_tool,
            self.action_add_marker_tool,
            self.action_joint_tool,
            self.action_rigid_joint_tool,
            self.action_slider_tool,
            self.action_ground_tool,
            self.action_slider_connect_tool,
            self.action_delete,
            self.action_add_rotation_driver,
            self.action_add_translation_driver,
        ):
            action.setEnabled(editing_allowed)
        self.add_parameter_button.setEnabled(editing_allowed)
        self.delete_parameter_button.setEnabled(editing_allowed)
        self.action_play_pause.setEnabled(has_simulation)
        self.action_stop.setEnabled(has_simulation)
        self.timeline_slider.setEnabled(has_simulation)
        if editing_allowed:
            edit_triggers = (
                QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
                | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
                | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
            )
            self.inspector.setEditTriggers(edit_triggers)
            self.parameters_table.setEditTriggers(edit_triggers)
        else:
            self.inspector.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.parameters_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.inspector.clearFocus()
            self.parameters_table.clearFocus()
        self._update_status_message()

    def _update_status_message(self) -> None:
        mode = self.canvas.mode()
        mode_label = {
            "select": "Select",
            "create_bar": "Create Bar",
            "create_body": "Create Body",
            "add_marker": "Add Marker",
            "create_revolute": "Revolute Joint",
            "create_rigid": "Rigid Joint",
            "create_slider": "Create Slider",
            "connect_ground": "Ground Joint",
            "connect_slider": "Slider Joint",
            "create_rotation_driver": "Rotation Driver",
            "create_translation_driver": "Translation Driver",
        }.get(mode, mode)

        if self._editing_allowed():
            suffix = "Editable (t=0)"
        else:
            suffix = f"Playback frame {self._current_frame_index + 1} (read-only)"

        backend = self.app_service.simulation_runner.describe_backend().replace(" backend: ", " ")
        message = f"Backend: {backend}  |  Tool: {mode_label}  |  {suffix}"
        self.statusBar().showMessage(message)
