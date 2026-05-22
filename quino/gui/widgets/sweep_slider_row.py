from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from quino.domain.workspace import SweepDef


class SweepSliderRow(QtWidgets.QWidget):
    index_changed = QtCore.Signal(int)
    edit_requested = QtCore.Signal(str)
    delete_requested = QtCore.Signal(str)

    def __init__(self, sweep: SweepDef, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._sweep = sweep
        self._values = sweep.resolved_values()

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        self._title_label = QtWidgets.QLabel(sweep.label or sweep.variable_kind, self)
        self._title_label.setMinimumWidth(160)
        layout.addWidget(self._title_label)

        self._slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, self)
        self._slider.setRange(0, max(0, len(self._values) - 1))
        self._slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._slider, stretch=1)

        self._value_label = QtWidgets.QLabel(self._format_value(0), self)
        self._value_label.setMinimumWidth(80)
        layout.addWidget(self._value_label)

        self._edit_btn = QtWidgets.QToolButton(self)
        self._edit_btn.setText("Edit")
        self._edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._sweep.id))
        layout.addWidget(self._edit_btn)

        self._del_btn = QtWidgets.QToolButton(self)
        self._del_btn.setText("X")
        self._del_btn.clicked.connect(lambda: self.delete_requested.emit(self._sweep.id))
        layout.addWidget(self._del_btn)

    def current_index(self) -> int:
        return self._slider.value()

    def set_disabled_recomputing(self, disabled: bool) -> None:
        self._slider.setEnabled(not disabled)
        self._edit_btn.setEnabled(not disabled)
        self._del_btn.setEnabled(not disabled)

    def _on_slider_changed(self, idx: int) -> None:
        self._value_label.setText(self._format_value(idx))
        self.index_changed.emit(idx)

    def _format_value(self, idx: int) -> str:
        if not self._values:
            return ""
        return f"{self._values[idx]:.4g}"
