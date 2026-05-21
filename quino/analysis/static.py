from __future__ import annotations

from quino.analysis.runner import AnalysisResult, AnalysisRunner


class StaticAnalysisRunner(AnalysisRunner):
    def validate(self, project, analysis) -> list[str]:
        return ["Static analysis is not yet implemented"]

    def run(self, project, analysis, *, initial_pose=None) -> AnalysisResult:
        raise NotImplementedError("Static analysis is not yet implemented")
