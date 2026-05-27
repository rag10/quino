import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from quino.gui.widgets.link_status_indicator import LinkStatusIndicator


def test_indicator_starts_in_linked_mode(qtbot):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ind = LinkStatusIndicator(state="linked")
    qtbot.addWidget(ind)
    assert ind.state() == "linked"


def test_indicator_state_can_change(qtbot):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ind = LinkStatusIndicator(state="linked")
    qtbot.addWidget(ind)
    ind.set_state("unlinked")
    assert ind.state() == "unlinked"
