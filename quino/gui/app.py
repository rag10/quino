from __future__ import annotations

import sys
from pathlib import Path

from quino.application.service import ApplicationService

_ICON_PATH = Path(__file__).parent / "icons" / "quino_app_icon_transparent_1024.png"


def run_gui(app_service: ApplicationService | None = None) -> int:
    from PySide6 import QtGui, QtWidgets

    from quino.gui.crash_reporter import install as install_crash_reporter
    from quino.gui.main_window import MainWindow

    install_crash_reporter()

    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    if _ICON_PATH.exists():
        qt_app.setWindowIcon(QtGui.QIcon(str(_ICON_PATH)))

    # Pre-initialize pyqtgraph with the QApplication already running so that
    # its internal colorSchemeChanged connection is made once, cleanly, before
    # any widget is created. Without this, the connection crashes on PySide6 >= 6.8
    # when a GraphicsLayoutWidget is first created inside a running event loop.
    import pyqtgraph as pg
    pg.setConfigOption("background", "k")
    pg.setConfigOption("foreground", "w")

    window = MainWindow(app_service or ApplicationService())
    window.show()
    return qt_app.exec()
