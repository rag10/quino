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

    Pose state is local to the active case.  The workspace selected_pose_id is
    the source of truth; _current_pose_id is kept only as a legacy mirror for
    callers that still ask this service directly.
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

    @property
    def _workspace(self):
        return self._ctx.workspace_provider()

    def _active_case(self):
        case = self._ctx.current_case_provider()
        if case is None:
            raise ValueError("No active case")
        return case

    # --- internal state hooks (called from ApplicationService) ---------------

    def clear_current(self) -> None:
        """Drop the current pose selection (used on new/load/undo/redo)."""
        self._current_pose_id = None
        ws = self._workspace
        if ws is not None:
            ws.selected_pose_id = None

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
        case = self._active_case()
        existing = {pose.name for pose in case.poses}
        index = len(case.poses) + 1
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

    def resolve_all_user_poses(self, reason: str = "model changed") -> list[str]:
        """Re-solve every non-default pose against the current model.

        Called after a topology/geometry change (e.g. a marker moved, directly
        or by cascade) that may have invalidated user poses. Instead of dropping
        them, each pose is re-solved using its current ``body_poses`` as the
        initial guess, so the solver converges to the nearest valid
        configuration under the new kinematics and bar/body lengths, respecting
        the pose's prescribes.

        A pose that cannot be solved is PRESERVED (never deleted) and flagged
        ``solve_failed=True`` with a warning recorded in
        ``pose.metadata.values["solve_warning"]``. The default/reference pose is
        left untouched (it always reflects the model).

        Returns the list of pose ids that failed to re-solve.
        """
        case = self._ctx.current_case_provider()
        if case is None:
            return []
        project = self._project
        failed: list[str] = []
        for pose in case.poses:
            if getattr(pose, "is_default", False):
                continue
            if not pose.body_poses:
                # Nothing solved yet; leave it to be solved on first entry.
                continue
            try:
                result = self._runner.solve(project, self.complete_pose(pose))
            except Exception as exc:  # noqa: BLE001 - solver may raise; keep pose
                self._flag_pose_failed(pose, f"{reason}: {exc}")
                failed.append(pose.id)
                continue
            if result.success and result.pose is not None:
                solved = self.complete_pose(result.pose)
                pose.body_poses = solved.body_poses
                pose.solve_failed = False
                pose.requires_recompute = False
                if pose.metadata is not None:
                    pose.metadata.values.pop("solve_warning", None)
            else:
                msg = result.error or "no valid configuration found"
                self._flag_pose_failed(pose, f"{reason}: {msg}")
                failed.append(pose.id)
        return failed

    @staticmethod
    def _flag_pose_failed(pose: Pose, message: str) -> None:
        pose.solve_failed = True
        pose.requires_recompute = True
        if pose.metadata is not None:
            pose.metadata.values["solve_warning"] = message

    # --- public API ---------------------------------------------------------

    def create_reference_pose(self, name: str = "Reference") -> Pose:
        """Build a reference Pose object without registering it in the project."""
        project = self._project
        return build_reference_pose(project, pose_id=self._ctx.ids.new("pose"), name=name)

    def list_poses(self) -> list[Pose]:
        case = self._active_case()
        return [p for p in case.poses if not p.is_default]

    def get_pose(self, pose_id: str) -> Pose | None:
        case = self._active_case()
        return next((pose for pose in case.poses if pose.id == pose_id), None)

    def get_current_pose_id(self) -> str | None:
        ws = self._workspace
        case = self._ctx.current_case_provider()
        pose_id = ws.selected_pose_id if ws is not None else self._current_pose_id
        if pose_id is None or case is None:
            return None
        pose = next((p for p in case.poses if p.id == pose_id), None)
        if pose is None or getattr(pose, "is_default", False):
            return None
        self._current_pose_id = pose_id
        return pose_id

    def set_current_pose_id(self, pose_id: str | None) -> None:
        ws = self._workspace
        if pose_id is None:
            self._current_pose_id = None
            if ws is not None:
                ws.selected_pose_id = None
            return
        pose = self.get_pose(pose_id)
        if pose is None:
            raise ValueError(f"Unknown pose id: {pose_id}")
        if getattr(pose, "is_default", False):
            self._current_pose_id = None
        else:
            self._current_pose_id = pose_id
        if ws is not None:
            ws.selected_pose_id = pose_id

    def get_current_pose(self) -> Pose | None:
        pose_id = self.get_current_pose_id()
        if pose_id is None:
            return None
        return self.get_pose(pose_id)

    def set_current_pose(self, pose: Pose | None) -> None:
        """Replace the body_poses of the current pose with the given values."""
        if pose is None:
            return
        case = self._active_case()
        completed = self.complete_pose(pose)
        target = self.get_current_pose()
        if target is None:
            case.poses.append(completed)
            self.set_current_pose_id(completed.id)
            return
        target.body_poses = copy.deepcopy(completed.body_poses)
        self._mark_runs_stale_for_current_pose("pose edited")

    def create_pose(self, name: str | None = None, *, set_current: bool = True) -> Pose:
        case = self._active_case()
        pose = self.create_reference_pose(name=name or self._next_pose_name())
        self._ctx.snapshot()
        case.poses.append(pose)
        if set_current:
            self.set_current_pose_id(pose.id)
        return pose

    def duplicate_pose(self, pose_id: str, *, set_current: bool = True) -> Pose:
        case = self._active_case()
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
        case.poses.append(clone)
        if set_current:
            self.set_current_pose_id(clone.id)
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
        case = self._active_case()
        if self.get_pose(pose_id) is None:
            return
        self._ctx.snapshot()
        case.poses = [pose for pose in case.poses if pose.id != pose_id]
        ws = self._workspace
        if self._current_pose_id == pose_id or (ws is not None and ws.selected_pose_id == pose_id):
            # Fall back to the first user pose (skip the reference/default).
            remaining_user = [p for p in case.poses if not getattr(p, "is_default", False)]
            next_id = remaining_user[0].id if remaining_user else None
            self._current_pose_id = next_id
            if ws is not None:
                ws.selected_pose_id = next_id

    def reset_current_pose_to_reference(self) -> Pose:
        """Reset the current pose body positions back to the reference geometry."""
        case = self._active_case()
        reference = self.create_reference_pose()
        current = self.get_current_pose()
        if current is None:
            self._ctx.snapshot()
            case.poses.append(reference)
            self.set_current_pose_id(reference.id)
            return reference
        current.body_poses = reference.body_poses
        self._mark_runs_stale_for_current_pose("pose reset to reference")
        return current

    def get_simulation_initial_pose_id(self) -> str | None:
        project = self._project
        return project.simulation_initial_pose_id

    def set_simulation_initial_pose(self, pose_id: str | None) -> None:
        if pose_id is not None and self.get_pose(pose_id) is None:
            raise ValueError(f"Unknown pose id: {pose_id}")
        if self.get_simulation_initial_pose_id() == pose_id:
            return
        self._ctx.snapshot()
        self._project.simulation_initial_pose_id = pose_id

    def get_simulation_initial_pose(self) -> Pose | None:
        pose_id = self.get_simulation_initial_pose_id()
        if pose_id is None:
            return None
        return self.get_pose(pose_id)

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
        pose_id = self.get_current_pose_id()
        if pose_id is None:
            raise ValueError("No current pose is available")
        self.set_simulation_initial_pose(pose_id)

    def clear_initial_pose(self) -> None:
        self.set_simulation_initial_pose(None)

    def solve_current_pose(
        self,
        temporary_constraints: list[PoseConstraint] | None = None,
        settings: PoseSolveSettings | None = None,
    ) -> PoseSolveResult:
        project = self._project
        case = self._active_case()
        working_pose = self.get_current_pose()
        if working_pose is None:
            reference = self.create_reference_pose()
            case.poses.append(reference)
            self.set_current_pose_id(reference.id)
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
        pose_id = self.get_current_pose_id()
        if pose_id is None:
            return 0
        from quino.services.run_invalidation import mark_runs_stale_for_pose
        return mark_runs_stale_for_pose(ws, pose_id, reason=reason)
