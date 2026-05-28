from __future__ import annotations

import math
from pathlib import Path

from PySide6 import QtWidgets

from quino.gui.analysis_modes import register_mode
from quino.gui.analysis_modes._base import AnalysisModeController
from quino.gui.widgets.report_panel import ReportPanelWidget
from quino.pose.geometry import pose_to_state_overlay
from quino.services.workspace_runner import load_result_artifact


@register_mode("dynamic")
class DynamicModeController(AnalysisModeController):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self._current_analysis = None
        self._metrics_panel: ReportPanelWidget | None = None
        self._config_panel: QtWidgets.QWidget | None = None
        self._playback_panel: QtWidgets.QGroupBox | None = None

    def build_toolbar(self, parent: QtWidgets.QWidget) -> QtWidgets.QToolBar:
        self.toolbar = self.main_window._analysis_toolbar
        self.toolbar.clear()
        self.main_window._add_toolbar_block(
            self.toolbar,
            [[self.main_window.action_validate, self.main_window.action_run, self.main_window.action_play_pause, self.main_window.action_stop]],
            "Run",
        )
        self.main_window._add_toolbar_sep(self.toolbar)
        self.main_window._add_toolbar_block(
            self.toolbar,
            [[self.main_window.action_new_plot, self.main_window.action_compare_runs, self.main_window.action_show_trajectories]],
            "View",
        )
        self.main_window._add_toolbar_sep(self.toolbar)
        self.main_window._add_toolbar_block(
            self.toolbar,
            [[self.main_window.action_export_script]],
            "Export",
        )
        return self.toolbar

    def build_config_widget(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        if self._config_panel is None:
            panel = QtWidgets.QWidget(parent)
            layout = QtWidgets.QHBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            layout.addWidget(QtWidgets.QLabel("Duration:"))
            layout.addWidget(self.main_window.duration_spin)
            layout.addSpacing(20)
            layout.addWidget(QtWidgets.QLabel("Frames:"))
            layout.addWidget(self.main_window.steps_spin)
            layout.addSpacing(20)
            layout.addWidget(QtWidgets.QLabel("Dt:"))
            layout.addWidget(self.main_window.dt_spin)
            layout.addStretch()
            self._config_panel = panel
        self.config_widget = self._config_panel
        return self.config_widget

    def build_bottom_panel(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        if self._playback_panel is None:
            playback_panel = QtWidgets.QGroupBox("Analysis", parent)
            playback_panel.setFlat(True)
            layout = QtWidgets.QVBoxLayout(playback_panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)

            controls_layout = QtWidgets.QHBoxLayout()
            controls_layout.addWidget(self.main_window.action_run_button)
            controls_layout.addWidget(self.main_window.action_play_button)
            controls_layout.addWidget(self.main_window.action_stop_button)
            controls_layout.addSpacing(12)
            controls_layout.addWidget(QtWidgets.QLabel("Frame:"))
            controls_layout.addWidget(self.main_window.timeline_slider)
            controls_layout.addWidget(self.main_window.timeline_label)
            controls_layout.addSpacing(12)
            controls_layout.addWidget(QtWidgets.QLabel("Speed:"))
            controls_layout.addWidget(self.main_window.playback_speed_spin)
            layout.addLayout(controls_layout)

            self._metrics_panel = ReportPanelWidget(playback_panel)
            layout.addWidget(self._metrics_panel)
            self._playback_panel = playback_panel
        self.bottom_panel = self._playback_panel
        return self.bottom_panel

    def on_enter(self, analysis) -> None:
        self._current_analysis = analysis
        self._populate_config_from_analysis()
        self.main_window.canvas.set_mode_badge_suffix("(dynamic)")
        if self._metrics_panel is not None:
            self._metrics_panel.setVisible(True)
        latest = self._latest_run()
        if latest is not None:
            self.on_run_selected(latest)
        else:
            self.clear_simulation_state()
            self._refresh_metrics_tab(None)
            self.main_window._append_message("No persisted runs for this analysis yet.")

    def on_leave(self) -> None:
        self.stop_playback()
        self.main_window.canvas.set_mode_badge_suffix("")
        if self._metrics_panel is not None:
            self._metrics_panel.clear_tabs()
            self._metrics_panel.setVisible(False)
        for widget in (
            self.main_window.action_run_button,
            self.main_window.action_play_button,
            self.main_window.action_stop_button,
            self.main_window.timeline_slider,
            self.main_window.timeline_label,
            self.main_window.playback_speed_spin,
            self.main_window.duration_spin,
            self.main_window.steps_spin,
            self.main_window.dt_spin,
        ):
            widget.setParent(self.main_window._playback_widget)
        self._current_analysis = None

    def on_run_clicked(self) -> None:
        if self._current_analysis is None:
            return
        self._sync_config_into_analysis()
        self.main_window._on_run_analysis_requested(self._current_analysis.id)

    def on_run_selected(self, run) -> None:
        project_dir = self.main_window.app_service.current_project_dir
        result = load_result_artifact(project_dir, run)
        self.main_window._last_simulation_result = result
        self.main_window._current_frame_index = 0
        self.update_timeline_controls()
        self.apply_current_frame()
        self.update_trajectories(result=result)
        self._refresh_metrics_tab(run)

    def on_run_finished(self, run_id: str, status: str) -> None:
        if self._current_analysis is None or status not in {"ok", "partial"}:
            return
        case = self.main_window.app_service.current_case()
        if case is None:
            return
        run = next((item for item in case.runs if item.id == run_id), None)
        if run is None or run.analysis_id != self._current_analysis.id:
            return
        self.on_run_selected(run)

    def _refresh_metrics_tab(self, run) -> None:
        if self._metrics_panel is None:
            return
        rows = []
        if run is not None:
            rows = [[key, f"{value:.6g}"] for key, value in sorted(run.metrics.items())]
        self._metrics_panel.replace_table_tab("Metrics", ["Key", "Value"], rows)

    def _latest_run(self):
        case = self.main_window.app_service.current_case()
        if case is None or self._current_analysis is None:
            return None
        runs = [
            run for run in case.runs
            if run.analysis_id == self._current_analysis.id
            and run.status in {"ok", "partial"}
            and run.result_ref is not None
        ]
        return runs[-1] if runs else None

    def export_to_python_script(self) -> None:
        if self.main_window.app_service.simulation_runner.backend_name() != "exudyn":
            QtWidgets.QMessageBox.information(
                self.main_window,
                "Export not available",
                "Script export is only supported for the Exudyn solver backend.",
            )
            return
        default_dir = Path("logs")
        default_dir.mkdir(exist_ok=True)
        default_path = str(default_dir / "exudyn_simulation.py")
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.main_window,
            "Export Exudyn Script",
            default_path,
            "Python Files (*.py)",
        )
        if not file_path:
            return
        try:
            script = self.main_window.app_service.export_exudyn_script(
                duration=float(self.main_window.duration_spin.value()),
                steps=int(self.main_window.steps_spin.value()),
            )
            Path(file_path).write_text(script, encoding="utf-8")
            self.main_window._append_message(f"Exported Exudyn script to {file_path}")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self.main_window,
                "Export failed",
                f"Failed to export script:\n\n{exc}",
            )

    def run_simulation(self) -> None:
        self.main_window._playback_timer.stop()
        self.sync_play_pause_icon()
        result = self.main_window.app_service.run_kinematic_simulation(
            duration=float(self.main_window.duration_spin.value()),
            steps=int(self.main_window.steps_spin.value()),
        )
        self.main_window._last_simulation_result = result
        self.main_window._current_frame_index = 0
        self.main_window.validation_view.setPlainText(
            "\n".join(
                ["Simulation diagnostics:"]
                + [f"  {warning}" for warning in result.warnings]
                + [f"  {message}" for message in result.messages]
                + ([f"  ERROR: {result.error}"] if result.error else [])
            ).strip()
        )
        self.main_window._append_message(f"Simulation backend: {result.backend}")
        for warning in result.warnings:
            self.main_window._append_message(f"  warning: {warning}")
        for message in result.messages:
            self.main_window._append_message(f"  {message}")
        self.update_timeline_controls()
        self.apply_current_frame()
        self.update_trajectories()
        self.main_window.refresh_all()
        if result.error:
            self.main_window._append_message(f"  ERROR: {result.error}")
            detail = ""
            icon = QtWidgets.QMessageBox.Icon.Critical
            if result.frames:
                detail = f"\n\nPartial trajectory available: {len(result.frames)} frame(s)."
                icon = QtWidgets.QMessageBox.Icon.Warning
            message_box = QtWidgets.QMessageBox(self.main_window)
            message_box.setIcon(icon)
            message_box.setWindowTitle("Analysis Error")
            message_box.setText(f"Analysis failed:\n\n{result.error}{detail}")
            message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
            message_box.exec()

    def toggle_playback(self) -> None:
        result = self.main_window._last_simulation_result
        if result is None or not result.frames:
            return
        if self.main_window._playback_timer.isActive():
            self.main_window._playback_timer.stop()
            self.sync_play_pause_icon()
            self.main_window._update_interaction_state()
            return
        self.main_window._playback_timer.start(40)
        self.sync_play_pause_icon()
        self.main_window._update_interaction_state()

    def stop_playback(self) -> None:
        self.main_window._playback_timer.stop()
        self.main_window._current_frame_index = 0
        self.apply_current_frame()
        self.update_timeline_controls()
        self.sync_play_pause_icon()
        self.main_window._update_interaction_state()

    def sync_play_pause_icon(self) -> None:
        if self.main_window._playback_timer.isActive():
            self.main_window.action_play_pause.setIcon(self.main_window._icon_pause)
            self.main_window.action_play_pause.setText("Pause")
        else:
            self.main_window.action_play_pause.setIcon(self.main_window._icon_play)
            self.main_window.action_play_pause.setText("Play")

    def advance_playback(self) -> None:
        result = self.main_window._last_simulation_result
        if result is None or not result.frames:
            self.stop_playback()
            return
        n_frames = len(result.frames)
        if self.main_window._current_frame_index >= n_frames - 1:
            self.stop_playback()
            return
        duration = self.main_window.duration_spin.value()
        steps = self.main_window.steps_spin.value()
        sim_dt = duration / steps if steps > 0 else 0.04
        playback_speed = self.main_window.playback_speed_spin.value()
        step_jump = max(1, round(playback_speed * 0.04 / sim_dt))
        self.main_window._current_frame_index = min(self.main_window._current_frame_index + step_jump, n_frames - 1)
        self.apply_current_frame()
        self.update_timeline_controls()

    def on_timeline_changed(self, value: int) -> None:
        self.main_window._current_frame_index = value
        self.apply_current_frame()
        self.update_timeline_controls()

    def on_duration_changed(self) -> None:
        if self.main_window._suspend_simulation_config_updates:
            return
        duration = self.main_window.duration_spin.value()
        dt = self.main_window.dt_spin.value()
        if dt > 0:
            steps = max(1, round(duration / dt))
            self.main_window._suspend_simulation_config_updates = True
            try:
                self.main_window.steps_spin.setValue(steps)
                self.main_window.dt_spin.setValue(duration / steps)
            finally:
                self.main_window._suspend_simulation_config_updates = False
        self.update_simulation_spin_steps()
        self.discard_simulation_for_parameter_change("Simulation discarded because duration changed")
        self._sync_config_into_analysis()

    def on_steps_changed(self) -> None:
        if self.main_window._suspend_simulation_config_updates:
            return
        duration = self.main_window.duration_spin.value()
        steps = self.main_window.steps_spin.value()
        if steps > 0:
            self.main_window._suspend_simulation_config_updates = True
            try:
                self.main_window.dt_spin.setValue(duration / steps)
            finally:
                self.main_window._suspend_simulation_config_updates = False
        self.update_simulation_spin_steps()
        self.discard_simulation_for_parameter_change("Simulation discarded because frame count changed")
        self._sync_config_into_analysis()

    def on_dt_changed(self) -> None:
        if self.main_window._suspend_simulation_config_updates:
            return
        duration = self.main_window.duration_spin.value()
        dt = self.main_window.dt_spin.value()
        if dt > 0:
            steps = max(1, round(duration / dt))
            self.main_window._suspend_simulation_config_updates = True
            try:
                self.main_window.steps_spin.setValue(steps)
                self.main_window.dt_spin.setValue(duration / steps)
            finally:
                self.main_window._suspend_simulation_config_updates = False
        self.update_simulation_spin_steps()
        self.discard_simulation_for_parameter_change("Simulation discarded because delta t changed")
        self._sync_config_into_analysis()

    def on_playback_speed_changed(self) -> None:
        self.update_simulation_spin_steps()

    def update_simulation_spin_steps(self) -> None:
        self.main_window.steps_spin.setSingleStep(self.adaptive_frame_step(self.main_window.steps_spin.value()))
        self.main_window.dt_spin.setSingleStep(self.adaptive_fractional_step(self.main_window.dt_spin.value()))
        self.main_window.playback_speed_spin.setSingleStep(
            self.adaptive_fractional_step(self.main_window.playback_speed_spin.value())
        )

    def adaptive_frame_step(self, value: int) -> int:
        return max(1, value // 10)

    def adaptive_fractional_step(self, value: float) -> float:
        magnitude = abs(value)
        if magnitude <= 0.0:
            return 0.0005
        exponent = math.floor(math.log10(magnitude))
        return 0.5 * (10 ** exponent)

    def discard_simulation_for_parameter_change(self, message: str) -> None:
        if self.has_simulation_frames():
            self.clear_simulation_state(message)

    def rewind_simulation_to_start(self) -> None:
        self.main_window._playback_timer.stop()
        self.sync_play_pause_icon()
        self.main_window._current_frame_index = 0
        self.apply_current_frame()
        self.update_timeline_controls()

    def apply_current_frame(self) -> None:
        frame = None
        time_value = 0.0
        if self.main_window._last_simulation_result is not None and self.main_window._last_simulation_result.frames:
            index = max(
                0,
                min(
                    self.main_window._current_frame_index,
                    len(self.main_window._last_simulation_result.frames) - 1,
                ),
            )
            frame = self.main_window._last_simulation_result.frames[index]
            if index < len(self.main_window._last_simulation_result.time):
                time_value = self.main_window._last_simulation_result.time[index]
        else:
            initial_pose = self._analysis_initial_pose()
            if initial_pose is not None:
                frame = pose_to_state_overlay(initial_pose)
        self.main_window._last_simulation_state = frame
        self.main_window.canvas.set_state_overlay(frame)
        self.main_window.canvas.set_simulation_time(time_value)
        if self.main_window.app_service.project is not None:
            self.main_window._populate_canvas_summary(self.main_window.app_service.project)
        self.main_window._update_interaction_state()

    def _analysis_initial_pose(self):
        if self._current_analysis is None:
            return self.main_window.app_service.get_simulation_initial_pose()
        ws = self.main_window.app_service._workspace
        case = self.main_window.app_service.current_case()
        if ws is None or case is None or self._current_analysis.pose_id is None:
            return self.main_window.app_service.get_simulation_initial_pose()
        return next((p for p in case.poses if p.id == self._current_analysis.pose_id), None)

    def update_timeline_controls(self) -> None:
        result = self.main_window._last_simulation_result
        if result is None or not result.frames:
            self.main_window.timeline_slider.blockSignals(True)
            self.main_window.timeline_slider.setRange(0, 0)
            self.main_window.timeline_slider.setValue(0)
            self.main_window.timeline_slider.blockSignals(False)
            self.main_window.timeline_label.setText("0 / 0")
            return
        max_index = len(result.frames) - 1
        current = max(0, min(self.main_window._current_frame_index, max_index))
        self.main_window.timeline_slider.blockSignals(True)
        self.main_window.timeline_slider.setRange(0, max_index)
        self.main_window.timeline_slider.setValue(current)
        self.main_window.timeline_slider.blockSignals(False)
        current_time = result.time[current] if current < len(result.time) else float(current)
        self.main_window.timeline_label.setText(f"{current + 1} / {len(result.frames)}  t={current_time:.3f}s")

    def has_simulation_frames(self) -> bool:
        return self.main_window._last_simulation_result is not None and bool(self.main_window._last_simulation_result.frames)

    def clear_simulation_state(self, message: str | None = None) -> None:
        self.main_window._playback_timer.stop()
        self.sync_play_pause_icon()
        self.main_window._last_simulation_result = None
        self.main_window._last_simulation_state = None
        self.main_window._current_frame_index = 0
        self.apply_current_frame()
        self.main_window.canvas.set_trajectories([])
        self.main_window.action_show_trajectories.setEnabled(False)
        self.update_timeline_controls()
        self.main_window._update_interaction_state()
        if self.main_window.app_service.project is not None:
            self.main_window.app_service.project.reaction_outputs.clear()
            self.main_window.app_service.project.sensor_outputs.clear()
        if message:
            self.main_window._append_message(message)

    def update_trajectories(self, *, result=None) -> None:
        project = self.main_window.app_service.project
        if project is None:
            return
        trajectories: list[list[tuple[float, float]]] = []
        if result is not None and result.frames:
            for sensor in project.model.sensors:
                if sensor.type.value != "point" or not sensor.marker_ids:
                    continue
                marker_id = sensor.marker_ids[0]
                key_x = f"marker:{marker_id}:x"
                key_y = f"marker:{marker_id}:y"
                points: list[tuple[float, float]] = []
                for frame in result.frames:
                    if key_x in frame and key_y in frame:
                        points.append((float(frame[key_x]), float(frame[key_y])))
                if len(points) >= 2:
                    trajectories.append(points)
        if not trajectories:
            for sensor in project.model.sensors:
                if sensor.type.value != "point":
                    continue
                output = project.sensor_outputs.get(sensor.id)
                if output is None or not output.data:
                    continue
                points = [(row[0], row[1]) for row in output.data]
                if len(points) >= 2:
                    trajectories.append(points)
        self.main_window.canvas.set_trajectories(trajectories)
        self.main_window.action_show_trajectories.setEnabled(bool(trajectories))
        if trajectories:
            self.main_window.action_show_trajectories.setChecked(True)
            self.main_window.canvas.set_show_trajectories(True)

    def _populate_config_from_analysis(self) -> None:
        if self._current_analysis is None:
            return
        config = self._current_analysis.config
        self.main_window._suspend_simulation_config_updates = True
        try:
            self.main_window.duration_spin.setValue(float(config.duration))
            self.main_window.steps_spin.setValue(int(config.steps))
            self.main_window.dt_spin.setValue(float(config.dt))
        finally:
            self.main_window._suspend_simulation_config_updates = False
        self.update_simulation_spin_steps()

    def _sync_config_into_analysis(self) -> None:
        if self._current_analysis is None:
            return
        config = self._current_analysis.config
        config.duration = float(self.main_window.duration_spin.value())
        config.steps = int(self.main_window.steps_spin.value())
        config.dt = float(self.main_window.dt_spin.value())
