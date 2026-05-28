from __future__ import annotations

from uuid import uuid4

from PySide6 import QtWidgets

from quino.domain.plotting import MetricDef
from quino.simulation.sensor_expressions import sensor_channel_keys

_KIND_LABELS = [
    ("Max", "max"),
    ("Min", "min"),
    ("RMS", "rms"),
    ("Value at time", "value_at_t"),
    ("Value at sweep indices", "value_at_sweep"),
    ("Spring energy", "spring_energy"),
]


class MetricEditorDialog(QtWidgets.QDialog):
    def __init__(
        self,
        project,
        metric: MetricDef | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Metric" if metric is not None else "New Metric")
        self.result_metric: MetricDef | None = None
        self._project = project
        self._original = metric

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.name_edit = QtWidgets.QLineEdit(self)
        self.name_edit.setPlaceholderText("Display name")
        form.addRow("Name", self.name_edit)

        self.key_edit = QtWidgets.QLineEdit(self)
        self.key_edit.setPlaceholderText("result_key")
        form.addRow("Key", self.key_edit)

        self.kind_combo = QtWidgets.QComboBox(self)
        for label, value in _KIND_LABELS:
            self.kind_combo.addItem(label, value)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        form.addRow("Kind", self.kind_combo)

        target_widget = QtWidgets.QWidget(self)
        target_layout = QtWidgets.QHBoxLayout(target_widget)
        target_layout.setContentsMargins(0, 0, 0, 0)
        self.sensor_combo = QtWidgets.QComboBox(self)
        self.channel_combo = QtWidgets.QComboBox(self)
        for sensor in project.model.sensors:
            self.sensor_combo.addItem(sensor.name, sensor.id)
        self.sensor_combo.currentIndexChanged.connect(self._reload_channels)
        target_layout.addWidget(self.sensor_combo)
        target_layout.addWidget(self.channel_combo)
        form.addRow("Target", target_widget)

        # Params stack
        self._params_stack = QtWidgets.QStackedWidget(self)
        self._t_page = QtWidgets.QWidget(self)
        t_layout = QtWidgets.QHBoxLayout(self._t_page)
        t_layout.setContentsMargins(0, 0, 0, 0)
        self._t_spin = QtWidgets.QDoubleSpinBox(self._t_page)
        self._t_spin.setRange(0.0, 1e6)
        self._t_spin.setDecimals(6)
        self._t_spin.setSuffix(" s")
        t_layout.addWidget(QtWidgets.QLabel("Time"))
        t_layout.addWidget(self._t_spin)
        t_layout.addStretch()

        self._indices_page = QtWidgets.QWidget(self)
        i_layout = QtWidgets.QHBoxLayout(self._indices_page)
        i_layout.setContentsMargins(0, 0, 0, 0)
        self._indices_edit = QtWidgets.QLineEdit(self._indices_page)
        self._indices_edit.setPlaceholderText("0, 1, 2")
        i_layout.addWidget(QtWidgets.QLabel("Indices"))
        i_layout.addWidget(self._indices_edit)
        i_layout.addStretch()

        self._params_stack.addWidget(self._t_page)
        self._params_stack.addWidget(self._indices_page)
        form.addRow("Params", self._params_stack)

        self.tags_edit = QtWidgets.QLineEdit(self)
        self.tags_edit.setPlaceholderText("comfort, validation, ...")
        form.addRow("Tags", self.tags_edit)

        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._reload_channels()
        self._on_kind_changed()

        if metric is not None:
            self._load_from_metric(metric)

    def _reload_channels(self) -> None:
        self.channel_combo.clear()
        sensor_id = self.sensor_combo.currentData()
        sensor = next((item for item in self._project.model.sensors if item.id == sensor_id), None)
        if sensor is None:
            return
        for channel, _unit in sensor_channel_keys(sensor):
            self.channel_combo.addItem(channel, channel)

    def _on_kind_changed(self) -> None:
        kind = self.kind_combo.currentData()
        needs_target = kind != "spring_energy"
        self.sensor_combo.setEnabled(needs_target)
        self.channel_combo.setEnabled(needs_target)

        if kind == "value_at_t":
            self._params_stack.setCurrentWidget(self._t_page)
            self._params_stack.setVisible(True)
        elif kind == "value_at_sweep":
            self._params_stack.setCurrentWidget(self._indices_page)
            self._params_stack.setVisible(True)
        else:
            self._params_stack.setVisible(False)

    def _load_from_metric(self, metric: MetricDef) -> None:
        self.name_edit.setText(metric.name)
        self.key_edit.setText(metric.key)
        for index in range(self.kind_combo.count()):
            if self.kind_combo.itemData(index) == metric.kind:
                self.kind_combo.setCurrentIndex(index)
                break

        if metric.target:
            parts = metric.target.split(":")
            sensor_id = parts[0] if parts else ""
            channel = parts[1] if len(parts) > 1 else ""
            for index in range(self.sensor_combo.count()):
                if self.sensor_combo.itemData(index) == sensor_id:
                    self.sensor_combo.setCurrentIndex(index)
                    break
            self._reload_channels()
            for index in range(self.channel_combo.count()):
                if self.channel_combo.itemData(index) == channel:
                    self.channel_combo.setCurrentIndex(index)
                    break

        if metric.kind == "value_at_t":
            self._t_spin.setValue(float(metric.params.get("t", 0.0)))
        elif metric.kind == "value_at_sweep":
            indices = metric.params.get("indices", [])
            self._indices_edit.setText(", ".join(str(i) for i in indices))

        self.tags_edit.setText(", ".join(metric.tags))

    def _accept(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            QtWidgets.QMessageBox.warning(self, "Validation", "Key is required.")
            return

        kind = self.kind_combo.currentData()
        target = ""
        if kind != "spring_energy":
            sensor_id = self.sensor_combo.currentData()
            channel = self.channel_combo.currentData()
            if sensor_id and channel:
                target = f"{sensor_id}:{channel}"
            else:
                QtWidgets.QMessageBox.warning(
                    self, "Validation", "Target sensor and channel are required."
                )
                return

        params: dict = {}
        if kind == "value_at_t":
            params["t"] = float(self._t_spin.value())
        elif kind == "value_at_sweep":
            text = self._indices_edit.text().strip()
            try:
                params["indices"] = [int(item.strip()) for item in text.split(",") if item.strip()]
            except ValueError:
                QtWidgets.QMessageBox.warning(
                    self, "Validation", "Indices must be comma-separated integers."
                )
                return

        tags = [item.strip() for item in self.tags_edit.text().split(",") if item.strip()]

        metric_id = self._original.id if self._original is not None else f"mt_{uuid4().hex[:8]}"
        self.result_metric = MetricDef(
            id=metric_id,
            key=key,
            name=self.name_edit.text().strip() or key,
            kind=kind,
            target=target,
            params=params,
            tags=tags,
        )
        self.accept()
