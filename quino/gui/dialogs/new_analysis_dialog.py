from __future__ import annotations

from PySide6 import QtWidgets

_TYPE_OPTIONS = [
    ("dynamic", "Dynamic", "Time integration", True),
    ("static", "Static", "Not yet implemented", False),
    ("kinematic", "Kinematic", "Not yet implemented", False),
    ("equilibrium", "Equilibrium", "Not yet implemented", False),
]


class NewAnalysisDialog(QtWidgets.QDialog):
    def __init__(self, *, poses: list[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Analysis")
        layout = QtWidgets.QFormLayout(self)

        self._name_edit = QtWidgets.QLineEdit("Analysis")
        layout.addRow("Name:", self._name_edit)

        type_group = QtWidgets.QGroupBox("Type")
        type_layout = QtWidgets.QVBoxLayout(type_group)
        self._type_buttons: dict[str, QtWidgets.QRadioButton] = {}
        for key, label, hint, operative in _TYPE_OPTIONS:
            btn = QtWidgets.QRadioButton(label)
            row_widget = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(btn)
            hint_lbl = QtWidgets.QLabel(f"— {hint}")
            if not operative:
                hint_lbl.setStyleSheet("color: #b07000;")
            row_layout.addWidget(hint_lbl)
            row_layout.addStretch(1)
            type_layout.addWidget(row_widget)
            self._type_buttons[key] = btn
        self._type_buttons["dynamic"].setChecked(True)
        layout.addRow(type_group)

        self._pose_combo = QtWidgets.QComboBox()
        for pose_id, pose_name in poses:
            self._pose_combo.addItem(pose_name, userData=pose_id)
        layout.addRow("Initial pose:", self._pose_combo)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
            | QtWidgets.QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def available_types(self) -> list[str]:
        return list(self._type_buttons.keys())

    def selected_type(self) -> str:
        for key, btn in self._type_buttons.items():
            if btn.isChecked():
                return key
        return "dynamic"

    def selected_name(self) -> str:
        return self._name_edit.text().strip() or "Analysis"

    def selected_pose_id(self) -> str | None:
        idx = self._pose_combo.currentIndex()
        return self._pose_combo.itemData(idx) if idx >= 0 else None
