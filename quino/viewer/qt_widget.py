from __future__ import annotations

from functools import partial

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from quino.viewer.dataset import SensorDataset
from quino.viewer.transform import ChannelTransform
from quino.viewer.exporter import DataExporter

# Professional engineering colour palette (Tableau-10 adapted)
COLOR_PALETTE = [
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#ff7f0e",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#17becf",
    "#7f7f7f",
    "#bcbd22",
]

_PLOT_BG = "#fafaf8"
_AXIS_PEN = "#3d3d3d"
_GRID_ALPHA = 0.25

# Column indices
_C_NAME  = 0
_C_COLOR = 1
_C_X     = 2
_C_Y     = 3
_C_MIN   = 4
_C_MAX   = 5
_C_WIDTH = 6
_C_SHIFT = 7
_C_MULT  = 8
_C_PTS   = 9
_NUM_COLS = 10

_COL_HEADERS = ["Sensor / Channel", "●", "X", "Y", "Min", "Max", "W", "Shift", "×Mult", "Pts"]
_COL_WIDTHS  = [170, 28, 28, 28, 72, 72, 52, 80, 80, 34]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class MatrixItem(QtWidgets.QTreeWidgetItem):
    """Top-level tree item for one sensor/CSV dataset.
    The row spans all columns as a section title."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.channels: list[ChannelItem] = []
        self.x_channel_idx = 0
        self.setText(_C_NAME, name)
        bg = QtGui.QColor("#dce8f5")
        for col in range(_NUM_COLS):
            self.setBackground(col, bg)
        font = self.font(_C_NAME)
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self.setFont(_C_NAME, font)

    def span_in_tree(self) -> None:
        """Call after addTopLevelItem to make name span all columns."""
        tree = self.treeWidget()
        if tree is None:
            return
        row = tree.indexOfTopLevelItem(self)
        tree.setFirstColumnSpanned(row, QtCore.QModelIndex(), True)

    def reset_shifts(self) -> None:
        for ch in self.channels:
            ch.spin_shift.setValue(0.0)

    def reset_mults(self) -> None:
        for ch in self.channels:
            if not ch.is_time:
                ch.spin_mult.setValue(1.0)


class ChannelItem(QtWidgets.QTreeWidgetItem):
    """One data column inside a MatrixItem."""

    def __init__(
        self,
        parent: MatrixItem,
        name: str,
        data: np.ndarray,
        is_time: bool = False,
        color: str = "#888888",
    ):
        super().__init__(parent)
        self.name = name
        self.setText(_C_NAME, name)
        self.values = data
        self.is_time = is_time
        self.color = color
        self.curve: pg.PlotDataItem | None = None
        self.scatter: pg.ScatterPlotItem | None = None
        self.transform = ChannelTransform()
        if not is_time:
            self.transform.set_multiplier(1.0)
        # widget refs — set in initialize()
        self.btn_color: QtWidgets.QPushButton | None = None
        self.check_x: QtWidgets.QCheckBox
        self.check_y: QtWidgets.QCheckBox
        self.spin_width: QtWidgets.QSpinBox | None = None
        self.spin_shift: QtWidgets.QDoubleSpinBox
        self.spin_mult: QtWidgets.QDoubleSpinBox | None = None
        self.check_points: QtWidgets.QCheckBox | None = None

    @property
    def x(self) -> bool:
        return self.check_x.isChecked()

    @property
    def y(self) -> bool:
        return self.check_y.isChecked()

    def line_width(self) -> int:
        return self.spin_width.value() if self.spin_width else 1

    def initialize(self, on_color_pick) -> None:
        tree = self.treeWidget()

        # Col 1: colour swatch (data channels only)
        if not self.is_time:
            self.btn_color = QtWidgets.QPushButton()
            self.btn_color.setFixedSize(22, 18)
            self.btn_color.setToolTip("Pick channel colour")
            self._apply_color_button()
            self.btn_color.clicked.connect(lambda: on_color_pick(self))
            tree.setItemWidget(self, _C_COLOR, self.btn_color)

        # Col 2: X checkbox
        self.check_x = QtWidgets.QCheckBox()
        self.check_x.setChecked(self.is_time)
        tree.setItemWidget(self, _C_X, self.check_x)

        # Col 3: Y checkbox
        self.check_y = QtWidgets.QCheckBox()
        self.check_y.setChecked(not self.is_time)
        if self.is_time:
            self.check_y.setChecked(False)
            self.check_y.setEnabled(False)
        tree.setItemWidget(self, _C_Y, self.check_y)

        # Cols 4-5: min / max (text, updated on redraw)
        self.setText(_C_MIN, f"{np.min(self.values):.6g}")
        self.setText(_C_MAX, f"{np.max(self.values):.6g}")
        for col in (_C_MIN, _C_MAX):
            self.setTextAlignment(col, QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)

        # Col 6: line width (data channels only)
        if not self.is_time:
            self.spin_width = QtWidgets.QSpinBox()
            self.spin_width.setRange(1, 8)
            self.spin_width.setValue(2)
            self.spin_width.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
            self.spin_width.setToolTip("Line width (px)")
            tree.setItemWidget(self, _C_WIDTH, self.spin_width)

        # Col 7: shift
        self.spin_shift = QtWidgets.QDoubleSpinBox()
        self.spin_shift.setDecimals(4)
        self.spin_shift.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin_shift.setToolTip("Additive shift applied to values")
        tree.setItemWidget(self, _C_SHIFT, self.spin_shift)

        # Col 8: multiplier (data channels only)
        if not self.is_time:
            self.spin_mult = QtWidgets.QDoubleSpinBox()
            self.spin_mult.setDecimals(4)
            self.spin_mult.setRange(-1_000_000, 1_000_000)
            self.spin_mult.setSingleStep(0.1)
            self.spin_mult.setValue(1.0)
            self.spin_mult.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
            self.spin_mult.setToolTip("Multiplicative scale factor")
            tree.setItemWidget(self, _C_MULT, self.spin_mult)

        # Col 9: show sample points (data channels only)
        if not self.is_time:
            self.check_points = QtWidgets.QCheckBox()
            self.check_points.setChecked(False)
            self.check_points.setToolTip("Show sample points")
            tree.setItemWidget(self, _C_PTS, self.check_points)

        # Dim all controls for time channel
        if self.is_time:
            dim = QtGui.QBrush(QtGui.QColor("#aaaaaa"))
            for col in range(_C_COLOR, _NUM_COLS):
                self.setForeground(col, dim)

    def _apply_color_button(self) -> None:
        if self.btn_color is not None:
            self.btn_color.setStyleSheet(
                f"background-color: {self.color}; border: 1px solid #999; border-radius: 2px;"
            )

    def apply_color(self) -> None:
        self._apply_color_button()
        r, g, b = _hex_to_rgb(self.color)
        if self.curve:
            self.curve.setPen(pg.mkPen(color=(r, g, b), width=self.line_width()))
        if self.scatter:
            self.scatter.setPen(pg.mkPen(r, g, b))
            self.scatter.setBrush(pg.mkBrush(r, g, b, 200))

    def data_to_plot(self) -> np.ndarray:
        return self.transform.apply(self.values)

    def update_plot(self, x: np.ndarray) -> None:
        if self.curve is None:
            return
        self.transform.set_shift(self.spin_shift.value())
        if not self.is_time and self.spin_mult:
            self.transform.set_multiplier(self.spin_mult.value())
        data_min = float(np.min(self.values))
        data_max = float(np.max(self.values))
        span = data_max - data_min
        self.spin_shift.setRange(
            -abs(data_min) - abs(100 * span),
            abs(data_max) + abs(100 * span),
        )
        self.spin_shift.setSingleStep(span / 1000 if span > 0 else 1.0)
        y = self.data_to_plot()
        self.curve.setData(x, y)
        self.setText(_C_MIN, f"{float(np.min(y)):.6g}")
        self.setText(_C_MAX, f"{float(np.max(y)):.6g}")
        if self.scatter and self.check_points and self.check_points.isChecked():
            self.scatter.setData(x=x, y=y)


class SensorPlotWidget(QtWidgets.QWidget):
    """Plot widget: white background, professional palette,
    colour picker, legend, axis labels, crosshair, scatter points, fit/zoom."""

    def __init__(self, dataset: SensorDataset | None = None, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.dataset = dataset
        self.matrices: list[MatrixItem] = []
        self.color_counter = 0
        self._legend: pg.LegendItem | None = None
        self._crosshair_enabled = False
        self._vline: pg.InfiniteLine | None = None
        self._hline: pg.InfiniteLine | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # ---- Left panel: tree + axis-labels ----
        left_widget = QtWidgets.QWidget()
        left_vbox = QtWidgets.QVBoxLayout(left_widget)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(4)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(_COL_HEADERS)
        self.tree.setColumnCount(_NUM_COLS)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QtWidgets.QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

        header = self.tree.header()
        header.setSectionsMovable(False)
        for col, w in enumerate(_COL_WIDTHS):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.tree.setColumnWidth(col, w)
        # Col 0 can stretch but is still interactive after a manual resize
        header.setStretchLastSection(False)

        left_vbox.addWidget(self.tree, stretch=1)

        # Axis labels panel
        labels_box = QtWidgets.QGroupBox("Axis labels")
        labels_box.setFlat(True)
        labels_grid = QtWidgets.QFormLayout(labels_box)
        labels_grid.setContentsMargins(4, 4, 4, 4)
        labels_grid.setSpacing(3)
        self.edit_title = QtWidgets.QLineEdit()
        self.edit_title.setPlaceholderText("Chart title…")
        self.edit_xlabel = QtWidgets.QLineEdit()
        self.edit_xlabel.setPlaceholderText("X axis label…")
        self.edit_ylabel = QtWidgets.QLineEdit()
        self.edit_ylabel.setPlaceholderText("Y axis label…")
        for edit in (self.edit_title, self.edit_xlabel, self.edit_ylabel):
            edit.setClearButtonEnabled(True)
        self.edit_title.textChanged.connect(lambda t: self.pg_plot.setTitle(t or None))
        self.edit_xlabel.textChanged.connect(lambda t: self.pg_plot.setLabel("bottom", t))
        self.edit_ylabel.textChanged.connect(lambda t: self.pg_plot.setLabel("left", t))
        labels_grid.addRow("Title", self.edit_title)
        labels_grid.addRow("X axis", self.edit_xlabel)
        labels_grid.addRow("Y axis", self.edit_ylabel)
        left_vbox.addWidget(labels_box)

        splitter.addWidget(left_widget)

        # ---- Right panel: plot ----
        right_widget = QtWidgets.QWidget()
        right_vbox = QtWidgets.QVBoxLayout(right_widget)
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.setSpacing(2)

        self.pg_window = pg.GraphicsLayoutWidget()
        self.pg_window.setBackground(_PLOT_BG)
        self.pg_plot = self.pg_window.addPlot()
        self._style_plot()
        right_vbox.addWidget(self.pg_window, stretch=1)

        self._coord_label = QtWidgets.QLabel("")
        self._coord_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self._coord_label.setStyleSheet("color: #555; font-size: 10px; padding: 0 6px;")
        self._coord_label.hide()
        right_vbox.addWidget(self._coord_label)

        splitter.addWidget(right_widget)
        splitter.setSizes([340, 760])

    def _style_plot(self) -> None:
        axis_pen = pg.mkPen(_AXIS_PEN, width=1)
        text_pen = pg.mkPen(_AXIS_PEN)
        for axis in ("left", "bottom", "top", "right"):
            ax = self.pg_plot.getAxis(axis)
            ax.setPen(axis_pen)
            ax.setTextPen(text_pen)
        self.pg_plot.showGrid(x=True, y=True, alpha=_GRID_ALPHA)
        self.pg_plot.getViewBox().setMenuEnabled(False)
        self.pg_plot.scene().sigMouseMoved.connect(self._on_mouse_moved)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_dataset(self, dataset: SensorDataset) -> None:
        self.dataset = dataset

    def load_sensor(self, sensor_name: str) -> None:
        if self.dataset is None:
            return
        matrix_data = self.dataset.get_matrix(sensor_name)
        if not matrix_data:
            return
        data, headers = matrix_data
        self._load_matrix(data, headers, sensor_name)

    def load_csv_matrix(self, name: str, data: np.ndarray, headers: list[str]) -> None:
        self._load_matrix(data, headers, name)

    def set_grid_visible(self, visible: bool) -> None:
        self.pg_plot.showGrid(x=visible, y=visible, alpha=_GRID_ALPHA if visible else 0)

    def set_legend_visible(self, visible: bool) -> None:
        if visible and self._legend is None:
            self._legend = self.pg_plot.addLegend(offset=(10, 10))
            self._legend.setLabelTextColor(_AXIS_PEN)
            self._rebuild_legend()
        elif not visible and self._legend is not None:
            self._legend.clear()
            self.pg_plot.legend = None
            self._legend = None

    def set_crosshair_visible(self, visible: bool) -> None:
        self._crosshair_enabled = visible
        if visible:
            if self._vline is None:
                self._vline = pg.InfiniteLine(
                    angle=90, movable=False,
                    pen=pg.mkPen("#888888", style=QtCore.Qt.PenStyle.DashLine, width=1),
                )
                self._hline = pg.InfiniteLine(
                    angle=0, movable=False,
                    pen=pg.mkPen("#888888", style=QtCore.Qt.PenStyle.DashLine, width=1),
                )
                self.pg_plot.addItem(self._vline, ignoreBounds=True)
                self.pg_plot.addItem(self._hline, ignoreBounds=True)
            self._vline.show()
            self._hline.show()
            self._coord_label.show()
        else:
            if self._vline:
                self._vline.hide()
                self._hline.hide()
            self._coord_label.hide()

    def fit_view(self) -> None:
        self.pg_plot.autoRange()

    def reset_zoom(self) -> None:
        for matrix in self.matrices:
            x_ch = matrix.channels[matrix.x_channel_idx]
            x_data = x_ch.data_to_plot()
            if len(x_data):
                self.pg_plot.setXRange(float(x_data[0]), float(x_data[-1]), padding=0.02)
                break

    def delete_selected(self) -> None:
        self._delete_selected()

    def delete_selected_channels(self) -> None:
        self._delete_selected()

    def export_selected(self) -> None:
        self._export_selected()

    # ------------------------------------------------------------------
    # Internal loading
    # ------------------------------------------------------------------

    def _load_matrix(self, data: np.ndarray, headers: list[str], name: str) -> None:
        matrix = MatrixItem(name)
        self.matrices.append(matrix)
        self.tree.addTopLevelItem(matrix)
        matrix.span_in_tree()

        for i, header in enumerate(headers):
            is_time = i == 0
            color = "#aaaaaa" if is_time else self._next_color()
            channel = ChannelItem(matrix, header, data[:, i], is_time=is_time, color=color)
            matrix.channels.append(channel)
            channel.initialize(on_color_pick=self._pick_channel_color)
            r, g, b = _hex_to_rgb(color)
            if is_time:
                pen = pg.mkPen(color=(170, 170, 170), width=1, style=QtCore.Qt.PenStyle.DashLine)
            else:
                pen = pg.mkPen(color=(r, g, b), width=2)
            channel.curve = self.pg_plot.plot(pen=pen)

            channel.check_x.clicked.connect(partial(self._on_x_changed, channel))
            channel.check_y.clicked.connect(partial(self._on_y_changed, channel))
            channel.spin_shift.valueChanged.connect(partial(self._on_shift_changed, channel))
            if not is_time:
                channel.spin_width.valueChanged.connect(partial(self._on_width_changed, channel))
                channel.spin_mult.valueChanged.connect(partial(self._on_channel_plot, channel))
                channel.check_points.stateChanged.connect(partial(self._on_points_toggled, channel))

        matrix.setExpanded(True)
        QtCore.QTimer.singleShot(0, self._update_all_plots)

    # ------------------------------------------------------------------
    # Color picker
    # ------------------------------------------------------------------

    def _pick_channel_color(self, channel: ChannelItem) -> None:
        r, g, b = _hex_to_rgb(channel.color)
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(r, g, b), self, f"Channel colour — {channel.name}")
        if color.isValid():
            channel.color = color.name()
            channel.apply_color()
            self._rebuild_legend()

    # ------------------------------------------------------------------
    # Mouse / crosshair
    # ------------------------------------------------------------------

    def _on_mouse_moved(self, pos) -> None:
        if not self._crosshair_enabled:
            return
        if self.pg_plot.sceneBoundingRect().contains(pos):
            mp = self.pg_plot.getViewBox().mapSceneToView(pos)
            x, y = mp.x(), mp.y()
            if self._vline:
                self._vline.setPos(x)
                self._hline.setPos(y)
            coord_text = f"x = {x:.4g}   y = {y:.4g}"
            self._coord_label.setText(coord_text)
            # Forward to PlotWindow status bar if available
            pw = getattr(self, "_plot_window_ref", None)
            if pw:
                pw.update_coord_label(coord_text)

    # ------------------------------------------------------------------
    # Tree interaction
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        pw = getattr(self, "_plot_window_ref", None)
        if pw and hasattr(pw, "_on_widget_selection_changed"):
            pw._on_widget_selection_changed(items)

    def _on_tree_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self.tree.itemAt(pos)
        menu = QtWidgets.QMenu(self)
        if isinstance(item, MatrixItem):
            menu.addAction("Reset all shifts", item.reset_shifts)
            menu.addAction("Reset all multipliers", item.reset_mults)
            menu.addSeparator()
            menu.addAction("Delete sensor", lambda: self._delete_item(item))
        elif isinstance(item, ChannelItem):
            menu.addAction("Delete channel", lambda: self._delete_item(item))
        else:
            return
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_x_changed(self, channel: ChannelItem) -> None:
        matrix = channel.parent()
        if channel.check_x.isChecked():
            for ch in matrix.channels:
                if ch is not channel:
                    ch.check_x.setChecked(False)
            matrix.x_channel_idx = matrix.channels.index(channel)
        else:
            matrix.channels[0].check_x.setChecked(True)
            matrix.x_channel_idx = 0
        self._update_matrix_plots(matrix)

    def _on_y_changed(self, channel: ChannelItem) -> None:
        matrix = channel.parent()
        x = matrix.channels[matrix.x_channel_idx].data_to_plot()
        channel.update_plot(x)
        channel.apply_color()
        visible = channel.check_y.isChecked()
        channel.curve.setVisible(visible)
        if channel.scatter:
            channel.scatter.setVisible(visible and channel.check_points.isChecked())
        self._rebuild_legend()

    def _on_shift_changed(self, channel: ChannelItem) -> None:
        matrix = channel.parent()
        if channel is matrix.channels[matrix.x_channel_idx]:
            self._update_matrix_plots(matrix)
        else:
            self._on_channel_plot(channel)

    def _on_width_changed(self, channel: ChannelItem) -> None:
        channel.apply_color()

    def _on_channel_plot(self, channel: ChannelItem) -> None:
        matrix = channel.parent()
        x = matrix.channels[matrix.x_channel_idx].data_to_plot()
        channel.update_plot(x)
        channel.apply_color()
        visible = channel.check_y.isChecked()
        channel.curve.setVisible(visible)
        if channel.scatter:
            channel.scatter.setVisible(visible and channel.check_points.isChecked())
        self._rebuild_legend()

    def _on_points_toggled(self, channel: ChannelItem) -> None:
        show = channel.check_points.isChecked() if channel.check_points else False
        if show:
            if channel.scatter is None:
                r, g, b = _hex_to_rgb(channel.color)
                channel.scatter = pg.ScatterPlotItem(
                    size=5,
                    pen=pg.mkPen(r, g, b),
                    brush=pg.mkBrush(r, g, b, 200),
                )
                self.pg_plot.addItem(channel.scatter)
            matrix = channel.parent()
            x = matrix.channels[matrix.x_channel_idx].data_to_plot()
            y = channel.data_to_plot()
            channel.scatter.setData(x=x, y=y)
            channel.scatter.setVisible(channel.check_y.isChecked())
        else:
            if channel.scatter:
                channel.scatter.hide()

    def _update_all_plots(self) -> None:
        for matrix in self.matrices:
            self._update_matrix_plots(matrix)

    def _update_matrix_plots(self, matrix: MatrixItem) -> None:
        x = matrix.channels[matrix.x_channel_idx].data_to_plot()
        for channel in matrix.channels:
            channel.update_plot(x)
            channel.apply_color()
            visible = channel.check_y.isChecked()
            channel.curve.setVisible(visible)
            if channel.scatter:
                pts_on = channel.check_points.isChecked() if channel.check_points else False
                channel.scatter.setVisible(visible and pts_on)
        self._rebuild_legend()

    def _rebuild_legend(self) -> None:
        if self._legend is None:
            return
        self._legend.clear()
        for matrix in self.matrices:
            for ch in matrix.channels:
                if not ch.is_time and ch.curve and ch.y:
                    self._legend.addItem(ch.curve, ch.name)

    # ------------------------------------------------------------------
    # Delete / export
    # ------------------------------------------------------------------

    def _delete_selected(self) -> None:
        for item in list(self.tree.selectedItems()):
            self._delete_item(item)

    def _delete_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        if isinstance(item, MatrixItem):
            self.tree.invisibleRootItem().removeChild(item)
            for ch in item.channels:
                if ch.curve:
                    self.pg_plot.removeItem(ch.curve)
                if ch.scatter:
                    self.pg_plot.removeItem(ch.scatter)
            self.matrices.remove(item)
        elif isinstance(item, ChannelItem):
            matrix = item.parent()
            if item.curve:
                self.pg_plot.removeItem(item.curve)
            if item.scatter:
                self.pg_plot.removeItem(item.scatter)
            matrix.removeChild(item)
            if item in matrix.channels:
                matrix.channels.remove(item)
            if not matrix.channels:
                self._delete_item(matrix)
        self._update_all_plots()

    def _export_selected(self) -> None:
        items = self.tree.selectedItems()
        if len(items) != 1 or not isinstance(items[0], MatrixItem):
            QtWidgets.QMessageBox.information(
                self, "Export", "Select a sensor row (top-level) to export its data."
            )
            return
        matrix = items[0]
        filepath, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Data", matrix.name,
            "CSV Files (*.csv);;Tab-separated (*.txt);;All Files (*)"
        )
        if not filepath:
            return
        data = np.column_stack([ch.data_to_plot() for ch in matrix.channels])
        headers = [ch.name for ch in matrix.channels]
        delimiter = "," if filepath.endswith(".csv") else "\t"
        try:
            DataExporter.export_matrix(filepath, data, headers, delimiter=delimiter)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export Error", f"Failed to export: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_color(self) -> str:
        color = COLOR_PALETTE[self.color_counter % len(COLOR_PALETTE)]
        self.color_counter += 1
        return color
