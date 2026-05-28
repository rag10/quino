from __future__ import annotations

from PySide6 import QtCore, QtWidgets


_ACTIONS = [
    ("accept", "Accept"),
    ("eliminate_diff", "Remove diff"),
]


class CascadeConflictsDialog(QtWidgets.QDialog):
    """Blocking table dialog for per-conflict cascade resolution."""

    def __init__(self, conflicts: list, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cascade conflicts")
        self.setModal(True)
        self._conflicts = conflicts
        self._combos: list[QtWidgets.QComboBox] = []

        layout = QtWidgets.QVBoxLayout(self)
        self._table = QtWidgets.QTableWidget(len(conflicts), 4)
        self._table.setHorizontalHeaderLabels(["Case", "Path", "Reason", "Action"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)

        for row, conflict in enumerate(conflicts):
            self._table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(conflict.case_id)))
            self._table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(conflict.path)))
            self._table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(conflict.reason)))
            combo = QtWidgets.QComboBox()
            for action, label in _ACTIONS:
                combo.addItem(label, action)
            self._combos.append(combo)
            self._table.setCellWidget(row, 3, combo)

        layout.addWidget(self._table)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(760, min(420, 120 + len(conflicts) * 36))

    def resolutions(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for conflict, combo in zip(self._conflicts, self._combos):
            result[f"{conflict.case_id}:{conflict.path}"] = str(combo.currentData())
        return result


def resolve_cascade_conflicts_modal(conflicts: list, parent: QtWidgets.QWidget | None = None) -> dict[str, str] | None:
    if not conflicts:
        return {}
    dialog = CascadeConflictsDialog(conflicts, parent)
    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return None
    return dialog.resolutions()
