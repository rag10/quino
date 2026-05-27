from __future__ import annotations

from abc import ABC, abstractmethod

from collections.abc import Callable

from PySide6 import QtGui, QtWidgets

from quino.gui.icons import get_icon


class AnalysisModeController(ABC):
    def __init__(self, main_window) -> None:
        self.main_window = main_window
        self.toolbar: QtWidgets.QToolBar | None = None
        self.config_widget: QtWidgets.QWidget | None = None
        self.bottom_panel: QtWidgets.QWidget | None = None

    def _toolbar_action(
        self,
        text: str,
        icon_name: str,
        color: str,
        slot: Callable | None = None,
        *,
        tooltip: str = "",
        checkable: bool = False,
        checked: bool = False,
    ) -> QtGui.QAction:
        action = QtGui.QAction(get_icon(icon_name, color), text, self.main_window)
        if tooltip:
            action.setToolTip(tooltip)
            action.setStatusTip(tooltip)
        action.setCheckable(checkable)
        if checkable:
            action.setChecked(checked)
        if slot is not None:
            action.triggered.connect(slot)
        return action

    @abstractmethod
    def build_toolbar(self, parent: QtWidgets.QWidget) -> QtWidgets.QToolBar:
        raise NotImplementedError

    @abstractmethod
    def build_config_widget(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        raise NotImplementedError

    @abstractmethod
    def build_bottom_panel(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        raise NotImplementedError

    @abstractmethod
    def on_enter(self, analysis) -> None:
        raise NotImplementedError

    @abstractmethod
    def on_leave(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def on_run_clicked(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def on_run_selected(self, run) -> None:
        raise NotImplementedError

    def on_run_queued(self, run_id: str) -> None:
        return None

    def on_run_started(self, run_id: str) -> None:
        return None

    def on_run_finished(self, run_id: str, status: str) -> None:
        return None
