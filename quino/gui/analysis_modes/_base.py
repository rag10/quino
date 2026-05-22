from __future__ import annotations

from abc import ABC, abstractmethod

from PySide6 import QtWidgets


class AnalysisModeController(ABC):
    def __init__(self, main_window) -> None:
        self.main_window = main_window
        self.toolbar: QtWidgets.QToolBar | None = None
        self.config_widget: QtWidgets.QWidget | None = None
        self.bottom_panel: QtWidgets.QWidget | None = None

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
