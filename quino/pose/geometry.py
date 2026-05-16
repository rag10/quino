from __future__ import annotations

import math

from quino.domain.model import BodyPose, Pose, Project
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService
from quino.simulation.assembler import MechanismAssembler

_UNIT_SERVICE = UnitService()
_EXPRESSION_SERVICE = ExpressionService(_UNIT_SERVICE)
_ASSEMBLER = MechanismAssembler(_EXPRESSION_SERVICE)


def assembled_reference_mechanism(project: Project):
    return _ASSEMBLER.assemble(project)


def create_reference_pose(
    project: Project,
    *,
    pose_id: str,
    name: str = "Reference",
) -> Pose:
    assembled = assembled_reference_mechanism(project)
    return Pose(
        id=pose_id,
        name=name,
        body_poses={
            body_id: BodyPose(
                body_id=body_id,
                x=body.origin_x,
                y=body.origin_y,
                angle=body.angle,
            )
            for body_id, body in assembled.bodies.items()
        },
    )


def pose_to_state_overlay(pose: Pose | None) -> dict[str, float] | None:
    if pose is None:
        return None
    overlay: dict[str, float] = {}
    for body_id, body_pose in pose.body_poses.items():
        overlay[f"{body_id}.x"] = body_pose.x
        overlay[f"{body_id}.y"] = body_pose.y
        overlay[f"{body_id}.angle"] = body_pose.angle
    return overlay


def state_overlay_to_pose(
    project: Project,
    state: dict[str, float],
    *,
    pose_id: str,
    name: str = "Pose",
) -> Pose:
    assembled = assembled_reference_mechanism(project)
    body_poses: dict[str, BodyPose] = {}
    for body_id, body in assembled.bodies.items():
        body_poses[body_id] = BodyPose(
            body_id=body_id,
            x=state.get(f"{body_id}.x", body.origin_x),
            y=state.get(f"{body_id}.y", body.origin_y),
            angle=state.get(f"{body_id}.angle", body.angle),
        )
    return Pose(id=pose_id, name=name, body_poses=body_poses)


def body_pose_for_reference(project: Project, body_id: str) -> BodyPose:
    assembled = assembled_reference_mechanism(project)
    body = assembled.bodies[body_id]
    return BodyPose(body_id=body_id, x=body.origin_x, y=body.origin_y, angle=body.angle)


def body_pose_for_project(project: Project, body_id: str, pose: Pose | None = None) -> BodyPose:
    if pose is not None and body_id in pose.body_poses:
        return pose.body_poses[body_id]
    return body_pose_for_reference(project, body_id)


def marker_world_position(
    project: Project,
    marker_id: str,
    pose: Pose | None = None,
) -> tuple[float, float]:
    assembled = assembled_reference_mechanism(project)
    for body_id, body in assembled.bodies.items():
        marker = body.markers.get(marker_id)
        if marker is None:
            continue
        if pose is None or body_id not in pose.body_poses:
            return marker.global_x, marker.global_y
        body_pose = pose.body_poses[body_id]
        cos_a = math.cos(body_pose.angle)
        sin_a = math.sin(body_pose.angle)
        return (
            body_pose.x + cos_a * marker.local_x - sin_a * marker.local_y,
            body_pose.y + sin_a * marker.local_x + cos_a * marker.local_y,
        )
    raise ValueError(f"Unknown marker: {marker_id}")
