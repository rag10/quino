from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


_PROPERTY_DIMENSION_HINTS: dict[str, str] = {
    "x": "length (e.g. 50 mm)",
    "y": "length (e.g. 50 mm)",
    "origin_x": "length (e.g. 50 mm)",
    "origin_y": "length (e.g. 50 mm)",
    "travel_min": "length (e.g. 50 mm)",
    "travel_max": "length (e.g. 50 mm)",
    "angle_limit_positive": "angle from model zero (e.g. 30 deg)",
    "angle_limit_negative": "angle from model zero (e.g. 15 deg)",
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
    override_reset_requested = QtCore.Signal(str)  # property_path

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
        # Outer container supports an optional hint label below the row
        outer_widget = QtWidgets.QWidget()
        outer_layout = QtWidgets.QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

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

        outer_layout.addWidget(row_widget)

        # Store for later reference (outer_widget allows hint injection)
        self._row_widgets[path] = outer_widget
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
        self.layout.addWidget(outer_widget)

    def add_property_combo(
        self,
        label: str,
        path: str,
        value: str,
        choices: list[tuple[str, str]],
        kind: str = "combo",
        enabled: bool = True,
    ) -> None:
        """Combo with (label, value) pairs. The label is shown to the user;
        the value is what's emitted via property_changed. The current `value`
        selects the matching pair (when present), else falls back to the first
        item or an empty entry."""
        outer_widget = QtWidgets.QWidget()
        outer_layout = QtWidgets.QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        row_widget = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label_widget = QtWidgets.QLabel(label)
        label_widget.setMinimumWidth(100)
        label_widget.setMaximumWidth(150)
        row_layout.addWidget(label_widget)

        combo = QtWidgets.QComboBox()
        combo.setEnabled(enabled)
        selected_index = -1
        for i, (lbl, val) in enumerate(choices):
            combo.addItem(lbl, userData=val)
            if val == value:
                selected_index = i
        if selected_index == -1 and value:
            # Stale value: keep it visible so user can see what was stored.
            combo.addItem(f"{value} (unknown)", userData=value)
            selected_index = combo.count() - 1
        if selected_index >= 0:
            combo.setCurrentIndex(selected_index)
        combo.currentIndexChanged.connect(
            lambda idx, p=path, k=kind, c=combo: self.property_changed.emit(
                p, str(c.itemData(idx) if c.itemData(idx) is not None else c.currentText()), k
            )
        )
        row_layout.addWidget(combo, stretch=1)
        outer_layout.addWidget(row_widget)
        self._row_widgets[path] = outer_widget
        self._compat_rows.append({
            "label": label,
            "path": path,
            "value": value,
            "kind": kind,
            "evaluated": value,
            "enabled": enabled,
            "editor": combo,
            "widget": combo,
        })
        self.layout.addWidget(outer_widget)

    def add_property_checkbox(self, label: str, path: str, value: bool, enabled: bool = True) -> None:
        outer_widget = QtWidgets.QWidget()
        outer_layout = QtWidgets.QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        row_widget = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label_widget = QtWidgets.QLabel(label)
        label_widget.setMinimumWidth(100)
        label_widget.setMaximumWidth(150)
        row_layout.addWidget(label_widget)

        cb = QtWidgets.QCheckBox()
        cb.setChecked(bool(value))
        cb.setEnabled(enabled)
        cb.toggled.connect(
            lambda checked, p=path: self.property_changed.emit(p, "true" if checked else "false", "block_bool")
        )
        row_layout.addWidget(cb)
        row_layout.addStretch()
        outer_layout.addWidget(row_widget)
        self._row_widgets[path] = outer_widget
        self._compat_rows.append({
            "label": label,
            "path": path,
            "value": "true" if value else "false",
            "kind": "block_bool",
            "evaluated": "true" if value else "false",
            "enabled": enabled,
            "editor": cb,
            "widget": cb,
        })
        self.layout.addWidget(outer_widget)

    def set_property_hint(self, path: str, hint: str, *, resettable: bool = False) -> None:
        """Add a small gray hint label below the property row for the given path.

        Typically used to show the baseline (or parent) value when a case
        override is active. Also tints the row's left edge blue to indicate
        the override visually. When ``resettable`` is True, a small "Reset"
        button is added next to the hint; clicking it emits
        ``override_reset_requested(path)`` so the host can clear the local
        override and refresh.

        If the path is not found, this is a no-op.
        """
        outer_widget = self._row_widgets.get(path)
        if outer_widget is None:
            return
        outer_layout = outer_widget.layout()
        if outer_layout is None:
            return
        # Remove any existing hint rows (avoid duplicates on re-populate)
        for i in reversed(range(outer_layout.count())):
            item = outer_layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None and w.property("is_baseline_hint_row"):
                outer_layout.removeWidget(w)
                w.deleteLater()
        # Apply a left-border accent to the outer widget to flag the override.
        # Orange is the override semantic; see quino/gui/_palette.py.
        outer_widget.setStyleSheet(
            "QWidget { border-left: 3px solid #c75b12; padding-left: 4px; }"
        )
        hint_row = QtWidgets.QWidget()
        hint_row.setProperty("is_baseline_hint_row", True)
        hint_layout = QtWidgets.QHBoxLayout(hint_row)
        hint_layout.setContentsMargins(108, 0, 0, 0)
        hint_layout.setSpacing(6)
        hint_label = QtWidgets.QLabel(hint)
        hint_label.setStyleSheet("color: #888888; font-size: 8pt; border: none;")
        hint_label.setWordWrap(False)
        hint_layout.addWidget(hint_label)
        if resettable:
            reset_btn = QtWidgets.QToolButton()
            reset_btn.setText("Reset")
            reset_btn.setAutoRaise(True)
            reset_btn.setToolTip(
                "Clear this local override so the inherited (or baseline) value applies again"
            )
            reset_btn.setStyleSheet("QToolButton { color: #2255aa; font-size: 8pt; }")
            reset_btn.clicked.connect(lambda _, p=path: self.override_reset_requested.emit(p))
            hint_layout.addWidget(reset_btn)
        hint_layout.addStretch()
        outer_layout.addWidget(hint_row)

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

        elif kind in {"expression", "expression_or_null", "block_param"}:
            text_input = QtWidgets.QLineEdit(value)
            text_input.setEnabled(enabled)
            text_input.editingFinished.connect(lambda p=path, w=text_input, k=kind: self.property_changed.emit(p, w.text(), k))
            layout.addWidget(text_input)

            if kind == "block_param":
                layout.addStretch()
                return container

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
