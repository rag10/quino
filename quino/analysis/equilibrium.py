from __future__ import annotations

from quino.analysis.runner import AnalysisResult, AnalysisRunner


class EquilibriumAnalysisRunner(AnalysisRunner):
    def validate(self, project, analysis) -> list[str]:
        return ["Equilibrium analysis is not yet implemented"]

    def run(self, project, analysis, *, initial_pose=None) -> AnalysisResult:
        raise NotImplementedError("Equilibrium analysis is not yet implemented")
