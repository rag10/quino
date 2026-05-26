from __future__ import annotations

from dataclasses import dataclass, field

from quino.domain.workspace import Pose


@dataclass(slots=True)
class PoseConstraint:
    id: str
    kind: str
    target_id: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class PoseSolveSettings:
    tolerance: float = 1e-8
    max_iterations: int = 50
    verbose: bool = False


@dataclass(slots=True)
class PoseSolveResult:
    success: bool
    pose: Pose | None = None
    warnings: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    error: str | None = None
    backend: str | None = None
