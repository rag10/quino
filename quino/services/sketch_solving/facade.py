# quino/services/sketch_solving/facade.py
from __future__ import annotations

from quino.domain.model import Project
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService
from quino.services.sketch_solving.base import SketchSolveResult, SketchSolverBackend


class SketchSolver:
    def __init__(
        self,
        expression_service: ExpressionService,
        unit_service: UnitService,
        *,
        backend: str = "solvespace",
    ) -> None:
        self._backend: SketchSolverBackend = _make_backend(
            backend, expression_service, unit_service
        )

    @property
    def backend_name(self) -> str:
        return self._backend.name

    def solve(self, project: Project, **kwargs) -> SketchSolveResult:
        return self._backend.solve(project, **kwargs)


def _make_backend(
    name: str,
    expr: ExpressionService,
    units: UnitService,
) -> SketchSolverBackend:
    if name == "solvespace":
        from quino.services.sketch_solving.solvespace_backend import SolvespaceBackend
        return SolvespaceBackend(expr, units)
    if name == "legacy":
        from quino.services.sketch_solving.legacy_backend import LegacyIterativeBackend
        return LegacyIterativeBackend(expr, units)
    raise ValueError(f"Unknown sketch solver backend: {name!r}")
