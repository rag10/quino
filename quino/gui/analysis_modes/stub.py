from __future__ import annotations

from PySide6 import QtWidgets

from quino.gui.analysis_modes._base import AnalysisModeController


class StubModeController(AnalysisModeController):
    def build_toolbar(self, parent):
        bar = QtWidgets.QToolBar(parent)
        bar.addWidget(QtWidgets.QLabel("  (mode not yet implemented in GUI) "))
        self.toolbar = bar
        return bar

    def build_config_widget(self, parent):
        widget = QtWidgets.QLabel("This analysis type has no configuration UI yet.", parent)
        self.config_widget = widget
        return widget

    def build_bottom_panel(self, parent):
        widget = QtWidgets.QLabel("Run via the executor; the GUI for this mode will arrive in a later phase.", parent)
        self.bottom_panel = widget
        return widget

    def on_enter(self, analysis) -> None:
        self.main_window.canvas.set_mode_badge_suffix(f"({analysis.analysis_type})")

    def on_leave(self) -> None:
        self.main_window.canvas.set_mode_badge_suffix("")

    def on_run_clicked(self) -> None:
        analysis_id = self.main_window.app_service.project.workspace.selected_analysis_id
        if analysis_id is not None:
            self.main_window._on_run_analysis_requested(analysis_id)

    def on_run_selected(self, run) -> None:
        return None
