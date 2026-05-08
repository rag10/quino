from __future__ import annotations

import sys

from quino.application.service import ApplicationService


def run_gui(app_service: ApplicationService | None = None) -> int:
    from PySide6 import QtWidgets

    from quino.gui.main_window import MainWindow

    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = MainWindow(app_service or ApplicationService())
    window.show()
    return qt_app.exec()
