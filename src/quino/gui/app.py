from __future__ import annotations

import sys

from quino.application.service import ApplicationService


def run_gui(app_service: ApplicationService | None = None) -> int:
    from PySide6 import QtWidgets

    from quino.gui.main_window import MainWindow

    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

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
