from __future__ import annotations

from dataclasses import dataclass

from quino.domain.model import Project
from quino.domain.types import JointType


@dataclass
class MechanismDofResult:
    total_dof: int
    body_count: int
    revolute_joint_count: int
    rigid_joint_count: int
    driver_count: int
    pose_constraint_count: int


def compute_mechanism_dof(
    project: Project | None,
    pose_constraint_count: int = 0,
) -> MechanismDofResult:
    """Compute a planar Gruebler-like DOF count for the mechanism.

    This is an approximate count useful for UI feedback:
        DOF = 3 * bodies - 2 * revolute_joints - 3 * rigid_joints - pose_constraints

    Drivers are *not* subtracted because in pose mode they are deliberately
    not applied (the user freely positions the mechanism).
    """
    if project is None:
        return MechanismDofResult(0, 0, 0, 0, 0, 0)

    model = project.model
    body_count = len(model.bodies)
    revolute_joint_count = sum(1 for j in model.joints if j.type is JointType.REVOLUTE)
    rigid_joint_count = sum(1 for j in model.joints if j.type is JointType.RIGID)
    driver_count = len(model.drivers)

    total_dof = (
        3 * body_count
        - 2 * revolute_joint_count
        - 3 * rigid_joint_count
        - pose_constraint_count
    )

    return MechanismDofResult(
        total_dof=max(total_dof, 0),
        body_count=body_count,
        revolute_joint_count=revolute_joint_count,
        rigid_joint_count=rigid_joint_count,
        driver_count=driver_count,
        pose_constraint_count=pose_constraint_count,
    )
