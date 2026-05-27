from __future__ import annotations

import json

from PySide6 import QtCore, QtWidgets

from quino.analysis.equilibrium_runner import EquilibriumAnalysisRunner
from quino.gui.analysis_modes import register_mode
from quino.gui.analysis_modes._base import AnalysisModeController
from quino.gui.theme import BLUE, GREEN, INK_MUTED, VIOLET
from quino.gui.widgets.report_panel import ReportPanelWidget
from quino.gui.widgets.validation_banner import ValidationBanner


@register_mode("equilibrium")
class EquilibriumModeController(AnalysisModeController):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self.banner: ValidationBanner | None = None
        self.list_widget: QtWidgets.QListWidget | None = None
        self.report: ReportPanelWidget | None = None
        self._loaded_equilibria: list[dict] = []
        self._current_analysis = None
        self._current_pose_blob: dict | None = None

    def build_toolbar(self, parent):
        bar = self.main_window._analysis_toolbar
        bar.clear()
        validate_action = self._toolbar_action(
            "Validate",
            "check-circle",
            BLUE,
            self._on_validate,
            tooltip="Validate the equilibrium setup before running.",
        )
        run_action = self._toolbar_action(
            "Run",
            "run-simulation",
            GREEN,
            self.on_run_clicked,
            tooltip="Run the equilibrium search on the current model.",
        )
        self.main_window._add_toolbar_block(bar, [[validate_action, run_action]], "Solve")
        self.main_window._add_toolbar_sep(bar)

        plot_action = self._toolbar_action(
            "Plot",
            "new-graph",
            VIOLET,
            lambda: self.main_window._open_plot_editor_for_analysis(self._current_analysis),
            tooltip="Create a plot from the latest equilibrium run.",
        )
        compare_action = self._toolbar_action(
            "Compare",
            "new-graph",
            INK_MUTED,
            self.main_window._open_compare_runs_dialog,
            tooltip="Compare persisted runs for this analysis.",
        )
        self.main_window._add_toolbar_block(bar, [[plot_action, compare_action]], "View")
        self.toolbar = bar
        return bar

    def build_config_widget(self, parent):
        widget = QtWidgets.QWidget(parent)
        form = QtWidgets.QFormLayout(widget)
        self._gravity_cb = QtWidgets.QCheckBox("Gravity enabled", widget)
        self._stability_cb = QtWidgets.QCheckBox("Stability check", widget)
        self._perturbations_edit = QtWidgets.QLineEdit(widget)
        self._tolerance_spin = QtWidgets.QDoubleSpinBox(widget)
        self._tolerance_spin.setRange(1e-9, 1.0)
        self._tolerance_spin.setDecimals(6)
        form.addRow(self._gravity_cb)
        form.addRow(self._stability_cb)
        form.addRow("Perturbations", self._perturbations_edit)
        form.addRow("Pose tolerance", self._tolerance_spin)
        self.config_widget = widget
        return widget

    def build_bottom_panel(self, parent):
        outer = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(outer)
        self.banner = ValidationBanner(outer)
        layout.addWidget(self.banner)
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, outer)
        self.list_widget = QtWidgets.QListWidget(split)
        self.list_widget.itemSelectionChanged.connect(self._on_eq_selected)
        self.report = ReportPanelWidget(split)
        split.addWidget(self.list_widget)
        split.addWidget(self.report)
        split.setSizes([220, 460])
        layout.addWidget(split)
        self.bottom_panel = outer
        return outer

    def on_enter(self, analysis):
        self._current_analysis = analysis
        self.main_window.canvas.set_mode_badge_suffix("(equilibrium)")
        self._populate_config_from(analysis.config)
        self._validate_and_refresh_banner()
        latest = self._latest_report_run()
        if latest is not None:
            self.on_run_selected(latest)

    def on_leave(self):
        self.main_window.canvas.set_mode_badge_suffix("")
        self.main_window.canvas.set_kinematic_pose(None)
        self.main_window.canvas.set_state_overlay(None)
        self._loaded_equilibria = []
        self._current_pose_blob = None

    def apply_current_frame(self) -> None:
        if self._current_pose_blob is not None:
            self.main_window.canvas.set_kinematic_pose(self._current_pose_blob)

    def on_run_clicked(self) -> None:
        if self._current_analysis is None:
            return
        if not self._validate_and_refresh_banner():
            return
        self._sync_config_into_analysis()
        self.main_window._on_run_analysis_requested(self._current_analysis.id)

    def on_run_selected(self, run) -> None:
        if self.list_widget is None or self.report is None:
            return
        self.list_widget.clear()
        self.report.clear_tabs()
        self._loaded_equilibria = []
        project_dir = self.main_window.app_service.current_project_dir
        if project_dir is None or run.result_ref is None:
            return
        path = project_dir / run.result_ref.artifact_path
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self._loaded_equilibria = list(data.get("equilibria", []))
        for index, equilibrium in enumerate(self._loaded_equilibria, start=1):
            perturbation = equilibrium.get("perturbation", "?")
            self.list_widget.addItem(f"Equilibrium #{index} (perturbation={perturbation})")
        if self._loaded_equilibria:
            self.list_widget.setCurrentRow(0)
        else:
            self._refresh_metrics_tab(run)

    def on_run_finished(self, run_id: str, status: str) -> None:
        if status not in {"ok", "partial"}:
            return
        latest = self._latest_report_run()
        if latest is not None:
            self.on_run_selected(latest)

    def _on_validate(self) -> None:
        self._validate_and_refresh_banner()

    def _on_eq_selected(self) -> None:
        if self.list_widget is None or self.report is None:
            return
        index = self.list_widget.currentRow()
        if index < 0 or index >= len(self._loaded_equilibria):
            return
        equilibrium = self._loaded_equilibria[index]
        self._current_pose_blob = equilibrium.get("pose")
        self.main_window.canvas.set_kinematic_pose(self._current_pose_blob)
        self.report.clear_tabs()
        self.report.add_kv_tab(
            f"Equilibrium #{index + 1}",
            [("Perturbation seed", str(equilibrium.get("perturbation", "?")))],
        )
        self._refresh_metrics_tab(self._latest_report_run())

    def _populate_config_from(self, cfg) -> None:
        self._gravity_cb.setChecked(cfg.gravity_enabled)
        self._stability_cb.setChecked(cfg.stability_check)
        self._perturbations_edit.setText(", ".join(str(value) for value in cfg.initial_perturbations))
        self._tolerance_spin.setValue(cfg.pose_match_tolerance)

    def _sync_config_into_analysis(self) -> None:
        cfg = self._current_analysis.config
        cfg.gravity_enabled = self._gravity_cb.isChecked()
        cfg.stability_check = self._stability_cb.isChecked()
        cfg.pose_match_tolerance = float(self._tolerance_spin.value())
        text = self._perturbations_edit.text().strip()
        cfg.initial_perturbations = [float(item.strip()) for item in text.split(",") if item.strip()] or [0.0]

    def _validate_and_refresh_banner(self) -> bool:
        if self._current_analysis is None or self.banner is None:
            return False
        errors = EquilibriumAnalysisRunner().validate(self.main_window.app_service.project, self._current_analysis)
        if not errors:
            self.banner.set_status("idle", "")
            return True
        self.banner.set_status("error", errors[0])
        return False

    def _latest_report_run(self):
        case = self.main_window.app_service.current_case()
        if case is None or self._current_analysis is None:
            return None
        runs = [
            run for run in case.runs
            if run.analysis_id == self._current_analysis.id and run.status in {"ok", "partial"} and run.result_ref is not None
        ]
        return runs[-1] if runs else None

    def _refresh_metrics_tab(self, run) -> None:
        if self.report is None:
            return
        rows = []
        if run is not None:
            rows = [[key, f"{value:.6g}"] for key, value in sorted(run.metrics.items())]
        self.report.replace_table_tab("Metrics", ["Key", "Value"], rows)
