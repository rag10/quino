from __future__ import annotations

import uuid

from quino.domain.workspace import Workspace, WorkspacePose


def resolve_default_pose(
    workspace: Workspace,
    *,
    case_id: str | None = None,
    baseline_id: str | None = None,
    app_service,
) -> WorkspacePose:
    """Find or create the default WorkspacePose for the given scope.

    Sets parent_pose_id from the parent scope's default pose, attempts
    a best-effort IK solve, marks solve_failed on exception.
    """
    pose = _find_default_pose(workspace, case_id=case_id, baseline_id=baseline_id)
    if pose is None:
        pose = _create_default_pose(workspace, case_id=case_id, baseline_id=baseline_id)

    pose.parent_pose_id = _resolve_parent_default_pose_id(workspace, case_id=case_id)

    try:
        solved_state = _solve_with_constraints(workspace, pose, app_service)
        pose.metadata["solved_state"] = solved_state
        pose.solve_failed = False
        pose.metadata.pop("solve_error", None)
    except Exception as exc:
        pose.solve_failed = True
        pose.metadata["solve_error"] = str(exc)

    pose.requires_recompute = False
    return pose


def _find_default_pose(
    workspace: Workspace,
    *,
    case_id: str | None,
    baseline_id: str | None = None,
) -> WorkspacePose | None:
    for p in workspace.poses:
        if p.is_default and p.case_id == case_id and p.baseline_id == baseline_id:
            return p
    return None


def _create_default_pose(
    workspace: Workspace,
    *,
    case_id: str | None,
    baseline_id: str | None = None,
) -> WorkspacePose:
    pose = WorkspacePose(
        id=f"pose-{uuid.uuid4().hex[:8]}",
        name="Default",
        is_default=True,
        case_id=case_id,
        baseline_id=baseline_id,
    )
    workspace.poses.append(pose)
    return pose


def _resolve_parent_default_pose_id(
    workspace: Workspace,
    *,
    case_id: str | None,
) -> str | None:
    if case_id is None:
        return None
    case = next((c for c in workspace.cases if c.id == case_id), None)
    if case is None:
        return None
    if case.parent_case_id is not None:
        parent = next(
            (p for p in workspace.poses
             if p.is_default and p.case_id == case.parent_case_id),
            None,
        )
        return parent.id if parent else None
    # No parent case — look for the baseline's default pose
    parent = next(
        (p for p in workspace.poses
         if p.is_default and p.baseline_id == case.baseline_id and p.case_id is None),
        None,
    )
    return parent.id if parent else None


def _solve_with_constraints(
    workspace: Workspace,
    pose: WorkspacePose,
    app_service,
) -> dict:
    """Best-effort IK solve. Returns marker→position state dict or empty."""
    if app_service is None:
        return {}

    from quino.services.workspace_composition import compose_project

    case = (
        next((c for c in workspace.cases if c.id == pose.case_id), None)
        if pose.case_id
        else None
    )
    project = app_service.project
    composed = compose_project(project, case=case)

    if not composed.model.bodies:
        return {}

    try:
        from quino.pose.geometry import assembled_reference_mechanism

        ref = assembled_reference_mechanism(composed)
        # assembled_reference_mechanism returns an assembled mechanism with .bodies
        # (not .marker_positions). Return body positions as best-effort state.
        return {
            body_id: [body.origin_x, body.origin_y, body.angle]
            for body_id, body in ref.bodies.items()
        }
    except Exception:
        return {}
