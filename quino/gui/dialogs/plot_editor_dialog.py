from __future__ import annotations

from uuid import uuid4

from PySide6 import QtWidgets

from quino.domain.plotting import PlotDef, YSeries
from quino.gui.icons import get_icon
from quino.gui.theme import VIOLET
from quino.simulation.sensor_expressions import sensor_channel_keys


class _SeriesRow(QtWidgets.QWidget):
    def __init__(self, project, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.sensor_combo = QtWidgets.QComboBox(self)
        for sensor in project.model.sensors:
            self.sensor_combo.addItem(sensor.name, sensor.id)
        self.channel_combo = QtWidgets.QComboBox(self)
        self.label_edit = QtWidgets.QLineEdit(self)
        self.label_edit.setPlaceholderText("Label")
        self.color_edit = QtWidgets.QLineEdit(self)
        self.color_edit.setPlaceholderText("Color")
        layout.addWidget(self.sensor_combo)
        layout.addWidget(self.channel_combo)
        layout.addWidget(self.label_edit)
        layout.addWidget(self.color_edit)
        self.sensor_combo.currentIndexChanged.connect(self._reload_channels)
        self._reload_channels()

    def _reload_channels(self) -> None:
        self.channel_combo.clear()
        sensor_id = self.sensor_combo.currentData()
        sensor = next((item for item in self._project.model.sensors if item.id == sensor_id), None)
        if sensor is None:
            return
        for channel, _unit in sensor_channel_keys(sensor):
            self.channel_combo.addItem(channel, channel)

    def to_series(self) -> YSeries:
        return YSeries(
            sensor_id=str(self.sensor_combo.currentData()),
            channel=str(self.channel_combo.currentData()),
            label=self.label_edit.text().strip(),
            color=self.color_edit.text().strip(),
        )


class PlotEditorDialog(QtWidgets.QDialog):
    def __init__(self, analysis_type: str, project, sweeps=None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plot Editor")
        self.result_plot: PlotDef | None = None
        self._project = project
        self._sweeps = list(sweeps or [])
        self._rows: list[_SeriesRow] = []

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.title_edit = QtWidgets.QLineEdit(self)
        self.x_kind_combo = QtWidgets.QComboBox(self)
        self.x_target_combo = QtWidgets.QComboBox(self)
        for label, value in _allowed_x_kinds(analysis_type):
            self.x_kind_combo.addItem(label, value)
        self.x_kind_combo.currentIndexChanged.connect(self._reload_x_targets)
        form.addRow("Title", self.title_edit)
        form.addRow("X kind", self.x_kind_combo)
        form.addRow("X target", self.x_target_combo)
        layout.addLayout(form)

        self.rows_container = QtWidgets.QWidget(self)
        self.rows_layout = QtWidgets.QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.rows_container)

        add_btn = QtWidgets.QPushButton(get_icon("add", VIOLET, size=16), "Add series", self)
        add_btn.clicked.connect(self._add_row)
        layout.addWidget(add_btn)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._reload_x_targets()
        self._add_row()

    def _reload_x_targets(self) -> None:
        self.x_target_combo.clear()
        x_kind = self.x_kind_combo.currentData()
        if x_kind == "sweep_axis":
            for sweep in self._sweeps:
                self.x_target_combo.addItem(sweep.label or sweep.variable_kind, sweep.id)
            return
        if x_kind == "sensor_channel":
            for sensor in self._project.model.sensors:
                for channel, _unit in sensor_channel_keys(sensor):
                    self.x_target_combo.addItem(f"{sensor.name}:{channel}", f"{sensor.id}:{channel}")

    def _add_row(self) -> None:
        row = _SeriesRow(self._project, self.rows_container)
        self.rows_layout.addWidget(row)
        self._rows.append(row)

    def _accept(self) -> None:
        self.result_plot = PlotDef(
            id=f"pl_{uuid4().hex[:8]}",
            title=self.title_edit.text().strip() or "Plot",
            x_kind=str(self.x_kind_combo.currentData()),
            x_target=str(self.x_target_combo.currentData() or ""),
            y_series=[row.to_series() for row in self._rows],
        )
        self.accept()


def _allowed_x_kinds(analysis_type: str) -> list[tuple[str, str]]:
    if analysis_type == "dynamic":
        return [("Time", "time")]
    if analysis_type == "kinematic":
        return [("Sweep axis", "sweep_axis")]
    return [("Sensor channel", "sensor_channel")]
