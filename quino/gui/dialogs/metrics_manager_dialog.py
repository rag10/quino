from __future__ import annotations

from typing import Any

from PySide6 import QtWidgets

from quino.gui.dialogs.metric_editor_dialog import MetricEditorDialog
from quino.services.metric_data import build_metric_data
from quino.services.metric_evaluator import evaluate_all
from quino.simulation.sensor_expressions import sensor_channel_keys


class MetricsManagerDialog(QtWidgets.QDialog):
    def __init__(
        self,
        project,
        analysis,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Métricas")
        self.setMinimumSize(560, 360)
        self._project = project
        self._analysis = analysis

        layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Nombre", "Tipo", "Resultado"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda *_: self._on_edit())
        layout.addWidget(self.table)

        btn_layout = QtWidgets.QHBoxLayout()
        self.add_btn = QtWidgets.QPushButton("Añadir", self)
        self.add_btn.clicked.connect(self._on_add)
        btn_layout.addWidget(self.add_btn)

        self.edit_btn = QtWidgets.QPushButton("Editar", self)
        self.edit_btn.clicked.connect(self._on_edit)
        btn_layout.addWidget(self.edit_btn)

        self.delete_btn = QtWidgets.QPushButton("Eliminar", self)
        self.delete_btn.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.delete_btn)

        self.recalc_btn = QtWidgets.QPushButton("Recalcular todas", self)
        self.recalc_btn.clicked.connect(self._on_recalculate)
        btn_layout.addWidget(self.recalc_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close,
            parent=self,
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_table()

    # -- shared evaluation context -----------------------------------------

    def _sensor_name_by_id(self) -> dict[str, str]:
        return {s.id: s.name for s in self._project.model.sensors}

    def _available_channels(self) -> list[str]:
        channels: list[str] = []
        for sensor in self._project.model.sensors:
            for chan, _unit in sensor_channel_keys(sensor):
                channels.append(f"{sensor.name}.{chan}")
        channels.extend(["t", "meta.dt", "meta.t_final"])
        return channels

    def _analysis_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        config = getattr(self._analysis, "config", None)
        for key in ("dt", "duration", "steps", "t_final"):
            value = getattr(config, key, None)
            if value is not None:
                meta[key] = value
        return meta

    # -- table --------------------------------------------------------------

    def _refresh_table(self) -> None:
        metrics = list(self._analysis.metrics)
        self.table.setRowCount(len(metrics))
        for row, metric in enumerate(metrics):
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(metric.name))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(metric.value_type))
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(self._result_text(metric)))
        self.table.horizontalHeader().setStretchLastSection(True)

    @staticmethod
    def _result_text(metric) -> str:
        result = metric.result
        if result is None:
            return "—"
        if result.status == "ok":
            return str(result.value)
        if result.status == "error":
            return "error"
        return "no_data"

    def _selected_index(self) -> int:
        selection = self.table.selectionModel().selectedRows()
        return selection[0].row() if selection else -1

    # -- actions ------------------------------------------------------------

    def _make_editor(self, metric=None) -> MetricEditorDialog:
        return MetricEditorDialog(
            self._analysis,
            metric=metric,
            available_channels=self._available_channels(),
            sensor_outputs=getattr(self._project, "sensor_outputs", {}),
            sensor_name_by_id=self._sensor_name_by_id(),
            analysis_meta=self._analysis_meta(),
            parent=self,
        )

    def _on_add(self) -> None:
        dialog = self._make_editor()
        if (
            dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
            and dialog.result_metric is not None
        ):
            self._analysis.metrics.append(dialog.result_metric)
            self._refresh_table()

    def _on_edit(self) -> None:
        index = self._selected_index()
        if index < 0 or index >= len(self._analysis.metrics):
            return
        metric = self._analysis.metrics[index]
        dialog = self._make_editor(metric=metric)
        if (
            dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
            and dialog.result_metric is not None
        ):
            self._analysis.metrics[index] = dialog.result_metric
            self._refresh_table()

    def _on_delete(self) -> None:
        index = self._selected_index()
        if index < 0 or index >= len(self._analysis.metrics):
            return
        metric = self._analysis.metrics[index]
        reply = QtWidgets.QMessageBox.question(
            self,
            "Eliminar métrica",
            f"¿Eliminar la métrica '{metric.name}'?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._analysis.metrics.pop(index)
            self._refresh_table()

    def _on_recalculate(self) -> None:
        sensor_outputs = getattr(self._project, "sensor_outputs", {}) or {}
        data, meta = build_metric_data(
            sensor_outputs, self._sensor_name_by_id(), self._analysis_meta()
        )
        evaluate_all(self._analysis, data, meta)
        self._refresh_table()
