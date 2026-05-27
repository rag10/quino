import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.application.service import ApplicationService
from quino.domain.plotting import MetricDef, PlotDef, YSeries


def test_plot_def_defaults() -> None:
    plot = PlotDef(id="p1", title="hub y vs t")
    assert plot.x_kind == "time"
    assert plot.x_target == ""
    assert plot.y_series == []


def test_metric_def_defaults() -> None:
    metric = MetricDef(id="m1", key="hub_y_max", name="Hub Y max")
    assert metric.kind == "max"
    assert metric.tags == []


def test_config_plots_persisted_roundtrip(tmp_path) -> None:
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    body = svc.project.model.bodies[0]
    marker_id = body.markers[0].id
    sensor_id = svc.create_sensor("Hub", "point", [marker_id])
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("D", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id)
    analysis.config.plots.append(
        PlotDef(id="pl_1", title="hub.y vs time", y_series=[YSeries(sensor_id=sensor_id, channel="y")])
    )
    analysis.config.metrics.append(
        MetricDef(id="m1", key="max_hub_y", name="max y", kind="max", target=f"{sensor_id}:y", tags=["comfort"])
    )
    path = tmp_path / "p.quino.json"
    svc.save_workspace(str(path))
    svc2 = ApplicationService()
    svc2.load_workspace(str(path))
    ws2 = svc2._workspace
    case2 = ws2.cases.get(case.id) or ws2.cases[ws2.root_case_ids[0]]
    analysis2 = next(item for item in case2.analyses if item.id == analysis.id)
    assert len(analysis2.config.plots) == 1
    assert analysis2.config.plots[0].title == "hub.y vs time"
    assert analysis2.config.metrics[0].tags == ["comfort"]
