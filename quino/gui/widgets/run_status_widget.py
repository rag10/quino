from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from quino.gui.icons import get_icon
from quino.gui.theme import RED


class _ElidedStatusLabel(QtWidgets.QLabel):
    """Single-line label that never asks the layout for unbounded width."""

    def __init__(self, text: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )

    def minimumSizeHint(self) -> QtCore.QSize:
        hint = super().minimumSizeHint()
        return QtCore.QSize(0, hint.height())

    def paintEvent(self, event) -> None:  # noqa: ANN001 - Qt override signature
        painter = QtWidgets.QStylePainter(self)
        option = QtWidgets.QStyleOption()
        option.initFrom(self)
        text = self.fontMetrics().elidedText(
            self.text(),
            QtCore.Qt.TextElideMode.ElideRight,
            self.contentsRect().width(),
        )
        painter.drawItemText(
            self.contentsRect(),
            int(self.alignment() | QtCore.Qt.AlignmentFlag.AlignVCenter),
            option.palette,
            self.isEnabled(),
            text,
            self.foregroundRole(),
        )


class RunStatusWidget(QtWidgets.QWidget):
    cancel_requested = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("runStatusWidget")
        self._current_id: str | None = None

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self._label = _ElidedStatusLabel("Idle")
        self._label.setObjectName("runStatusLabel")
        self._cancel_btn = QtWidgets.QToolButton()
        self._cancel_btn.setText("Cancel")
        self._cancel_btn.setIcon(get_icon("stop", RED, size=16))
        self._cancel_btn.setIconSize(QtCore.QSize(16, 16))
        self._cancel_btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        layout.addWidget(self._label)
        layout.addStretch(1)
        layout.addWidget(self._cancel_btn)

    def show_running(self, run_id: str, label: str, pending: int = 0) -> None:
        self._current_id = run_id
        suffix = f" - {pending} pending" if pending else ""
        text = f"Running: {label}{suffix}"
        self._label.setText(text)
        self._label.setToolTip(text)
        self._cancel_btn.setEnabled(True)

    def show_idle(self) -> None:
        self._current_id = None
        self._label.setText("Idle")
        self._label.setToolTip("")
        self._cancel_btn.setEnabled(False)

    def show_finished(self, status: str, label: str, error: str | None = None) -> None:
        self._current_id = None
        self._cancel_btn.setEnabled(False)
        if status in {"ok", "partial"}:
            text = f"Finished ({status}): {label}"
            self._label.setText(text)
            self._label.setToolTip(text)
        elif status == "failed":
            text = f"Failed: {label}"
            tooltip = text
            if error:
                tooltip += f"\n\n{error}"
            self._label.setText(text)
            self._label.setToolTip(tooltip)
        else:
            self._label.setText("Idle")
            self._label.setToolTip("")

    def _on_cancel(self) -> None:
        if self._current_id is not None:
            self.cancel_requested.emit(self._current_id)
