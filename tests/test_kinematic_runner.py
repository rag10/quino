from __future__ import annotations

import math

from quino.analysis.kinematic_runner import KinematicAnalysisRunner
from quino.analysis.runner import AnalysisResult
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.model import BodyPose, Pose
from quino.domain.workspace import SweepDef
from quino.services.sensor_extraction_kinematic import extract_sensors_from_pose


def _bar_project():
    svc = ApplicationService()
    svc.new_project("k")
    body_id = svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = svc.get_body(body_id)
    marker_a = next(marker for marker in body.markers if marker.name == "A")
    marker_b = next(marker for marker in body.markers if marker.name == "B")
    svc.connect_marker_to_ground(marker_a.id, joint_type="revolute", name="Pivot")
    return svc, body_id, marker_a, marker_b


def test_extract_point_sensor() -> None:
    svc, body_id, marker_a, marker_b = _bar_project()
    sensor_id = svc.create_sensor("PosB", "point", [marker_b.id])
    pose = Pose(
        id="p1",
        name="P1",
        body_poses={body_id: BodyPose(body_id=body_id, x=0.0, y=0.0, angle=0.0)},
    )
    data = extract_sensors_from_pose(svc.project, pose)
    assert sensor_id in data
    assert data[sensor_id]["channels"] == ["x", "y", "vx", "vy", "ax", "ay"]
    assert math.isnan(data[sensor_id]["values"][2])
    assert data[sensor_id]["values"][0] == 100.0


def test_two_axis_sweep_visits_all_cells_in_snake_order() -> None:
    order = list(KinematicAnalysisRunner()._snake_iter([3, 4]))
    assert len(order) == 12
    for previous, current in zip(order, order[1:]):
        diff = sum(abs(a - b) for a, b in zip(previous, current))
        assert diff == 1


def test_ramp_splits_large_steps() -> None:
    runner = KinematicAnalysisRunner()
    steps = list(runner._ramp([40.0], [0.0], ["marker_x"]))
    assert len(steps) == 4
    assert steps[-1] == [40.0]


def test_unreachable_cells_write_nan_and_partial(monkeypatch) -> None:
    svc, body_id, marker_a, marker_b = _bar_project()
    sensor_id = svc.create_sensor("PosB", "point", [marker_b.id])
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("Sweep", analysis_type="kinematic", case_id=case.id, workspace_pose_id=pose.id)
    analysis.config.sweeps.append(
        SweepDef(id="sw1", variable_kind="marker_x", target_ids=[marker_b.id], mode="linear", start=20.0, end=80.0, steps=4)
    )

    class FakePoseRunner:
        def __init__(self, adapter) -> None:
            pass

        def solve(self, project, initial_pose, temporary_constraints=None, settings=None):
            value = temporary_constraints[0].metadata["value"]
            if value >= 60.0:
                return type("R", (), {"success": False, "pose": None})()
            pose = Pose(
                id="ok",
                name="ok",
                body_poses={body_id: BodyPose(body_id=body_id, x=0.0, y=0.0, angle=0.0)},
            )
            return type("R", (), {"success": True, "pose": pose})()

    monkeypatch.setattr("quino.pose.runner.PoseRunner", FakePoseRunner)
    result = KinematicAnalysisRunner().run(svc.project, analysis)
    assert result.status == "partial"
    assert any(result.failed_mask)
    assert any(math.isnan(value) for value in result.sensors[sensor_id]["values"])
