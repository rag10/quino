from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from quino.gui.icons import get_icon

_ICON_DIR = Path(__file__).parent.parent / "gui" / "icons"
_APP_ICON = _ICON_DIR / "quino_app_icon_transparent_1024.png"


def _action(
    parent: QtWidgets.QWidget,
    text: str,
    icon_name: str | None = None,
    tooltip: str = "",
    checkable: bool = False,
    checked: bool = False,
) -> QtGui.QAction:
    action = QtGui.QAction(text, parent)
    if icon_name:
        action.setIcon(get_icon(icon_name))
    if tooltip:
        action.setToolTip(tooltip)
    if checkable:
        action.setCheckable(True)
        action.setChecked(checked)
    return action


class PlotWindow(QtWidgets.QMainWindow):
    """Stand-alone plot window wrapping SensorPlotWidget with full menu/toolbar."""

    window_closed = QtCore.Signal()

    def __init__(
        self,
        app_service=None,  # ApplicationService | None — avoid hard import cycle
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.app_service = app_service

        self.setWindowTitle("QUINO — Plot")
        self.resize(1280, 680)
        if _APP_ICON.exists():
            self.setWindowIcon(QtGui.QIcon(str(_APP_ICON)))

        self._build_plot_widget()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()

    # ------------------------------------------------------------------
    # Internal construction
    # ------------------------------------------------------------------

    def _build_plot_widget(self) -> None:
        from quino.viewer.qt_widget import SensorPlotWidget

        self.plot_widget = SensorPlotWidget(dataset=None, parent=self)
        self.plot_widget._plot_window_ref = self
        self.setCentralWidget(self.plot_widget)

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")

        self.action_import_sim = _action(
            self,
            "Import from simulation",
            "play",
            "Load sensor data from the active simulation",
        )
        self.action_import_csv = _action(
            self,
            "Import from CSV…",
            "folder-open",
            "Load data from a CSV or TSV file",
        )
        self.action_export = _action(
            self,
            "Export…",
            "content-save",
            "Export visible channels to CSV",
        )
        self.action_close = _action(self, "Close", tooltip="Close this plot window")

        file_menu.addAction(self.action_import_sim)
        file_menu.addAction(self.action_import_csv)
        file_menu.addSeparator()
        file_menu.addAction(self.action_export)
        file_menu.addSeparator()
        file_menu.addAction(self.action_close)

        # View
        view_menu = mb.addMenu("&View")

        self.action_fit_view = _action(self, "Fit View", "fit-view", "Fit all data in view")
        self.action_reset_zoom = _action(self, "Reset Zoom", tooltip="Reset zoom to full time range")
        self.action_toggle_legend = _action(
            self, "Toggle Legend", "check-circle", checkable=True, checked=True
        )
        self.action_toggle_grid = _action(
            self, "Toggle Grid", "four-bar", checkable=True, checked=True
        )
        self.action_toggle_crosshair = _action(
            self, "Toggle Crosshair", checkable=True, checked=False
        )

        view_menu.addAction(self.action_fit_view)
        view_menu.addAction(self.action_reset_zoom)
        view_menu.addSeparator()
        view_menu.addAction(self.action_toggle_legend)
        view_menu.addAction(self.action_toggle_grid)
        view_menu.addAction(self.action_toggle_crosshair)

        # Wire signals
        self.action_import_sim.triggered.connect(self._import_from_simulation)
        self.action_import_csv.triggered.connect(self._import_from_csv)
        self.action_export.triggered.connect(self._export)
        self.action_close.triggered.connect(self.close)
        self.action_fit_view.triggered.connect(lambda: self.plot_widget.fit_view())
        self.action_reset_zoom.triggered.connect(lambda: self.plot_widget.reset_zoom())
        self.action_toggle_legend.toggled.connect(self.plot_widget.set_legend_visible)
        self.action_toggle_grid.toggled.connect(self.plot_widget.set_grid_visible)
        self.action_toggle_crosshair.toggled.connect(self.plot_widget.set_crosshair_visible)

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.setIconSize(QtCore.QSize(20, 20))
        tb.setMovable(False)

        tb.addAction(self.action_import_sim)
        tb.addAction(self.action_import_csv)
        tb.addSeparator()
        tb.addAction(self.action_export)
        tb.addSeparator()
        tb.addAction(self.action_fit_view)
        tb.addAction(self.action_toggle_legend)
        tb.addAction(self.action_toggle_grid)
        tb.addAction(self.action_toggle_crosshair)
        tb.addSeparator()

        self.action_delete_channel = _action(
            self, "Delete selected", "delete", "Delete selected channel(s)"
        )
        self.action_delete_channel.triggered.connect(self._delete_selected_channels)
        tb.addAction(self.action_delete_channel)

    def _build_statusbar(self) -> None:
        self.coord_label = QtWidgets.QLabel("")
        self.coord_label.setMinimumWidth(280)
        self.statusBar().addPermanentWidget(self.coord_label)
        self.statusBar().showMessage("Ready")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prompt_import_from_simulation(self) -> None:
        """Called by main_window immediately after show() to offer sensor import."""
        self._import_from_simulation()

    def update_coord_label(self, text: str) -> None:
        """Called by SensorPlotWidget when crosshair moves."""
        self.coord_label.setText(text)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _import_from_simulation(self) -> None:
        if self.app_service is None or self.app_service.project is None:
            QtWidgets.QMessageBox.information(
                self, "No simulation", "No active project. Run a simulation first."
            )
            return
        from quino.viewer.dataset import SensorDataset

        dataset = SensorDataset(self.app_service.project)
        if not dataset.has_data():
            QtWidgets.QMessageBox.information(
                self,
                "No Data",
                "No sensor data available. Run a simulation first.",
            )
            return

        names = dataset.get_matrix_names()
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Select sensors to load")
        dialog.resize(300, 380)
        lay = QtWidgets.QVBoxLayout(dialog)
        lay.addWidget(QtWidgets.QLabel("Select sensors:"))
        lw = QtWidgets.QListWidget()
        lw.addItems(names)
        lw.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        lay.addWidget(lw)
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dialog.accept)
        btns.rejected.connect(dialog.reject)
        lay.addWidget(btns)

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        selected = [item.text() for item in lw.selectedItems()]
        if not selected:
            return

        self.plot_widget.set_dataset(dataset)
        for name in selected:
            self.plot_widget.load_sensor(name)
        self.statusBar().showMessage(f"Loaded {len(selected)} sensor(s) from simulation")

    def _import_from_csv(self) -> None:
        path_str, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open CSV / TSV",
            "",
            "Data files (*.csv *.tsv *.txt);;All files (*)",
        )
        if not path_str:
            return
        from quino.viewer.dataset import load_from_csv

        try:
            data, headers, name = load_from_csv(Path(path_str))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Import error", str(exc))
            return

        self.plot_widget.load_csv_matrix(name, data, headers)
        self.statusBar().showMessage(f"Loaded '{name}' from {Path(path_str).name}")

    def _export(self) -> None:
        self.plot_widget.export_selected()

    def _delete_selected_channels(self) -> None:
        self.plot_widget.delete_selected_channels()

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.window_closed.emit()
        super().closeEvent(event)
