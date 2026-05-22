from __future__ import annotations

import copy
import math
import threading

from quino.domain.model import BodyPose
from quino.pose.geometry import create_reference_pose, state_overlay_to_pose
from quino.simulation.runner import SimulationRunner
from quino.solver_adapters.exudyn_adapter import ExudynAdapter
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService


def find_stable_equilibria(project, config, *, initial_pose=None, cancel_event: threading.Event | None = None) -> list[dict]:
    runner = SimulationRunner(ExudynAdapter(ExpressionService(UnitService())))
    equilibria: list[dict] = []
    base_pose = initial_pose or create_reference_pose(project, pose_id="eq_base", name="Equilibrium Base")
    for perturbation in config.initial_perturbations:
        if cancel_event is not None and cancel_event.is_set():
            break
        trial = copy.deepcopy(project)
        _apply_artificial_damping(trial)
        perturbed_pose = _perturb_pose(base_pose, perturbation)
        trial.poses = [perturbed_pose]
        trial.simulation_initial_pose_id = perturbed_pose.id
        result = runner.run(trial, duration=5.0, steps=300, cancel_event=cancel_event)
        if not result.frames:
            continue
        frame = result.frames[-1]
        pose = state_overlay_to_pose(trial, frame, pose_id=f"eq_{len(equilibria)}", name="Equilibrium")
        equilibria.append(
            {
                "pose": {
                    body_id: {"x": body_pose.x, "y": body_pose.y, "theta": body_pose.angle}
                    for body_id, body_pose in pose.body_poses.items()
                },
                "perturbation": perturbation,
            }
        )
    return _deduplicate(equilibria, tolerance=config.pose_match_tolerance)


def _apply_artificial_damping(project) -> None:
    for joint in project.model.joints:
        joint.metadata.values["friction_viscous"] = max(float(joint.metadata.values.get("friction_viscous", 0.0)), 5.0)
    for spring in project.model.springs:
        spring.metadata.values["damping"] = max(float(spring.metadata.values.get("damping", 0.0)), 0.5)


def _perturb_pose(pose, perturbation: float):
    perturbed = copy.deepcopy(pose)
    for body_pose in perturbed.body_poses.values():
        body_pose.angle += perturbation
    return perturbed


def _deduplicate(equilibria: list[dict], tolerance: float) -> list[dict]:
    deduped: list[dict] = []
    for equilibrium in equilibria:
        if any(_pose_close(equilibrium["pose"], other["pose"], tolerance) for other in deduped):
            continue
        deduped.append(equilibrium)
    return deduped


def _pose_close(pose_a: dict, pose_b: dict, tolerance: float) -> bool:
    if pose_a.keys() != pose_b.keys():
        return False
    for body_id in pose_a:
        a = pose_a[body_id]
        b = pose_b[body_id]
        if (
            abs(a["x"] - b["x"]) > tolerance
            or abs(a["y"] - b["y"]) > tolerance
            or abs(a["theta"] - b["theta"]) > tolerance
        ):
            return False
    return True
