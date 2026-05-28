import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from quino.application.service import ApplicationService
from quino.domain.plotting import MetricDef
from quino.gui.dialogs.metric_editor_dialog import MetricEditorDialog
from quino.gui.dialogs.metrics_manager_dialog import MetricsManagerDialog


def _setup():
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    marker_id = svc.project.model.bodies[0].markers[0].id
    sensor_id = svc.create_sensor("Hub", "point", [marker_id])
    return svc, sensor_id


def test_metric_editor_dialog_creates_max_metric(qtbot) -> None:
    svc, sensor_id = _setup()
    dialog = MetricEditorDialog(svc.project, parent=None)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("Max Y")
    dialog.key_edit.setText("max_y")
    dialog.sensor_combo.setCurrentIndex(dialog.sensor_combo.findData(sensor_id))
    dialog._reload_channels()
    dialog.channel_combo.setCurrentIndex(dialog.channel_combo.findData("y"))
    dialog._accept()
    assert dialog.result_metric is not None
    assert dialog.result_metric.key == "max_y"
    assert dialog.result_metric.name == "Max Y"
    assert dialog.result_metric.kind == "max"
    assert dialog.result_metric.target == f"{sensor_id}:y"


def test_metric_editor_dialog_creates_value_at_t_metric(qtbot) -> None:
    svc, sensor_id = _setup()
    dialog = MetricEditorDialog(svc.project, parent=None)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("Y at 1s")
    dialog.key_edit.setText("y_at_1s")
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("value_at_t"))
    dialog._on_kind_changed()
    dialog.sensor_combo.setCurrentIndex(dialog.sensor_combo.findData(sensor_id))
    dialog._reload_channels()
    dialog.channel_combo.setCurrentIndex(dialog.channel_combo.findData("y"))
    dialog._t_spin.setValue(1.0)
    dialog._accept()
    assert dialog.result_metric is not None
    assert dialog.result_metric.kind == "value_at_t"
    assert dialog.result_metric.params == {"t": 1.0}


def test_metric_editor_dialog_creates_spring_energy_metric(qtbot) -> None:
    svc, _sensor_id = _setup()
    dialog = MetricEditorDialog(svc.project, parent=None)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("Spring E")
    dialog.key_edit.setText("spring_e")
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("spring_energy"))
    dialog._on_kind_changed()
    dialog._accept()
    assert dialog.result_metric is not None
    assert dialog.result_metric.kind == "spring_energy"
    assert dialog.result_metric.target == ""


def test_metric_editor_dialog_rejects_empty_key(qtbot, monkeypatch) -> None:
    svc, sensor_id = _setup()
    dialog = MetricEditorDialog(svc.project, parent=None)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", MagicMock())
    dialog.key_edit.setText("")
    dialog.sensor_combo.setCurrentIndex(dialog.sensor_combo.findData(sensor_id))
    dialog._reload_channels()
    dialog.channel_combo.setCurrentIndex(dialog.channel_combo.findData("y"))
    dialog._accept()
    assert dialog.result_metric is None
    QtWidgets.QMessageBox.warning.assert_called_once()


def test_metric_editor_dialog_edits_existing_metric(qtbot) -> None:
    svc, sensor_id = _setup()
    metric = MetricDef(
        id="m1",
        key="old_key",
        name="Old Name",
        kind="max",
        target=f"{sensor_id}:x",
    )
    dialog = MetricEditorDialog(svc.project, metric=metric, parent=None)
    qtbot.addWidget(dialog)
    assert dialog.key_edit.text() == "old_key"
    dialog.key_edit.setText("new_key")
    dialog._accept()
    assert dialog.result_metric is not None
    assert dialog.result_metric.id == "m1"
    assert dialog.result_metric.key == "new_key"


def test_metrics_manager_dialog_refreshes_table(qtbot) -> None:
    svc, sensor_id = _setup()
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis(
        "D", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id
    )

    analysis.config.metrics.append(
        MetricDef(id="m1", key="max_y", name="Max Y", kind="max", target=f"{sensor_id}:y")
    )

    dialog = MetricsManagerDialog(svc.project, analysis, parent=None)
    qtbot.addWidget(dialog)
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).text() == "max_y"


def test_metrics_manager_dialog_delete_metric(qtbot, monkeypatch) -> None:
    svc, sensor_id = _setup()
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis(
        "D", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id
    )

    analysis.config.metrics.append(
        MetricDef(id="m1", key="max_y", name="Max Y", kind="max", target=f"{sensor_id}:y")
    )

    dialog = MetricsManagerDialog(svc.project, analysis, parent=None)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Yes,
    )
    dialog.table.selectRow(0)
    dialog._on_delete()
    assert len(analysis.config.metrics) == 0
    assert dialog.table.rowCount() == 0
