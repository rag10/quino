import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_new_analysis_dialog_has_all_four_types(qtbot):
    from quino.gui.dialogs.new_analysis_dialog import NewAnalysisDialog

    dialog = NewAnalysisDialog(poses=[("p", "Default")])
    qtbot.addWidget(dialog)
    types = dialog.available_types()
    assert "dynamic" in types
    assert "static" in types
    assert "kinematic" in types
    assert "equilibrium" in types


def test_new_analysis_dialog_default_is_dynamic(qtbot):
    from quino.gui.dialogs.new_analysis_dialog import NewAnalysisDialog

    dialog = NewAnalysisDialog(poses=[("p", "Default")])
    qtbot.addWidget(dialog)
    assert dialog.selected_type() == "dynamic"
