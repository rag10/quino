from __future__ import annotations

import json
from pathlib import Path

from quino.domain.plotting import PlotDef, YSeries


def render_plot(plot: PlotDef, runs_with_artifacts: list[tuple[str, dict]]):
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    for run_label, artifact in runs_with_artifacts:
        for series in plot.y_series:
            x_values, y_values = _series_xy(plot, series, artifact)
            if not x_values or not y_values:
                continue
            ax.plot(
                x_values,
                y_values,
                label=f"{run_label} - {series.label or series.channel or series.sensor_id}",
                color=series.color or None,
            )
    ax.set_title(plot.title)
    ax.legend()
    ax.grid(True, alpha=0.3)
    return fig


def load_artifact(project_dir: Path | None, run) -> dict:
    if project_dir is None or run.result_ref is None:
        return {}
    path = project_dir / run.result_ref.artifact_path
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _series_xy(plot: PlotDef, series: YSeries, artifact: dict) -> tuple[list[float], list[float]]:
    y_values = _series_values(artifact, series.sensor_id, series.channel)
    if not y_values:
        return [], []
    if plot.x_kind == "time":
        times = list(artifact.get("time", []))
        if times:
            return times[: len(y_values)], y_values[: len(times)]
        return list(range(len(y_values))), y_values
    if plot.x_kind == "sweep_axis":
        axes = list(artifact.get("sweep_axes", []))
        axis = next((item for item in axes if item.get("id") == plot.x_target), None)
        if axis is not None:
            x_values = list(axis.get("values", []))
            return x_values[: len(y_values)], y_values[: len(x_values)]
    if plot.x_kind == "sensor_channel":
        parts = plot.x_target.split(":")
        if len(parts) >= 2:
            x_values = _series_values(artifact, parts[0], parts[1])
            return x_values[: len(y_values)], y_values[: len(x_values)]
    return list(range(len(y_values))), y_values


def _series_values(artifact: dict, sensor_id: str, channel: str) -> list[float]:
    from quino.services.metric_evaluator import _series

    return list(_series(artifact, sensor_id, channel))
