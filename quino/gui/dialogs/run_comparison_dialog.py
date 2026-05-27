from __future__ import annotations

from collections import defaultdict

from PySide6 import QtCore, QtWidgets

from quino.domain.plotting import PlotDef, YSeries
from quino.gui.icons import get_icon
from quino.gui.theme import VIOLET
from quino.services.plot_renderer import load_artifact, render_plot


class RunComparisonDialog(QtWidgets.QDialog):
    def __init__(self, app_service, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.app_service = app_service
        self.setWindowTitle("Compare Runs")
        self.resize(900, 520)
        self._run_items: dict[tuple[str, str], QtWidgets.QTreeWidgetItem] = {}

        layout = QtWidgets.QVBoxLayout(self)
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self)
        self.run_tree = QtWidgets.QTreeWidget(split)
        self.run_tree.setHeaderLabels(["Analysis / Run"])
        self.channel_list = QtWidgets.QListWidget(split)
        split.addWidget(self.run_tree)
        split.addWidget(self.channel_list)
        split.setSizes([520, 280])
        layout.addWidget(split)

        plot_btn = QtWidgets.QPushButton(get_icon("new-graph", VIOLET, size=16), "Plot", self)
        plot_btn.clicked.connect(self._plot_selected)
        layout.addWidget(plot_btn)

        self.run_tree.itemChanged.connect(self._on_item_changed)
        self._populate_runs()

    def _populate_runs(self) -> None:
        ws = self.app_service._workspace
        if ws is None:
            return
        by_name: dict[str, list] = defaultdict(list)
        for case in ws.cases.values():
            analyses = {a.id: a for a in case.analyses}
            for run in case.runs:
                analysis = analyses.get(run.analysis_id)
                if analysis is None:
                    continue
                by_name[analysis.name].append((analysis, run))
        for analysis_name, items in by_name.items():
            root = QtWidgets.QTreeWidgetItem([analysis_name])
            self.run_tree.addTopLevelItem(root)
            for analysis, run in items:
                item = QtWidgets.QTreeWidgetItem([f"{run.id} ({analysis.analysis_type})"])
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, (analysis.name, run.id))
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
                root.addChild(item)
                self._run_items[(analysis.name, run.id)] = item
            root.setExpanded(True)

    def _on_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        key = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not key:
            return
        selected_names = {
            analysis_name
            for (analysis_name, _run_id), run_item in self._run_items.items()
            if run_item.checkState(0) == QtCore.Qt.CheckState.Checked
        }
        locked_name = next(iter(selected_names), None) if len(selected_names) == 1 else None
        self.run_tree.blockSignals(True)
        for (analysis_name, _run_id), run_item in self._run_items.items():
            if locked_name is not None and analysis_name != locked_name:
                run_item.setDisabled(True)
                run_item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
            else:
                run_item.setDisabled(False)
        self.run_tree.blockSignals(False)
        self._refresh_channels()

    def _refresh_channels(self) -> None:
        self.channel_list.clear()
        selected = self._selected_runs()
        if not selected:
            return
        intersections: set[str] | None = None
        for _label, artifact in selected:
            channels = _artifact_channels(artifact)
            intersections = channels if intersections is None else intersections & channels
        for channel in sorted(intersections or set()):
            item = QtWidgets.QListWidgetItem(channel)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Unchecked)
            self.channel_list.addItem(item)

    def _selected_runs(self) -> list[tuple[str, dict]]:
        ws = self.app_service._workspace
        if ws is None:
            return []
        runs = {run.id: run for case in ws.cases.values() for run in case.runs}
        out: list[tuple[str, dict]] = []
        for (analysis_name, run_id), item in self._run_items.items():
            if item.checkState(0) != QtCore.Qt.CheckState.Checked:
                continue
            run = runs.get(run_id)
            if run is None:
                continue
            out.append((run_id, load_artifact(self.app_service.current_project_dir, run)))
        return out

    def _plot_selected(self) -> None:
        selected = self._selected_runs()
        channels = [
            self.channel_list.item(index).text()
            for index in range(self.channel_list.count())
            if self.channel_list.item(index).checkState() == QtCore.Qt.CheckState.Checked
        ]
        if not selected or not channels:
            return
        plot = PlotDef(
            id="compare",
            title="Run comparison",
            x_kind="time",
            y_series=[YSeries(sensor_id=channel.split(":")[0], channel=channel.split(":")[1]) for channel in channels],
        )
        figure = render_plot(plot, selected)
        figure.show()

    def _find_run_item(self, analysis_name: str, run_id: str) -> QtWidgets.QTreeWidgetItem | None:
        return self._run_items.get((analysis_name, run_id))


def _artifact_channels(artifact: dict) -> set[str]:
    frames = artifact.get("frames")
    if frames:
        first = frames[0]
        out = set()
        for key in first:
            if key.startswith("sensor:"):
                parts = key.split(":")
                if len(parts) >= 3:
                    out.add(f"{parts[1]}:{parts[2]}")
        return out
    sensors = artifact.get("sensors", {})
    out = set()
    for sensor_id, blob in sensors.items():
        for channel in blob.get("channels", []):
            out.add(f"{sensor_id}:{channel}")
    return out
