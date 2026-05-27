from __future__ import annotations

import copy

from quino.application._context import ServiceContext
from quino.domain.model import Driver
from quino.domain.workspace import Pose
from quino.pose.geometry import create_reference_pose as build_reference_pose
from quino.pose.model import PoseConstraint, PoseSolveResult, PoseSolveSettings
from quino.pose.runner import PoseRunner


class PoseCommands:
    """Command-service for pose operations.

    Owns the current-pose selection state (`_current_pose_id`). Project-scoped
    state such as `simulation_initial_pose_id` and per-pose `initial_velocities`
    live on the domain `Project`/`Pose` objects, not here.
    """

    def __init__(self, ctx: ServiceContext, runner: PoseRunner) -> None:
        self._ctx = ctx
        self._runner = runner
        self._current_pose_id: str | None = None

    @property
    def _project(self):
        project = self._ctx.project_provider()
        if project is None:
            raise ValueError("No active project")
        return project

    # --- internal state hooks (called from ApplicationService) ---------------

    def clear_current(self) -> None:
        """Drop the current pose selection (used on new/load/undo/redo)."""
        self._current_pose_id = None

    def cleanup_driver_velocities(self, removed_driver_ids: set[str]) -> None:
        project = self._ctx.project_provider()
        if not removed_driver_ids or project is None:
            return
        for pose in project.poses:
            for driver_id in list(pose.initial_velocities.keys()):
                if driver_id in removed_driver_ids:
                    pose.initial_velocities.pop(driver_id, None)

    # --- helpers ------------------------------------------------------------

    def _next_pose_name(self) -> str:
        project = self._project
        existing = {pose.name for pose in project.poses}
        index = len(project.poses) + 1
        while f"Pose {index}" in existing:
            index += 1
        return f"Pose {index}"

    def _find_driver(self, driver_id: str) -> Driver:
        project = self._project
        for driver in project.model.drivers:
            if driver.id == driver_id:
                return driver
        raise ValueError(f"Unknown driver id: {driver_id}")

    def complete_pose(self, pose: Pose) -> Pose:
        project = self._project
        complete = build_reference_pose(project, pose_id=pose.id, name=pose.name)
        complete.metadata = copy.deepcopy(pose.metadata)
        for body_id, body_pose in pose.body_poses.items():
            complete.body_poses[body_id] = copy.deepcopy(body_pose)
        return complete

    # --- public API ---------------------------------------------------------

    def create_reference_pose(self, name: str = "Reference") -> Pose:
        """Build a reference Pose object without registering it in the project."""
        project = self._project
        return build_reference_pose(project, pose_id=self._ctx.ids.new("pose"), name=name)

    def list_poses(self) -> list[Pose]:
        project = self._project
        return [p for p in project.poses if not p.is_default]

    def get_pose(self, pose_id: str) -> Pose | None:
        project = self._project
        return next((pose for pose in project.poses if pose.id == pose_id), None)

    def get_current_pose_id(self) -> str | None:
        return self._current_pose_id

    def set_current_pose_id(self, pose_id: str | None) -> None:
        if pose_id is None:
            self._current_pose_id = None
            return
        if self.get_pose(pose_id) is None:
            raise ValueError(f"Unknown pose id: {pose_id}")
        self._current_pose_id = pose_id

    def get_current_pose(self) -> Pose | None:
        if self._current_pose_id is None:
            return None
        return self.get_pose(self._current_pose_id)

    def set_current_pose(self, pose: Pose | None) -> None:
        """Replace the body_poses of the current pose with the given values."""
        if pose is None:
            return
        project = self._project
        completed = self.complete_pose(pose)
        target = self.get_current_pose()
        if target is None:
            project.poses.append(completed)
            self._current_pose_id = completed.id
            return
        target.body_poses = copy.deepcopy(completed.body_poses)
        self._mark_runs_stale_for_current_pose("pose edited")

    def create_pose(self, name: str | None = None, *, set_current: bool = True) -> Pose:
        project = self._project
        pose = self.create_reference_pose(name=name or self._next_pose_name())
        self._ctx.snapshot()
        project.poses.append(pose)
        if set_current:
            self._current_pose_id = pose.id
        return pose

    def duplicate_pose(self, pose_id: str, *, set_current: bool = True) -> Pose:
        project = self._project
        source = self.get_pose(pose_id)
        if source is None:
            raise ValueError(f"Unknown pose id: {pose_id}")
        self._ctx.snapshot()
        clone = Pose(
            id=self._ctx.ids.new("pose"),
            name=f"{source.name} copy",
            body_poses={bid: copy.deepcopy(bp) for bid, bp in source.body_poses.items()},
            initial_velocities=dict(source.initial_velocities),
            metadata=copy.deepcopy(source.metadata),
        )
        project.poses.append(clone)
        if set_current:
            self._current_pose_id = clone.id
        return clone

    def rename_pose(self, pose_id: str, name: str) -> None:
        pose = self.get_pose(pose_id)
        if pose is None:
            raise ValueError(f"Unknown pose id: {pose_id}")
        name = name.strip()
        if not name:
            raise ValueError("Pose name cannot be empty")
        if pose.name == name:
            return
        self._ctx.snapshot()
        pose.name = name

    def delete_pose(self, pose_id: str) -> None:
        project = self._project
        if self.get_pose(pose_id) is None:
            return
        self._ctx.snapshot()
        project.poses = [pose for pose in project.poses if pose.id != pose_id]
        if self._current_pose_id == pose_id:
            # Fall back to the first user pose (skip the reference/default).
            remaining_user = [p for p in project.poses if not getattr(p, "is_default", False)]
            self._current_pose_id = remaining_user[0].id if remaining_user else None

    def reset_current_pose_to_reference(self) -> Pose:
        """Reset the current pose body positions back to the reference geometry."""
        project = self._project
        reference = self.create_reference_pose()
        current = self.get_current_pose()
        if current is None:
            self._ctx.snapshot()
            project.poses.append(reference)
            self._current_pose_id = reference.id
            return reference
        current.body_poses = reference.body_poses
        self._mark_runs_stale_for_current_pose("pose reset to reference")
        return current

    def get_simulation_initial_pose_id(self) -> str | None:
        project = self._project
        return project.simulation_initial_pose_id

    def set_simulation_initial_pose(self, pose_id: str | None) -> None:
        project = self._project
        if pose_id is not None and self.get_pose(pose_id) is None:
            raise ValueError(f"Unknown pose id: {pose_id}")
        if project.simulation_initial_pose_id == pose_id:
            return
        self._ctx.snapshot()
        project.simulation_initial_pose_id = pose_id

    def get_simulation_initial_pose(self) -> Pose | None:
        project = self._project
        if project.simulation_initial_pose_id is None:
            return None
        return self.get_pose(project.simulation_initial_pose_id)

    def set_driver_initial_velocity(self, driver_id: str, value: float | None) -> None:
        """Set/clear the initial velocity for a driver on the *current* pose."""
        pose = self.get_current_pose()
        if pose is None:
            raise ValueError("No current pose selected")
        self._find_driver(driver_id)
        self._ctx.snapshot()
        if value is None:
            pose.initial_velocities.pop(driver_id, None)
        else:
            pose.initial_velocities[driver_id] = float(value)
        self._mark_runs_stale_for_current_pose("driver initial velocity changed")

    def get_driver_initial_velocity(self, driver_id: str) -> float | None:
        pose = self.get_current_pose()
        if pose is None:
            return None
        return pose.initial_velocities.get(driver_id)

    def set_initial_pose_from_current(self) -> None:
        """Mark the current pose as the simulation initial pose."""
        if self._current_pose_id is None:
            raise ValueError("No current pose is available")
        self.set_simulation_initial_pose(self._current_pose_id)

    def clear_initial_pose(self) -> None:
        self.set_simulation_initial_pose(None)

    def solve_current_pose(
        self,
        temporary_constraints: list[PoseConstraint] | None = None,
        settings: PoseSolveSettings | None = None,
    ) -> PoseSolveResult:
        project = self._project
        working_pose = self.get_current_pose()
        if working_pose is None:
            reference = self.create_reference_pose()
            project.poses.append(reference)
            self._current_pose_id = reference.id
            working_pose = reference
        result = self._runner.solve(
            project,
            self.complete_pose(working_pose),
            temporary_constraints=temporary_constraints,
            settings=settings,
        )
        if result.success and result.pose is not None:
            current = self.get_current_pose()
            if current is not None:
                solved = self.complete_pose(result.pose)
                current.body_poses = solved.body_poses
                self._mark_runs_stale_for_current_pose("pose solved")
        return result

    def mark_runs_stale_for_current_pose(self, reason: str) -> int:
        """Public hook so GUI-side pose mutations (prescribes, etc.) can
        invalidate runs that depended on the now-edited pose."""
        return self._mark_runs_stale_for_current_pose(reason)

    def _mark_runs_stale_for_current_pose(self, reason: str) -> int:
        ws = self._ctx.workspace_provider()
        if ws is None:
            return 0
        pose_id = self._current_pose_id
        if pose_id is None:
            return 0
        from quino.services.run_invalidation import mark_runs_stale_for_pose
        return mark_runs_stale_for_pose(ws, pose_id, reason=reason)
