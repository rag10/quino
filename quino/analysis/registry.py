from __future__ import annotations

from quino.analysis.dynamic import DynamicAnalysisRunner
from quino.analysis.equilibrium import EquilibriumAnalysisRunner
from quino.analysis.kinematic import KinematicAnalysisRunner
from quino.analysis.runner import AnalysisRunner
from quino.analysis.static import StaticAnalysisRunner

ANALYSIS_RUNNERS: dict[str, type[AnalysisRunner]] = {
    "dynamic": DynamicAnalysisRunner,
    "static": StaticAnalysisRunner,
    "kinematic": KinematicAnalysisRunner,
    "equilibrium": EquilibriumAnalysisRunner,
}


def get_runner_for_type(analysis_type: str) -> AnalysisRunner:
    cls = ANALYSIS_RUNNERS.get(str(analysis_type))
    if cls is None:
        raise KeyError(f"Unknown analysis type: {analysis_type!r}")
    return cls()
