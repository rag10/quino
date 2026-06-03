from __future__ import annotations

from typing import Any
from uuid import uuid4

from PySide6 import QtWidgets

from quino.domain.workspace import Metric
from quino.services.metric_data import build_metric_data
from quino.services.metric_evaluator import evaluate

_VALUE_TYPES = [
    ("float", "float"),
    ("bool", "bool"),
    ("int", "int"),
    ("str", "str"),
]

_CODE_PLACEHOLDER = "var = data['sensor1.x']\nreturn var[-1]"


class MetricEditorDialog(QtWidgets.QDialog):
    """Editor for a user-written Python metric (body of ``eval(data, meta)``)."""

    def __init__(
        self,
        analysis,
        metric: Metric | None = None,
        *,
        available_channels: list[str] | None = None,
        sensor_outputs: dict[str, Any] | None = None,
        sensor_name_by_id: dict[str, str] | None = None,
        analysis_meta: dict[str, Any] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar métrica" if metric is not None else "Nueva métrica")
        self.setMinimumSize(640, 420)

        self._analysis = analysis
        self._original = metric
        self._available_channels = list(available_channels or [])
        self._sensor_outputs = sensor_outputs or {}
        self._sensor_name_by_id = sensor_name_by_id or {}
        self._analysis_meta = analysis_meta or {}
        self.result_metric: Metric | None = None

        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.name_edit = QtWidgets.QLineEdit(self)
        self.name_edit.setPlaceholderText("Nombre de la métrica")
        form.addRow("Nombre", self.name_edit)

        self.description_edit = QtWidgets.QLineEdit(self)
        self.description_edit.setPlaceholderText("Descripción (opcional)")
        form.addRow("Descripción", self.description_edit)

        self.type_combo = QtWidgets.QComboBox(self)
        for label, value in _VALUE_TYPES:
            self.type_combo.addItem(label, value)
        form.addRow("Tipo", self.type_combo)
        layout.addLayout(form)

        # Code editor + channel palette side by side.
        body_layout = QtWidgets.QHBoxLayout()

        code_box = QtWidgets.QVBoxLayout()
        code_box.addWidget(QtWidgets.QLabel("Código  (cuerpo de eval(data, meta), debe usar return)"))
        self.code_edit = QtWidgets.QPlainTextEdit(self)
        self.code_edit.setPlaceholderText(_CODE_PLACEHOLDER)
        self.code_edit.setTabChangesFocus(False)
        code_box.addWidget(self.code_edit)
        body_layout.addLayout(code_box, 3)

        palette_box = QtWidgets.QVBoxLayout()
        palette_box.addWidget(QtWidgets.QLabel("Canales (doble clic)"))
        self.channel_list = QtWidgets.QListWidget(self)
        for channel in self._available_channels:
            self.channel_list.addItem(channel)
        self.channel_list.itemDoubleClicked.connect(self._on_channel_double_clicked)
        palette_box.addWidget(self.channel_list)
        body_layout.addLayout(palette_box, 1)

        layout.addLayout(body_layout)

        # Test row.
        test_layout = QtWidgets.QHBoxLayout()
        self.test_btn = QtWidgets.QPushButton("Probar", self)
        self.test_btn.clicked.connect(self._on_test)
        test_layout.addWidget(self.test_btn)
        self.result_label = QtWidgets.QLabel("", self)
        self.result_label.setWordWrap(True)
        test_layout.addWidget(self.result_label, 1)
        layout.addLayout(test_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if metric is not None:
            self._load_from_metric(metric)

    # -- channel palette ----------------------------------------------------

    def _on_channel_double_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        self._insert_channel_token(item.text())

    def _token_for_channel(self, channel: str) -> str:
        if channel == "t":
            return "data['t']"
        if channel.startswith("meta."):
            return f"meta['{channel[len('meta.'):]}']"
        return f"data['{channel}']"

    def _insert_channel_token(self, channel: str) -> None:
        token = self._token_for_channel(channel)
        cursor = self.code_edit.textCursor()
        cursor.insertText(token)
        self.code_edit.setTextCursor(cursor)
        self.code_edit.setFocus()

    # -- test ---------------------------------------------------------------

    def _build_tmp_metric(self) -> Metric:
        return Metric(
            id="__tmp__",
            name=self.name_edit.text().strip() or "tmp",
            description=self.description_edit.text().strip(),
            value_type=self.type_combo.currentData(),
            code=self.code_edit.toPlainText(),
        )

    def _on_test(self) -> None:
        if not self._sensor_outputs:
            data: dict[str, Any] = {}
            meta: dict[str, Any] = dict(self._analysis_meta)
        else:
            data, meta = build_metric_data(
                self._sensor_outputs, self._sensor_name_by_id, self._analysis_meta
            )
        if not data:
            self.result_label.setText("no_data: no hay resultados de sensores para evaluar")
            return
        result = evaluate(self._build_tmp_metric(), data, meta)
        if result.status == "ok":
            self.result_label.setText(f"ok: {result.value!r}")
        elif result.status == "no_data":
            self.result_label.setText("no_data")
        else:
            self.result_label.setText(f"error: {result.error}")

    # -- load / accept ------------------------------------------------------

    def _load_from_metric(self, metric: Metric) -> None:
        self.name_edit.setText(metric.name)
        self.description_edit.setText(metric.description)
        index = self.type_combo.findData(metric.value_type)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        self.code_edit.setPlainText(metric.code)

    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Validación", "El nombre es obligatorio.")
            return

        metric_id = self._original.id if self._original is not None else f"mt_{uuid4().hex[:8]}"
        self.result_metric = Metric(
            id=metric_id,
            name=name,
            description=self.description_edit.text().strip(),
            value_type=self.type_combo.currentData(),
            code=self.code_edit.toPlainText(),
        )
        self.accept()
