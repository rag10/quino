from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from quino.analysis.kinematic_sweeps import (
    AngleBetweenSegmentsStrategy,
    AngleHorizontalStrategy,
    AngleVerticalStrategy,
    SliderStrokeStrategy,
    body_of_marker,
    compute_sweep_base_value,
    segment_local_angle,
    slider_axis_for,
    strategy_for,
)
from quino.analysis.runner import AnalysisResult, AnalysisRunner
from quino.domain.workspace import Analysis, KinematicConfig, Pose, ResultRef
from quino.pose.geometry import create_reference_pose
from quino.pose.model import PoseSolveSettings
from quino.services.sensor_extraction_kinematic import extract_sensors_from_pose


@dataclass(slots=True)
class KinematicResult(AnalysisResult):
    sweep_axes: list[dict] = field(default_factory=list)
    shape: list[int] = field(default_factory=list)
    sensors: dict[str, dict] = field(default_factory=dict)
    poses: list[dict] = field(default_factory=list)
    failed_mask: list[bool] = field(default_factory=list)


class KinematicAnalysisRunner(AnalysisRunner):
    def validate(self, project, analysis) -> list[str]:
        cfg: KinematicConfig = analysis.config
        errors: list[str] = []
        if not cfg.sweeps:
            errors.append("Kinematic analysis requires at least one sweep variable")
            return errors
        for sweep in cfg.sweeps:
            try:
                strat = strategy_for(sweep)
                self._bind_strategy(strat, project)
            except Exception as exc:
                errors.append(f"Sweep {sweep.id}: {exc}")
        return errors

    def run(
        self,
        project,
        analysis,
        *,
        initial_pose=None,
        cancel_event=None,
        run=None,
        project_dir: Path | None = None,
    ) -> AnalysisResult:
        from quino.pose.runner import PoseRunner
        from quino.services.expressions import ExpressionService
        from quino.services.units import UnitService
        from quino.solver_adapters.exudyn_pose_adapter import ExudynPoseAdapter

        cfg: KinematicConfig = analysis.config
        strategies = [strategy_for(sweep) for sweep in cfg.sweeps]
        for strategy in strategies:
            self._bind_strategy(strategy, project)

        if initial_pose is None or not initial_pose.body_poses:
            pose = self._initial_pose(project)
        else:
            pose = initial_pose
        base_values = [
            compute_sweep_base_value(project, sweep, pose)
            for sweep in cfg.sweeps
        ]

        axes = []
        for strategy, base in zip(strategies, base_values):
            raw_values = strategy.sweep.resolved_values()
            if strategy.sweep.reference_mode == "relative":
                values = [v + base for v in raw_values]
            else:
                values = raw_values
            axes.append({"id": strategy.sweep.id, "label": strategy.label(), "values": values})

        shape = [len(axis["values"]) for axis in axes]

        pose_runner = PoseRunner(ExudynPoseAdapter(ExpressionService(UnitService())))
        settings = PoseSolveSettings(tolerance=1e-6, max_iterations=80)
        last_pose = pose
        last_targets: list[float] | None = None

        sensor_channels = {
            sensor.id: self._sensor_channel_names(sensor.type.value)
            for sensor in project.model.sensors
        }
        sensors_acc = {sensor.id: [] for sensor in project.model.sensors}
        poses_acc: list[dict] = []
        failed_mask: list[bool] = []
        any_failed = False
        first_failure_reason: str | None = None

        for indices in self._snake_iter(shape):
            if cancel_event is not None and cancel_event.is_set():
                return KinematicResult(
                    analysis_id=analysis.id,
                    analysis_type="kinematic",
                    status="to_be_run",
                    error_message="Cancelled by user",
                )
            targets = [axis["values"][indices[i]] for i, axis in enumerate(axes)]
            cell_pose = last_pose
            cell_success = True
            cell_perturbed = False
            ramp_steps = list(
                self._ramp(
                    targets,
                    last_targets,
                    [strategy.sweep.variable_kind for strategy in strategies],
                )
            )
            for ramp_targets in ramp_steps:
                constraints = []
                for strategy, value in zip(strategies, ramp_targets):
                    constraints.extend(strategy.constraints(value))
                result = pose_runner.solve(project, cell_pose, constraints, settings)
                if (not result.success or result.pose is None) and cell_pose is not pose:
                    # Last-known-good pose is corrupted: retry from the original initial pose.
                    result = pose_runner.solve(project, pose, constraints, settings)
                if not result.success or result.pose is None:
                    cell_success = False
                    if first_failure_reason is None:
                        first_failure_reason = (
                            getattr(result, "error", None)
                            or (getattr(result, "messages", None) or ["pose solve failed"])[-1]
                        )
                    break
                if self._result_was_perturbed(result):
                    cell_perturbed = True
                cell_pose = result.pose
            if cell_success and cell_pose is not None:
                # If the solver needed a perturbed initial guess, the resulting
                # pose may have residual drift that breaks the next solve. Keep
                # the previous clean last_pose so the next cell restarts from
                # known-good geometry.
                if not cell_perturbed:
                    last_pose = cell_pose
                last_targets = targets
                extracted = extract_sensors_from_pose(project, cell_pose)
                for sensor in project.model.sensors:
                    payload = extracted.get(sensor.id)
                    values = (
                        payload["values"]
                        if payload is not None
                        else [math.nan] * len(sensor_channels[sensor.id])
                    )
                    sensors_acc[sensor.id].extend(values)
                poses_acc.append(self._pose_blob(cell_pose))
                failed_mask.append(False)
            else:
                any_failed = True
                for sensor in project.model.sensors:
                    sensors_acc[sensor.id].extend([math.nan] * len(sensor_channels[sensor.id]))
                poses_acc.append({})
                failed_mask.append(True)

        sensors_blob = {
            sensor_id: {"channels": sensor_channels[sensor_id], "values": values}
            for sensor_id, values in sensors_acc.items()
        }
        if any_failed and all(failed_mask):
            status = "failed"
        elif any_failed:
            status = "partial"
        else:
            status = "ok"
        error_message = ""
        if any_failed and first_failure_reason:
            failed_count = sum(1 for failed in failed_mask if failed)
            error_message = (
                f"{failed_count}/{len(failed_mask)} sweep cells failed. "
                f"First failure: {first_failure_reason}"
            )
        result = KinematicResult(
            analysis_id=analysis.id,
            analysis_type="kinematic",
            status=status,
            error_message=error_message,
            sweep_axes=axes,
            shape=shape,
            sensors=sensors_blob,
            poses=poses_acc,
            failed_mask=failed_mask,
        )
        if project_dir is not None and run is not None:
            self._persist_artifact(project_dir, run, result)
        return result

    def _persist_artifact(self, project_dir: Path, run: Analysis, result: KinematicResult) -> Path:
        artifact_dir = project_dir / "artifacts" / f"run_{run.id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / "result.json"
        payload = {
            "type": "kinematic",
            "sweep_axes": result.sweep_axes,
            "shape": result.shape,
            "sensors": result.sensors,
            "poses": result.poses,
            "failed_mask": result.failed_mask,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        run.result_ref = ResultRef(
            run_entry_id=run.id,
            artifact_path=str(path.relative_to(project_dir)),
            checksum=f"sha256:{checksum}",
        )
        return path

    def _initial_pose(self, project) -> Pose:
        return create_reference_pose(project, pose_id="kinematic_reference", name="Kinematic Reference")

    def _bind_strategy(self, strategy, project) -> None:
        if isinstance(strategy, SliderStrokeStrategy):
            ax, ay, rx, ry = slider_axis_for(project, strategy.sweep.target_ids[0])
            strategy.bind_geometry(axis=(ax, ay), reference=(rx, ry))
            return
        if isinstance(strategy, AngleBetweenSegmentsStrategy):
            body_a = body_of_marker(project, strategy.sweep.target_ids[0])
            body_b = body_of_marker(project, strategy.sweep.target_ids[2])
            strategy.bind_bodies(
                body_a_id=body_a,
                body_b_id=body_b,
                local_phi_a=segment_local_angle(project, strategy.sweep.target_ids[0], strategy.sweep.target_ids[1]),
                local_phi_b=segment_local_angle(project, strategy.sweep.target_ids[2], strategy.sweep.target_ids[3]),
            )
            return
        if isinstance(strategy, AngleHorizontalStrategy):
            marker_a, marker_b = strategy.sweep.target_ids[0], strategy.sweep.target_ids[1]
            strategy.bind_bodies(
                body_a_id=body_of_marker(project, marker_a),
                body_b_id="__ground__",
                local_phi_a=segment_local_angle(project, marker_a, marker_b),
                local_phi_b=0.0,
            )
            return
        if isinstance(strategy, AngleVerticalStrategy):
            marker_a, marker_b = strategy.sweep.target_ids[0], strategy.sweep.target_ids[1]
            strategy.bind_bodies(
                body_a_id=body_of_marker(project, marker_a),
                body_b_id="__ground__",
                local_phi_a=segment_local_angle(project, marker_a, marker_b),
                local_phi_b=math.pi / 2.0,
            )

    def _sensor_channel_names(self, kind: str) -> list[str]:
        if kind == "point":
            return ["x", "y", "vx", "vy", "ax", "ay"]
        if kind == "distance":
            return ["d"]
        return ["theta"]

    @staticmethod
    def _result_was_perturbed(result) -> bool:
        warnings = getattr(result, "warnings", None) or []
        return any("perturbed initial guess" in w for w in warnings)

    def _pose_blob(self, pose: Pose) -> dict:
        return {
            body_id: {"x": body_pose.x, "y": body_pose.y, "theta": body_pose.angle}
            for body_id, body_pose in pose.body_poses.items()
        }

    def _snake_iter(self, shape: list[int]) -> Iterable[list[int]]:
        if not shape:
            yield []
            return
        def recurse(axis: int, prefix: list[int], forward: bool) -> Iterable[list[int]]:
            if axis == len(shape) - 1:
                values = range(shape[axis]) if forward else range(shape[axis] - 1, -1, -1)
                for value in values:
                    yield prefix + [value]
                return
            outer_values = range(shape[axis])
            toggle = forward
            for value in outer_values:
                yield from recurse(axis + 1, prefix + [value], toggle)
                toggle = not toggle
        yield from recurse(0, [], True)

    def _ramp(
        self,
        targets: list[float],
        last_targets: list[float] | None,
        variable_kinds: list[str],
    ) -> Iterable[list[float]]:
        if last_targets is None:
            yield targets
            return
        max_steps = [
            5.0 if kind.startswith("angle_") else 10.0
            for kind in variable_kinds
        ]
        substeps = 1
        for target, previous, max_step in zip(targets, last_targets, max_steps):
            substeps = max(substeps, int(math.ceil(abs(target - previous) / max_step)))
        for i in range(1, substeps + 1):
            yield [
                previous + (target - previous) * (i / substeps)
                for target, previous in zip(targets, last_targets)
            ]
