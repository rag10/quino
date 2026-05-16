from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quino.domain.model import Project
    from quino.pose.geometry import Pose
    from quino.pose.model import PoseConstraint
    from quino.simulation.assembler import AssembledMechanism


def build_drag_initial_pose(
    assembled: "AssembledMechanism",
    current_pose: "Pose",
    marker_id: str,
    target_x: float,
    target_y: float,
    *,
    fixed_angles: "dict[str, float] | None" = None,
) -> "Pose | None":
    """
    Compute an initial-guess pose for the drag target by finding the driver
    body angle via 1D Newton-Raphson and propagating joint positions outward.

    Returns a pose with the driver at the solved angle and connected body
    origins updated from joint positions (angles may be stale for closed loops).
    Returns None if the marker is not found or no driver exists.
    """
    if fixed_angles is None:
        fixed_angles = {}
    result = find_driver_angle_for_drag(
        assembled, current_pose, marker_id, target_x, target_y, fixed_angles=fixed_angles
    )
    if result is None:
        return None
    driver_body_id, driver_angle = result
    return _pose_at_angle(assembled, current_pose, driver_body_id, driver_angle, fixed_angles)


def get_drag_driver(
    assembled: "AssembledMechanism",
    current_pose: "Pose",
    marker_id: str,
    target_x: float,
    target_y: float,
    *,
    fixed_angles: "dict[str, float] | None" = None,
) -> "tuple[str, float, Pose] | None":
    """
    Returns (driver_body_id, driver_angle, initial_guess_pose) for the drag,
    or None if the marker is not found.
    """
    if fixed_angles is None:
        fixed_angles = {}
    result = find_driver_angle_for_drag(
        assembled, current_pose, marker_id, target_x, target_y, fixed_angles=fixed_angles
    )
    if result is None:
        return None
    driver_body_id, driver_angle = result
    guess_pose = _pose_at_angle(assembled, current_pose, driver_body_id, driver_angle, fixed_angles)
    return driver_body_id, driver_angle, guess_pose


def has_ground_revolute(assembled: "AssembledMechanism", body_id: str) -> bool:
    """Return True if body_id is connected to ground via a revolute (pin) joint."""
    from quino.domain.types import JointEndpointKind

    for joint in assembled.joints:
        ea = joint.endpoint_a
        eb = joint.endpoint_b
        if ea.kind == JointEndpointKind.GROUND and eb.body_id == body_id:
            return True
        if eb.kind == JointEndpointKind.GROUND and ea.body_id == body_id:
            return True
    return False


def find_driver_angle_for_drag(
    assembled: "AssembledMechanism",
    current_pose: "Pose",
    marker_id: str,
    target_x: float,
    target_y: float,
    *,
    fixed_angles: "dict[str, float] | None" = None,
    max_iterations: int = 60,
    tolerance: float = 1e-6,
) -> "tuple[str, float] | None":
    """
    Find the driver body id and the angle that places marker_id closest to
    (target_x, target_y) along the kinematic curve.

    Returns (driver_body_id, angle) or None if the marker is not found.
    Uses a 1D Newton-Raphson on the driver body angle (single DOF assumption).
    """
    if fixed_angles is None:
        fixed_angles = {}

    owner_body_id: str | None = None
    for body_id, body in assembled.bodies.items():
        if marker_id in body.markers:
            owner_body_id = body_id
            break
    if owner_body_id is None:
        return None

    driver_body_id = _find_chain_root(assembled, owner_body_id)
    if driver_body_id is None:
        driver_body_id = owner_body_id
    if driver_body_id in fixed_angles and driver_body_id != owner_body_id:
        driver_body_id = owner_body_id

    driver_bp = current_pose.body_poses.get(driver_body_id)
    if driver_bp is None:
        return None
    theta = driver_bp.angle

    h = 1e-5
    for _ in range(max_iterations):
        test_pose = _pose_at_angle(assembled, current_pose, driver_body_id, theta, fixed_angles)
        mx, my = _marker_pos_in_pose(assembled, marker_id, test_pose)

        dx = target_x - mx
        dy = target_y - my
        if math.hypot(dx, dy) < tolerance:
            break

        pose_p = _pose_at_angle(assembled, current_pose, driver_body_id, theta + h, fixed_angles)
        mx_p, my_p = _marker_pos_in_pose(assembled, marker_id, pose_p)

        jx = (mx_p - mx) / h
        jy = (my_p - my) / h

        denom = jx * jx + jy * jy
        if denom < 1e-20:
            break

        delta_theta = (dx * jx + dy * jy) / denom
        max_step = math.pi / 8
        theta += max(-max_step, min(max_step, delta_theta))

    return driver_body_id, theta


def solve_drag_pose(
    project: "Project",
    assembled: "AssembledMechanism",
    current_pose: "Pose",
    marker_id: str,
    target_x: float,
    target_y: float,
    *,
    active_constraints: "list[PoseConstraint] | None" = None,
    max_iterations: int = 60,
    tolerance: float = 1e-6,
) -> "Pose | None":
    """
    Find the pose closest to target_x/target_y for marker_id.

    Uses a pure-Python 1D kinematic solver (single DOF assumption) as a fallback
    when Exudyn is not available. For multi-body closed loops the result may show
    bar stretching; prefer the hybrid Exudyn path when available.

    Returns a Pose with the driver body angle updated and connected bodies
    propagated via joints, or None if no solution found.
    """
    if active_constraints is None:
        active_constraints = []

    fixed_angles: dict[str, float] = {}
    for c in active_constraints:
        if c.kind == "body_angle" and "angle" in c.metadata:
            fixed_angles[c.target_id] = float(c.metadata["angle"])

    result = find_driver_angle_for_drag(
        assembled,
        current_pose,
        marker_id,
        target_x,
        target_y,
        fixed_angles=fixed_angles,
        max_iterations=max_iterations,
        tolerance=tolerance,
    )
    if result is None:
        return None

    driver_body_id, theta = result
    return _pose_at_angle(assembled, current_pose, driver_body_id, theta, fixed_angles)


def _find_chain_root(assembled: "AssembledMechanism", body_id: str) -> "str | None":
    """
    Walk the joint graph to find the ground-connected body in the chain
    leading to body_id. Returns body_id itself if directly ground-connected.
    """
    from quino.domain.types import JointEndpointKind

    ground_connected: set[str] = set()
    body_neighbors: dict[str, set[str]] = {bid: set() for bid in assembled.bodies}

    for joint in assembled.joints:
        ea = joint.endpoint_a
        eb = joint.endpoint_b
        if ea.kind == JointEndpointKind.GROUND:
            if eb.body_id:
                ground_connected.add(eb.body_id)
        elif eb.kind == JointEndpointKind.GROUND:
            if ea.body_id:
                ground_connected.add(ea.body_id)
        else:
            if ea.body_id and eb.body_id:
                body_neighbors[ea.body_id].add(eb.body_id)
                body_neighbors[eb.body_id].add(ea.body_id)

    if body_id in ground_connected:
        return body_id

    visited = {body_id}
    queue = [body_id]
    while queue:
        current = queue.pop(0)
        for neighbor in body_neighbors.get(current, set()):
            if neighbor in ground_connected:
                return neighbor
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    return body_id


def _pose_at_angle(
    assembled: "AssembledMechanism",
    base_pose: "Pose",
    driver_body_id: str,
    angle: float,
    fixed_angles: dict[str, float],
) -> "Pose":
    """
    Return a copy of base_pose with the driver body at `angle` and all
    dependent bodies propagated via kinematic joint constraints.
    """
    import copy
    from quino.domain.model import BodyPose, Pose

    new_pose = Pose(
        id=base_pose.id,
        name=base_pose.name,
        body_poses=copy.deepcopy(base_pose.body_poses),
        metadata=copy.deepcopy(base_pose.metadata),
    )

    old_bp = new_pose.body_poses.get(driver_body_id)
    if old_bp is None:
        return new_pose

    new_pose.body_poses[driver_body_id] = BodyPose(
        body_id=driver_body_id,
        x=old_bp.x,
        y=old_bp.y,
        angle=angle,
    )

    _propagate_joints(assembled, new_pose, driver_body_id, set(), fixed_angles)
    return new_pose


def _propagate_joints(
    assembled: "AssembledMechanism",
    pose: "Pose",
    from_body_id: str,
    visited: set,
    fixed_angles: dict[str, float],
) -> None:
    """
    Given the pose of from_body_id, compute dependent body poses via joints.
    For each connected body, compute its angle from the two world-space joint
    pivot positions (closed-form rigid-body kinematics), so bars never stretch.
    """
    from quino.domain.types import JointEndpointKind
    from quino.domain.model import BodyPose

    visited = visited | {from_body_id}

    # Collect all body-body joints that touch from_body_id and lead to unvisited bodies
    for joint in assembled.joints:
        ea = joint.endpoint_a
        eb = joint.endpoint_b

        if ea.kind != JointEndpointKind.MARKER or eb.kind != JointEndpointKind.MARKER:
            continue
        if ea.body_id == from_body_id and eb.body_id not in visited:
            from_marker_id = ea.marker_id
            to_body_id = eb.body_id
            to_marker_id = eb.marker_id
        elif eb.body_id == from_body_id and ea.body_id not in visited:
            from_marker_id = eb.marker_id
            to_body_id = ea.body_id
            to_marker_id = ea.marker_id
        else:
            continue

        if to_body_id is None or to_body_id not in assembled.bodies:
            continue

        from_bp = pose.body_poses.get(from_body_id)
        if from_bp is None:
            continue
        from_body = assembled.bodies[from_body_id]
        from_m = from_body.markers.get(from_marker_id)
        if from_m is None:
            continue

        # World position of the joint pivot on the from-body side
        cos_a = math.cos(from_bp.angle)
        sin_a = math.sin(from_bp.angle)
        joint_world_x = from_bp.x + cos_a * from_m.local_x - sin_a * from_m.local_y
        joint_world_y = from_bp.y + sin_a * from_m.local_x + cos_a * from_m.local_y

        to_body = assembled.bodies[to_body_id]
        to_m = to_body.markers.get(to_marker_id)
        if to_m is None:
            continue

        # Determine the to-body angle
        if to_body_id in fixed_angles:
            tb_angle = fixed_angles[to_body_id]
        else:
            # Try to find a second joint pivot for to_body_id (already resolved)
            second_pivot = _find_second_pivot(assembled, pose, to_body_id, to_marker_id, visited | {to_body_id})
            if second_pivot is not None:
                second_world_x, second_world_y, second_local_x, second_local_y = second_pivot
                tb_angle = _angle_from_two_pivots(
                    joint_world_x, joint_world_y, to_m.local_x, to_m.local_y,
                    second_world_x, second_world_y, second_local_x, second_local_y,
                )
            else:
                # Single-pivot body: keep existing angle
                existing_bp = pose.body_poses.get(to_body_id)
                tb_angle = existing_bp.angle if existing_bp is not None else 0.0

        # Compute to_body origin from the joint world position and to_body angle
        cos_tb = math.cos(tb_angle)
        sin_tb = math.sin(tb_angle)
        new_origin_x = joint_world_x - (cos_tb * to_m.local_x - sin_tb * to_m.local_y)
        new_origin_y = joint_world_y - (sin_tb * to_m.local_x + cos_tb * to_m.local_y)

        pose.body_poses[to_body_id] = BodyPose(
            body_id=to_body_id,
            x=new_origin_x,
            y=new_origin_y,
            angle=tb_angle,
        )
        _propagate_joints(assembled, pose, to_body_id, visited, fixed_angles)


def _find_second_pivot(
    assembled: "AssembledMechanism",
    pose: "Pose",
    body_id: str,
    exclude_marker_id: str,
    visited: set[str],
) -> "tuple[float, float, float, float] | None":
    """
    Find another body-body joint on body_id (other than the one using exclude_marker_id)
    whose other-end body is already resolved (in visited or has a known pose).
    Returns (world_x, world_y, local_x, local_y) of the other pivot, or None.
    """
    from quino.domain.types import JointEndpointKind

    for joint in assembled.joints:
        ea = joint.endpoint_a
        eb = joint.endpoint_b

        if ea.kind != JointEndpointKind.MARKER or eb.kind != JointEndpointKind.MARKER:
            continue

        # Find a joint involving body_id on one side, a visited body on the other
        if ea.body_id == body_id and eb.body_id in visited and ea.marker_id != exclude_marker_id:
            my_marker_id = ea.marker_id
            other_body_id = eb.body_id
            other_marker_id = eb.marker_id
        elif eb.body_id == body_id and ea.body_id in visited and eb.marker_id != exclude_marker_id:
            my_marker_id = eb.marker_id
            other_body_id = ea.body_id
            other_marker_id = ea.marker_id
        else:
            continue

        other_bp = pose.body_poses.get(other_body_id)
        if other_bp is None:
            continue
        other_body = assembled.bodies.get(other_body_id)
        if other_body is None:
            continue
        other_m = other_body.markers.get(other_marker_id)
        if other_m is None:
            continue

        cos_a = math.cos(other_bp.angle)
        sin_a = math.sin(other_bp.angle)
        world_x = other_bp.x + cos_a * other_m.local_x - sin_a * other_m.local_y
        world_y = other_bp.y + sin_a * other_m.local_x + cos_a * other_m.local_y

        my_body = assembled.bodies.get(body_id)
        if my_body is None:
            continue
        my_m = my_body.markers.get(my_marker_id)
        if my_m is None:
            continue

        return world_x, world_y, my_m.local_x, my_m.local_y

    return None


def _angle_from_two_pivots(
    world_ax: float, world_ay: float, local_ax: float, local_ay: float,
    world_bx: float, world_by: float, local_bx: float, local_by: float,
) -> float:
    """
    Compute body angle given world positions of two markers and their local coordinates.
    world_B - world_A = R(theta) * (local_B - local_A)
    theta = atan2(world_delta) - atan2(local_delta)
    """
    world_dx = world_bx - world_ax
    world_dy = world_by - world_ay
    local_dx = local_bx - local_ax
    local_dy = local_by - local_ay
    if abs(local_dx) < 1e-12 and abs(local_dy) < 1e-12:
        return 0.0
    return math.atan2(world_dy, world_dx) - math.atan2(local_dy, local_dx)


def _marker_pos_in_pose(
    assembled: "AssembledMechanism",
    marker_id: str,
    pose: "Pose",
) -> tuple[float, float]:
    for body_id, body in assembled.bodies.items():
        m = body.markers.get(marker_id)
        if m is None:
            continue
        bp = pose.body_poses.get(body_id)
        if bp is None:
            return m.global_x, m.global_y
        cos_a = math.cos(bp.angle)
        sin_a = math.sin(bp.angle)
        return (
            bp.x + cos_a * m.local_x - sin_a * m.local_y,
            bp.y + sin_a * m.local_x + cos_a * m.local_y,
        )
    raise ValueError(f"Unknown marker: {marker_id}")
