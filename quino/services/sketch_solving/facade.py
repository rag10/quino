# quino/services/sketch_solving/facade.py
from __future__ import annotations

from quino.domain.model import Project
from quino.services.expressions import ExpressionService
from quino.services.sketch_solving.base import SketchSolveResult
from quino.services.sketch_solving.solvespace_backend import SolvespaceBackend
from quino.services.units import UnitService


class SketchSolver:
    """Facade for the sketch constraint solver.

    Solvespace is the only supported backend. The class is kept as a thin
    wrapper to preserve the existing public surface used by callers.
    """

    def __init__(
        self,
        expression_service: ExpressionService,
        unit_service: UnitService,
    ) -> None:
        self._backend = SolvespaceBackend(expression_service, unit_service)

    @property
    def backend_name(self) -> str:
        return self._backend.name

    def solve(self, project: Project, **kwargs) -> SketchSolveResult:
        return self._backend.solve(project, **kwargs)

    def analyze_dof(self, project: Project):
        return self._backend.analyze_dof(project)
