from __future__ import annotations

import json

from PySide6 import QtWidgets

from quino.analysis.static_runner import StaticAnalysisRunner
from quino.gui.analysis_modes import register_mode
from quino.gui.analysis_modes._base import AnalysisModeController
from quino.gui.widgets.report_panel import ReportPanelWidget
from quino.gui.widgets.validation_banner import ValidationBanner


@register_mode("static")
class StaticModeController(AnalysisModeController):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self.banner: ValidationBanner | None = None
        self.report: ReportPanelWidget | None = None
        self._current_analysis = None

    def build_toolbar(self, parent):
        bar = self.main_window._analysis_toolbar
        bar.clear()
        validate_action = bar.addAction("Validate")
        validate_action.triggered.connect(self._on_validate)
        run_action = bar.addAction("Run")
        run_action.triggered.connect(self.on_run_clicked)
        bar.addSeparator()
        reactions_action = bar.addAction("Show reactions")
        reactions_action.triggered.connect(self._on_show_reactions)
        plot_action = bar.addAction("New plot")
        plot_action.triggered.connect(self.main_window.create_plot_window)
        self.toolbar = bar
        return bar

    def build_config_widget(self, parent):
        widget = QtWidgets.QWidget(parent)
        form = QtWidgets.QFormLayout(widget)
        self._gravity_cb = QtWidgets.QCheckBox("Gravity enabled", widget)
        self._tolerance_spin = QtWidgets.QDoubleSpinBox(widget)
        self._tolerance_spin.setRange(1e-12, 1.0)
        self._tolerance_spin.setDecimals(12)
        self._reactions_cb = QtWidgets.QCheckBox("Report reactions", widget)
        self._energy_cb = QtWidgets.QCheckBox("Report spring energy", widget)
        form.addRow(self._gravity_cb)
        form.addRow("Tolerance", self._tolerance_spin)
        form.addRow(self._reactions_cb)
        form.addRow(self._energy_cb)
        self.config_widget = widget
        return widget

    def build_bottom_panel(self, parent):
        outer = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(outer)
        self.banner = ValidationBanner(outer)
        layout.addWidget(self.banner)
        self.report = ReportPanelWidget(outer)
        layout.addWidget(self.report)
        self.bottom_panel = outer
        return outer

    def on_enter(self, analysis):
        self._current_analysis = analysis
        self.main_window.canvas.set_mode_badge_suffix("(static)")
        self._populate_config_from(analysis.config)
        self._validate_and_refresh_banner()
        latest = self._latest_report_run()
        if latest is not None:
            self.on_run_selected(latest)

    def on_leave(self):
        self.main_window.canvas.set_mode_badge_suffix("")
        self.main_window.canvas.set_kinematic_pose(None)

    def on_run_clicked(self) -> None:
        if self._current_analysis is None:
            return
        if not self._validate_and_refresh_banner():
            return
        self._sync_config_into_analysis()
        self.main_window._on_run_analysis_requested(self._current_analysis.id)

    def on_run_selected(self, run) -> None:
        if self.report is None:
            return
        self.report.clear_tabs()
        project_dir = self.main_window.app_service.current_project_dir
        if project_dir is None or run.result_ref is None:
            return
        path = project_dir / run.result_ref.artifact_path
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self.report.add_table_tab(
            "Applied loads",
            ["name", "source", "fx", "fy"],
            [[row.get("name", ""), row.get("source", ""), row.get("fx", ""), row.get("fy", "")]
             for row in data.get("applied_loads", [])],
        )
        self.report.add_table_tab(
            "Reactions",
            ["joint", "fx", "fy", "moment"],
            [[row.get("joint_name", row.get("joint_id", "")), row.get("fx", ""), row.get("fy", ""), row.get("moment", "")]
             for row in data.get("reactions", [])],
        )
        self.report.add_table_tab(
            "Springs",
            ["name", "kind", "F", "length", "energy"],
            [[row.get("name", ""), row.get("kind", ""), row.get("F", ""), row.get("length", ""), row.get("energy", "")]
             for row in data.get("spring_forces", [])],
        )
        self.report.add_kv_tab(
            "Energy",
            [("Total spring potential energy", f'{data.get("total_energy_in_springs", 0.0):.4g} J')],
        )
        pose = data.get("pose")
        self.main_window.canvas.set_kinematic_pose(pose)

    def on_run_finished(self, run_id: str, status: str) -> None:
        if status not in {"ok", "partial"}:
            return
        latest = self._latest_report_run()
        if latest is not None:
            self.on_run_selected(latest)

    def _on_validate(self) -> None:
        self._validate_and_refresh_banner()

    def _on_show_reactions(self) -> None:
        if self.report is None:
            return
        for index in range(self.report.count()):
            if self.report.tabText(index).lower().startswith("reactions"):
                self.report.setCurrentIndex(index)
                break

    def _populate_config_from(self, cfg) -> None:
        self._gravity_cb.setChecked(cfg.gravity_enabled)
        self._tolerance_spin.setValue(cfg.tolerance)
        self._reactions_cb.setChecked(cfg.report_reactions)
        self._energy_cb.setChecked(cfg.report_spring_energy)

    def _sync_config_into_analysis(self) -> None:
        cfg = self._current_analysis.config
        cfg.gravity_enabled = self._gravity_cb.isChecked()
        cfg.tolerance = float(self._tolerance_spin.value())
        cfg.report_reactions = self._reactions_cb.isChecked()
        cfg.report_spring_energy = self._energy_cb.isChecked()

    def _validate_and_refresh_banner(self) -> bool:
        if self._current_analysis is None or self.banner is None:
            return False
        errors = StaticAnalysisRunner().validate(self.main_window.app_service.project, self._current_analysis)
        if not errors:
            self.banner.set_status("idle", "")
            return True
        critical = [error for error in errors if not error.startswith("WARNING")]
        if critical:
            self.banner.set_status("error", critical[0])
            return False
        self.banner.set_status("warning", errors[0].removeprefix("WARNING: "))
        return True

    def _latest_report_run(self):
        project = self.main_window.app_service.project
        if project is None or project.workspace is None or self._current_analysis is None:
            return None
        runs = [
            run for run in project.workspace.runs
            if run.analysis_id == self._current_analysis.id and run.status in {"ok", "partial"} and run.result_ref is not None
        ]
        return runs[-1] if runs else None
