from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from quino.gui.analysis_modes import register_mode
from quino.gui.analysis_modes._base import AnalysisModeController
from quino.gui.dialogs.add_sweep_dialog import AddSweepDialog
from quino.gui.dialogs.sweep_editor_dialog import SweepEditorDialog
from quino.gui.widgets.report_panel import ReportPanelWidget
from quino.gui.widgets.sweep_slider_row import SweepSliderRow
from quino.services.kinematic_cache import KinematicCache


@register_mode("kinematic")
class KinematicModeController(AnalysisModeController):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self._rows: list[SweepSliderRow] = []
        self._panel: QtWidgets.QWidget | None = None
        self._panel_layout: QtWidgets.QVBoxLayout | None = None
        self._summary_label: QtWidgets.QLabel | None = None
        self._report: ReportPanelWidget | None = None
        self._cache: KinematicCache | None = None
        self._current_analysis = None

    def build_toolbar(self, parent):
        bar = self.main_window._analysis_toolbar
        bar.clear()
        add_action = bar.addAction("Add sweep")
        add_action.triggered.connect(self._on_add_sweep)
        run_action = bar.addAction("Run")
        run_action.setToolTip("Run (or re-run) the sweep on the current model")
        run_action.triggered.connect(self._on_recompute)
        bar.addSeparator()
        self.action_show_traj = bar.addAction("Show trajectories")
        self.action_show_traj.setCheckable(True)
        self.action_show_traj.setChecked(True)
        self.action_show_traj.toggled.connect(self._on_toggle_trajectories)
        bar.addSeparator()
        plot_action = bar.addAction("New plot")
        plot_action.triggered.connect(lambda: self.main_window._open_plot_editor_for_analysis(self._current_analysis))
        compare_action = bar.addAction("Compare")
        compare_action.triggered.connect(self.main_window._open_compare_runs_dialog)
        self.toolbar = bar
        return bar

    def build_config_widget(self, parent):
        label = QtWidgets.QLabel("Kinematic sweeps configured below.", parent)
        self.config_widget = label
        return label

    def build_bottom_panel(self, parent):
        panel = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self._summary_label = QtWidgets.QLabel("", panel)
        layout.addWidget(self._summary_label)
        self._report = ReportPanelWidget(panel)
        layout.addWidget(self._report)
        self._panel = panel
        self._panel_layout = layout
        self.bottom_panel = panel
        return panel

    def on_enter(self, analysis):
        self._current_analysis = analysis
        self.main_window.canvas.set_mode_badge_suffix("(kinematic)")
        self._rebuild_rows()
        self._refresh_summary()
        latest = self._latest_cached_run()
        if latest is not None:
            self.on_run_selected(latest)
        else:
            self._clear_canvas()
        self._refresh_metrics_tab(latest)

    def on_leave(self):
        self._clear_canvas()
        self.main_window.canvas.set_mode_badge_suffix("")
        self.main_window.canvas.set_state_overlay(None)
        self._cache = None
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()
        self._current_analysis = None

    def apply_current_frame(self) -> None:
        """Called by MainWindow.refresh_all in place of the default analysis frame.

        Kinematic mode owns its overlay: re-emit it from the cache so the
        canvas keeps showing the selected sweep cell instead of reverting to
        the reference pose.
        """
        self._refresh_canvas_from_current_indices()

    def on_run_clicked(self) -> None:
        self._on_recompute()

    def on_run_selected(self, run) -> None:
        self._cache = KinematicCache.load(self.main_window.app_service.current_project_dir, run)
        self._refresh_canvas_from_current_indices()
        self._refresh_metrics_tab(run)

    def on_run_finished(self, run_id: str, status: str) -> None:
        for row in self._rows:
            row.set_disabled_recomputing(False)
        if self._current_analysis is None:
            return
        if status == "failed":
            self._clear_canvas()
            if self._summary_label is not None:
                self._summary_label.setText(
                    "Last run failed — see the dialog for details."
                )
            return
        if status in {"ok", "partial"}:
            latest = self._latest_cached_run()
            if latest is not None:
                self.on_run_selected(latest)
            if status == "partial" and self._summary_label is not None:
                self._summary_label.setText(
                    self._summary_label.text() + "    (partial: some cells unsolved)"
                )

    def _refresh_summary(self) -> None:
        if self._summary_label is None or self._current_analysis is None:
            return
        sweeps = self._current_analysis.config.sweeps
        if not sweeps:
            self._summary_label.setText("No sweeps configured.")
            return
        parts = [f"{sweep.label or sweep.variable_kind}: {len(sweep.resolved_values())} step(s)" for sweep in sweeps]
        self._summary_label.setText(" | ".join(parts))

    def _rebuild_rows(self) -> None:
        if self._panel_layout is None or self._current_analysis is None:
            return
        while self._panel_layout.count() > 1:
            item = self._panel_layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()
        for sweep in self._current_analysis.config.sweeps:
            row = SweepSliderRow(sweep, self._panel)
            row.index_changed.connect(lambda _idx, _row=row: self._refresh_canvas_from_current_indices())
            row.edit_requested.connect(self._on_edit_sweep)
            row.delete_requested.connect(self._on_delete_sweep)
            self._panel_layout.addWidget(row)
            self._rows.append(row)
        self._panel_layout.addStretch(1)

    def _on_add_sweep(self) -> None:
        project = self.main_window.app_service.display_project
        if project is None or self._current_analysis is None:
            return
        dialog = AddSweepDialog(project, self.main_window)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted and dialog.result_sweep is not None:
            self._current_analysis.config.sweeps.append(dialog.result_sweep)
            self._rebuild_rows()
            self._refresh_summary()
            self._on_recompute()

    def _on_edit_sweep(self, sweep_id: str) -> None:
        project = self.main_window.app_service.display_project
        if project is None or self._current_analysis is None:
            return
        sweep = next((item for item in self._current_analysis.config.sweeps if item.id == sweep_id), None)
        if sweep is None:
            return
        dialog = SweepEditorDialog(project, sweep, self.main_window)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted and dialog.result_sweep is not None:
            self._current_analysis.config.sweeps = [
                dialog.result_sweep if item.id == sweep_id else item for item in self._current_analysis.config.sweeps
            ]
            self._rebuild_rows()
            self._refresh_summary()
            self._on_recompute()

    def _on_delete_sweep(self, sweep_id: str) -> None:
        if self._current_analysis is None:
            return
        self._current_analysis.config.sweeps = [item for item in self._current_analysis.config.sweeps if item.id != sweep_id]
        self._rebuild_rows()
        self._refresh_summary()
        if self._current_analysis.config.sweeps:
            self._on_recompute()
        else:
            # No sweeps left → nothing to compute, just drop overlays.
            self._cache = None
            self._clear_canvas()

    def _on_toggle_trajectories(self, on: bool) -> None:
        self.main_window.canvas.set_show_trajectories(on)
        self.main_window.canvas.set_kinematic_trajectory(self._cache.inner_axis_line(self._current_indices()) if on and self._cache else [])

    def _on_recompute(self) -> None:
        if self._current_analysis is None:
            return
        if not self._current_analysis.config.sweeps:
            QtWidgets.QMessageBox.information(
                self.main_window,
                "No sweeps configured",
                "Add at least one sweep variable (Add sweep) before running the kinematic analysis.",
            )
            return
        for row in self._rows:
            row.set_disabled_recomputing(True)
        self.main_window._on_run_analysis_requested(self._current_analysis.id)

    def _latest_cached_run(self):
        project = self.main_window.app_service.project
        if project is None or project.workspace is None or self._current_analysis is None:
            return None
        runs = [
            run for run in project.workspace.runs
            if run.analysis_id == self._current_analysis.id and run.status in {"ok", "partial"} and run.result_ref is not None
        ]
        if not runs:
            return None
        return runs[-1]

    def _current_indices(self) -> list[int]:
        return [row.current_index() for row in self._rows]

    def _refresh_canvas_from_current_indices(self) -> None:
        if self._cache is None:
            self._clear_canvas()
            return
        indices = self._current_indices()
        pose = self._cache.pose_at(indices)
        self.main_window.canvas.set_kinematic_cloud(self._cache.point_cloud())
        if self.action_show_traj.isChecked():
            self.main_window.canvas.set_kinematic_trajectory(self._cache.inner_axis_line(indices))
        else:
            self.main_window.canvas.set_kinematic_trajectory([])
        if pose is None:
            self.main_window.canvas.set_playback_locked(True, "Cell has no solution")
            self.main_window.canvas.set_kinematic_pose(None)
            return
        self.main_window.canvas.set_playback_locked(False)
        self.main_window.canvas.set_kinematic_pose(pose)

    def _clear_canvas(self) -> None:
        self.main_window.canvas.set_playback_locked(False)
        self.main_window.canvas.set_kinematic_pose(None)
        self.main_window.canvas.set_kinematic_cloud([])
        self.main_window.canvas.set_kinematic_trajectory([])

    def _refresh_metrics_tab(self, run) -> None:
        if self._report is None:
            return
        rows = []
        if run is not None:
            rows = [[key, f"{value:.6g}"] for key, value in sorted(run.metrics.items())]
        self._report.replace_table_tab("Metrics", ["Key", "Value"], rows)
