from __future__ import annotations

from quino.domain.model import Pose, Project
from quino.pose.model import PoseConstraint, PoseSolveResult, PoseSolveSettings


class PoseRunner:
    def __init__(self, adapter) -> None:
        self.adapter = adapter

    def backend_name(self) -> str:
        return self.adapter.name

    def backend_available(self) -> bool:
        return self.adapter.is_available()

    def solve(
        self,
        project: Project,
        initial_pose: Pose | None,
        temporary_constraints: list[PoseConstraint] | None = None,
        settings: PoseSolveSettings | None = None,
    ) -> PoseSolveResult:
        return self.adapter.solve_pose(
            project,
            initial_pose,
            temporary_constraints or [],
            settings or PoseSolveSettings(),
        )
