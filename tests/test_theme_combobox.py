import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from quino.gui import theme


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_app_qss_has_combobox_down_arrow_image():
    # The combined app stylesheet must style QComboBox::down-arrow with an image.
    _app()
    qss = theme.app_stylesheet()  # see note: expose a builder that returns the full QSS string
    assert "QComboBox::down-arrow" in qss
    segment = qss.split("QComboBox::down-arrow", 1)[1][:200]
    assert "image:" in segment and "url(" in segment
