from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class RunStatusWidget(QtWidgets.QWidget):
    cancel_requested = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("runStatusWidget")
        self._current_id: str | None = None

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self._label = QtWidgets.QLabel("Idle")
        self._label.setObjectName("runStatusLabel")
        self._cancel_btn = QtWidgets.QToolButton()
        self._cancel_btn.setText("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        layout.addWidget(self._label)
        layout.addStretch(1)
        layout.addWidget(self._cancel_btn)

    def show_running(self, run_id: str, label: str, pending: int = 0) -> None:
        self._current_id = run_id
        suffix = f"  · {pending} pending" if pending else ""
        self._label.setText(f"Running: {label}{suffix}")
        self._cancel_btn.setEnabled(True)

    def show_idle(self) -> None:
        self._current_id = None
        self._label.setText("Idle")
        self._cancel_btn.setEnabled(False)

    def show_finished(self, status: str, label: str, error: str | None = None) -> None:
        self._current_id = None
        self._cancel_btn.setEnabled(False)
        if status in {"ok", "partial"}:
            self._label.setText(f"Finished ({status}): {label}")
        elif status == "failed":
            tooltip = f"Failed: {label}"
            if error:
                tooltip += f" — {error}"
            self._label.setText(tooltip)
        else:
            self._label.setText("Idle")

    def _on_cancel(self) -> None:
        if self._current_id is not None:
            self.cancel_requested.emit(self._current_id)
