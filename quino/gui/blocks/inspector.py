"""Property inspector for selected blocks."""

from __future__ import annotations

import ast
from typing import Any

from PySide6 import QtCore, QtWidgets

from quino.simulation.sensor_expressions import sensor_channel_keys


class BlockInspector(QtWidgets.QWidget):
    """Form panel that shows editable parameters of the selected block."""

    parametersChanged = QtCore.Signal(str, dict)  # instance_id, new_params

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._instance_id: str | None = None
        self._block_type: str = ""
        self._project = None
        self._layout = QtWidgets.QFormLayout(self)
        self._layout.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        self._fields: dict[str, QtWidgets.QWidget] = {}
        self._clear_form()

    def set_project(self, project: Any | None) -> None:
        self._project = project

    def _clear_form(self) -> None:
        while self._layout.rowCount() > 0:
            self._layout.removeRow(0)
        self._fields.clear()
        self._instance_id = None
        self._block_type = ""
        self._layout.addRow(QtWidgets.QLabel("Select a block to edit its properties."))

    def set_block(self, instance_id: str, block_type: str, parameters: dict[str, Any]) -> None:
        self._clear_form()
        self._instance_id = instance_id
        self._block_type = block_type
        self._layout.addRow("Instance ID:", QtWidgets.QLabel(instance_id))
        self._layout.addRow("Type:", QtWidgets.QLabel(block_type))
        self._layout.addRow(self._horizontal_line())

        for key, value in parameters.items():
            if key.startswith("_"):
                continue  # skip internal keys like _position
            widget = self._widget_for_value(key, value)
            self._fields[key] = widget
            self._layout.addRow(f"{key}:", widget)
            if hasattr(widget, "editingFinished"):
                widget.editingFinished.connect(self._on_field_changed)
            elif hasattr(widget, "textChanged"):
                widget.textChanged.connect(self._on_field_changed)
            elif hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._on_field_changed)

    def _widget_for_value(self, key: str, value: Any) -> QtWidgets.QWidget:
        semantic = self._semantic_widget(key, value)
        if semantic is not None:
            return semantic
        if isinstance(value, bool):
            cb = QtWidgets.QCheckBox()
            cb.setChecked(value)
            return cb
        if isinstance(value, (int, float)):
            sb = QtWidgets.QDoubleSpinBox()
            sb.setDecimals(6)
            sb.setRange(-1e12, 1e12)
            sb.setValue(float(value))
            return sb
        if isinstance(value, list) and len(value) > 0 and isinstance(value[0], (int, float)):
            # Vector value (e.g. direction)
            le = QtWidgets.QLineEdit(str(value))
            return le
        le = QtWidgets.QLineEdit(str(value))
        return le

    def _semantic_widget(self, key: str, value: Any) -> QtWidgets.QWidget | None:
        model = getattr(self._project, "model", None)
        if key == "sensor_id":
            return self._entity_combo(getattr(model, "sensors", []), str(value))
        if key == "load_id":
            return self._entity_combo(getattr(model, "loads", []), str(value))
        if key == "spring_id":
            return self._entity_combo(getattr(model, "springs", []), str(value))
        if key == "driver_id":
            return self._entity_combo(getattr(model, "drivers", []), str(value))
        if key == "body_id":
            return self._entity_combo(getattr(model, "bodies", []), str(value))
        if key == "component":
            combo = QtWidgets.QComboBox()
            for option in ("fx", "fy", "x", "y", "angle"):
                combo.addItem(option, option)
            self._set_combo_value(combo, str(value))
            return combo
        if key == "channel":
            combo = QtWidgets.QComboBox()
            self._populate_channel_combo(combo, current_value=str(value))
            return combo
        return None

    def _entity_combo(self, entities: list[Any], current_id: str) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.addItem("", "")
        for entity in entities:
            combo.addItem(f"{entity.name} ({entity.id})", entity.id)
        self._set_combo_value(combo, current_id)
        if self._project is not None and self._block_type in {"ModelSensor", "MBSSensor"}:
            combo.currentIndexChanged.connect(self._on_sensor_selection_changed)
        return combo

    def _set_combo_value(self, combo: QtWidgets.QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value or combo.itemText(index) == value:
                combo.setCurrentIndex(index)
                return
        if value:
            combo.addItem(value, value)
            combo.setCurrentIndex(combo.count() - 1)

    def _populate_channel_combo(self, combo: QtWidgets.QComboBox, current_value: str = "") -> None:
        combo.blockSignals(True)
        combo.clear()
        channels = self._available_sensor_channels()
        if not channels:
            channels = [("y", "y")]
        seen: set[str] = set()
        for channel, _unit in channels:
            if channel in seen:
                continue
            combo.addItem(channel, channel)
            seen.add(channel)
        self._set_combo_value(combo, current_value or combo.currentText())
        combo.blockSignals(False)

    def _available_sensor_channels(self) -> list[tuple[str, str]]:
        if self._project is None:
            return []
        sensor_widget = self._fields.get("sensor_id")
        sensor_id = ""
        if isinstance(sensor_widget, QtWidgets.QComboBox):
            sensor_id = str(sensor_widget.currentData() or "")
        if not sensor_id:
            return []
        sensor = next((item for item in self._project.model.sensors if item.id == sensor_id), None)
        if sensor is None:
            return []
        return sensor_channel_keys(sensor)

    def _on_sensor_selection_changed(self) -> None:
        channel_widget = self._fields.get("channel")
        if isinstance(channel_widget, QtWidgets.QComboBox):
            current_value = str(channel_widget.currentData() or channel_widget.currentText() or "")
            self._populate_channel_combo(channel_widget, current_value=current_value)
        self._on_field_changed()

    def _horizontal_line(self) -> QtWidgets.QFrame:
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        return line

    def _on_field_changed(self) -> None:
        if self._instance_id is None:
            return
        new_params: dict[str, Any] = {}
        for key, widget in self._fields.items():
            if isinstance(widget, QtWidgets.QCheckBox):
                new_params[key] = widget.isChecked()
            elif isinstance(widget, QtWidgets.QDoubleSpinBox):
                new_params[key] = widget.value()
            elif isinstance(widget, QtWidgets.QLineEdit):
                text = widget.text().strip()
                # Try to parse as number
                try:
                    if text.startswith("["):
                        new_params[key] = ast.literal_eval(text)
                    else:
                        new_params[key] = float(text)
                except (ValueError, SyntaxError):
                    new_params[key] = text
            elif isinstance(widget, QtWidgets.QComboBox):
                new_params[key] = widget.currentData() or widget.currentText()
        self.parametersChanged.emit(self._instance_id, new_params)
