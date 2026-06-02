from __future__ import annotations

import math

from quino.analysis.kinematic_runner import KinematicAnalysisRunner
from quino.analysis.runner import AnalysisResult
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.model import BodyPose
from quino.domain.workspace import Pose
from quino.domain.workspace import SweepDef
from quino.services.sensor_extraction_kinematic import extract_sensors_from_pose


def _bar_project():
    svc = ApplicationService()
    svc.new_workspace("k")
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


def test_empty_pose_falls_back_to_reference(monkeypatch) -> None:
    svc, body_id, marker_a, marker_b = _bar_project()
    case = svc.workspace.create_case("C")
    empty_pose = Pose(id="empty", name="Empty", body_poses={})
    case.poses.append(empty_pose)
    analysis = svc.workspace.create_analysis(
        "Sweep", analysis_type="kinematic", case_id=case.id, workspace_pose_id=empty_pose.id
    )
    analysis.config.sweeps.append(
        SweepDef(
            id="sw1",
            variable_kind="marker_x",
            target_ids=[marker_b.id],
            mode="linear",
            start=-10.0,
            end=10.0,
            steps=3,
            reference_mode="relative",
        )
    )

    received_initial_poses = []

    class FakePoseRunner:
        def __init__(self, adapter) -> None:
            pass

        def solve(self, project, initial_pose, temporary_constraints=None, settings=None):
            received_initial_poses.append(initial_pose)
            pose = Pose(
                id="ok",
                name="ok",
                body_poses={body_id: BodyPose(body_id=body_id, x=0.0, y=0.0, angle=0.0)},
            )
            return type("R", (), {"success": True, "pose": pose})()

    monkeypatch.setattr("quino.pose.runner.PoseRunner", FakePoseRunner)
    result = KinematicAnalysisRunner().run(svc.project, analysis, initial_pose=empty_pose)
    assert result.status == "ok"
    assert received_initial_poses[0] is not None
    assert received_initial_poses[0].body_poses, "Empty pose should be replaced with reference pose"
    # Base value should come from the reference pose: marker_b is at x=100 in reference.
    assert result.sweep_axes[0]["values"] == [90.0, 100.0, 110.0]


def test_perturbed_solution_does_not_corrupt_next_cell(monkeypatch) -> None:
    svc, body_id, marker_a, marker_b = _bar_project()
    case = svc.workspace.create_case("C")
    pose = Pose(
        id="p1",
        name="P1",
        body_poses={body_id: BodyPose(body_id=body_id, x=0.0, y=0.0, angle=0.0)},
    )
    case.poses.append(pose)
    analysis = svc.workspace.create_analysis(
        "Sweep", analysis_type="kinematic", case_id=case.id, workspace_pose_id=pose.id
    )
    analysis.config.sweeps.append(
        SweepDef(
            id="sw1",
            variable_kind="marker_x",
            target_ids=[marker_b.id],
            mode="linear",
            start=100.0,
            end=104.0,
            steps=3,
        )
    )

    # Fake solver: first call returns a "perturbed" pose with a 50 mm drift.
    # Subsequent calls succeed only if the initial pose is the clean one,
    # not the drifted one — simulating Exudyn refusing to converge from a
    # pose with residual constraint violations.
    call_count = {"n": 0}
    clean_pose = Pose(
        id="ok",
        name="ok",
        body_poses={body_id: BodyPose(body_id=body_id, x=0.0, y=0.0, angle=0.0)},
    )
    drifted_pose = Pose(
        id="drift",
        name="drift",
        body_poses={body_id: BodyPose(body_id=body_id, x=50.0, y=0.0, angle=0.5)},
    )

    class FakePoseRunner:
        def __init__(self, adapter) -> None:
            pass

        def solve(self, project, initial_pose, temporary_constraints=None, settings=None):
            call_count["n"] += 1
            # First solve: returns drifted pose with a perturbed-guess warning.
            if call_count["n"] == 1:
                return type("R", (), {
                    "success": True,
                    "pose": drifted_pose,
                    "warnings": ["Pose solve required a perturbed initial guess near a singular configuration"],
                })()
            # Subsequent solves: succeed only when given the clean pose.
            ok = initial_pose is not None and abs(initial_pose.body_poses[body_id].x) < 1.0
            return type("R", (), {
                "success": ok,
                "pose": clean_pose if ok else None,
                "warnings": [],
                "error": None if ok else "diverged",
            })()

    monkeypatch.setattr("quino.pose.runner.PoseRunner", FakePoseRunner)
    result = KinematicAnalysisRunner().run(svc.project, analysis, initial_pose=pose)
    assert result.status == "ok", f"expected ok, got {result.status} (failed_mask={result.failed_mask})"
    assert not any(result.failed_mask)


def test_relative_mode_offsets_values_by_base(monkeypatch) -> None:
    svc, body_id, marker_a, marker_b = _bar_project()
    case = svc.workspace.create_case("C")
    # Pose with body at x=10, y=0, angle=0 → marker_b at world x=110
    pose = Pose(
        id="p1",
        name="P1",
        body_poses={body_id: BodyPose(body_id=body_id, x=10.0, y=0.0, angle=0.0)},
    )
    case.poses.append(pose)
    analysis = svc.workspace.create_analysis(
        "Sweep", analysis_type="kinematic", case_id=case.id, workspace_pose_id=pose.id
    )
    # Relative sweep: start=-10, end=10 → absolute values should be [100, 110, 120]
    analysis.config.sweeps.append(
        SweepDef(
            id="sw1",
            variable_kind="marker_x",
            target_ids=[marker_b.id],
            mode="linear",
            start=-10.0,
            end=10.0,
            steps=3,
            reference_mode="relative",
        )
    )

    received_values = []

    class FakePoseRunner:
        def __init__(self, adapter) -> None:
            pass

        def solve(self, project, initial_pose, temporary_constraints=None, settings=None):
            value = temporary_constraints[0].metadata["value"]
            received_values.append(value)
            pose = Pose(
                id="ok",
                name="ok",
                body_poses={body_id: BodyPose(body_id=body_id, x=0.0, y=0.0, angle=0.0)},
            )
            return type("R", (), {"success": True, "pose": pose})()

    monkeypatch.setattr("quino.pose.runner.PoseRunner", FakePoseRunner)
    result = KinematicAnalysisRunner().run(svc.project, analysis, initial_pose=pose)
    assert result.status == "ok"
    # Absolute values should be 110 + [-10, 0, 10] = [100, 110, 120]
    assert received_values == [100.0, 110.0, 120.0]
    assert result.sweep_axes[0]["values"] == [100.0, 110.0, 120.0]
