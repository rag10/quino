from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


_PROPERTY_DIMENSION_HINTS: dict[str, str] = {
    "x": "length (e.g. 50 mm)",
    "y": "length (e.g. 50 mm)",
    "origin_x": "length (e.g. 50 mm)",
    "origin_y": "length (e.g. 50 mm)",
    "travel_min": "length (e.g. 50 mm)",
    "travel_max": "length (e.g. 50 mm)",
    "angle": "angle (e.g. 90 deg)",
    "mass": "mass (e.g. 1.5 kg)",

    "radius": "length (e.g. 25 mm)",
    "value": "see constraint type",
    "law": "angle or length (e.g. 90 deg * t / 1 s)",
    "friction_pin_radius": "pin radius in mm (e.g. 5 mm)",
}


class _InspectorCompatItem:
    def __init__(self, owner: "InspectorPropertyWidget", row_info: dict[str, object], column: int) -> None:
        self._owner = owner
        self._row_info = row_info
        self._column = column

    def text(self) -> str:
        if self._column == 0:
            return str(self._row_info["label"])
        if self._column == 2:
            return str(self._row_info["evaluated"])
        editor = self._row_info.get("editor")
        if isinstance(editor, QtWidgets.QLineEdit):
            return editor.text()
        if isinstance(editor, QtWidgets.QComboBox):
            return editor.currentText()
        return str(self._row_info["value"])

    def setText(self, value: str) -> None:
        if self._column != 1:
            return
        editor = self._row_info.get("editor")
        path = str(self._row_info["path"])
        kind = str(self._row_info["kind"])
        if isinstance(editor, QtWidgets.QLineEdit):
            editor.setText(value)
            self._owner.property_changed.emit(path, value, kind)
        elif isinstance(editor, QtWidgets.QComboBox):
            editor.setCurrentText(value)

    def flags(self) -> QtCore.Qt.ItemFlag:
        flags = QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
        if self._column == 1 and bool(self._row_info.get("enabled", False)):
            kind = str(self._row_info["kind"])
            if kind not in {"readonly", "key", "section_header"}:
                flags |= QtCore.Qt.ItemFlag.ItemIsEditable
        return flags


class InspectorPropertyWidget(QtWidgets.QWidget):
    """Custom form widget for displaying entity properties with appropriate input controls."""

    property_changed = QtCore.Signal(str, str, str)  # (property_path, new_value, kind)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self._row_widgets: dict[str, QtWidgets.QWidget] = {}
        self._compat_rows: list[dict[str, object]] = []

    def clear_properties(self):
        """Remove all property rows."""
        while self.layout.count() > 0:
            child = self.layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._row_widgets.clear()
        self._compat_rows.clear()

    def add_property(self, label: str, path: str, value: str, kind: str, evaluated: str, enabled: bool = True):
        """Add a single property row to the form."""
        row_widget = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        # Label
        label_widget = QtWidgets.QLabel(label)
        label_widget.setMinimumWidth(100)
        label_widget.setMaximumWidth(150)
        row_layout.addWidget(label_widget)

        # Input widget (determined by kind)
        input_widget = self._create_input_widget(path, value, kind, evaluated, enabled)
        row_layout.addWidget(input_widget, stretch=1)

        # Store for later reference
        self._row_widgets[path] = row_widget
        self._compat_rows.append({
            "label": label,
            "path": path,
            "value": value,
            "kind": kind,
            "evaluated": evaluated,
            "enabled": enabled,
            "editor": self._extract_editor(input_widget),
            "widget": input_widget,
        })
        self.layout.addWidget(row_widget)

    def rowCount(self) -> int:
        return len(self._compat_rows)

    def item(self, row: int, column: int):
        if row < 0 or row >= len(self._compat_rows):
            return None
        if column not in {0, 1, 2}:
            return None
        return _InspectorCompatItem(self, self._compat_rows[row], column)

    def cellWidget(self, row: int, column: int):
        if row < 0 or row >= len(self._compat_rows) or column != 1:
            return None
        return self._compat_rows[row].get("editor")

    def _extract_editor(self, widget: QtWidgets.QWidget) -> QtWidgets.QWidget | None:
        if isinstance(widget, (QtWidgets.QLineEdit, QtWidgets.QComboBox)):
            return widget
        editor = widget.findChild(QtWidgets.QLineEdit)
        if editor is not None:
            return editor
        return widget.findChild(QtWidgets.QComboBox)

    def _create_input_widget(self, path: str, value: str, kind: str, evaluated: str, enabled: bool) -> QtWidgets.QWidget:
        """Factory method to create the appropriate input widget based on kind."""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if kind == "section_header":
            section_label = QtWidgets.QLabel(value)
            section_label.setStyleSheet("color: #888888; font-style: italic;")
            layout.addWidget(section_label)
            layout.addStretch()
            return container

        elif kind == "readonly":
            value_label = QtWidgets.QLabel(evaluated)
            layout.addWidget(value_label)
            layout.addStretch()
            return container

        elif kind == "boolean":
            combo = QtWidgets.QComboBox()
            combo.addItems(["false", "true"])
            combo.setCurrentText(value)
            combo.setEnabled(enabled)
            combo.currentTextChanged.connect(lambda text, p=path, k=kind: self.property_changed.emit(p, text, k))
            layout.addWidget(combo)
            layout.addStretch()
            return container

        elif kind == "color":
            preview = QtWidgets.QLabel()
            preview.setFixedSize(20, 20)
            preview.setStyleSheet(f"background-color: {value}; border: 1px solid #888;")
            layout.addWidget(preview)

            def pick_color():
                color = QtWidgets.QColorDialog.getColor(
                    QtGui.QColor(value), self, "Choose Color"
                )
                if color.isValid():
                    new_color = color.name()
                    preview.setStyleSheet(f"background-color: {new_color}; border: 1px solid #888;")
                    self.property_changed.emit(path, new_color, kind)

            pick_btn = QtWidgets.QPushButton("…")
            pick_btn.setFixedWidth(28)
            pick_btn.setFixedHeight(20)
            pick_btn.setEnabled(enabled)
            pick_btn.clicked.connect(pick_color)
            layout.addWidget(pick_btn)
            layout.addStretch()
            return container

        elif kind in {"expression", "expression_or_null"}:
            text_input = QtWidgets.QLineEdit(value)
            text_input.setEnabled(enabled)
            text_input.editingFinished.connect(lambda p=path, w=text_input, k=kind: self.property_changed.emit(p, w.text(), k))
            layout.addWidget(text_input)

            eval_label = QtWidgets.QLabel(evaluated)
            eval_label.setStyleSheet("color: #666; font-size: 9pt;")
            eval_label.setMaximumWidth(150)
            layout.addWidget(eval_label)
            return container

        elif kind == "key":
            key_label = QtWidgets.QLabel(value)
            mono_font = QtGui.QFont("Courier New", key_label.font().pointSize() - 1)
            key_label.setFont(mono_font)
            key_label.setStyleSheet("color: #666; background-color: #f0f0f0; padding: 2px;")
            layout.addWidget(key_label)
            layout.addStretch()
            return container

        else:
            fallback_label = QtWidgets.QLabel(value)
            layout.addWidget(fallback_label)
            layout.addStretch()
            return container
