from __future__ import annotations

import math
from functools import partial

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from quino.viewer.dataset import SensorDataset
from quino.viewer.transform import ChannelTransform
from quino.viewer.exporter import DataExporter


COLOR_SET = [
    (255, 255, 0),
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 127, 0),
    (0, 255, 127),
    (127, 0, 255),
    (255, 0, 127),
    (127, 255, 0),
    (0, 127, 255),
]


class MatrixItem(QtWidgets.QTreeWidgetItem):
    """Tree widget item representing a sensor matrix."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.channels: list[ChannelItem] = []
        self.x_channel_idx = 0
        self.setText(0, name)
        for i in range(8):
            self.setBackground(i, QtGui.QColor(200, 200, 200))

    def initialize(self) -> None:
        """Initialize reset buttons."""
        reset_shift = QtWidgets.QPushButton("Reset")
        reset_shift.clicked.connect(self.reset_shifts)
        self.treeWidget().setItemWidget(self, 6, reset_shift)

        reset_mult = QtWidgets.QPushButton("Reset")
        reset_mult.clicked.connect(self.reset_mults)
        self.treeWidget().setItemWidget(self, 7, reset_mult)

    def reset_shifts(self) -> None:
        """Reset all shifts to 0."""
        for channel in self.channels:
            channel.transform.set_shift(0.0)
            channel.spin_shift.setValue(0.0)

    def reset_mults(self) -> None:
        """Reset all multipliers to 1."""
        for i, channel in enumerate(self.channels):
            if i > 0:
                channel.transform.set_multiplier(1.0)
                channel.spin_mult.setValue(1.0)


class ChannelItem(QtWidgets.QTreeWidgetItem):
    """Tree widget item representing a channel."""

    def __init__(self, parent: MatrixItem, name: str, data: np.ndarray, is_time: bool = False, color: tuple = (255, 255, 255)):
        super().__init__(parent)
        self.name = name
        self.values = data
        self.is_time = is_time
        self.color = color
        self.curve: pg.PlotDataItem | None = None
        self.transform = ChannelTransform()
        if not is_time:
            self.transform.set_multiplier(1.0)

    @property
    def x(self) -> bool:
        return self.check_x.isChecked()

    @property
    def y(self) -> bool:
        return self.check_y.isChecked()

    def initialize(self) -> None:
        """Initialize UI elements."""
        tree = self.treeWidget()

        self.check_x = QtWidgets.QCheckBox()
        if self.is_time:
            self.check_x.setChecked(True)
        tree.setItemWidget(self, 1, self.check_x)
        self.setBackground(1, QtGui.QColor(*self.color))

        self.check_y = QtWidgets.QCheckBox()
        self.check_y.setChecked(not self.is_time)
        tree.setItemWidget(self, 2, self.check_y)
        self.setBackground(2, QtGui.QColor(*self.color))

        self.setText(3, self.name)
        self.setText(4, f"{np.min(self.values):.6g}")
        self.setText(5, f"{np.max(self.values):.6g}")

        self.spin_shift = QtWidgets.QDoubleSpinBox()
        self.spin_shift.setDecimals(6)
        tree.setItemWidget(self, 6, self.spin_shift)

        if not self.is_time:
            self.spin_mult = QtWidgets.QDoubleSpinBox()
            self.spin_mult.setDecimals(6)
            self.spin_mult.setRange(-1000000, 1000000)
            self.spin_mult.setSingleStep(0.1)
            self.spin_mult.setValue(1.0)
            tree.setItemWidget(self, 7, self.spin_mult)

        if self.is_time:
            self.check_y.setChecked(False)
            self.check_y.setEnabled(False)
            for col in range(2, 8):
                self.setForeground(col, QtGui.QBrush(QtGui.QColor("grey")))

    def set_color(self) -> None:
        """Update curve color."""
        if self.curve:
            self.curve.setPen(pg.mkPen(color=self.color))

    def data_to_plot(self) -> np.ndarray:
        """Get transformed data."""
        return self.transform.apply(self.values)

    def update_plot(self, x: np.ndarray) -> None:
        """Update curve with transformed data."""
        if self.curve is None:
            return
        self.transform.set_shift(self.spin_shift.value())
        if not self.is_time:
            self.transform.set_multiplier(self.spin_mult.value())
        data_min, data_max = np.min(self.values), np.max(self.values)
        self.spin_shift.setDecimals(6)
        self.spin_shift.setRange(
            -abs(data_min) - abs(100 * (data_max - data_min)),
            abs(data_max) + abs(100 * (data_max - data_min)),
        )
        self.spin_shift.setSingleStep((data_max - data_min) / 1000 if data_max != data_min else 1.0)
        y = self.data_to_plot()
        self.curve.setData(x, y)
        self.setText(4, f"{np.min(y):.6g}")
        self.setText(5, f"{np.max(y):.6g}")


class SensorPlotWidget(QtWidgets.QWidget):
    """Independent plot viewer for sensor data."""

    def __init__(self, dataset: SensorDataset, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.dataset = dataset
        self.matrices: list[MatrixItem] = []
        self.color_counter = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the UI layout."""
        layout = QtWidgets.QVBoxLayout(self)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["", "x", "y", "Name", "Min", "Max", "+", "x", ""])
        self.tree.setColumnCount(9)
        self.tree.selectionMode = QtWidgets.QTreeWidget.SelectionMode.ExtendedSelection
        for col in range(1, self.tree.columnCount()):
            self.tree.resizeColumnToContents(col)
        self.tree.expandAll()
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.tree)

        right_layout = QtWidgets.QVBoxLayout()
        self.pg_window = pg.GraphicsLayoutWidget()
        self.pg_plot = self.pg_window.addPlot()
        self.pg_plot.showGrid(True, True, 0.5)
        right_layout.addWidget(self.pg_window)

        button_layout = QtWidgets.QHBoxLayout()
        self.btn_delete = QtWidgets.QPushButton("Delete")
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_delete.setEnabled(False)
        button_layout.addWidget(self.btn_delete)

        self.btn_export = QtWidgets.QPushButton("Export")
        self.btn_export.clicked.connect(self._export_selected)
        self.btn_export.setEnabled(False)
        button_layout.addWidget(self.btn_export)
        right_layout.addLayout(button_layout)

        right_widget = QtWidgets.QWidget()
        right_widget.setLayout(right_layout)
        splitter.addWidget(right_widget)
        splitter.setSizes([200, 800])

        self.setLayout(layout)

    def load_sensor(self, sensor_name: str) -> None:
        """Load a sensor into the plot."""
        matrix_data = self.dataset.get_matrix(sensor_name)
        if not matrix_data:
            return
        data, headers = matrix_data
        self._load_matrix(data, headers, sensor_name)

    def _load_matrix(self, data: np.ndarray, headers: list[str], name: str) -> None:
        """Load matrix data into tree and plot."""
        matrix = MatrixItem(name)
        self.matrices.append(matrix)
        self.tree.addTopLevelItem(matrix)
        matrix.initialize()

        for i, header in enumerate(headers):
            is_time = i == 0
            color = (255, 255, 255) if is_time else self._next_color()
            channel = ChannelItem(matrix, header, data[:, i], is_time=is_time, color=color)
            matrix.channels.append(channel)
            channel.initialize()
            channel.curve = self.pg_plot.plot()
            channel.check_x.clicked.connect(partial(self._on_x_changed, channel))
            channel.check_y.clicked.connect(partial(self._on_channel_plot, channel))
            channel.spin_shift.valueChanged.connect(partial(self._on_shift_changed, channel))
            if not is_time:
                channel.spin_mult.valueChanged.connect(partial(self._on_channel_plot, channel))

        matrix.setExpanded(True)
        QtCore.QTimer.singleShot(0, self._update_all_plots)

    def _on_selection_changed(self) -> None:
        """Handle tree selection change."""
        items = self.tree.selectedItems()
        self.btn_delete.setEnabled(len(items) > 0)
        self.btn_export.setEnabled(len(items) == 1 and isinstance(items[0], MatrixItem))

    def _delete_selected(self) -> None:
        """Delete selected items."""
        items = list(self.tree.selectedItems())
        for item in items:
            self._delete_item(item)

    def _delete_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        """Delete an item and its curves."""
        if isinstance(item, MatrixItem):
            self.tree.invisibleRootItem().removeChild(item)
            for channel in item.channels:
                if channel.curve:
                    self.pg_plot.removeItem(channel.curve)
            self.matrices.remove(item)
        elif isinstance(item, ChannelItem):
            if item.curve:
                self.pg_plot.removeItem(item.curve)
            item.parent().removeChild(item)
            item.parent().channels.remove(item)
            if not item.parent().channels:
                self._delete_item(item.parent())
        self._update_all_plots()

    def _export_selected(self) -> None:
        """Export selected matrix."""
        items = self.tree.selectedItems()
        if len(items) != 1 or not isinstance(items[0], MatrixItem):
            return
        matrix = items[0]
        filepath, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Matrix", matrix.name, "Text Files (*.txt);;CSV Files (*.csv)"
        )
        if not filepath:
            return
        data = np.column_stack([channel.data_to_plot() for channel in matrix.channels])
        headers = [channel.name for channel in matrix.channels]
        try:
            DataExporter.export_matrix(filepath, data, headers)
            QtWidgets.QMessageBox.information(self, "Export", "Data exported successfully")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Export Error", f"Failed to export: {e}")

    def _on_x_changed(self, channel: ChannelItem) -> None:
        """Handle X axis selection."""
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

    def _on_shift_changed(self, channel: ChannelItem) -> None:
        """Handle shift change."""
        matrix = channel.parent()
        if channel == matrix.channels[matrix.x_channel_idx]:
            self._update_matrix_plots(matrix)
        else:
            self._on_channel_plot(channel)

    def _on_channel_plot(self, channel: ChannelItem) -> None:
        """Update a single channel plot."""
        matrix = channel.parent()
        x = matrix.channels[matrix.x_channel_idx].data_to_plot()
        channel.update_plot(x)
        channel.set_color()
        if channel.check_y.isChecked():
            channel.curve.show()
        else:
            channel.curve.hide()

    def _update_all_plots(self) -> None:
        """Update all plots."""
        for matrix in self.matrices:
            self._update_matrix_plots(matrix)

    def _update_matrix_plots(self, matrix: MatrixItem) -> None:
        """Update all plots in a matrix."""
        x = matrix.channels[matrix.x_channel_idx].data_to_plot()
        for channel in matrix.channels:
            channel.update_plot(x)
            channel.set_color()
            if channel.check_y.isChecked():
                channel.curve.show()
            else:
                channel.curve.hide()

    def _next_color(self) -> tuple[int, int, int]:
        """Get next color from palette."""
        color = COLOR_SET[self.color_counter % len(COLOR_SET)]
        self.color_counter += 1
        return color
