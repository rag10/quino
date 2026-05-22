import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.application.service import ApplicationService
from quino.gui.dialogs.plot_editor_dialog import PlotEditorDialog


def test_plot_editor_dialog_collects_dynamic_plot(qtbot) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    marker_id = svc.project.model.bodies[0].markers[0].id
    sensor_id = svc.create_sensor("Hub", "point", [marker_id])
    dialog = PlotEditorDialog(analysis_type="dynamic", project=svc.project, parent=None)
    qtbot.addWidget(dialog)
    dialog.title_edit.setText("hub y")
    row = dialog._rows[0]
    row.sensor_combo.setCurrentIndex(row.sensor_combo.findData(sensor_id))
    row._reload_channels()
    row.channel_combo.setCurrentIndex(row.channel_combo.findData("y"))
    row.label_edit.setText("Hub y")
    dialog._accept()
    assert dialog.result_plot is not None
    assert dialog.result_plot.y_series[0].sensor_id == sensor_id
