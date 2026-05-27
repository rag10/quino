from __future__ import annotations

from PySide6 import QtWidgets

_COLORS = {
    "error": ("#fdecea", "#b43a2f", "#e4afa9"),
    "warning": ("#fff1e2", "#c76f1f", "#e5bd92"),
    "ok": ("#e7f4ee", "#25815f", "#b8d9cb"),
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
        background, color, border = _COLORS.get(severity, ("#eef4f8", "#66727e", "#cbd6e2"))
        self.setStyleSheet(
            f"QLabel {{ background: {background}; color: {color}; padding: 6px 8px;"
            f" border: 1px solid {border}; border-radius: 4px; font-weight: 600; }}"
        )
        self.setText(message)
        self.setVisible(True)
