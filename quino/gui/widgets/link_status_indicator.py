from __future__ import annotations

from PySide6 import QtCore, QtWidgets

_GLYPHS = {"linked": "↺", "unlinked": "✎", "local": "+", "none": ""}
_TOOLTIPS = {
    "linked": "Linked to parent. Right-click to override.",
    "unlinked": "Override (unlinked). Right-click to re-link.",
    "local": "Locally created.",
    "none": "Root case — no parent.",
}


class LinkStatusIndicator(QtWidgets.QLabel):
    relink_requested = QtCore.Signal()
    override_requested = QtCore.Signal()

    def __init__(self, state: str = "none", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self._refresh()

    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        if state not in _GLYPHS:
            raise ValueError(f"Unknown link state: {state!r}")
        self._state = state
        self._refresh()

    def _refresh(self) -> None:
        self.setText(_GLYPHS[self._state])
        self.setToolTip(_TOOLTIPS[self._state])

    def _show_menu(self, pos) -> None:
        if self._state not in {"linked", "unlinked"}:
            return
        menu = QtWidgets.QMenu(self)
        if self._state == "linked":
            action = menu.addAction("Override in this case")
            if menu.exec(self.mapToGlobal(pos)) == action:
                self.override_requested.emit()
        else:
            action = menu.addAction("Re-link to parent")
            if menu.exec(self.mapToGlobal(pos)) == action:
                self.relink_requested.emit()
