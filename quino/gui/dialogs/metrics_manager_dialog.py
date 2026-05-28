from __future__ import annotations

from PySide6 import QtWidgets

from quino.gui.dialogs.metric_editor_dialog import MetricEditorDialog


class MetricsManagerDialog(QtWidgets.QDialog):
    def __init__(
        self,
        project,
        analysis,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Metrics")
        self.setMinimumSize(520, 320)
        self._project = project
        self._analysis = analysis

        layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Key", "Name", "Kind", "Target"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.table)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()

        self.add_btn = QtWidgets.QPushButton("Add", self)
        self.add_btn.clicked.connect(self._on_add)
        btn_layout.addWidget(self.add_btn)

        self.edit_btn = QtWidgets.QPushButton("Edit", self)
        self.edit_btn.clicked.connect(self._on_edit)
        btn_layout.addWidget(self.edit_btn)

        self.delete_btn = QtWidgets.QPushButton("Delete", self)
        self.delete_btn.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.delete_btn)

        layout.addLayout(btn_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close,
            parent=self,
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_table()

    def _refresh_table(self) -> None:
        metrics = list(self._analysis.config.metrics)
        self.table.setRowCount(len(metrics))
        for row, metric in enumerate(metrics):
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(metric.key))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(metric.name))
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(metric.kind))
            self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(metric.target))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def _selected_index(self) -> int:
        selection = self.table.selectedIndexes()
        return selection[0].row() if selection else -1

    def _on_add(self) -> None:
        dialog = MetricEditorDialog(self._project, parent=self)
        if (
            dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
            and dialog.result_metric is not None
        ):
            self._analysis.config.metrics.append(dialog.result_metric)
            self._refresh_table()

    def _on_edit(self) -> None:
        index = self._selected_index()
        if index < 0 or index >= len(self._analysis.config.metrics):
            return
        metric = self._analysis.config.metrics[index]
        dialog = MetricEditorDialog(self._project, metric=metric, parent=self)
        if (
            dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
            and dialog.result_metric is not None
        ):
            self._analysis.config.metrics[index] = dialog.result_metric
            self._refresh_table()

    def _on_delete(self) -> None:
        index = self._selected_index()
        if index < 0 or index >= len(self._analysis.config.metrics):
            return
        metric = self._analysis.config.metrics[index]
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete metric",
            f"Delete metric '{metric.name}' ({metric.key})?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._analysis.config.metrics.pop(index)
            self._refresh_table()
