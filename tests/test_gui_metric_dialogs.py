import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from quino.domain.workspace import Analysis, Metric
from quino.gui.dialogs.metric_editor_dialog import MetricEditorDialog
from quino.gui.dialogs.metrics_manager_dialog import MetricsManagerDialog


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_editor_builds_python_metric():
    _app()
    analysis = Analysis(id="an1", name="Dyn")
    dlg = MetricEditorDialog(analysis, available_channels=["hub.x", "t"])
    dlg.name_edit.setText("final pos")
    idx = dlg.type_combo.findData("float")
    dlg.type_combo.setCurrentIndex(idx)
    dlg.code_edit.setPlainText("return data['hub.x'][-1]")
    dlg._accept()
    assert dlg.result_metric is not None
    assert dlg.result_metric.name == "final pos"
    assert dlg.result_metric.value_type == "float"
    assert "data['hub.x'][-1]" in dlg.result_metric.code


def test_editor_edit_mode_populates_fields():
    _app()
    analysis = Analysis(id="an1", name="Dyn")
    m = Metric(id="m1", name="thr", description="d", value_type="bool",
               code="return data['hub.x'][-1] > 10")
    dlg = MetricEditorDialog(analysis, metric=m, available_channels=["hub.x"])
    assert dlg.name_edit.text() == "thr"
    assert dlg.type_combo.currentData() == "bool"
    assert "data['hub.x'][-1] > 10" in dlg.code_edit.toPlainText()
    dlg._accept()
    assert dlg.result_metric.id == "m1"  # id preserved in edit mode


def test_editor_rejects_empty_name(monkeypatch):
    _app()
    from unittest.mock import MagicMock

    analysis = Analysis(id="an1", name="Dyn")
    dlg = MetricEditorDialog(analysis, available_channels=["hub.x"])
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", MagicMock())
    dlg.name_edit.setText("")
    dlg._accept()
    assert dlg.result_metric is None
    QtWidgets.QMessageBox.warning.assert_called_once()


def test_editor_insert_token():
    _app()
    analysis = Analysis(id="an1", name="Dyn")
    dlg = MetricEditorDialog(analysis, available_channels=["hub.x", "t", "meta.dt"])
    dlg._insert_channel_token("hub.x")
    dlg._insert_channel_token("t")
    dlg._insert_channel_token("meta.dt")
    text = dlg.code_edit.toPlainText()
    assert "data['hub.x']" in text
    assert "data['t']" in text
    assert "meta['dt']" in text


def test_editor_test_button_no_data():
    _app()
    analysis = Analysis(id="an1", name="Dyn")
    dlg = MetricEditorDialog(analysis, available_channels=["hub.x"], sensor_outputs={})
    dlg.code_edit.setPlainText("return 1")
    dlg._on_test()
    # No sensor outputs -> no data reported in the label.
    assert "no_data" in dlg.result_label.text() or "no data" in dlg.result_label.text().lower()


def test_manager_lists_and_adds_metrics():
    _app()

    class FakeModel:
        sensors = []

    class FakeProject:
        model = FakeModel()
        sensor_outputs = {}

    analysis = Analysis(id="an1", name="Dyn",
                        metrics=[Metric(id="m1", name="x", value_type="float", code="return 1")])
    dlg = MetricsManagerDialog(FakeProject(), analysis)
    # table shows the existing metric
    assert dlg.table.rowCount() == 1


def test_manager_delete_metric(monkeypatch):
    _app()

    class FakeModel:
        sensors = []

    class FakeProject:
        model = FakeModel()
        sensor_outputs = {}

    analysis = Analysis(id="an1", name="Dyn",
                        metrics=[Metric(id="m1", name="x", value_type="float", code="return 1")])
    dlg = MetricsManagerDialog(FakeProject(), analysis)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes,
    )
    dlg.table.selectRow(0)
    dlg._on_delete()
    assert len(analysis.metrics) == 0
    assert dlg.table.rowCount() == 0


def test_manager_recalculate_no_data():
    _app()

    class FakeModel:
        sensors = []

    class FakeProject:
        model = FakeModel()
        sensor_outputs = {}

    analysis = Analysis(id="an1", name="Dyn",
                        metrics=[Metric(id="m1", name="x", value_type="float", code="return 1")])
    dlg = MetricsManagerDialog(FakeProject(), analysis)
    dlg._on_recalculate()
    assert analysis.metrics[0].result is not None
    assert analysis.metrics[0].result.status == "no_data"
