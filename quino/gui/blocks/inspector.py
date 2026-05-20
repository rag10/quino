"""Property inspector for selected blocks."""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets


class BlockInspector(QtWidgets.QWidget):
    """Form panel that shows editable parameters of the selected block."""

    parametersChanged = QtCore.Signal(str, dict)  # instance_id, new_params

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._instance_id: str | None = None
        self._block_type: str = ""
        self._layout = QtWidgets.QFormLayout(self)
        self._layout.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        self._fields: dict[str, QtWidgets.QWidget] = {}
        self._clear_form()

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
                    if "," in text and text.startswith("["):
                        # list literal
                        new_params[key] = eval(text)
                    else:
                        new_params[key] = float(text)
                except ValueError:
                    new_params[key] = text
            elif isinstance(widget, QtWidgets.QComboBox):
                new_params[key] = widget.currentText()
        self.parametersChanged.emit(self._instance_id, new_params)
