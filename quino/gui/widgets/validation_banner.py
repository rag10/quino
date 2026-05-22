from __future__ import annotations

from PySide6 import QtWidgets

_COLORS = {
    "error": "#aa2222",
    "warning": "#c75b12",
    "ok": "#228822",
}


class ValidationBanner(QtWidgets.QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setVisible(False)

    def set_status(self, severity: str, message: str) -> None:
        if severity == "idle" or not message:
            self.clear()
            self.setVisible(False)
            return
        color = _COLORS.get(severity, "#666666")
        self.setStyleSheet(
            f"QLabel {{ background: {color}; color: white; padding: 4px; border-radius: 3px; }}"
        )
        self.setText(message)
        self.setVisible(True)
