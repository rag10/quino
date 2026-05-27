from __future__ import annotations

import json

from PySide6 import QtWidgets

from quino.analysis.static_runner import StaticAnalysisRunner
from quino.domain.model import ReactionOutput
from quino.gui.analysis_modes import register_mode
from quino.gui.analysis_modes._base import AnalysisModeController
from quino.gui.widgets.report_panel import ReportPanelWidget
from quino.gui.widgets.validation_banner import ValidationBanner


def _fmt(value, decimals: int = 4) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.{decimals}g}"
    except (TypeError, ValueError):
        return str(value)


@register_mode("static")
class StaticModeController(AnalysisModeController):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self.banner: ValidationBanner | None = None
        self.report: ReportPanelWidget | None = None
        self._current_analysis = None
        self._current_pose_blob: dict | None = None
        self._installed_reactions: bool = False

    def build_toolbar(self, parent):
        bar = self.main_window._analysis_toolbar
        bar.clear()
        validate_action = bar.addAction("Validate")
        validate_action.setToolTip(
            "Check whether DoF=0 and force sources exist before running."
        )
        validate_action.triggered.connect(self._on_validate)
        run_action = bar.addAction("Run")
        run_action.setToolTip("Run the static analysis on the current model.")
        run_action.triggered.connect(self.on_run_clicked)
        bar.addSeparator()
        reactions_action = bar.addAction("Show reactions")
        reactions_action.setToolTip("Focus the Reactions tab in the report.")
        reactions_action.triggered.connect(self._on_show_reactions)
        plot_action = bar.addAction("New plot")
        plot_action.triggered.connect(
            lambda: self.main_window._open_plot_editor_for_analysis(self._current_analysis)
        )
        compare_action = bar.addAction("Compare")
        compare_action.triggered.connect(self.main_window._open_compare_runs_dialog)
        self.toolbar = bar
        return bar

    def build_config_widget(self, parent):
        widget = QtWidgets.QWidget(parent)
        form = QtWidgets.QFormLayout(widget)
        self._gravity_cb = QtWidgets.QCheckBox("Gravity enabled", widget)
        self._tolerance_spin = QtWidgets.QDoubleSpinBox(widget)
        # Tolerance is a small absolute number — give it a usable range and
        # step that the user can actually nudge with the spinner.
        self._tolerance_spin.setRange(1e-12, 1.0)
        self._tolerance_spin.setDecimals(10)
        self._tolerance_spin.setSingleStep(1e-7)
        self._tolerance_spin.setValue(1e-6)
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
        self._current_pose_blob = None
        latest = self._latest_report_run()
        if latest is not None:
            self.on_run_selected(latest)
        else:
            # Show the active pose as the canvas state so the user can see
            # what the analysis is about to solve.
            self._apply_pose_from_active_workspace()

    def on_leave(self):
        self.main_window.canvas.set_mode_badge_suffix("")
        self.main_window.canvas.set_kinematic_pose(None)
        self.main_window.canvas.set_state_overlay(None)
        self._uninstall_reactions()
        self._current_pose_blob = None
        self._current_analysis = None

    def apply_current_frame(self) -> None:
        """Re-emit the cached static pose so MainWindow.refresh_all doesn't
        revert the canvas to the reference geometry between selections."""
        if self._current_pose_blob is not None:
            self.main_window.canvas.set_kinematic_pose(self._current_pose_blob)
            return
        # Before a run we still want the active pose visible.
        self._apply_pose_from_active_workspace()

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
        self._uninstall_reactions()
        project_dir = self.main_window.app_service.current_project_dir
        if project_dir is None or run.result_ref is None:
            return
        path = project_dir / run.result_ref.artifact_path
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self._populate_report_tabs(data)
        self._refresh_metrics_tab(run)
        pose_blob = data.get("pose")
        self._current_pose_blob = pose_blob
        self.main_window.canvas.set_kinematic_pose(pose_blob)
        self._install_reactions(data.get("reactions") or [])

    def on_run_finished(self, run_id: str, status: str) -> None:
        # A run that just finished may have changed validity (e.g. user edited
        # the model meanwhile). Always re-validate.
        self._validate_and_refresh_banner()
        if status not in {"ok", "partial"}:
            # Failed: keep the previous pose visible but make sure no stale
            # reaction arrows linger.
            self._uninstall_reactions()
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
            rows = [[key, _fmt(value, 6)] for key, value in sorted(run.metrics.items())]
        self.report.replace_table_tab("Metrics", ["Key", "Value"], rows)

    def _populate_report_tabs(self, data: dict) -> None:
        if self.report is None:
            return
        self.report.add_table_tab(
            "Applied loads",
            ["Name", "Source", "Fx (N)", "Fy (N)"],
            [
                [
                    row.get("name", ""),
                    row.get("source", ""),
                    _fmt(row.get("fx")),
                    _fmt(row.get("fy")),
                ]
                for row in data.get("applied_loads", [])
            ],
        )
        self.report.add_table_tab(
            "Reactions",
            ["Joint", "Fx (N)", "Fy (N)", "Moment (N·mm)", "|F| (N)"],
            [
                [
                    row.get("joint_name", row.get("joint_id", "")),
                    _fmt(row.get("fx")),
                    _fmt(row.get("fy")),
                    _fmt(row.get("moment")),
                    _fmt(((row.get("fx") or 0.0) ** 2 + (row.get("fy") or 0.0) ** 2) ** 0.5),
                ]
                for row in data.get("reactions", [])
            ],
        )
        self.report.add_table_tab(
            "Springs",
            ["Name", "Kind", "F (N)", "Length (mm)", "Energy (J)"],
            [
                [
                    row.get("name", ""),
                    row.get("kind", ""),
                    _fmt(row.get("F")),
                    _fmt(row.get("length")),
                    _fmt(row.get("energy"), 5),
                ]
                for row in data.get("spring_forces", [])
            ],
        )
        self.report.add_kv_tab(
            "Energy",
            [
                ("Total spring potential energy", f"{_fmt(data.get('total_energy_in_springs', 0.0), 5)} J"),
            ],
        )

    def _apply_pose_from_active_workspace(self) -> None:
        """When no run exists yet, show the analysis's bound pose on the canvas."""
        if self._current_analysis is None:
            return
        ws = self.main_window.app_service._workspace
        if ws is None:
            self.main_window.canvas.set_kinematic_pose(None)
            return
        pose_id = self._current_analysis.pose_id
        if pose_id is None:
            self.main_window.canvas.set_kinematic_pose(None)
            return
        pose = next(
            (p for case in ws.cases.values() for p in case.poses if p.id == pose_id),
            None,
        )
        if pose is None or not pose.body_poses:
            self.main_window.canvas.set_kinematic_pose(None)
            return
        blob = {
            body_id: {"x": bp.x, "y": bp.y, "theta": bp.angle}
            for body_id, bp in pose.body_poses.items()
        }
        self.main_window.canvas.set_kinematic_pose(blob)

    def _install_reactions(self, reaction_rows: list[dict]) -> None:
        """Push reaction data into project.reaction_outputs so the canvas
        renders the arrows that already exist for dynamic mode."""
        project = self.main_window.app_service.project
        if project is None or not reaction_rows:
            return
        for row in reaction_rows:
            joint_id = row.get("joint_id")
            if not isinstance(joint_id, str):
                continue
            fx = float(row.get("fx", 0.0))
            fy = float(row.get("fy", 0.0))
            mz = float(row.get("moment", 0.0))
            magnitude = (fx * fx + fy * fy) ** 0.5
            output = ReactionOutput(
                joint_id=joint_id,
                joint_name=str(row.get("joint_name", joint_id)),
                endpoint_type=str(row.get("endpoint_type", "ground")),
                time=[0.0],
                columns=["fx", "fy", "f", "mz"],
                data=[[fx, fy, magnitude, mz]],
                positions=[(
                    float(row.get("position_x", 0.0)),
                    float(row.get("position_y", 0.0)),
                )],
            )
            project.reaction_outputs[joint_id] = output
        self._installed_reactions = True
        # Reaction arrows are interpolated against the canvas's simulation_time;
        # pin it to t=0 so our single-frame static row is selected.
        self.main_window.canvas.set_simulation_time(0.0)
        self.main_window.canvas.update()

    def _uninstall_reactions(self) -> None:
        if not self._installed_reactions:
            return
        project = self.main_window.app_service.project
        if project is not None:
            project.reaction_outputs.clear()
        self._installed_reactions = False
        self.main_window.canvas.update()
