from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from quino.application.service import ApplicationService


class DivergencesDock(QtWidgets.QWidget):
    def __init__(self, app_service: ApplicationService, parent=None) -> None:
        super().__init__(parent)
        self._service = app_service
        self._case_id: str | None = None
        self._table = QtWidgets.QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Path", "Parent", "Child", "Action"])
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._table)

    def show_case(self, case_id: str) -> None:
        self._case_id = case_id
        self._refresh()

    def row_count(self) -> int:
        return self._table.rowCount()

    def _warnings(self) -> list[dict]:
        if self._case_id is None:
            return []
        ws = self._service._workspace
        if ws is None:
            return []
        case = ws.cases.get(self._case_id)
        if case is None:
            return []
        return list(case.metadata.get("divergence_warnings", []))

    def _refresh(self) -> None:
        self._table.setRowCount(0)
        for i, w in enumerate(self._warnings()):
            self._table.insertRow(i)
            self._table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(w.get("path", ""))))
            self._table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(w.get("parent_value", ""))))
            self._table.setItem(i, 2, QtWidgets.QTableWidgetItem(str(w.get("child_value", ""))))
            btn = QtWidgets.QPushButton("Keep override")
            btn.clicked.connect(lambda _=False, idx=i: self.keep_override(idx))
            self._table.setCellWidget(i, 3, btn)

    def keep_override(self, idx: int) -> None:
        if self._case_id is None:
            return
        ws = self._service._workspace
        if ws is None:
            return
        case = ws.cases.get(self._case_id)
        if case is None:
            return
        warnings = case.metadata.get("divergence_warnings", [])
        if 0 <= idx < len(warnings):
            warnings.pop(idx)
            case.metadata["divergence_warnings"] = warnings
        self._refresh()
